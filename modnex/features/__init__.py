"""Funciones del gestor sobre la API de plugins: copias, diagnóstico, avisos, tareas, actualización segura, servidor de pruebas, sincronización, estadísticas, propuestas y seguridad."""
import shutil
from pathlib import Path

from . import backups, doctor, monitor, notify, proposals, remote, retention, safeupdate, scheduler, security, spark, staging, stats, sync

WEB = Path(__file__).parent / "web"


def _admin(user):
    if not user or not user.get("is_admin"):
        raise PermissionError("solo administradores")


def _guard(fn=None, perm=None):
    """Convierte las excepciones esperadas en respuestas HTTP claras.
    Sin `perm` solo entra un admin; con `perm`, también quien tenga ese permiso en el servidor."""
    if fn is None:
        return lambda f: _guard(f, perm)

    def wrapped(ctx, user, name, q, body):
        try:
            if perm == "*":  # cualquier permiso sobre este servidor
                if not user or not (user.get("is_admin") or any(ctx.user_perms(user["id"]).get(name, {}).values())):
                    raise PermissionError("no tienes acceso a este servidor")
            elif perm:
                if not user or not (user.get("is_admin") or ctx.can(user, name, perm)):
                    raise PermissionError("no tienes permiso para esto")
            else:
                _admin(user)
            ctx.server_path(name)  # valida que el servidor existe
            return fn(ctx, user, name, q, body or {})
        except PermissionError as e:
            return 403, {"error": str(e)}
        except (FileNotFoundError, ValueError) as e:
            return 400, {"error": str(e)}
        except backups.BackupError as e:
            return 409, {"error": str(e)}
        except proposals.ProposalError as e:
            return 400, {"error": str(e)}
        except (safeupdate.UpdateError, sync.SyncError, staging.StagingError, retention.RetentionError) as e:
            return 409, {"error": str(e)}
    return wrapped


