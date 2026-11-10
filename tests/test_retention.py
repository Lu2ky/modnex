import json, os, sqlite3, sys, tempfile, threading, time, types, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from features import backups, retention as R, scheduler

NOW = 1_800_000_000
DAY = 86400
MB = 2 ** 20


class Base(unittest.TestCase):
    def setUp(self):
        os.environ.pop("MODNEX_BACKUP_DIR", None)
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        db = sqlite3.connect(":memory:", check_same_thread=False); db.row_factory = sqlite3.Row
        db.executescript(R.SCHEMA + scheduler.SCHEMA)
        class Conn:
            def __enter__(s): return db
            def __exit__(s, *a): return False
        self.audits, self.sent = [], []
        self.ctx = types.SimpleNamespace(
            here=str(self.root), config=lambda: {"backup_dir": str(self.root / "bk")},
            db_run=lambda sql, args=(), one=False, many=False: (db.execute(sql, args).fetchone() if one else db.execute(sql, args).fetchall()),
            db_connect=lambda: Conn(), audit=lambda *a: self.audits.append(a), list_servers=lambda: [{"name": "s"}])
        self.db = db
        self.pn = mock.patch.object(R.notify, "send", lambda ctx, name, ev, msg: self.sent.append((name, ev, msg))); self.pn.start()
        self.n = 0

    def tearDown(self):
        self.pn.stop(); self.tmp.cleanup()

    def make(self, kind, age_days, size_mb=10, pinned=False, name="s"):
        """Crea en disco una copia de `age_days` días de antigüedad (más reciente = menor edad)."""
        self.n += 1
        created = NOW - int(age_days * DAY)
        bid = time.strftime("%Y%m%d-%H%M%S", time.gmtime(created)) + "-%04x" % self.n
        d = backups.backup_dir(self.ctx, name)
        (d / f"{bid}.tar.gz").write_bytes(b"x")
        meta = {"id": bid, "created": created, "kind": kind, "size": size_mb * MB, "label": kind, "pinned": pinned}
        (d / f"{bid}.json").write_text(json.dumps(meta))
        return bid

    def ids(self, p): return {d["id"] for d in p["delete"]}


