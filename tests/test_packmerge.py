import json, sys, tempfile, unittest, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.services.packmerge import merge_packs


def make_zip(path, files, fmt=34, desc="x"):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("pack.mcmeta", json.dumps({"pack": {"pack_format": fmt, "description": desc}}))
        for name, data in files.items():
            z.writestr(name, data)
    return path


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())

    def test_el_mas_nuevo_gana_en_cada_archivo(self):
        a = make_zip(self.d / "a.zip", {"assets/x/textures/item/s.png": b"A", "assets/x/textures/item/t.png": b"A-t"})
        b = make_zip(self.d / "b.zip", {"assets/x/textures/item/s.png": b"B", "assets/x/textures/item/u.png": b"B-u"}, fmt=34)
        out = self.d / "u.zip"
        rep = merge_packs([a, b], out)
        with zipfile.ZipFile(out) as z:
            self.assertEqual(z.read("assets/x/textures/item/s.png"), b"B")
            self.assertEqual(z.read("assets/x/textures/item/t.png"), b"A-t")
            self.assertEqual(z.read("assets/x/textures/item/u.png"), b"B-u")
        self.assertEqual(rep["overrides_total"], 1)
        self.assertEqual(rep["overridden"], ["assets/x/textures/item/s.png"])
        self.assertEqual(rep["packs"], 2)

    def test_lang_se_fusiona_por_clave(self):
        a = make_zip(self.d / "a.zip", {"assets/x/lang/es_es.json": json.dumps({"k1": "uno", "k2": "viejo"})})
        b = make_zip(self.d / "b.zip", {"assets/x/lang/es_es.json": json.dumps({"k2": "nuevo", "k3": "tres"})})
        out = self.d / "u.zip"
        rep = merge_packs([a, b], out)
        with zipfile.ZipFile(out) as z:
            data = json.loads(z.read("assets/x/lang/es_es.json"))
        self.assertEqual(data, {"k1": "uno", "k2": "nuevo", "k3": "tres"})
        self.assertEqual(rep["lang_files"], 1)
        self.assertEqual(rep["overrides_total"], 0)

    def test_mcmeta_del_mas_nuevo_y_descripcion(self):
        a = make_zip(self.d / "a.zip", {}, fmt=15)
        b = make_zip(self.d / "b.zip", {}, fmt=34)
        out = self.d / "u.zip"
        rep = merge_packs([a, b], out)
        with zipfile.ZipFile(out) as z:
            meta = json.loads(z.read("pack.mcmeta"))
        self.assertEqual(meta["pack"]["pack_format"], 34)
        self.assertIn("2 packs", meta["pack"]["description"])
        self.assertTrue(rep["mixed_formats"])

    def test_rutas_peligrosas_se_descartan(self):
        a = self.d / "a.zip"
        with zipfile.ZipFile(a, "w") as z:
            z.writestr("pack.mcmeta", json.dumps({"pack": {"pack_format": 34, "description": ""}}))
            z.writestr("../escapa.png", b"x")
            z.writestr("/abs.png", b"x")
            z.writestr("assets/ok.png", b"ok")
        out = self.d / "u.zip"
        merge_packs([a], out)
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
        self.assertIn("assets/ok.png", names)
        self.assertFalse(any(".." in n or n.startswith("/") for n in names))

    def test_sin_packs_falla(self):
        with self.assertRaises(ValueError):
            merge_packs([], self.d / "u.zip")


if __name__ == "__main__":
    unittest.main()


class RebuildTests(unittest.TestCase):
    """rebuild_unified con la base de datos simulada: no toca datos reales."""
    def setUp(self):
        from unittest import mock
        from modnex.services import resourcepacks as rp
        self.rp = rp
        self.d = Path(tempfile.mkdtemp())
        self.rows = []
        self.url = [""]
        self.sets = []
        patches = [
            mock.patch.object(rp, "packs_dir", lambda name: self.d),
            mock.patch.object(rp.db, "packs_for", lambda name: list(self.rows)),
            mock.patch.object(rp.db, "pack_add", lambda name, f, sha: self.rows.insert(0, {"filename": f, "sha1": sha, "token": "T" + f})),
            mock.patch.object(rp.db, "pack_delete", lambda name, f: self.rows.__setitem__(slice(None), [r for r in self.rows if r["filename"] != f])),
            mock.patch.object(rp, "get_resourcepack", lambda name: {"url": self.url[0], "sha1": "", "required": False, "prompt": ""}),
            mock.patch.object(rp, "set_resourcepack", lambda name, url, sha1, req, prompt: (self.url.__setitem__(0, url), self.sets.append(url))),
        ]
        for p in patches:
            p.start(); self.addCleanup(p.stop)

    def _pack(self, fname, data):
        make_zip(self.d / fname, {"assets/x/textures/a.png": data})
        self.rows.insert(0, {"filename": fname, "sha1": "", "token": "T" + fname})

    def test_con_uno_no_hay_unificado(self):
        self._pack("a.zip", b"A")
        self.assertIsNone(self.rp.rebuild_unified("srv"))
        self.assertFalse((self.d / self.rp.UNIFIED).exists())

    def test_con_dos_crea_unificado_y_lo_registra(self):
        self._pack("a.zip", b"A")
        self._pack("b.zip", b"B")
        rep = self.rp.rebuild_unified("srv")
        self.assertEqual(rep["packs"], 2)
        self.assertTrue((self.d / self.rp.UNIFIED).is_file())
        self.assertTrue(any(r["filename"] == self.rp.UNIFIED for r in self.rows))

    def test_si_se_sirve_el_unificado_se_actualiza_sin_cambiar_url(self):
        self._pack("a.zip", b"A")
        self._pack("b.zip", b"B")
        self.rp.rebuild_unified("srv")
        self.url[0] = "http://h:8765/packs/Tunificado.zip/unificado.zip"
        self._pack("c.zip", b"C")
        self.rp.rebuild_unified("srv")
        self.assertEqual(self.url[0], "http://h:8765/packs/Tunificado.zip/unificado.zip")
