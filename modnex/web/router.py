"""Tabla de rutas de la API.

Cada ruta es una función `fn(req)` registrada con `@route(método, patrón, auth=...)`:

    @route("GET", r"/api/tags")                  # exige sesión
    @route("POST", r"/api/users", auth="admin")  # exige administrador
    @route("POST", r"/api/login", auth="public") # sin sesión

Las acciones de un servidor (`/api/servers/<nombre>/<acción>`) se declaran con `@server_action`, indicando el permiso
que hace falta. La función devuelve el cuerpo JSON (200), un `Reply` si necesita otro código o cabeceras, o `PASS` para
dejar que siga buscando otra ruta.
"""
import re
from collections import namedtuple

from modnex.infra import db

PASS = object()      # la ruta no se ocupa de esta petición: seguir con la siguiente
HANDLED = object()   # la ruta ya escribió la respuesta ella misma (descargas en trozos)

JSON = "application/json; charset=utf-8"
Reply = namedtuple("Reply", "status body ctype headers", defaults=(200, None, JSON, None))
ServerAction = namedtuple("ServerAction", "fn perm raw")

ROUTES = []            # (método, patrón compilado, función, auth)
SERVER_ACTIONS = {}    # (método, acción) -> ServerAction


def route(method, pattern, auth="user"):
    """Registra una ruta. method puede ser "GET", "POST" o "*" (cualquiera). auth: "public", "user" o "admin"."""
    rx = re.compile(pattern)

    def deco(fn):
        ROUTES.append((method, rx, fn, auth))
        return fn
    return deco


def server_action(method, action, perm=None, raw=False):
    """Registra una acción de servidor. perm: None = solo administradores, "*" = cualquier permiso sobre el servidor,
    o el nombre de un permiso (mods, logs, control...). raw: el cuerpo no es JSON (subidas de archivos)."""
    def deco(fn):
        SERVER_ACTIONS[(method, action)] = ServerAction(fn, perm, raw)
        return fn
    return deco


class Request:
    """Lo que una ruta necesita saber de la petición, sin tocar el manejador HTTP directamente."""

    def __init__(self, handler, method, path, query, user):
        self.h, self.method, self.path, self.q, self.user, self.m = handler, method, path, query, user, None

    def body(self):
        return self.h._body()

    def need_admin(self):
        if not self.user["is_admin"]:
            raise PermissionError("solo administradores")

    def need(self, server, perm):
        """Exige un permiso sobre un servidor; "*" admite cualquiera."""
        if perm == "*":
            if not any(db.can(self.user, server, p) for p in db.PERMS):
                raise PermissionError("no tienes permiso para esto")
        elif not db.can(self.user, server, perm):
            raise PermissionError("no tienes permiso para esto")


def _match(req, auth_levels):
    for method, rx, fn, auth in ROUTES:
        if auth not in auth_levels or method not in ("*", req.method):
            continue
        m = rx.fullmatch(req.path)
        if not m:
            continue
        req.m = m
        if auth == "admin":
            req.need_admin()
        out = fn(req)
        if out is not PASS:
            return out
    return PASS


def dispatch(req):
    """Busca la ruta de la petición y devuelve lo que ella devuelve (o PASS si ninguna la atiende).
    Primero las públicas; luego se exige sesión, y para un administrador, que no llegue desde fuera de la red local."""
    out = _match(req, ("public",))
    if out is not PASS:
        return out
    req.user = db.user_for_token(req.h._cookie())
    if req.path.startswith("/api/") and not req.user:
        return Reply(401, {"error": "no autorizado"})
    if req.h._admin_remote_blocked(req.user):   # una sesión de administrador no sirve desde fuera, aunque se robe la cookie
        return Reply(403, {"error": "los administradores solo pueden usar el panel desde este equipo o la red local"})
    return _match(req, ("user", "admin"))
