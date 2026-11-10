import json, sys, tempfile, time, types, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.features import safeupdate as su, sync

FP = "ab" * 32
FAKE = r'''#!/usr/bin/env bash
cd "$(dirname "$0")"
if ls mods | grep -qi "automodpack"; then
  mkdir -p automodpack/host-modpack
  echo '{"bindPort": -1, "modpackHost": true, "autoExcludeServerSideMods": true, "secret": "NO"}' > automodpack/automodpack-server.json
  echo '{"list": [{"file": "/mods/a-1.jar"}, {"file": "/mods/b-1.jar"}, {"file": "/config/x.toml"}]}' > automodpack/host-modpack/automodpack-content.json
  echo "[00:00:27] [Server thread/WARN] [AutoModpack/]: Certificate fingerprint: ''' + FP + r'''"
fi
if ls mods | grep -q "breaks"; then echo "Exception: Mod loading has failed"; exit 1; fi
echo "[00:00:01] [Server thread/INFO]: Done (1.0s)! For help"
while read -r l; do [ "$l" = stop ] && exit 0; done
'''
ROW = {"version_number": "4.0.7", "version_type": "release", "date_published": "2026-10-23",
       "files": [{"primary": True, "filename": "automodpack-mc1.21.1-neoforge-4.0.7.jar", "url": "https://cdn.modrinth.com/data/x/versions/y/automodpack-mc1.21.1-neoforge-4.0.7.jar", "hashes": {"sha1": "00"}}]}


def rows(*extra): return lambda q: [dict(ROW), *extra]


