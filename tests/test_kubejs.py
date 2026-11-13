import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modnex.features import kubejs


def cells(*ids):
    return list(ids) + [None] * (9 - len(ids))


def rec(**kw):
    base = {"id": "anillo", "type": "shaped", "grid": cells("minecraft:gold_ingot", None, "minecraft:gold_ingot"),
            "result": {"id": "minecraft:stone", "count": 2}}
    base.update(kw)
    return base


class CleanTest(unittest.TestCase):
    def test_shaped_ok(self):
        r = kubejs.clean_recipe(rec())
        self.assertEqual(r["result"]["count"], 2)
        self.assertNotIn("xp", r)

    def test_rejects_bad_values(self):
        for bad in (rec(id="Mal Nombre"), rec(type="raro"), rec(result={"id": "x", "count": 0}),
                    rec(grid=cells()), rec(grid=[None] * 8), rec(grid=cells("no valido")),
                    rec(type="smelting", xp=500), rec(type="smelting", time=0),
                    rec(type="stonecutting", grid=cells())):
            with self.assertRaises(ValueError, msg=str(bad)[:80]):
                kubejs.clean_recipe(bad)

    def test_single_input_keeps_only_first_slot(self):
        r = kubejs.clean_recipe(rec(type="smelting", grid=cells("minecraft:iron_ore", "minecraft:coal"),
                                    xp=0.7, time=None))
        self.assertEqual(r["grid"][1], None)
        self.assertEqual(r["time"], 200)
        self.assertEqual(r["xp"], 0.7)

    def test_campfire_default_time(self):
        self.assertEqual(kubejs.clean_recipe(rec(type="campfire"))["time"], 600)

    def test_duplicate_names(self):
        with self.assertRaises(ValueError):
            kubejs.clean_list([rec(), rec()])


class ScriptTest(unittest.TestCase):
    def test_all_types_emitted(self):
        recs = kubejs.clean_list([
            rec(id="a", type="shaped", grid=cells("x:a", "x:b", None, None, "x:a")),
            rec(id="b", type="shapeless", grid=cells("x:a", "x:b")),
            rec(id="c", type="smelting", grid=cells("x:ore"), xp=0.5, time=100),
            rec(id="d", type="blasting", grid=cells("x:ore")),
            rec(id="e", type="smoking", grid=cells("x:ore")),
            rec(id="f", type="campfire", grid=cells("x:ore")),
            rec(id="g", type="stonecutting", grid=cells("x:ore")),
        ])
        js = kubejs.build_script(recs)
        for needle in ("event.shaped(", "event.shapeless(", "event.smelting(", "event.blasting(",
                       "event.smoking(", "event.campfireCooking(", "event.stonecutting(", "Item.exists"):
            self.assertIn(needle, js)
        self.assertIn('"time": 100', js)

    def test_pattern_is_trimmed(self):
        pattern, keys = kubejs._shaped_pattern(cells(None, "x:a", None, None, "x:b"))
        self.assertEqual(pattern, ["A", "B"])
        self.assertEqual(sorted(keys.values()), ["x:a", "x:b"])


if __name__ == "__main__":
    unittest.main()


class SaveTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "kubejs" / "server_scripts").mkdir(parents=True)
        (self.dir / "mods").mkdir()
        self.ctx = SimpleNamespace(server_path=lambda n: self.dir)

    def test_save_writes_source_and_script(self):
        out = kubejs.save(self.ctx, "x", [rec(id="cobre", type="smelting", grid=cells("x:ore"), xp=0.3, time=120)])
        self.assertEqual(out[0]["time"], 120)
        self.assertTrue((self.dir / "kubejs" / "modnex" / "recetas.json").is_file())
        js = (self.dir / "kubejs" / "server_scripts" / "modnex_recetas.js").read_text(encoding="utf-8")
        self.assertIn("event.smelting(out, r.input)", js)
        state = kubejs.load(self.ctx, "x")
        self.assertEqual(state["recipes"][0]["id"], "cobre")
        self.assertTrue(state["script"])

    def test_save_rejects_invalid_list(self):
        with self.assertRaises(ValueError):
            kubejs.save(self.ctx, "x", [{"id": "Mal"}])
        self.assertFalse((self.dir / "kubejs" / "modnex" / "recetas.json").exists())


class ScriptsTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "mods").mkdir()
        (self.dir / "mods" / "kubejs-neoforge-2101.7.2-build.381.jar").write_bytes(b"x")
        for d in kubejs.SCRIPT_DIRS:
            (self.dir / "kubejs" / d).mkdir(parents=True)
        (self.dir / "kubejs" / "server_scripts" / "madera.js").write_text("// hola\n", encoding="utf-8")
        (self.dir / "logs").mkdir()
        (self.dir / "logs" / "latest.log").write_text(
            "[12nov2026 10:00:00.000] [Server thread/ERROR] [KubeJS Server/]: server_scripts:madera.js#3: boom\n"
            "[12nov2026 10:00:01.000] [Server thread/INFO] [KubeJS Server/]: todo bien\n"
            "[12nov2026 10:00:02.000] [Server thread/WARN] [minecraft/X]: ajeno\n", encoding="utf-8")
        self.ctx = SimpleNamespace(server_path=lambda n: self.dir)

    def test_installed_and_addons(self):
        from modnex.services import servers
        self.assertTrue(kubejs.installed(self.ctx, "x"))
        self.assertEqual(servers.addons_of(self.dir), ["kubejs"])
        (self.dir / "mods" / "kubejs-neoforge-2101.7.2-build.381.jar").unlink()
        (self.dir / "mods" / "kubejsadditions-neoforge-1.21.1.jar").write_bytes(b"x")  # complemento, no el mod
        self.assertFalse(kubejs.installed(self.ctx, "x"))
        self.assertEqual(servers.addons_of(self.dir), [])

    def test_list_read_save_create_delete(self):
        self.assertEqual([s["path"] for s in kubejs.scripts(self.ctx, "x")], ["server_scripts/madera.js"])
        self.assertEqual(kubejs.read_script(self.ctx, "x", "server_scripts/madera.js")["text"], "// hola\n")
        kubejs.save_script(self.ctx, "x", "server_scripts/madera.js", "// nuevo\n")
        self.assertEqual((self.dir / "kubejs/server_scripts/madera.js").read_text(), "// nuevo\n")
        rel = kubejs.new_script_path("client_scripts", "tooltips.js")
        kubejs.save_script(self.ctx, "x", rel, "// t\n", create=True)
        with self.assertRaises(ValueError):
            kubejs.save_script(self.ctx, "x", rel, "// otra\n", create=True)
        kubejs.delete_script(self.ctx, "x", rel)
        self.assertFalse((self.dir / "kubejs" / rel).exists())

    def test_path_safety(self):
        for bad in ("../x.js", "server_scripts/../../x.js", "/etc/passwd", "server_scripts/a/b/c.js",
                    "server_scripts/x.sh", "config/x.js", "server_scripts/MAYUS.js"):
            with self.assertRaises(ValueError, msg=bad):
                kubejs.read_script(self.ctx, "x", bad)
        for folder, name in (("mods", "x.js"), ("server_scripts", "../x.js"), ("server_scripts", "x.txt")):
            with self.assertRaises(ValueError):
                kubejs.new_script_path(folder, name)

    def test_generated_script_is_protected(self):
        with self.assertRaises(ValueError):
            kubejs.save_script(self.ctx, "x", kubejs.GENERATED, "// x\n")
        with self.assertRaises(ValueError):
            kubejs.delete_script(self.ctx, "x", kubejs.GENERATED)

    def test_diagnostics_only_kubejs_warnings(self):
        d = kubejs.diagnostics(self.ctx, "x")
        self.assertEqual(len(d["log"]), 1)
        self.assertIn("boom", d["log"][0])
        self.assertEqual(d["counts"]["server_scripts"], 1)

    def test_not_installed_blocks_scripts(self):
        (self.dir / "mods" / "kubejs-neoforge-2101.7.2-build.381.jar").unlink()
        with self.assertRaises(ValueError):
            kubejs.scripts(self.ctx, "x")


