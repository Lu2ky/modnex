"""Recetas de Create hechas con formularios: validación, JSON de Create, script generado y almacenamiento."""
import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.features import kubejs, kubejs_create as kc


def item(i): return {"k": "item", "id": i}
def out(i, **kw): return {"k": "item", "id": i, **kw}
def fluid(i, a=1000): return {"k": "fluid", "id": i, "amount": a}
def rec(**kw): return {"id": "r1", **kw}


class Ctx:
    def __init__(self, root): self.root = root
    def server_path(self, name): return str(self.root)


class ValidationTest(unittest.TestCase):
    def test_prensa_basica(self):
        r = kc.clean_recipe(rec(type="pressing", ins=[item("a:b")], outs=[out("a:c")]))
        self.assertEqual(kc.to_json(r), {"type": "create:pressing", "ingredients": [{"item": "a:b"}], "results": [{"id": "a:c"}]})

    def test_cada_tipo_tiene_su_numero_de_ingredientes(self):
        for bad in (rec(type="pressing", ins=[], outs=[out("a:c")]), rec(type="pressing", ins=[item("a:b"), item("a:b")], outs=[out("a:c")]),
                    rec(type="deploying", ins=[item("a:b")], outs=[out("a:c")]), rec(type="pressing", ins=[item("a:b")], outs=[])):
            with self.assertRaises(ValueError): kc.clean_recipe(bad)

    def test_solo_algunas_maquinas_admiten_fluidos(self):
        with self.assertRaises(ValueError): kc.clean_recipe(rec(type="pressing", ins=[fluid("minecraft:water")], outs=[out("a:c")]))
        with self.assertRaises(ValueError): kc.clean_recipe(rec(type="crushing", ins=[item("a:b")], outs=[fluid("minecraft:lava")]))
        kc.clean_recipe(rec(type="mixing", ins=[item("a:b"), fluid("minecraft:water")], outs=[fluid("minecraft:lava", 50)]))

    def test_mezclado_con_calor_tiempo_y_probabilidad(self):
        r = kc.clean_recipe(rec(type="mixing", ins=[item("a:b"), fluid("minecraft:water", 500)], outs=[out("a:c", count=2, chance=0.5)], heat="superheated", time=100))
        j = kc.to_json(r)
        self.assertEqual(j["heat_requirement"], "superheated"); self.assertEqual(j["processing_time"], 100)
        self.assertEqual(j["ingredients"][1], {"type": "neoforge:single", "fluid": "minecraft:water", "amount": 500})
        self.assertEqual(j["results"][0], {"id": "a:c", "count": 2, "chance": 0.5})

    def test_valores_fuera_de_rango(self):
        base = dict(type="crushing", ins=[item("a:b")])
        for bad in (dict(outs=[out("a:c", chance=0)]), dict(outs=[out("a:c", chance=1.5)]), dict(outs=[out("a:c", count=65)]),
                    dict(outs=[out("a:c")], time=0), dict(outs=[out("a:c")], time=10 ** 6)):
            with self.assertRaises(ValueError, msg=str(bad)): kc.clean_recipe(rec(**base, **bad))

    def test_id_invalido(self):
        with self.assertRaises(ValueError): kc.clean_recipe(rec(type="pressing", ins=[item('a:b"); evil(); ("')], outs=[out("a:c")]))
        with self.assertRaises(ValueError): kc.clean_recipe({"id": "Mal Nombre", "type": "pressing", "ins": [item("a:b")], "outs": [out("a:c")]})

    def test_surtidor_y_drenador_ordenan_item_y_fluido(self):
        f = kc.clean_recipe(rec(type="filling", ins=[fluid("minecraft:water", 250), item("minecraft:bucket")], outs=[out("minecraft:water_bucket")]))
        self.assertEqual([i["k"] for i in f["ins"]], ["item", "fluid"])
        e = kc.clean_recipe(rec(type="emptying", ins=[item("minecraft:honey_bottle")], outs=[fluid("create:honey", 250), out("minecraft:glass_bottle")]))
        self.assertEqual([o["k"] for o in e["outs"]], ["item", "fluid"])
        with self.assertRaises(ValueError): kc.clean_recipe(rec(type="filling", ins=[item("a:b"), item("a:c")], outs=[out("a:d")]))

    def test_fluido_por_etiqueta_se_escribe_como_neoforge_tag(self):
        r = kc.clean_recipe(rec(type="filling", ins=[item("minecraft:glass_bottle"), fluid("#c:honey", 250)], outs=[out("minecraft:honey_bottle")]))
        self.assertEqual(kc.to_json(r)["ingredients"][1], {"type": "neoforge:tag", "tag": "c:honey", "amount": 250})
        with self.assertRaises(ValueError): kc.clean_recipe(rec(type="filling", ins=[item("a:b"), fluid("#mal etiqueta", 250)], outs=[out("a:c")]))

    def test_desplegador_con_item_que_se_conserva(self):
        j = kc.to_json(kc.clean_recipe(rec(type="deploying", ins=[item("a:b"), item("a:c")], outs=[out("a:d")], keep=True)))
        self.assertTrue(j["keep_held_item"])


