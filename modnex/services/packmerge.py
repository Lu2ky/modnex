"""Fusión de varios packs de texturas en uno solo.

Reglas:
- El orden importa: los packs se pasan del más antiguo al más nuevo y el más nuevo gana en cada archivo.
- Los `.json` de idioma (assets/<ns>/lang/*.json) se fusionan clave a clave, para no perder traducciones de otros packs.
- `pack.mcmeta` y `pack.png` salen del pack más nuevo; la descripción dice cuántos packs se fusionaron.
- Las rutas peligrosas (absolutas, con `..` o con barras invertidas) se descartan.
"""

import json
import re
import zipfile
from pathlib import Path

LANG_RE = re.compile(r"^assets/[^/]+/lang/[^/]+\.json$")
MAX_REPORTED = 50


def _safe_name(name):
    if name.startswith("/") or "\\" in name or ".." in name.split("/") or not name:
        return None
    return name


def merge_packs(sources, out, pack_format=None):
    """Une `sources` (lista de rutas a zips, del más antiguo al más nuevo) en el zip `out`.

    Devuelve un informe: cuántos packs, archivos, sobrescritos y claves de idioma fusionadas.
    `pack_format`: el formato que pide la versión de Minecraft del servidor. Sin él se usa el del pack más nuevo; el panel siempre
    lo pasa, porque un formato más nuevo que el del juego sale como «incompatible» aunque los archivos estén bien.
    """
    files = {}          # nombre -> (bytes, origen)
    lang = {}           # nombre -> dict de claves
    overridden = []
    overrides_total = 0
    mcmeta = None
    png = None
    formats = set()
    usable = 0
    for src in sources:
        with zipfile.ZipFile(src) as z:
            usable += 1
            for info in z.infolist():
                if info.is_dir():
                    continue
                name = _safe_name(info.filename)
                if name is None:
                    continue
                data = z.read(info)
                if name == "pack.mcmeta":
                    mcmeta = data
                    try:
                        formats.add(json.loads(data)["pack"]["pack_format"])
                    except (ValueError, KeyError, TypeError):
                        pass
                    continue
                if name == "pack.png":
                    png = data
                    continue
                if LANG_RE.match(name):
                    try:
                        entries = json.loads(data.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if isinstance(entries, dict):
                        lang.setdefault(name, {}).update(entries)
                    continue
                if name in files:
                    overrides_total += 1
                    if len(overridden) < MAX_REPORTED:
                        overridden.append(name)
                files[name] = (data, src)
    if usable == 0:
        raise ValueError("no hay packs que fusionar")
    meta = {"pack": {"pack_format": 34, "description": ""}}
    if mcmeta:
        try:
            meta = json.loads(mcmeta)
        except ValueError:
            pass
    fmt_list = sorted(formats)
    meta.setdefault("pack", {})
    if pack_format is not None:
        meta["pack"]["pack_format"] = int(pack_format)
    meta["pack"]["description"] = f"Pack unificado ({usable} packs)"
    tmp = Path(str(out) + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("pack.mcmeta", json.dumps(meta, ensure_ascii=False, indent=2))
        if png:
            z.writestr("pack.png", png)
        for name in sorted(files):
            z.writestr(name, files[name][0])
        for name in sorted(lang):
            z.writestr(name, json.dumps(lang[name], ensure_ascii=False, indent=2))
    tmp.replace(out)
    return {"packs": usable, "files": len(files) + len(lang), "overridden": overridden,
            "overrides_total": overrides_total, "lang_files": len(lang),
            "pack_formats": fmt_list, "mixed_formats": len(fmt_list) > 1}
