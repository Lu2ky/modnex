"""Rutas públicas: el panel, sus archivos estáticos, los archivos de los plugins y la descarga de packs de texturas."""
import urllib.parse

from modnex import plugins
from modnex.config import STATIC
from modnex.infra import db
from modnex.web.router import HANDLED, PASS, Reply, route

ASSETS = {"style.css": "text/css; charset=utf-8", "app.js": "text/javascript; charset=utf-8",
          "icons.js": "text/javascript; charset=utf-8", "motion.js": "text/javascript; charset=utf-8", "theme.js": "text/javascript; charset=utf-8",
          "fonts/Inter.ttf": "font/ttf",
          "brand/modnex-mark.png": "image/png", "brand/modnex-logo.png": "image/png",
          **{f"brand/servers/{n}.png": "image/png" for n in db.ICONS}}


@route("GET", r"/", auth="public")
def root(req):
    # La landing pública es un sitio estático aparte (carpeta landing/). El gestor solo sirve el panel.
    return Reply(302, b"", "text/plain; charset=utf-8", {"Location": "/app"})


@route("GET", r"/app/?", auth="public")
def panel(req):
    return Reply(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")


@route("GET", r"/assets/([A-Za-z0-9_./-]+)", auth="public")
def asset(req):
    name = req.m.group(1)
    if name not in ASSETS:
        return PASS
    return Reply(200, (STATIC / name).read_bytes(), ASSETS[name])


@route("GET", r"/plugin/([A-Za-z0-9_.-]{1,60})", auth="public")
def plugin_asset(req):
    a = plugins.asset(req.m.group(1))
    if not a or not a[0].is_file():
        return Reply(404, {"error": "no encontrado"})
    return Reply(200, a[0].read_bytes(), a[1])


@route("GET", r"/packs/([A-Za-z0-9_-]{10,40})/([^/]+)", auth="public")
def pack_download(req):
    req.h._serve_pack(req.m.group(1), urllib.parse.unquote(req.m.group(2)))
    return HANDLED
