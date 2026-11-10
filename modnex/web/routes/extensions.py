"""Lo que aportan los plugins: su inventario para el panel y sus rutas globales."""

from modnex import plugins
from modnex.web.router import PASS, Reply, route


@route("GET", r"/api/plugins")
def plugin_info(req):
    return plugins.info()


@route("*", r"/api/features/([a-z0-9_]+)")
def feature_route(req):
    gr = plugins.dispatch_global(req.method, req.user, req.m.group(1), req.q, req.body)
    return PASS if gr is None else Reply(gr[0], gr[1])
