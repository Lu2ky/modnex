"""Túneles de playit por servidor: lectura de la clave, forma de la petición, sin duplicados y errores sin secretos."""
import io, json, sys, tempfile, unittest, urllib.error
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.services import playit as P

KEY = "agentkey-SECRETO-1234567890"


class PlayitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.toml = self.tmp / "playit.toml"
        self.toml.write_text(f'secret_key = "{KEY}"\n'); self.srv = self.tmp / "srv"; self.srv.mkdir()

    def test_lee_la_clave_y_sin_archivo_es_none(self):
        self.assertEqual(P.read_key(self.toml), KEY)
        self.assertIsNone(P.read_key(self.tmp / "no-existe.toml"))
        (self.tmp / "vacio.toml").write_text("otra = 1\n"); self.assertIsNone(P.read_key(self.tmp / "vacio.toml"))

    def test_sin_clave_no_crea_nada(self):
        self.assertIsNone(P.ensure_tunnel(self.srv, "cobble", 25565, key_path=self.tmp / "no.toml"))
        self.assertFalse((self.srv / P.RECORD).exists())

    def test_crea_el_tunel_con_la_forma_del_crate_y_lo_guarda(self):
        calls = []
        def fake(path, body, key, timeout=20):
            calls.append((path, body, key))
            if path == "/agents/rundata": return {"agent_id": "a-1"}
            return {"id": "t-9"}
        with mock.patch.object(P, "_post", fake):
            rec = P.ensure_tunnel(self.srv, "cobble", 25566, key_path=self.toml)
        self.assertEqual(rec, {"tunnel_id": "t-9", "local_port": 25566})
        path, body, key = calls[-1]
        self.assertEqual(path, "/tunnels/create"); self.assertEqual(key, KEY)
        self.assertEqual(body["tunnel_type"], "minecraft-java"); self.assertEqual(body["port_type"], "tcp")
        self.assertEqual(body["origin"], {"type": "agent", "data": {"agent_id": "a-1", "local_ip": "127.0.0.1", "local_port": 25566}})
        self.assertTrue(body["enabled"]); self.assertEqual(body["name"], "Minecraft cobble")

    def test_no_duplica_el_tunel(self):
        (self.srv / P.RECORD).write_text(json.dumps({"tunnel_id": "t-1", "local_port": 25565}))
        with mock.patch.object(P, "_post", side_effect=AssertionError("no debía llamar a la API")):
            self.assertEqual(P.ensure_tunnel(self.srv, "cobble", 25565, key_path=self.toml)["tunnel_id"], "t-1")

    def test_un_error_de_playit_se_guarda_y_no_lanza(self):
        with mock.patch.object(P, "_post", side_effect=P.PlayitError("playit respondió 400: validation")):
            rec = P.ensure_tunnel(self.srv, "cobble", 25565, key_path=self.toml)
        self.assertIn("error", rec); self.assertNotIn("tunnel_id", rec)
        self.assertNotIn(KEY, json.dumps(rec))

    def test_los_errores_de_red_no_muestran_la_clave(self):
        def boom(req, timeout=20):
            raise urllib.error.HTTPError(req.full_url, 401, "no", {}, io.BytesIO(b'{"status":"error","data":{"message":"bad key"}}'))
        with mock.patch("urllib.request.urlopen", boom):
            with self.assertRaises(P.PlayitError) as cm:
                P.rundata(KEY)
        self.assertIn("401", str(cm.exception)); self.assertNotIn(KEY, str(cm.exception))

    def test_direccion_publica_del_tunel(self):
        (self.srv / P.RECORD).write_text(json.dumps({"tunnel_id": "t-1", "local_port": 25565}))
        tun = [{"id": "t-1", "assigned_domain": "abc.tun.ply.gg", "port": {"from": 49870, "to": 49871}}]
        with mock.patch.object(P, "_post", lambda path, body, key, timeout=20: {"agent_id": "a", "tunnels": tun}):
            self.assertEqual(P.address(self.srv, key_path=self.toml), "abc.tun.ply.gg:49870")
        with mock.patch.object(P, "_post", side_effect=P.PlayitError("x")):
            self.assertIsNone(P.address(self.srv, key_path=self.toml))


if __name__ == "__main__":
    unittest.main()
