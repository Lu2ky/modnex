"""Acceso remoto por túnel (solo administradores)."""
from . import remote
from .guard import _admin, _own


def register(api):
    ctx = api.ctx

    @api.global_route("GET", "remote_status")
    @_own
    def g_remote_status(ctx, user, q, b):
        _admin(user)
        return 200, {**remote.status(ctx), "require_2fa": ctx.config().get("remote_2fa", ctx.config().get("pro_remote_2fa")) is not False}

    @api.global_route("POST", "remote_start")
    @_own
    def g_remote_start(ctx, user, q, b):
        _admin(user)
        provider = str(b.get("provider") or "cloudflared")
        st = remote.start(ctx, provider)
        ctx.audit(user, None, "acceso remoto abierto", provider)
        return 200, st

    @api.global_route("POST", "remote_stop")
    @_own
    def g_remote_stop(ctx, user, q, b):
        _admin(user)
        remote.stop()
        ctx.audit(user, None, "acceso remoto cerrado", "")
        return 200, remote.status(ctx)
