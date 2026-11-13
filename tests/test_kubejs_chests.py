"""Botín de cofres: grupos con tiradas, objetos con peso, lectura de tablas de vanilla y archivos escritos."""
import json, sys, tempfile, unittest, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.features import kubejs, kubejs_loot as kl


class Ctx:
    def __init__(self, root): self.root = root; self.here = root
    def server_path(self, name): return str(self.root)


def chest(**kw):
    return {"id": "mina", "kind": "chest", "target": "minecraft:abandoned_mineshaft", "pools": [{"min": 2, "max": 4}],
            "drops": [{"item": "minecraft:diamond", "weight": 1}, {"item": "minecraft:apple", "min": 1, "max": 3, "weight": 9}], **kw}


class ValidationTest(unittest.TestCase):
    def test_regla_basica(self):
        r = kl.clean_rule(chest())
        self.assertEqual(r["kind"], "chest"); self.assertEqual(r["pools"], [{"min": 2, "max": 4}])
        self.assertEqual(r["drops"][1], {"item": "minecraft:apple", "min": 1, "max": 3, "weight": 9, "pool": 0}); self.assertFalse(r["survives"])

    def test_valores_invalidos(self):
        for bad in (chest(pools=[]), chest(pools="x"), chest(pools=[{"min": 3, "max": 1}]), chest(pools=[{"min": 0, "max": 99}]), chest(pools=[{}] * 9),
                    chest(drops=[{"item": "a:b", "weight": 0}]), chest(drops=[{"item": "a:b", "weight": 5000}]), chest(drops=[{"item": "a:b", "pool": 3}]),
                    chest(drops=[{"item": "a:b", "min": 3, "max": 2}]), chest(drops=[{"item": 'a:b"); x(); ("'}]), chest(drops=[{"item": "a:b"}] * 81)):
            with self.assertRaises(ValueError, msg=str(bad)): kl.clean_rule(bad)

    def test_ignora_lo_que_no_es_de_cofres(self):
        r = kl.clean_rule(chest(drops=[{"item": "a:b", "chance": 0.5, "bonus": "looting", "player": True, "when": "silk"}]))
        self.assertEqual(r["drops"], [{"item": "a:b", "min": 1, "max": 1, "weight": 10, "pool": 0}])

    def test_rutas_con_subcarpetas(self):
        self.assertEqual(kl.rel_path(kl.clean_rule(chest(target="minecraft:village/village_armorer"))), "data/minecraft/loot_table/chests/village/village_armorer.json")


class JsonTest(unittest.TestCase):
    def test_formato_de_vanilla(self):
        j = kl.to_json(kl.clean_rule(chest(pools=[{"min": 2, "max": 4}, {"min": 1, "max": 1}], drops=[
            {"item": "a:x", "weight": 5}, {"item": "a:y", "min": 3, "max": 3, "weight": 2, "pool": 1}])))
        self.assertEqual(j["type"], "minecraft:chest"); self.assertEqual(j["random_sequence"], "minecraft:chests/abandoned_mineshaft")
        self.assertEqual(j["pools"][0]["rolls"], {"type": "minecraft:uniform", "min": 2.0, "max": 4.0}); self.assertEqual(j["pools"][1]["rolls"], 1.0)
        self.assertEqual(j["pools"][0]["entries"], [{"type": "minecraft:item", "name": "a:x", "weight": 5}])
        self.assertEqual(j["pools"][1]["entries"][0]["functions"], [{"function": "minecraft:set_count", "count": 3.0, "add": False}])


VANILLA = {"type": "minecraft:chest", "pools": [
    {"rolls": {"type": "minecraft:uniform", "min": 2.0, "max": 4.0}, "bonus_rolls": 0.0, "entries": [
        {"type": "minecraft:item", "name": "minecraft:golden_apple", "weight": 20},
        {"type": "minecraft:item", "name": "minecraft:iron_ingot", "weight": 10, "functions": [{"function": "minecraft:set_count", "count": {"type": "minecraft:uniform", "min": 1.0, "max": 5.0}, "add": False}]},
        {"type": "minecraft:item", "name": "minecraft:book", "weight": 1, "functions": [{"function": "minecraft:enchant_with_levels", "levels": 30}]},
        {"type": "minecraft:empty", "weight": 5}]},
    {"rolls": 3.0, "bonus_rolls": 0.0, "entries": [{"type": "minecraft:tag", "name": "minecraft:logs", "weight": 1, "expand": True}]}]}


class ReadTest(unittest.TestCase):
    def test_lee_grupos_pesos_y_marca_lo_complejo(self):
        got = kl.summarize_chest(VANILLA)
        self.assertEqual([(p["min"], p["max"]) for p in got["pools"]], [(2, 4), (3, 3)])
        by = {d["item"]: d for d in got["drops"]}
        self.assertEqual((by["minecraft:golden_apple"]["weight"], by["minecraft:golden_apple"]["pool"]), (20, 0)); self.assertNotIn("complex", by["minecraft:golden_apple"])
        self.assertEqual((by["minecraft:iron_ingot"]["min"], by["minecraft:iron_ingot"]["max"]), (1, 5))
        self.assertTrue(by["minecraft:book"]["complex"])         # enchant_with_levels: no se reproduce
        self.assertTrue(by["?"]["complex"] and by["#minecraft:logs"]["complex"] and by["#minecraft:logs"]["pool"] == 1)

    def test_tabla_rota(self):
        self.assertEqual(kl.summarize_chest({}), {"pools": [], "drops": []}); self.assertEqual(kl.summarize_chest(None), {"pools": [], "drops": []})


class IntegrationTest(unittest.TestCase):
    def test_indice_objetivos_actual_y_guardado(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "mods").mkdir(); (root / "kubejs").mkdir()
            with zipfile.ZipFile(root / "mods/fake.jar", "w") as z:
                z.writestr("data/fake/loot_table/chests/dungeon/vault.json", json.dumps(VANILLA))
                z.writestr("data/fake/loot_table/blocks/rock.json", "{}")
            ctx = Ctx(root)
            t = kl.targets(ctx, "s", "chest")
            self.assertEqual([x["id"] for x in t], ["fake:dungeon/vault"])
            self.assertEqual([x["id"] for x in kl.targets(ctx, "s", "block")], ["fake:rock"])
            cur = kl.current(ctx, "s", "chest", "fake:dungeon/vault")
            self.assertTrue(cur["exists"] and cur["complex"] and len(cur["pools"]) == 2 and len(cur["drops"]) == 5)
            r = chest(target="fake:dungeon/vault")
            kl.save(ctx, "s", [r])
            f = root / "kubejs/data/fake/loot_table/chests/dungeon/vault.json"
            self.assertEqual(json.loads(f.read_text())["type"], "minecraft:chest")
            self.assertEqual(kl.current(ctx, "s", "chest", "fake:dungeon/vault")["rule"]["kind"], "chest")
            kl.save(ctx, "s", [])
            self.assertFalse(f.exists())

    def test_otros_tipos_siguen_igual(self):
        self.assertEqual(kl.KINDS, ("block", "entity", "chest"))
        with self.assertRaises(ValueError): kl.targets(Ctx(Path(".")), "s", "item")


if __name__ == "__main__":
    unittest.main()
