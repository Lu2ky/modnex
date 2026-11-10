"""Carga opcional de plugins (edición Pro).

El núcleo no contiene código de Pro ni depende de él. Si existe un paquete `modnex_pro`
(ruta en la variable MODNEX_PRO_PATH o en `pro_path` de config.json) y expone
`register(api)`, se le ofrece una API pequeña:

    api.route("GET", "backups")      rutas por servidor: /api/servers/<nombre>/<acción>
    api.tab(id, label, js)           pestaña extra en la página de un servidor
    api.add_schema(sql)              tablas propias del plugin
    api.on("server_crashed")         eventos: server_started, server_stopped, server_crashed
    api.asset(nombre, ruta, mime)    archivo estático servido en /plugin/<nombre>

Si el paquete no está, o falla al cargarse, el núcleo sigue funcionando como edición gratuita.
"""
import importlib
import os
import sys
import threading
import traceback
from pathlib import Path

API = None          # PluginAPI activa, o None en la edición gratuita
LOAD_ERROR = None   # motivo por el que no se cargó, si falló (no si simplemente no existe)


class PluginAPI:
    def __init__(self, ctx):
        self.ctx = ctx
        self.name = "pro"
        self.routes = {}      # (METHOD, acción) -> fn(ctx, user, servidor, q, body) -> (status, dict)
        self.tabs = []        # [{"id","label","admin"}]
        self.scripts = []     # rutas /plugin/... que el panel debe cargar
        self.schema = []
        self.handlers = {}
        self.assets = {}
        self.pages = []            # [{"id","label","admin"}] entradas de la barra lateral
        self.global_routes = {}    # (METHOD, acción) -> fn(ctx, user, q, body) -> (status, dict)
        self.client_includes = []  # fn(ctx, name, rows) -> nombres de archivo que el cliente debe llevar siempre
        self.second_factors = []   # fn(ctx, user, body, remote, ip) -> None | (status, dict[, contar_fallo])

    def route(self, method, action):
        def deco(fn):
            self.routes[(method.upper(), action)] = fn
            return fn
        return deco

    def tab(self, tab_id, label, admin=True, perm=None):
        """perm: permiso por servidor que basta para ver la pestaña (además de ser admin); "*" = cualquiera."""
        self.tabs.append({"id": tab_id, "label": label, "admin": bool(admin), "perm": perm})

    def page(self, page_id, label, admin=False):
        """Página propia en la barra lateral (#/p/<id>); la interfaz llama a ModnexPlugins[id].renderPage."""
        self.pages.append({"id": page_id, "label": label, "admin": bool(admin)})

    def global_route(self, method, action):
        """Ruta que no es de un servidor: /api/pro/<acción>. Exige sesión; la autorización la decide el plugin."""
        def deco(fn):
            self.global_routes[(method.upper(), action)] = fn
            return fn
        return deco

    def client_include(self, fn):
        """Mods que el cliente generado debe incluir siempre (p. ej. el que lo sincroniza con el servidor)."""
        self.client_includes.append(fn)
        return fn

    def second_factor(self, fn):
        """Comprobación adicional tras acertar la contraseña. Devuelve None para dejar pasar."""
        self.second_factors.append(fn)
        return fn

    def add_schema(self, sql):
        self.schema.append(sql)

    def on(self, event):
        def deco(fn):
            self.handlers.setdefault(event, []).append(fn)
            return fn
        return deco

    def asset(self, name, path, mime, script=False):
        self.assets[name] = (Path(path), mime)
        if script:
            self.scripts.append(f"/plugin/{name}")


def load(ctx, config):
    """Intenta cargar el paquete Pro. Devuelve la API o None."""
    global API, LOAD_ERROR
    API, LOAD_ERROR = None, None
    path = os.environ.get("MODNEX_PRO_PATH") or config.get("pro_path")
    if path and Path(path).is_dir() and str(path) not in sys.path:
        sys.path.insert(0, str(path))
    try:
        mod = importlib.import_module("modnex_pro")
    except ModuleNotFoundError as e:
        if e.name != "modnex_pro":
            LOAD_ERROR = f"falta una dependencia de modnex_pro: {e.name}"
        return None
    api = PluginAPI(ctx)
    try:
        mod.register(api)
        if api.schema:
            with ctx.db_connect() as c:
                for sql in api.schema:
                    c.executescript(sql)
                c.commit()
    except Exception as e:  # un plugin roto no debe tumbar el núcleo
        LOAD_ERROR = f"{type(e).__name__}: {e}"
        traceback.print_exc()
        return None
    API = api
    return api


def info():
    return {"edition": "pro" if API else "free", "tabs": API.tabs if API else [], "pages": API.pages if API else [],
            "scripts": API.scripts if API else [], "error": LOAD_ERROR}


def client_must_include(name, rows):
    """Archivos de `rows` que un plugin exige en el cliente. Un plugin roto no impide generar el cliente."""
    out = []
    if not API:
        return out
    for fn in API.client_includes:
        try:
            out += [f for f in fn(API.ctx, name, rows) if f in rows]
        except Exception:
            traceback.print_exc()
    return list(dict.fromkeys(out))


def second_factor(user, body, remote, ip):
    """None si se permite el acceso; si no, (status, dict[, contar_fallo]).
    Falla CERRADO: si un plugin de seguridad se rompe, no se salta la verificación."""
    if not API:
        return None
    for fn in API.second_factors:
        try:
            r = fn(API.ctx, user, body, remote, ip)
        except Exception:
            traceback.print_exc()
            return 503, {"error": "no se pudo completar la verificación en dos pasos"}
        if r:
            return r
    return None


def dispatch_global(method, user, action, q, body_fn):
    if not API:
        return None
    fn = API.global_routes.get((method.upper(), action))
    if not fn:
        return None
    body = body_fn() if method.upper() == "POST" else {}
    return fn(API.ctx, user, q, body)


def dispatch(method, user, name, action, q, body_fn):
    """Si el plugin tiene esa ruta, devuelve (status, dict); si no, None."""
    if not API:
        return None
    fn = API.routes.get((method.upper(), action))
    if not fn:
        return None
    body = body_fn() if method.upper() == "POST" else {}
    return fn(API.ctx, user, name, q, body)


def asset(name):
    return API.assets.get(name) if API else None


def emit(event, *args):
    """Avisa a los plugins sin bloquear al núcleo ni propagar sus errores."""
    if not API:
        return
    for fn in API.handlers.get(event, []):
        def run(f=fn):
            try:
                f(API.ctx, *args)
            except Exception:
                traceback.print_exc()
        threading.Thread(target=run, daemon=True).start()
