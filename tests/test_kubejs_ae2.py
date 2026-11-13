"""Recetas de AE2 con KubeJS: validación, JSON con los formatos del jar, guardado y script generado."""
import json, sys, tempfile, unittest, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.features import kubejs_ae2 as A
from modnex.services import servers

I = lambda i: {"k": "item", "id": i}
T = lambda i: {"k": "tag", "id": i}


class Ctx:
    def __init__(self, root): self.root = root
    def server_path(self, name): return str(self.root)


def insc(**kw):
    return {"id": "proc", "type": "inscriber", "mode": "inscribe", "ingredients": {"top": I("ae2:engineering_processor_press"), "middle": I("minecraft:iron_block")},
            "result": {"count": 1, "id": "ae2:engineering_processor_press"}, **kw}


class ValidationTest(unittest.TestCase):
    def test_inscriber_inscribe_y_press(self):
        r = A.clean_recipe(insc())
        self.assertEqual(r["mode"], "inscribe"); self.assertEqual(set(r["ingredients"]), {"top", "middle"})
        p = A.clean_recipe(insc(mode="press", ingredients={"top": I("a:t"), "middle": T("c:gems/diamond"), "bottom": I("a:b")}))
        self.assertEqual(p["ingredients"]["middle"], T("c:gems/diamond"))

    def test_inscriber_reglas_de_piezas(self):
        with self.assertRaises(ValueError): A.clean_recipe(insc(mode="press", ingredients={"top": I("a:t"), "middle": I("a:m")}))     # press sin abajo
        with self.assertRaises(ValueError): A.clean_recipe(insc(ingredients={"top": I("a:t"), "middle": I("a:m"), "bottom": I("a:b")}))  # inscribir con abajo
        with self.assertRaises(ValueError): A.clean_recipe(insc(ingredients={"top": I("a:t")}))                                        # sin centro
        with self.assertRaises(ValueError): A.clean_recipe(insc(mode="x"))

    def test_charger_y_transform(self):
        self.assertEqual(A.clean_recipe({"id": "c", "type": "charger", "ingredient": I("minecraft:book"), "result": {"id": "ae2:guide"}})["result"], {"id": "ae2:guide", "count": 1})
        t = A.clean_recipe({"id": "t", "type": "transform", "ingredients": [I("a:x"), T("c:dusts/ender_pearl")], "circumstance": "explosion", "result": {"id": "a:y", "count": 2}})
        self.assertEqual(t["circumstance"], "explosion")
        for bad in ([I("a:x")], [I("a:x")] * 10):
            with self.assertRaises(ValueError): A.clean_recipe({"id": "t", "type": "transform", "ingredients": bad, "result": {"id": "a:y"}})
        with self.assertRaises(ValueError): A.clean_recipe({"id": "t", "type": "transform", "ingredients": [I("a:x"), I("a:z")], "circumstance": "lluvia", "result": {"id": "a:y"}})

    def test_entropy_bloque_o_fluido(self):
        e = A.clean_recipe({"id": "e", "type": "entropy", "mode": "heat", "input": {"k": "block", "id": "minecraft:ice"}, "output": {"k": "fluid", "id": "minecraft:water"}})
        self.assertEqual((e["input"]["k"], e["output"]["k"]), ("block", "fluid"))
        with self.assertRaises(ValueError): A.clean_recipe({"id": "e", "type": "entropy", "mode": "heat", "input": {"k": "tag", "id": "c:x"}, "output": {"k": "block", "id": "a:b"}})
        with self.assertRaises(ValueError): A.clean_recipe({"id": "e", "type": "entropy", "mode": "frio", "input": {"k": "block", "id": "a:b"}, "output": {"k": "block", "id": "a:c"}})
        with self.assertRaises(ValueError): A.clean_recipe({"id": "e", "type": "entropy", "mode": "cool", "input": {"k": "block", "id": "a:b"}, "output": {"k": "block", "id": "a:b"}})

    def test_slug_tipo_y_nombres_repetidos(self):
        with self.assertRaises(ValueError): A.clean_recipe(insc(id="Mal Nombre"))
        with self.assertRaises(ValueError): A.clean_recipe(insc(type="matter_cannon"))
        with self.assertRaises(ValueError): A.clean_list([insc(), insc()])
        with self.assertRaises(ValueError): A.clean_recipe(insc(id='x"); evil(); ("'))


