"""Tablas de botín con formularios: validación, JSON de datapack, lectura de tablas reales y archivos escritos."""
import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.features import kubejs_loot as kl


class Ctx:
    def __init__(self, root): self.root = root
    def server_path(self, name): return str(self.root)


def rule(**kw): return {"id": "r1", "kind": "block", "target": "minecraft:diamond_ore", "drops": [{"item": "minecraft:diamond"}], **kw}


class ValidationTest(unittest.TestCase):
    def test_regla_basica(self):
        r = kl.clean_rule(rule())
        self.assertEqual(r["drops"], [{"item": "minecraft:diamond", "min": 1, "max": 1}]); self.assertTrue(r["survives"])

    def test_puede_no_soltar_nada(self):
        self.assertEqual(kl.clean_rule(rule(drops=[]))["drops"], [])
        self.assertEqual(kl.to_json(kl.clean_rule(rule(drops=[])))["pools"], [])

    def test_valores_invalidos(self):
        for bad in (rule(kind="item"), rule(target="no valido"), rule(id="Mal Nombre"), rule(drops="x"), rule(drops=[{"item": "a:b", "min": 3, "max": 2}]),
                    rule(drops=[{"item": "a:b", "max": 65}]), rule(drops=[{"item": "a:b", "chance": 0}]), rule(drops=[{"item": "a:b", "chance": 1.5}]),
                    rule(drops=[{"item": 'a:b"); x(); ("'}])):
            with self.assertRaises(ValueError, msg=str(bad)): kl.clean_rule(bad)

    def test_cada_tipo_solo_admite_lo_suyo(self):
        with self.assertRaises(ValueError): kl.clean_rule(rule(drops=[{"item": "a:b", "bonus": "looting"}]))             # saqueo no es de bloques
        with self.assertRaises(ValueError): kl.clean_rule(rule(kind="entity", drops=[{"item": "a:b", "bonus": "fortune"}]))
        with self.assertRaises(ValueError): kl.clean_rule(rule(kind="entity", drops=[{"item": "a:b", "when": "silk"}]))
        with self.assertRaises(ValueError): kl.clean_rule(rule(drops=[{"item": "a:b", "player": True}]))

    def test_una_regla_por_objetivo(self):
        with self.assertRaises(ValueError): kl.clean_list([rule(), rule(id="r2")])
        kl.clean_list([rule(), rule(id="r2", kind="entity", target="minecraft:diamond_ore")])


class JsonTest(unittest.TestCase):
    def test_cantidad_fija_y_rango(self):
        j = kl.to_json(kl.clean_rule(rule(drops=[{"item": "a:fijo", "min": 3, "max": 3}, {"item": "a:rango", "min": 1, "max": 4}, {"item": "a:uno"}])))
        f = [p["entries"][0].get("functions") for p in j["pools"]]
        self.assertEqual(f[0], [{"function": "minecraft:set_count", "count": 3.0, "add": False}])
        self.assertEqual(f[1][0]["count"], {"type": "minecraft:uniform", "min": 1.0, "max": 4.0}); self.assertIsNone(f[2])

    def test_formato_de_vanilla_para_probabilidad_toque_de_seda_y_bonus(self):
        r = kl.clean_rule(rule(drops=[{"item": "a:b", "chance": 0.25, "bonus": "fortune", "when": "nosilk"}, {"item": "minecraft:diamond_ore", "when": "silk"}]))
        p = kl.to_json(r)["pools"]
        self.assertIn({"condition": "minecraft:random_chance", "chance": 0.25}, p[0]["conditions"])
        self.assertEqual(p[0]["conditions"][1]["condition"], "minecraft:inverted"); self.assertEqual(p[1]["conditions"][0]["condition"], "minecraft:match_tool")
        self.assertEqual(p[0]["entries"][0]["functions"][0], {"function": "minecraft:apply_bonus", "enchantment": "minecraft:fortune", "formula": "minecraft:ore_drops"})
        self.assertEqual(p[0]["conditions"][-1], {"condition": "minecraft:survives_explosion"})

    def test_mob_con_saqueo_y_solo_jugador(self):
        j = kl.to_json(kl.clean_rule(rule(kind="entity", target="minecraft:zombie", drops=[{"item": "a:b", "bonus": "looting", "player": True, "min": 0, "max": 2}])))
        self.assertEqual(j["type"], "minecraft:entity"); self.assertEqual(j["random_sequence"], "minecraft:entities/zombie")
        self.assertEqual(j["pools"][0]["conditions"], [{"condition": "minecraft:killed_by_player"}])
        self.assertEqual(j["pools"][0]["entries"][0]["functions"][1]["function"], "minecraft:enchanted_count_increase")

    def test_ruta_del_archivo(self):
        self.assertEqual(kl.rel_path(kl.clean_rule(rule(target="create:zinc_ore"))), "data/create/loot_table/blocks/zinc_ore.json")
        self.assertEqual(kl.rel_path(kl.clean_rule(rule(kind="entity", target="minecraft:cow"))), "data/minecraft/loot_table/entities/cow.json")


