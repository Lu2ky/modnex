"""Política de acceso de administradores (vive en el núcleo) y proveedores de túnel."""
import os, sys, tempfile, types, unittest
from pathlib import Path
CORE = Path(__file__).resolve().parent.parent
_tmp = tempfile.mkdtemp(prefix="modnex-policy-")
os.environ.setdefault("MANAGER_DB", str(Path(_tmp) / "db.db"))
os.environ.setdefault("SERVERS_DIR", _tmp)
sys.path.insert(0, str(CORE)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.web import access, server as app
from modnex.features import remote


def req(peer, **headers):
    h = app.Handler.__new__(app.Handler)
    h.client_address = (peer, 5555)
    h.headers = {k.replace("_", "-"): v for k, v in headers.items()}
    class H(dict):
        def get(self, k, d=None):
            for kk, v in self.items():
                if kk.lower() == k.lower(): return v
            return d
    h.headers = H(h.headers)
    return h


ADMIN = {"is_admin": True}; USER = {"is_admin": False}


class OrigenTests(unittest.TestCase):
    def test_local(self):
        for peer, hdr in (("127.0.0.1", {"Host": "127.0.0.1:8765"}), ("::1", {"Host": "localhost:8765"}), ("192.168.1.20", {"Host": "192.168.1.5:8765"}),
                          ("10.166.104.1", {"Host": "10.166.104.28:8765"}), ("100.100.1.1", {}), ("fd00::5", {}), ("::ffff:192.168.1.9", {}),
                          ("127.0.0.1", {"Host": "mi-pc.local:8765"}), ("127.0.0.1", {"Host": "servidor"}), ("127.0.0.1", {"Host": "nas.home.arpa"}), ("127.0.0.1", {"Host": "[::1]:8765"})):
            self.assertFalse(req(peer, **hdr)._remote_origin(), (peer, hdr))

    def test_remoto(self):
        for peer, hdr in (("8.8.8.8", {}), ("2001:4860:4860::8888", {}), ("8.8.4.4", {"Host": "192.168.1.5"}),
                          ("127.0.0.1", {"Cf_Connecting_Ip": "1.2.3.4"}), ("127.0.0.1", {"X_Forwarded_For": "1.2.3.4"}),
                          ("127.0.0.1", {"Host": "abc.trycloudflare.com"}), ("127.0.0.1", {"Host": "x.ngrok-free.app:443"}), ("127.0.0.1", {"Host": "panel.midominio.com"})):
            self.assertTrue(req(peer, **hdr)._remote_origin(), (peer, hdr))

    def test_cabeceras_falsas_desde_la_red_local_no_cambian_el_origen(self):
        # un equipo de la LAN no puede hacerse pasar por el túnel ni esconder su origen: se juzga por su IP real
        self.assertFalse(req("192.168.1.20", Cf_Connecting_Ip="8.8.8.8")._remote_origin())

    def test_admin_bloqueado_solo_cuando_es_remoto(self):
        self.assertTrue(req("127.0.0.1", X_Forwarded_For="8.8.8.8")._admin_remote_blocked(ADMIN))
        self.assertFalse(req("127.0.0.1", X_Forwarded_For="8.8.8.8")._admin_remote_blocked(USER))
        self.assertFalse(req("127.0.0.1")._admin_remote_blocked(ADMIN))
        self.assertFalse(req("127.0.0.1")._admin_remote_blocked(None))

    def test_se_puede_permitir_con_admin_remote_true(self):
        orig = access.load_config
        access.load_config = lambda: {"admin_remote": True}
        try: self.assertFalse(req("8.8.8.8")._admin_remote_blocked(ADMIN))
        finally: access.load_config = orig
        access.load_config = lambda: {"admin_remote": "true"}
        try: self.assertTrue(req("8.8.8.8")._admin_remote_blocked(ADMIN), "solo vale el booleano true")
        finally: access.load_config = orig


class ProveedoresTests(unittest.TestCase):
    def test_urls_de_ngrok(self):
        r = remote.PROVIDERS["ngrok"]["url_re"]
        for ok in ("url=https://ab-12.ngrok-free.app", "https://x.ngrok.io", "https://x.ngrok-free.dev", "https://x.ngrok.app"):
            self.assertTrue(r.search(ok), ok)
        for bad in ("https://evil.com/ngrok.io", "https://x.ngrok.io.evil.org", "http://x.ngrok.io", "https://ngrok.com/docs"):
            self.assertIsNone(r.search(bad), bad)

    def test_proveedor_desconocido(self):
        with self.assertRaises(remote.RemoteError): remote.start(types.SimpleNamespace(config=lambda: {}, here="/x", port=1), provider="../x")


if __name__ == "__main__":
    unittest.main()
