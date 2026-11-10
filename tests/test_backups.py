import io, json, os, sys, tarfile, tempfile, time, types, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from features import backups


def make_ctx(root, running=False, control=False):
    srv = Path(root) / "srv"
    sent = []
    ctx = types.SimpleNamespace(
        here=root, config=lambda: {"backup_dir": str(Path(root) / "bk")},
        server_path=lambda name: srv,
        status=lambda name: {"running": running, "control": control},
        send_command=lambda name, cmd: sent.append(cmd))
    ctx.sent = sent
    return ctx, srv


def fill(srv):
    (srv / "world").mkdir(parents=True); (srv / "world/level.dat").write_bytes(b"NIVEL-1")
    (srv / "mods").mkdir(); (srv / "mods/a.jar").write_bytes(b"A" * 10); (srv / "mods/b.jar").write_bytes(b"B" * 20)
    (srv / "config").mkdir(); (srv / "config/x.toml").write_text("valor=1")
    (srv / "logs").mkdir(); (srv / "logs/latest.log").write_text("log")
    (srv / "libraries").mkdir(); (srv / "libraries/gran.jar").write_bytes(b"L" * 100)
    (srv / "server.properties").write_text("level-name=world")
    (srv / ".manager.json").write_text(json.dumps({"mc": "1.21.1", "loader": "neoforge", "loader_version": "21.1.1"}))


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = self.tmp.name
        self.ctx, self.srv = make_ctx(self.root); fill(self.srv)

    def tearDown(self):
        self.tmp.cleanup()

    def names(self, bid):
        with tarfile.open(Path(self.root) / "bk" / "srv" / f"{bid}.tar.gz") as t:
            return set(t.getnames())

    def test_crea_y_excluye_logs_y_librerias(self):
        m = backups.create(self.ctx, "srv", label="inicial")
        n = self.names(m["id"])
        self.assertIn("world/level.dat", n); self.assertIn("mods/a.jar", n); self.assertIn("config/x.toml", n)
        self.assertFalse(any(x.startswith(("logs", "libraries")) for x in n))
        self.assertEqual(m["minecraft"], "1.21.1"); self.assertEqual(len(m["mods"]), 2)

    def test_restaurar_vuelve_al_estado_anterior(self):
        m = backups.create(self.ctx, "srv")
        (self.srv / "world/level.dat").write_bytes(b"ROTO"); (self.srv / "mods/a.jar").unlink()
        (self.srv / "config/x.toml").write_text("valor=99"); (self.srv / "mods/nuevo.jar").write_bytes(b"N")
        (self.srv / "logs/latest.log").write_text("log nuevo")
        r = backups.restore(self.ctx, "srv", m["id"])
        self.assertEqual((self.srv / "world/level.dat").read_bytes(), b"NIVEL-1")
        self.assertTrue((self.srv / "mods/a.jar").exists())
        self.assertFalse((self.srv / "mods/nuevo.jar").exists(), "los mods añadidos después deben desaparecer")
        self.assertEqual((self.srv / "config/x.toml").read_text(), "valor=1")
        self.assertEqual((self.srv / "logs/latest.log").read_text(), "log nuevo", "los logs no se tocan")
        kinds = [x["kind"] for x in backups.list_backups(self.ctx, "srv")]
        self.assertIn("pre-restore", kinds); self.assertEqual(r["restored"], m["id"])
        self.assertFalse((self.srv / ".restore-tmp").exists())

    def test_restaurar_se_puede_deshacer(self):
        m = backups.create(self.ctx, "srv")
        (self.srv / "world/level.dat").write_bytes(b"NIVEL-2")
        r = backups.restore(self.ctx, "srv", m["id"])
        backups.restore(self.ctx, "srv", r["safety"])
        self.assertEqual((self.srv / "world/level.dat").read_bytes(), b"NIVEL-2")

    def test_no_restaura_con_servidor_en_marcha(self):
        m = backups.create(self.ctx, "srv")
        ctx2, _ = make_ctx(self.root, running=True, control=True)
        with self.assertRaises(backups.BackupError):
            backups.restore(ctx2, "srv", m["id"])

    def test_copia_en_caliente_guarda_y_reactiva(self):
        ctx2, srv = make_ctx(self.root, running=True, control=True)
        backups._wait_saved = lambda *a, **k: True
        m = backups.create(ctx2, "srv")
        self.assertEqual(ctx2.sent, ["save-off", "save-all flush", "save-on"]); self.assertTrue(m["hot"])

    def test_caliente_sin_consola_se_rechaza(self):
        ctx2, _ = make_ctx(self.root, running=True, control=False)
        with self.assertRaises(backups.BackupError):
            backups.create(ctx2, "srv")

    def test_save_on_se_envia_aunque_falle_la_copia(self):
        ctx2, srv = make_ctx(self.root, running=True, control=True)
        backups._wait_saved = lambda *a, **k: True
        orig = backups.tarfile.open
        backups.tarfile.open = lambda *a, **k: (_ for _ in ()).throw(OSError("disco lleno"))
        try:
            with self.assertRaises(OSError):
                backups.create(ctx2, "srv")
        finally:
            backups.tarfile.open = orig
        self.assertEqual(ctx2.sent[-1], "save-on")

    def test_tar_malicioso_no_escapa(self):
        d = Path(self.root) / "bk" / "srv"; d.mkdir(parents=True)
        bid = "20260101-000000-abcd"
        with tarfile.open(d / f"{bid}.tar.gz", "w:gz") as t:
            data = b"mal"; ti = tarfile.TarInfo("../fuera.txt"); ti.size = len(data); t.addfile(ti, io.BytesIO(data))
        (d / f"{bid}.json").write_text(json.dumps({"id": bid, "kind": "manual", "created": 1}))
        with self.assertRaises(Exception):
            backups.restore(self.ctx, "srv", bid)
        self.assertFalse((Path(self.root) / "fuera.txt").exists())
        self.assertFalse((self.srv.parent / "fuera.txt").exists())

    def test_id_invalido(self):
        for bad in ("../x", "", "20260101-000000-zzzz", "a/b"):
            with self.assertRaises(backups.BackupError):
                backups.delete(self.ctx, "srv", bad)

    def test_prune_conserva_las_recientes(self):
        ids = []
        for i in range(4):
            ids.append(backups.create(self.ctx, "srv", kind="auto")["id"]); time.sleep(1.1)
        backups.create(self.ctx, "srv", kind="manual")
        borradas = backups.prune(self.ctx, "srv", keep=2, kind="auto")
        left = backups.list_backups(self.ctx, "srv")
        self.assertEqual(borradas, 2)
        self.assertEqual(sum(1 for m in left if m["kind"] == "auto"), 2)
        self.assertEqual(sum(1 for m in left if m["kind"] == "manual"), 1)

    def test_diff_de_mods(self):
        m = backups.create(self.ctx, "srv")
        (self.srv / "mods/a.jar").unlink(); (self.srv / "mods/c.jar").write_bytes(b"C"); (self.srv / "mods/b.jar").write_bytes(b"BBBB")
        d = backups.diff(self.ctx, "srv", m["id"], "current")
        self.assertEqual(d["added"], ["c.jar"]); self.assertEqual(d["removed"], ["a.jar"]); self.assertEqual(d["changed"], ["b.jar"])

    def test_sin_espacio(self):
        orig = backups.shutil.disk_usage
        backups.shutil.disk_usage = lambda p: types.SimpleNamespace(free=1)
        try:
            with self.assertRaises(backups.BackupError):
                backups.create(self.ctx, "srv")
        finally:
            backups.shutil.disk_usage = orig

    def test_no_se_siguen_enlaces_simbolicos(self):
        (self.srv / "enlace").symlink_to("/etc")
        m = backups.create(self.ctx, "srv")
        self.assertFalse(any(x.startswith("enlace") for x in self.names(m["id"])))


if __name__ == "__main__":
    unittest.main()
