"""Cuenta: verificación en dos pasos, que cada usuario gestiona por su cuenta."""
from . import security
from .guard import _admin, _own


def register(api):
    ctx = api.ctx
    api.second_factor(security.login_hook)

    @api.global_route("GET", "2fa_status")
    @_own
    def g_2fa_status(ctx, user, q, b):
        return 200, security.status(ctx, user["id"])

    @api.global_route("POST", "2fa_begin")
    @_own
    def g_2fa_begin(ctx, user, q, b):
        return 200, security.begin(ctx, user)

    @api.global_route("POST", "2fa_confirm")
    @_own
    def g_2fa_confirm(ctx, user, q, b):
        codes = security.confirm(ctx, user, str(b.get("code") or ""))
        ctx.audit(user, None, "2FA activado", "")
        return 200, {"recovery": codes}

    @api.global_route("POST", "2fa_disable")
    @_own
    def g_2fa_disable(ctx, user, q, b):
        security.disable(ctx, user, str(b.get("code") or ""))
        ctx.audit(user, None, "2FA desactivado", "")
        return 200, {"ok": True}

    @api.global_route("POST", "2fa_reset")
    @_own
    def g_2fa_reset(ctx, user, q, b):
        _admin(user)
        target = ctx.db_run("SELECT id, username FROM users WHERE id = ?", (int(b.get("user_id") or 0),), one=True)
        if not target:
            raise ValueError("ese usuario no existe")
        security.remove(ctx, target["id"])
        ctx.audit(user, None, "2FA restablecido", target["username"])
        return 200, {"ok": True}
