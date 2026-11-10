"""Prueba de extremo a extremo del gestor real, sobre instancias aisladas (puertos 8821/8822).
Uso: python3 tests/e2e_core.py"""
import io, json, os, shutil, zipfile, subprocess, sys, tempfile, time, urllib.error, urllib.request
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent
TOKEN = "token-de-prueba-e2e"
ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print("PASS", name)
    else: fail += 1; print("FAIL", name, extra)


class Client:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())

    def req(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else (b"{}" if method == "POST" else None)
        r = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with self.op.open(r, timeout=60) as resp: return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            try: return e.code, json.loads(e.read())
            except Exception: return e.code, {}

    def upload(self, path, fname, data):
        """Subida en bruto (el cuerpo no es JSON): el nombre va en X-Filename."""
        r = urllib.request.Request(self.base + path, data=data, method="POST", headers={"X-Filename": fname, "Content-Type": "application/octet-stream"})
        try:
            with self.op.open(r, timeout=60) as resp: return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            try: return e.code, json.loads(e.read())
            except Exception: return e.code, {}

    def login(self, user="admin", pw=TOKEN):
        return self.req("POST", "/api/login", {"username": user, "password": pw})[0]


def start_core(port, tmp):
    cfg = tmp / "config.json"
    cfg.write_text(json.dumps({"access_token": TOKEN, "bind": "127.0.0.1"}))
    env = dict(os.environ, MANAGER_PORT=str(port), MANAGER_DB=str(tmp / f"db{port}.db"), SERVERS_DIR=str(tmp / "srv"),
               MODNEX_CONFIG=str(cfg), MODNEX_BACKUP_DIR=str(tmp / "bk"))
    p = subprocess.Popen([sys.executable, "app.py"], cwd=CORE, env=env, stdout=open(tmp / f"core{port}.log", "w"), stderr=subprocess.STDOUT)
    for _ in range(40):
        time.sleep(0.25)
        try: urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1); return p
        except Exception: pass
    raise RuntimeError("el núcleo no arrancó")


FAKE_START = r'''#!/usr/bin/env bash
cd "$(dirname "$0")"
echo "[00:00:01] [Server thread/INFO] [minecraft/DedicatedServer]: Done (1.0s)! For help, type \"help\""
while read -r line; do
  echo "$line" >> received.txt
  case "$line" in
    "save-all flush") echo "[00:00:02] [Server thread/INFO]: Saved the game" ;;
    stop) exit 0 ;;
  esac
done
'''


