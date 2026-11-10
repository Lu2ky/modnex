"""Actualización segura de mods en un entorno aislado."""
from . import notify, safeupdate
from .guard import _guard


def register(api):
    ctx = api.ctx

    @api.route("GET", "safe_update")
    @_guard
    def r_safe_update(ctx, user, name, q, b):
        job = safeupdate.public(safeupdate.JOBS.get(name)) or {"state": "none"}
        return 200, {**job, "running": bool(ctx.status(name)["running"])}

    @api.route("POST", "safe_update_start")
    @_guard
    def r_safe_update_start(ctx, user, name, q, b):
        safeupdate.start_job(ctx, name)
        ctx.audit(user, name, "prueba de actualización de mods", "")
        return 202, {"started": True}

    @api.route("POST", "safe_update_apply")
    @_guard
    def r_safe_update_apply(ctx, user, name, q, b):
        files = b.get("files")
        if not isinstance(files, list) or not all(isinstance(f, str) for f in files):
            raise ValueError("lista de mods no válida")
        r = safeupdate.apply(ctx, name, files)
        ctx.audit(user, name, "actualizar mods", f"{len(r['applied'])} (copia previa {r['backup']})")
        notify.send(ctx, name, "backup", f"Se actualizaron {len(r['applied'])} mods de «{name}» (hay copia previa).")
        return 200, r
