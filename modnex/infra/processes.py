"""Procesos de los servidores de Minecraft detrás de una interfaz (puerto) con un adaptador por sistema operativo.

`services/servers.py` no sabe cómo se arranca un script ni cómo se lee el consumo de un proceso: le pide a `backend` que
lo haga. Hoy hay un adaptador para Linux y macOS (bash, señales y `/proc`); uno para Windows nativo solo tendría que
implementar estos mismos cuatro métodos. En las pruebas se sustituye con `use()`.
"""
import os
import signal
import subprocess
from pathlib import Path


class ProcessBackend:
    """Lo que el gestor necesita del sistema operativo para llevar un servidor. Un adaptador implementa estos métodos."""

    def spawn(self, script, cwd, env, log):
        """Arranca el script del servidor, en su propio grupo de procesos y con stdin abierto. Devuelve un Popen."""
        raise NotImplementedError

    def is_java_alive(self, pid):
        """True si `pid` existe y es un proceso de Java (evita confundir un pid reutilizado)."""
        raise NotImplementedError

    def terminate(self, pid):
        """Pide al proceso que termine de forma ordenada (Java guarda el mundo)."""
        raise NotImplementedError

    def usage(self, pid):
        """Consumo del proceso: {"rss_mb": int, "uptime_s": int}, o {} si no se puede leer."""
        raise NotImplementedError


class PosixProcesses(ProcessBackend):
    """Linux y macOS: bash, SIGTERM y, donde existe, /proc."""

    def spawn(self, script, cwd, env, log):
        return subprocess.Popen(["bash", str(script)], cwd=cwd, env=env, stdin=subprocess.PIPE,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)

    def is_java_alive(self, pid):
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return False
        try:
            return b"java" in Path(f"/proc/{pid}/cmdline").read_bytes()
        except OSError:
            return False

    def terminate(self, pid):
        os.kill(pid, signal.SIGTERM)

    def usage(self, pid):
        out = {}
        try:
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    out["rss_mb"] = int(line.split()[1]) // 1024
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            since_boot = float(Path("/proc/uptime").read_text().split()[0])
            out["uptime_s"] = max(0, int(since_boot - int(fields[19]) / os.sysconf("SC_CLK_TCK")))
        except (OSError, ValueError, IndexError):
            pass
        return out


backend = PosixProcesses()


def use(new_backend):
    """Cambia el adaptador (la raíz de composición o una prueba). Devuelve el anterior."""
    global backend
    old, backend = backend, new_backend
    return old
