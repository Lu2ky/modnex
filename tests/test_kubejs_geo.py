"""Modelos 3D de mobs de mods con modelos de datos (GeckoLib / Bedrock): emparejado por nombre y construcción de caras."""
import json, struct, sys, tempfile, unittest, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.features import kubejs, kubejs_geo as G


def png(w, h): return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00"


def geo(bones, w=64, h=32): return {"format_version": "1.12.0", "minecraft:geometry": [{"description": {"identifier": "geometry.x", "texture_width": w, "texture_height": h}, "bones": bones}]}


class Ctx:
    def __init__(self, root): self.here = root; self.srv = root / "srv"
    def server_path(self, name): return str(self.srv)


class MatchTest(unittest.TestCase):
    GEO = ["m:zombieclown", "m:krampus", "m:boneimp2", "m:other/deep/pumpkinhead", "x:zombieclown"]
    TEX = ["m:entities/zombieclown", "m:entities/zombieclown_e", "m:entities/krampus_texture", "m:entities/boneimp", "m:block/krampus", "m:entities/pumpkinhead", "m:item/boneimp"]

    def test_nombre_con_guiones_bajos(self):
        self.assertEqual(G.match("m:zombie_clown", self.GEO, self.TEX), ("m:zombieclown", "m:entities/zombieclown"))

    def test_variantes_y_sufijos(self):
        self.assertEqual(G.match("m:zombie_clown_not_despawn", self.GEO, self.TEX)[0], "m:zombieclown")
        self.assertEqual(G.match("m:bone_imp_2", self.GEO, self.TEX), ("m:boneimp2", "m:entities/boneimp"))

    def test_textura_parecida_y_carpetas_ignoradas(self):
        self.assertEqual(G.match("m:krampus", self.GEO, self.TEX)[1], "m:entities/krampus_texture")      # nunca la de block/
        self.assertEqual(G.match("m:pumpkinhead", self.GEO, self.TEX), ("m:other/deep/pumpkinhead", "m:entities/pumpkinhead"))

    def test_solo_del_mismo_mod_y_sin_pareja(self):
        self.assertEqual(G.match("x:zombie_clown", self.GEO, self.TEX), None)                          # x tiene modelo pero no textura
        self.assertIsNone(G.match("m:nothing", self.GEO, self.TEX)); self.assertIsNone(G.match("m:krampus", [], self.TEX))


