"""Carpeta de mods o plugins de un servidor: rutas, nombres seguros e instalación de un archivo descargado."""

import os
import re
import urllib.request
import zipfile

from modnex.services import release
from modnex.services import templates
from modnex.config import ALLOWED_DL_HOSTS, JAR_RE
from modnex.services.datapacks import datapacks_dir
from modnex.infra.net import _download
from modnex.services.servers import server_path


def server_template_of(name):
    return templates.server_template(server_path(name))


def server_loader(name):
    return templates.loader_of(server_template_of(name))


def addons_dir(name):
    return server_path(name) / templates.folder_for(server_template_of(name))


def _mod_path(name, file):
    if not JAR_RE.fullmatch(file or "") or os.path.basename(file) != file:
        raise ValueError("nombre de mod no válido")
    d = addons_dir(name)
    p = (d / file).resolve()
    if p.parent != d.resolve() or not p.exists():
        raise FileNotFoundError("mod no encontrado")
    return p


INSTALLED_CACHE = {}   # servidor -> (momento, índice); caduca a los 60 s o al cambiar los mods


INSTALLED_TTL = 60


def _invalidate_installed(name):
    INSTALLED_CACHE.pop(name, None)


MAX_MOD_UPLOAD = 256 * 1024 * 1024

# Archivo que identifica un mod o plugin dentro del .jar, y a qué cargador pertenece cada uno
DESCRIPTORS = {
    "META-INF/neoforge.mods.toml": "NeoForge", "META-INF/mods.toml": "Forge", "mcmod.info": "Forge",
    "fabric.mod.json": "Fabric", "quilt.mod.json": "Quilt", "plugin.yml": "Paper", "paper-plugin.yml": "Paper",
}
ACCEPTS = {   # qué descriptores sirven en cada tipo de servidor
    "neoforge": {"NeoForge", "Forge"}, "forge": {"Forge"}, "fabric": {"Fabric"}, "quilt": {"Quilt", "Fabric"}, "paper": {"Paper"},
}


def finish_mod_upload(name, tmp, fname):
    """Valida un .jar subido por el administrador y lo deja en la carpeta de mods o plugins del servidor.

    Comprueba que sea un zip con el descriptor de un mod del cargador del servidor (un mod de Fabric no arranca en
    NeoForge), que no pise otro archivo y que el servidor admita mods. Si algo falla, borra el archivo temporal."""
    try:
        template = server_template_of(name)
        if templates.kind_of(template) == "none":
            raise ValueError("este servidor es Vanilla: no admite mods ni plugins")
        if not zipfile.is_zipfile(tmp):
            raise ValueError("el archivo no es un .jar válido (no es un zip)")
        with zipfile.ZipFile(tmp) as z:
            found = {DESCRIPTORS[n] for n in z.namelist() if n in DESCRIPTORS}
        if not found:
            raise ValueError("no parece un mod ni un plugin: falta su descriptor (neoforge.mods.toml, fabric.mod.json, plugin.yml…)")
        loader = templates.loader_of(template)
        if loader in ACCEPTS and not found & ACCEPTS[loader]:
            raise ValueError(f"es un mod de {' / '.join(sorted(found))} y este servidor es {templates.TEMPLATES[template]['label']}")
        dest = addons_dir(name)
        dest.mkdir(exist_ok=True)
        if (dest / fname).exists() or (dest / (fname + ".disabled")).exists():
            raise ValueError(f"ya hay un archivo llamado {fname}: bórralo o cambia el nombre antes de subir otro")
        tmp.replace(dest / fname)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    _invalidate_installed(name)
    return fname


def safe_jar_name(filename):
    fname = os.path.basename(filename or "")
    if not re.fullmatch(r"[A-Za-z0-9._+\-\[\]() ]+\.jar", fname):
        raise ValueError("nombre de archivo no válido")
    return fname


def install(server_name, url, filename, sha1, kind="mod"):
    u = urllib.parse.urlparse(url or "")
    if u.scheme != "https" or u.hostname not in ALLOWED_DL_HOSTS:
        raise ValueError("host de descarga no permitido")
    if kind in ("mod", "plugin"):
        fname = safe_jar_name(filename)
        if templates.kind_of(server_template_of(server_name)) == "none":
            raise ValueError("este servidor es Vanilla: no admite mods ni plugins")
        dest_dir = addons_dir(server_name)
        if not dest_dir.is_dir():
            raise FileNotFoundError("el servidor no tiene carpeta de mods o plugins")
    elif kind == "datapack":
        fname = release.safe_zip_name(filename)
        dest_dir = datapacks_dir(server_name, create=True)
    else:
        raise ValueError("tipo no instalable")
    tmp = dest_dir / (fname + ".part")
    _download(url, tmp, sha1)
    if kind == "datapack":
        if not zipfile.is_zipfile(tmp) or "pack.mcmeta" not in zipfile.ZipFile(tmp).namelist():
            tmp.unlink(missing_ok=True)
            raise ValueError("el archivo descargado no es un datapack válido (falta pack.mcmeta)")
    tmp.replace(dest_dir / fname)
    _invalidate_installed(server_name)
    return fname