# Tablas reales de vanilla 1.21.1 (resumidas)
DIAMOND = {"type": "minecraft:block", "pools": [{"bonus_rolls": 0.0, "rolls": 1.0, "entries": [{"type": "minecraft:alternatives", "children": [
    {"type": "minecraft:item", "name": "minecraft:diamond_ore", "conditions": [{"condition": "minecraft:match_tool", "predicate": {"predicates": {"minecraft:enchantments": [{"enchantments": "minecraft:silk_touch", "levels": {"min": 1}}]}}}]},
    {"type": "minecraft:item", "name": "minecraft:diamond", "functions": [{"enchantment": "minecraft:fortune", "formula": "minecraft:ore_drops", "function": "minecraft:apply_bonus"}, {"function": "minecraft:explosion_decay"}]}]}]}]}
ZOMBIE = {"type": "minecraft:entity", "pools": [
    {"rolls": 1.0, "entries": [{"type": "minecraft:item", "name": "minecraft:rotten_flesh", "functions": [{"add": False, "count": {"type": "minecraft:uniform", "max": 2.0, "min": 0.0}, "function": "minecraft:set_count"},
                                                                                              {"count": {"type": "minecraft:uniform", "max": 1.0, "min": 0.0}, "enchantment": "minecraft:looting", "function": "minecraft:enchanted_count_increase"}]}]},
    {"rolls": 1.0, "conditions": [{"condition": "minecraft:killed_by_player"}, {"condition": "minecraft:random_chance_with_enchanted_bonus", "unenchanted_chance": 0.025, "enchantment": "minecraft:looting", "enchanted_chance": {}}],
     "entries": [{"type": "minecraft:item", "name": "minecraft:iron_ingot"}]}]}
COW = {"type": "minecraft:entity", "pools": [{"rolls": 1.0, "entries": [{"type": "minecraft:item", "name": "minecraft:beef", "functions": [
    {"function": "minecraft:set_count", "count": {"type": "minecraft:uniform", "min": 1.0, "max": 3.0}, "add": False}, {"function": "minecraft:furnace_smelt", "conditions": [{"condition": "minecraft:entity_properties"}]}]}]}]}


class SummarizeTest(unittest.TestCase):
    def test_mineral_con_toque_de_seda_y_fortuna(self):
        d = kl.summarize(DIAMOND)
        self.assertEqual([(x["item"], x.get("when"), x.get("bonus")) for x in d], [("minecraft:diamond_ore", "silk", None), ("minecraft:diamond", "nosilk", "fortune")])
        self.assertFalse(any(x.get("complex") for x in d))

    def test_mob_con_saqueo_cantidad_probabilidad_y_jugador(self):
        d = kl.summarize(ZOMBIE)
        self.assertEqual((d[0]["min"], d[0]["max"], d[0]["bonus"]), (0, 2, "looting"))
        self.assertEqual((d[1]["chance"], d[1]["player"], d[1]["bonus"]), (0.025, True, "looting"))

    def test_lo_que_no_se_sabe_reproducir_se_marca_condicional(self):
        self.assertTrue(kl.summarize(COW)[0]["complex"])           # furnace_smelt si el mob ardía

    def test_ida_y_vuelta_de_una_tabla_simple(self):
        r = kl.clean_rule(rule(drops=[{k: v for k, v in x.items() if k != "complex"} for x in kl.summarize(DIAMOND)]))
        again = kl.summarize(kl.to_json(r))
        self.assertEqual([(x["item"], x.get("when"), x.get("bonus")) for x in again], [("minecraft:diamond_ore", "silk", None), ("minecraft:diamond", "nosilk", "fortune")])

    def test_tabla_vacia_o_rota(self):
        self.assertEqual(kl.summarize({}), []); self.assertEqual(kl.summarize({"pools": [{"entries": [{"type": "minecraft:dynamic"}]}]})[0]["complex"], True)


class StoreTest(unittest.TestCase):
    def test_escribe_los_archivos_y_borra_solo_los_suyos(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "kubejs").mkdir(); (Path(d) / "kubejs/data/minecraft/loot_table/blocks").mkdir(parents=True)
            ajeno = Path(d) / "kubejs/data/minecraft/loot_table/blocks/ajeno.json"; ajeno.write_text("{}")
            ctx = Ctx(Path(d))
            kl.save(ctx, "s", [rule(), rule(id="r2", target="minecraft:stone", drops=[])])
            a, b = Path(d) / "kubejs/data/minecraft/loot_table/blocks/diamond_ore.json", Path(d) / "kubejs/data/minecraft/loot_table/blocks/stone.json"
            self.assertTrue(a.is_file() and b.is_file()); self.assertEqual(json.loads(b.read_text())["pools"], [])
            kl.save(ctx, "s", [rule()])
            self.assertTrue(a.is_file()); self.assertFalse(b.exists()); self.assertTrue(ajeno.is_file())     # el archivo ajeno no se toca
            kl.save(ctx, "s", [])
            self.assertFalse(a.exists()); self.assertTrue(ajeno.is_file()); self.assertEqual(kl.load(ctx, "s")["rules"], [])


if __name__ == "__main__":
    unittest.main()