class RemovalsTest(unittest.TestCase):
    def setUp(self):
        import json, tempfile, zipfile
        from pathlib import Path
        from types import SimpleNamespace
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "kubejs" / "server_scripts").mkdir(parents=True)
        (self.dir / "mods").mkdir()
        extra = self.dir / "libraries" / "net" / "minecraft" / "server" / "1.21.1-x"
        extra.mkdir(parents=True)
        with zipfile.ZipFile(extra / "server-1.21.1-x-extra.jar", "w") as z:
            z.writestr("assets/minecraft/lang/en_us.json", json.dumps({
                "item.minecraft.stick": "Stick", "block.minecraft.oak_planks": "Oak Planks",
                "block.minecraft.oak_wall_sign": "Oak Wall Sign", "item.minecraft.banner.creeper.red": "Banner"}))
            z.writestr("data/minecraft/recipe/stick.json", json.dumps({
                "type": "minecraft:crafting_shaped", "key": {"#": {"tag": "minecraft:planks"}},
                "pattern": ["#", "#"], "result": {"id": "minecraft:stick", "count": 4}}))
            z.writestr("data/minecraft/recipe/stick_from_bamboo.json", json.dumps({
                "type": "minecraft:crafting_shaped", "key": {"#": {"item": "minecraft:bamboo"}},
                "pattern": ["#", "#"], "result": {"id": "minecraft:stick", "count": 1}}))
        with zipfile.ZipFile(self.dir / "mods" / "x.jar", "w") as z:
            z.writestr("assets/minecraft/models/item/oak_planks.json", "{}")
        self.ctx = SimpleNamespace(server_path=lambda n: self.dir, here=self.dir)

    def test_vanilla_names_and_filters(self):
        ids = {i["id"] for i in kubejs.search(self.ctx, "x", "", 120)}
        self.assertIn("minecraft:stick", ids)
        self.assertIn("minecraft:oak_planks", ids)            # bloque con modelo de item
        self.assertNotIn("minecraft:oak_wall_sign", ids)      # bloque sin item
        self.assertNotIn("minecraft:banner.creeper.red", ids)  # variante de traducción, no un item

    def test_recipes_for_reads_vanilla_recipes(self):
        r = kubejs.recipes_for(self.ctx, "x", "minecraft:stick")
        self.assertEqual([x["id"] for x in r["recipes"]], ["minecraft:stick", "minecraft:stick_from_bamboo"])
        self.assertEqual(r["recipes"][0]["ingredients"][0]["id"], "#minecraft:planks")
        self.assertTrue(r["recipes"][0]["ingredients"][0]["tag"])
        self.assertEqual(kubejs.recipes_for(self.ctx, "x", "minecraft:bamboo")["recipes"], [])

    def test_clean_removals(self):
        out = kubejs.clean_removals([{"kind": "output", "value": "minecraft:stick"},
                                     {"kind": "output", "value": "minecraft:stick"},
                                     {"kind": "id", "value": "minecraft:stick_from_bamboo"}])
        self.assertEqual(len(out), 2)
        for bad in ({"kind": "otro", "value": "minecraft:stick"}, {"kind": "id", "value": "no valido"}, "x"):
            with self.assertRaises(ValueError):
                kubejs.clean_removals([bad])

    def test_save_removals_keeps_recipes_and_script_removes_first(self):
        kubejs.save(self.ctx, "x", [rec(id="a", grid=cells("minecraft:stick"))])
        kubejs.save_removals(self.ctx, "x", [{"kind": "output", "value": "minecraft:stick"}])
        state = kubejs.load(self.ctx, "x")
        self.assertEqual(len(state["recipes"]), 1)
        self.assertEqual(state["removals"], [{"kind": "output", "value": "minecraft:stick"}])
        js = (self.dir / "kubejs" / "server_scripts" / "modnex_recetas.js").read_text(encoding="utf-8")
        self.assertLess(js.index("MODNEX_QUITAR.forEach"), js.index("MODNEX_RECETAS.forEach"))
        self.assertIn("event.remove({ output: r.value })", js)
        self.assertIn("event.remove({ id: r.value })", js)
        kubejs.save(self.ctx, "x", [])   # guardar recetas no borra las eliminaciones
        self.assertEqual(len(kubejs.load(self.ctx, "x")["removals"]), 1)

    def test_old_file_format_is_still_read(self):
        import json
        d = self.dir / "kubejs" / "modnex"
        d.mkdir()
        (d / "recetas.json").write_text(json.dumps([rec(id="vieja", grid=cells("minecraft:stick"))]), encoding="utf-8")
        state = kubejs.load(self.ctx, "x")
        self.assertEqual(state["recipes"][0]["id"], "vieja")
        self.assertEqual(state["removals"], [])

    def test_vanilla_status_without_client(self):
        st = kubejs.vanilla_status(self.ctx, "x")
        self.assertFalse(st["client"])
        self.assertTrue(st["names"])


class PanelRecipesInRemovalTest(RemovalsTest):
    """Las recetas agregadas desde el panel también se listan al quitar recetas y se pueden borrar."""

    def test_panel_recipes_are_listed_first_and_deletable(self):
        kubejs.save(self.ctx, "x", [rec(id="palos", type="shapeless", grid=cells("minecraft:bamboo"),
                                        result={"id": "minecraft:stick", "count": 4})])
        r = kubejs.recipes_for(self.ctx, "x", "minecraft:stick")
        self.assertEqual(r["recipes"][0]["id"], "modnex:palos")
        self.assertEqual(r["recipes"][0]["source"], "panel")
        self.assertEqual(r["recipes"][0]["slug"], "palos")
        self.assertEqual(r["recipes"][0]["type"], "minecraft:crafting_shapeless")
        self.assertEqual({x["source"] for x in r["recipes"][1:]}, {"pack"})
        kubejs.save_removals(self.ctx, "x", [{"kind": "output", "value": "minecraft:stick"}])
        kubejs.delete_recipe(self.ctx, "x", "palos")
        state = kubejs.load(self.ctx, "x")
        self.assertEqual(state["recipes"], [])
        self.assertEqual(len(state["removals"]), 1)           # la eliminación se conserva
        self.assertNotIn("palos", (self.dir / "kubejs/server_scripts/modnex_recetas.js").read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            kubejs.delete_recipe(self.ctx, "x", "palos")
