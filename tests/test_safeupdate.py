import itertools, os, stat, sys, tempfile, time, types, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from features import safeupdate as su


def tester(bad=(), pairs=(), named=False):
    """test(subset): falla si contiene un 'bad' o un par que interactúa. Cuenta los arranques."""
    calls = []
    def test(subset):
        calls.append(tuple(sorted(subset)))
        s = set(subset)
        broken = [b for b in bad if b in s]
        inter = any(a in s and b in s for a, b in pairs)
        ok = not broken and not inter
        return ok, (broken if (named and not ok) else [])
    test.calls = calls
    return test


ITEMS = [f"m{i}" for i in range(8)]


class FindSafeTests(unittest.TestCase):
    def test_todo_bien_un_solo_arranque(self):
        t = tester(); r = su.find_safe(ITEMS, t)
        self.assertEqual((sorted(r["safe"]), r["bad"], r["boots"]), (sorted(ITEMS), [], 1))

    def test_un_culpable(self):
        t = tester(bad=["m5"]); r = su.find_safe(ITEMS, t)
        self.assertEqual(r["bad"], ["m5"]); self.assertEqual(sorted(r["safe"]), sorted(set(ITEMS) - {"m5"}))
        self.assertLessEqual(r["boots"], 6, "bisección, no uno por uno")

    def test_dos_culpables(self):
        r = su.find_safe(ITEMS, tester(bad=["m1", "m6"]))
        self.assertEqual(sorted(r["bad"]), ["m1", "m6"]); self.assertEqual(len(r["safe"]), 6)

    def test_todos_culpables(self):
        r = su.find_safe(["a", "b", "c"], tester(bad=["a", "b", "c"]))
        self.assertEqual((r["safe"], sorted(r["bad"])), ([], ["a", "b", "c"]))

    def test_el_log_nombra_al_culpable_y_ahorra_arranques(self):
        mudo = su.find_safe(ITEMS, tester(bad=["m5"], named=False))
        nombrado = su.find_safe(ITEMS, tester(bad=["m5"], named=True))
        self.assertEqual(nombrado["bad"], ["m5"]); self.assertEqual(nombrado["boots"], 2, "falla y se repite sin el culpable")
        self.assertLess(nombrado["boots"], mudo["boots"])

    def test_interaccion_entre_dos_actualizaciones(self):
        r = su.find_safe(["a", "b", "c", "d"], tester(pairs=[("a", "d")]))
        self.assertFalse(set(["a", "d"]) <= set(r["safe"]), "nunca deben quedar juntas las dos que chocan")
        self.assertTrue(r["bad"] or r["conflict"], "alguna de las dos debe quedar fuera y señalada")
        self.assertTrue(su.find_safe(["a", "b", "c", "d"], tester(pairs=[("a", "d")]))["boots"] <= su.MAX_BOOTS)

    def test_lo_seguro_realmente_pasa_la_prueba(self):
        for bad, pairs in ((["m2"], []), (["m0", "m7"], []), ([], [("m1", "m4")]), (["m3"], [("m0", "m6")])):
            t = tester(bad=bad, pairs=pairs); r = su.find_safe(ITEMS, t)
            self.assertTrue(t(r["safe"])[0] if r["safe"] else True, f"{bad} {pairs}: el resultado 'seguro' debe arrancar")

    def test_presupuesto_de_arranques(self):
        r = su.find_safe([f"x{i}" for i in range(40)], tester(bad=["x3", "x17", "x30", "x38"]), max_boots=4)
        self.assertTrue(r["truncated"]); self.assertLessEqual(r["boots"], 4)
        self.assertEqual(set(r["safe"]) & {"x3", "x17", "x30", "x38"}, set())

    def test_un_elemento_y_vacio(self):
        self.assertEqual(su.find_safe(["a"], tester(bad=["a"]))["bad"], ["a"])
        self.assertEqual(su.find_safe([], tester())["safe"], [])


