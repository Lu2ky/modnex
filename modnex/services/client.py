"""Cliente compatible con el servidor: plan de mods, presets y generación del modpack (.mrpack o .zip)."""

import hashlib
import html
import json
import re
import threading
import time
import urllib.request
import zipfile

from modnex import plugins
from modnex.infra import db
from modnex.services import release
from modnex.services.addons import addons_dir
from modnex.config import JAR_RE, load_cf_key
from modnex.services.identify import _cf_fp, identify_mods
from modnex.infra.net import _download, http_post_json, mr_get
from modnex.services.servers import server_path


SECRET_RE = re.compile(r"secret|token|password|credential|api[-_]?key", re.I)


PACK_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ \-]{0,47}")


PACK_VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+\-]{0,31}")


def server_versions(name):
    """Versión de Minecraft y de NeoForge que ejecuta el servidor, leída de los argumentos de arranque."""
    p = server_path(name)
    mc = nf = None
    for f in sorted((p / "libraries" / "net" / "neoforged" / "neoforge").glob("*/unix_args.txt")):
        txt = f.read_text(errors="replace")
        m1 = re.search(r"--fml\.neoForgeVersion\s+(\S+)", txt)
        m2 = re.search(r"--fml\.mcVersion\s+(\S+)", txt)
        nf = m1.group(1) if m1 else nf
        mc = m2.group(1) if m2 else mc
    return {"minecraft": mc, "loader": "neoforge" if nf else None, "loader_version": nf}


def _mod_decision(r):
    """Decide si un mod del servidor debe ir en el cliente y explica por qué."""
    if r["source"] == "modrinth":
        if r.get("client_side") == "unsupported":
            return False, "Solo funciona en el servidor"
        return True, "Necesario en el cliente" if r.get("client_side") == "required" else "Opcional en el cliente"
    if r["source"] == "curseforge":
        tags = set(r.get("cf_tags") or [])
        if "Server" in tags and "Client" not in tags:
            return False, "Etiquetado solo para servidor en CurseForge"
        return True, "Reconocido en CurseForge (sin dato fiable de lado)"
    return True, "No reconocido: se incluye por seguridad, revísalo"


CLIENT_PRESETS = {
    "rendimiento": {
        "label": "Rendimiento",
        "desc": "Renderizado, CPU y memoria del cliente: Sodium, Iris para shaders, culling de entidades y ajustes de FPS.",
        "slugs": ["sodium", "sodium-extra", "iris", "entityculling", "immediatelyfast", "dynamic-fps",
                  "ferrite-core", "modernfix", "lithium"],
    },
}


CLIENT_PRESETS["ayudas"] = {
    "label": "Ayudas de juego",
    "desc": "JEI (recetas y usos de cada objeto) y Jade (información de lo que miras), con sus dependencias.",
    "slugs": ["jei", "jade"],
}


_PRESET_CACHE = {}


_PRESET_LOCK = threading.Lock()


PRESET_DEP_DEPTH = 3


def _preset_version(slug, ver):
    """Proyecto y versión de Modrinth para la versión de Minecraft y NeoForge del servidor (None si no hay)."""
    proj = mr_get(f"/project/{slug}")
    vs = mr_get(f"/project/{slug}/version?" + urllib.parse.urlencode({
        "loaders": json.dumps(["neoforge"]), "game_versions": json.dumps([ver["minecraft"]])}))
    return proj, (vs[0] if vs else None)


def _item_from(proj, v, slug, note=None):
    f = next((x for x in v["files"] if x.get("primary")), v["files"][0])
    if not JAR_RE.fullmatch(f["filename"]):
        return {"slug": slug, "name": proj["title"], "status": "unavailable", "note": "Nombre de archivo no válido."}
    return {"slug": slug, "name": proj["title"], "status": "ok", "version": v["version_number"],
            "filename": f["filename"], "url": f["url"], "sha1": f["hashes"].get("sha1"),
            "sha512": f["hashes"].get("sha512"), "client": proj.get("client_side"),
            "server": proj.get("server_side"), **({"note": note} if note else {})}


