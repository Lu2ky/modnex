"""Copias de seguridad, su historial en árbol y las reglas de ciclo de vida."""
import shutil

from . import backups, notify, retention, scheduler
from .guard import _guard


def register(api):
    ctx = api.ctx

    @api.route("GET", "backups")
    @_guard
    def r_backups(ctx, user, name, q, b):
        d = backups.backup_dir(ctx, name)
        return 200, {"backups": backups.list_backups(ctx, name), "graph": backups.graph(ctx, name), "job": backups.JOBS.get(name),
                     "free": shutil.disk_usage(d).free, "schedules": scheduler.list_schedules(ctx, name),
                     "running": bool(ctx.status(name)["running"]),
                     "retention": {"policy": retention.get(ctx, name), "plan": retention.plan(ctx, name)}}

    @api.route("POST", "backup_pin")
    @_guard
    def r_backup_pin(ctx, user, name, q, b):
        pinned = b.get("pinned")
        if not isinstance(pinned, bool):
            raise ValueError("indica si se fija o se suelta")
        m = backups.set_pinned(ctx, name, str(b.get("id") or ""), pinned)
        ctx.audit(user, name, "copia fijada" if pinned else "copia soltada", m["id"])
        return 200, {"id": m["id"], "pinned": m["pinned"]}

    @api.route("POST", "retention_preview")
    @_guard
    def r_retention_preview(ctx, user, name, q, b):
        return 200, retention.plan(ctx, name, retention.validate({**retention.get(ctx, name), **(b or {})}))

    @api.route("POST", "retention_set")
    @_guard
    def r_retention_set(ctx, user, name, q, b):
        p = retention.save(ctx, name, b or {})
        ctx.audit(user, name, "reglas de retención de copias", ", ".join(f"{k}={v}" for k, v in p.items()))
        return 200, {"policy": p, "plan": retention.plan(ctx, name)}

    @api.route("POST", "retention_apply")
    @_guard
    def r_retention_apply(ctx, user, name, q, b):
        r = retention.apply(ctx, name)
        ctx.audit(user, name, "reglas de retención aplicadas", f"{len(r['deleted'])} copias")
        return 200, r

    @api.route("POST", "backup_create")
    @_guard
    def r_backup_create(ctx, user, name, q, b):
        label = str(b.get("label") or "")[:80]
        note = str(b.get("note") or "")[:500]

        def done(meta, err):
            if meta:
                ctx.audit(user, name, "copia de seguridad", meta["id"])
                notify.send(ctx, name, "backup", f"Copia de «{name}» creada ({meta['size'] // 2**20} MB).")
            else:
                ctx.audit(user, name, "copia fallida", str(err)[:200])
                notify.send(ctx, name, "backup", f"La copia de «{name}» falló: {err}")
        backups.run_job(ctx, name, on_done=done, label=label, note=note, kind="manual")
        return 202, {"started": True}

    @api.route("POST", "backup_restore")
    @_guard
    def r_backup_restore(ctx, user, name, q, b):
        if b.get("confirm") != name:
            raise ValueError("falta la confirmación: escribe el nombre del servidor")
        r = backups.restore(ctx, name, str(b.get("id") or ""))
        ctx.audit(user, name, "restaurar copia", f"{r['restored']} (antes: {r['safety']})")
        return 200, r

    @api.route("POST", "backup_delete")
    @_guard
    def r_backup_delete(ctx, user, name, q, b):
        backups.delete(ctx, name, str(b.get("id") or ""))
        ctx.audit(user, name, "borrar copia", str(b.get("id")))
        return 200, {"ok": True}

    @api.route("POST", "backup_forget")
    @_guard
    def r_backup_forget(ctx, user, name, q, b):
        backups.forget(ctx, name, str(b.get("id") or ""))
        ctx.audit(user, name, "quitar copia borrada del historial", str(b.get("id")))
        return 200, {"ok": True}

    @api.route("GET", "backup_diff")
    @_guard
    def r_backup_diff(ctx, user, name, q, b):
        return 200, backups.diff(ctx, name, q.get("a", ""), q.get("b", "current"))