class PlanTests(Base):
    def test_seguridad_previa_conserva_las_ultimas_3(self):
        ids = [self.make("pre-update", a) for a in (1, 2, 3, 4, 5)]
        p = R.plan(self.ctx, "s", now=NOW)
        self.assertEqual(self.ids(p), set(ids[3:]), "las dos más antiguas")
        self.assertTrue(all("más de 3" in d["reason"] for d in p["delete"]))

    def test_seguridad_previa_por_edad(self):
        old = self.make("pre-update", 20); new = self.make("pre-restore", 1)
        self.assertEqual(self.ids(R.plan(self.ctx, "s", now=NOW)), {old})
        self.assertEqual(self.ids(R.plan(self.ctx, "s", {"pre_days": 0}, now=NOW)), set(), "0 = sin límite de edad")

    def test_la_mas_reciente_nunca_se_borra_aunque_sea_vieja(self):
        only = self.make("pre-update", 400)
        p = R.plan(self.ctx, "s", {"pre_days": 1, "pre_keep": 1, "max_gb": 1, "min_free_gb": 100000}, now=NOW, free=0)
        self.assertEqual(p["delete"], []); self.assertEqual(p["kept"], 1)

    def test_siempre_queda_al_menos_una(self):
        for a in (30, 40, 50): self.make("auto", a)
        p = R.plan(self.ctx, "s", {"auto_keep": 1, "max_gb": 1, "min_free_gb": 100000}, now=NOW, free=0)
        self.assertEqual(p["kept"], 1)

    def test_las_fijadas_no_se_borran_ni_cuentan(self):
        pinned = self.make("pre-update", 50, pinned=True)
        keep3 = [self.make("pre-update", a) for a in (1, 2, 3)]
        old = self.make("pre-update", 4)
        p = R.plan(self.ctx, "s", now=NOW)
        self.assertNotIn(pinned, self.ids(p)); self.assertEqual(self.ids(p), {old}, "la fijada no ocupa uno de los 3 cupos")

    def test_manuales_intactas_por_defecto_y_por_edad_si_se_pide(self):
        m = self.make("manual", 300); self.make("manual", 1)
        self.assertEqual(self.ids(R.plan(self.ctx, "s", now=NOW)), set())
        self.assertEqual(self.ids(R.plan(self.ctx, "s", {"manual_days": 90}, now=NOW)), {m})

    def test_automaticas_usan_el_menor_conservar_de_las_tareas(self):
        a = [self.make("auto", x) for x in (1, 2, 3, 4)]
        self.db.execute("INSERT INTO pro_schedules(server, kind, hhmm, days, keep) VALUES('s','backup','04:00','*',2)"); self.db.execute("INSERT INTO pro_schedules(server, kind, hhmm, days, keep) VALUES('s','backup','05:00','*',3)")
        self.assertEqual(self.ids(R.plan(self.ctx, "s", now=NOW)), set(a[2:]))

    def test_automaticas_sin_tarea_usan_la_regla(self):
        a = [self.make("auto", x) for x in range(1, 6)]
        self.assertEqual(self.ids(R.plan(self.ctx, "s", {"auto_keep": 2}, now=NOW)), set(a[2:]))

    def test_limite_de_espacio_borra_las_mas_antiguas(self):
        a = [self.make("manual", x, size_mb=600) for x in (1, 2, 3, 4)]      # 2400 MB
        p = R.plan(self.ctx, "s", {"max_gb": 1}, now=NOW)
        self.assertEqual(self.ids(p), set(a[1:]), "solo queda la más reciente (600 MB ≤ 1 GB)")
        self.assertTrue(all("límite de 1 GB" in d["reason"] for d in p["delete"]))

    def test_limite_imposible_se_avisa_y_no_toca_lo_protegido(self):
        newest = self.make("manual", 1, size_mb=3000); pinned = self.make("manual", 5, size_mb=3000, pinned=True)
        p = R.plan(self.ctx, "s", {"max_gb": 1}, now=NOW)
        self.assertEqual(p["delete"], []); self.assertTrue(p["unmet"])

    def test_disco_libre_minimo(self):
        a = [self.make("manual", x, size_mb=1024) for x in (1, 2, 3)]
        p = R.plan(self.ctx, "s", {"min_free_gb": 3}, now=NOW, free=1 * 2 ** 30)   # hay 1 GB, hacen falta 3: liberar 2 GB
        self.assertEqual(self.ids(p), set(a[1:])); self.assertEqual(p["freed"], 2048 * MB)

    def test_reglas_combinadas_no_cuentan_dos_veces_lo_mismo(self):
        old = self.make("pre-update", 30, size_mb=2048); new = self.make("pre-update", 1, size_mb=2048)
        p = R.plan(self.ctx, "s", {"max_gb": 3}, now=NOW)
        self.assertEqual(self.ids(p), {old}); self.assertEqual(len(p["delete"]), 1)

    def test_sin_copias(self):
        self.assertEqual(R.plan(self.ctx, "s", now=NOW)["delete"], [])


class ValidacionTests(Base):
    def test_rechaza_valores_malos(self):
        for bad in ({"pre_keep": -1}, {"pre_keep": 1.5}, {"pre_keep": "3"}, {"pre_keep": True}, {"auto_keep": 0}, {"pre_days": 99999}, {"otra": 1}, [], None, {"max_gb": None}):
            with self.assertRaises(R.RetentionError, msg=str(bad)): R.validate(bad)

    def test_guardar_y_leer(self):
        self.assertEqual(R.get(self.ctx, "s"), R.DEFAULTS)
        R.save(self.ctx, "s", {"pre_keep": 5, "max_gb": 40}); p = R.get(self.ctx, "s")
        self.assertEqual((p["pre_keep"], p["max_gb"], p["pre_days"]), (5, 40, 14))
        R.save(self.ctx, "s", {"pre_keep": 2}); self.assertEqual(R.get(self.ctx, "s")["max_gb"], 40, "guardar parcial no pisa lo demás")
        with self.assertRaises(R.RetentionError): R.save(self.ctx, "s", {"pre_keep": 99})

    def test_las_reglas_son_por_servidor(self):
        R.save(self.ctx, "a", {"pre_keep": 9}); self.assertEqual(R.get(self.ctx, "b")["pre_keep"], 3)


