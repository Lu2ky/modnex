from unittest import mock
import base64, os, sqlite3, stat, sys, tempfile, time, types, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from features import remote, security as S

RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()   # secreto de prueba del RFC 6238 (SHA-1)


def make_ctx(users=(("ana", 0), ("root", 1))):
    db = sqlite3.connect(":memory:", check_same_thread=False); db.row_factory = sqlite3.Row
    db.executescript(S.SCHEMA + "CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT, is_admin INTEGER, active INTEGER DEFAULT 1);")
    for i, (n, a) in enumerate(users, 1):
        db.execute("INSERT INTO users(id, username, is_admin) VALUES(?,?,?)", (i, n, a))
    def run(sql, args=(), one=False, many=False):
        cur = db.execute(sql, args)
        return cur.fetchone() if one else cur.fetchall()
    class Conn:
        def __enter__(s): return db
        def __exit__(s, *a): return False
    return types.SimpleNamespace(db_run=run, db_connect=lambda: Conn())


ANA = {"id": 1, "username": "ana", "is_admin": False}


def enable(ctx, user=ANA):
    sec = S.begin(ctx, user)["secret"]
    codes = S.confirm(ctx, user, S.totp(sec))
    return sec, codes


class TotpTests(unittest.TestCase):
    def test_vectores_oficiales_del_rfc_6238(self):
        for t, esperado in ((59, "287082"), (1111111109, "081804"), (1111111111, "050471"), (1234567890, "005924"),
                            (2000000000, "279037"), (20000000000, "353130")):
            self.assertEqual(S.totp(RFC_SECRET, t), esperado, t)

    def test_ventana_de_mas_menos_un_paso(self):
        now = 1_700_000_000
        for delta, ok in ((0, True), (-30, True), (30, True), (-60, False), (60, False)):
            self.assertEqual(S.match_counter(RFC_SECRET, S.totp(RFC_SECRET, now + delta), now=now) is not None, ok, delta)

    def test_formato_de_codigo(self):
        for bad in ("", "12345", "1234567", "abcdef", "12 34 5a", None, "١٢٣٤٥٦"):
            self.assertIsNone(S.match_counter(RFC_SECRET, bad, now=59))
        self.assertIsNotNone(S.match_counter(RFC_SECRET, "287 082", now=59), "se ignoran los espacios")

    def test_no_repite_un_contador(self):
        now = 1_700_000_000; c = S.match_counter(RFC_SECRET, S.totp(RFC_SECRET, now), now=now)
        self.assertIsNone(S.match_counter(RFC_SECRET, S.totp(RFC_SECRET, now), now=now, after=c))

    def test_secretos_distintos_y_largos(self):
        a, b = S.new_secret(), S.new_secret()
        self.assertNotEqual(a, b); self.assertEqual(len(base64.b32decode(a + "=" * (-len(a) % 8))), 20)

    def test_uri_para_apps(self):
        u = S.uri("ABC", "a b&c")
        self.assertTrue(u.startswith("otpauth://totp/Modnex:a%20b%26c?secret=ABC&issuer=Modnex"))


