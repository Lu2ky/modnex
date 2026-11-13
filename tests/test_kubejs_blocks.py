"""Modelos de bloque para dibujarlos en 3D, y catálogo de fluidos, con un mod de mentira."""
import json, sys, tempfile, unittest, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.features import kubejs

PNG = b"\x89PNG\r\n\x1a\n" + b"datos"


class Ctx:
    def __init__(self, root): self.here = root; self.srv = root / "srv"
    def server_path(self, name): return str(self.srv)


def jar(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for n, v in files.items(): z.writestr(n, v if isinstance(v, bytes) else json.dumps(v))


class BlocksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name); (root / "srv/mods").mkdir(parents=True); self.ctx = Ctx(root)
        face = lambda t, **k: {"texture": t, **k}
        jar(root / "srv/mods/fake.jar", {
            "assets/fake/lang/en_us.json": {"item.fake.machine": "Machine", "item.fake.grass": "Grass", "item.fake.gem": "Gem", "block.fake.machine": "Machine",
                                              "fluid.fake.honey": "Honey", "fluid_type.fake.slime": "Slime"},
            "assets/fake/models/block/base.json": {"textures": {"side": "fake:block/side"}, "display": {"gui": {"rotation": [30, 225, 0], "scale": [0.5, 0.5, 0.5]}},
                "elements": [{"from": [0, 0, 0], "to": [16, 8, 16], "faces": {"up": face("#side"), "north": face("#side", uv=[0, 0, 16, 8])}},
                             {"from": [4, 8, 4], "to": [12, 16, 12], "rotation": {"origin": [8, 8, 8], "axis": "y", "angle": 45}, "faces": {"up": face("#side", tintindex=0, rotation=90)}}]},
            "assets/fake/models/item/machine.json": {"parent": "fake:block/base"},
            "assets/fake/models/item/grass.json": {"parent": "fake:block/base", "textures": {"side": "fake:block/other"}},
            "assets/fake/models/item/gem.json": {"parent": "minecraft:item/generated", "textures": {"layer0": "fake:item/gem"}},
            "assets/fake/textures/block/side.png": PNG, "assets/fake/textures/block/other.png": PNG, "assets/fake/textures/item/gem.png": PNG,
            "assets/fake/textures/fluid/honey_still.png": PNG, "assets/fake/textures/block/slime_still.png": PNG})

    def test_item_con_cubos(self):
        m = kubejs.block_model(self.ctx, "s", "fake:machine")
        self.assertEqual(len(m["elements"]), 2); self.assertEqual(m["tex"], ["fake:block/side"])
        self.assertEqual(m["display"]["rotation"], [30.0, 225.0, 0.0]); self.assertEqual(m["display"]["scale"], [0.5, 0.5, 0.5])

    def test_rotacion_de_elemento_tinte_y_giro_de_cara(self):
        top = kubejs.block_model(self.ctx, "s", "fake:machine")["elements"][1]
        self.assertEqual(top["rot"], {"o": [8.0, 8.0, 8.0], "a": "y", "d": 45.0})
        self.assertEqual(top["faces"]["up"], {"t": "fake:block/side", "tint": 1, "r": 90})

    def test_item_plano_no_tiene_modelo_de_cubos(self):
        self.assertIsNone(kubejs.block_model(self.ctx, "s", "fake:gem"))
        self.assertIsNone(kubejs.block_model(self.ctx, "s", "fake:no_existe"))

    def test_el_hijo_pisa_la_textura_del_padre(self):
        self.assertEqual(kubejs.block_model(self.ctx, "s", "fake:grass")["tex"], ["fake:block/other"])   # redefine «side»: gana la del hijo

    def test_lote_comparte_texturas_y_es_cacheado(self):
        models, tex = kubejs.block_models(self.ctx, "s", ["fake:machine", "fake:gem", "fake:grass"])
        self.assertEqual(sorted(tex), ["fake:block/other", "fake:block/side"]); self.assertIsNone(models["fake:gem"])   # cada textura una sola vez
        self.assertTrue(tex["fake:block/side"].startswith("data:image/png;base64,"))
        self.assertIs(kubejs.block_model(self.ctx, "s", "fake:machine"), models["fake:machine"])

    def test_id_invalido(self):
        with self.assertRaises(ValueError): kubejs.block_model(self.ctx, "s", "no es un id")

    def test_fluidos_con_nombre_y_textura(self):
        f = {x["id"]: x for x in kubejs.fluids(self.ctx, "s")}
        self.assertEqual(f["fake:honey"]["name"], "Honey"); self.assertTrue(f["fake:honey"]["icon"].startswith("data:image/png"))
        self.assertTrue(f["fake:slime"]["icon"])          # textura en block/, no en fluid/
        self.assertEqual(f["minecraft:water"]["tint"], "#3f76e4"); self.assertIn("minecraft:lava", f)


if __name__ == "__main__":
    unittest.main()
