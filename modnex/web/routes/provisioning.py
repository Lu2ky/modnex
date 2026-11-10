"""Crear servidores: plantillas, modpacks, extras y el seguimiento de los trabajos de creación."""
from modnex.services import extras, modpacks, templates
from modnex.services.creation import create_modpack_server, create_server
from modnex.web.router import route


@route("GET", r"/api/templates")
def template_list(req):
    return [{"id": k, "label": v["label"], "kind": v["kind"], "desc": v["desc"], "loader": v["loader"],
             "perf": templates.perf_list(k)} for k, v in templates.TEMPLATES.items()]


@route("GET", r"/api/extras")
def extra_list(req):
    return extras.listing()


@route("GET", r"/api/templates/versions", auth="admin")
def template_versions(req):
    return {"versions": templates.versions(req.q.get("template", ""))}


@route("GET", r"/api/jobs/[^/]+", auth="admin")
def job_status(req):
    st = templates.job_status(req.path.rsplit("/", 1)[1])
    if not st:
        raise FileNotFoundError("trabajo no encontrado")
    return st


@route("GET", r"/api/modpacks/search", auth="admin")
def modpack_search(req):
    return modpacks.search(req.q.get("source", "modrinth"), req.q.get("q", ""), req.q.get("mc", "1.21.1"))


@route("GET", r"/api/modpacks/versions", auth="admin")
def modpack_versions(req):
    return modpacks.versions(req.q.get("source", "modrinth"), req.q["project"], req.q.get("mc", "1.21.1"))


@route("POST", r"/api/servers/create_modpack", auth="admin")
def create_from_modpack(req):
    return {"job": create_modpack_server(req.user, req.body(), req.h.ctx)}


@route("POST", r"/api/servers/create", auth="admin")
def create_from_template(req):
    return {"job": create_server(req.user, req.body(), req.h.ctx)}
