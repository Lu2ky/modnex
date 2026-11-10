import datetime, json, sqlite3, sys, types, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.features import notify, scheduler, backups

GOOD = "https://discord.com/api/webhooks/123456789012345678/abcDEFghiJKLmnoPQRstu-_123456"


def make_ctx():
    db = sqlite3.connect(":memory:", check_same_thread=False); db.row_factory = sqlite3.Row
    db.executescript(notify.SCHEMA + scheduler.SCHEMA)
    def run(sql, args=(), one=False, many=False):
        cur = db.execute(sql, args)
        return cur.fetchone() if one else cur.fetchall()
    class Conn:
        def __enter__(s): return db
        def __exit__(s, *a): return False
    ctx = types.SimpleNamespace(db_run=run, db_connect=lambda: Conn(), sent=[], audits=[],
                                send_command=lambda n, c: ctx.sent.append(c), audit=lambda *a: ctx.audits.append(a),
                                status=lambda n: {"running": True, "control": True},
                                stop=lambda n: ctx.sent.append("STOP"), start=lambda n: ctx.sent.append("START"))
    return ctx


class NotifyTests(unittest.TestCase):
    def setUp(self):
        notify._LAST.clear(); notify._SENT.clear()  # el estado de límites es global al módulo

    def test_urls_validas_e_invalidas(self):
        self.assertTrue(notify.valid_webhook(GOOD))
        for bad in ("http://discord.com/api/webhooks/123456789012345678/abcDEFghiJKLmnoPQRstu-_123456",
                    "https://discord.com.evil.com/api/webhooks/123456789012345678/abcDEFghiJKLmnoPQRstu-_123456",
                    "https://evil.com/https://discord.com/api/webhooks/123456789012345678/abcDEFghiJKLmnoPQRstu",
                    "https://discord.com/api/webhooks/12/corto", "", None, "https://127.0.0.1/api/webhooks/1/2",
                    GOOD + "/../x", GOOD + "?x=1"):
            self.assertFalse(notify.valid_webhook(bad), bad)

    def test_no_devuelve_el_webhook_completo(self):
        ctx = make_ctx(); notify.set_config(ctx, "s", GOOD, ["started"])
        g = notify.get(ctx, "s")
        self.assertTrue(g["configured"]); self.assertNotIn("abcDEFghiJKLmnoPQRstu", json.dumps(g)); self.assertEqual(g["events"], ["started"])

    def test_rechaza_webhook_invalido(self):
        with self.assertRaises(ValueError):
            notify.set_config(make_ctx(), "s", "https://evil.com/x", [])

    def test_envio_sin_menciones_y_solo_eventos_activos(self):
        ctx = make_ctx(); notify.set_config(ctx, "s", GOOD, ["started"])
        posts = []
        notify._post = lambda url, text: posts.append((url, text)) or True
        notify._LAST.clear()
        self.assertTrue(notify.send(ctx, "s", "started", "hola")); self.assertFalse(notify.send(ctx, "s", "crashed", "no"))
        self.assertEqual(len(posts), 1)

    def test_payload_desactiva_menciones(self):
        import importlib
        importlib.reload(notify)  # otras pruebas sustituyen _post; aquí se usa el real
        captured = {}

        class Respuesta:
            status = 204
            def __enter__(self): return self
            def __exit__(self, *a): return False

        notify.urllib.request.urlopen = lambda req, timeout: captured.update(body=json.loads(req.data)) or Respuesta()
        notify._post(GOOD, "@everyone hola")
        self.assertEqual(captured["body"]["allowed_mentions"], {"parse": []})
        self.assertEqual(captured["body"]["content"], "@everyone hola")

    def test_limite_de_frecuencia(self):
        ctx = make_ctx(); notify.set_config(ctx, "s", GOOD, ["started"])
        n = []; notify._post = lambda u, t: n.append(1) or True; notify._LAST.clear()
        notify.send(ctx, "s", "started", "a"); notify.send(ctx, "s", "started", "b")
        self.assertEqual(len(n), 1)

    def test_fallo_de_red_no_propaga(self):
        ctx = make_ctx(); notify.set_config(ctx, "s", GOOD, ["started"]); notify._LAST.clear()
        def boom(*a): raise OSError("sin red")
        notify._post = boom
        self.assertFalse(notify.send(ctx, "s", "started", "x"))


