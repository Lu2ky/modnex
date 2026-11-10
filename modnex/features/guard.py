"""Decorador común de las rutas por servidor: permisos y traducción de los errores esperados a respuestas HTTP."""
from . import backups, proposals, remote, retention, safeupdate, staging, sync


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


def _own(fn):
    """Rutas globales de la cuenta propia: exige sesión; cada usuario solo toca lo suyo."""
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
