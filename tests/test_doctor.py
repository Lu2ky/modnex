import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.features import doctor


def ids(t):
    return {f["id"] for f in doctor.analyze(t)}


class DoctorTests(unittest.TestCase):
    def test_java(self):
        t = "\t- Cobblemon (cobblemon) is missing a feature it requires to run\n\t  It requires javaVersion 21 or above, and below 21.999999 but 25.0.4.1 is available"
        f = doctor.analyze(t)
        self.assertEqual(f[0]["id"], "java"); self.assertIn("Java 21", f[0]["detail"]); self.assertIn("25.0.4.1", f[0]["detail"])

    def test_cliente_sin_identificar(self):
        self.assertIn("client_mod", ids("Attempted to load class net/minecraft/client/gui/screens/Screen for invalid dist DEDICATED_SERVER"))

    def test_modulo_lwjgl(self):
        self.assertIn("client_mod", ids("Exception in thread \"main\" java.lang.module.FindException: Module org.lwjgl not found, required by org.lwjgl.tinyexr"))

    def test_oom_puerto_eula(self):
        self.assertIn("oom", ids("Exception in thread \"Server thread\" java.lang.OutOfMemoryError: Java heap space"))
        self.assertIn("port", ids("**** FAILED TO BIND TO PORT!\nAddress already in use"))
        self.assertIn("eula", ids("[main/WARN]: You need to agree to the EULA in order to run the server."))

    def test_dependencias(self):
        t = "Missing or unsupported mandatory dependencies:\n\tMod ID: 'create', Requested by: 'createaddon', Expected range: '[6.0,)', Actual version: '[MISSING]'"
        f = [x for x in doctor.analyze(t) if x["id"] == "deps"][0]
        self.assertEqual(f["mods"], ["create"]); self.assertIn("createaddon necesita create", f["detail"])

    def test_lag_solo_si_es_frecuente(self):
        self.assertNotIn("lag", ids("Can't keep up! " * 4))
        self.assertIn("lag", ids("Can't keep up! " * 5))

    def test_ok_si_llego_a_done(self):
        f = doctor.analyze("[Server thread/INFO]: Done (18.056s)! For help, type \"help\"")
        self.assertEqual([x["id"] for x in f], ["ok"])

    def test_ok_no_aparece_si_hay_error(self):
        self.assertNotIn("ok", ids("Done (2s)\njava.lang.OutOfMemoryError: Java heap space"))

    def test_ansi(self):
        self.assertIn("oom", ids("\x1b[31mjava.lang.OutOfMemoryError\x1b[0m"))

    def test_texto_vacio(self):
        self.assertEqual(doctor.analyze(""), [])


if __name__ == "__main__":
    unittest.main()
