"""Servidor de pruebas hijo y su fusión con el real."""
from . import staging, sync
from .guard import _guard


def register(api):
    ctx = api.ctx

    @api.route("GET", "staging")
    @_guard
    def r_staging(ctx, user, name, q, b):
        return 200, staging.status(ctx, name)

    @api.route("POST", "staging_create")
    @_guard
    def r_staging_create(ctx, user, name, q, b):
        r = staging.create(ctx, name)
        ctx.audit(user, name, "crear servidor de pruebas", r["staging"])
        return 200, r

    @api.route("GET", "staging_diff")
    @_guard
    def r_staging_diff(ctx, user, name, q, b):
        return 200, staging.diff(ctx, name)

    @api.route("POST", "staging_merge")
    @_guard
    def r_staging_merge(ctx, user, name, q, b):
        r = staging.merge(ctx, name, b.get("picks"))
        ctx.audit(user, name, "fusionar configuración de pruebas", f"{len(r['merged'])} archivos (copia previa {r['backup']})")
        return 200, r

    @api.route("POST", "staging_merge_mods")
    @_guard
    def r_staging_merge_mods(ctx, user, name, q, b):
        r = staging.merge_mods(ctx, name, b.get("picks"))
        ctx.audit(user, name, "fusionar mods de pruebas", f"{len(r['merged'])} mods (copia previa {r['backup']})")
        return 200, r

    @api.route("POST", "staging_delete")
    @_guard
    def r_staging_delete(ctx, user, name, q, b):
        r = staging.delete(ctx, name)
        ctx.audit(user, name, "borrar servidor de pruebas", r["deleted"])
        return 200, r

    @api.route("POST", "staging_sync_install")
    @_guard
    def r_staging_sync_install(ctx, user, name, q, b):
        pair = staging.link(ctx, name)
        if not pair:
            raise staging.StagingError("este servidor no tiene servidor de pruebas")
        r = sync.install_in_staging(ctx, pair[1])
        ctx.audit(user, pair[1], "instalar AutoModpack en pruebas", r["installed"])
        return 200, r