def _preset_slug_items(slug, ver, seen, depth=0, note=None):
    """Un mod del preset más sus dependencias obligatorias (Modrinth), en orden y sin repetir."""
    seen.add(slug)
    try:
        proj, v = _preset_version(slug, ver)
    except (urllib.error.URLError, KeyError, ValueError):
        return [{"slug": slug, "name": slug, "status": "unavailable", "note": "No se pudo consultar en Modrinth."}]
    if v is None:
        return [{"slug": slug, "name": slug, "status": "unavailable",
                 "note": f"No hay versión para Minecraft {ver['minecraft']} y NeoForge."}]
    out = [_item_from(proj, v, slug, note)]
    if depth >= PRESET_DEP_DEPTH:
        return out
    for d in v.get("dependencies", []):
        if d.get("dependency_type") != "required":
            continue
        try:
            pid = d.get("project_id") or mr_get(f"/version/{d['version_id']}")["project_id"]
            dep_slug = mr_get(f"/project/{pid}")["slug"]
        except (urllib.error.URLError, KeyError, ValueError):
            continue
        if dep_slug in seen:
            continue
        out.extend(_preset_slug_items(dep_slug, ver, seen, depth + 1, note=f"dependencia de {proj['title']}"))
    return out


def preset_items(name, preset="all"):
    """Versiones de los presets para la versión de Minecraft y NeoForge del servidor. Cacheado 15 minutos.
    preset='all' combina todos los presets; cada mod de Modrinth aparece una sola vez."""
    keys = list(CLIENT_PRESETS) if preset == "all" else [preset]
    if any(k not in CLIENT_PRESETS for k in keys):
        raise ValueError("preset no válido")
    ver = server_versions(name)
    if not (ver["minecraft"] and ver["loader_version"]):
        return []
    key = (tuple(keys), ver["minecraft"])
    with _PRESET_LOCK:
        hit = _PRESET_CACHE.get(key)
        if hit and time.time() - hit[0] < 900:
            return hit[1]
    items, seen = [], set()
    for k in keys:
        for slug in CLIENT_PRESETS[k]["slugs"]:
            if slug in seen:
                continue
            items.extend(i for i in _preset_slug_items(slug, ver, seen) if i.get("slug") not in {x.get("slug") for x in items})
    with _PRESET_LOCK:
        _PRESET_CACHE[key] = (time.time(), items)
    return items


def _preset_for_build(name, server_slugs):
    """Los mods del preset que el servidor aún no tiene, listos para incluir."""
    return [i for i in preset_items(name) if i["status"] == "ok" and i["slug"] not in server_slugs]


def client_plan(name):
    ver = server_versions(name)
    rows = [r for r in identify_mods(name, ver["loader"] or "neoforge", ver["minecraft"] or "1.21.1") if r["enabled"]]
    mods = []
    forced = set(plugins.client_must_include(name, {r["file"]: r for r in rows}))
    for r in rows:
        include, reason = _mod_decision(r)
        if r["file"] in forced:
            include, reason = True, "Se incluye siempre: sincroniza el cliente con el servidor"
        mods.append({"file": r["file"], "name": r["name"], "source": r["source"], "installed": r["installed"],
                     "size": r["size"], "client_side": r["client_side"], "include": include, "reason": reason, "locked": r["file"] in forced})
    builds = db.builds_for(name)
    last = builds[0] if builds else None
    stale = None
    if last:
        now = {r["sha1"]: (r["name"] or r["file"]) for r in rows}
        before = {m["sha1"]: m["file"] for m in last["server_mods"]}
        added = sorted(n for h, n in now.items() if h not in before)
        removed = sorted(n for h, n in before.items() if h not in now)
        changed_ver = (last["minecraft"], last["loader_version"]) != (ver["minecraft"], ver["loader_version"])
        stale = {"stale": bool(added or removed or changed_ver), "added": added, "removed": removed, "versions_changed": changed_ver}
    if load_cf_key():
        _warm_cf_cache([addons_dir(name) / m["file"] for m in mods])
    server_slugs = {r["slug"] for r in rows if r.get("slug")}
    preset_list = [i for i in preset_items(name) if i["slug"] not in server_slugs]
    preset = {"label": "Rendimiento y ayudas de juego",
              "desc": CLIENT_PRESETS["rendimiento"]["desc"] + " " + CLIENT_PRESETS["ayudas"]["desc"],
              "items": [{k: i.get(k) for k in ("slug", "name", "status", "version", "client", "server", "note")} for i in preset_list],
              "available": sum(1 for i in preset_list if i["status"] == "ok")} if ver.get("loader") == "neoforge" else None
    return {**ver, "curseforge": bool(load_cf_key()), "mods": mods, "preset": preset, "last_build": ({k: last[k] for k in ("filename", "version", "fmt", "created_at")}
                                                | {"mods": len(last["included"])}) if last else None, "stale": stale}