def S(**kw):
    base = {"id": 1, "server": "s", "kind": "backup", "hhmm": "04:00", "days": "*", "keep": 3, "enabled": 1, "last_run": ""}
    base.update(kw); return base


class SchedulerTests(unittest.TestCase):
    def test_due(self):
        t = datetime.datetime(2026, 11, 9, 4, 0, 5)   # lunes
        self.assertTrue(scheduler.is_due(S(), t))
        self.assertFalse(scheduler.is_due(S(hhmm="04:01"), t))
        self.assertFalse(scheduler.is_due(S(last_run="20261109"), t), "una vez al día")
        self.assertFalse(scheduler.is_due(S(enabled=0), t))
        self.assertTrue(scheduler.is_due(S(days="0,3"), t)); self.assertFalse(scheduler.is_due(S(days="1,2"), t))

    def test_avisos_de_reinicio(self):
        r = S(kind="restart", hhmm="04:00")
        self.assertEqual(scheduler.warn_minutes(r, datetime.datetime(2026, 11, 9, 3, 55, 10)), 5)
        self.assertEqual(scheduler.warn_minutes(r, datetime.datetime(2026, 11, 9, 3, 59, 10)), 1)
        self.assertIsNone(scheduler.warn_minutes(r, datetime.datetime(2026, 11, 9, 3, 50, 0)))
        self.assertIsNone(scheduler.warn_minutes(S(kind="backup"), datetime.datetime(2026, 11, 9, 3, 55, 0)))

    def test_reinicio_que_cruza_medianoche(self):
        r = S(kind="restart", hhmm="00:03")
        self.assertEqual(scheduler.warn_minutes(r, datetime.datetime(2026, 11, 9, 23, 58, 0)), 5)

    def test_validacion(self):
        for bad in (("x", "04:00", "*", 3), ("backup", "25:00", "*", 3), ("backup", "4:00", "*", 3),
                    ("backup", "04:00", "7", 3), ("backup", "04:00", "*", 0), ("backup", "04:00", "*", 500)):
            with self.assertRaises(ValueError): scheduler.validate(*bad)
        self.assertEqual(scheduler.validate("restart", "23:59", "0,6", 7), ("restart", "23:59", "0,6", 7))

    def test_alta_baja_y_limite(self):
        ctx = make_ctx()
        sid = scheduler.add(ctx, "s", "backup", "03:30")
        self.assertEqual(len(scheduler.list_schedules(ctx, "s")), 1)
        scheduler.set_enabled(ctx, "s", sid, False); self.assertEqual(scheduler.list_schedules(ctx, "s")[0]["enabled"], 0)
        scheduler.remove(ctx, "s", sid); self.assertEqual(scheduler.list_schedules(ctx, "s"), [])
        for i in range(20): scheduler.add(ctx, "s", "backup", "03:30")
        with self.assertRaises(ValueError): scheduler.add(ctx, "s", "backup", "03:30")

    def test_tick_ejecuta_y_marca(self):
        ctx = make_ctx(); scheduler._warned.clear()
        scheduler.add(ctx, "s", "backup", "04:00")
        ran = []
        scheduler.run_task = lambda c, s: ran.append(s["id"])
        t = datetime.datetime(2026, 11, 9, 4, 0, 3)
        scheduler.tick(ctx, t); import time; time.sleep(0.2)
        scheduler.tick(ctx, t); time.sleep(0.2)
        self.assertEqual(len(ran), 1, "no debe repetirse el mismo día")

    def test_tick_avisa_en_el_juego(self):
        ctx = make_ctx(); scheduler._warned.clear()
        scheduler.add(ctx, "s", "restart", "04:00")
        scheduler.tick(ctx, datetime.datetime(2026, 11, 9, 3, 55, 5)); scheduler.tick(ctx, datetime.datetime(2026, 11, 9, 3, 55, 25))
        self.assertEqual(ctx.sent, ["say Reinicio del servidor en 5 minutos"], "un solo aviso aunque haya varios ticks")


if __name__ == "__main__":
    unittest.main()
