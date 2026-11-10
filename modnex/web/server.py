"""Servidor HTTP del panel: cabeceras de seguridad, cookie de sesión, cuerpos y subidas, y el enrutado hacia `routes/`."""
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler

from modnex.infra import db
from modnex.services import release
from modnex.services.resourcepacks import packs_dir
from modnex.web import routes  # noqa: F401  (registra las rutas)
from modnex.web.access import AccessPolicy
from modnex.web.errors import to_response
from modnex.web.router import HANDLED, JSON, PASS, Reply, Request, dispatch

COOKIE = "mgr_session"
CSP = ("default-src 'self'; img-src 'self' data: https:; style-src 'self'; script-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


class Handler(AccessPolicy, BaseHTTPRequestHandler):
    ctx = None   # lo fija la raíz de composición: lo que los servicios necesitan de fuera (plugins)
    server_version = "CobblemonManager/2.0"

    def log_message(self, *args):
        pass

    # --- respuesta ---
    def _send(self, code, payload, ctype=JSON, headers=None):
        data = json.dumps(payload).encode() if ctype.startswith("application/json") else payload
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy", CSP)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _reply(self, out):
        """Escribe lo que devolvió una ruta: un Reply, un cuerpo JSON (200) o nada si ya respondió ella."""
        if out is HANDLED:
            return
        if out is PASS:
            return self._send(404, {"error": "no encontrado"})
        if not isinstance(out, Reply):
            out = Reply(200, out)
        return self._send(out.status, out.body, out.ctype, out.headers)

    # --- entrada ---
    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 1_000_000:
            raise ValueError("cuerpo demasiado grande")
        return json.loads(self.rfile.read(n) or b"{}")

    def _cookie(self):
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return urllib.parse.unquote(v)
        return None

    def _cookie_header(self, token, max_age):
        secure = "; Secure" if self._https() else ""
        return {"Set-Cookie": f"{COOKIE}={urllib.parse.quote(token)}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}{secure}"}

    def _serve_pack(self, token, fname):
        row = db.pack_lookup(token, fname)
        f = packs_dir(row["server_name"]) / row["filename"] if row else None
        if not row or not f.is_file():
            return self._send(404, {"error": "no encontrado"})
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(f.stat().st_size))
        self.send_header("Content-Disposition", f'attachment; filename="{row["filename"]}"')
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            with open(f, "rb") as fh:
                while chunk := fh.read(1 << 20):
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _save_upload(self, dest_dir, limit, namer=release.safe_zip_name):
        fname = namer(self.headers.get("X-Filename", ""))
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > limit:
            raise ValueError(f"tamaño no válido (máximo {limit // (1 << 20)} MB)")
        tmp = dest_dir / (fname + ".part")
        remaining = n
        with open(tmp, "wb") as fh:
            while remaining > 0:
                chunk = self.rfile.read(min(1 << 20, remaining))
                if not chunk:
                    break
                fh.write(chunk)
                remaining -= len(chunk)
        if remaining:
            tmp.unlink(missing_ok=True)
            raise ValueError("subida incompleta")
        return tmp, fname

    # --- enrutado ---
    def _route(self, method):
        if not self._same_origin():
            return self._send(403, {"error": "origen no permitido"})
        u = urllib.parse.urlparse(self.path)
        req = Request(self, method, u.path, dict(urllib.parse.parse_qsl(u.query)), None)
        try:
            return self._reply(dispatch(req))
        except Exception as e:  # noqa: BLE001 - se devuelve al cliente (con su código) para depurar
            return self._send(*to_response(e))

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")