class FlujoTests(unittest.TestCase):
    def setUp(self):
        self.ctx = make_ctx(); S._FAILS.clear()

    def test_activar_y_estado(self):
        self.assertEqual(S.status(self.ctx, 1), {"enabled": False, "pending": False, "recovery_left": 0})
        S.begin(self.ctx, ANA); self.assertTrue(S.status(self.ctx, 1)["pending"])
        sec, codes = enable(self.ctx)
        st = S.status(self.ctx, 1); self.assertEqual((st["enabled"], st["pending"], st["recovery_left"]), (True, False, S.RECOVERY_COUNT))
        self.assertEqual(len(set(codes)), S.RECOVERY_COUNT)

    def test_confirmar_con_codigo_malo(self):
        S.begin(self.ctx, ANA)
        with self.assertRaises(ValueError): S.confirm(self.ctx, ANA, "000000")
        self.assertFalse(S.status(self.ctx, 1)["enabled"])

    def test_no_se_puede_activar_dos_veces(self):
        enable(self.ctx)
        with self.assertRaises(ValueError): S.begin(self.ctx, ANA)

    def test_recuperacion_de_un_solo_uso(self):
        sec, codes = enable(self.ctx)
        self.assertTrue(S.check_code(self.ctx, 1, codes[0].lower())); self.assertFalse(S.check_code(self.ctx, 1, codes[0]))
        self.assertTrue(S.check_code(self.ctx, 1, codes[1].replace("-", "")))
        self.assertEqual(S.status(self.ctx, 1)["recovery_left"], S.RECOVERY_COUNT - 2)

    def test_codigos_de_recuperacion_no_se_guardan_en_claro(self):
        _, codes = enable(self.ctx)
        guardado = " ".join(r["code_hash"] for r in self.ctx.db_run("SELECT code_hash FROM pro_recovery", many=True))
        for c in codes: self.assertNotIn(c.replace("-", ""), guardado.upper())

    def test_un_totp_no_se_puede_reutilizar(self):
        sec, _ = enable(self.ctx)
        # el código de activación ya consumió el contador actual: ese mismo código no vale para entrar
        self.assertFalse(S.check_code(self.ctx, 1, S.totp(sec)))
        self.assertTrue(S.check_code(self.ctx, 1, S.totp(sec, time.time() + 30)))
        self.assertFalse(S.check_code(self.ctx, 1, S.totp(sec, time.time() + 30)), "tampoco se repite el siguiente")

    def test_desactivar_exige_codigo(self):
        sec, codes = enable(self.ctx)
        with self.assertRaises(ValueError): S.disable(self.ctx, ANA, "123456")
        S.disable(self.ctx, ANA, codes[0]); self.assertFalse(S.status(self.ctx, 1)["enabled"])
        self.assertEqual(self.ctx.db_run("SELECT COUNT(*) AS n FROM pro_recovery", one=True)["n"], 0)

    def test_admins_sin_2fa(self):
        self.assertEqual(S.admins_without_2fa(self.ctx), ["root"])
        enable(self.ctx, {"id": 2, "username": "root", "is_admin": True}); self.assertEqual(S.admins_without_2fa(self.ctx), [])

    def test_bloqueo_por_usuario(self):
        enable(self.ctx)
        for _ in range(S.MAX_FAILS): S.register_fail(1)
        self.assertTrue(S.locked(1)); self.assertFalse(S.locked(2))
        self.assertFalse(S.locked(1, now=time.time() + S.LOCK_SECONDS + 1))


class GanchoDeLoginTests(unittest.TestCase):
    def setUp(self):
        self.ctx = make_ctx(); S._FAILS.clear()

    def hook(self, body=None, remote=False):
        return S.login_hook(self.ctx, ANA, body or {}, remote, "1.2.3.4")

    def test_sin_2fa_en_local_pasa(self):
        self.assertIsNone(self.hook())

    def test_sin_2fa_desde_el_tunel_se_rechaza(self):
        r = self.hook(remote=True); self.assertEqual(r[0], 403); self.assertIn("red local", r[1]["error"])

    def test_con_2fa_sin_codigo_pide_el_codigo_sin_contar_fallo(self):
        enable(self.ctx); r = self.hook()
        self.assertEqual(r[0], 401); self.assertTrue(r[1]["need_otp"]); self.assertEqual(len(r), 2, "pedir el código no es un fallo")

    def test_codigo_correcto_pasa_incorrecto_cuenta_fallo(self):
        sec, _ = enable(self.ctx)
        self.assertIsNone(self.hook({"otp": S.totp(sec, time.time() + 30)}))
        r = self.hook({"otp": "000000"}); self.assertEqual(r[0], 401); self.assertTrue(r[2])

    def test_2fa_tambien_se_exige_desde_el_tunel(self):
        sec, _ = enable(self.ctx)
        self.assertEqual(self.hook(remote=True)[0], 401)
        self.assertIsNone(self.hook({"otp": S.totp(sec, time.time() + 30)}, remote=True))

    def test_bloqueo_tras_cinco_codigos_malos_aunque_luego_acierte(self):
        sec, _ = enable(self.ctx)
        for _ in range(S.MAX_FAILS): self.hook({"otp": "000000"})
        r = self.hook({"otp": S.totp(sec, time.time() + 30)})
        self.assertEqual(r[0], 429, "bloqueado: ni el código bueno entra")

    def test_se_puede_entrar_con_recuperacion(self):
        _, codes = enable(self.ctx)
        self.assertIsNone(self.hook({"otp": codes[0]})); self.assertEqual(self.hook({"otp": codes[0]})[0], 401)

    def test_otp_no_es_texto_valido(self):
        enable(self.ctx)
        for bad in ({"otp": None}, {"otp": 123456}, {"otp": ["1"]}, {"otp": {"a": 1}}):
            self.assertEqual(self.hook(bad)[0], 401)