class FanTest(unittest.TestCase):
    """El ventilador: el catalizador decide el tipo de receta."""
    def test_agua_y_fuego_azul_son_recetas_de_create(self):
        for t, name in (("splashing", "create:splashing"), ("haunting", "create:haunting")):
            j = kc.to_json(kc.clean_recipe(rec(type=t, ins=[item("a:b")], outs=[out("a:c", chance=0.5)])))
            self.assertEqual(j["type"], name); self.assertEqual(j["results"][0]["chance"], 0.5)

    def test_fuego_y_lava_son_recetas_de_vanilla(self):
        for t in ("smoking", "blasting"):
            j = kc.to_json(kc.clean_recipe(rec(type=t, ins=[{"k": "tag", "id": "c:raw"}], outs=[out("a:c", count=2)])))
            self.assertEqual(j["type"], "minecraft:" + t); self.assertEqual(j["ingredient"], {"tag": "c:raw"}); self.assertEqual(j["result"], {"id": "a:c", "count": 2})
            self.assertEqual((j["cookingtime"], j["experience"]), (100, 0.0)); self.assertNotIn("ingredients", j)

    def test_las_de_vanilla_no_admiten_probabilidad_ni_varios_resultados(self):
        with self.assertRaises(ValueError): kc.clean_recipe(rec(type="smoking", ins=[item("a:b")], outs=[out("a:c", chance=0.5)]))
        with self.assertRaises(ValueError): kc.clean_recipe(rec(type="blasting", ins=[item("a:b")], outs=[out("a:c"), out("a:d")]))

    def test_los_cuatro_catalizadores_estan_declarados(self):
        self.assertEqual(kc.FAN, {"water": "splashing", "fire": "smoking", "lava": "blasting", "soul_fire": "haunting"})
        for t in kc.FAN.values():
            self.assertEqual(kc.TYPES[t]["machine"], "create:encased_fan"); self.assertTrue(kc.TYPES[t]["extra"] and kc.TYPES[t]["catalyst"])


class OtherShapesTest(unittest.TestCase):
    def test_fabricador_mecanico(self):
        r = kc.clean_recipe(rec(type="mechanical_crafting", pattern=[" A ", "ABA", " A "], key={"A": item("a:x"), "B": {"k": "tag", "id": "c:t"}}, result=out("a:r", count=2)))
        j = kc.to_json(r)
        self.assertEqual(j["pattern"], [" A ", "ABA", " A "]); self.assertEqual(j["key"]["B"], {"tag": "c:t"}); self.assertEqual(j["result"], {"id": "a:r", "count": 2})
        self.assertFalse(j["show_notification"])

    def test_fabricador_rechaza_formas_imposibles(self):
        for bad in (dict(pattern=["A", "AA"], key={"A": item("a:x")}), dict(pattern=["A" * 10], key={"A": item("a:x")}), dict(pattern=["AB"], key={"A": item("a:x")}),
                    dict(pattern=["  "], key={}), dict(pattern=["a"], key={"a": item("a:x")})):
            with self.assertRaises(ValueError, msg=str(bad)): kc.clean_recipe(rec(type="mechanical_crafting", result=out("a:r"), **bad))

    def test_ensamblaje_en_secuencia(self):
        r = kc.clean_recipe(rec(type="sequenced_assembly", input={"k": "tag", "id": "c:plates/gold"}, transitional="create:incomplete_x", loops=3,
                                steps=[{"t": "deploying", "held": item("create:cogwheel")}, {"t": "filling", "fluid": {"id": "minecraft:lava", "amount": 250}}, {"t": "pressing"}],
                                outs=[{"id": "create:x", "weight": 120}, {"id": "minecraft:iron_ingot"}]))
        j = kc.to_json(r)
        self.assertEqual(j["transitional_item"], {"id": "create:incomplete_x"}); self.assertEqual(j["loops"], 3)
        self.assertEqual([s["type"] for s in j["sequence"]], ["create:deploying", "create:filling", "create:pressing"])
        self.assertEqual(j["sequence"][0]["ingredients"], [{"item": "create:incomplete_x"}, {"item": "create:cogwheel"}])
        self.assertEqual(j["sequence"][1]["ingredients"][1], {"type": "neoforge:single", "fluid": "minecraft:lava", "amount": 250})
        self.assertEqual(j["results"][0]["chance"], 120.0); self.assertNotIn("chance", j["results"][1])

    def test_ensamblaje_pasos_invalidos(self):
        base = dict(type="sequenced_assembly", input=item("a:b"), transitional="a:t", outs=[{"id": "a:r"}])
        for steps in ([], [{"t": "milling"}], [{"t": "deploying"}], [{"t": "pressing"}] * 13):
            with self.assertRaises(ValueError): kc.clean_recipe(rec(steps=steps, **base))


