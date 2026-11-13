"""AutoModpack 5: lectura de server.conf, qué se publica de kubejs/ y la edición de la lista exclude."""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.features import automodpack as am

CONF = '''# AutoModpack configuration.
modpack-host: true
modpack: {
  name: ""
  General: {
    main: {
      display-name: ""
      selection: REQUIRED
      # extra paths from the server root
      from-server: [mods/*.jar, kubejs/**, emotes/*]
      # drop these from the pack; they do not add files
      exclude: [**/.*, **/.*/**, "**/*.{tmp,disabled,bak}", kubejs/server_scripts/**]
      editable: [options.txt, config/**]
    }
  }
}
require-modpack: true
'''


class Ctx:
    def __init__(self, root): self.root = root
    def server_path(self, name): return str(self.root)


def server(tmp, conf=CONF):
    root = Path(tmp)
    for f in ("kubejs/server_scripts/a.js", "kubejs/server_scripts/modnex_reglas.js", "kubejs/startup_scripts/main.js", "kubejs/client_scripts/modnex_cliente.js",
              "kubejs/modnex/loot.json", "kubejs/modnex/recetas.json", "kubejs/data/minecraft/loot_table/entities/zombie.json", "kubejs/assets/x/lang/es.json", "kubejs/.cache/x"):
        (root / f).parent.mkdir(parents=True, exist_ok=True); (root / f).write_text("x")
    if conf is not None:
        (root / "automodpack").mkdir(); (root / "automodpack/server.conf").write_text(conf)
    return Ctx(root)


class ParseTest(unittest.TestCase):
    def test_lee_las_listas_con_llaves_y_comillas(self):
        g = am.parse(CONF)
        self.assertEqual(g[0]["from_server"], ["mods/*.jar", "kubejs/**", "emotes/*"])
        self.assertEqual(g[0]["exclude"], ["**/.*", "**/.*/**", "**/*.{tmp,disabled,bak}", "kubejs/server_scripts/**"])

    def test_lista_en_varias_lineas_y_comentarios(self):
        g = am.parse("from-server: [\n  kubejs/**,\n  # nota\n  mods/*.jar\n]\nexclude: [\n  a/**\n  b/**,\n]\n")
        self.assertEqual(g[0]["from_server"], ["kubejs/**", "mods/*.jar"]); self.assertEqual(g[0]["exclude"], ["a/**", "b/**"])

    def test_dos_grupos_cada_uno_con_su_exclude(self):
        g = am.parse("a: {\n from-server: [kubejs/**]\n exclude: [x/**]\n}\nb: {\n from-server: [mods/*.jar]\n}\n")
        self.assertEqual([x["exclude"] for x in g], [["x/**"], []])

    def test_sin_archivo_valido(self):
        self.assertEqual(am.parse(""), []); self.assertEqual(am.parse("modpack-host: true"), [])

    def test_patrones(self):
        m = lambda path, pat: am._glob(pat).fullmatch(path) is not None
        self.assertTrue(m("kubejs/data/a/b.json", "kubejs/**") and m("kubejs/x", "kubejs/**")); self.assertFalse(m("kubejs", "kubejs/**"))
        self.assertTrue(m("mods/a.jar", "mods/*.jar")); self.assertFalse(m("mods/sub/a.jar", "mods/*.jar"))
        self.assertTrue(m("a/b/.hidden", "**/.*") and m(".hidden", "**/.*")); self.assertFalse(m("a/b/c", "**/.*"))
        self.assertTrue(m("x/y.tmp", "**/*.{tmp,disabled,bak}") and not m("x/y.jar", "**/*.{tmp,disabled,bak}"))
        self.assertTrue(m("kubejs/.cache/x", "**/.*/**"))


class AnalyzeTest(unittest.TestCase):
    def test_detecta_lo_que_se_filtra_a_los_jugadores(self):
        with tempfile.TemporaryDirectory() as d:
            a = am.analyze(server(d), "s")
            self.assertTrue(a["configured"] and a["publishes_kubejs"])
            self.assertNotIn("kubejs/server_scripts/a.js", a["published"])                     # ya estaba excluido
            self.assertNotIn("kubejs/.cache/x", a["published"])                                 # ocultos fuera
            self.assertEqual(sorted(a["leaks"]), ["kubejs/data/minecraft/loot_table/entities/zombie.json", "kubejs/modnex/loot.json", "kubejs/modnex/recetas.json"])
            self.assertEqual([m["pattern"] for m in a["missing"]], ["kubejs/modnex/**", "kubejs/data/**"])
            self.assertIn("kubejs/startup_scripts/main.js", a["published"]); self.assertIn("kubejs/client_scripts/modnex_cliente.js", a["client_files"])

    def test_sin_server_conf(self):
        with tempfile.TemporaryDirectory() as d:
            a = am.analyze(server(d, None), "s"); self.assertFalse(a["configured"]); self.assertEqual(a["missing"], [])

    def test_si_no_publica_kubejs_no_hay_nada_que_arreglar(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = server(d, "from-server: [mods/*.jar]\nexclude: []\n")
            a = am.analyze(ctx, "s"); self.assertFalse(a["publishes_kubejs"]); self.assertEqual(a["missing"], []); self.assertEqual(a["leaks"], [])
            with self.assertRaises(ValueError): am.fix(ctx, "s")


class FixTest(unittest.TestCase):
    def test_solo_cambia_la_lista_exclude_y_guarda_copia(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = server(d)
            r = am.fix(ctx, "s")
            new = (Path(d) / "automodpack/server.conf").read_text()
            self.assertTrue(r["changed"]); self.assertEqual(r["missing"], []); self.assertEqual(r["leaks"], [])
            self.assertEqual((Path(d) / am.BACKUP).read_text(), CONF)
            self.assertEqual(new.replace(", kubejs/modnex/**, kubejs/data/**]", "]"), CONF)      # lo único añadido es eso
            self.assertIn("kubejs/startup_scripts/main.js", r["published"])                      # lo del cliente sigue publicándose

    def test_es_idempotente(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = server(d); am.fix(ctx, "s")
            first = (Path(d) / "automodpack/server.conf").read_text()
            r = am.fix(ctx, "s")
            self.assertFalse(r["changed"]); self.assertEqual((Path(d) / "automodpack/server.conf").read_text(), first)

    def test_lista_en_varias_lineas_y_grupo_sin_exclude(self):
        multi = "from-server: [kubejs/**]\nexclude: [\n  a/**\n]\n"
        out, changed = am._insert(multi, ["kubejs/modnex/**"])
        self.assertTrue(changed); self.assertEqual(am.parse(out)[0]["exclude"], ["a/**", "kubejs/modnex/**"])
        none, changed = am._insert("  from-server: [kubejs/**]\n", ["kubejs/modnex/**"])
        self.assertTrue(changed); self.assertEqual(am.parse(none)[0]["exclude"], ["kubejs/modnex/**"]); self.assertIn("\n  exclude: [", none)

    def test_no_toca_grupos_que_no_publican_kubejs(self):
        text = "a: {\n from-server: [mods/*.jar]\n exclude: []\n}\nb: {\n from-server: [kubejs/**]\n exclude: [z/**]\n}\n"
        out, _ = am._insert(text, ["kubejs/modnex/**"])
        g = am.parse(out); self.assertEqual(g[0]["exclude"], []); self.assertEqual(g[1]["exclude"], ["z/**", "kubejs/modnex/**"])


if __name__ == "__main__":
    unittest.main()