_WARMING = set()


def _warm_cf_cache(paths):
    """Calcula en segundo plano los fingerprints de CurseForge para que generar el cliente sea instantáneo."""
    paths = [p for p in paths if str(p) not in _WARMING]
    _WARMING.update(str(p) for p in paths)

    def work():
        for p in paths:
            try:
                _cf_fp(p)
            except OSError:
                pass
    if paths:
        threading.Thread(target=work, daemon=True).start()


def _cf_refs(paths):
    """{archivo: (projectID, fileID)} para los jars que están idénticos en CurseForge y que CurseForge deja descargar."""
    key = load_cf_key()
    if not key or not paths:
        return {}
    fps = {fname: _cf_fp(p) for fname, p in paths.items()}
    res = http_post_json("https://api.curseforge.com/v1/fingerprints/432", {"fingerprints": sorted(set(fps.values()))},
                         headers={"x-api-key": key})
    by_fp = {m["file"]["fileFingerprint"]: m for m in res.get("data", {}).get("exactMatches", [])}
    return {fname: (m["id"], m["file"]["id"]) for fname, fp in fps.items()
            if (m := by_fp.get(fp)) and m["file"].get("downloadUrl") and m["file"].get("isAvailable", True)}


def _sha512(path):
    h = hashlib.sha512()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _config_files(name):
    root = (server_path(name) / "config").resolve()
    out = []
    if root.is_dir():
        for f in sorted(root.rglob("*")):
            if (f.is_file() and not f.is_symlink() and f.resolve().is_relative_to(root)
                    and f.stat().st_size <= 2 * 1024 * 1024 and not SECRET_RE.search(f.name)):
                out.append(f)
    return out[:500], root


