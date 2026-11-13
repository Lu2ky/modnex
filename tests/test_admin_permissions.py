"""Validación del cuerpo de permisos de usuario: un formato incorrecto da 400, nunca 500."""
import sys, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.web import errors
from modnex.web.routes import admin


class CleanPermissionsTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(admin, "server_path", lambda name: "/x/" + name)
        p.start(); self.addCleanup(p.stop)

    def test_formato_correcto(self):
        out = admin.clean_permissions({"cobble": {"logs": True, "control": 1}})
        self.assertTrue(out["cobble"]["logs"] and out["cobble"]["control"])
        self.assertFalse(out["cobble"]["mods"])

    def test_lista_en_vez_de_objeto_es_400(self):
        with self.assertRaises(ValueError) as cm:
            admin.clean_permissions({"cobble": ["logs", "control"]})
        self.assertEqual(errors.to_response(cm.exception)[0], 400)

    def test_cuerpo_que_no_es_objeto(self):
        for bad in (["cobble"], "logs", None, 3):
            with self.assertRaises(ValueError):
                admin.clean_permissions(bad)

    def test_valor_nulo_de_un_servidor(self):
        with self.assertRaises(ValueError):
            admin.clean_permissions({"cobble": None})


if __name__ == "__main__":
    unittest.main()
