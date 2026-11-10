"""Eventos del núcleo que disparan avisos, y los procesos de fondo (tareas y vigilancia)."""
from . import monitor, notify, scheduler


def register(api):
    ctx = api.ctx

    @api.on("server_started")
    def on_started(ctx, name):
        notify.send(ctx, name, "started", f"Servidor «{name}» arrancando.")

    @api.on("server_stopped")
    def on_stopped(ctx, name, why=""):
        notify.send(ctx, name, "stopped", f"Servidor «{name}» parado ({why}).")

    @api.on("server_crashed")
    def on_crashed(ctx, name, why=""):
        notify.send(ctx, name, "crashed", f"Servidor «{name}» se ha caído: {why}.")

    scheduler.start(ctx)
    monitor.start(ctx)
