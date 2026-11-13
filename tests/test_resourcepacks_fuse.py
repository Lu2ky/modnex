"""Añadir packs de Modrinth a la fusión: dominio, SHA-1, nombre reservado, formato del servidor y fusión automática."""
import hashlib, json, shutil, sys, tempfile, unittest, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.services import resourcepacks as rp, modpacks


def make_zip(path, fmt, files):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("pack.mcmeta", json.dumps({"pack": {"pack_format": fmt, "description": path.stem}}))
        for k, v in files.items(): z.writestr(k, v)
    return path


class FakeDB:
    def __init__(self): self.rows = []
    def pack_add(self, name, fname, sha1):
        self.rows = [r for r in self.rows if r["filename"] != fname] + [{"filename": fname, "sha1": sha1, "token": f"t{len(self.rows)}"}]
    def packs_for(self, name): return list(reversed(self.rows))
    def pack_delete(self, name, fname): self.rows = [r for r in self.rows if r["filename"] != fname]


class FuseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.pdir = self.tmp / "packs" / "srv"; self.pdir.mkdir(parents=True)
        self.db = FakeDB()
        self.patches = [
            (rp, "packs_dir", lambda name: self.pdir), (rp.db, "pack_add", self.db.pack_add), (rp.db, "packs_for", self.db.packs_for),
            (rp.db, "pack_delete", self.db.pack_delete), (rp, "get_resourcepack", lambda name: {"url": "", "required": False, "prompt": ""}),
            (rp, "set_resourcepack", lambda *a, **k: None), (rp, "target_format", lambda name: 34),
        ]
        self.saved = [(o, a, getattr(o, a)) for o, a, _ in self.patches]
        for o, a, v in self.patches: setattr(o, a, v)
        self.saved_dl = modpacks._download
        self.addCleanup(self.restore)
        self.src = make_zip(self.tmp / "remote.zip", 34, {"assets/minecraft/textures/block/stone.png": b"S"})
        self.sha = hashlib.sha1(self.src.read_bytes()).hexdigest()
        self.url = "https://cdn.modrinth.com/data/abc/versions/1/E19.zip"
        def fake(url, dest, sha1=None, sha512=None, limit=0):
            shutil.copy2(self.src, dest)
            if sha1 and hashlib.sha1(dest.read_bytes()).hexdigest() != sha1: dest.unlink(); raise ValueError("el SHA-1 no coincide")
        modpacks._download = fake

    def restore(self):
        for o, a, v in self.saved: setattr(o, a, v)
        modpacks._download = self.saved_dl

    def local(self, fname, fmt, files):
        make_zip(self.pdir / fname, fmt, files)
        self.db.pack_add("srv", fname, hashlib.sha1((self.pdir / fname).read_bytes()).hexdigest())

    def test_descarga_verificada_y_fusion_con_formato_del_servidor(self):
        self.local("propio.zip", 15, {"assets/minecraft/textures/block/dirt.png": b"D"})
        rp.add_remote_pack("srv", self.url, self.sha, "E19.zip")
        self.assertTrue((self.pdir / "E19.zip").is_file()); self.assertTrue((self.pdir / rp.UNIFIED).is_file())
        meta = json.loads(zipfile.ZipFile(self.pdir / rp.UNIFIED).read("pack.mcmeta"))
        self.assertEqual(meta["pack"]["pack_format"], 34)                           # el del servidor, no el del pack más nuevo
        names = zipfile.ZipFile(self.pdir / rp.UNIFIED).namelist()
        self.assertIn("assets/minecraft/textures/block/stone.png", names); self.assertIn("assets/minecraft/textures/block/dirt.png", names)

    def test_sha1_que_no_coincide_no_deja_nada(self):
        with self.assertRaises(ValueError): rp.add_remote_pack("srv", self.url, "0" * 40, "E19.zip")
        self.assertFalse((self.pdir / "E19.zip").exists()); self.assertEqual(list(self.pdir.glob("pack-*")), [])

    def test_solo_cdn_de_modrinth_por_https(self):
        for bad in ("http://cdn.modrinth.com/x.zip", "https://evil.example/x.zip", "https://cdn.modrinth.com.evil.example/x.zip", "ftp://cdn.modrinth.com/x.zip"):
            with self.assertRaises(ValueError, msg=bad): rp.add_remote_pack("srv", bad, self.sha, "x.zip")

    def test_nombre_y_sha_validos(self):
        with self.assertRaises(ValueError): rp.add_remote_pack("srv", self.url, self.sha, rp.UNIFIED)
        with self.assertRaises(ValueError): rp.add_remote_pack("srv", self.url, "xyz", "x.zip")
        with self.assertRaises(ValueError): rp.add_remote_pack("srv", self.url, self.sha, "x.rar")
        rp.add_remote_pack("srv", self.url, self.sha, "../../x.zip")          # la ruta se quita: se guarda dentro de la carpeta del servidor
        self.assertTrue((self.pdir / "x.zip").is_file()); self.assertFalse((self.tmp / "x.zip").exists())

    def test_un_zip_sin_pack_mcmeta_se_rechaza(self):
        bad = self.tmp / "bad.zip"
        with zipfile.ZipFile(bad, "w") as z: z.writestr("otra.txt", "x")
        modpacks._download = lambda url, dest, **k: shutil.copy2(bad, dest)
        with self.assertRaises(ValueError): rp.add_remote_pack("srv", self.url, hashlib.sha1(bad.read_bytes()).hexdigest(), "x.zip")

    def test_sin_version_conocida_usa_el_del_pack_nuevo(self):
        rp.target_format = lambda name: None
        try:
            self.local("a.zip", 15, {"assets/minecraft/textures/block/a.png": b"A"})
            self.local("b.zip", 34, {"assets/minecraft/textures/block/b.png": b"B"})
            rp.rebuild_unified("srv")
            self.assertEqual(json.loads(zipfile.ZipFile(self.pdir / rp.UNIFIED).read("pack.mcmeta"))["pack"]["pack_format"], 34)
        finally:
            rp.target_format = lambda name: 34


if __name__ == "__main__":
    unittest.main()
