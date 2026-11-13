"""Historial de KubeJS: versiones antes de cada cambio, restaurar y deshacer, retención y rutas seguras."""
import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.features import kubejs_history as h


class Ctx:
    def __init__(self, root): self.root = root
    def server_path(self, name): return str(self.root)


def put(root, rel, text):
    p = Path(root) / "kubejs" / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text); return p


def read(root, rel):
    p = Path(root) / "kubejs" / rel; return p.read_text() if p.is_file() else None


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root = Path(self.tmp.name); self.ctx = Ctx(self.root)
        (self.root / "kubejs").mkdir()

    def test_gestionado_solo_lo_del_panel(self):
        put(self.root, "modnex/recetas.json", "1"); put(self.root, "server_scripts/modnex_recetas.js", "a"); put(self.root, "server_scripts/madera.js", "mio")
        put(self.root, "client_scripts/modnex_cliente.js", "c"); put(self.root, "modnex/history/x/meta.json", "{}")
        put(self.root, "modnex/loot.json", json.dumps({"files": ["data/minecraft/loot_table/entities/zombie.json", "../../etc/passwd", "data/x/y.txt"]}))
        put(self.root, "data/minecraft/loot_table/entities/zombie.json", "{}"); put(self.root, "data/minecraft/loot_table/entities/ajeno.json", "{}")
        got = h.managed(self.root / "kubejs")
        self.assertEqual(sorted(got), ["client_scripts/modnex_cliente.js", "data/minecraft/loot_table/entities/zombie.json", "modnex/loot.json", "modnex/recetas.json", "server_scripts/modnex_recetas.js"])

    def test_la_version_guarda_el_estado_de_antes_y_restaurar_deshace(self):
        put(self.root, "modnex/recetas.json", "v1"); put(self.root, "server_scripts/modnex_recetas.js", "s1")
        vid = h.snapshot(self.ctx, "s", "Antes de guardar recetas", "ana")
        put(self.root, "modnex/recetas.json", "v2"); put(self.root, "server_scripts/modnex_recetas.js", "s2"); put(self.root, "server_scripts/modnex_nuevo.js", "n")
        v = h.versions(self.ctx, "s")
        self.assertEqual([(x["id"], x["label"], x["user"], x["files"]) for x in v], [(vid, "Antes de guardar recetas", "ana", 2)])
        self.assertFalse(v[0]["same"]); self.assertEqual({(c["file"], c["status"]) for c in v[0]["changes"]},
                                                       {("modnex/recetas.json", "cambiado"), ("server_scripts/modnex_recetas.js", "cambiado"), ("server_scripts/modnex_nuevo.js", "se borra")})
        out = h.restore(self.ctx, "s", vid, "ana")
        self.assertEqual(out["files"], 2)
        self.assertEqual(read(self.root, "modnex/recetas.json"), "v1"); self.assertEqual(read(self.root, "server_scripts/modnex_recetas.js"), "s1")
        self.assertIsNone(read(self.root, "server_scripts/modnex_nuevo.js"))                    # lo que no existía entonces se borra
        after = h.versions(self.ctx, "s")
        self.assertEqual(len(after), 2); self.assertEqual(after[0]["label"], "Antes de restaurar una versión anterior")   # y se puede volver atrás
        h.restore(self.ctx, "s", after[0]["id"])
        self.assertEqual(read(self.root, "modnex/recetas.json"), "v2"); self.assertEqual(read(self.root, "server_scripts/modnex_nuevo.js"), "n")

    def test_no_duplica_si_nada_cambio(self):
        put(self.root, "modnex/reglas.json", "1")
        self.assertTrue(h.snapshot(self.ctx, "s", "a")); self.assertIsNone(h.snapshot(self.ctx, "s", "b"))
        put(self.root, "modnex/reglas.json", "2"); self.assertTrue(h.snapshot(self.ctx, "s", "c")); self.assertEqual(len(h.versions(self.ctx, "s")), 2)

    def test_deshacer_el_primer_cambio_borra_lo_que_creo(self):
        vid = h.snapshot(self.ctx, "s", "Antes de guardar recetas")                           # todavía no había nada del panel
        put(self.root, "modnex/recetas.json", "v1"); put(self.root, "server_scripts/modnex_recetas.js", "s1"); put(self.root, "server_scripts/madera.js", "mio")
        h.restore(self.ctx, "s", vid)
        self.assertIsNone(read(self.root, "modnex/recetas.json")); self.assertIsNone(read(self.root, "server_scripts/modnex_recetas.js"))
        self.assertEqual(read(self.root, "server_scripts/madera.js"), "mio")                  # lo escrito a mano no se toca

    def test_botin_restaura_y_borra_sus_datapacks(self):
        put(self.root, "modnex/loot.json", json.dumps({"rules": [], "files": ["data/minecraft/loot_table/entities/zombie.json"]})); put(self.root, "data/minecraft/loot_table/entities/zombie.json", "viejo")
        vid = h.snapshot(self.ctx, "s", "Antes de guardar tablas de botín")
        put(self.root, "modnex/loot.json", json.dumps({"rules": [], "files": ["data/minecraft/loot_table/entities/zombie.json", "data/minecraft/loot_table/blocks/stone.json"]}))
        put(self.root, "data/minecraft/loot_table/entities/zombie.json", "nuevo"); put(self.root, "data/minecraft/loot_table/blocks/stone.json", "{}"); put(self.root, "data/minecraft/loot_table/blocks/ajeno.json", "ajeno")
        h.restore(self.ctx, "s", vid)
        self.assertEqual(read(self.root, "data/minecraft/loot_table/entities/zombie.json"), "viejo"); self.assertIsNone(read(self.root, "data/minecraft/loot_table/blocks/stone.json"))
        self.assertEqual(read(self.root, "data/minecraft/loot_table/blocks/ajeno.json"), "ajeno")

    def test_retencion(self):
        old = h.KEEP; h.KEEP = 3
        try:
            for i in range(6):
                put(self.root, "modnex/recetas.json", str(i)); h.snapshot(self.ctx, "s", f"c{i}")
        finally: h.KEEP = old
        self.assertEqual([v["label"] for v in h.versions(self.ctx, "s")], ["c5", "c4", "c3"])

    def test_rutas_manipuladas_no_escapan(self):
        put(self.root, "modnex/recetas.json", "v1"); vid = h.snapshot(self.ctx, "s", "x")
        meta = self.root / "kubejs/modnex/history" / vid / "meta.json"; m = json.loads(meta.read_text()); m["files"] += ["../../evil.txt", "server_scripts/madera.js", "/etc/passwd"]; meta.write_text(json.dumps(m))
        (self.root / "evil.txt").write_text("fuera"); h.restore(self.ctx, "s", vid)
        self.assertEqual((self.root / "evil.txt").read_text(), "fuera"); self.assertIsNone(read(self.root, "server_scripts/madera.js"))
        for bad in ("../x", "20260101-000000-000/../..", "", None, "abc", "20260101-000000"):
            with self.assertRaises(ValueError): h.restore(self.ctx, "s", bad)
        with self.assertRaises(ValueError): h.restore(self.ctx, "s", "20200101-000000-000")

    def test_sin_carpeta_kubejs(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(h.snapshot(Ctx(Path(d)), "s", "x")); self.assertEqual(h.versions(Ctx(Path(d)), "s"), [])


if __name__ == "__main__":
    unittest.main()
