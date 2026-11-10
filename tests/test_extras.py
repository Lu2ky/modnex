"""Extras del asistente de creación: AutoModpack (núcleo) y spark (plugin `features`)."""
import json, os, sys, tempfile, types, unittest
from pathlib import Path
CORE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CORE)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex import plugins
from modnex.services import extras
from modnex.features import spark

ROW = {"version_number": "1.0", "version_type": "release", "date_published": "2026-10-23",
       "files": [{"primary": True, "filename": "automodpack-mc1.21.1-neoforge-4.0.7.jar",
                  "url": "https://cdn.modrinth.com/data/x/versions/y/automodpack-mc1.21.1-neoforge-4.0.7.jar", "hashes": {"sha1": "00"}}]}


def rows(*more): return lambda q: [dict(ROW), *more]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.srv = Path(self.tmp.name) / "s"
        self.audits, self.downloads = [], []

        def download(url, dest, sha1):
            self.downloads.append((url, sha1)); Path(dest).write_bytes(b"JAR")
        self.ctx = types.SimpleNamespace(server_path=lambda n: self.srv, download=download,
                                         audit=lambda *a: self.audits.append(a))

    def server(self, template="neoforge", loader="neoforge", mc="1.21.1", folder="mods"):
        (self.srv / folder).mkdir(parents=True)
        (self.srv / ".manager.json").write_text(json.dumps({"template": template, "loader": loader, "mc": mc}))

    def tearDown(self): self.tmp.cleanup()


class InstallTests(Base):
    def test_instala_en_mods_con_el_cargador_y_version_del_servidor(self):
        self.server()
        seen = []
        f = extras.install_modrinth(self.ctx, "s", "automodpack", prefix="automodpack", fetch=lambda q: seen.append(q) or [dict(ROW)])
        self.assertEqual(f, "automodpack-mc1.21.1-neoforge-4.0.7.jar")
        self.assertTrue((self.srv / "mods" / f).is_file()); self.assertFalse(list((self.srv / "mods").glob("*.part")))
        self.assertIn("neoforge", seen[0]); self.assertIn("1.21.1", seen[0])

    def test_paper_lo_deja_en_plugins(self):
        self.server("paper", "paper", "1.21.1", "plugins")
        row = dict(ROW, files=[dict(ROW["files"][0], filename="spark-1.10.jar", url="https://cdn.modrinth.com/data/x/spark-1.10.jar")])
        self.assertEqual(extras.install_modrinth(self.ctx, "s", "spark", fetch=lambda q: [row]), "spark-1.10.jar")
        self.assertTrue((self.srv / "plugins" / "spark-1.10.jar").is_file())

    def test_no_instala_dos_veces(self):
        self.server(); (self.srv / "mods" / "automodpack-old.jar").write_bytes(b"x")
        self.assertIsNone(extras.install_modrinth(self.ctx, "s", "automodpack", prefix="automodpack", fetch=rows()))
        self.assertEqual(self.downloads, [])

    def test_cargador_no_compatible_es_no_disponible(self):
        self.server("paper", "paper", "1.21.1", "plugins")
        with self.assertRaises(extras.ExtraUnavailable):
            extras.install_modrinth(self.ctx, "s", "automodpack", loaders={"fabric", "neoforge"}, fetch=rows())

    def test_sin_version_estable_y_descargas_raras(self):
        self.server()
        with self.assertRaises(extras.ExtraUnavailable):
            extras.install_modrinth(self.ctx, "s", "x", fetch=lambda q: [dict(ROW, version_type="beta")])
        for url, fn in (("https://evil.com/a.jar", "a.jar"), ("http://cdn.modrinth.com/a.jar", "a.jar"), ("https://cdn.modrinth.com/a.jar", "../a.jar")):
            bad = dict(ROW, files=[{"primary": True, "filename": fn, "url": url}])
            with self.assertRaises(extras.ExtraUnavailable): extras.install_modrinth(self.ctx, "s", "x", fetch=lambda q: [bad])
        self.assertEqual(self.downloads, [])


class RegistryTests(Base):
    def test_automodpack_es_del_nucleo(self):
        a = next(e for e in extras.listing() if e["id"] == "automodpack")
        self.assertEqual(a["loaders"], ["fabric", "forge", "neoforge"])
        self.assertNotIn("install", a)

    def test_validar_rechaza_desconocidos_y_cargador_incompatible(self):
        self.assertEqual(extras.validate(None), []); self.assertEqual(extras.validate(["automodpack", "automodpack"], "neoforge"), ["automodpack"])
        for bad in (["nope"], "automodpack", [1], ["x"] * 3):
            with self.assertRaises(ValueError): extras.validate(bad)
        with self.assertRaises(ValueError): extras.validate(["automodpack"], "paper")

    def test_spark_solo_existe_si_un_plugin_lo_registra(self):
        extras.EXTRAS.pop("spark", None)
        self.assertNotIn("spark", [e["id"] for e in extras.listing()])
        with self.assertRaises(ValueError): extras.validate(["spark"])
        api = plugins.PluginAPI(self.ctx)
        api.extra("spark", "Perfilador", "d", spark.install, loaders=spark.LOADERS)
        try:
            s = next(e for e in extras.listing() if e["id"] == "spark")
            self.assertEqual(s["loaders"], ["fabric", "forge", "neoforge"])
            with self.assertRaises(ValueError): extras.validate(["spark"], "paper")
        finally:
            extras.EXTRAS.pop("spark", None)

    def test_run_anota_y_no_falla_si_un_extra_no_se_puede_instalar(self):
        def boom(ctx, n): raise OSError("sin red")
        def na(ctx, n): raise extras.ExtraUnavailable("no hay versión")
        extras.register("t-ok", "Ok", "d", lambda c, n: "a.jar"); extras.register("t-boom", "Boom", "d", boom); extras.register("t-na", "NA", "d", na)
        try:
            r = extras.run(self.ctx, "s", ["t-ok", "t-boom", "t-na"])
        finally:
            for k in ("t-ok", "t-boom", "t-na"): extras.EXTRAS.pop(k)
        self.assertEqual([(x["id"], x["ok"]) for x in r], [("t-ok", True), ("t-boom", False), ("t-na", False)])
        self.assertIn("sin red", r[1]["reason"]); self.assertEqual(len(self.audits), 3)

    def test_spark_usa_el_instalador_del_nucleo(self):
        calls = []
        ctx = types.SimpleNamespace(install_modrinth=lambda *a, **k: calls.append((a, k)) or "spark-1.jar")
        self.assertEqual(spark.install(ctx, "s"), "spark-1.jar")
        self.assertEqual(calls[0][0], ("s", "spark")); self.assertEqual(calls[0][1]["prefix"], "spark")


class ClientTests(unittest.TestCase):
    def test_el_cliente_lleva_siempre_automodpack_aun_sin_pro(self):
        plugins.API = None
        rows_ = {"AutoModpack-1.jar": 1, "automodpack-mc1.21.1-neoforge-4.0.7.jar": 1, "otro.jar": 1, "automodpack.txt": 1}
        self.assertEqual(plugins.client_must_include("s", rows_), ["AutoModpack-1.jar", "automodpack-mc1.21.1-neoforge-4.0.7.jar"])


if __name__ == "__main__":
    unittest.main()
