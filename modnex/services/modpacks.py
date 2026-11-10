"""Crear servidores a partir de modpacks (Modrinth y CurseForge).

- Modrinth: se instala NeoForge con la versión del índice .mrpack y se descargan solo los archivos
  cuyo env.server no es "unsupported". Los overrides (y server-overrides) se copian al servidor.
- CurseForge: se usa el paquete de servidor oficial del archivo (serverPackFileId). Su server.jar instala
  NeoForge con --installer al primer uso; aquí se ejecuta una vez y se deja listo para arrancar.

En ambos casos el archivo de cliente ORIGINAL del modpack se guarda en las releases, sin tocarlo,
para que conserve los ajustes que hizo su desarrollador.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from modnex.services import templates

from modnex import config

UA = "modnex-server-manager/1.0 (local)"
CF_CLASS_MODPACKS = 4471
CLIENT_ONLY = {"options.txt", "optionsof.txt", "optionsshaders.txt", "servers.dat", "servers.dat_old"}
CLIENT_DIRS = ("resourcepacks/", "shaderpacks/", "screenshots/", "saves/", "logs/", "crash-reports/")
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ \-]{0,47}")
STEPS = ["Descargando el modpack", "Preparando la carpeta", "Instalando NeoForge",
         "Instalando el servidor del modpack", "Escribiendo la configuración", "Listo"]


def _get_json(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _cf_key():
    from_env = os.environ.get("CURSEFORGE_API_KEY")
    if from_env:
        return from_env
    cfg = config.CONFIG_FILE
    return json.loads(cfg.read_text()).get("curseforge_api_key", "") if cfg.exists() else ""


def _cf(path, **params):
    key = _cf_key()
    if not key:
        raise RuntimeError("falta la API key de CurseForge")
    url = "https://api.curseforge.com/v1/" + path + ("?" + urllib.parse.urlencode(params) if params else "")
    return _get_json(url, headers={"x-api-key": key})


# ---------- búsqueda ----------

def search(source, q="", mc="1.21.1"):
    """Modpacks con servidor. Modrinth: server_side distinto de unsupported. CurseForge: tienen paquete de servidor."""
    q = (q or "").strip()
    if source == "modrinth":
        facets = [["project_type:modpack"], [f"versions:{mc}"], ["categories:neoforge"], ["server_side!=unsupported"]]
        d = _get_json("https://api.modrinth.com/v2/search?" + urllib.parse.urlencode(
            {"query": q, "limit": 24, "index": "downloads" if not q else "relevance", "facets": json.dumps(facets)}))
        return [{"source": "modrinth", "id": h["project_id"], "slug": h["slug"], "name": h["title"],
                 "summary": h["description"], "downloads": h["downloads"], "icon": h.get("icon_url"),
                 "server": h.get("server_side")} for h in d["hits"]]
    if source == "curseforge":
        params = {"gameId": 432, "classId": CF_CLASS_MODPACKS, "gameVersion": mc, "pageSize": 40,
                  "sortField": 6 if not q else 2, "sortOrder": "desc"}
        if q:
            params["searchFilter"] = q
        out = []
        for m in _cf("mods/search", **params)["data"]:
            files = m.get("latestFiles", [])
            if not any(f.get("serverPackFileId") and "NeoForge" in f.get("gameVersions", []) for f in files):
                continue  # solo NeoForge y con paquete de servidor
            out.append({"source": "curseforge", "id": str(m["id"]), "slug": m["slug"], "name": m["name"],
                        "summary": m["summary"], "downloads": m["downloadCount"],
                        "icon": (m.get("logo") or {}).get("url"), "server": "paquete de servidor"})
            if len(out) >= 24:
                break
        return out
    raise ValueError("fuente no válida")


def versions(source, project, mc="1.21.1"):
    """Versiones del modpack que sirven como servidor (para NeoForge)."""
    if source == "modrinth":
        vs = _get_json(f"https://api.modrinth.com/v2/project/{urllib.parse.quote(project)}/version?" + urllib.parse.urlencode(
            {"loaders": json.dumps(["neoforge"]), "game_versions": json.dumps([mc])}))
        out = []
        for v in vs[:20]:
            f = next((x for x in v["files"] if x["filename"].endswith(".mrpack")), None)
            if f:
                out.append({"id": v["id"], "name": v["version_number"], "date": v["date_published"][:10],
                            "mc": ", ".join(v["game_versions"][:2]), "file": f["filename"]})
        return out
    if source == "curseforge":
        fs = _cf(f"mods/{int(project)}/files", gameVersion=mc, pageSize=30)["data"]
        out = []
        for f in fs:
            if f.get("serverPackFileId"):
                out.append({"id": str(f["id"]), "name": f["displayName"], "date": f["fileDate"][:10],
                            "mc": mc, "file": f["fileName"], "server_pack": str(f["serverPackFileId"])})
        return out[:20]
    raise ValueError("fuente no válida")


# ---------- descargas con verificación ----------

def _download(url, dest, sha1=None, sha512=None, limit=2 * 1024 * 1024 * 1024):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    h1 = hashlib.sha1() if sha1 else None
    h5 = hashlib.sha512() if sha512 else None
    try:
        with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as fh:
            total = 0
            while chunk := r.read(1 << 16):
                total += len(chunk)
                if total > limit:
                    raise ValueError("el archivo supera el límite de 2 GB")
                fh.write(chunk)
                if h1: h1.update(chunk)
                if h5: h5.update(chunk)
        if sha1 and h1.hexdigest() != sha1:
            raise ValueError("el SHA-1 no coincide")
        if sha512 and h5.hexdigest() != sha512:
            raise ValueError("el SHA-512 no coincide")
    except BaseException:
        Path(dest).unlink(missing_ok=True)
        raise


def _safe_rel(path):
    p = path.replace("\\", "/")
    if not p or p.startswith("/") or ".." in p.split("/") or ":" in p.split("/")[0]:
        raise ValueError(f"ruta no permitida en el paquete: {path}")
    return p


def _client_only(rel):
    base = rel.rsplit("/", 1)[-1]
    return base in CLIENT_ONLY or any(rel.startswith(d) or ("/" + d) in ("/" + rel) for d in CLIENT_DIRS)


# ---------- resolución y creación ----------

def _modrinth_client(project, version_id, tmp):
    v = _get_json(f"https://api.modrinth.com/v2/version/{urllib.parse.quote(version_id)}")
    f = next(x for x in v["files"] if x["filename"].endswith(".mrpack"))
    _download(f["url"], tmp, sha1=f["hashes"].get("sha1"))
    z = zipfile.ZipFile(tmp)
    idx = json.loads(z.read("modrinth.index.json"))
    return f["filename"], idx, z


def _cf_client(project, file_id, tmp):
    f = _cf(f"mods/{int(project)}/files/{int(file_id)}")["data"]
    if not f.get("downloadUrl"):
        raise RuntimeError("el autor no permite descargar este archivo desde aquí")
    _download(f["downloadUrl"], tmp)
    z = zipfile.ZipFile(tmp)
    if "manifest.json" not in z.namelist():
        raise RuntimeError(
            "este archivo no es un paquete de cliente (no trae manifest.json). "
            "Suele pasar al usar el id de un server pack: usa el archivo de cliente del mismo modpack")
    man = json.loads(z.read("manifest.json"))
    return f["fileName"], man, z, f


def _loader_from(idx_or_manifest, kind):
    if kind == "modrinth":
        deps = idx_or_manifest["dependencies"]
        return deps["minecraft"], deps["neoforge"]
    mc = idx_or_manifest["minecraft"]["version"]
    lid = idx_or_manifest["minecraft"]["modLoaders"][0]["id"]
    m = re.match(r"neoforge-(.+)", lid)
    if not m:
        raise RuntimeError(f"el modpack usa {lid}; solo se admite NeoForge")
    return mc, m.group(1)


def _extract_overrides(z, dest, prefix, skip=frozenset()):
    for info in z.infolist():
        name = info.filename
        if not name.startswith(prefix) or info.is_dir():
            continue
        rel = _safe_rel(name[len(prefix):])
        if _client_only(rel) or rel in skip:
            continue
        target = Path(dest) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with z.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)


_PID_RE = re.compile(r"/data/([A-Za-z0-9]+)/")


def _modrinth_client_only(files, log):
    """IDs de proyecto que Modrinth marca como solo cliente (server_side == unsupported).
    El índice del .mrpack puede decir "required" para mods que en realidad no corren en servidor
    (Sodium, Iris...). Modrinth es la fuente de verdad. Si la consulta falla, no se excluye nada."""
    pids = sorted({m.group(1) for f in files for u in f.get("downloads", [])[:1]
                   for m in [_PID_RE.search(u)] if m})
    out = set()
    try:
        for i in range(0, len(pids), 100):
            chunk = pids[i:i + 100]
            data = _get_json("https://api.modrinth.com/v2/projects?" + urllib.parse.urlencode({"ids": json.dumps(chunk)}))
            out |= {p["id"] for p in data if p.get("server_side") == "unsupported"}
    except Exception as e:
        log(f"aviso: no pude comprobar server_side en Modrinth ({e}); se instalan según el índice")
        return set()
    return out


def _overrides_client_jars(z, prefixes, log):
    """Jars de overrides/ (y server-overrides/) que Modrinth identifica como solo cliente.
    Se buscan por SHA-1 en Modrinth (version_files) y se mira server_side del proyecto."""
    jars = {}
    for info in z.infolist():
        for pre in prefixes:
            if info.filename.startswith(pre + "mods/") and info.filename.endswith(".jar"):
                jars[info.filename] = info
    if not jars:
        return set()
    sha = {}
    for name, info in jars.items():
        h = hashlib.sha1()
        with z.open(info) as src:
            for chunk in iter(lambda: src.read(1 << 20), b""):
                h.update(chunk)
        sha[h.hexdigest()] = name
    try:
        req = urllib.request.Request("https://api.modrinth.com/v2/version_files",
                                     data=json.dumps({"hashes": list(sha), "algorithm": "sha1"}).encode(),
                                     headers={"User-Agent": UA, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            versions = json.loads(r.read())
        pids = sorted({v["project_id"] for v in versions.values()})
        projs = _get_json("https://api.modrinth.com/v2/projects?" + urllib.parse.urlencode({"ids": json.dumps(pids)})) if pids else []
        client = {p["id"] for p in projs if p.get("server_side") == "unsupported"}
    except Exception as e:
        log(f"aviso: no pude comprobar los jars de overrides en Modrinth ({e})")
        return set()
    out = set()
    for h, v in versions.items():
        if v.get("project_id") in client and h in sha:
            out.add(sha[h])
    return out


def _install_modrinth_server(dest, idx, z, log):
    n = 0
    client_pids = _modrinth_client_only(idx["files"], log)
    skipped = []
    for f in idx["files"]:
        if f.get("env", {}).get("server") == "unsupported":
            continue
        url0 = (f.get("downloads") or [""])[0]
        m = _PID_RE.search(url0)
        if m and m.group(1) in client_pids:
            skipped.append(f["path"])
            continue
        rel = _safe_rel(f["path"])
        if _client_only(rel):
            continue
        target = Path(dest) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        url = f["downloads"][0]
        _download(url, target, sha1=f["hashes"].get("sha1"), sha512=None if f["hashes"].get("sha1") else f["hashes"].get("sha512"))
        n += 1
        log(f"mods del servidor: {n}")
    if skipped:
        log(f"omitidos por ser solo de cliente (Modrinth): {len(skipped)}")
    ov_client = _overrides_client_jars(z, ("overrides/", "server-overrides/"), log)
    if ov_client:
        log(f"omitidos de overrides por ser solo de cliente (Modrinth): {len(ov_client)}")
    _extract_overrides(z, dest, "overrides/", skip=frozenset(p[len("overrides/"):] for p in ov_client if p.startswith("overrides/")))
    _extract_overrides(z, dest, "server-overrides/", skip=frozenset(p[len("server-overrides/"):] for p in ov_client if p.startswith("server-overrides/")))
    return n


def _install_cf_server(dest, project, server_pack_id, z_client_manifest, log):
    sp = _cf(f"mods/{int(project)}/files/{int(server_pack_id)}")["data"]
    if not sp.get("downloadUrl"):
        raise RuntimeError("el paquete de servidor no se puede descargar")
    tmp = Path(dest) / ".serverpack.zip"
    _download(sp["downloadUrl"], tmp)
    try:
        z = zipfile.ZipFile(tmp)
        for info in z.infolist():
            if info.is_dir():
                continue
            rel = _safe_rel(info.filename)
            if rel.endswith((".sh", ".bat")) and "/" not in rel:
                rel = "original-" + rel  # los scripts del autor se guardan; el arranque lo genera el gestor
            target = Path(dest) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    finally:
        tmp.unlink(missing_ok=True)
    log("paquete de servidor extraído")


def _run_starter(dest, loader_version, log):
    """Ejecuta el server.jar de CurseForge en modo instalador (una vez)."""
    jar = Path(dest) / "server.jar"
    if not jar.exists() or list(Path(dest).glob("libraries/net/neoforged/neoforge/*/unix_args.txt")):
        return
    java = templates._java()
    log("instalando NeoForge con el instalador del paquete (puede tardar varios minutos)")
    r = subprocess.run([java, "-jar", "server.jar", "--installer", loader_version, "nogui"],
                       cwd=dest, capture_output=True, text=True, timeout=1800)
    if not list(Path(dest).glob("libraries/net/neoforged/neoforge/*/unix_args.txt")):
        tail = (r.stdout + r.stderr).strip().splitlines()[-6:]
        raise RuntimeError("el instalador del paquete no dejó NeoForge listo: " + " | ".join(tail))


# ---------- trabajo de creación ----------

def start_job(servers_dir, name, source, project, version_id, memory, port, display_name, include_client, on_done):
    job = uuid_hex()
    with templates.JOBS_LOCK:
        templates.JOBS[job] = {"state": "running", "step": 0, "steps": STEPS, "error": None, "server": name, "perf": []}
    threading.Thread(target=_run, args=(job, servers_dir, name, source, project, version_id, memory, port,
                                        display_name, include_client, on_done), daemon=True).start()
    return job


def uuid_hex():
    import uuid
    return uuid.uuid4().hex[:16]


def _run(job, servers_dir, name, source, project, version_id, memory, port, display_name, include_client, on_done):
    dest = Path(servers_dir) / name
    tmp_client = Path(servers_dir) / (".client-" + job)
    client_name = None
    try:
        def step(i):
            templates._set(job, step=i)
        step(0)
        if source == "modrinth":
            client_name, idx, z = _modrinth_client(project, version_id, tmp_client)
            mc, loader_version = _loader_from(idx, "modrinth")
            manifest = None
        elif source == "curseforge":
            client_name, manifest, z, fobj = _cf_client(project, version_id, tmp_client)
            mc, loader_version = _loader_from(manifest, "curseforge")
            sp_id = fobj.get("serverPackFileId")
            if not sp_id:
                raise RuntimeError("este archivo no tiene paquete de servidor")
            idx = None
        else:
            raise ValueError("fuente no válida")
        step(1)
        dest.mkdir(parents=True, exist_ok=False)
        if source == "modrinth":
            step(2)
            templates.install("neoforge", mc, dest, loader_version)
            step(3)
            _install_modrinth_server(dest, idx, z, lambda m: None)
        else:
            step(2)
            step(3)
            _install_cf_server(dest, project, sp_id, manifest, lambda m: None)
            _run_starter(dest, loader_version, lambda m: None)
        step(4)
        (dest / "eula.txt").write_text("eula=true\n")
        (dest / "user_jvm_args.txt").write_text(f"-Xmx{memory}\n-Xms{templates._half(memory)}\n")
        templates.write_properties(dest, port, display_name or name)
        info = {"args": "neoforge"} if list(dest.glob("libraries/net/neoforged/neoforge/*/unix_args.txt")) else {}
        (dest / "start.sh").write_text(templates.start_script("neoforge", dest, info))
        (dest / "start.sh").chmod(0o755)
        (dest / "mods").mkdir(exist_ok=True)
        meta = {"template": "neoforge", "mc": mc, "loader": "neoforge", "loader_version": loader_version,
                "created": int(time.time()),
                "modpack": {"source": source, "project": str(project), "version": str(version_id), "name": client_name}}
        (dest / ".manager.json").write_text(json.dumps(meta, indent=2) + "\n")
        if include_client:
            import release
            rd = release.release_dir(name)
            os.replace(tmp_client, rd / client_name)
        else:
            tmp_client.unlink(missing_ok=True)
        on_done(name)
        step(5)
        templates._set(job, state="done")
    except BaseException as e:  # noqa: BLE001
        tmp_client.unlink(missing_ok=True)
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        templates._set(job, state="error", error=f"{type(e).__name__}: {e}")
