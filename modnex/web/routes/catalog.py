"""Buscar e instalar mods, plugins y datapacks."""
from modnex.infra import db
from modnex.services.addons import install, server_loader
from modnex.services.catalog import KINDS, category_tags, compat_for, mod_files, search
from modnex.services.deps import install_many, resolve_deps
from modnex.services.detail import mod_detail
from modnex.web.router import route


@route("GET", r"/api/(search|files)")
def search_or_files(req):
    q = req.q
    kind = q.get("kind", "mod")
    if kind not in KINDS:
        raise ValueError("tipo de contenido no válido")
    if not db.can_any(req.user, KINDS[kind]["perm"]):
        raise PermissionError("no tienes permiso para buscar este contenido")
    loader, version = q.get("loader", "neoforge"), q.get("version", "1.21.1")
    sv = q.get("server")
    if sv:
        req.need(sv, KINDS[kind]["perm"])
        loader, kind = compat_for(sv, kind)
        kind = kind if kind in KINDS else "mod"
    if req.m.group(1) == "search":
        paged = "page" in q
        return search(q.get("source", "modrinth"), q.get("q", ""), loader, version, kind, q.get("sort", "auto"), q.get("side", "server"),
                      int(q.get("page", 1) or 1), [t for t in q.get("tags", "").split(",") if t], paged)
    return mod_files(q["source"], q["project"], q.get("slug", ""), loader, version, kind)


@route("GET", r"/api/tags")
def tags(req):
    kind = req.q.get("kind", "mod")
    if kind not in KINDS:
        raise ValueError("tipo de contenido no válido")
    if not db.can_any(req.user, KINDS[kind]["perm"]):
        raise PermissionError("no tienes permiso para este contenido")
    return category_tags(kind)


@route("GET", r"/api/mod")
def mod(req):
    if not db.can_any(req.user, "mods"):
        raise PermissionError("no tienes permiso para ver fichas de mods")
    q = req.q
    return mod_detail(q.get("source", "modrinth"), q["id"], q.get("loader", "neoforge"), q.get("version", "1.21.1"))


@route("GET", r"/api/deps")
def deps(req):
    q = req.q
    req.need(q["server"], "mods")
    compat_for(q["server"], "mod")
    return resolve_deps(q["server"], q["source"], q["project"], q["vid"],
                        server_loader(q["server"]) or q.get("loader", "neoforge"), q.get("version", "1.21.1"))


@route("POST", r"/api/install_many")
def install_many_route(req):
    b = req.body()
    req.need(b["server"], "mods")
    compat_for(b["server"], "mod")
    res = install_many(b["server"], b.get("items"))
    db.audit(req.user, b["server"], "instalar mods con dependencias", ", ".join(r["file"] for r in res if r["ok"])[:250])
    return {"results": res}


@route("POST", r"/api/install")
def install_route(req):
    b = req.body()
    kind = b.get("kind", "mod")
    if kind not in ("mod", "plugin", "datapack"):
        raise ValueError("tipo no instalable")
    req.need(b["server"], KINDS[kind]["perm"])
    compat_for(b["server"], kind)  # lanza error si el tipo no encaja con el servidor
    fname = install(b["server"], b["url"], b["filename"], b.get("sha1"), kind)
    db.audit(req.user, b["server"], f"instalar {'datapack' if kind == 'datapack' else 'mod'}", fname)
    return {"installed": fname}