def main():
    tmp = Path(tempfile.mkdtemp(prefix="modnex-e2e-"))
    srv = tmp / "srv" / "fake"
    (srv / "world").mkdir(parents=True); (srv / "mods").mkdir()
    (srv / "world/level.dat").write_bytes(b"NIVEL-1"); (srv / "mods/a.jar").write_bytes(b"A" * 50)
    (srv / "start.sh").write_text(FAKE_START); (srv / "start.sh").chmod(0o755)
    procs = []
    try:
        free = start_core(8821, tmp); procs.append(free)
        c = Client(8821); check("gratuita: login", c.login() == 200)
        import http.client
        hc = http.client.HTTPConnection("127.0.0.1", 8821, timeout=10); hc.request("GET", "/"); r0 = hc.getresponse(); r0.read()
        check("la landing ya no se sirve desde el gestor: «/» redirige al panel", r0.status == 302 and r0.getheader("Location") == "/app", (r0.status, r0.getheader("Location")))
        for gone in ("/assets/landing.css", "/assets/landing.js", "/assets/shots/panel-mods.png"):
            hc = http.client.HTTPConnection("127.0.0.1", 8821, timeout=10); hc.request("GET", gone); rr = hc.getresponse(); rr.read()
            check(f"{gone} ya no lo sirve el gestor", rr.status == 404, rr.status)
        hc = http.client.HTTPConnection("127.0.0.1", 8821, timeout=10); hc.request("GET", "/app"); ra = hc.getresponse(); body = ra.read().decode()
        check("el panel sigue en /app y no enlaza a la landing", ra.status == 200 and "landing" not in body, ra.status)
        check("gratuita: el núcleo sigue sirviendo", c.req("GET", "/api/servers")[0] == 200)
        st, ex = c.req("GET", "/api/extras")
        check("el asistente ofrece AutoModpack y spark", st == 200 and [e["id"] for e in ex] == ["automodpack", "spark"], ex)
        st, d = c.req("POST", "/api/servers/create", {"template": "neoforge", "mc": "1.21.1", "name": "x-extra", "accept_eula": True, "extras": ["no-existe"]})
        check("un extra desconocido se rechaza al crear", st == 400 and "no-existe" in str(d), (st, d))
        free.terminate(); free.wait(5)

        pro = start_core(8822, tmp); procs.append(pro)
        c = Client(8822); c.login()
        st, d = c.req("POST", "/api/servers/create", {"template": "paper", "mc": "1.21.1", "name": "x-extra", "accept_eula": True, "extras": ["spark"]})
        check("un extra que no vale para el cargador se rechaza", st == 400 and "paper" in str(d).lower(), (st, d))
        s, d = c.req("GET", "/api/plugins")
        check("las pestañas de copias, diagnóstico, avisos, estadísticas y propuestas existen", {"copias", "diagnostico", "avisos", "estadisticas", "propuestas"} <= {t["id"] for t in d["tabs"]}, d)
        s, d = c.req("POST", "/api/servers/fake/backup_create", {"label": "inicial"}); check("crear copia -> 202", s == 202, (s, d))
        for _ in range(40):
            s, d = c.req("GET", "/api/servers/fake/backups")
            if d["job"] and d["job"]["state"] != "running": break
            time.sleep(0.25)
        check("copia creada y listada", len(d["backups"]) == 1 and d["backups"][0]["label"] == "inicial", d)
        bid = d["backups"][0]["id"]
        (srv / "world/level.dat").write_bytes(b"ROTO"); (srv / "mods/b.jar").write_bytes(b"B")
        s, df = c.req("GET", f"/api/servers/fake/backup_diff?a={bid}&b=current")
        check("diff detecta mod añadido", df["added"] == ["b.jar"], df)
        check("restaurar sin confirmar -> 400", c.req("POST", "/api/servers/fake/backup_restore", {"id": bid})[0] == 400)
        s, r = c.req("POST", "/api/servers/fake/backup_restore", {"id": bid, "confirm": "fake"}); check("restaurar -> 200", s == 200, (s, r))
        check("mundo restaurado", (srv / "world/level.dat").read_bytes() == b"NIVEL-1")
        check("mod añadido después desaparece", not (srv / "mods/b.jar").exists())
        s, d = c.req("GET", "/api/servers/fake/backups")
        check("existe copia previa a restaurar", any(b["kind"] == "pre-restore" for b in d["backups"]))
        check("id malicioso rechazado", c.req("POST", "/api/servers/fake/backup_delete", {"id": "../../etc/passwd"})[0] == 409)
        check("arrancar servidor falso", c.req("POST", "/api/servers/fake/start")[0] == 200)
        for _ in range(40):
            if (srv / "manager-console.log").exists() and b"Done (" in (srv / "manager-console.log").read_bytes(): break
            time.sleep(0.25)
        c.req("POST", "/api/servers/fake/backup_create", {"label": "en caliente"})
        for _ in range(60):
            s, d = c.req("GET", "/api/servers/fake/backups")
            if d["job"] and d["job"]["state"] != "running": break
            time.sleep(0.5)
        got = (srv / "received.txt").read_text().split("\n") if (srv / "received.txt").exists() else []
        check("caliente: save-off, save-all flush, save-on en orden", [x for x in got if x][:3] == ["save-off", "save-all flush", "save-on"], got)
        check("caliente: copia marcada como hot", any(b.get("hot") for b in d["backups"]), d["backups"])
        check("restaurar con el servidor en marcha -> 409", c.req("POST", "/api/servers/fake/backup_restore", {"id": bid, "confirm": "fake"})[0] == 409)
        c.req("POST", "/api/servers/fake/stop")
        s, d = c.req("POST", "/api/servers/fake/schedule_add", {"kind": "backup", "hhmm": "04:00", "days": "*", "keep": 3}); check("alta de tarea", s == 200, d)
        check("hora inválida -> 400", c.req("POST", "/api/servers/fake/schedule_add", {"kind": "backup", "hhmm": "99:99"})[0] == 400)
        s, d = c.req("GET", "/api/servers/fake/backups"); check("tarea listada", len(d["schedules"]) == 1)
        check("webhook ajeno -> 400", c.req("POST", "/api/servers/fake/notify_set", {"webhook": "https://evil.com/x"})[0] == 400)
        s, d = c.req("POST", "/api/servers/fake/notify_set", {"webhook": "https://discord.com/api/webhooks/123456789012345678/abcDEFghiJKLmnoPQRstu-_123456", "events": ["crashed"]})
        check("webhook válido guardado y enmascarado", s == 200 and "abcDEFghiJKLm" not in json.dumps(d), d)
        (srv / "manager-console.log").write_text("It requires javaVersion 21 or above, and below 21.999999 but 25.0.4.1 is available\n")
        s, d = c.req("GET", "/api/servers/fake/doctor")
        check("doctor detecta Java incorrecto", any(f["id"] == "java" for f in d["findings"]), d)
        (srv / "logs").mkdir(exist_ok=True)
        (srv / "logs/latest.log").write_text(
            "[09nov2026 10:00:00.100] [Server thread/INFO] [net.minecraft.server.MinecraftServer/]: Ana joined the game\n"
            "[09nov2026 11:30:00.100] [Server thread/INFO] [net.minecraft.server.MinecraftServer/]: Ana left the game\n")
        s, d = c.req("GET", "/api/servers/fake/player_stats")
        check("estadísticas: 1 h 30 de Ana", s == 200 and d["players"][0]["name"] == "Ana" and d["players"][0]["seconds"] == 5400, d)
        s, u = c.req("POST", "/api/users", {"username": "bob", "password": "bobpass123"})
        b = Client(8822); b.login("bob", "bobpass123")
        def jar(*names):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for n in names: z.writestr(n, "x")
            return buf.getvalue()
        up = "/api/servers/fake/mod_upload"
        c.req("POST", f"/api/users/{u['id']}/permissions", {"server": "fake", "mods": True})
        st, d = b.upload(up, "propio.jar", jar("META-INF/neoforge.mods.toml"))
        check("subir un mod propio es solo para administradores, aunque tengas el permiso de mods", st == 403, (st, d))
        st, d = c.upload(up, "propio.jar", jar("META-INF/neoforge.mods.toml"))
        check("el administrador sube un mod propio", st == 200 and d.get("uploaded") == "propio.jar" and (tmp / "srv" / "fake" / "mods" / "propio.jar").is_file(), (st, d))
        st, d = c.upload(up, "propio.jar", jar("META-INF/neoforge.mods.toml"))
        check("no pisa un mod con el mismo nombre", st == 400 and "ya hay" in d.get("error", ""), (st, d))
        st, d = c.upload(up, "fabric.jar", jar("fabric.mod.json"))
        check("un mod de otro cargador se rechaza diciendo cuál es", st == 400 and "Fabric" in d.get("error", ""), (st, d))
        st, d = c.upload(up, "raro.jar", b"no soy un zip")
        check("un archivo que no es un jar se rechaza", st == 400, (st, d))
        st, d = c.upload(up, "../fuera.jar", jar("META-INF/neoforge.mods.toml"))
        check("un nombre con ruta no escapa de la carpeta de mods", (st == 200 and d.get("uploaded") == "fuera.jar") or st == 400, (st, d))
        check("no queda ningún .part en la carpeta de mods", not list((tmp / "srv" / "fake" / "mods").glob("*.part")))
        check("el archivo con ruta no salió de la carpeta del servidor", not (tmp / "srv" / "fuera.jar").exists() and not (tmp / "fuera.jar").exists())
        s2, ms = c.req("GET", "/api/servers/fake/mods")
        check("el mod subido aparece en la lista de mods", s2 == 200 and any(m.get("file") == "propio.jar" for m in ms), (s2, str(ms)[:200]))
        for extra in ("propio.jar", "fuera.jar"): (tmp / "srv" / "fake" / "mods" / extra).unlink(missing_ok=True)   # el servidor de pruebas queda como estaba
        c.req("POST", f"/api/users/{u['id']}/permissions", {"server": "fake", "logs": True})
        check("sin permiso Jugadores: estadísticas -> 403", b.req("GET", "/api/servers/fake/player_stats")[0] == 403)
        c.req("POST", f"/api/users/{u['id']}/permissions", {"server": "fake", "logs": True, "players": True})
        check("con permiso Jugadores: estadísticas -> 200", b.req("GET", "/api/servers/fake/player_stats")[0] == 200)
        c.req("POST", f"/api/users/{u['id']}/permissions", {"server": "fake", "logs": True})
        # actualización segura de mods
        s, d = c.req("GET", "/api/servers/fake/safe_update"); check("actualizar: estado inicial none", s == 200 and d["state"] == "none", d)
        check("aplicar sin probar -> 409", c.req("POST", "/api/servers/fake/safe_update_apply", {"files": ["a.jar"]})[0] == 409)
        check("aplicar con lista inválida -> 400", c.req("POST", "/api/servers/fake/safe_update_apply", {"files": "a.jar"})[0] == 400)
        check("no admin no puede probar -> 403", b.req("POST", "/api/servers/fake/safe_update_start", {})[0] == 403)
        s, d = c.req("POST", "/api/servers/fake/safe_update_start", {}); check("probar con el servidor parado -> 202", s == 202, (s, d))
        for _ in range(120):
            s, d = c.req("GET", "/api/servers/fake/safe_update")
            if d["state"] != "running": break
            time.sleep(0.5)
        check("la prueba termina (sin actualizaciones para jars desconocidos)", d["state"] == "done" and d.get("safe") == [] and "_plan" not in d, d)
        check("el servidor real no cambió", sorted(p.name for p in (srv / "mods").iterdir()) == ["a.jar"])
        check("aplicar algo que no pasó la prueba -> 409", c.req("POST", "/api/servers/fake/safe_update_apply", {"files": ["a.jar"]})[0] == 409)
        # ciclo de vida de las copias
        s, d = c.req("GET", "/api/servers/fake/backups"); bk = d["backups"]
        check("retención: reglas por defecto en la lista de copias", s == 200 and d["retention"]["policy"]["pre_keep"] == 3 and "delete" in d["retention"]["plan"], d.get("retention"))
        s, d = c.req("POST", "/api/servers/fake/retention_preview", {"pre_keep": 1, "max_gb": 0}); check("retención: vista previa", s == 200 and "freed" in d, (s, d))
        check("retención: valor negativo -> 400", c.req("POST", "/api/servers/fake/retention_preview", {"pre_keep": -5})[0] in (400, 409))
        check("retención: clave desconocida -> 400", c.req("POST", "/api/servers/fake/retention_set", {"borrar_todo": 1})[0] in (400, 409))
        check("retención: no admin -> 403", b.req("POST", "/api/servers/fake/retention_set", {"pre_keep": 1})[0] == 403)
        s, d = c.req("POST", "/api/servers/fake/retention_set", {"pre_keep": 2, "pre_days": 30}); check("retención: guardar", s == 200 and d["policy"]["pre_keep"] == 2 and d["policy"]["pre_days"] == 30, (s, d))
        s, d = c.req("GET", "/api/servers/fake/backups"); check("retención: lo guardado persiste", d["retention"]["policy"]["pre_days"] == 30)
        if bk:
            s, d = c.req("POST", "/api/servers/fake/backup_pin", {"id": bk[0]["id"], "pinned": True}); check("fijar una copia", s == 200 and d["pinned"] is True, (s, d))
            s, d = c.req("GET", "/api/servers/fake/backups"); check("la copia aparece fijada", [x for x in d["backups"] if x["id"] == bk[0]["id"]][0].get("pinned") is True)
            check("fijar con valor no booleano -> 400", c.req("POST", "/api/servers/fake/backup_pin", {"id": bk[0]["id"], "pinned": "si"})[0] in (400, 409))
            c.req("POST", "/api/servers/fake/backup_pin", {"id": bk[0]["id"], "pinned": False})
        check("retención: id de copia con ruta -> 400/409", c.req("POST", "/api/servers/fake/backup_pin", {"id": "../x", "pinned": True})[0] in (400, 409))
        s, d = c.req("POST", "/api/servers/fake/retention_apply", {}); check("retención: aplicar nunca deja el servidor sin copias", s == 200 and (not bk or len(c.req("GET", "/api/servers/fake/backups")[1]["backups"]) >= 1), (s, d))
        c.req("POST", "/api/servers/fake/retention_set", {"pre_keep": 3, "pre_days": 14})

        # servidor de pruebas (hijo del real)
        check("pruebas: no admin no puede crear -> 403", b.req("POST", "/api/servers/fake/staging_create", {})[0] == 403)
        s, d = c.req("POST", "/api/servers/fake/staging_create", {}); check("pruebas: crear", s == 200 and d["staging"] == "fake-prueba", (s, d))
        s, d = c.req("GET", "/api/servers"); kids = [x for x in (d if isinstance(d, list) else d.get("servers", [])) if x["name"] == "fake-prueba"]
        check("pruebas: aparece como servidor hijo de fake", bool(kids) and kids[0].get("parent") == "fake", d)
        check("pruebas: sin mundo copiado", not (srv.parent / "fake-prueba" / "world").exists())
        (srv.parent / "fake-prueba" / "config").mkdir(exist_ok=True); (srv.parent / "fake-prueba" / "config" / "t.toml").write_text("v=2\n")
        s, d = c.req("GET", "/api/servers/fake-prueba/staging_diff"); check("pruebas: diff desde el hijo", s == 200 and [x["path"] for x in d["changes"]] == ["config/t.toml"], d)
        s, d = c.req("POST", "/api/servers/fake/staging_merge", {"picks": [{"path": "config/t.toml", "action": "copy"}]}); check("pruebas: fusionar", s == 200 and (srv / "config" / "t.toml").read_text() == "v=2\n", (s, d))
        (srv.parent / "fake-prueba" / "mods" / "nuevo.jar").write_bytes(b"N")
        s, d = c.req("GET", "/api/servers/fake/staging_diff"); check("pruebas: diff de mods", [m["file"] for m in d["mod_changes"]] == ["nuevo.jar"], d)
        s, d = c.req("POST", "/api/servers/fake/staging_merge_mods", {"picks": [{"file": "nuevo.jar", "action": "copy"}]}); check("pruebas: fusionar mods", s == 200 and (srv / "mods" / "nuevo.jar").read_bytes() == b"N", (s, d))
        check("pruebas: mod con ruta peligrosa -> 409", c.req("POST", "/api/servers/fake/staging_merge_mods", {"picks": [{"file": "../a.jar", "action": "copy"}]})[0] == 409)
        check("pruebas: no admin no fusiona mods -> 403", b.req("POST", "/api/servers/fake/staging_merge_mods", {"picks": []})[0] == 403)
        check("pruebas: ruta peligrosa -> 409", c.req("POST", "/api/servers/fake/staging_merge", {"picks": [{"path": "../x", "action": "copy"}]})[0] == 409)
        check("pruebas: borrar", c.req("POST", "/api/servers/fake/staging_delete", {})[0] == 200 and not (srv.parent / "fake-prueba").exists())
        check("pruebas: el real intacto tras borrar", (srv / "mods" / "a.jar").exists())
        # sincronización de clientes (AutoModpack)
        s, d = c.req("GET", "/api/servers/fake/sync"); check("sync: estado inicial", s == 200 and d["state"] == "none" and d["installed"] == [], d)
        check("sync: instalar sin probar -> 409", c.req("POST", "/api/servers/fake/sync_install", {})[0] == 409)
        check("sync: no admin no puede probar -> 403", b.req("POST", "/api/servers/fake/sync_test_start", {})[0] == 403)
        check("sync: no admin no ve el estado -> 403", b.req("GET", "/api/servers/fake/sync")[0] == 403)
        # propuestas de mods
        s, d = b.req("POST", "/api/servers/fake/proposal_create", {"source": "modrinth", "project_id": "AANobbMI", "title": "Sodium", "note": "FPS"})
        check("usuario con permiso propone -> 200", s == 200, (s, d))
        check("duplicado -> 400", b.req("POST", "/api/servers/fake/proposal_create", {"source": "modrinth", "project_id": "AANobbMI", "title": "Sodium"})[0] == 400)
        check("id con caracteres raros -> 400", b.req("POST", "/api/servers/fake/proposal_create", {"source": "modrinth", "project_id": "../x", "title": "x"})[0] == 400)
        s, d = b.req("GET", "/api/servers/fake/proposals")
        pid = d["proposals"][0]["id"]
        check("lista con la propuesta y sin poder decidir", s == 200 and len(d["proposals"]) == 1 and d["can_decide"] is False, d)
        check("usuario normal no decide -> 403", b.req("POST", "/api/servers/fake/proposal_decide", {"id": pid, "decision": "approve"})[0] == 403)
        s, d = c.req("POST", "/api/servers/fake/proposal_decide", {"id": pid, "decision": "approve"}); check("admin aprueba", s == 200 and d["status"] == "approved", d)
        check("decidir otra vez -> 400", c.req("POST", "/api/servers/fake/proposal_decide", {"id": pid, "decision": "reject"})[0] == 400)
        check("retirar una aprobada -> 400", b.req("POST", "/api/servers/fake/proposal_withdraw", {"id": pid})[0] == 400)
        s, nobody = c.req("POST", "/api/users", {"username": "carl", "password": "carlpass123"})
        carl = Client(8822); carl.login("carl", "carlpass123")
        check("usuario sin permisos no ve propuestas -> 403", carl.req("GET", "/api/servers/fake/proposals")[0] == 403)
        s, d = c.req("GET", "/api/servers/fake/metrics"); check("métricas: admin las ve con sus campos", s == 200 and {"running", "players", "warn", "error", "disk_free_gb"} <= set(d), d)
        check("descubrir: etiquetas sin permiso -> 403", carl.req("GET", "/api/tags?kind=mod")[0] == 403)
        check("descubrir: etiqueta de un tipo inventado -> 400", c.req("GET", "/api/tags?kind=virus")[0] in (400, 404))
        check("descubrir: instalados sin permiso -> 403", carl.req("GET", "/api/servers/fake/installed")[0] == 403)
        s, d = c.req("GET", "/api/servers/fake/installed"); check("descubrir: índice de instalados responde", s == 200 and "projects" in d and "versions" in d, (s, d))
        check("métricas: sin permisos -> 403", carl.req("GET", "/api/servers/fake/metrics")[0] == 403)
        check("métricas: usuario con algún permiso -> 200", b.req("GET", "/api/servers/fake/metrics")[0] == 200)
        check("métricas: servidor inexistente -> 404 o 400", c.req("GET", "/api/servers/noexiste/metrics")[0] in (400, 404))
        s, d = c.req("GET", "/api/plugins"); check("plugins: declaran grupos y bloque de riel", any(x.get("group") == "proteger" for x in d["tabs"]) and any(r["id"] == "copias" for r in d.get("rails", [])), d)
        s, d = b.req("GET", "/api/servers/fake/proposal_search?q=sodium")
        check("búsqueda de propuestas: resultados reales (o 502 si no hay red)", (s == 200 and len(d["results"]) > 0 and all(r["project_id"] and r["title"] for r in d["results"])) or s == 502, (s, str(d)[:200]))
        if s == 200: print("     ->", [r["title"] for r in d["results"][:4]])
        check("no admin: backups -> 403", b.req("GET", "/api/servers/fake/backups")[0] == 403)
        check("no admin: crear copia -> 403", b.req("POST", "/api/servers/fake/backup_create", {})[0] == 403)
        check("sin sesión: backups -> 401/403", Client(8822).req("GET", "/api/servers/fake/backups")[0] in (401, 403))
        check("los recursos de las funciones se sirven", urllib.request.urlopen("http://127.0.0.1:8822/plugin/panel.js").status == 200)
        check("servidor inexistente -> 400", c.req("GET", "/api/servers/nada/backups")[0] == 400)
    finally:
        for p in procs:
            try: p.terminate(); p.wait(5)
            except Exception: pass
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{ok} OK, {fail} FALLOS")
    sys.exit(1 if fail else 0)


main()
