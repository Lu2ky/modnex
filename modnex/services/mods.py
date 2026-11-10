"""Mods instalados de un servidor: listar, activar o desactivar, borrar e índice de lo ya instalado."""

import time

from modnex.services.addons import INSTALLED_CACHE, INSTALLED_TTL, _mod_path, addons_dir
from modnex.config import JAR_RE
from modnex.services.identify import identify_mods


def list_mods(name):
    d = addons_dir(name)
    if not d.is_dir():
        return []
    return sorted(
        [{"file": f.name, "enabled": f.suffix == ".jar", "size": f.stat().st_size}
         for f in d.iterdir() if JAR_RE.fullmatch(f.name)],
        key=lambda x: x["file"].lower(),
    )


def installed_index(name, loader="neoforge", version="1.21.1"):
    """Qué proyectos hay instalados, para marcar «Instalado» al descubrir mods.
    `projects` mezcla `proveedor:id` y `slug:nombre` (el slug une Modrinth y CurseForge); `versions` da la versión
    instalada de cada proyecto. Se cachea 60 s porque identificar los mods consulta a los proveedores."""
    hit = INSTALLED_CACHE.get(name)
    if hit and time.time() - hit[0] < INSTALLED_TTL:
        return hit[1]
    projects, versions = [], {}
    for r in identify_mods(name, loader, version):
        if not r["enabled"]:
            continue
        if r["project_id"]:
            projects.append(f"{r['source']}:{r['project_id']}")
            if r["installed"]:
                versions[f"{r['source']}:{r['project_id']}"] = r["installed"]
        if r["slug"]:
            projects.append(f"slug:{r['slug'].lower()}")
    idx = {"projects": sorted(set(projects)), "versions": versions}
    INSTALLED_CACHE[name] = (time.time(), idx)
    return idx


def toggle_mod(name, file):
    p = _mod_path(name, file)
    if p.name.endswith(".disabled"):
        new = p.with_name(p.name[: -len(".disabled")])
    else:
        new = p.with_name(p.name + ".disabled")
    p.rename(new)
    return new.name


def delete_mod(name, file):
    _mod_path(name, file).unlink()
