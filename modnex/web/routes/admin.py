"""Administración: usuarios y permisos, auditoría y la descarga pública temporal del cliente."""
from modnex.infra import db
from modnex.services import release
from modnex.services.servers import server_path
from modnex.web.router import route


@route("GET", r"/api/users", auth="admin")
def users(req):
    return db.list_users()


@route("POST", r"/api/users", auth="admin")
def create_user(req):
    b = req.body()
    uid = db.create_user(b.get("username", ""), b.get("password", ""), bool(b.get("is_admin")))
    db.audit(req.user, None, "crear usuario", b.get("username"))
    return {"id": uid}


@route("POST", r"/api/users/(\d+)/(update|delete|permissions)", auth="admin")
def edit_user(req):
    user = req.user
    uid, action = int(req.m.group(1)), req.m.group(2)
    b = req.body()
    target = db.get_user(uid)
    if not target:
        raise FileNotFoundError("usuario no encontrado")
    if action == "update":
        db.update_user(uid, password=b.get("password"), is_admin=b.get("is_admin"), active=b.get("active"))
        db.audit(user, None, "editar usuario", target["username"])
    elif action == "delete":
        if uid == user["id"]:
            raise ValueError("no puedes borrar tu propia cuenta")
        db.delete_user(uid)
        db.audit(user, None, "borrar usuario", target["username"])
    elif "permissions" in b:  # guardado explícito de todos los permisos del usuario
        perms = b["permissions"]
        if not isinstance(perms, dict):
            raise ValueError("permisos no válidos")
        clean = {}
        for srv, p in perms.items():
            server_path(srv)
            clean[srv] = {k: bool(p.get(k)) for k in db.PERMS}
        db.set_all_permissions(uid, clean)
        db.audit(user, None, "permisos", f"{target['username']}: " + ", ".join(
            f"{s}[{'/'.join(k for k in db.PERMS if p[k]) or '-'}]" for s, p in clean.items()))
    else:
        server_path(b["server"])
        db.set_permissions(uid, b["server"], {k: bool(b.get(k)) for k in db.PERMS})
        db.audit(user, b["server"], "permisos", f"{target['username']}: {b}")
    return {"ok": True}


@route("GET", r"/api/audit", auth="admin")
def audit(req):
    return db.recent_audit(int(req.q.get("limit", 100)))


@route("GET", r"/api/share", auth="admin")
def share_status(req):
    return release.status()


@route("POST", r"/api/share_stop", auth="admin")
def share_stop(req):
    release.stop_share()
    db.audit(req.user, None, "detener descarga pública")
    return {"ok": True}
