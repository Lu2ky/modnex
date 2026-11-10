import os, sys, tempfile, types, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.features import monitor, notify


def L(hms, msg):
    return f"[09nov2026 {hms}.100] [Server thread/INFO] [net.minecraft.server.MinecraftServer/]: {msg}\n"


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.f = Path(self.tmp.name) / "latest.log"
        self.f.write_text(L("10:00:00", "Vieja joined the game")); self.st = {}

    def tearDown(self):
        self.tmp.cleanup()

    def test_primera_lectura_no_repite_historial(self):
        self.assertEqual(monitor.read_new(self.f, self.st), [])
        self.assertEqual(monitor.player_events(monitor.read_new(self.f, self.st)), [])

    def test_lee_solo_lo_nuevo(self):
        monitor.read_new(self.f, self.st)
        with open(self.f, "a") as fh: fh.write(L("10:05:00", "Ana joined the game") + L("10:06:00", "Ana left the game"))
        self.assertEqual(monitor.player_events(monitor.read_new(self.f, self.st)), [("join", "Ana"), ("leave", "Ana")])
        self.assertEqual(monitor.read_new(self.f, self.st), [], "no se repite")

    def test_linea_a_medias_se_completa_despues(self):
        monitor.read_new(self.f, self.st)
        linea = L("10:05:00", "Ana joined the game")
        with open(self.f, "a") as fh: fh.write(linea[:40])
        self.assertEqual(monitor.read_new(self.f, self.st), [])
        with open(self.f, "a") as fh: fh.write(linea[40:])
        self.assertEqual(monitor.player_events(monitor.read_new(self.f, self.st)), [("join", "Ana")])

    def test_rotacion_del_log(self):
        monitor.read_new(self.f, self.st)
        os.remove(self.f)
        self.f.write_text(L("11:00:00", "Bob joined the game"))
        self.assertEqual(monitor.player_events(monitor.read_new(self.f, self.st)), [("join", "Bob")])

    def test_archivo_recortado(self):
        monitor.read_new(self.f, self.st)
        corta = "[09nov2026 12:00:01.1] [Server thread/INFO]: Cy left the game\n"
        self.assertLess(len(corta), self.st["pos"])
        self.f.write_text(corta)
        ev = monitor.player_events(monitor.read_new(self.f, self.st))
        self.assertIn(("leave", "Cy"), ev)

    def test_archivo_inexistente(self):
        self.assertEqual(monitor.read_new(Path(self.tmp.name) / "no.log", {}), [])

    def test_tick_avisa_solo_de_servidores_en_marcha(self):
        sent = []
        real_send = notify.send
        self.addCleanup(setattr, notify, "send", real_send)
        notify.send = lambda ctx, name, ev, text, force=False: sent.append((name, ev, text)) or True
        srv = Path(self.tmp.name)
        ctx = types.SimpleNamespace(list_servers=lambda: [{"name": "a", "status": {"running": True}}, {"name": "b", "status": {"running": False}}],
                                    server_path=lambda n: srv.parent / n)
        (srv.parent / "a" / "logs").mkdir(parents=True, exist_ok=True)
        log = srv.parent / "a" / "logs" / "latest.log"; log.write_text("")
        states = {}
        monitor.tick(ctx, states)
        with open(log, "a") as fh: fh.write(L("10:00:00", "Ana joined the game"))
        monitor.tick(ctx, states)
        self.assertEqual(sent, [("a", "players", "Ana entró a «a»")])


class TopeDeAvisos(unittest.TestCase):
    def test_tope_por_minuto_y_jugadores_distintos(self):
        import importlib, sqlite3
        importlib.reload(notify)
        self.addCleanup(notify._SENT.clear); self.addCleanup(notify._LAST.clear)
        db = sqlite3.connect(":memory:", check_same_thread=False); db.row_factory = sqlite3.Row; db.executescript(notify.SCHEMA)
        db.execute("INSERT INTO pro_notify VALUES('s', ?, 'players')", ("https://discord.com/api/webhooks/123456789012345678/abcDEFghiJKLmnoPQRstu-_123456",))
        ctx = types.SimpleNamespace(db_run=lambda sql, a=(), one=False, many=False: (db.execute(sql, a).fetchone() if one else db.execute(sql, a).fetchall()))
        n = []; notify._post = lambda u, t: n.append(t) or True
        for i in range(30): notify.send(ctx, "s", "players", f"jugador{i} entró")
        self.assertEqual(len(n), notify.MAX_PER_MINUTE, "tope por minuto")
        self.assertFalse(notify.send(ctx, "s", "players", "jugador0 entró"), "mismo texto repetido en 2 s")


if __name__ == "__main__":
    unittest.main()
