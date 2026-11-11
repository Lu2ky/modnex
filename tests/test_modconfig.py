import sys, tempfile, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.services import modconfig as mc

SAMPLE = """#General settings
[general]
	#How many ticks that the count cache is kept alive.
	# Default: 10
	# Range: 0 ~ 10000
	cacheRetentionTicks = 10
	#The radius that is used for player specific conditions
	# Default: 100
	# Range: 1 ~ 10000
	perPlayerRadius = 100
	#Do chiseled bookshelves provide enchanting power
	#NONE: Vanilla behavior.
	#Allowed Values: NONE, SINGLE, ALL
	enchantment_hint = "SINGLE"
	# Default: []
	disabledAddons = []
	compressDenylist = ["minecraft:sandstone", "minecraft:iron_trapdoor"]
"""


class ParseTests(unittest.TestCase):
    def test_lee_secciones_y_metadatos(self):
        es = {e["key"]: e for e in mc.parse(SAMPLE)}
        self.assertEqual(es["cacheRetentionTicks"]["section"], "general")
        self.assertEqual(es["cacheRetentionTicks"]["type"], "int")
        self.assertEqual(es["cacheRetentionTicks"]["range"], "0 ~ 10000")
        self.assertEqual(es["cacheRetentionTicks"]["default"], "10")
        self.assertIn("kept alive", es["cacheRetentionTicks"]["description"])
        self.assertEqual(es["enchantment_hint"]["allowed"], "NONE, SINGLE, ALL")
        self.assertEqual(es["enchantment_hint"]["value"], "SINGLE")
        self.assertEqual(es["compressDenylist"]["type"], "list")
        self.assertEqual(es["compressDenylist"]["value"], ["minecraft:sandstone", "minecraft:iron_trapdoor"])

    def test_bool_float_y_crudo(self):
        t = "[a]\n\tflag = true\n\tratio = 0.5\n\tx = 3.0e2\n"
        es = {e["key"]: e for e in mc.parse(t)}
        self.assertEqual(es["flag"]["type"], "bool")
        self.assertEqual(es["ratio"]["type"], "float")
        self.assertEqual(es["x"]["type"], "float")


class PatchTests(unittest.TestCase):
    def test_cambia_solo_la_linea_editada(self):
        out = mc.apply_updates(SAMPLE, [{"section": "general", "key": "perPlayerRadius", "value": 250}])
        self.assertIn("\tperPlayerRadius = 250\n", out)
        self.assertIn("\t# Range: 1 ~ 10000\n", out)      # comentarios intactos
        self.assertEqual(out.replace("perPlayerRadius = 250", "perPlayerRadius = 100"), SAMPLE)

    def test_tipos_distintos(self):
        out = mc.apply_updates(SAMPLE, [
            {"section": "general", "key": "enchantment_hint", "value": "ALL"},
            {"section": "general", "key": "compressDenylist", "value": ["minecraft:stone"]},
        ])
        self.assertIn('enchantment_hint = "ALL"', out)
        self.assertIn('compressDenylist = ["minecraft:stone"]', out)

    def test_clave_inexistente_falla(self):
        with self.assertRaises(KeyError):
            mc.apply_updates(SAMPLE, [{"section": "general", "key": "nope", "value": 1}])


class ValidationTests(unittest.TestCase):
    def test_fuera_de_rango(self):
        with self.assertRaisesRegex(ValueError, "fuera de rango"):
            mc.apply_updates(SAMPLE, [{"section": "general", "key": "perPlayerRadius", "value": 0}])

    def test_valor_no_permitido(self):
        with self.assertRaisesRegex(ValueError, "debe ser uno de"):
            mc.apply_updates(SAMPLE, [{"section": "general", "key": "enchantment_hint", "value": "MUCHO"}])

    def test_tipo_incorrecto(self):
        with self.assertRaises(ValueError):
            mc.apply_updates(SAMPLE, [{"section": "general", "key": "cacheRetentionTicks", "value": "diez"}])
        with self.assertRaises(ValueError):
            mc.apply_updates(SAMPLE, [{"section": "general", "key": "cacheRetentionTicks", "value": 2.5}])

    def test_texto_con_comillas_se_escapa(self):
        self.assertEqual(mc.serialize("str", 'di "hola"'), '"di \\"hola\\""')


class SaveTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.cfg = self.root / "config"
        self.cfg.mkdir()
        (self.cfg / "incontrol-server.toml").write_text(SAMPLE, encoding="utf-8")
        p = [mock.patch.object(mc, "_cfg_dir", lambda name: self.cfg),
             mock.patch.object(mc, "HERE", self.root)]
        for x in p:
            x.start(); self.addCleanup(x.stop)

    def test_guarda_con_copia_de_seguridad(self):
        r = mc.save_config("srv", "incontrol-server.toml",
                           updates=[{"section": "general", "key": "perPlayerRadius", "value": 300}])
        self.assertTrue(r["changed"])
        self.assertIn("perPlayerRadius = 300", (self.cfg / "incontrol-server.toml").read_text())
        self.assertEqual(len(list((self.root / "backups" / "configs" / "srv").glob("*.bak"))), 1)

    def test_sin_cambios_no_escribe(self):
        r = mc.save_config("srv", "incontrol-server.toml", updates=[])
        self.assertFalse(r["changed"])

    def test_json_invalido_se_rechaza_y_no_se_toca(self):
        (self.cfg / "incontrol").mkdir()
        f = self.cfg / "incontrol" / "spawn.json"
        f.write_text("[]", encoding="utf-8")
        with self.assertRaises(ValueError):
            mc.save_config("srv", "incontrol/spawn.json", json_text="{no es json")
        self.assertEqual(f.read_text(), "[]")

    def test_rutas_peligrosas(self):
        for rel in ("../x.toml", "/etc/passwd", "a/../../b.toml"):
            with self.assertRaises(ValueError):
                mc.read_config("srv", rel)

    def test_descubre_archivos_por_modid(self):
        (self.cfg / "incontrol").mkdir(exist_ok=True)
        (self.cfg / "incontrol" / "spawn.json").write_text("[]", encoding="utf-8")
        files = mc.mod_config_files("srv", "incontrol")
        self.assertEqual(files, ["incontrol-server.toml", "incontrol/spawn.json"])
        self.assertEqual(mc.mod_config_files("srv", "../etc"), [])


if __name__ == "__main__":
    unittest.main()


class AutoTests(unittest.TestCase):
    def setUp(self):
        self.f = Path(tempfile.mkdtemp()) / "auto.json"
        p = mock.patch.object(mc, "AUTO_FILE", self.f)
        p.start(); self.addCleanup(p.stop)

    def test_por_defecto_incontrol(self):
        self.assertEqual(mc.auto_mods(), {"incontrol"})

    def test_activar_y_quitar(self):
        mc.set_auto("ae2", True)
        self.assertIn("ae2", mc.auto_mods())
        mc.set_auto("incontrol", False)
        self.assertEqual(mc.auto_mods(), {"ae2"})

    def test_modid_invalido(self):
        with self.assertRaises(ValueError):
            mc.set_auto("../x", True)

    def test_mods_with_config_marca_automaticos(self):
        cfg = Path(tempfile.mkdtemp()) / "config"
        cfg.mkdir()
        (cfg / "incontrol-server.toml").write_text(SAMPLE, encoding="utf-8")
        (cfg / "ae2-common.toml").write_text(SAMPLE, encoding="utf-8")
        with mock.patch.object(mc, "_cfg_dir", lambda name: cfg):
            out = {m["modid"]: m["auto"] for m in mc.mods_with_config("srv", ["incontrol", "ae2", "otro"])}
        self.assertEqual(out, {"ae2": False, "incontrol": True})
