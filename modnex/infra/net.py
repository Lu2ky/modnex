"""Cliente HTTP y descargas hacia los proveedores (Modrinth, CurseForge): JSON, POST y descarga con SHA-1."""

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request

from modnex.config import MAX_MOD_BYTES, UA
from modnex.infra.breaker import ProviderUnavailable, breaker_for


def guarded(url, call):
    """Ejecuta `call()` protegido por el circuit breaker del host de `url`. Cuentan como fallo los errores de red, los
    tiempos agotados y las respuestas 5xx o 429; un 404 u otro 4xx es una respuesta válida y no abre el breaker."""
    host = urllib.parse.urlparse(url).hostname or url
    b = breaker_for(host)
    if not b.allow():
        raise ProviderUnavailable(f"{host} no responde ahora mismo; se reintentará en unos segundos")
    try:
        out = call()
    except urllib.error.HTTPError as e:
        b.failure() if (e.code >= 500 or e.code == 429) else b.success()
        raise
    except OSError:          # URLError, tiempo agotado, conexión rechazada...
        b.failure()
        raise
    b.success()
    return out


def http_json(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})

    def call():
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read()
    return json.loads(guarded(url, call))


def _download(url, tmp, sha1, limit=MAX_MOD_BYTES):
    """Descarga a un archivo temporal con límite de tamaño y verificación SHA-1; limpia si algo falla."""
    h = hashlib.sha1()
    req = urllib.request.Request(url, headers={"User-Agent": UA})

    def fetch():
        with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as fh:
            if int(r.headers.get("Content-Length") or 0) > limit:
                raise ValueError(f"el archivo supera el límite de {limit // (1 << 20)} MB")
            total = 0
            while chunk := r.read(65536):
                total += len(chunk)
                if total > limit:
                    raise ValueError(f"el archivo supera el límite de {limit // (1 << 20)} MB")
                fh.write(chunk)
                h.update(chunk)
    try:
        guarded(url, fetch)
        if sha1 and h.hexdigest() != sha1:
            raise ValueError("el SHA-1 no coincide; descarga cancelada")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return h.hexdigest()


def mr_get(path):
    return http_json("https://api.modrinth.com/v2" + path)


def http_post_json(url, body, headers=None):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "User-Agent": UA, "Content-Type": "application/json", **(headers or {})})

    def call():
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    return json.loads(guarded(url, call))
