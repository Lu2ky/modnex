"""Sincronización de clientes con AutoModpack."""
from . import sync
from .guard import _guard


def register(api):
    ctx = api.ctx

    @api.route("GET", "sync")
    @_guard
    def r_sync(ctx, user, name, q, b):
        return 200, sync.public(ctx, name)

    @api.route("POST", "sync_test_start")
    @_guard
    def r_sync_test(ctx, user, name, q, b):
        sync.start_test(ctx, name)
        ctx.audit(user, name, "prueba de sincronización de clientes", "")
        return 202, {"started": True}

    @api.route("POST", "sync_install")
    @_guard
    def r_sync_install(ctx, user, name, q, b):
        r = sync.install(ctx, name)
        ctx.audit(user, name, "instalar sincronización de clientes", f"{r['installed']} (copia previa {r['backup']})")
        return 200, r
