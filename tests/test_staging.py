import json, sqlite3, sys, tempfile, types, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from features import staging as S


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        r = self.root / "srv" / "main"; self.real = r
        (r / "mods").mkdir(parents=True); (r / "config" / "sub").mkdir(parents=True); (r / "libraries").mkdir(); (r / "world").mkdir()
        (r / "world" / "level.dat").write_bytes(b"MUNDO-REAL")
        for n in ("a", "b"): (r / "mods" / f"{n}-1.jar").write_bytes(b"jar-" + n.encode())
        (r / "config" / "x.toml").write_text("a=1\nb=2\n"); (r / "config" / "sub" / "y.json").write_text('{"k": 1}')
        (r / "config" / "gone.toml").write_text("only=real\n")
        (r / "server.properties").write_text("server-port=25565\nlevel-name=world\nmotd=real\n")
        (r / "user_jvm_args.txt").write_text("-Xmx8G\n-Xms2G\n"); (r / "start.sh").write_text("#!/bin/bash\n"); (r / "eula.txt").write_text("eula=true\n")
        (r / ".manager.json").write_text(json.dumps({"template": "neoforge", "modpack": {"name": "X"}}))
        db = sqlite3.connect(":memory:", check_same_thread=False); db.row_factory = sqlite3.Row; db.executescript(S.SCHEMA)
        class Conn:
            def __enter__(s): return db
            def __exit__(s, *a): return False
        self.running = set()
        def server_path(n):
            p = (self.root / "srv" / n)
            if not p.is_dir(): raise FileNotFoundError(n)
            return p
        self.ctx = types.SimpleNamespace(
            servers_dir=str(self.root / "srv"), server_path=server_path,
            status=lambda n: {"running": n in self.running, "control": False},
            db_run=lambda sql, args=(), one=False, many=False: (db.execute(sql, args).fetchone() if one else db.execute(sql, args).fetchall()),
            db_connect=lambda: Conn(), config=lambda: {"backup_dir": str(self.root / "bk")}, here=str(self.root), send_command=lambda *a: None)
        self.bk = mock.patch.object(S.backups, "create", lambda *a, **k: {"id": "bk1"}); self.bk.start()

    def tearDown(self):
        self.bk.stop(); self.tmp.cleanup()


class CreateTests(Base):
    def test_crea_un_servidor_aparte_sin_mundo(self):
        r = S.create(self.ctx, "main"); st = self.root / "srv" / r["staging"]
        self.assertEqual(r["staging"], "main-prueba")
        self.assertFalse((st / "world").exists(), "el mundo no se copia"); self.assertEqual((self.real / "world" / "level.dat").read_bytes(), b"MUNDO-REAL")
        self.assertEqual(sorted(p.name for p in (st / "mods").iterdir()), ["a-1.jar", "b-1.jar"])
        props = (st / "server.properties").read_text()
        self.assertIn("level-name=mundo-prueba", props); self.assertNotIn("server-port=25565", props); self.assertIn("server-port=25566", props)
        self.assertIn("-Xmx4096M", (st / "user_jvm_args.txt").read_text()); self.assertIn("-Xmx8G", (self.real / "user_jvm_args.txt").read_text())
        self.assertTrue((st / "libraries").is_symlink())

    def test_es_hijo_del_padre_y_no_hereda_el_modpack(self):
        S.create(self.ctx, "main"); m = json.loads((self.root / "srv" / "main-prueba" / ".manager.json").read_text())
        self.assertEqual(m["parent"], "main"); self.assertNotIn("modpack", m)

    def test_los_mods_son_copias_independientes(self):
        S.create(self.ctx, "main"); (self.root / "srv" / "main-prueba" / "mods" / "a-1.jar").write_bytes(b"cambiado")
        self.assertEqual((self.real / "mods" / "a-1.jar").read_bytes(), b"jar-a")

    def test_no_se_crea_dos_veces_ni_desde_el_hijo(self):
        S.create(self.ctx, "main")
        for n in ("main", "main-prueba"):
            with self.assertRaises(S.StagingError): S.create(self.ctx, n)

    def test_puerto_libre_si_el_siguiente_esta_ocupado(self):
        o = self.root / "srv" / "otro"; o.mkdir(); (o / "server.properties").write_text("server-port=25566\n")
        self.assertEqual(S.create(self.ctx, "main")["port"], 25567)


