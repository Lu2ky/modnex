"""E2E de verificación en dos pasos y acceso remoto sobre un gestor real aislado (puerto 8824)."""
import http.client, json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from features import security as S

CORE = Path(__file__).resolve().parent.parent
TOKEN = "token-de-prueba-e2e"
PORT = 8824
ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print("PASS", name)
    else: fail += 1; print("FAIL", name, extra)


class C:
    def __init__(self, headers=None): self.cookie = None; self.h = headers or {}
    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
        h = {"Content-Type": "application/json", **self.h}
        if self.cookie: h["Cookie"] = self.cookie
        conn.request(method, path, json.dumps(body if body is not None else {}) if method == "POST" else None, h)
        r = conn.getresponse(); raw = r.read(); sc = r.getheader("Set-Cookie")
        if sc and "=" in sc and not sc.split(";")[0].endswith("="): self.cookie = sc.split(";")[0]
        try: d = json.loads(raw or b"{}")
        except Exception: d = {}
        return r.status, d, sc


def main():
    tmp = Path(tempfile.mkdtemp(prefix="modnex-sec-")); (tmp / "srv").mkdir()
    CFG = tmp / "config.json"; CFG.write_text(json.dumps({"access_token": TOKEN, "bind": "127.0.0.1"}))
    fake = tmp / "cloudflared"
    fake.write_text('#!/usr/bin/env bash\necho "https://e2e-test.trycloudflare.com"\nsleep 300\n'); fake.chmod(0o755)
    fake_ngrok = tmp / "ngrok"
    fake_ngrok.write_text('#!/usr/bin/env bash\necho "t=2026 lvl=info msg=\\"started tunnel\\" obj=tunnels name=command_line addr=http://127.0.0.1:8824 url=https://e2e-test.ngrok-free.app"\nsleep 300\n'); fake_ngrok.chmod(0o755)
    env = dict(os.environ, MANAGER_PORT=str(PORT), MANAGER_DB=str(tmp / "db.db"), SERVERS_DIR=str(tmp / "srv"),
               MODNEX_CONFIG=str(CFG), MODNEX_BACKUP_DIR=str(tmp / "bk"), MODNEX_CLOUDFLARED=str(fake), MODNEX_NGROK=str(fake_ngrok))
    p = subprocess.Popen([sys.executable, "app.py"], cwd=CORE, env=env, stdout=open(tmp / "core.log", "w"), stderr=subprocess.STDOUT)
    try:
        for _ in range(40):
            time.sleep(0.25)
            try: C().req("GET", "/api/plugins"); break
            except Exception: pass
        a = C()
        check("login normal sin 2FA", a.req("POST", "/api/login", {"username": "admin", "password": TOKEN})[0] == 200)
        s, d, _ = a.req("GET", "/api/plugins"); check("páginas de plugin listadas", any(x["id"] == "seguridad" for x in d.get("pages", [])), d)
        s, d, _ = a.req("GET", "/api/features/2fa_status"); check("estado inicial: desactivado", s == 200 and not d["enabled"], d)
        s, d, _ = C().req("GET", "/api/features/2fa_status"); check("sin sesión no hay acceso a 2FA", s in (401, 403), s)
        s, d, _ = a.req("POST", "/api/features/2fa_begin"); secret = d["secret"]; check("begin da secreto", s == 200 and len(secret) >= 16)
        check("código malo no activa", a.req("POST", "/api/features/2fa_confirm", {"code": "000000"})[0] == 400)
        s, d, _ = a.req("POST", "/api/features/2fa_confirm", {"code": S.totp(secret)}); codes = d.get("recovery", [])
        check("confirmar activa y da 8 códigos", s == 200 and len(codes) == 8, d)
        # --- login con 2FA ---
        b = C(); s, d, _ = b.req("POST", "/api/login", {"username": "admin", "password": TOKEN})
        check("login sin código pide código", s == 401 and d.get("need_otp") is True, (s, d))
        s, d, sc = b.req("POST", "/api/login", {"username": "admin", "password": TOKEN, "otp": "000000"})
        check("código incorrecto -> 401", s == 401 and "incorrecto" in d.get("error", ""), (s, d))
        s, d, sc = b.req("POST", "/api/login", {"username": "admin", "password": TOKEN, "otp": S.totp(secret, time.time() + 30)})
        check("código correcto entra", s == 200 and sc and "Secure" not in sc, (s, d, sc))
        c = C(); check("código de recuperación entra", c.req("POST", "/api/login", {"username": "admin", "password": TOKEN, "otp": codes[0]})[0] == 200)
        check("recuperación no se reutiliza", C().req("POST", "/api/login", {"username": "admin", "password": TOKEN, "otp": codes[0]})[0] == 401)
        # --- los administradores no entran por el túnel ---
        TUN = {"Cf-Connecting-Ip": "203.0.113.9", "X-Forwarded-Proto": "https"}
        s, d, sc = C(TUN).req("POST", "/api/login", {"username": "admin", "password": TOKEN, "otp": codes[1]})
        check("admin por el túnel: rechazado como contraseña errónea (no se revela nada)", s == 401 and d.get("error") == "usuario o contraseña incorrectos" and not sc, (s, d))
        s, d, _ = C({"X-Forwarded-For": "203.0.113.9"}).req("POST", "/api/login", {"username": "admin", "password": TOKEN, "otp": codes[1]}); check("admin con X-Forwarded-For (ngrok): rechazado", s == 401, (s, d))
        s, d, _ = C({"Host": "algo.trycloudflare.com"}).req("POST", "/api/login", {"username": "admin", "password": TOKEN, "otp": codes[1]}); check("admin con Host de dominio público: rechazado", s == 401, (s, d))
        s, d, _ = C({"Host": "mi-pc.local"}).req("POST", "/api/login", {"username": "admin", "password": TOKEN, "otp": codes[2]}); check("admin con Host .local entra", s == 200, (s, d))
        a2 = C(); a2.req("POST", "/api/login", {"username": "admin", "password": TOKEN, "otp": codes[3]})
        a2.h = dict(TUN); s, d, _ = a2.req("GET", "/api/me"); check("cookie de admin robada y usada por el túnel -> 403", s == 403, (s, d))
        a2.h = {}; check("la misma cookie en local sigue valiendo", a2.req("GET", "/api/me")[0] == 200)
        s, d, _ = a.req("GET", "/api/audit"); check("queda registrado el acceso bloqueado", any("bloqueado" in (x.get("action") or "") for x in (d if isinstance(d, list) else d.get("entries", d.get("audit", [])))), str(d)[:200])
        # --- abrir y cerrar el túnel ---
        s, d, _ = a.req("POST", "/api/features/remote_start", {"provider": "otro"}); check("proveedor desconocido -> 400", s == 400, (s, d))
        s, d, _ = a.req("POST", "/api/features/remote_start"); check("abre el túnel", s == 200 and d.get("url") == "https://e2e-test.trycloudflare.com", (s, d))
        s, d, _ = a.req("GET", "/api/features/remote_status"); check("estado activo", d.get("active") is True and d.get("provider") == "cloudflared", d)
        check("segundo abrir -> 400", a.req("POST", "/api/features/remote_start")[0] == 400)
        s, d, _ = a.req("POST", "/api/features/remote_stop"); check("cierra el túnel", s == 200 and d["active"] is False, d)
        s, d, _ = a.req("POST", "/api/features/remote_start", {"provider": "ngrok"}); check("abre con ngrok simulado", s == 200 and d.get("url") == "https://e2e-test.ngrok-free.app" and d.get("provider") == "ngrok", (s, d))
        a.req("POST", "/api/features/remote_stop")
        # --- usuarios normales por el túnel ---
        s, u, _ = a.req("POST", "/api/users", {"username": "dana", "password": "danapass123"})
        s, d, _ = C().req("POST", "/api/login", {"username": "dana", "password": "danapass123"}); check("dana sin 2FA entra en local", s == 200, (s, d))
        s, d, _ = C(TUN).req("POST", "/api/login", {"username": "dana", "password": "danapass123"})
        check("dana sin 2FA no entra por el túnel (2FA obligatorio)", s == 403, (s, d))
        dn = C(); dn.req("POST", "/api/login", {"username": "dana", "password": "danapass123"})
        s, d, _ = dn.req("POST", "/api/features/2fa_begin"); dsec = d["secret"]; s, d, _ = dn.req("POST", "/api/features/2fa_confirm", {"code": S.totp(dsec)}); dcodes = d["recovery"]
        t2 = C(TUN); s, d, sc = t2.req("POST", "/api/login", {"username": "dana", "password": "danapass123", "otp": dcodes[0]})
        check("dana con 2FA entra por el túnel con cookie Secure", s == 200 and sc and "Secure" in sc, (s, d, sc))
        check("y puede usar el panel por el túnel", t2.req("GET", "/api/me")[0] == 200)
        check("no admin no abre túnel", dn.req("POST", "/api/features/remote_start")[0] == 403)
        check("no admin no restablece 2FA", dn.req("POST", "/api/features/2fa_reset", {"user_id": 1})[0] == 403)
        # --- bloqueo por usuario aunque cambie de IP ---
        for _ in range(5): C({"Cf-Connecting-Ip": f"198.51.100.{_ + 1}"}).req("POST", "/api/login", {"username": "dana", "password": "danapass123", "otp": "111111"})
        s, d, _ = C({"Cf-Connecting-Ip": "198.51.100.99"}).req("POST", "/api/login", {"username": "dana", "password": "danapass123", "otp": S.totp(dsec, time.time() + 60)})
        check("tras 5 códigos malos el usuario queda bloqueado (otra IP también)", s == 429, (s, d))
        # --- las cabeceras de túnel se ignoran si no vienen de loopback: se comprueba en unitarias del núcleo (no hay otra interfaz aquí)
        # --- restablecer ---
        s, d, _ = a.req("GET", "/api/users"); me = [x for x in d if x["username"] == "admin"][0]
        check("admin restablece su 2FA", a.req("POST", "/api/features/2fa_reset", {"user_id": me["id"]})[0] == 200)
        s, d, _ = C().req("POST", "/api/login", {"username": "admin", "password": TOKEN}); check("tras restablecer entra solo con contraseña", s == 200, (s, d))
    finally:
        p.terminate()
        try: p.wait(10)
        except Exception: p.kill()
        subprocess.run(["pkill", "-P", str(p.pid)], check=False) if False else None
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"{ok} OK, {fail} FALLOS"); sys.exit(1 if fail else 0)


main()
