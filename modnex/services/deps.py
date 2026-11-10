"""Dependencias de los mods: resolverlas e instalar varios mods de una vez."""

import json
import urllib.request

from modnex.services.addons import install
from modnex.config import CF_LOADER_TYPE, load_cf_key
from modnex.services.identify import identify_mods
from modnex.infra.net import http_json, mr_get


MAX_DEPS = 30


def _installed_keys(server, loader, version):
    """Proyectos ya instalados, por id de proveedor y por slug (el slug une Modrinth y CurseForge)."""
    keys = set()
    for r in identify_mods(server, loader, version):
        if not r["enabled"]:
            continue
        if r["project_id"]:
            keys.add((r["source"], str(r["project_id"])))
        if r["slug"]:
            keys.add(("slug", r["slug"].lower()))
    return keys


def _resolve_mr(version_obj, installed, loader, version, via, out, warnings, seen):
    for d in version_obj.get("dependencies", []):
        pid = d.get("project_id") or (mr_get(f"/version/{d['version_id']}")["project_id"] if d.get("version_id") else None)
        if not pid:
            continue
        kind = d.get("dependency_type")
        if kind == "incompatible":
            if ("modrinth", pid) in installed:
                try:
                    shown = mr_get(f"/project/{pid}")["title"]
                except urllib.error.URLError:
                    shown = pid
                warnings.append(f"Es incompatible con «{shown}», que ya tienes instalado.")
            continue
        if kind != "required" or ("modrinth", pid) in installed or pid in seen:
            continue
        seen.add(pid)
        if len(out) >= MAX_DEPS:
            warnings.append("Hay demasiadas dependencias; solo se muestran las primeras.")
            return
        try:
            proj = mr_get(f"/project/{pid}")
            if ("slug", proj["slug"].lower()) in installed:
                continue
            if d.get("version_id"):
                v = mr_get(f"/version/{d['version_id']}")
            else:
                vs = mr_get(f"/project/{pid}/version?" + urllib.parse.urlencode(
                    {"loaders": json.dumps([loader]), "game_versions": json.dumps([version])}))
                v = vs[0] if vs else None
        except urllib.error.URLError:  # una dependencia que no se puede consultar no debe abortar el resto
            out.append({"source": "modrinth", "project_id": pid, "name": pid, "slug": pid, "via": via, "page": None,
                        "status": "unavailable", "note": "No se pudo consultar esta dependencia en Modrinth."})
            continue
        item = {"source": "modrinth", "project_id": pid, "name": proj["title"], "slug": proj["slug"], "via": via, "page": None}
        if not v or not v.get("files"):
            out.append({**item, "status": "unavailable", "note": f"No hay una versión para Minecraft {version} y {loader}."})
            continue
        f = next((x for x in v["files"] if x.get("primary")), v["files"][0])
        out.append({**item, "status": "ok", "filename": f["filename"], "url": f["url"],
                    "sha1": f["hashes"].get("sha1"), "version": v["version_number"]})
        _resolve_mr(v, installed, loader, version, proj["title"], out, warnings, seen)


def _resolve_cf(file_obj, installed, loader, version, via, out, warnings, seen):
    key = load_cf_key()
    hdr = {"x-api-key": key}
    for d in file_obj.get("dependencies", []):
        mid, kind = str(d["modId"]), d.get("relationType")
        if kind == 5:  # incompatible
            if ("curseforge", mid) in installed:
                try:
                    name = http_json(f"https://api.curseforge.com/v1/mods/{int(mid)}", headers=hdr)["data"]["name"]
                except urllib.error.URLError:
                    name = mid
                warnings.append(f"Es incompatible con «{name}», que ya tienes instalado.")
            continue
        if kind != 3 or ("curseforge", mid) in installed or mid in seen:  # 3 = obligatoria
            continue
        seen.add(mid)
        if len(out) >= MAX_DEPS:
            warnings.append("Hay demasiadas dependencias; solo se muestran las primeras.")
            return
        try:
            mod = http_json(f"https://api.curseforge.com/v1/mods/{int(mid)}", headers=hdr)["data"]
            if ("slug", mod["slug"].lower()) in installed:
                continue
            files = http_json(f"https://api.curseforge.com/v1/mods/{int(mid)}/files?" + urllib.parse.urlencode(
                {"gameVersion": version, "modLoaderType": CF_LOADER_TYPE[loader], "pageSize": 5}), headers=hdr)["data"]
        except urllib.error.URLError:
            out.append({"source": "curseforge", "project_id": mid, "name": mid, "slug": mid, "via": via, "page": None,
                        "status": "unavailable", "note": "No se pudo consultar esta dependencia en CurseForge."})
            continue
        page = f"https://www.curseforge.com/minecraft/mc-mods/{mod['slug']}"
        item = {"source": "curseforge", "project_id": mid, "name": mod["name"], "slug": mod["slug"], "via": via, "page": page}
        f = next((x for x in files if x.get("downloadUrl")), None)
        if not files:
            out.append({**item, "status": "unavailable", "note": f"No hay un archivo para Minecraft {version} y {loader}."})
            continue
        if not f:
            out.append({**item, "status": "unavailable", "note": "El autor no permite descargarlo desde aquí; descárgalo a mano."})
            continue
        sha1 = next((h["value"] for h in f.get("hashes", []) if h["algo"] == 1), None)
        out.append({**item, "status": "ok", "filename": f["fileName"], "url": f["downloadUrl"], "sha1": sha1, "version": f["displayName"]})
        _resolve_cf(f, installed, loader, version, mod["name"], out, warnings, seen)


def resolve_deps(server, source, project, vid, loader, version):
    """Dependencias obligatorias (y las de ellas, en cascada) de una versión de mod que aún no están instaladas."""
    installed = _installed_keys(server, loader, version)
    out, warnings = [], []
    if source == "modrinth":
        v = mr_get(f"/version/{urllib.parse.quote(str(vid), safe='')}")
        _resolve_mr(v, installed, loader, version, "", out, warnings, {v["project_id"]})
    elif source == "curseforge":
        if not load_cf_key():
            raise RuntimeError("falta la API key de CurseForge")
        f = http_json(f"https://api.curseforge.com/v1/mods/{int(project)}/files/{int(vid)}",
                      headers={"x-api-key": load_cf_key()})["data"]
        _resolve_cf(f, installed, loader, version, "", out, warnings, {str(int(project))})
    else:
        raise ValueError("fuente no válida")
    return {"deps": out, "warnings": warnings}


def install_many(server_name, items):
    if not isinstance(items, list) or not items or len(items) > MAX_DEPS + 1:
        raise ValueError("lista de mods no válida")
    results = []
    for it in items:
        if not isinstance(it, dict):
            results.append({"file": "?", "ok": False, "error": "entrada no válida"})
            continue
        try:
            results.append({"file": install(server_name, it["url"], it["filename"], it.get("sha1"), "mod"), "ok": True})
        except KeyError as e:
            results.append({"file": str(it.get("filename")) if isinstance(it, dict) else "?", "ok": False, "error": f"falta el campo {e}"})
        except (ValueError, OSError, urllib.error.URLError) as e:
            results.append({"file": str(it.get("filename")) if isinstance(it, dict) else "?", "ok": False, "error": str(e)})
    return results
