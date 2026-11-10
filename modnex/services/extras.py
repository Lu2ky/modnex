"""Extras opcionales al crear un servidor: mods o plugins aparte que se instalan al terminar la creación.

El núcleo registra AutoModpack y los plugins pueden añadir otros con `api.extra(...)` (spark, por ejemplo);
los que no estén registrados no existen ni se aceptan. Un extra que no se puede instalar (cargador
no compatible, sin versión estable, sin red) no hace fallar la creación: queda anotado en la auditoría.
"""
import json
import re
import urllib.parse
from pathlib import Path

from modnex.infra.net import http_json
from modnex.services import templates

CDN = "cdn.modrinth.com"
API = "https://api.modrinth.com/v2/project"
JAR_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+\-]{0,118}\.jar")
SAFE_TOKEN = re.compile(r"[A-Za-z0-9._\-]{1,40}")

EXTRAS = {}   # id -> {"id","label","desc","loaders","install"}


class ExtraUnavailable(Exception):
    """El extra no se puede instalar en este servidor (el motivo se muestra al usuario)."""


def register(extra_id, label, desc, install, loaders=None):
    """install(ctx, nombre_del_servidor) -> nombre del archivo instalado, o None si ya estaba.
    loaders: cargadores donde tiene sentido (None = cualquiera)."""
    EXTRAS[extra_id] = {"id": extra_id, "label": label, "desc": desc, "loaders": sorted(loaders) if loaders else None,
                        "install": install}


def listing():
    return [{k: v for k, v in e.items() if k != "install"} for e in EXTRAS.values()]


def validate(ids, loader=None):
    """Lista de ids pedidos por el usuario, sin repetidos. Rechaza los desconocidos y los que no valen para `loader`
    (si se da; con None no se comprueba, p. ej. un modpack, cuyo cargador se sabe al instalarlo)."""
    if ids in (None, ""):
        return []
    if not isinstance(ids, list) or len(ids) > 20:
        raise ValueError("extras no válidos")
    out = []
    for x in ids:
        e = EXTRAS.get(x) if isinstance(x, str) else None
        if not e:
            raise ValueError(f"extra desconocido: {str(x)[:40]}")
        if loader is not None and e["loaders"] and loader not in e["loaders"]:
            raise ValueError(f"«{e['label']}» no está disponible para {loader}")
        if x not in out:
            out.append(x)
    return out


def run(ctx, name, ids, user=None):
    """Instala los extras pedidos en un servidor ya creado. Devuelve [{"id","ok","file"|"reason"}]."""
    results = []
    for x in ids:
        e = EXTRAS.get(x)
        if not e:
            continue
        try:
            f = e["install"](ctx, name)
            results.append({"id": x, "ok": True, "file": f})
            ctx.audit(user or {"username": "Modnex"}, name, f"extra instalado: {e['label']}", f or "ya estaba")
        except ExtraUnavailable as ex:
            results.append({"id": x, "ok": False, "reason": str(ex)})
            ctx.audit(user or {"username": "Modnex"}, name, f"extra no instalado: {e['label']}", str(ex))
        except Exception as ex:  # una descarga caída no debe tumbar la creación
            results.append({"id": x, "ok": False, "reason": f"{type(ex).__name__}: {ex}"})
            ctx.audit(user or {"username": "Modnex"}, name, f"extra no instalado: {e['label']}", f"{type(ex).__name__}: {ex}")
    return results


def server_meta(ctx, name):
    try:
        m = json.loads((Path(ctx.server_path(name)) / ".manager.json").read_text())
    except (OSError, ValueError):
        m = {}
    return m


def install_modrinth(ctx, name, slug, loaders=None, prefix=None, fetch=None):
    """Instala la última versión estable de un proyecto de Modrinth para el cargador y la versión de Minecraft del
    servidor, en su carpeta de mods o plugins. Devuelve el nombre del archivo, o None si ya estaba."""
    m = server_meta(ctx, name)
    template = m.get("template") or ""
    loader = str(m.get("loader") or templates.loader_of(template) or "")
    mc = str(m.get("mc") or "")
    if loaders and loader not in loaders:
        raise ExtraUnavailable(f"no está disponible para {loader or 'este tipo de servidor'}")
    if not (SAFE_TOKEN.fullmatch(loader) and SAFE_TOKEN.fullmatch(mc)):
        raise ExtraUnavailable("no se pudo determinar el cargador y la versión de Minecraft del servidor")
    dest = Path(ctx.server_path(name)) / templates.folder_for(template)
    dest.mkdir(exist_ok=True)
    pre = (prefix or slug).lower()
    if any(p.name.lower().startswith(pre) for p in dest.glob("*.jar")):
        return None
    q = urllib.parse.urlencode({"loaders": json.dumps([loader]), "game_versions": json.dumps([mc])})
    if fetch:
        rows = fetch(q)
    else:
        rows = http_json(f"{API}/{urllib.parse.quote(slug)}/version?{q}")
    stable = [x for x in rows if x.get("version_type") == "release"]
    if not stable:
        raise ExtraUnavailable(f"no hay versión estable para {loader} {mc}")
    best = max(stable, key=lambda x: x.get("date_published", ""))
    f = next((x for x in best["files"] if x.get("primary")), best["files"][0])
    u = urllib.parse.urlparse(f["url"])
    if u.scheme != "https" or u.hostname != CDN or not JAR_NAME.fullmatch(f["filename"]):
        raise ExtraUnavailable("Modrinth devolvió una descarga no válida")
    tmp = dest / (f["filename"] + ".part")
    ctx.download(f["url"], tmp, (f.get("hashes") or {}).get("sha1"))
    tmp.replace(dest / f["filename"])
    return f["filename"]


def _automodpack(ctx, name):
    return install_modrinth(ctx, name, "automodpack", loaders={"fabric", "neoforge", "forge"}, prefix="automodpack")


register("automodpack", "Sincronizar los mods con los clientes (AutoModpack)",
         "Los jugadores reciben los mods del servidor al entrar, sin instalar nada a mano. Es un mod aparte (LGPL) "
         "y el cliente que generas lo incluye siempre.", _automodpack, loaders={"fabric", "neoforge", "forge"})