class JsonTest(unittest.TestCase):
    def test_formatos_como_los_del_jar(self):
        j = A.to_json(A.clean_recipe(insc(mode="press", ingredients={"top": I("a:t"), "middle": I("a:m"), "bottom": T("c:b")})))
        self.assertEqual(j, {"type": "ae2:inscriber", "mode": "press", "ingredients": {"top": {"item": "a:t"}, "middle": {"item": "a:m"}, "bottom": {"tag": "c:b"}},
                             "result": {"count": 1, "id": "ae2:engineering_processor_press"}})
        self.assertEqual(A.to_json(A.clean_recipe({"id": "c", "type": "charger", "ingredient": I("minecraft:compass"), "result": {"id": "ae2:meteorite_compass"}})),
                         {"type": "ae2:charger", "ingredient": {"item": "minecraft:compass"}, "result": {"count": 1, "id": "ae2:meteorite_compass"}})
        t = A.to_json(A.clean_recipe({"id": "t", "type": "transform", "ingredients": [I("a:x"), I("a:z")], "result": {"id": "a:y"}}))
        self.assertNotIn("circumstance", t)
        self.assertEqual(A.to_json(A.clean_recipe({"id": "t", "type": "transform", "ingredients": [I("a:x"), I("a:z")], "circumstance": "explosion", "result": {"id": "a:y"}}))["circumstance"], {"type": "explosion"})
        self.assertEqual(A.to_json(A.clean_recipe({"id": "e", "type": "entropy", "mode": "heat", "input": {"k": "block", "id": "minecraft:cobblestone"}, "output": {"k": "block", "id": "minecraft:stone"}})),
                         {"type": "ae2:entropy", "mode": "heat", "input": {"block": {"id": "minecraft:cobblestone"}}, "output": {"block": {"id": "minecraft:stone"}}})

    def test_items_que_se_comprueban(self):
        r = A.clean_recipe(insc(mode="press", ingredients={"top": I("a:t"), "middle": T("c:m"), "bottom": I("a:b")}))
        self.assertEqual(A.item_ids(r), ["a:b", "a:t", "ae2:engineering_processor_press"])
        e = A.clean_recipe({"id": "e", "type": "entropy", "mode": "heat", "input": {"k": "block", "id": "minecraft:air"}, "output": {"k": "fluid", "id": "minecraft:water"}})
        self.assertEqual(A.item_ids(e), [])

    def test_script_seguro_y_con_json(self):
        s = A.build_script([A.clean_recipe(insc())])
        self.assertIn("event.custom(r.recipe).id('modnex:ae2_' + r.id)", s); self.assertIn('"type": "ae2:inscriber"', s)


class SaveTest(unittest.TestCase):
    def test_guarda_escribe_script_y_borra_al_quedar_vacio(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "kubejs").mkdir(); ctx = Ctx(root)
            A.save(ctx, "s", [insc()])
            self.assertTrue((root / "kubejs" / A.SCRIPT).is_file()); self.assertEqual(len(A.load(ctx, "s")["recipes"]), 1)
            A.save(ctx, "s", [])
            self.assertFalse((root / "kubejs" / A.SCRIPT).exists())

    def test_sin_kubejs_error(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError): A.save(Ctx(Path(d)), "s", [insc()])


class AddonTest(unittest.TestCase):
    def test_detecta_applied_energistics_pero_no_ae2wtlib(self):
        with tempfile.TemporaryDirectory() as d:
            mods = Path(d) / "mods"; mods.mkdir()
            (mods / "appliedenergistics2-19.2.19.jar").write_text(""); (mods / "ae2wtlib-19.5.1.jar").write_text("")
            self.assertEqual(servers.addons_of(d), ["ae2"])


if __name__ == "__main__":
    unittest.main()