def build_client(name, files, fmt, version, include_config, pack_name, author="Gestor", reference_cf=False, presets=False):
    if fmt not in ("mrpack", "zip"):
        raise ValueError("formato no válido")
    if not PACK_VERSION_RE.fullmatch(version or ""):
        raise ValueError("versión no válida (letras, números, . _ + -; máximo 32)")
    if not PACK_NAME_RE.fullmatch(pack_name or ""):
        raise ValueError("nombre del paquete no válido (letras, números, espacios, . _ -)")
    ver = server_versions(name)
    if not (ver["minecraft"] and ver["loader_version"]):
        raise RuntimeError("no pude detectar las versiones de Minecraft y NeoForge del servidor")
    rows = {r["file"]: r for r in identify_mods(name, ver["loader"] or "neoforge", ver["minecraft"] or "1.21.1") if r["enabled"]}
    if not isinstance(files, list) or not files:
        raise ValueError("selecciona al menos un mod para el cliente")
    files = list(dict.fromkeys(files + [f for f in plugins.client_must_include(name, rows) if f not in files]))
    unknown = [f for f in files if f not in rows]
    if unknown:
        raise ValueError(f"mods que no existen en el servidor: {', '.join(map(str, unknown[:3]))}")
    mods_dir = server_path(name) / "mods"
    slug = re.sub(r"[ ]+", "-", pack_name.strip())
    out_name = f"{slug}-{version}.{fmt}"
    dest_dir = release.release_dir(name)
    tmp = dest_dir / (out_name + ".part")
    cfg, cfg_root = _config_files(name) if include_config else ([], None)
    embedded = []
    extra = _preset_for_build(name, {r["slug"] for r in rows.values() if r.get("slug")}) if presets else []
    try:
        with zipfile.ZipFile(tmp, "w") as z:
            if fmt == "mrpack":
                entries = []
                for it in extra:  # el preset se descarga desde Modrinth; el paquete solo guarda la referencia
                    entries.append({"path": f"mods/{it['filename']}", "hashes": {"sha1": it["sha1"], "sha512": it["sha512"]},
                                    "env": {"client": it["client"] or "required", "server": it["server"] or "unsupported"},
                                    "downloads": [it["url"]], "fileSize": 0})
                for fname in files:
                    r, local = rows[fname], mods_dir / fname
                    if r["source"] == "modrinth" and r["download_url"]:
                        entries.append({"path": f"mods/{fname}", "hashes": {"sha1": r["sha1"], "sha512": _sha512(local)},
                                        "env": {"client": "required", "server": r["server_side"] or "required"},
                                        "downloads": [r["download_url"]], "fileSize": local.stat().st_size})
                    else:  # fuera de Modrinth no hay URL permitida por el formato: el jar va dentro del paquete
                        z.write(local, f"overrides/mods/{fname}", compress_type=zipfile.ZIP_STORED)
                        embedded.append(fname)
                index = {"formatVersion": 1, "game": "minecraft", "versionId": version, "name": pack_name,
                         "summary": f"Cliente compatible con el servidor {name}", "files": entries,
                         "dependencies": {"minecraft": ver["minecraft"], "neoforge": ver["loader_version"]}}
                z.writestr("modrinth.index.json", json.dumps(index, indent=2, ensure_ascii=False), compress_type=zipfile.ZIP_DEFLATED)
                for f in cfg:
                    z.write(f, f"overrides/config/{f.relative_to(cfg_root).as_posix()}", compress_type=zipfile.ZIP_DEFLATED)
            else:
                for it in extra:  # en el zip el jar va dentro: se descarga y se comprueba su SHA-1
                    part = dest_dir / (it["filename"] + ".part")
                    _download(it["url"], part, it["sha1"])
                    try:
                        z.write(part, f"overrides/mods/{it['filename']}", compress_type=zipfile.ZIP_STORED)
                    finally:
                        part.unlink(missing_ok=True)
                    embedded.append(it["filename"])
                # Modpack al estilo CurseForge: lo importan la app de CurseForge y Prism Launcher.
                # Con reference_cf, los mods idénticos a los de CurseForge se referencian por ID (zip pequeño);
                # el resto va dentro de overrides/mods, así que el paquete sigue siendo completo.
                refs = {}
                if reference_cf:
                    try:
                        refs = _cf_refs({f: mods_dir / f for f in files})
                    except Exception:  # noqa: BLE001 - sin CurseForge, todo va dentro del zip (sigue siendo válido)
                        refs = {}
                for fname in files:
                    if fname not in refs:
                        z.write(mods_dir / fname, f"overrides/mods/{fname}", compress_type=zipfile.ZIP_STORED)
                        embedded.append(fname)
                manifest = {"minecraft": {"version": ver["minecraft"],
                                          "modLoaders": [{"id": f"neoforge-{ver['loader_version']}", "primary": True}]},
                            "manifestType": "minecraftModpack", "manifestVersion": 1, "name": pack_name,
                            "version": version, "author": author, "overrides": "overrides",
                            "files": [{"projectID": p, "fileID": i, "required": True}
                                      for p, i in dict.fromkeys(refs[f] for f in files if f in refs)]}
                z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False), compress_type=zipfile.ZIP_DEFLATED)
                items = "".join(f"<li>{html.escape(rows[f]['name'] or f)}</li>" for f in files)
                z.writestr("modlist.html", f"<ul>{items}</ul>", compress_type=zipfile.ZIP_DEFLATED)
                for f in cfg:
                    z.write(f, f"overrides/config/{f.relative_to(cfg_root).as_posix()}", compress_type=zipfile.ZIP_DEFLATED)
        tmp.replace(dest_dir / out_name)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    db.add_build(name, out_name, version, fmt, ver["minecraft"], ver["loader_version"],
                 [{"file": f, "sha1": rows[f]["sha1"]} for f in files],
                 [{"file": r["file"], "sha1": r["sha1"]} for r in rows.values()])
    return {"file": out_name, "format": fmt, "mods": len(files), "embedded": embedded, "referenced": len(files) - len(embedded) if fmt == "zip" else 0,
            "config_files": len(cfg), "size": (dest_dir / out_name).stat().st_size}
