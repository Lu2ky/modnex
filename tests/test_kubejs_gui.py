"""Texturas de las interfaces de Minecraft para el editor de recetas."""
import base64, json, sys, tempfile, unittest, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.features import kubejs

PNG = b"\x89PNG\r\n\x1a\n" + b"datos-de-prueba"


class Ctx:
    def __init__(self, root): self.here = root; self.srv = root / "srv"
    def server_path(self, name): return str(self.srv)


class GuiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.ctx = Ctx(self.root)
        self.ctx.srv.mkdir()
        (self.ctx.srv / ".manager.json").write_text(json.dumps({"mc": "1.21.1"}))
        kubejs._GUI.update(key=None, tex={})

    def jar(self, names):
        (self.root / "cache").mkdir(exist_ok=True)
        with zipfile.ZipFile(self.root / "cache" / "minecraft-1.21.1-client.jar", "w") as z:
            for n in names: z.writestr(f"assets/minecraft/textures/gui/container/{n}.png", PNG)

    def test_sin_cliente_descargado(self):
        self.assertEqual(kubejs.gui_textures(self.ctx, "s"), {})

    def test_devuelve_data_uri_de_cada_piel(self):
        self.jar(["crafting_table", "furnace", "smithing"])
        out = kubejs.gui_textures(self.ctx, "s")
        self.assertEqual(sorted(out), ["crafting", "furnace", "smithing"])
        self.assertEqual(base64.b64decode(out["crafting"].split(",", 1)[1]), PNG)
        self.assertTrue(out["crafting"].startswith("data:image/png;base64,"))

    def test_las_que_faltan_se_omiten(self):
        self.jar(["stonecutter"])
        self.assertEqual(list(kubejs.gui_textures(self.ctx, "s")), ["stonecutter"])

    def test_jar_roto_no_rompe(self):
        (self.root / "cache").mkdir()
        (self.root / "cache" / "minecraft-1.21.1-client.jar").write_bytes(b"no soy un zip")
        self.assertEqual(kubejs.gui_textures(self.ctx, "s"), {})

    def test_se_recalcula_si_cambia_el_jar(self):
        self.jar(["furnace"]); a = kubejs.gui_textures(self.ctx, "s")
        self.jar(["furnace", "smoker"]); b = kubejs.gui_textures(self.ctx, "s")
        self.assertEqual(sorted(a), ["furnace"]); self.assertEqual(sorted(b), ["furnace", "smoker"])


if __name__ == "__main__":
    unittest.main()