class BuildTest(unittest.TestCase):
    def test_caja_con_uv_de_caja(self):
        m = G.build(geo([{"name": "root", "pivot": [0, 0, 0], "cubes": [{"origin": [-4, 0, -4], "size": [8, 8, 8], "uv": [0, 0]}]}]), "m:t")
        self.assertEqual(len(m["quads"]), 6); self.assertEqual(m["tex"], ["m:t"]); self.assertEqual(m["ent"], 1)
        for q in m["quads"]:
            self.assertEqual(len(q["p"]), 4); self.assertTrue(all(0 <= c <= 16 for p in q["p"] for c in p), q["p"])
            self.assertTrue(all(0 <= u <= 16.001 and 0 <= v <= 16.001 for u, v in q["uv"]))
        up = [q for q in m["quads"] if q["n"] == [0.0, 1.0, 0.0]]; self.assertEqual(len(up), 1)       # la cara de arriba mira hacia arriba
        front = [q for q in m["quads"] if q["n"] == [0.0, 0.0, 1.0]]; self.assertEqual(len(front), 1)  # y el frente hacia el visor, con su textura (u+d, v+d)
        self.assertEqual(front[0]["uv"][0], [8 / 64 * 16, 8 / 32 * 16])
        c = [sum(p[k] for q in m["quads"] for p in q["p"]) / 24 for k in range(3)]                    # normales hacia fuera: ningún espejo
        for q in m["quads"]:
            mid = [sum(p[k] for p in q["p"]) / 4 for k in range(3)]
            self.assertGreater(sum((mid[k] - c[k]) * q["n"][k] for k in range(3)), 0, q["n"])

    def test_los_huesos_hijos_heredan_el_giro_del_padre(self):
        cube = {"origin": [-1, 0, -1], "size": [2, 6, 2], "uv": [0, 0]}
        straight = G.build(geo([{"name": "a", "pivot": [0, 0, 0], "cubes": [cube]}]), "m:t")
        turned = G.build(geo([{"name": "p", "pivot": [0, 0, 0], "rotation": [0, 0, 90]}, {"name": "a", "parent": "p", "pivot": [0, 0, 0], "cubes": [cube]}]), "m:t")
        ys = lambda m: max(p[1] for q in m["quads"] for p in q["p"]) - min(p[1] for q in m["quads"] for p in q["p"])
        xs = lambda m: max(p[0] for q in m["quads"] for p in q["p"]) - min(p[0] for q in m["quads"] for p in q["p"])
        self.assertGreater(ys(straight), xs(straight)); self.assertGreater(xs(turned), ys(turned))     # el palo vertical pasa a horizontal

    def test_uv_por_cara_y_formato_antiguo(self):
        face = {"uv": [4, 4], "uv_size": [4, 4]}
        m = G.build(geo([{"name": "a", "cubes": [{"origin": [0, 0, 0], "size": [4, 4, 4], "uv": {"north": face, "up": face}}]}]), "m:t")
        self.assertEqual(len(m["quads"]), 2)
        old = {"geometry.x": {"texturewidth": 16, "textureheight": 16, "bones": [{"name": "a", "cubes": [{"origin": [0, 0, 0], "size": [2, 2, 2], "uv": [0, 0]}]}]}}
        self.assertEqual(len(G.build(old, "m:t")["quads"]), 6)

    def test_la_textura_manda_sobre_el_tamano_declarado(self):
        cube = {"origin": [0, 0, 0], "size": [8, 8, 8], "uv": [0, 0]}
        a = G.build(geo([{"name": "a", "cubes": [cube]}], 64, 64), "m:t", (128, 128))
        b = G.build(geo([{"name": "a", "cubes": [cube]}], 64, 64), "m:t")
        self.assertNotEqual(a["quads"][0]["uv"], b["quads"][0]["uv"])

    def test_entradas_rotas_o_demasiado_grandes(self):
        for bad in ({}, {"minecraft:geometry": []}, {"minecraft:geometry": [{"bones": []}]}, {"minecraft:geometry": [{"bones": "x"}]}, geo([{"name": "a"}]), None):
            self.assertIsNone(G.build(bad, "m:t"), str(bad))
        many = [{"name": f"b{i}", "cubes": [{"origin": [0, 0, 0], "size": [1, 1, 1], "uv": [0, 0]}]} for i in range(G.MAX_CUBES + 1)]
        self.assertIsNone(G.build(geo([{"name": "a", "cubes": many}]), "m:t"))

    def test_png_size(self):
        self.assertEqual(G.png_size(png(64, 32)), (64, 32)); self.assertIsNone(G.png_size(b"nope"))


class RouteTest(unittest.TestCase):
    def test_mob_de_un_mod_con_su_modelo(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "srv/mods").mkdir(parents=True)
            with zipfile.ZipFile(root / "srv/mods/m.jar", "w") as z:
                z.writestr("assets/m/geo/zombieclown.geo.json", json.dumps(geo([{"name": "a", "cubes": [{"origin": [0, 0, 0], "size": [4, 4, 4], "uv": [0, 0]}]}])))
                z.writestr("assets/m/textures/entities/zombieclown.png", png(64, 32))
                z.writestr("assets/minecraft/textures/entity/pig/pig.png", png(64, 32))
            ctx = Ctx(root)
            models, textures = kubejs.block_models(ctx, "s", ["mob:m:zombie_clown", "mob:m:desconocido", "mob:minecraft:pig"])
            self.assertEqual(len(models["mob:m:zombie_clown"]["quads"]), 6); self.assertIn("m:entities/zombieclown", textures)
            self.assertIsNone(models["mob:m:desconocido"]); self.assertTrue(models["mob:minecraft:pig"])      # vanilla sigue igual


if __name__ == "__main__":
    unittest.main()