FAKE_TUNNEL = '#!/usr/bin/env bash\necho "2026 INF Requesting new quick Tunnel"\necho "INF |  https://fake-name-123.trycloudflare.com  |"\nsleep 300\n'


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.bin = Path(self.tmp.name) / "cloudflared"
        self.ctx = types.SimpleNamespace(here=self.tmp.name, port=8765, config=lambda: {"cloudflared_path": str(self.bin)})
        remote.stop()

    def tearDown(self):
        remote.stop(); self.tmp.cleanup()

    def script(self, body):
        self.bin.write_text(body); self.bin.chmod(0o755)

    def test_abre_y_cierra_el_tunel(self):
        self.script(FAKE_TUNNEL)
        st = remote.start(self.ctx, timeout=10)
        self.assertTrue(st["active"]); self.assertEqual(st["url"], "https://fake-name-123.trycloudflare.com")
        pid = remote._STATE["proc"].pid
        remote.stop(); self.assertFalse(remote.status(self.ctx)["active"])
        with self.assertRaises(ProcessLookupError): os.kill(pid, 0)

    def test_no_se_abre_dos_veces(self):
        self.script(FAKE_TUNNEL); remote.start(self.ctx, timeout=10)
        with self.assertRaises(remote.RemoteError): remote.start(self.ctx, timeout=10)

    def test_sin_binario(self):
        with mock.patch.object(remote.shutil, "which", lambda x: None):
            with self.assertRaises(remote.RemoteError): remote.start(self.ctx, timeout=1)
            self.assertFalse(remote.status(self.ctx)["available"])

    def test_si_no_hay_url_falla_y_no_deja_procesos(self):
        self.script('#!/usr/bin/env bash\necho "sin url"\nsleep 300\n')
        with self.assertRaises(remote.RemoteError): remote.start(self.ctx, timeout=1.5)
        self.assertIsNone(remote._STATE["proc"]); self.assertFalse(remote.status(self.ctx)["active"])

    def test_solo_urls_de_trycloudflare(self):
        self.assertIsNone(remote.URL_RE.search("https://evil.com/trycloudflare.com"))
        self.assertIsNone(remote.URL_RE.search("https://x.trycloudflare.com.evil.org"), "no vale un dominio que solo empieza igual")
        self.assertEqual(remote.URL_RE.search("a https://ab-c1.trycloudflare.com b").group(0), "https://ab-c1.trycloudflare.com")

    def test_el_tunel_apunta_al_puerto_local(self):
        self.script('#!/usr/bin/env bash\necho "ARGS: $@"\necho "https://p-1.trycloudflare.com"\nsleep 300\n')
        remote.start(self.ctx, timeout=10)
        # el primer argumento es "tunnel" y la URL de origen es el loopback del gestor, nunca otra dirección
        self.assertEqual(remote._STATE["proc"].args[1:5], ["tunnel", "--url", "http://127.0.0.1:8765", "--no-autoupdate"])


if __name__ == "__main__":
    unittest.main()
