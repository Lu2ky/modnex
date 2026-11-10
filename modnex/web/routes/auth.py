"""Sesión: entrar, salir y la cuenta propia."""
from modnex import plugins
from modnex.infra import db
from modnex.web.router import Reply, route


@route("POST", r"/api/login", auth="public")
def login(req):
    h, b = req.h, req.body()
    try:
        user = db.authenticate(b.get("username", ""), b.get("password", ""), h._client_ip())
    except PermissionError as e:
        return Reply(429, {"error": str(e)})
    if not user:
        return Reply(401, {"error": "usuario o contraseña incorrectos"})
    if h._admin_remote_blocked(user):
        # Misma respuesta que una contraseña errónea: desde fuera no se revela que la cuenta existe ni que es admin.
        db.register_fail(h._client_ip())
        db.audit(user, None, "acceso de administrador bloqueado", f"desde fuera de la red local ({h._client_ip()})")
        return Reply(401, {"error": "usuario o contraseña incorrectos"})
    sf = plugins.second_factor(user, b, h._via_tunnel(), h._client_ip())
    if sf:
        if len(sf) > 2 and sf[2]:
            db.register_fail(h._client_ip())
        return Reply(sf[0], sf[1])
    token = db.create_session(user["id"])
    db.audit(user, None, "login")
    return Reply(200, {"user": user}, headers=h._cookie_header(token, db.SESSION_TTL))


@route("POST", r"/api/logout", auth="public")
def logout(req):
    db.delete_session(req.h._cookie())
    return Reply(200, {"ok": True}, headers=req.h._cookie_header("", 0))


@route("GET", r"/api/me")
def me(req):
    return {"user": req.user, "icons": db.ICONS}


@route("POST", r"/api/me/password")
def change_password(req):
    b = req.body()
    if not db.verify_password(req.user["id"], b.get("old", "")):
        return Reply(400, {"error": "la contraseña actual no es correcta"})
    db.update_user(req.user["id"], password=b.get("new", ""))
    token = db.create_session(req.user["id"])  # update_user cerró las sesiones
    db.audit(req.user, None, "cambio de contraseña")
    return Reply(200, {"ok": True}, headers=req.h._cookie_header(token, db.SESSION_TTL))
