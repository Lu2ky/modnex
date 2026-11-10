"""Acceso remoto al panel mediante un túnel (Cloudflare o ngrok) para usuarios que no son administradores.

Los administradores no pueden entrar por el túnel: el núcleo solo les deja usar el panel desde este equipo
o la red local. Por el túnel entran únicamente cuentas normales, y por defecto con verificación en dos pasos.
La dirección es pública mientras el túnel esté abierto.

- cloudflared (túnel rápido): HTTPS lo pone Cloudflare; la dirección cambia cada vez; sin cuenta.
- ngrok: necesita una cuenta y el token configurado en ngrok; el plan gratuito puede mostrar una página de aviso.
"""
import atexit
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

PROVIDERS = {
    "cloudflared": {
        "label": "Cloudflare",
        "url_re": re.compile(r"https://[a-z0-9\-]+\.trycloudflare\.com(?![A-Za-z0-9.\-])"),
        "env": "MODNEX_CLOUDFLARED", "config": "cloudflared_path", "bin": "cloudflared",
        "cmd": lambda b, port: [b, "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate"],
    },
    "ngrok": {
        "label": "ngrok",
        "url_re": re.compile(r"https://[a-z0-9\-]+\.ngrok(?:-free)?\.(?:app|dev|io)(?![A-Za-z0-9.\-])"),
        "env": "MODNEX_NGROK", "config": "ngrok_path", "bin": "ngrok",
        "cmd": lambda b, port: [b, "http", f"127.0.0.1:{port}", "--log=stdout", "--log-format=logfmt"],
    },
}
URL_RE = PROVIDERS["cloudflared"]["url_re"]   # compatibilidad
_STATE = {"proc": None, "url": None, "started": 0, "error": "", "provider": None}
_LOCK = threading.Lock()


class RemoteError(Exception):
    pass


def _binary(ctx, provider):
    p = PROVIDERS[provider]
    cand = os.environ.get(p["env"]) or ctx.config().get(p["config"]) or str(Path(ctx.here) / "bin" / p["bin"])
    path = Path(cand)
    if not path.is_file():
        found = shutil.which(p["bin"])
        path = Path(found) if found else path
    return path if path.is_file() and os.access(path, os.X_OK) else None


def available(ctx):
    return {k: bool(_binary(ctx, k)) for k in PROVIDERS}


def status(ctx):
    proc = _STATE["proc"]
    active = bool(proc and proc.poll() is None and _STATE["url"])
    if proc and proc.poll() is not None and _STATE["url"]:
        _STATE.update(proc=None, url=None, error="el túnel se cerró")
    return {"active": active, "url": _STATE["url"] if active else None, "started": _STATE["started"], "error": _STATE["error"],
            "provider": _STATE["provider"] if active else None, "providers": {k: {"label": v["label"], "available": a} for (k, v), a in zip(PROVIDERS.items(), available(ctx).values())},
            "available": any(available(ctx).values())}


def start(ctx, provider="cloudflared", timeout=30):
    if provider not in PROVIDERS:
        raise RemoteError("proveedor de túnel no válido")
    with _LOCK:
        if status(ctx)["active"]:
            raise RemoteError("el acceso remoto ya está activo")
        binary = _binary(ctx, provider)
        if not binary:
            raise RemoteError(f"no encuentro {PROVIDERS[provider]['bin']}")
        spec = PROVIDERS[provider]
        proc = subprocess.Popen(spec["cmd"](str(binary), ctx.port), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
        _STATE.update(proc=proc, url=None, started=0, error="", provider=provider)
        found, tail = threading.Event(), []

        def reader():
            try:
                for line in proc.stdout:
                    tail.append(line.strip()[:300]); del tail[:-8]
                    m = spec["url_re"].search(line)
                    if m and not _STATE["url"]:
                        _STATE.update(url=m.group(0), started=int(time.time()))
                        found.set()
            except (ValueError, OSError):
                pass  # la tubería se cerró al parar el túnel
            found.set()
        threading.Thread(target=reader, daemon=True).start()
        if not found.wait(timeout) or not _STATE["url"]:
            _kill(proc)
            _STATE.update(proc=None, url=None, provider=None)
            err = next((t for t in reversed(tail) if re.search(r"err|fail|auth|token|denied", t, re.I)), "")
            raise RemoteError("no se pudo abrir el túnel" + (f": {err}" if err else " (¿hay conexión a internet?)"))
        return status(ctx)


def _kill(proc):
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(8)
    except (ProcessLookupError, subprocess.TimeoutExpired, OSError):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
    finally:
        try:
            proc.stdout.close()
        except (ValueError, OSError):
            pass


def stop(ctx=None):
    with _LOCK:
        proc = _STATE["proc"]
        if proc and proc.poll() is None:
            _kill(proc)
        _STATE.update(proc=None, url=None, started=0, error="", provider=None)


atexit.register(stop)