class ApplyTests(Base):
    def test_lo_que_se_borra_es_exactamente_lo_previsto(self):
        for a in (1, 2, 3, 4, 5): self.make("pre-update", a)
        pl = R.plan(self.ctx, "s", now=NOW); res = R.apply(self.ctx, "s", now=NOW)
        self.assertEqual({d["id"] for d in res["deleted"]}, self.ids(pl))
        left = {m["id"] for m in backups.list_backups(self.ctx, "s")}
        self.assertEqual(len(left), 3); self.assertFalse(left & self.ids(pl))
        d = backups.backup_dir(self.ctx, "s")
        for i in self.ids(pl): self.assertFalse((d / f"{i}.tar.gz").exists() or (d / f"{i}.json").exists())

    def test_deja_rastro_en_auditoria_y_avisa(self):
        for a in (1, 2, 3, 4): self.make("pre-update", a)
        R.apply(self.ctx, "s", now=NOW)
        self.assertTrue(any("retención" in str(a) for a in self.audits)); self.assertTrue(self.sent and "1 copias" in self.sent[0][2])

    def test_si_hay_una_copia_en_curso_no_borra(self):
        for a in (1, 2, 3, 4): self.make("pre-update", a)
        lk = backups._lock("s"); lk.acquire()
        try: r = R.apply(self.ctx, "s", now=NOW)
        finally: lk.release()
        self.assertIn("skipped", r); self.assertEqual(len(backups.list_backups(self.ctx, "s")), 4)

    def test_aplicar_sin_nada_que_borrar_no_molesta(self):
        self.make("pre-update", 1); R.apply(self.ctx, "s", now=NOW); self.assertEqual((self.audits, self.sent), ([], []))

    def test_pin_y_unpin(self):
        a = self.make("pre-update", 50); self.make("pre-update", 1)
        backups.set_pinned(self.ctx, "s", a, True)
        self.assertEqual(R.plan(self.ctx, "s", now=NOW)["delete"], [])
        backups.set_pinned(self.ctx, "s", a, False)
        self.assertEqual(self.ids(R.plan(self.ctx, "s", now=NOW)), {a})
        with self.assertRaises(backups.BackupError): backups.set_pinned(self.ctx, "s", "../x", True)

    def test_prune_del_programador_respeta_las_fijadas(self):
        keep = [self.make("auto", x) for x in (1, 2)]; pin = self.make("auto", 9, pinned=True); old = self.make("auto", 10)
        backups.prune(self.ctx, "s", 2, kind="auto")
        left = {m["id"] for m in backups.list_backups(self.ctx, "s")}
        self.assertEqual(left, set(keep) | {pin})

    def test_se_ejecuta_sola_al_terminar_cada_copia(self):
        for a in (2, 3, 4, 5): self.make("pre-update", a)
        meta = {"id": "x"}
        with mock.patch.object(backups, "_create", lambda *a, **k: meta), mock.patch.object(backups, "AFTER_CREATE", [R.after_create]):
            self.assertIs(backups.create(self.ctx, "s", kind="pre-update"), meta)
        self.assertEqual(len(backups.list_backups(self.ctx, "s")), 3)

    def test_unas_reglas_rotas_no_hacen_fallar_la_copia(self):
        meta = {"id": "x"}
        def boom(*a): raise RuntimeError("fallo")
        with mock.patch.object(backups, "_create", lambda *a, **k: meta), mock.patch.object(backups, "AFTER_CREATE", [boom]):
            self.assertIs(backups.create(self.ctx, "s"), meta)

    def test_pasada_diaria_una_vez_al_dia_y_no_de_madrugada(self):
        import datetime
        for a in (1, 2, 3, 4, 5): self.make("pre-update", a)
        R._DAILY.clear()
        R.daily(self.ctx, datetime.datetime(2027, 1, 1, 2, 0)); self.assertEqual(len(backups.list_backups(self.ctx, "s")), 5, "antes de las 3 no actúa")
        with mock.patch.object(R, "plan", wraps=R.plan) as pl:
            R.daily(self.ctx, datetime.datetime(2027, 1, 1, 3, 30)); R.daily(self.ctx, datetime.datetime(2027, 1, 1, 15, 0))
            self.assertEqual(pl.call_count, 1, "solo una vez ese día")


if __name__ == "__main__":
    unittest.main()
