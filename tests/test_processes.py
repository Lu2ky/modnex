"""Puerto de procesos: el gestor arranca, consulta y mide servidores a través de `processes.backend`, no del sistema."""
import os, sys, tempfile, threading, time, types, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.infra import processes
from modnex.services import servers


class FakeProc:
    pid = 4242
    def __init__(self): self.gone = threading.Event(); self.stdin = types.SimpleNamespace(write=lambda b: None, flush=lambda: None)
    def poll(self): return 0 if self.gone.is_set() else None
    def wait(self, timeout=None): self.gone.wait(5); return 0


class FakeBackend(processes.ProcessBackend):
    def __init__(self): self.spawned, self.killed, self.proc = [], [], FakeProc()
    def spawn(self, script, cwd, env, log): self.spawned.append((Path(script).name, Path(cwd).name, "JAVA_BIN" in env)); return self.proc
    def is_java_alive(self, pid): return pid == self.proc.pid and not self.proc.gone.is_set()
    def terminate(self, pid): self.killed.append(pid); self.proc.gone.set()
    def usage(self, pid): return {"rss_mb": 1234, "uptime_s": 99}


class BackendPortTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name).resolve()
        (self.root / "mi-server").mkdir(); (self.root / "mi-server" / "start.sh").write_text("#!/bin/sh\n")
        self.fake = FakeBackend(); self.old = processes.use(self.fake)
        self.patches = [mock.patch.object(servers, "SERVERS_DIR", self.root), mock.patch.object(servers.plugins, "emit", lambda *a: None)]
        for p in self.patches: p.start()
        servers.PROCS.clear()

    def tearDown(self):
        self.fake.proc.gone.set(); time.sleep(0.2)   # deja terminar el hilo que vigila el proceso antes de borrar la carpeta
        [p.stop() for p in self.patches]; processes.use(self.old); servers.PROCS.clear(); self.tmp.cleanup()

    def test_start_usa_el_adaptador_y_el_estado_lo_refleja(self):
        servers.start("mi-server")
        self.assertEqual(self.fake.spawned, [("start.sh", "mi-server", True)])
        st = servers.status("mi-server"); self.assertEqual((st["running"], st["pid"], st["control"]), (True, 4242, True))
        self.assertEqual((self.root / "mi-server" / ".manager.pid").read_text(), "4242")

    def test_no_arranca_dos_veces(self):
        servers.start("mi-server")
        with self.assertRaises(RuntimeError): servers.start("mi-server")

    def test_metricas_salen_del_adaptador(self):
        servers.start("mi-server")
        with mock.patch.object(servers, "read_log", lambda n, lines=200: ""):
            m = servers.live_metrics("mi-server")
        self.assertEqual((m["rss_mb"], m["uptime_s"]), (1234, 99))

    def test_un_pid_sin_control_se_comprueba_con_el_adaptador(self):
        (self.root / "mi-server" / ".manager.pid").write_text("4242")
        self.assertEqual(servers.status("mi-server")["running"], True)
        self.fake.proc.gone.set()
        self.assertEqual(servers.status("mi-server")["running"], False)
        self.assertFalse((self.root / "mi-server" / ".manager.pid").exists(), "borra el pid de un proceso que ya no existe")


class PosixAdapterTests(unittest.TestCase):
    def test_un_proceso_que_no_es_java_no_cuenta_como_servidor(self):
        self.assertFalse(processes.PosixProcesses().is_java_alive(os.getpid()))
        self.assertFalse(processes.PosixProcesses().is_java_alive(2 ** 22 + 12345))

    @unittest.skipUnless(Path("/proc/self/status").exists(), "solo con /proc")
    def test_usage_lee_memoria_y_tiempo(self):
        u = processes.PosixProcesses().usage(os.getpid())
        self.assertGreater(u["rss_mb"], 0); self.assertGreaterEqual(u["uptime_s"], 0)

    def test_usage_de_un_pid_inexistente_es_vacio(self):
        self.assertEqual(processes.PosixProcesses().usage(2 ** 22 + 12345), {})

    def test_spawn_lanza_un_script_con_stdin_abierto(self):
        with tempfile.TemporaryDirectory() as d:
            s = Path(d) / "x.sh"; s.write_text("read l; echo $l > salida.txt\n")
            with open(Path(d) / "log", "ab") as log:
                p = processes.PosixProcesses().spawn(s, d, dict(os.environ), log)
                p.stdin.write(b"hola\n"); p.stdin.flush(); p.wait(5)
            self.assertEqual((Path(d) / "salida.txt").read_text().strip(), "hola")


if __name__ == "__main__":
    unittest.main()
