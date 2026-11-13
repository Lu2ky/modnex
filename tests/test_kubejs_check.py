"""Probar los scripts en el servidor: interpretación de los logs de /reload (con líneas reales) y el flujo con una consola falsa."""
import sys, tempfile, threading, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.features import kubejs_check as kc

# Líneas tomadas de un reload real de un servidor con KubeJS, incluido el ruido de otros mods.
OK_LATEST = """[13nov2026 01:34:57.805] [Worker-ResourceReload-20/WARN] [net.minecraft.server.ReloadableServerRegistries/]: Found loot table element validation problem in {minecraft:loot_table:bonsaitrees4:bonsai/x}
[13nov2026 01:34:58.027] [Worker-ResourceReload-22/ERROR] [net.neoforged.neoforge.registries.DataMapLoader/]: Could not read data map of type neoforge:oxidizables for registry
[13nov2026 01:34:59.242] [Server thread/INFO] [KubeJS Server/]: server_scripts:modnex_recetas.js#32: [modnex] 0 de 0 recetas añadidas
[13nov2026 01:35:00.300] [Server thread/INFO] [net.minecraft.server.MinecraftServer/]: Reloaded with no KubeJS errors!
[13nov2026 01:35:00.300] [Server thread/INFO] [KubeJS Server/]: Server resource reload complete!
"""
OK_KJS = """[01:34:59] [WARN] KubeRecipe.java#90: Failed to parse recipe 'ironfurnaces:upgrades/upgrade_vibranium[minecraft:crafting_shaped]'! Falling back to vanilla: Invalid component key
[01:34:59] [INFO] server_scripts:madera.js#63: [madera] recetas añadidas: 13 de palos
[01:34:59] [INFO] server_scripts:modnex_recetas.js#32: [modnex] 0 de 0 recetas añadidas
[01:34:59] [INFO] Added 61 recipes, removed 0 recipes, modified 9 recipes, with 0 failed recipes taking 559 ms in total
[01:35:00] [INFO] Server resource reload complete!
"""


class AnalyzeTest(unittest.TestCase):
    def test_reload_sin_errores(self):
        r = kc.analyze(OK_LATEST, OK_KJS)
        self.assertTrue(r["ok"] and r["finished"]); self.assertEqual(r["kubejs_errors"], 0)
        self.assertEqual(r["recipes"], {"added": 61, "removed": 0, "modified": 9, "failed": 0})
        self.assertEqual(r["summary"], ["modnex_recetas.js: 0 de 0 recetas añadidas"])

    def test_el_ruido_de_otros_mods_no_cuenta(self):
        self.assertEqual(kc.analyze(OK_LATEST, OK_KJS)["problems"], [])      # el ERROR de DataMapLoader y el WARN de ironfurnaces no son de Modnex

    def test_errores_de_kubejs(self):
        latest = OK_LATEST.replace("Reloaded with no KubeJS errors!", "Reloaded with 2 KubeJS errors, run '/kubejs errors server' for more info")
        kjs = OK_KJS + "[01:34:59] [ERROR] server_scripts:modnex_reglas.js#12: Error in 'ServerEvents.tags': TypeError: x is not a function\n"
        r = kc.analyze(latest, kjs)
        self.assertFalse(r["ok"]); self.assertEqual(r["kubejs_errors"], 2)
        self.assertEqual(r["problems"][0]["level"], "error"); self.assertIn("TypeError", r["problems"][0]["text"])
        self.assertTrue(r["problems"][0]["text"].startswith("modnex_reglas.js: "))     # el archivo sí, el número de línea del prefijo no
        self.assertNotIn("#12", r["problems"][0]["text"])

    def test_receta_saltada_es_un_aviso_no_un_error(self):
        kjs = OK_KJS + "[01:34:59] [WARN] server_scripts:modnex_recetas.js#32: [modnex] receta anillo saltada: no existen mod:no_existe\n"
        r = kc.analyze(OK_LATEST, kjs)
        self.assertTrue(r["ok"]); self.assertEqual([p["level"] for p in r["problems"]], ["warn"]); self.assertIn("saltada", r["problems"][0]["text"])

    def test_receta_de_modnex_que_no_parsea(self):
        kjs = OK_KJS + "[01:34:59] [WARN] KubeRecipe.java#90: Failed to parse recipe 'modnex:create_x[create:pressing]'! Falling back to vanilla: Failed to read component\n"
        r = kc.analyze(OK_LATEST, kjs)
        self.assertEqual(len(r["problems"]), 1); self.assertIn("modnex:create_x", r["problems"][0]["text"])

    def test_error_de_minecraft_con_una_receta_nuestra(self):
        latest = OK_LATEST + "[13nov2026 01:35:00.100] [Worker-ResourceReload-3/ERROR] [net.minecraft.world.item.crafting.RecipeManager/]: Parsing error loading recipe modnex:create_x\n"
        r = kc.analyze(latest, OK_KJS)
        self.assertFalse(r["ok"]); self.assertIn("modnex:create_x", r["problems"][0]["text"])

    def test_sin_final_del_reload(self):
        r = kc.analyze("[13nov2026 01:35:00.100] [Server thread/INFO] [x/]: nada\n", "")
        self.assertFalse(r["finished"]); self.assertFalse(r["ok"])

    def test_lineas_repetidas_en_los_dos_logs_salen_una_vez(self):
        line = "[13nov2026 01:34:59.242] [Server thread/INFO] [KubeJS Server/]: server_scripts:modnex_recetas.js#32: [modnex] 3 de 3 recetas añadidas\n"
        r = kc.analyze(OK_LATEST + line, OK_KJS + "[01:34:59] [INFO] server_scripts:modnex_recetas.js#32: [modnex] 3 de 3 recetas añadidas\n")
        self.assertEqual(r["summary"].count("modnex_recetas.js: 3 de 3 recetas añadidas"), 1)


