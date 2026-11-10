"""Identificación de los mods de un servidor por huella (Modrinth y CurseForge) y su actualización."""

import hashlib
import json
import threading
import urllib.request

from modnex.services.addons import _mod_path, addons_dir, install, server_loader
from modnex.config import JAR_RE, load_cf_key
from modnex.infra.net import http_json, http_post_json


HASH_CACHE = {}  # (ruta, tamaño, mtime) -> {"sha1": ..., "cf": ...}


def _murmur2(data, seed=1):
    """MurmurHash2 de 32 bits; es el hash 'fingerprint' que usa la API de CurseForge."""
    m, mask = 0x5BD1E995, 0xFFFFFFFF
    n = len(data)
    h = (seed ^ n) & mask
    i = 0
    while n - i >= 4:
        k = int.from_bytes(data[i:i + 4], "little")
        k = (k * m) & mask
        k ^= k >> 24
        k = (k * m) & mask
        h = (h * m) & mask
        h ^= k
        i += 4
    rem = n - i
    if rem >= 3:
        h ^= data[i + 2] << 16
    if rem >= 2:
        h ^= data[i + 1] << 8
    if rem >= 1:
        h ^= data[i]
        h = (h * m) & mask
    h ^= h >> 13
    h = (h * m) & mask
    h ^= h >> 15
    return h


def _hashes(p):
    """SHA-1 (Modrinth) y fingerprint (CurseForge), cacheados por ruta/tamaño/fecha."""
    st = p.stat()
    key = (str(p), st.st_size, st.st_mtime_ns)
    if key not in HASH_CACHE:
        h = hashlib.sha1()
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        HASH_CACHE[key] = {"sha1": h.hexdigest(), "cf": None}
    return HASH_CACHE[key]


_FP_LOCK = threading.Lock()  # evita calcular dos veces el mismo fingerprint (hilo de calentamiento + petición)


def _cf_fp(p):
    entry = _hashes(p)
    if entry["cf"] is None:
        with _FP_LOCK:
            if entry["cf"] is None:
                data = p.read_bytes().translate(None, b"\t\n\r ")
                entry["cf"] = _murmur2(data, 1)
    return entry["cf"]


def identify_mods(name, loader="neoforge", version="1.21.1"):
    loader = server_loader(name) or loader  # el servidor manda: un Paper nunca se consulta con loader de mods
    d = addons_dir(name)
    if not d.is_dir():
        return []
    files = [f for f in sorted(d.iterdir()) if JAR_RE.fullmatch(f.name)]
    sha = {f.name: _hashes(f)["sha1"] for f in files}

    # 1) Modrinth: identificar por SHA-1
    found = {}
    if sha:
        try:
            found = http_post_json("https://api.modrinth.com/v2/version_files",
                                   {"hashes": list(sha.values()), "algorithm": "sha1"})
        except Exception:  # noqa: BLE001 - si Modrinth falla, seguimos sin identificar
            found = {}
    projects = {}
    pids = list({v["project_id"] for v in found.values()})
    if pids:
        for p in http_json("https://api.modrinth.com/v2/projects?" + urllib.parse.urlencode(
                {"ids": json.dumps(pids)})):
            projects[p["id"]] = p

    # 2) Actualizaciones disponibles en Modrinth
    latest = {}
    if sha and found:
        try:
            latest = http_post_json("https://api.modrinth.com/v2/version_files/update", {
                "hashes": list(sha.values()), "algorithm": "sha1",
                "loaders": [loader], "game_versions": [version]})
        except Exception:  # noqa: BLE001
            latest = {}

    # 3) Los no encontrados en Modrinth: intentar CurseForge por fingerprint
    cf = {}
    key = load_cf_key()
    unknown = [f for f in files if sha[f.name] not in found]
    if key and unknown:
        try:
            fps = {f.name: _cf_fp(f) for f in unknown}
            res = http_post_json("https://api.curseforge.com/v1/fingerprints/432",
                                 {"fingerprints": list(fps.values())}, headers={"x-api-key": key})
            matches = res.get("data", {}).get("exactMatches", [])
            by_fp = {m.get("file", {}).get("fileFingerprint"): m for m in matches}
            cf_ids = list({m["id"] for m in by_fp.values()})
            names = {}
            if cf_ids:
                for m in http_post_json("https://api.curseforge.com/v1/mods", {"modIds": cf_ids},
                                        headers={"x-api-key": key}).get("data", []):
                    names[m["id"]] = m
            for fname, fp in fps.items():
                m = by_fp.get(fp)
                if m:
                    cf[fname] = {"id": m["id"], "file": m.get("file", {}), "mod": names.get(m["id"], {})}
        except Exception:  # noqa: BLE001
            cf = {}

    out = []
    for f in files:
        row = {"file": f.name, "enabled": f.suffix == ".jar", "size": f.stat().st_size,
               "source": None, "name": None, "slug": None, "installed": None, "latest": None,
               "update_url": None, "project_id": None, "sha1": sha[f.name],
               "client_side": None, "server_side": None, "download_url": None, "cf_tags": None}
        h = sha[f.name]
        if h in found:
            v = found[h]
            p = projects.get(v["project_id"], {})
            mine = next((x for x in v.get("files", []) if x.get("hashes", {}).get("sha1") == h), None)
            row.update(source="modrinth", project_id=v["project_id"], name=p.get("title"),
                       slug=p.get("slug"), installed=v.get("version_number"),
                       client_side=p.get("client_side"), server_side=p.get("server_side"),
                       download_url=mine["url"] if mine else None)
            lv = latest.get(h)
            if lv and lv["id"] != v["id"]:
                row["latest"] = lv["version_number"]
                row["update_url"] = lv["files"][0]["url"] if lv.get("files") else None
                row["update_filename"] = lv["files"][0]["filename"] if lv.get("files") else None
                row["update_sha1"] = lv["files"][0]["hashes"].get("sha1") if lv.get("files") else None
        elif f.name in cf:
            c = cf[f.name]
            mod = c["mod"]
            row.update(source="curseforge", project_id=str(c["id"]), name=mod.get("name"),
                       slug=mod.get("slug"), installed=c["file"].get("displayName"),
                       cf_tags=[t for t in c["file"].get("gameVersions", []) if t in ("Client", "Server")])
        out.append(row)
    return out


def update_mod(name, file, loader="neoforge", version="1.21.1"):
    """Actualiza un mod de Modrinth: descarga la nueva versión y borra la antigua."""
    old = _mod_path(name, file)
    sha = _hashes(old)["sha1"]
    latest = http_post_json("https://api.modrinth.com/v2/version_files/update", {
        "hashes": [sha], "algorithm": "sha1", "loaders": [loader], "game_versions": [version]})
    lv = latest.get(sha)
    if not lv or lv["id"] == http_post_json("https://api.modrinth.com/v2/version_files",
                                            {"hashes": [sha], "algorithm": "sha1"})[sha]["id"]:
        raise RuntimeError("no hay versión nueva para este mod")
    f = lv["files"][0]
    new_name = install(name, f["url"], f["filename"], f["hashes"].get("sha1"))
    if new_name != old.name:
        old.unlink()
    return new_name
