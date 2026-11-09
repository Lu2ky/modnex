"""Releases del cliente (.zip) y enlace público temporal mediante un túnel de Cloudflare.

Seguridad: el túnel apunta a un mini servidor propio que sirve UN solo archivo bajo una
ruta con token aleatorio. El panel de administración nunca se expone por el túnel.
"""
import atexit
import json
import os
import re
import secrets
import signal
import socket
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIN = HERE / "bin" / "cloudflared"
RELEASES = HERE / "releases"
PID_FILE = HERE / ".tunnel.pid"
MAX_MINUTES = 720
DEFAULT_MINUTES = 60
ZIP_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ \-\[\]()+]{0,119}\.zip")
REL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ \-\[\]()+]{0,119}\.(?:zip|mrpack)")
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

LOCK = threading.Lock()
SHARE = None  # compartición activa (solo una a la vez)


def release_dir(server):
    d = (RELEASES / server).resolve()
    if d.parent != RELEASES.resolve():
        raise ValueError("servidor no válido")
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_zip_name(name):
    name = os.path.basename(urllib.parse.unquote(name or ""))
    if not ZIP_RE.fullmatch(name):
        raise ValueError("nombre de archivo no válido (solo .zip, sin rutas)")
    return name


def safe_release_name(name):
    """Como safe_zip_name pero admite también .mrpack (paquetes de Modrinth, que son zips)."""
    name = os.path.basename(urllib.parse.unquote(name or ""))
    if not REL_RE.fullmatch(name):
        raise ValueError("nombre de archivo no válido (solo .zip o .mrpack, sin rutas)")
    return name


def list_releases(server):
    d = release_dir(server)
    return sorted(({"file": f.name, "size": f.stat().st_size, "mtime": int(f.stat().st_mtime)}
                   for f in d.iterdir() if f.is_file() and REL_RE.fullmatch(f.name)),
                  key=lambda x: -x["mtime"])


def finish_upload(server, tmp, fname):
    """Valida el zip subido y lo deja como release."""
    if not zipfile.is_zipfile(tmp):
        tmp.unlink(missing_ok=True)
        raise ValueError("el archivo no es un zip válido")
    dest = release_dir(server) / fname
    tmp.replace(dest)
    return fname


def delete_release(server, fname):
    fname = safe_release_name(fname)
    with LOCK:
        if SHARE and SHARE["server"] == server and SHARE["file"] == fname:
            raise RuntimeError("detén la descarga pública antes de borrar este archivo")
    p = release_dir(server) / fname
    if not p.exists():
        raise FileNotFoundError("release no encontrada")
    p.unlink()


# ---------- mini servidor de un solo archivo ----------

def _make_handler(token, path, fname):
    url_path = f"/{token}/{urllib.parse.quote(fname)}"

    class OneFile(BaseHTTPRequestHandler):
        server_version = "release/1.0"

        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.split("?")[0] != url_path:
                self.send_error(404)
                return
            try:
                size = path.stat().st_size
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Length", str(size))
                self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                with open(path, "rb") as fh:
                    while chunk := fh.read(1 << 20):
                        self.wfile.write(chunk)
                with LOCK:
                    if SHARE:
                        SHARE["downloads"] += 1
            except (BrokenPipeError, ConnectionResetError):
                pass

    return OneFile, url_path


def _kill_stale():
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            if b"cloudflared" in Path(f"/proc/{pid}/cmdline").read_bytes():
                os.kill(pid, signal.SIGTERM)
        except (ValueError, OSError):
            pass
        PID_FILE.unlink(missing_ok=True)


def _doh_ip(host):
    """IP del host según el DNS de Cloudflare por HTTPS. No toca la caché del DNS local."""
    req = urllib.request.Request(f"https://cloudflare-dns.com/dns-query?name={host}&type=A",
                                 headers={"Accept": "application/dns-json", "User-Agent": "release-check/1.0"})
    with urllib.request.urlopen(req, timeout=8) as r:
        answers = [a["data"] for a in json.load(r).get("Answer", []) if a.get("type") == 1]
    return answers[0] if answers else None


