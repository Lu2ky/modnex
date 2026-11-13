"""Rendimiento (spark)."""
from . import perf
from .guard import _guard


def register(api):
    @api.route("GET", "performance")
    @_guard
    def r_performance(ctx, user, name, q, b):
        return 200, perf.info(ctx, name)

    @api.route("POST", "performance_run")
    @_guard
    def r_performance_run(ctx, user, name, q, b):
        action = str(b.get("action") or "")
        out = perf.run(ctx, name, action)
        ctx.audit(user, name, "spark: " + action, "")
        return 200, out
