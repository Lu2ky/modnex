"""Distribución de los huecos de las recetas existentes en la interfaz del juego."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.features.kubejs import recipe_layout as lay


def item(i): return {"item": i}


class ShapedTest(unittest.TestCase):
    def test_posicion_por_fila_y_columna(self):
        r = lay({"type": "minecraft:crafting_shaped", "pattern": ["XX ", " Y "], "key": {"X": item("a:b"), "Y": {"tag": "c:t"}},
                 "result": {"id": "a:r", "count": 4}})
        self.assertEqual(r["skin"], "crafting")
        self.assertEqual(r["slots"], {"g0": {"id": "a:b"}, "g1": {"id": "a:b"}, "g4": {"id": "#c:t"}, "out": {"id": "a:r", "count": 4}})

    def test_ingrediente_con_varias_opciones_toma_la_primera(self):
        r = lay({"type": "minecraft:crafting_shaped", "pattern": ["X"], "key": {"X": [item("a:uno"), item("a:dos")]}, "result": {"id": "a:r"}})
        self.assertEqual(r["slots"]["g0"], {"id": "a:uno"})

    def test_patron_imposible_no_se_dibuja(self):
        self.assertIsNone(lay({"type": "minecraft:crafting_shaped", "pattern": ["XXXX"], "key": {"X": item("a:b")}, "result": {"id": "a:r"}}))
        self.assertIsNone(lay({"type": "minecraft:crafting_shaped", "pattern": ["X"], "key": "mal", "result": {"id": "a:r"}}))


class OtherTypesTest(unittest.TestCase):
    def test_sin_forma_llena_en_orden(self):
        r = lay({"type": "minecraft:crafting_shapeless", "ingredients": [item("a:x"), item("a:y")], "result": {"id": "a:r"}})
        self.assertEqual(sorted(k for k in r["slots"] if k.startswith("g")), ["g0", "g1"])

    def test_cada_tipo_de_coccion_elige_su_interfaz(self):
        for t, skin in (("smelting", "furnace"), ("blasting", "blast_furnace"), ("smoking", "smoker"), ("campfire_cooking", "campfire"), ("stonecutting", "stonecutter")):
            r = lay({"type": "minecraft:" + t, "ingredient": item("a:in"), "result": {"id": "a:out", "count": 2}})
            self.assertEqual(r["skin"], skin, t)
            self.assertEqual(r["slots"]["g0"], {"id": "a:in"}); self.assertEqual(r["slots"]["out"]["count"], 2)

    def test_resultado_como_texto(self):
        self.assertEqual(lay({"type": "minecraft:smelting", "ingredient": item("a:in"), "result": "a:out"})["slots"]["out"], {"id": "a:out", "count": 1})

    def test_herreria(self):
        r = lay({"type": "minecraft:smithing_transform", "template": item("a:t"), "base": item("a:b"), "addition": item("a:c"), "result": {"id": "a:r"}})
        self.assertEqual(r["skin"], "smithing"); self.assertEqual(sorted(r["slots"]), ["addition", "base", "result", "template"])

    def test_lo_que_no_se_sabe_dibujar_devuelve_none(self):
        for bad in ({"type": "minecraft:crafting_transmute", "input": item("a:t"), "result": {"id": "a:r"}},
                    {"type": "mekanism:crushing", "input": item("a:t"), "output": {"id": "a:r"}}, {"type": "create:item_copying", "results": [{"id": "a:r"}]},
                    {"type": "minecraft:smelting", "ingredient": item("a:in")}, "no es un dict", None):
            self.assertIsNone(lay(bad), bad)


if __name__ == "__main__":
    unittest.main()