class ScriptTest(unittest.TestCase):
    def test_script_usa_event_custom_y_cita_los_valores(self):
        r = kc.clean_recipe(rec(type="pressing", ins=[item("a:b")], outs=[out("a:c")]))
        js = kc.build_script([r])
        self.assertIn("event.custom(r.recipe)", js); self.assertIn("modnex:create_", js); self.assertIn("Item.exists", js); self.assertIn("try {", js)
        self.assertIn('"type": "create:pressing"', js)

    def test_items_que_debe_existir(self):
        r = kc.clean_recipe(rec(type="mixing", ins=[item("a:b"), {"k": "tag", "id": "c:t"}, fluid("minecraft:water")], outs=[out("a:c")]))
        self.assertEqual(kc.item_ids(r), ["a:b", "a:c"])   # ni tags ni fluidos


class StoreTest(unittest.TestCase):
    def test_guardar_escribe_json_y_script_y_borrar_los_quita(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "kubejs").mkdir(); ctx = Ctx(Path(d))
            kc.save(ctx, "s", [rec(type="pressing", ins=[item("a:b")], outs=[out("a:c")])])
            self.assertTrue((Path(d) / "kubejs/server_scripts/modnex_create.js").is_file())
            self.assertEqual(len(kc.load(ctx, "s")["recipes"]), 1)
            kc.delete(ctx, "s", "r1")
            self.assertFalse((Path(d) / "kubejs/server_scripts/modnex_create.js").exists())
            with self.assertRaises(ValueError): kc.delete(ctx, "s", "r1")

    def test_nombres_repetidos(self):
        r = rec(type="pressing", ins=[item("a:b")], outs=[out("a:c")])
        with self.assertRaises(ValueError): kc.clean_list([r, r])


class DetectionTest(unittest.TestCase):
    """La vista Create solo aparece con Create instalado, no con sus complementos (createaddition, createnuclear...)."""
    def addons(self, *jars):
        from modnex.services import servers
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "mods").mkdir()
            for j in jars: (Path(d) / "mods" / j).write_bytes(b"x")
            return servers.addons_of(d)

    def test_create_se_detecta(self):
        self.assertIn("create", self.addons("create-1.21.1-6.0.10.jar", "kubejs-neoforge-2101.7.2-build.381.jar"))

    def test_los_complementos_no_cuentan(self):
        for jar in ("createaddition-1.7.2.jar", "createnuclear-2.0.1-neoforge.jar", "create_ultimate_factory-2.2.4-neoforge-1.21.1.jar", "kubejs-create-neoforge-2101.3.1-build.18.jar"):
            self.assertNotIn("create", self.addons(jar), jar)

    def test_kubejs_y_morejs_siguen_detectandose(self):
        self.assertEqual(sorted(self.addons("kubejs-neoforge-2101.7.2-build.381.jar", "morejs-neoforge-1.21.1-0.16.0.jar")), ["kubejs", "morejs"])