def register(api):
    ctx = api.ctx
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
    api.tab("propuestas", "Propuestas", admin=False, perm="*", group="contenido")
    api.tab("sincronizacion", "Sincronización", group="distribuir")
    api.tab("estadisticas", "Estadísticas", admin=False, perm="players", group="operar")
    api.rail("copias", "Copias")
    api.asset("panel.js", WEB / "panel.js", "application/javascript; charset=utf-8", script=True)
    api.asset("panel.css", WEB / "panel.css", "text/css; charset=utf-8")

    # --- copias y versiones ---
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

    @api.route("GET", "backup_diff")
    @_guard
    def r_backup_diff(ctx, user, name, q, b):
        return 200, backups.diff(ctx, name, q.get("a", ""), q.get("b", "current"))

    # --- tareas programadas ---
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

    # --- diagnóstico ---
    @api.route("GET", "doctor")
    @_guard
    def r_doctor(ctx, user, name, q, b):
        return 200, doctor.diagnose(ctx, name)

    # --- actualización segura de mods ---
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

    # --- servidor de pruebas ---
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

    # --- extras al crear un servidor ---
    if hasattr(api, "extra"):    # núcleos anteriores a los extras no tienen este gancho
        api.extra("spark", "Perfilador de rendimiento (spark)",
                  "Mide los TPS y qué mod gasta más tiempo por tick, con el comando /spark. Es un mod aparte (GPL).",
                  spark.install, loaders=spark.LOADERS)

    # --- sincronización de clientes (AutoModpack) ---
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

    # --- propuestas de mods ---
    @api.route("GET", "proposal_search")
    @_guard(perm="*")
    def r_proposal_search(ctx, user, name, q, b):
        text = (q.get("q") or "").strip()[:80]
        source = q.get("source", "modrinth")
        if source not in proposals.SOURCES:
            raise ValueError("proveedor no válido")
        loader, _kind = ctx.compat_for(name, "mod")
        mc = ctx.server_versions(name).get("minecraft") or "1.21.1"
        try:
            raw = ctx.search(source, text, loader, mc, "mod", "auto", "server")
        except (OSError, RuntimeError) as e:
            return 502, {"error": f"no se pudo buscar en {source}: {e}"}
        return 200, {"results": proposals.search_results(raw)}

    @api.route("GET", "proposals")
    @_guard(perm="*")
    def r_proposals(ctx, user, name, q, b):
        return 200, {"proposals": proposals.list_for(ctx, name), "can_decide": bool(user.get("is_admin")), "me": user["id"]}

    @api.route("POST", "proposal_create")
    @_guard(perm="*")
    def r_proposal_create(ctx, user, name, q, b):
        pid = proposals.create(ctx, name, user, str(b.get("source")), str(b.get("project_id") or ""), str(b.get("title") or ""),
                               slug=str(b.get("slug") or ""), icon=str(b.get("icon") or ""), note=str(b.get("note") or ""))
        ctx.audit(user, name, "propuesta de mod", f"{b.get('title')}")
        notify.send(ctx, name, "proposals", f"{user['username']} propuso «{str(b.get('title'))[:80]}» en «{name}».")
        return 200, {"id": pid}

    @api.route("POST", "proposal_decide")
    @_guard
    def r_proposal_decide(ctx, user, name, q, b):
        status = proposals.decide(ctx, name, user, b.get("id"), str(b.get("decision")), str(b.get("reason") or ""))
        ctx.audit(user, name, "propuesta de mod " + ("aprobada" if status == "approved" else "rechazada"), str(b.get("id")))
        notify.send(ctx, name, "proposals", f"Propuesta en «{name}» {'aprobada' if status == 'approved' else 'rechazada'} por {user['username']}.")
        return 200, {"status": status}

    @api.route("POST", "proposal_withdraw")
    @_guard(perm="*")
    def r_proposal_withdraw(ctx, user, name, q, b):
        proposals.withdraw(ctx, name, user, b.get("id"))
        return 200, {"ok": True}

    # --- estadísticas de jugadores ---
    @api.route("GET", "player_stats")
    @_guard(perm="players")
    def r_player_stats(ctx, user, name, q, b):
        running = bool(ctx.status(name)["running"])
        return 200, {**stats.server_stats(Path(ctx.server_path(name)) / "logs", running=running), "running": running}

    # --- avisos ---
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

    # --- cuenta: verificación en dos pasos (cada usuario gestiona la suya) ---
    api.second_factor(security.login_hook)

    def _own(fn):
        def wrapped(ctx, user, q, body):
            try:
                if not user:
                    raise PermissionError("inicia sesión")
                return fn(ctx, user, q, body or {})
            except PermissionError as e:
                return 429 if "demasiados" in str(e) else 403, {"error": str(e)}
            except (ValueError, remote.RemoteError) as e:
                return 400, {"error": str(e)}
        return wrapped

    @api.global_route("GET", "2fa_status")
    @_own
    def g_2fa_status(ctx, user, q, b):
        return 200, security.status(ctx, user["id"])

    @api.global_route("POST", "2fa_begin")
    @_own
    def g_2fa_begin(ctx, user, q, b):
        return 200, security.begin(ctx, user)

    @api.global_route("POST", "2fa_confirm")
    @_own
    def g_2fa_confirm(ctx, user, q, b):
        codes = security.confirm(ctx, user, str(b.get("code") or ""))
        ctx.audit(user, None, "2FA activado", "")
        return 200, {"recovery": codes}

    @api.global_route("POST", "2fa_disable")
    @_own
    def g_2fa_disable(ctx, user, q, b):
        security.disable(ctx, user, str(b.get("code") or ""))
        ctx.audit(user, None, "2FA desactivado", "")
        return 200, {"ok": True}

    @api.global_route("POST", "2fa_reset")
    @_own
    def g_2fa_reset(ctx, user, q, b):
        _admin(user)
        target = ctx.db_run("SELECT id, username FROM users WHERE id = ?", (int(b.get("user_id") or 0),), one=True)
        if not target:
            raise ValueError("ese usuario no existe")
        security.remove(ctx, target["id"])
        ctx.audit(user, None, "2FA restablecido", target["username"])
        return 200, {"ok": True}

    # --- acceso remoto (solo administradores) ---
    @api.global_route("GET", "remote_status")
    @_own
    def g_remote_status(ctx, user, q, b):
        _admin(user)
        return 200, {**remote.status(ctx), "require_2fa": ctx.config().get("remote_2fa", ctx.config().get("pro_remote_2fa")) is not False}

    @api.global_route("POST", "remote_start")
    @_own
    def g_remote_start(ctx, user, q, b):
        _admin(user)
        provider = str(b.get("provider") or "cloudflared")
        st = remote.start(ctx, provider)
        ctx.audit(user, None, "acceso remoto abierto", provider)
        return 200, st

    @api.global_route("POST", "remote_stop")
    @_own
    def g_remote_stop(ctx, user, q, b):
        _admin(user)
        remote.stop()
        ctx.audit(user, None, "acceso remoto cerrado", "")
        return 200, remote.status(ctx)

    # --- eventos del núcleo -> avisos ---
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
