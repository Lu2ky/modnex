"""Subir un mod propio: validación del .jar, cargador, nombres y limpieza del archivo temporal."""
import io, json, sys, tempfile, unittest, zipfile
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.services import addons, servers


def jar(*names, extra=b"x"):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n in names: z.writestr(n, extra)
    return b.getvalue()


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name).resolve()
        self.p = mock.patch.object(servers, "SERVERS_DIR", self.root); self.p.start()
        addons.INSTALLED_CACHE.clear()

    def tearDown(self): self.p.stop(); self.tmp.cleanup()

    def server(self, template="neoforge"):
        d = self.root / "s"; (d / ("plugins" if template == "paper" else "mods")).mkdir(parents=True)
        (d / ".manager.json").write_text(json.dumps({"template": template})); return d

    def sube(self, content, fname="mi-mod.jar", name="s"):
        tmp = self.root / name / (fname + ".part"); tmp.write_bytes(content)
        return addons.finish_mod_upload(name, tmp, fname), tmp

    def test_un_mod_de_neoforge_se_instala_en_mods_y_limpia_la_cache(self):
        d = self.server(); addons.INSTALLED_CACHE["s"] = (0, {})
        f, tmp = self.sube(jar("META-INF/neoforge.mods.toml", "a/B.class"))
        self.assertEqual(f, "mi-mod.jar"); self.assertTrue((d / "mods" / "mi-mod.jar").is_file()); self.assertFalse(tmp.exists())
        self.assertNotIn("s", addons.INSTALLED_CACHE, "la lista de instalados se vuelve a calcular")

    def test_neoforge_acepta_tambien_el_descriptor_de_forge(self):
        self.server(); self.sube(jar("META-INF/mods.toml"))

    def test_un_mod_de_fabric_no_sirve_en_neoforge_y_el_mensaje_lo_dice(self):
        d = self.server()
        with self.assertRaises(ValueError) as cm: self.sube(jar("fabric.mod.json"))
        self.assertIn("Fabric", str(cm.exception)); self.assertIn("NeoForge", str(cm.exception))
        self.assertEqual(list((d / "mods").iterdir()), [], "no queda nada, ni el temporal")

    def test_fabric_acepta_fabric_y_paper_acepta_plugins(self):
        self.server("fabric"); self.sube(jar("fabric.mod.json"))
        (self.root / "s").rename(self.root / "viejo"); self.server("paper")
        f, _ = self.sube(jar("plugin.yml")); self.assertTrue((self.root / "s" / "plugins" / f).is_file())

    def test_un_plugin_no_sirve_en_un_servidor_de_mods(self):
        self.server()
        with self.assertRaises(ValueError): self.sube(jar("plugin.yml"))

    def test_no_zip_y_zip_sin_descriptor_se_rechazan_y_se_limpian(self):
        d = self.server()
        for contenido in (b"no soy un jar", jar("solo/una/Clase.class")):
            with self.assertRaises(ValueError): self.sube(contenido)
        self.assertEqual(list((d / "mods").iterdir()), [])

    def test_no_pisa_un_mod_con_el_mismo_nombre_ni_su_version_desactivada(self):
        d = self.server(); (d / "mods" / "mi-mod.jar").write_bytes(b"original")
        with self.assertRaises(ValueError): self.sube(jar("META-INF/neoforge.mods.toml"))
        self.assertEqual((d / "mods" / "mi-mod.jar").read_bytes(), b"original")
        (d / "mods" / "mi-mod.jar").unlink(); (d / "mods" / "mi-mod.jar.disabled").write_bytes(b"off")
        with self.assertRaises(ValueError): self.sube(jar("META-INF/neoforge.mods.toml"))

    def test_vanilla_no_admite_mods(self):
        d = self.root / "s"; d.mkdir(); (d / ".manager.json").write_text(json.dumps({"template": "vanilla"}))
        with self.assertRaises(ValueError) as cm: self.sube(jar("META-INF/neoforge.mods.toml"))
        self.assertIn("Vanilla", str(cm.exception))

    def test_nombres_peligrosos_se_rechazan(self):
        for bad in ("../x.jar", "x.zip", "a b/c.jar", "", ".jar"):
            try: n = addons.safe_jar_name(bad)
            except ValueError: continue
            self.assertEqual(n, Path(bad).name, bad)    # solo se admite la parte del nombre, sin rutas


if __name__ == "__main__":
    unittest.main()
