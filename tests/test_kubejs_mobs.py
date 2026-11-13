"""Modelos 3D de mobs de vanilla: caras, coordenadas de textura y encaje en el cubo de 16."""
import json, sys, tempfile, unittest, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.features import kubejs, kubejs_mobs as M

PNG = b"\x89PNG\r\n\x1a\n" + b"datos"
ALL = {spec["tex"] for spec in M.MOBS.values()} | {t for spec in M.MOBS.values() for t, *_ in spec.get("layers", [])}


class Ctx:
    def __init__(self, root): self.here = root; self.srv = root / "srv"
    def server_path(self, name): return str(self.srv)


class MobsTest(unittest.TestCase):
    def test_every_mob_builds(self):
        for mid in M.MOBS:
            m = M.build(mid, ALL)
            self.assertTrue(m, mid)
            self.assertTrue(m["quads"] and m["ent"] == 1 and set(m["tex"]) <= ALL, mid)

    def test_fits_in_the_cube_and_stands_on_the_floor(self):
        for mid in M.MOBS:
            pts = [p for q in M.build(mid, ALL)["quads"] for p in q["p"]]
            lo, hi = [min(p[k] for p in pts) for k in range(3)], [max(p[k] for p in pts) for k in range(3)]
            self.assertAlmostEqual(lo[1], 1.0, places=2, msg=mid)
            self.assertTrue(all(0 <= c <= 16 for c in lo + hi), (mid, lo, hi))
            self.assertAlmostEqual(max(h - l for h, l in zip(hi, lo)), 14.0, places=1, msg=mid)

    def test_texture_coordinates_stay_inside_the_texture(self):
        for mid in M.MOBS:
            for q in M.build(mid, ALL)["quads"]:
                for u, v in q["uv"]:
                    self.assertTrue(0 <= u <= 16.001 and 0 <= v <= 16.001, (mid, u, v))

    def test_normals_are_unit_and_point_out_of_each_box(self):
        # Cada pieza aporta seis caras seguidas: todas deben mirar hacia fuera de su propia caja (con giros y espejos incluidos).
        for mid in M.MOBS:
            quads = M.build(mid, ALL)["quads"]
            self.assertEqual(len(quads) % 6, 0)
            for i in range(0, len(quads), 6):
                group = quads[i:i + 6]
                pts = [p for q in group for p in q["p"]]
                centre = [sum(p[k] for p in pts) / len(pts) for k in range(3)]
                for q in group:
                    self.assertAlmostEqual(sum(c * c for c in q["n"]), 1.0, places=1)
                    face = [sum(p[k] for p in q["p"]) / 4 for k in range(3)]
                    self.assertGreater(sum((face[k] - centre[k]) * q["n"][k] for k in range(3)), 0, (mid, i, q["n"]))

    def test_front_of_the_mob_faces_the_viewer(self):
        # La cara de la cabeza (frente, -z del modelo) debe acabar mirando a +z, con su textura en (8, 8) del cubo de la cabeza.
        m = M.build("minecraft:creeper", ALL)
        head_front = [q for q in m["quads"] if q["n"] == [0.0, 0.0, 1.0] and abs(q["uv"][0][0] - 8 / 64 * 16) < 1e-3 and abs(q["uv"][0][1] - 8 / 32 * 16) < 1e-3]
        self.assertEqual(len(head_front), 1)

    def test_mirrored_limb_swaps_sides(self):
        part = {"b": (0, 0, 0, 4, 12, 4), "uv": (40, 16)}
        plain, mirrored = M._faces(part), M._faces(dict(part, m=True))
        # frente: misma región de la textura, pero invertida en horizontal
        self.assertEqual(plain[0][1][0][0], mirrored[0][1][1][0])
        # lado -x del espejo = región del lado +x del original
        self.assertEqual(sorted({u for u, _ in mirrored[2][1]}), sorted({u for u, _ in plain[3][1]}))

    def test_missing_texture_or_unknown_mob(self):
        self.assertIsNone(M.build("minecraft:zombie", set()))
        self.assertIsNone(M.build("minecraft:warden", ALL))
        self.assertIsNone(M.build("fake:thing", ALL))

    def test_layers_are_skipped_if_their_texture_is_missing(self):
        have = ALL - {"minecraft:entity/skeleton/stray_overlay"}
        self.assertEqual(M.build("minecraft:stray", have)["tex"], ["minecraft:entity/skeleton/stray"])
        self.assertEqual(len(M.build("minecraft:stray", ALL)["tex"]), 2)

    def test_json_serialisable(self):
        json.dumps(M.build("minecraft:sheep", ALL))


class RouteTest(unittest.TestCase):
    def test_mob_prefix_returns_the_mob_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "srv/mods").mkdir(parents=True)
            with zipfile.ZipFile(root / "srv/mods/fake.jar", "w") as z:
                z.writestr("assets/minecraft/textures/entity/pig/pig.png", PNG)
                z.writestr("assets/minecraft/textures/block/stone.png", PNG)
            ctx = Ctx(root)
            models, textures = kubejs.block_models(ctx, "s", ["mob:minecraft:pig", "mob:minecraft:cow", "minecraft:stone"])
            self.assertTrue(models["mob:minecraft:pig"]["quads"])
            self.assertIsNone(models["mob:minecraft:cow"])          # falta su textura: se queda el huevo
            self.assertIn("minecraft:entity/pig/pig", textures)


if __name__ == "__main__":
    unittest.main()