class ReadExistingTest(unittest.TestCase):
    """Las recetas que Create trae en su jar deben leerse a la misma forma normalizada."""
    def test_trituracion_con_probabilidad_y_tiempo(self):
        r = kubejs.create_layout({"type": "create:crushing", "ingredients": [{"tag": "c:raw_materials/nickel"}], "processing_time": 400,
                                  "results": [{"id": "create:crushed_raw_nickel"}, {"chance": 0.75, "id": "create:experience_nugget"}]})
        self.assertEqual(r["ins"], [{"k": "tag", "id": "c:raw_materials/nickel"}]); self.assertEqual(r["time"], 400); self.assertEqual(r["outs"][1]["chance"], 0.75)

    def test_fluidos_en_ingredientes_y_resultados(self):
        r = kubejs.create_layout({"type": "create:filling", "ingredients": [{"item": "minecraft:glass_bottle"}, {"type": "neoforge:tag", "amount": 250, "tag": "c:honey"}], "results": [{"id": "minecraft:honey_bottle"}]})
        self.assertEqual(r["ins"][1], {"k": "fluid", "id": "#c:honey", "amount": 250})
        e = kubejs.create_layout({"type": "create:emptying", "ingredients": [{"item": "minecraft:honey_bottle"}], "results": [{"id": "minecraft:glass_bottle"}, {"amount": 250, "id": "create:honey"}]})
        self.assertEqual(e["outs"][1], {"k": "fluid", "id": "create:honey", "amount": 250})

    def test_calor_y_desplegador(self):
        m = kubejs.create_layout({"type": "create:mixing", "heat_requirement": "superheated", "ingredients": [{"tag": "c:cobblestones"}], "results": [{"amount": 50, "id": "minecraft:lava"}]})
        self.assertEqual(m["heat"], "superheated")
        d = kubejs.create_layout({"type": "create:deploying", "keep_held_item": True, "ingredients": [{"item": "a:x"}, [{"tag": "c:n"}, {"item": "a:y"}]], "results": [{"id": "a:r"}]})
        self.assertTrue(d["keep"]); self.assertEqual(d["ins"][1], {"k": "tag", "id": "c:n"})

    def test_ensamblaje_lee_pesos_y_pasos(self):
        r = kubejs.create_layout({"type": "create:sequenced_assembly", "ingredient": {"tag": "c:plates/gold"}, "loops": 5, "transitional_item": {"id": "create:i"},
                                  "results": [{"chance": 120.0, "id": "create:x"}, {"id": "minecraft:iron_ingot"}],
                                  "sequence": [{"type": "create:deploying", "ingredients": [{"item": "create:i"}, {"item": "create:cogwheel"}], "results": [{"id": "create:i"}]},
                                               {"type": "create:pressing", "ingredients": [{"item": "create:i"}], "results": [{"id": "create:i"}]}]})
        self.assertEqual(r["outs"][0]["weight"], 120.0); self.assertEqual([s["t"] for s in r["steps"]], ["deploying", "pressing"])

    def test_fabricador(self):
        r = kubejs.create_layout({"type": "create:mechanical_crafting", "pattern": [" A ", "ABA"], "key": {"A": {"item": "a:x"}, "B": {"tag": "c:t"}}, "result": {"count": 2, "id": "a:r"}})
        self.assertEqual(r["pattern"], [" A ", "ABA"]); self.assertEqual(r["outs"][0]["count"], 2)

    def test_neoforge_compound_toma_la_primera_opcion(self):
        r = kubejs.create_layout({"type": "create:pressing", "ingredients": [{"type": "neoforge:compound", "ingredients": [{"item": "ru:silt_dirt"}]}], "results": [{"id": "ru:path"}]})
        self.assertEqual(r["ins"], [item("ru:silt_dirt")])

    def test_fluido_de_pocion_con_componentes(self):
        r = kubejs.create_layout({"type": "create:filling", "ingredients": [{"item": "create:cinder_flour"}, {"type": "neoforge:components", "amount": 25, "components": {}, "fluids": "create:potion"}],
                                  "results": [{"id": "minecraft:glowstone_dust"}]})
        self.assertEqual(r["ins"][1], fluid("create:potion", 25))

    def test_nueve_ingredientes_en_el_cuenco(self):
        r = kubejs.create_layout({"type": "create:compacting", "ingredients": [{"item": "minecraft:snow_block"}] * 9, "results": [{"id": "minecraft:ice"}]})
        self.assertEqual(len(r["ins"]), 9)
        kc.clean_recipe(rec(type="compacting", ins=r["ins"], outs=r["outs"]))

    def test_tipos_que_no_se_saben_dibujar(self):
        self.assertIsNone(kubejs.create_layout({"type": "create:item_copying"})); self.assertIsNone(kubejs.create_layout({"type": "create:crushing", "ingredients": [], "results": []}))


if __name__ == "__main__":
    unittest.main()