class PipelineTests(unittest.TestCase):
    """Entorno aislado real: carpetas, enlaces y un start.sh que falla si encuentra el mod malo."""
    FAKE = '#!/usr/bin/env bash\ncd "$(dirname "$0")"\nif ls mods | grep -q "bad"; then echo "Exception: Mod loading has failed"; exit 1; fi\necho "[00:00:01] [Server thread/INFO]: Done (1.0s)! For help"\nwhile read -r l; do [ "$l" = stop ] && exit 0; done\n'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); r = Path(self.tmp.name)
        self.srv = r / "srv"; (self.srv / "mods").mkdir(parents=True); (self.srv / "config").mkdir(); (self.srv / "libraries").mkdir()
        for n in ("a", "b", "c"): (self.srv / "mods" / f"{n}-1.jar").write_bytes(b"old-" + n.encode())
        (self.srv / "start.sh").write_text(self.FAKE); (self.srv / "start.sh").chmod(0o755)
        (self.srv / "server.properties").write_text("server-port=25565\nlevel-name=world\nmotd=real\n")
        (self.srv / "user_jvm_args.txt").write_text("-Xmx2G\n")
        (self.srv / "world").mkdir(); (self.srv / "world" / "level.dat").write_bytes(b"MUNDO")
        self.running = False
        rows = [{"file": f"{n}-1.jar", "enabled": True, "name": n.upper(), "installed": "1", "latest": "2",
                 "update_url": f"https://cdn.modrinth.com/data/x/versions/y/{n}-2.jar" if n != "c" else f"https://cdn.modrinth.com/data/x/versions/y/bad-{n}-2.jar",
                 "update_filename": f"{n}-2.jar" if n != "c" else f"bad-{n}-2.jar", "update_sha1": None} for n in ("a", "b", "c")]
        self.ctx = types.SimpleNamespace(
            here=str(r), config=lambda: {"backup_dir": str(r / "bk"), "sandbox_dir": str(r / "sb")}, server_path=lambda n: self.srv,
            status=lambda n: {"running": self.running, "control": False}, send_command=lambda n, c: None,
            server_versions=lambda n: {"minecraft": "1.21.1", "loader": "neoforge"}, identify_mods=lambda n, l, v: rows,
            java_bin=lambda: "java", audit=lambda *a: None,
            download=lambda url, dest, sha1=None: Path(dest).write_bytes(b"new-" + Path(url).name.encode()))
        su.JOBS.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def wait(self, name="s"):
        for _ in range(200):
            if su.JOBS[name]["state"] != "running": return su.JOBS[name]
            time.sleep(0.1)
        self.fail("la prueba no terminó")

    def test_candidatos_filtran_hosts_y_nombres(self):
        rows = [{"file": "a.jar", "enabled": True, "latest": "2", "update_url": "https://evil.com/a-2.jar", "update_filename": "a-2.jar"},
                {"file": "b.jar", "enabled": True, "latest": "2", "update_url": "http://cdn.modrinth.com/b-2.jar", "update_filename": "b-2.jar"},
                {"file": "c.jar", "enabled": True, "latest": "2", "update_url": "https://cdn.modrinth.com/c", "update_filename": "../c-2.jar"},
                {"file": "d.jar", "enabled": True, "latest": "2", "update_url": "https://cdn.modrinth.com/d", "update_filename": "d.jar"},
                {"file": "e.jar", "enabled": False, "latest": "2", "update_url": "https://cdn.modrinth.com/e", "update_filename": "e-2.jar"},
                {"file": "ok.jar", "enabled": True, "latest": "2", "update_url": "https://cdn.modrinth.com/ok", "update_filename": "ok-2.jar"}]
        self.ctx.identify_mods = lambda n, l, v: rows
        self.assertEqual([c["file"] for c in su.candidates(self.ctx, "s")], ["ok.jar"])

    def test_sandbox_aislado(self):
        sb = su.make_sandbox(self.ctx, "s", Path(self.tmp.name) / "sb")
        self.assertFalse((sb / "world").exists(), "no se copia el mundo")
        self.assertTrue((sb / "libraries").is_symlink())
        props = (sb / "server.properties").read_text()
        self.assertIn("level-name=sandbox-world", props); self.assertNotIn("server-port=25565", props)
        self.assertEqual((self.srv / "server.properties").read_text().count("motd=real"), 1, "el original no se toca")

    def test_flujo_completo_y_el_real_no_se_toca(self):
        su.start_job(self.ctx, "s"); job = self.wait()
        self.assertEqual(job["state"], "done", job)
        self.assertEqual(sorted(x["file"] for x in job["safe"]), ["a-1.jar", "b-1.jar"])
        self.assertEqual([x["file"] for x in job["bad"]], ["c-1.jar"])
        self.assertEqual(sorted(p.name for p in (self.srv / "mods").iterdir()), ["a-1.jar", "b-1.jar", "c-1.jar"], "el servidor real no cambia")
        self.assertEqual((self.srv / "world/level.dat").read_bytes(), b"MUNDO")
        self.assertFalse(any(Path(self.tmp.name, "sb").glob("s-*")), "el entorno aislado se borra al terminar")

    def test_aplicar_solo_lo_seguro_con_copia_previa(self):
        su.start_job(self.ctx, "s"); self.wait()
        with self.assertRaises(su.UpdateError): su.apply(self.ctx, "s", ["c-1.jar"])  # la mala no se puede aplicar
        r = su.apply(self.ctx, "s", ["a-1.jar", "b-1.jar"])
        self.assertEqual(sorted(p.name for p in (self.srv / "mods").iterdir()), ["a-2.jar", "b-2.jar", "c-1.jar"])
        self.assertTrue(r["backup"]); self.assertEqual(su.JOBS["s"]["_plan"], {})
        self.assertTrue(any(m["kind"] == "pre-update" for m in backups_list(self.ctx)))

    def test_no_aplicar_con_el_servidor_en_marcha(self):
        su.start_job(self.ctx, "s"); self.wait(); self.running = True
        with self.assertRaises(su.UpdateError): su.apply(self.ctx, "s", ["a-1.jar"])

    def test_no_probar_con_el_servidor_en_marcha(self):
        self.running = True
        with self.assertRaises(su.UpdateError): su.start_job(self.ctx, "s")

    def test_sin_actualizaciones(self):
        self.ctx.identify_mods = lambda n, l, v: []
        su.start_job(self.ctx, "s"); job = self.wait()
        self.assertEqual((job["state"], job["safe"]), ("done", []))

    def test_sin_memoria_suficiente_se_rechaza(self):
        orig = su.mem_available_mb; su.mem_available_mb = lambda: 100
        try:
            su.start_job(self.ctx, "s"); job = self.wait()
        finally:
            su.mem_available_mb = orig
        self.assertEqual(job["state"], "error"); self.assertIn("memoria", job["error"])

    def test_una_prueba_a_la_vez(self):
        orig = su.candidates
        su.candidates = lambda c, n: (time.sleep(1.0) or [])
        try:
            su.start_job(self.ctx, "s")
            with self.assertRaises(su.UpdateError): su.start_job(self.ctx, "otro")
            self.wait()
        finally:
            su.candidates = orig

    def test_antes_de_probar_no_se_puede_aplicar(self):
        with self.assertRaises(su.UpdateError): su.apply(self.ctx, "s", ["a-1.jar"])


def backups_list(ctx):
    from features import backups
    return backups.list_backups(ctx, "s")


if __name__ == "__main__":
    unittest.main()
