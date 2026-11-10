"""Avisos a Discord."""
from . import notify
from .guard import _guard


def register(api):
    ctx = api.ctx

    @api.route("GET", "notify")
    @_guard
    def r_notify(ctx, user, name, q, b):
        return 200, notify.get(ctx, name)

    @api.route("POST", "notify_set")
    @_guard
    def r_notify_set(ctx, user, name, q, b):
        notify.set_config(ctx, name, str(b.get("webhook") or ""), b.get("events") or [])
        ctx.audit(user, name, "avisos de Discord configurados", "")
        return 200, notify.get(ctx, name)

    @api.route("POST", "notify_remove")
    @_guard
    def r_notify_remove(ctx, user, name, q, b):
        notify.remove(ctx, name)
        ctx.audit(user, name, "avisos de Discord quitados", "")
        return 200, {"ok": True}

    @api.route("POST", "notify_test")
    @_guard
    def r_notify_test(ctx, user, name, q, b):
        if not notify.send(ctx, name, "started", f"Prueba de aviso de Modnex para «{name}».", force=True):
            raise ValueError("no se pudo enviar el aviso de prueba (¿webhook configurado y válido?)")
        return 200, {"ok": True}
