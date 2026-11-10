"""Estadísticas de jugadores."""
from pathlib import Path

from . import stats
from .guard import _guard


def register(api):
    ctx = api.ctx

    @api.route("GET", "player_stats")
    @_guard(perm="players")
    def r_player_stats(ctx, user, name, q, b):
        running = bool(ctx.status(name)["running"])
        return 200, {**stats.server_stats(Path(ctx.server_path(name)) / "logs", running=running), "running": running}