class DiffMergeTests(Base):
    def setUp(self):
        super().setUp(); S.create(self.ctx, "main"); self.st = self.root / "srv" / "main-prueba"

    def test_sin_cambios_no_hay_diferencias(self):
        d = S.diff(self.ctx, "main"); self.assertEqual(d["changes"], []); self.assertEqual(d["mods"]["same"], 2)

    def test_detecta_modificado_nuevo_y_borrado_con_diff(self):
        (self.st / "config" / "x.toml").write_text("a=1\nb=3\n"); (self.st / "config" / "nuevo.toml").write_text("n=1\n"); (self.st / "config" / "gone.toml").unlink()
        by = {c["path"]: c for c in S.diff(self.ctx, "main-prueba")["changes"]}
        self.assertEqual({k: v["kind"] for k, v in by.items()}, {"config/x.toml": "modified", "config/nuevo.toml": "added", "config/gone.toml": "removed"})
        self.assertIn("-b=2", by["config/x.toml"]["diff"]); self.assertIn("+b=3", by["config/x.toml"]["diff"])

    def test_mods_se_comparan_pero_no_se_fusionan(self):
        (self.st / "mods" / "c-1.jar").write_bytes(b"c"); (self.st / "mods" / "a-1.jar").unlink()
        d = S.diff(self.ctx, "main"); self.assertEqual(d["mods"]["only_staging"], ["c-1.jar"]); self.assertEqual(d["mods"]["only_real"], ["a-1.jar"])
        self.assertFalse([c for c in d["changes"] if c["path"].startswith("mods")])

    def test_server_properties_y_mundo_no_entran_en_la_comparacion(self):
        (self.st / "server.properties").write_text("x=1"); (self.st / "world").mkdir(); (self.st / "world" / "a.dat").write_bytes(b"z")
        self.assertEqual(S.diff(self.ctx, "main")["changes"], [])

    def test_fusion_copia_y_borra_solo_lo_elegido_con_copia_previa(self):
        (self.st / "config" / "x.toml").write_text("a=9\n"); (self.st / "config" / "sub" / "y.json").write_text('{"k": 2}'); (self.st / "config" / "gone.toml").unlink()
        r = S.merge(self.ctx, "main", [{"path": "config/x.toml", "action": "copy"}, {"path": "config/gone.toml", "action": "delete"}])
        self.assertEqual(r["backup"], "bk1"); self.assertEqual((self.real / "config" / "x.toml").read_text(), "a=9\n")
        self.assertFalse((self.real / "config" / "gone.toml").exists())
        self.assertEqual((self.real / "config" / "sub" / "y.json").read_text(), '{"k": 1}', "lo no elegido no cambia")
        self.assertEqual((self.real / "world" / "level.dat").read_bytes(), b"MUNDO-REAL")

    def test_fusion_crea_carpetas_y_se_puede_pedir_desde_el_hijo(self):
        (self.st / "config" / "deep" / "er").mkdir(parents=True); (self.st / "config" / "deep" / "er" / "z.toml").write_text("z=1\n")
        S.merge(self.ctx, "main-prueba", [{"path": "config/deep/er/z.toml", "action": "copy"}])
        self.assertEqual((self.real / "config" / "deep" / "er" / "z.toml").read_text(), "z=1\n")

    def test_exige_el_real_parado(self):
        (self.st / "config" / "x.toml").write_text("a=9\n"); self.running.add("main")
        with self.assertRaises(S.StagingError): S.merge(self.ctx, "main", [{"path": "config/x.toml", "action": "copy"}])
        self.assertEqual((self.real / "config" / "x.toml").read_text(), "a=1\nb=2\n")

    def test_rutas_peligrosas_se_rechazan(self):
        (self.st / "config" / "x.toml").write_text("a=9\n")
        for bad in ("../x", "/etc/passwd", "config/../world/level.dat", "world/level.dat", "mods/a-1.jar", "server.properties", "config//x", "config\\x.toml", "", None, 5):
            with self.assertRaises(S.StagingError, msg=str(bad)): S.merge(self.ctx, "main", [{"path": bad, "action": "copy"}])
        self.assertEqual((self.real / "world" / "level.dat").read_bytes(), b"MUNDO-REAL")

    def test_solo_vale_lo_que_aparece_en_la_diferencia_y_con_su_accion(self):
        (self.st / "config" / "gone.toml").unlink(); (self.st / "config" / "x.toml").write_text("a=9\n")
        for pick in ({"path": "config/sub/y.json", "action": "copy"},            # sin cambios
                     {"path": "config/gone.toml", "action": "copy"},            # borrado: solo 'delete'
                     {"path": "config/x.toml", "action": "delete"},             # modificado: no se borra
                     {"path": "config/x.toml", "action": "otra"}):
            with self.assertRaises(S.StagingError): S.merge(self.ctx, "main", [pick])

    def test_enlace_simbolico_en_pruebas_no_se_sigue(self):
        secret = self.root / "secreto.txt"; secret.write_text("S")
        (self.st / "config" / "l.toml").symlink_to(secret)
        self.assertEqual(S.diff(self.ctx, "main")["changes"], [], "los enlaces se ignoran")
        with self.assertRaises(S.StagingError): S.merge(self.ctx, "main", [{"path": "config/l.toml", "action": "copy"}])

    def test_selecciones_repetidas_o_vacias(self):
        (self.st / "config" / "x.toml").write_text("a=9\n")
        for picks in ([], None, [{"path": "config/x.toml", "action": "copy"}] * 2, ["config/x.toml"]):
            with self.assertRaises(S.StagingError): S.merge(self.ctx, "main", picks)

    def test_binarios_no_muestran_diff(self):
        (self.real / "config" / "b.bin").write_bytes(b"\xff\xfe\x00"); (self.st / "config" / "b.bin").write_bytes(b"\xff\xfe\x01")
        c = [c for c in S.diff(self.ctx, "main")["changes"] if c["path"].endswith("b.bin")][0]; self.assertFalse(c["text"]); self.assertEqual(c["diff"], "")


