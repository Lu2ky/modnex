import sys, unittest, tempfile, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.features import kubejs_rules as kr


def rule(**kw):
    return kw


class Ctx:
    def __init__(self, p): self.p = p
    def server_path(self, name): return self.p


class CleanTest(unittest.TestCase):
    def test_tag(self):
        r = kr.clean_rule(rule(id="t1", type="tag", registry="item", tag="c:ingots/x", action="add", entries=["minecraft:iron_ingot", "#c:a"]))
        self.assertEqual(r["entries"][1], "#c:a")

    def test_bad(self):
        for bad in (rule(id="A", type="tag"), rule(id="a", type="zzz"),
                    rule(id="a", type="tag", registry="item", tag="x", action="add", entries=["a:b"]),
                    rule(id="a", type="replace", mode="input", source="a:b", target="a:b"),
                    rule(id="a", type="event", event="player_login", actions=[{"do": "cancel"}]),
                    rule(id="a", type="event", event="block_broken", actions=[{"do": "tell", "text": "x"}]),
                    rule(id="a", type="trade", profession="x", inputs=[], output={"id": "a:b"}),
                    rule(id="a", type="item_prop", item="a:b")):
            with self.assertRaises(ValueError):
                kr.clean_rule(bad)

    def test_dup(self):
        t = rule(id="a", type="hide", items=["a:b"])
        with self.assertRaises(ValueError):
            kr.clean_rules([t, t])

    def test_cancel_last(self):
        r = kr.clean_rule(rule(id="a", type="event", event="block_broken", filter="a:b",
                               actions=[{"do": "cancel"}, {"do": "tell", "text": "no"}]))
        self.assertEqual(r["actions"][-1], {"do": "cancel"})


class ScriptTest(unittest.TestCase):
    def build(self, *rules):
        return kr.build_scripts(kr.clean_rules(list(rules)))

    def test_injection_is_quoted(self):
        s = self.build(rule(id="a", type="event", event="player_login", actions=[{"do": "tell", "text": 'x"); evil(); ("'}]))["server"]
        self.assertIn('\\"); evil(); (\\"', s)
        self.assertNotIn('tell("x");', s)

    def test_sides(self):
        out = self.build(rule(id="a", type="hide", items=["a:b"]), rule(id="b", type="item_prop", item="a:b", stack=16),
                         rule(id="c", type="tag", registry="item", tag="c:x", action="add", entries=["a:b"]))
        self.assertIn("RecipeViewerEvents", out["client"])
        self.assertIn("maxStackSize = 16", out["startup"])
        self.assertIn("ServerEvents.tags", out["server"])

    def test_empty_and_disabled(self):
        out = self.build(rule(id="a", type="hide", items=["a:b"], on=False))
        self.assertEqual(out, {"server": None, "client": None, "startup": None})

    def test_trade(self):
        s = self.build(rule(id="t", type="trade", profession="farmer", level=2, inputs=[{"id": "a:b", "count": 3}],
                            output={"id": "a:c", "count": 1}), rule(id="c", type="trade_clear", which="vanilla"))["server"]
        self.assertIn('event.addTrade("farmer", 2, ["3x a:b"], "a:c").maxUses(12)', s)
        self.assertLess(s.index("removeVanillaTrades"), s.index("addTrade"))

    def test_command_and_replace(self):
        s = self.build(rule(id="c", type="command", name="hola", level=0, actions=[{"do": "tell", "text": "hi"}]),
                       rule(id="r", type="replace", mode="input", source="a:b", target="#c:d", only="a:z"))["server"]
        self.assertIn("hasPermission(0)", s)
        self.assertIn('Ingredient.of("#c:d")', s)
        self.assertIn('{"input": "a:b", "output": "a:z"}', s)


class SaveTest(unittest.TestCase):
    def test_roundtrip_and_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "kubejs").mkdir()
            ctx = Ctx(d)
            kr.save(ctx, "s", [rule(id="a", type="hide", items=["a:b"])])
            self.assertTrue((Path(d) / "kubejs/client_scripts/modnex_cliente.js").is_file())
            self.assertEqual(len(kr.load(ctx, "s")["rules"]), 1)
            kr.save(ctx, "s", [])
            self.assertFalse((Path(d) / "kubejs/client_scripts/modnex_cliente.js").exists())


if __name__ == "__main__":
    unittest.main()
