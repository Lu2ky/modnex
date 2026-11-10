"""Un único sitio que decide qué código HTTP corresponde a cada excepción.

Los servicios lanzan excepciones normales (PermissionError, ValueError, FileNotFoundError, RuntimeError...) y nunca
eligen un código HTTP. Quien necesite uno distinto puede ponerlo en un atributo `http_status` de su excepción.
"""
import urllib.error


def to_response(exc):
    """Devuelve (código, cuerpo) para una excepción. El cuerpo siempre tiene la forma {"error": "..."}."""
    status = getattr(exc, "http_status", None)
    if status:
        return status, {"error": str(exc)}
    if isinstance(exc, PermissionError):
        return 403, {"error": str(exc)}
    if isinstance(exc, (ValueError, KeyError)):
        return 400, {"error": str(exc)}
    if isinstance(exc, (FileNotFoundError, LookupError)):
        return 404, {"error": str(exc)}
    if isinstance(exc, RuntimeError):
        return 409, {"error": str(exc)}
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 404:
            return 404, {"error": "no existe en el proveedor"}
        return 502, {"error": f"el proveedor respondió {exc.code}"}
    return 500, {"error": f"{type(exc).__name__}: {exc}"}