class ModMergeTests(Base):
    def setUp(self):
        super().setUp(); S.create(self.ctx, "main"); self.st = self.root / "srv" / "main-prueba"

    def pick(self, f, a): return {"file": f, "action": a}

    def test_detecta_nuevo_quitado_y_cambiado(self):
        (self.st / "mods" / "c-1.jar").write_bytes(b"c"); (self.st / "mods" / "a-1.jar").unlink(); (self.st / "mods" / "b-1.jar").write_bytes(b"otro")
        d = S.diff(self.ctx, "main"); by = {m["file"]: m["kind"] for m in d["mod_changes"]}
        self.assertEqual(by, {"c-1.jar": "added", "a-1.jar": "removed", "b-1.jar": "modified"}); self.assertEqual(d["mods"]["same"], 0)

    def test_fusiona_anadir_quitar_y_reemplazar_con_copia_previa(self):
        (self.st / "mods" / "c-1.jar").write_bytes(b"c"); (self.st / "mods" / "a-1.jar").unlink(); (self.st / "mods" / "b-1.jar").write_bytes(b"otro")
        r = S.merge_mods(self.ctx, "main", [self.pick("c-1.jar", "copy"), self.pick("a-1.jar", "delete"), self.pick("b-1.jar", "copy")])
        self.assertEqual(r["backup"], "bk1"); m = self.real / "mods"
        self.assertEqual(sorted(p.name for p in m.iterdir()), ["b-1.jar", "c-1.jar"]); self.assertEqual((m / "b-1.jar").read_bytes(), b"otro")
        self.assertEqual(S.diff(self.ctx, "main")["mod_changes"], [])

    def test_solo_lo_elegido(self):
        (self.st / "mods" / "c-1.jar").write_bytes(b"c"); (self.st / "mods" / "a-1.jar").unlink()
        S.merge_mods(self.ctx, "main", [self.pick("c-1.jar", "copy")])
        self.assertTrue((self.real / "mods" / "a-1.jar").exists(), "lo no elegido no se toca")

    def test_exige_real_parado(self):
        (self.st / "mods" / "c-1.jar").write_bytes(b"c"); self.running.add("main")
        with self.assertRaises(S.StagingError): S.merge_mods(self.ctx, "main", [self.pick("c-1.jar", "copy")])
        self.assertFalse((self.real / "mods" / "c-1.jar").exists())

    def test_nombres_y_acciones_peligrosas(self):
        (self.st / "mods" / "c-1.jar").write_bytes(b"c"); (self.st / "mods" / "a-1.jar").unlink()
        for p in (self.pick("../x.jar", "copy"), self.pick("a/b.jar", "copy"), self.pick("c-1.txt", "copy"), self.pick("b-1.jar", "delete"),
                  self.pick("c-1.jar", "delete"), self.pick("a-1.jar", "copy"), self.pick("c-1.jar", "otra"), self.pick(None, "copy"), "c-1.jar"):
            with self.assertRaises(S.StagingError, msg=str(p)): S.merge_mods(self.ctx, "main", [p])
        for picks in ([], None, [self.pick("c-1.jar", "copy")] * 2):
            with self.assertRaises(S.StagingError): S.merge_mods(self.ctx, "main", picks)

    def test_enlaces_simbolicos_no_se_siguen(self):
        sec = self.root / "sec.jar"; sec.write_bytes(b"S"); (self.st / "mods" / "l-1.jar").symlink_to(sec)
        self.assertEqual(S.diff(self.ctx, "main")["mod_changes"], [])
        with self.assertRaises(S.StagingError): S.merge_mods(self.ctx, "main", [self.pick("l-1.jar", "copy")])

    def test_mods_desactivados_tambien(self):
        (self.st / "mods" / "d-1.jar.disabled").write_bytes(b"d")
        S.merge_mods(self.ctx, "main", [self.pick("d-1.jar.disabled", "copy")]); self.assertTrue((self.real / "mods" / "d-1.jar.disabled").exists())


class DeleteTests(Base):
    def test_borra_solo_el_de_pruebas_y_no_sigue_el_enlace_de_libraries(self):
        (self.real / "libraries" / "lib.jar").write_bytes(b"L"); S.create(self.ctx, "main")
        S.delete(self.ctx, "main"); self.assertFalse((self.root / "srv" / "main-prueba").exists())
        self.assertEqual((self.real / "libraries" / "lib.jar").read_bytes(), b"L"); self.assertEqual((self.real / "mods" / "a-1.jar").read_bytes(), b"jar-a")
        self.assertIsNone(S.link(self.ctx, "main")); S.create(self.ctx, "main")

    def test_no_borra_en_marcha_ni_sin_pareja(self):
        S.create(self.ctx, "main"); self.running.add("main-prueba")
        with self.assertRaises(S.StagingError): S.delete(self.ctx, "main")
        with self.assertRaises(S.StagingError): S.delete(self.ctx, "otro")

    def test_borrar_desde_el_hijo_no_borra_el_real(self):
        S.create(self.ctx, "main"); S.delete(self.ctx, "main-prueba"); self.assertTrue(self.real.exists())


if __name__ == "__main__":
    unittest.main()
