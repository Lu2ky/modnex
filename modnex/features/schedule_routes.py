"""Tareas programadas: copias y reinicios a una hora fija."""
from . import scheduler
from .guard import _guard


def register(api):
    ctx = api.ctx

    @api.route("POST", "schedule_add")
    @_guard
    def r_schedule_add(ctx, user, name, q, b):
        sid = scheduler.add(ctx, name, str(b.get("kind")), str(b.get("hhmm")), str(b.get("days") or "*"), b.get("keep", 7))
        ctx.audit(user, name, "tarea programada", f"{b.get('kind')} {b.get('hhmm')}")
        return 200, {"id": sid}

    @api.route("POST", "schedule_remove")
    @_guard
    def r_schedule_remove(ctx, user, name, q, b):
        scheduler.remove(ctx, name, b.get("id"))
        return 200, {"ok": True}

    @api.route("POST", "schedule_toggle")
    @_guard
    def r_schedule_toggle(ctx, user, name, q, b):
        scheduler.set_enabled(ctx, name, b.get("id"), b.get("enabled"))
        return 200, {"ok": True}
