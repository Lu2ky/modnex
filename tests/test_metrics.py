"""Métricas en vivo del núcleo para el riel de estado: jugadores según el registro, sin enviar comandos."""
import os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
CORE = Path(__file__).resolve().parent.parent
_tmp = tempfile.mkdtemp(prefix="modnex-metrics-")
os.environ.setdefault("MANAGER_DB", str(Path(_tmp) / "db.db")); os.environ.setdefault("SERVERS_DIR", _tmp)
sys.path.insert(0, str(CORE))
import app


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.d = Path(_tmp) / "srv"; self.d.mkdir(exist_ok=True)
        (self.d / "server.properties").write_text("max-players=12\n")
        self.running = True; self.log = ""
        self.pa = [mock.patch.object(app, "server_path", lambda n: self.d),
                   mock.patch.object(app, "status", lambda n: {"running": self.running, "pid": os.getpid() if self.running else None, "control": False}),
                   mock.patch.object(app, "read_log", lambda n, lines=200: self.log)]
        for p in self.pa: p.start()

    def tearDown(self):
        for p in self.pa: p.stop()

    def test_jugadores_segun_el_registro(self):
        self.log = ("[10:00:00] [Server thread/INFO]: Starting minecraft server version 1.21.1\n"
                    "[10:01:00] [Server thread/INFO] [minecraft/MinecraftServer]: Ana joined the game\n"
                    "[10:02:00] [Server thread/INFO] [minecraft/MinecraftServer]: Beto joined the game\n"
                    "[10:03:00] [Server thread/INFO] [minecraft/MinecraftServer]: Ana left the game\n")
        m = app.live_metrics("x")
        self.assertEqual(m["players"], ["Beto"]); self.assertEqual(m["max_players"], 12)

    def test_un_reinicio_vacia_la_lista(self):
        self.log = ("[1] ]: Ana joined the game\n[2] Starting minecraft server version 1.21.1\n")
        self.assertEqual(app.live_metrics("x")["players"], [])

    def test_servidor_parado_no_tiene_jugadores(self):
        self.running = False; self.log = "[1] ]: Ana joined the game\n"
        m = app.live_metrics("x"); self.assertEqual(m["players"], []); self.assertFalse(m["running"]); self.assertIsNone(m["rss_mb"])

    def test_memoria_y_actividad_del_proceso(self):
        m = app.live_metrics("x")
        self.assertGreater(m["rss_mb"], 0); self.assertGreaterEqual(m["uptime_s"], 0)

    def test_cuenta_avisos_y_errores_y_disco(self):
        self.log = "a WARN b\nc WARN d\ne ERROR f\nException in thread\n"
        m = app.live_metrics("x"); self.assertEqual((m["warn"], m["error"]), (2, 1)); self.assertGreater(m["disk_free_gb"], 0)

    def test_nombres_raros_no_se_cuelan(self):
        self.log = "]: <script>alert(1)</script> joined the game\n]: Aaaaaaaaaaaaaaaaaaaaa joined the game\n"
        self.assertEqual(app.live_metrics("x")["players"], [])


if __name__ == "__main__":
    unittest.main()