class VersionTests(unittest.TestCase):
    ctx = types.SimpleNamespace(server_versions=lambda n: {"minecraft": "1.21.1", "loader": "neoforge"})

    def test_elige_la_estable_mas_reciente_y_ignora_betas(self):
        beta = dict(ROW, version_number="5.0.0-rc.7", version_type="beta", date_published="2026-10-24")
        v = sync.resolve_version(self.ctx, "s", rows(beta))
        self.assertEqual(v["version"], "4.0.7")

    def test_sin_estable_falla(self):
        with self.assertRaises(sync.SyncError): sync.resolve_version(self.ctx, "s", lambda q: [dict(ROW, version_type="beta")])

    def test_rechaza_hosts_y_nombres_raros(self):
        for url, fn in (("https://evil.com/a.jar", "a.jar"), ("http://cdn.modrinth.com/a.jar", "a.jar"), ("https://cdn.modrinth.com/a.jar", "../a.jar")):
            bad = dict(ROW, files=[{"primary": True, "filename": fn, "url": url}])
            with self.assertRaises(sync.SyncError): sync.resolve_version(self.ctx, "s", lambda q, b=bad: [b])

    def test_valores_del_servidor_no_se_cuelan_en_la_consulta(self):
        ctx = types.SimpleNamespace(server_versions=lambda n: {"minecraft": "1.21.1&x=1", "loader": "neoforge"})
        with self.assertRaises(sync.SyncError): sync.resolve_version(ctx, "s", rows())


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); r = Path(self.tmp.name)
        self.srv = r / "srv"; (self.srv / "mods").mkdir(parents=True); (self.srv / "libraries").mkdir(); (self.srv / "config").mkdir()
        for n in ("a", "b", "serveronly"): (self.srv / "mods" / f"{n}-1.jar").write_bytes(b"x")
        (self.srv / "start.sh").write_text(FAKE); (self.srv / "start.sh").chmod(0o755)
        (self.srv / "server.properties").write_text("server-port=25565\nlevel-name=world\n")
        (self.srv / "user_jvm_args.txt").write_text("-Xmx8G\n")
        (self.srv / "world").mkdir(); (self.srv / "world" / "level.dat").write_bytes(b"MUNDO")
        self.running = False
        self.dl = []
        self.ctx = types.SimpleNamespace(
            here=str(r), config=lambda: {"backup_dir": str(r / "bk"), "sandbox_dir": str(r / "sb")}, server_path=lambda n: self.srv,
            status=lambda n: {"running": self.running, "control": False}, send_command=lambda n, c: None,
            server_versions=lambda n: {"minecraft": "1.21.1", "loader": "neoforge"}, java_bin=lambda: "java", audit=lambda *a: None,
            download=lambda url, dest, sha1=None: (self.dl.append((url, sha1)), Path(dest).write_bytes(b"jar"))[1])
        sync.JOBS.clear()
        self.p = mock.patch.object(su, "mem_available_mb", lambda: 50000); self.p.start()

    def tearDown(self):
        self.p.stop(); self.tmp.cleanup()

    def run_test(self, **kw):
        sync.start_test(self.ctx, "s", fetch=rows(), **kw)
        for _ in range(200):
            if sync.JOBS["s"]["state"] != "running": return sync.JOBS["s"]
            time.sleep(0.1)
        self.fail("no terminó")

    def test_prueba_resume_lo_que_se_publicaria(self):
        j = self.run_test()
        self.assertEqual((j["state"], j["ok"]), ("done", True), j)
        self.assertEqual(j["published"], ["a-1.jar", "b-1.jar"]); self.assertEqual(j["excluded"], ["serveronly-1.jar"])
        self.assertTrue(j["host_on_game_port"]); self.assertEqual(j["test_fingerprint"], FP)
        self.assertNotIn("secret", j["config"], "solo se muestran ajustes conocidos")
        self.assertEqual(self.dl[0][1], "00", "se verifica el hash")

    def test_el_servidor_real_no_cambia(self):
        before = sorted(p.name for p in (self.srv / "mods").iterdir())
        self.run_test()
        self.assertEqual(sorted(p.name for p in (self.srv / "mods").iterdir()), before)
        self.assertEqual((self.srv / "world" / "level.dat").read_bytes(), b"MUNDO")
        self.assertEqual((self.srv / "user_jvm_args.txt").read_text(), "-Xmx8G\n", "la memoria recortada es solo del entorno aislado")
        self.assertFalse(list((Path(self.tmp.name) / "sb").glob("s-*")), "el entorno aislado se borra")

    def test_se_puede_probar_con_el_servidor_en_marcha(self):
        self.running = True
        self.assertTrue(self.run_test()["ok"])

    def test_si_no_hay_memoria_no_arranca(self):
        with mock.patch.object(su, "mem_available_mb", lambda: 2000):
            j = self.run_test()
        self.assertEqual(j["state"], "error"); self.assertIn("memoria", j["error"])

    def test_si_otro_mod_rompe_el_arranque_lo_cuenta(self):
        (self.srv / "mods" / "breaks-1.jar").write_bytes(b"x")
        j = self.run_test()
        self.assertEqual((j["state"], j["ok"]), ("done", False)); self.assertTrue(j["reason"])

    def test_no_instala_sin_prueba(self):
        with self.assertRaises(sync.SyncError): sync.install(self.ctx, "s")

    def test_instalar_exige_servidor_parado_y_hace_copia(self):
        self.run_test(); self.running = True
        with self.assertRaises(sync.SyncError): sync.install(self.ctx, "s")
        self.running = False
        with mock.patch.object(sync.backups, "create", lambda *a, **k: {"id": "bk1"}) as c:
            r = sync.install(self.ctx, "s")
        self.assertEqual(r["backup"], "bk1"); self.assertEqual(sync.installed(self.ctx, "s"), ["automodpack-mc1.21.1-neoforge-4.0.7.jar"])
        with self.assertRaises(sync.SyncError): sync.install(self.ctx, "s")

    def test_una_prueba_a_la_vez(self):
        self.assertTrue(su._GLOBAL.acquire(blocking=False))
        try:
            with self.assertRaises(sync.SyncError): sync.start_test(self.ctx, "s", fetch=rows())
        finally: su._GLOBAL.release()
        self.assertNotEqual(sync.JOBS.get("s", {}).get("state"), "running")

    def test_huella_en_el_formato_de_cada_version_de_automodpack(self):
        for linea in (f"[00:00:27] [Server thread/WARN] [AutoModpack/]: Certificate fingerprint: {FP}",
                      f"[10nov2026 15:32:45.489] [Server thread/INFO] [AutoModpack/]: AutoModpack host certificate fingerprint: {FP}",
                      f"AUTOMODPACK HOST CERTIFICATE FINGERPRINT:   {FP.upper().lower()}"):
            self.assertEqual(sync.FP_RE.findall(linea), [FP], linea)
        self.assertEqual(sync.FP_RE.findall("certificate fingerprint: abc123"), [], "una huella tiene 64 caracteres hexadecimales")

    def test_huella_real_con_automodpack_5_en_latest_log(self):
        (self.srv / "logs").mkdir(exist_ok=True)
        (self.srv / "logs" / "latest.log").write_text(f"x\n[AutoModpack/]: AutoModpack host certificate fingerprint: {FP}\ny\n")
        self.assertEqual(sync.real_fingerprint(self.ctx, "s"), FP)

    def test_huella_real_se_lee_del_log_del_servidor_real(self):
        (self.srv / "logs").mkdir(); (self.srv / "logs" / "latest.log").write_text(f"x\nCertificate fingerprint: {FP}\n")
        self.assertEqual(sync.real_fingerprint(self.ctx, "s"), FP)

    def test_estado_publico_no_filtra_campos_internos(self):
        self.run_test(); self.assertFalse([k for k in sync.public(self.ctx, "s") if k.startswith("_")])


if __name__ == "__main__":
    unittest.main()
