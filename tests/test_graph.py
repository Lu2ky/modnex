"""Árbol de versiones de las copias: padres, ramas al restaurar y reparto en columnas."""
import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from features import backups
from test_backups import make_ctx, fill


def bid(n):
    return f"20260101-0000{n:02d}-{n:04x}"


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = self.tmp.name
        self.ctx, self.srv = make_ctx(self.root); fill(self.srv)
        self.dir = backups.backup_dir(self.ctx, "srv")

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, n, **extra):
        m = {"id": bid(n), "created": 1767225600 + n, "kind": "manual", "size": 1, "mods": [], **extra}
        (self.dir / f"{bid(n)}.tar.gz").write_bytes(b"x")
        (self.dir / f"{bid(n)}.json").write_text(json.dumps(m))

    def node(self, g, n):
        return next(x for x in g["nodes"] if x["id"] == bid(n))

    def test_sin_copias(self):
        g = backups.graph(self.ctx, "srv")
        self.assertEqual((g["nodes"], g["lanes"], g["head"]), ([], 1, None))

    def test_copias_antiguas_sin_padre_forman_una_linea(self):
        for n in (1, 2, 3):
            self.put(n)
        g = backups.graph(self.ctx, "srv")
        self.assertEqual([x["id"] for x in g["nodes"]], [bid(3), bid(2), bid(1)])
        self.assertEqual({x["lane"] for x in g["nodes"]}, {0})
        self.assertEqual(self.node(g, 3)["parent"], bid(2))
        self.assertIsNone(self.node(g, 1)["parent"])
        self.assertEqual(g["lanes"], 1)

    def test_crear_encadena_y_marca_la_posicion_actual(self):
        a = backups.create(self.ctx, "srv", label="a")
        b = backups.create(self.ctx, "srv", label="b")
        self.assertIsNone(a["parent"]); self.assertEqual(b["parent"], a["id"])
        self.assertEqual(backups.get_head(self.ctx, "srv"), b["id"])
        g = backups.graph(self.ctx, "srv")
        self.assertEqual([x["id"] for x in g["nodes"] if x["head"]], [b["id"]])

    def test_restaurar_una_antigua_abre_una_rama(self):
        a = backups.create(self.ctx, "srv", label="a")
        b = backups.create(self.ctx, "srv", label="b")
        r = backups.restore(self.ctx, "srv", a["id"])
        self.assertEqual(backups.get_head(self.ctx, "srv"), a["id"])
        c = backups.create(self.ctx, "srv", label="c")
        self.assertEqual(c["parent"], a["id"])
        safety = next(m for m in backups.list_backups(self.ctx, "srv") if m["id"] == r["safety"])
        self.assertEqual(safety["parent"], b["id"])            # la copia de seguridad cuelga de donde estabas
        g = backups.graph(self.ctx, "srv")
        self.assertGreaterEqual(g["lanes"], 2)                  # hay dos puntas: la rama vieja y la nueva
        by = {x["id"]: x for x in g["nodes"]}
        self.assertEqual(by[c["id"]]["parent"], a["id"])
        self.assertEqual(by[b["id"]]["parent"], a["id"])
        self.assertEqual(by[safety["id"]]["parent"], b["id"])
        self.assertIsNone(by[a["id"]]["parent"])
        self.assertEqual(sum(1 for x in g["nodes"] if x["parent"] == a["id"]), 2)   # a tiene dos hijos: la bifurcación

    def test_bifurcacion_reparto_en_columnas(self):
        self.put(1, parent=None)
        self.put(2, parent=bid(1))
        self.put(3, parent=bid(1))        # segunda rama desde 1
        self.put(4, parent=bid(2))
        g = backups.graph(self.ctx, "srv")
        self.assertEqual(g["lanes"], 2)
        self.assertNotEqual(self.node(g, 4)["lane"], self.node(g, 3)["lane"])
        self.assertEqual(self.node(g, 1)["lane"], 0)
        self.assertEqual(self.node(g, 3)["edge"]["lane"], 0)
        self.assertEqual(self.node(g, 3)["edge"]["to"], self.node(g, 1)["row"])

    def test_padre_borrado_se_enlaza_con_la_anterior(self):
        self.put(1, parent=None)
        self.put(3, parent=bid(2))        # la 2 ya no existe
        g = backups.graph(self.ctx, "srv")
        self.assertEqual(self.node(g, 3)["parent"], bid(1))

    def test_padre_imposible_se_ignora(self):
        self.put(1, parent=bid(2))        # un hijo más viejo que su padre: dato corrupto
        self.put(2, parent=None)
        g = backups.graph(self.ctx, "srv")
        self.assertIsNone(self.node(g, 1)["parent"])


if __name__ == "__main__":
    unittest.main()
