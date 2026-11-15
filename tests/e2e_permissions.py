"""E2E de los permisos delegables sobre un gestor real aislado (puerto 8826): cada permiso abre solo lo suyo."""
import http.client, json, os, subprocess, sys, tempfile, time
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent
TOKEN = "token-de-prueba-permisos"
PORT = 8826
ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print("PASS", name)
    else: fail += 1; print("FAIL", name, extra)


class C:
    def __init__(self): self.cookie = None
    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
        h = {"Content-Type": "application/json"}
        if self.cookie: h["Cookie"] = self.cookie
        conn.request(method, path, json.dumps(body if body is not None else {}) if method == "POST" else None, h)
        r = conn.getresponse(); raw = r.read(); sc = r.getheader("Set-Cookie")
        if sc and "=" in sc and not sc.split(";")[0].endswith("="): self.cookie = sc.split(";")[0]
        try: d = json.loads(raw or b"{}")
        except Exception: d = {}
        return r.status, d


# permiso -> rutas GET que abre (todas de solo lectura)
OPENS = {
    "backups": ["backups"], "recipes": ["kubejs_state", "kubejs_rules", "kubejs_loot", "kubejs_history"], "properties": ["properties"],
    "perf": ["performance"], "distribution": ["sync", "automodpack", "client_plan", "releases"], "diagnostics": ["doctor"],
}
ADMIN_ONLY_GET = ["kubejs_scripts", "notify", "staging"]
ADMIN_ONLY_POST = ["backup_delete", "retention_set", "sync_install", "automodpack_fix", "kubejs_script_save", "delete", "command", "memory"]


def main():
    tmp = Path(tempfile.mkdtemp(prefix="modnex-perm-"))
    s = tmp / "srv" / "cobble"; (s / "mods").mkdir(parents=True); (s / "kubejs/server_scripts").mkdir(parents=True)
    (s / "mods/kubejs-neoforge-2101.7.2-build.381.jar").write_bytes(b"x"); (s / "start.sh").write_text("#!/bin/sh\nsleep 1\n"); (s / "server.properties").write_text("server-port=25570\n")
    (tmp / "c.json").write_text(json.dumps({"access_token": TOKEN, "bind": "127.0.0.1"}))
    env = dict(os.environ, MODNEX_PLAYIT_SECRET="/nonexistent/playit.toml", MANAGER_PORT=str(PORT), MANAGER_DB=str(tmp / "db.db"), SERVERS_DIR=str(tmp / "srv"), MODNEX_CONFIG=str(tmp / "c.json"), MODNEX_BACKUP_DIR=str(tmp / "bk"))
    p = subprocess.Popen([sys.executable, "app.py"], cwd=CORE, env=env, stdout=open(tmp / "core.log", "w"), stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            time.sleep(0.25)
            try: C().req("GET", "/api/plugins"); break
            except Exception: pass
        a = C(); check("login de admin", a.req("POST", "/api/login", {"username": "admin", "password": TOKEN})[0] == 200)
        st, d = a.req("POST", "/api/users", {"username": "ayudante", "password": "clave-larga-de-prueba-1"}); uid = d.get("id")
        check("usuario sin privilegios creado", st == 200 and uid, d)
        u = C(); check("login del ayudante", u.req("POST", "/api/login", {"username": "ayudante", "password": "clave-larga-de-prueba-1"})[0] == 200)
        base = "/api/servers/cobble/"
        every = [r for rs in OPENS.values() for r in rs]
        check("sin permisos no entra a nada", all(u.req("GET", base + r)[0] in (403, 404) for r in every), [(r, u.req("GET", base + r)[0]) for r in every])
        check("sin permisos tampoco ve la dirección pública", u.req("GET", base + "address")[0] in (403, 404))
        for perm, routes in OPENS.items():
            st, _ = a.req("POST", f"/api/users/{uid}/permissions", {"permissions": {"cobble": {perm: True}}})
            got = {r: u.req("GET", base + r)[0] for r in every}
            check(f"«{perm}» abre lo suyo", st == 200 and all(got[r] == 200 for r in routes), got)
            check(f"«{perm}» no abre lo de otros permisos", all(got[r] == 403 for r in every if r not in routes), got)
            check(f"«{perm}» no da acceso a lo de administradores", all(u.req("GET", base + r)[0] == 403 for r in ADMIN_ONLY_GET) and all(u.req("POST", base + r, {})[0] == 403 for r in ADMIN_ONLY_POST))
        a.req("POST", f"/api/users/{uid}/permissions", {"permissions": {"cobble": {k: True for k in OPENS}}})
        check("con los seis nuevos sigue sin poder lo de administradores", all(u.req("POST", base + r, {})[0] == 403 for r in ADMIN_ONLY_POST))
        st, d = u.req("GET", base + "address")
        check("con algún permiso puede ver la dirección para jugadores (vacía si no hay túnel)", st == 200 and "address" in d, (st, d))
        st, d = u.req("GET", "/api/servers"); me = next((x for x in d if x["name"] == "cobble"), None) if isinstance(d, list) else None
        check("la lista de servidores le dice sus permisos", bool(me) and all(me["permissions"].get(k) for k in OPENS) and not me["permissions"].get("control"), d if not me else me["permissions"])
        st, d = a.req("GET", "/api/servers"); me = next((x for x in d if x["name"] == "cobble"), None) if isinstance(d, list) else None
        check("el admin los tiene todos", bool(me) and all(me["permissions"].values()))
    finally:
        p.terminate()
    print(f"\n{ok} OK, {fail} FALLOS"); sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
