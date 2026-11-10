import sqlite3, sys, types, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.features import proposals as P

ANA = {"id": 1, "username": "ana", "is_admin": False}
BOB = {"id": 2, "username": "bob", "is_admin": False}
ADM = {"id": 9, "username": "admin", "is_admin": True}


def make_ctx():
    db = sqlite3.connect(":memory:", check_same_thread=False); db.row_factory = sqlite3.Row; db.executescript(P.SCHEMA)
    def run(sql, args=(), one=False, many=False):
        cur = db.execute(sql, args)
        return cur.fetchone() if one else cur.fetchall()
    class Conn:
        def __enter__(s): return db
        def __exit__(s, *a): return False
    return types.SimpleNamespace(db_run=run, db_connect=lambda: Conn())


class ProposalTests(unittest.TestCase):
    def setUp(self):
        self.ctx = make_ctx()

    def add(self, user=ANA, pid="AANobbMI", **kw):
        return P.create(self.ctx, "s", user, kw.get("source", "modrinth"), pid, kw.get("title", "Sodium"), note=kw.get("note", ""))

    def test_crear_y_listar(self):
        self.add(note="para mejorar los FPS")
        r = P.list_for(self.ctx, "s")
        self.assertEqual((len(r), r[0]["status"], r[0]["username"], r[0]["note"]), (1, "pending", "ana", "para mejorar los FPS"))

    def test_validaciones(self):
        for bad in (dict(source="otro"), dict(pid="../x"), dict(pid=""), dict(pid="a" * 41), dict(title="   "), dict(pid="x y")):
            with self.assertRaises(P.ProposalError, msg=str(bad)):
                self.add(**bad)

    def test_duplicado_pendiente_o_aprobado(self):
        pid = self.add()
        with self.assertRaises(P.ProposalError): self.add(user=BOB)
        P.decide(self.ctx, "s", ADM, pid, "approve")
        with self.assertRaises(P.ProposalError): self.add(user=BOB)

    def test_rechazado_se_puede_volver_a_proponer(self):
        P.decide(self.ctx, "s", ADM, self.add(), "reject", "ya hay uno parecido")
        self.add(user=BOB)  # no lanza

    def test_limite_de_pendientes_por_usuario(self):
        for i in range(P.MAX_PENDING_PER_USER): self.add(pid=f"mod{i}")
        with self.assertRaises(P.ProposalError): self.add(pid="otro")
        self.add(user=BOB, pid="otro")  # otro usuario no se ve afectado

    def test_misma_propuesta_en_otro_servidor(self):
        self.add()
        P.create(self.ctx, "otro", ANA, "modrinth", "AANobbMI", "Sodium")  # no lanza

    def test_decidir_una_sola_vez(self):
        pid = self.add()
        self.assertEqual(P.decide(self.ctx, "s", ADM, pid, "approve", "ok"), "approved")
        with self.assertRaises(P.ProposalError): P.decide(self.ctx, "s", ADM, pid, "reject")
        r = P.list_for(self.ctx, "s")[0]
        self.assertEqual((r["status"], r["decided_by"], r["reason"]), ("approved", "admin", "ok"))

    def test_decidir_con_valores_invalidos(self):
        pid = self.add()
        with self.assertRaises(P.ProposalError): P.decide(self.ctx, "s", ADM, pid, "borrar")
        with self.assertRaises(P.ProposalError): P.decide(self.ctx, "s", ADM, 999, "approve")
        with self.assertRaises(P.ProposalError): P.decide(self.ctx, "otro", ADM, pid, "approve")

    def test_retirar(self):
        pid = self.add()
        with self.assertRaises(P.ProposalError): P.withdraw(self.ctx, "s", BOB, pid)
        P.withdraw(self.ctx, "s", ANA, pid); self.assertEqual(P.list_for(self.ctx, "s"), [])

    def test_admin_puede_retirar_y_no_las_resueltas(self):
        a, b = self.add(), self.add(pid="otro")
        P.decide(self.ctx, "s", ADM, b, "approve")
        P.withdraw(self.ctx, "s", ADM, a)
        with self.assertRaises(P.ProposalError): P.withdraw(self.ctx, "s", ANA, b)

    def test_pendientes_primero(self):
        a = self.add(pid="a"); self.add(pid="b"); P.decide(self.ctx, "s", ADM, a, "approve")
        self.assertEqual([r["status"] for r in P.list_for(self.ctx, "s")], ["pending", "approved"])

    def test_texto_se_limpia_y_recorta(self):
        pid = self.add(title="Mod\n\tcon saltos", note="x" * 1000)
        r = P.list_for(self.ctx, "s")[0]
        self.assertNotIn("\n", r["title"]); self.assertEqual(len(r["note"]), 300)

    def test_icono_solo_de_hosts_conocidos(self):
        P.create(self.ctx, "s", ANA, "modrinth", "a1", "A", icon="https://evil.com/x.png")
        P.create(self.ctx, "s", ANA, "modrinth", "a2", "B", icon="https://cdn.modrinth.com/data/x/icon.png")
        r = {x["title"]: x["icon"] for x in P.list_for(self.ctx, "s")}
        self.assertEqual(r["A"], ""); self.assertTrue(r["B"].startswith("https://cdn.modrinth.com/"))

    def test_sql_en_campos_no_rompe_nada(self):
        P.create(self.ctx, "s", ANA, "modrinth", "ok1", "x'); DROP TABLE pro_proposals;--", note="'; DELETE FROM pro_proposals; --")
        self.assertEqual(len(P.list_for(self.ctx, "s")), 1)

    def test_resultados_del_buscador(self):
        raw = [{"source": "modrinth", "id": "AANobbMI", "slug": "sodium", "name": "Sodium", "summary": "FPS", "downloads": 5, "icon": "https://cdn.modrinth.com/data/a/i.png"},
               {"id": "../mal", "name": "Malo"}, {"name": "sin id"}]
        out = P.search_results(raw)
        self.assertEqual([r["project_id"] for r in out], ["AANobbMI"]); self.assertEqual(out[0]["title"], "Sodium")


if __name__ == "__main__":
    unittest.main()
