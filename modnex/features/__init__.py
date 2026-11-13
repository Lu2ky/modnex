"""Funciones del gestor sobre la API de plugins: copias, diagnóstico, avisos, tareas, actualización segura, servidor de pruebas, sincronización, estadísticas, propuestas y seguridad."""
from pathlib import Path

from . import (account_routes, backups, backups_routes, doctor_routes, event_hooks, notify, notify_routes, kubejs_routes, perf_routes, proposal_routes, proposals,
               remote_routes, retention, schedule_routes, scheduler, security, spark, staging, staging_routes, stats_routes, sync_routes,
               update_routes)

WEB = Path(__file__).parent / "web"


def register(api):
    api.add_schema(notify.SCHEMA)
    api.add_schema(scheduler.SCHEMA)
    api.add_schema(proposals.SCHEMA)
    api.add_schema(security.SCHEMA)
    api.add_schema(staging.SCHEMA)
    api.add_schema(retention.SCHEMA)
    if retention.after_create not in backups.AFTER_CREATE:
        backups.AFTER_CREATE.append(retention.after_create)
    api.page("seguridad", "Seguridad")
    for tab_id, label in (("copias", "Copias"), ("diagnostico", "Diagnóstico"), ("avisos", "Avisos")):
        api.tab(tab_id, label, group="proteger")
    api.tab("pruebas", "Servidor de pruebas", group="proteger")
    api.tab("actualizar", "Actualizar mods", group="contenido")
    api.tab("kubejs", "KubeJS", group="contenido", addon="kubejs")
    api.tab("propuestas", "Propuestas", admin=False, perm="*", group="contenido")
    api.tab("sincronizacion", "Sincronización", group="distribuir")
    api.tab("rendimiento", "Rendimiento", group="operar")
    api.tab("estadisticas", "Estadísticas", admin=False, perm="players", group="operar")
    api.rail("copias", "Copias")
    api.asset("panel.js", WEB / "panel.js", "application/javascript; charset=utf-8", script=True)
    api.asset("kjs_rules.js", WEB / "kjs_rules.js", "application/javascript; charset=utf-8", script=True)
    api.asset("panel.css", WEB / "panel.css", "text/css; charset=utf-8")

    # --- extras al crear un servidor ---
    if hasattr(api, "extra"):    # núcleos anteriores a los extras no tienen este gancho
        api.extra("spark", "Perfilador de rendimiento (spark)",
                  "Mide los TPS y qué mod gasta más tiempo por tick, con el comando /spark. Es un mod aparte (GPL).",
                  spark.install, loaders=spark.LOADERS)

    for area in (backups_routes, schedule_routes, doctor_routes, update_routes, staging_routes, sync_routes, proposal_routes,
                 stats_routes, perf_routes, kubejs_routes, notify_routes, account_routes, remote_routes, event_hooks):
        area.register(api)