def _https_status(ip, host):
    ctx = ssl.create_default_context()
    with socket.create_connection((ip, 443), timeout=8) as raw, ctx.wrap_socket(raw, server_hostname=host) as tls:
        tls.sendall(f"GET / HTTP/1.1\r\nHost: {host}\r\nUser-Agent: release-check/1.0\r\nConnection: close\r\n\r\n".encode())
        return int(tls.recv(64).split()[1])


def _reachable(url, timeout=60, interval=3):
    """Espera a que el túnel responda desde internet. Un 404 de nuestro mini servidor sobre "/"
    prueba que DNS, túnel y ruta funcionan; los fallos del túnel dan 5xx. No usa el DNS local
    porque una consulta temprana quedaría cacheada como inexistente en el router."""
    host = urllib.parse.urlparse(url).hostname
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            ip = _doh_ip(host)
            if ip and _https_status(ip, host) == 404:
                return True
        except Exception:  # noqa: BLE001 - aún sin propagar, conexión rechazada, etc.
            pass
        time.sleep(interval)
    return False


def status():
    with LOCK:
        if not SHARE:
            return {"active": False, "cloudflared": BIN.exists()}
        return {"active": True, "server": SHARE["server"], "file": SHARE["file"], "url": SHARE["url"],
                "expires_at": SHARE["expires_at"], "downloads": SHARE["downloads"], "ready": SHARE["ready"],
                "cloudflared": True}


def start_share(server, fname, minutes=DEFAULT_MINUTES):
    global SHARE
    fname = safe_release_name(fname)
    path = release_dir(server) / fname
    if not path.is_file():
        raise FileNotFoundError("release no encontrada")
    if not BIN.exists():
        raise RuntimeError("falta bin/cloudflared")
    minutes = max(1, min(int(minutes), MAX_MINUTES))
    stop_share()
    token = secrets.token_urlsafe(24)
    handler, url_path = _make_handler(token, path, fname)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    proc = subprocess.Popen([str(BIN), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    PID_FILE.write_text(str(proc.pid))
    found = {}

    def drain():
        for line in proc.stderr:  # sigue leyendo para no bloquear el proceso
            m = URL_RE.search(line)
            if m and "url" not in found:
                found["url"] = m.group(0)
            if "Registered tunnel connection" in line:
                found["registered"] = True

    threading.Thread(target=drain, daemon=True).start()
    deadline = time.time() + 40
    while time.time() < deadline and "url" not in found and proc.poll() is None:
        time.sleep(0.25)
    if "url" not in found:
        proc.kill()
        httpd.shutdown()
        PID_FILE.unlink(missing_ok=True)
        raise RuntimeError("no se pudo crear el túnel de Cloudflare (¿sin internet?)")

    # No consultar el DNS antes de tiempo: espera a que el túnel esté registrado y deja un margen.
    reg_deadline = time.time() + 30
    while time.time() < reg_deadline and not found.get("registered") and proc.poll() is None:
        time.sleep(0.25)
    time.sleep(4)
    ready = _reachable(found["url"])
    expires = int(time.time()) + minutes * 60
    timer = threading.Timer(minutes * 60, stop_share)
    timer.daemon = True
    timer.start()
    with LOCK:
        SHARE = {"server": server, "file": fname, "url": found["url"] + url_path, "expires_at": expires,
                 "downloads": 0, "ready": ready, "proc": proc, "httpd": httpd, "timer": timer}
    return status()


def stop_share():
    global SHARE
    with LOCK:
        s, SHARE = SHARE, None
    if not s:
        return
    s["timer"].cancel()
    try:
        s["proc"].terminate()
        s["proc"].wait(timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        s["proc"].kill()
    s["httpd"].shutdown()
    s["httpd"].server_close()
    PID_FILE.unlink(missing_ok=True)


_kill_stale()
atexit.register(stop_share)