class Ctx:
    """Consola falsa: al recibir «reload» escribe en los logs lo que escribiría el servidor."""
    def __init__(self, root, running=True, control=True, reply=None, delay=0.05):
        self.root = Path(root); self.running, self.control, self.reply, self.delay, self.sent = running, control, reply, delay, []
        (self.root / "logs/kubejs").mkdir(parents=True, exist_ok=True)
        (self.root / "logs/latest.log").write_text("[x] [Server thread/INFO] [m/]: arranque\n")
    def server_path(self, name): return str(self.root)
    def status(self, name): return {"running": self.running, "control": self.control}
    def send_command(self, name, cmd):
        self.sent.append(cmd)
        if self.reply is None: return
        def write():
            time.sleep(self.delay)
            with open(self.root / "logs/kubejs/server.log", "a") as f: f.write(self.reply[1])
            with open(self.root / "logs/latest.log", "a") as f: f.write(self.reply[0])
        threading.Thread(target=write, daemon=True).start()


class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)

    def test_apagado_o_sin_control(self):
        with self.assertRaisesRegex(ValueError, "apagado"): kc.run(Ctx(self.tmp.name, running=False), "s")
        with self.assertRaisesRegex(ValueError, "no lo arrancó el gestor"): kc.run(Ctx(self.tmp.name, control=False), "s")

    def test_flujo_completo(self):
        ctx = Ctx(self.tmp.name, reply=(OK_LATEST, OK_KJS))
        r = kc.run(ctx, "s", wait=5, poll=0.05)
        self.assertEqual(ctx.sent, ["reload"]); self.assertTrue(r["ok"]); self.assertEqual(r["recipes"]["added"], 61)
        self.assertNotIn("arranque", " ".join(r["summary"]))       # solo lo escrito después del reload

    def test_sin_respuesta_avisa_del_tiempo(self):
        r = kc.run(Ctx(self.tmp.name, reply=None), "s", wait=0.4, poll=0.05)
        self.assertFalse(r["ok"]); self.assertFalse(r["finished"]); self.assertEqual(r["problems"][0]["level"], "warn")

    def test_dos_pruebas_a_la_vez(self):
        ctx = Ctx(self.tmp.name, reply=(OK_LATEST, OK_KJS), delay=0.4)
        out = []
        t = threading.Thread(target=lambda: out.append(kc.run(ctx, "s2", wait=5, poll=0.05))); t.start(); time.sleep(0.1)
        with self.assertRaisesRegex(ValueError, "en curso"): kc.run(ctx, "s2", wait=1, poll=0.05)
        t.join(); self.assertTrue(out[0]["ok"])
        kc.run(Ctx(self.tmp.name, reply=(OK_LATEST, OK_KJS)), "s2", wait=5, poll=0.05)    # y vuelve a poder usarse

    def test_notas_de_lo_que_reload_no_aplica(self):
        for d, f in (("startup_scripts", "modnex_inicio.js"), ("client_scripts", "modnex_cliente.js")):
            (Path(self.tmp.name) / "kubejs" / d).mkdir(parents=True); (Path(self.tmp.name) / "kubejs" / d / f).write_text("//")
        n = kc.notes(Ctx(self.tmp.name), "s")
        self.assertEqual(len(n), 2); self.assertIn("reiniciar", n[0]); self.assertIn("F3+T", n[1])


if __name__ == "__main__":
    unittest.main()
