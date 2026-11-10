"""Router de la API y mapa de errores: cada excepción da su código y cada ruta exige lo que declara."""
import sys, unittest, urllib.error
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.web import errors, router
from modnex.web.router import PASS, Reply, Request, dispatch, route, server_action


class ErrorTests(unittest.TestCase):
    def test_codigos(self):
        cases = [(PermissionError("x"), 403), (ValueError("x"), 400), (KeyError("k"), 400), (FileNotFoundError("x"), 404),
                 (LookupError("x"), 404), (RuntimeError("x"), 409), (OSError("x"), 500)]
        for exc, code in cases:
            self.assertEqual(errors.to_response(exc)[0], code, repr(exc))

    def test_el_cuerpo_siempre_lleva_error(self):
        self.assertEqual(errors.to_response(ValueError("mal"))[1], {"error": "mal"})
        self.assertEqual(errors.to_response(OSError("disco"))[1], {"error": "OSError: disco"})

    def test_proveedor_http(self):
        e404 = urllib.error.HTTPError("u", 404, "n", {}, None); e503 = urllib.error.HTTPError("u", 503, "n", {}, None)
        self.assertEqual(errors.to_response(e404)[0], 404); self.assertEqual(errors.to_response(e503)[0], 502)

    def test_http_status_propio_manda(self):
        class Choque(Exception): http_status = 418
        self.assertEqual(errors.to_response(Choque("té")), (418, {"error": "té"}))


class FakeHandler:
    def __init__(self, blocked=False): self.blocked = blocked; self.parsed = 0
    def _cookie(self): return "tok"
    def _admin_remote_blocked(self, user): return self.blocked
    def _body(self): self.parsed += 1; return {"a": 1}


USERS = {"tok": {"id": 1, "username": "u", "is_admin": False}}


def run(method, path, user=None, handler=None):
    h = handler or FakeHandler()
    with mock.patch.object(router.db, "user_for_token", lambda t: user), mock.patch.object(router.db, "can", lambda u, s, p: p == "mods"):
        return dispatch(Request(h, method, path, {}, None)), h


@route("GET", r"/t/publica", auth="public")
def _publica(req): return {"p": 1}
@route("GET", r"/api/t/usuario")
def _usuario(req): return {"u": req.user["username"]}
@route("GET", r"/api/t/admin", auth="admin")
def _admin(req): return {"a": 1}
@route("GET", r"/api/t/pasa")
def _pasa(req): return PASS
@route("GET", r"/api/t/(\d+)")
def _num(req): return {"n": int(req.m.group(1))}
@server_action("GET", "t_lee", perm="mods")
def _lee(req, name): return {"leido": name}
@server_action("POST", "t_admin")
def _escribe(req, name, b): return None
@server_action("POST", "t_sube", perm="mods", raw=True)
def _sube(req, name): return {"sube": name}


class RouterTests(unittest.TestCase):
    def test_publica_no_pide_sesion(self):
        self.assertEqual(run("GET", "/t/publica")[0], {"p": 1})

    def test_api_sin_sesion_da_401(self):
        out, _ = run("GET", "/api/t/usuario")
        self.assertEqual((out.status, out.body["error"]), (401, "no autorizado"))

    def test_con_sesion_pasa_y_ve_al_usuario(self):
        self.assertEqual(run("GET", "/api/t/usuario", USERS["tok"])[0], {"u": "u"})

    def test_admin_rechaza_a_un_usuario_normal(self):
        with self.assertRaises(PermissionError): run("GET", "/api/t/admin", USERS["tok"])
        self.assertEqual(run("GET", "/api/t/admin", {"id": 2, "username": "a", "is_admin": True})[0], {"a": 1})

    def test_administrador_desde_fuera_da_403(self):
        out, _ = run("GET", "/api/t/usuario", {"id": 2, "username": "a", "is_admin": True}, FakeHandler(blocked=True))
        self.assertEqual(out.status, 403)

    def test_pass_sigue_con_la_siguiente_ruta_y_el_patron_es_completo(self):
        self.assertIs(run("GET", "/api/t/pasa", USERS["tok"])[0], PASS)
        self.assertEqual(run("GET", "/api/t/42", USERS["tok"])[0], {"n": 42})
        self.assertIs(run("GET", "/api/t/42x", USERS["tok"])[0], PASS)

    def test_metodo_distinto_no_encaja(self):
        self.assertIs(run("POST", "/api/t/usuario", USERS["tok"])[0], PASS)


class ServerActionTests(unittest.TestCase):
    def setUp(self):
        from modnex.web.routes import servers      # registra la ruta de acciones de servidor
        self.servers = servers

    def call(self, method, action, user=USERS["tok"]):
        with mock.patch.object(self.servers.plugins, "dispatch", lambda *a, **k: None):
            return run(method, f"/api/servers/s1/{action}", user)

    def test_get_con_permiso(self):
        self.assertEqual(self.call("GET", "t_lee")[0], {"leido": "s1"})

    def test_get_accion_desconocida_pasa_a_404_general(self):
        self.assertIs(self.call("GET", "no_existe")[0], PASS)

    def test_post_desconocida_es_404_y_lee_el_cuerpo_antes(self):
        out, h = self.call("POST", "no_existe")
        self.assertEqual((out.status, out.body["error"]), (404, "acción desconocida")); self.assertEqual(h.parsed, 1)

    def test_post_sin_permiso_de_admin_da_403(self):
        with self.assertRaises(PermissionError): self.call("POST", "t_admin")

    def test_post_sin_valor_responde_ok(self):
        self.assertEqual(self.call("POST", "t_admin", {"id": 2, "username": "a", "is_admin": True})[0], {"ok": True})

    def test_subida_en_bruto_no_lee_el_cuerpo(self):
        out, h = self.call("POST", "t_sube")
        self.assertEqual(out, {"sube": "s1"}); self.assertEqual(h.parsed, 0)

    def test_plugin_tiene_prioridad(self):
        with mock.patch.object(self.servers.plugins, "dispatch", lambda *a, **k: (200, {"de": "plugin"})):
            out, _ = run("GET", "/api/servers/s1/t_lee", USERS["tok"])
        self.assertEqual((out.status, out.body), (200, {"de": "plugin"}))


if __name__ == "__main__":
    unittest.main()
