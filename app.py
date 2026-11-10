#!/usr/bin/env python3
"""Gestor de servidores de Minecraft.

Por defecto escucha en todas las interfaces (acceso desde la LAN) y exige
una contraseña (access_token en config.json). Funciones: listar/arrancar/parar
servidores, ver log y enviar comandos, gestionar mods, ajustar memoria y
buscar/instalar mods desde Modrinth y CurseForge.
"""
import collections
import hashlib
import html
import ipaddress
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import autofilter
import db
import extras
import plugins
import release
import templates
import modpacks

SERVERS_DIR = Path(os.environ.get("SERVERS_DIR", "/home/luky/servers")).resolve()
HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
CONFIG_FILE = HERE / "config.json"
PORT = int(os.environ.get("MANAGER_PORT", "8765"))
COOKIE = "mgr_session"
UA = "cobblemon-server-manager/1.0 (local)"
ALLOWED_DL_HOSTS = {"cdn.modrinth.com", "mediafilez.forgecdn.net", "edge.forgecdn.net"}
CF_LOADER_TYPE = {"forge": 1, "fabric": 4, "neoforge": 6}
MAX_MOD_BYTES = 512 * 1024 * 1024

NAME_RE = re.compile(r"[A-Za-z0-9._-]+")
JAR_RE = re.compile(r"[A-Za-z0-9._+\-\[\]() ]+\.jar(\.disabled)?")
MEM_RE = re.compile(r"\d{1,2}[MG]")

PROCS = {}  # nombre -> Popen (solo los arrancados desde este gestor)
LOCK = threading.Lock()


def load_config():
    return json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}


def load_cf_key():
    if os.environ.get("CURSEFORGE_API_KEY"):
        return os.environ["CURSEFORGE_API_KEY"]
    return load_config().get("curseforge_api_key", "")


def ensure_config():
    """Crea config.json con una contraseña aleatoria si no existe o no tiene access_token."""
    cfg = load_config()
    if not cfg.get("access_token"):
        cfg["access_token"] = secrets.token_urlsafe(24)
        cfg.setdefault("bind", "0.0.0.0")
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n")
        os.chmod(CONFIG_FILE, 0o600)
        print(f"Contraseña generada en {CONFIG_FILE} (campo access_token)", flush=True)
    return cfg


def http_json(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


# ---------- servidores ----------

def server_path(name):
    if not NAME_RE.fullmatch(name or ""):
        raise ValueError("nombre de servidor no válido")
    p = (SERVERS_DIR / name).resolve()
    if p.parent != SERVERS_DIR or not p.is_dir():
        raise FileNotFoundError(f"no existe el servidor {name}")
    return p


def _alive(pid):
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    try:
        return b"java" in Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False


def status(name):
    p = server_path(name)
    with LOCK:
        proc = PROCS.get(name)
        if proc and proc.poll() is None:
            return {"running": True, "pid": proc.pid, "control": True}
        PROCS.pop(name, None)
    pidf = p / ".manager.pid"
    if pidf.exists():
        try:
            pid = int(pidf.read_text().strip())
        except ValueError:
            pid = 0
        if pid and _alive(pid):
            return {"running": True, "pid": pid, "control": False}
        pidf.unlink(missing_ok=True)
    return {"running": False, "pid": None, "control": False}


def list_servers():
    out = []
    for d in sorted(SERVERS_DIR.iterdir()):
        if not d.is_dir() or not NAME_RE.fullmatch(d.name) or d.resolve() == HERE:
            continue
        if not ((d / "start.sh").exists() or (d / "run.sh").exists() or (d / "mods").is_dir()):
            continue
        sub = d / templates.folder_for(templates.server_template(d))
        mods = [f for f in sub.glob("*.jar*")] if sub.is_dir() else []
        parent = None
        try:
            parent = json.loads((d / ".manager.json").read_text()).get("parent")
            if not (isinstance(parent, str) and NAME_RE.fullmatch(parent) and parent != d.name):
                parent = None
        except (OSError, ValueError):
            pass
        out.append({
            "name": d.name,
            "parent": parent,
            "mods": len([m for m in mods if m.suffix == ".jar"]),
            "status": status(d.name),
            "memory": read_memory(d),
        })
    return out


ATTEMPTS = {}   # servidor -> mods puestos en cuarentena en la sesión de arranque actual
STOPPING = set()  # servidores que el usuario está parando (no se reintenta su arranque)
MAX_QUARANTINE = 5


def start(name, _auto=False):
    if status(name)["running"]:
        raise RuntimeError("el servidor ya está en marcha")
    if not _auto:
        ATTEMPTS.pop(name, None)
        STOPPING.discard(name)
    p = server_path(name)
    script = p / "start.sh" if (p / "start.sh").exists() else p / "run.sh"
    if not script.exists():
        raise FileNotFoundError("no hay start.sh ni run.sh")
    try:
        log = open(p / "manager-console.log", "ab")
    except OSError as e:
        raise RuntimeError(f"no se puede escribir el log de consola: {e.strerror}")
    # El Java del gestor manda aunque el start.sh se escribiera con otro (p. ej. si el runtime no existía entonces).
    env = dict(os.environ, JAVA_BIN=templates._java())
    offset = (p / "manager-console.log").stat().st_size
    proc = subprocess.Popen(
        ["bash", str(script)], cwd=p, env=env, stdin=subprocess.PIPE,
        stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
    )
    log.close()
    with LOCK:
        PROCS[name] = proc
    (p / ".manager.pid").write_text(str(proc.pid))
    threading.Thread(target=_supervise, args=(name, proc, offset), daemon=True).start()
    plugins.emit("server_started", name)


def _supervise(name, proc, offset):
    """Si el arranque falla por un mod de cliente identificado en la traza, lo pone en cuarentena y reintenta."""
    rc = proc.wait()
    with LOCK:
        if PROCS.get(name) is proc:
            PROCS.pop(name, None)
    if name in STOPPING:
        STOPPING.discard(name)
        plugins.emit("server_stopped", name, "usuario")
        return
    p = server_path(name)
    try:
        with open(p / "manager-console.log", "rb") as f:
            f.seek(offset)
            text = f.read().decode("utf-8", "ignore")
    except OSError:
        return
    if rc == 0:
        plugins.emit("server_stopped", name, "salida normal")
        return
    if "Done (" in autofilter.clean(text):
        plugins.emit("server_crashed", name, "cayó mientras estaba en marcha")
        return  # arrancó: no es un fallo de arranque que filtrar
    cands, ambiguous = autofilter.diagnose(text, p / "mods")
    if not cands:
        db.audit("sistema", name, "arranque fallido", "sin mod de cliente identificado en la traza")
        plugins.emit("server_crashed", name, "arranque fallido")
        return
    if ambiguous:
        db.audit("sistema", name, "arranque fallido", "varios candidatos, revisar a mano: " + ", ".join(j for j, _ in cands))
        return
    if ATTEMPTS.get(name, 0) >= MAX_QUARANTINE:
        db.audit("sistema", name, "arranque fallido", f"límite de {MAX_QUARANTINE} mods en cuarentena alcanzado")
        return
    jar, why = cands[0]
    if autofilter.quarantine(p, jar) is None:
        return
    ATTEMPTS[name] = ATTEMPTS.get(name, 0) + 1
    db.audit("sistema", name, "mod de cliente en cuarentena", f"{jar}: {why}")
    time.sleep(2)
    try:
        start(name, _auto=True)
    except RuntimeError as e:
        db.audit("sistema", name, "reintento no iniciado", str(e))


def stop(name):
    p = server_path(name)
    STOPPING.add(name)
    with LOCK:
        proc = PROCS.get(name)
    if proc and proc.poll() is None:
        try:
            proc.stdin.write(b"stop\n")
            proc.stdin.flush()
            proc.wait(timeout=120)
        except (BrokenPipeError, subprocess.TimeoutExpired):
            proc.kill()
            proc.wait(timeout=30)
        with LOCK:
            PROCS.pop(name, None)
    else:
        st = status(name)
        if st["running"]:
            # Sin manejador de stdin (el gestor se reinició): SIGTERM deja que Java guarde el mundo.
            os.kill(st["pid"], signal.SIGTERM)
            for _ in range(240):
                if not _alive(st["pid"]):
                    break
                time.sleep(0.5)
    (p / ".manager.pid").unlink(missing_ok=True)


def send_command(name, cmd):
    if not cmd or "\n" in cmd or len(cmd) > 256:
        raise ValueError("comando no válido")
    with LOCK:
        proc = PROCS.get(name)
    if not proc or proc.poll() is not None:
        raise RuntimeError("sin control directo: arranca el servidor desde el gestor para poder enviar comandos")
    proc.stdin.write((cmd + "\n").encode())
    proc.stdin.flush()


_JOIN_RE = re.compile(r"\]: (\w{1,16}) joined the game")
_LEAVE_RE = re.compile(r"\]: (\w{1,16}) left the game")
_START_RE = re.compile(r"Starting minecraft server|Starting Minecraft server|Loading Minecraft \d")


def live_metrics(name):
    """Estado en vivo para el panel: memoria y tiempo de actividad del proceso, jugadores según el registro
    (sin enviar comandos a la consola) y recuento de avisos y errores recientes."""
    p = server_path(name)
    st = status(name)
    out = {"running": st["running"], "uptime_s": None, "rss_mb": None, "players": [], "max_players": None,
           "warn": 0, "error": 0, "disk_free_gb": round(shutil.disk_usage(p).free / 2**30, 1)}
    pid = st.get("pid")
    if st["running"] and pid:
        try:
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    out["rss_mb"] = int(line.split()[1]) // 1024
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            since_boot = float(Path("/proc/uptime").read_text().split()[0])
            out["uptime_s"] = max(0, int(since_boot - int(fields[19]) / os.sysconf("SC_CLK_TCK")))
        except (OSError, ValueError, IndexError):
            pass
    try:
        for line in (p / "server.properties").read_text().splitlines():
            if line.startswith("max-players="):
                out["max_players"] = int(line.split("=", 1)[1])
    except (OSError, ValueError):
        pass
    online = []
    for line in read_log(name, 1500).splitlines():
        if _START_RE.search(line):
            online = []
        m = _JOIN_RE.search(line)
        if m and m.group(1) not in online:
            online.append(m.group(1))
        m = _LEAVE_RE.search(line)
        if m and m.group(1) in online:
            online.remove(m.group(1))
    if st["running"]:
        out["players"] = online
    recent = read_log(name, 400)
    out["warn"] = len(re.findall(r"\bWARN\b", recent))
    out["error"] = len(re.findall(r"\b(?:ERROR|FATAL)\b", recent))
    return out


def read_log(name, lines=200):
    p = server_path(name)
    f = p / "logs" / "latest.log"
    if not f.exists():
        f = p / "manager-console.log"
    if not f.exists():
        return ""
    with open(f, errors="replace") as fh:
        return "".join(collections.deque(fh, maxlen=max(1, min(lines, 2000))))


# ---------- memoria ----------

def read_memory(p):
    f = (p if isinstance(p, Path) else server_path(p)) / "user_jvm_args.txt"
    mem = {"xmx": None, "xms": None}
    if f.exists():
        for line in f.read_text().splitlines():
            m = re.match(r"\s*-Xm([xs])(\S+)", line)
            if m:
                mem["xmx" if m.group(1) == "x" else "xms"] = m.group(2)
    return mem


def set_memory(name, xmx, xms):
    if not (MEM_RE.fullmatch(xmx) and MEM_RE.fullmatch(xms)):
        raise ValueError("memoria no válida (ej. 8G o 4096M)")
    if status(name)["running"]:
        raise RuntimeError("para el servidor antes de cambiar la memoria")
    f = server_path(name) / "user_jvm_args.txt"
    lines = f.read_text().splitlines() if f.exists() else []
    keep = [l for l in lines if not re.match(r"\s*-Xm[xs]", l)]
    keep += [f"-Xmx{xmx}", f"-Xms{xms}"]
    f.write_text("\n".join(keep) + "\n")


# ---------- mods ----------

def server_template_of(name):
    return templates.server_template(server_path(name))


def server_loader(name):
    return templates.loader_of(server_template_of(name))


def addons_dir(name):
    return server_path(name) / templates.folder_for(server_template_of(name))


def list_mods(name):
    d = addons_dir(name)
    if not d.is_dir():
        return []
    return sorted(
        [{"file": f.name, "enabled": f.suffix == ".jar", "size": f.stat().st_size}
         for f in d.iterdir() if JAR_RE.fullmatch(f.name)],
        key=lambda x: x["file"].lower(),
    )


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


def safe_jar_name(filename):
    fname = os.path.basename(filename or "")
    if not re.fullmatch(r"[A-Za-z0-9._+\-\[\]() ]+\.jar", fname):
        raise ValueError("nombre de archivo no válido")
    return fname


# ---------- búsqueda e instalación ----------

KINDS = {
    "mod": {"perm": "mods", "cf_class": 6, "mr_type": "mod"},
    "plugin": {"perm": "mods", "cf_class": 5, "mr_type": "plugin"},
    "datapack": {"perm": "datapacks", "cf_class": 6945, "mr_type": "datapack"},
    "resourcepack": {"perm": "textures", "cf_class": 12, "mr_type": "resourcepack"},
}
MR_SORTS = {"relevance", "downloads", "updated", "newest"}
CF_SORTS = {"relevance": 2, "downloads": 6, "updated": 3, "newest": 11}
# Modrinth declara por separado el lado cliente y el lado servidor (required / optional / unsupported).
# "server" = mods que tienen sentido en un servidor: lo exigen, o lo admiten sin exigir cliente
# (así se excluyen mods de cliente que solo "toleran" el servidor, como un minimapa).
SIDE_FILTERS = {
    "server": '(server_side = "required") OR (server_side = "optional" AND client_side != "required")',
    "required": 'server_side = "required"',
}


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _match_score(query, item):
    """0 = nombre exacto, 1 = empieza por, 2 = contiene, 3 = no coincide por nombre."""
    q, n, sl = _norm(query), _norm(item["name"]), _norm(item["slug"])
    if n == q or sl == q:
        return 0
    if n.startswith(q) or sl.startswith(q):
        return 1
    return 2 if (q in n or q in sl) else 3


def _cf_client_only(mod, version):
    """CurseForge etiqueta los archivos con 'Client' y/o 'Server'. Solo es seguro descartar los que
    son únicamente de cliente (p. ej. Sodium); los que no traen etiqueta se mantienen."""
    files = [f for f in mod.get("latestFiles", []) if version in f.get("gameVersions", [])] or mod.get("latestFiles", [])
    return bool(files) and all("Client" in f.get("gameVersions", []) and "Server" not in f.get("gameVersions", [])
                               for f in files)


def compat_for(server, kind):
    """Loader y tipo real que puede usar un servidor. Un Paper recibe plugins; uno Vanilla, nada."""
    if not server or kind in ("datapack", "resourcepack"):  # datapacks y texturas valen en cualquier servidor
        return None, kind
    tpl = server_template_of(server)
    if templates.kind_of(tpl) == "none":
        raise ValueError("este servidor es Vanilla: no admite mods ni plugins (usa datapacks)")
    if templates.kind_of(tpl) == "plugin":
        if kind == "mod":
            kind = "plugin"
        if kind != "plugin":
            raise ValueError("este servidor usa plugins de Paper, no mods")
    elif kind == "plugin":
        raise ValueError("este servidor usa mods, no plugins")
    return templates.loader_of(tpl), kind


PER_PAGE = 24
MAX_PAGE = 50
TAG_RE = re.compile(r"[a-z0-9][a-z0-9\-]{0,29}")
TAG_LABELS = {"adventure": "Aventura", "cursed": "Maldito", "decoration": "Decoración", "economy": "Economía", "equipment": "Equipamiento",
              "food": "Comida", "game-mechanics": "Mecánicas", "library": "Librería", "magic": "Magia", "management": "Administración",
              "minigame": "Minijuego", "mobs": "Criaturas", "optimization": "Optimización", "social": "Social", "storage": "Almacenamiento",
              "technology": "Tecnología", "transportation": "Transporte", "utility": "Utilidad", "worldgen": "Generación de mundo",
              "combat": "Combate", "themed": "Temático", "tweaks": "Ajustes", "realistic": "Realista", "simplistic": "Sencillo",
              "modded": "Para mods", "vanilla-like": "Estilo vainilla", "challenging": "Desafiante", "kitchen-sink": "De todo",
              "lightweight": "Ligero", "multiplayer": "Multijugador", "quests": "Misiones", "exploration": "Exploración",
              "fantasy": "Fantasía", "survival": "Supervivencia", "technology-fallback": "Tecnología", "chat": "Chat", "mechanics": "Mecánicas",
              "world-management": "Gestión del mundo", "gameplay": "Jugabilidad", "worldgen-fallback": "Mundo", "transport": "Transporte"}
_TAG_CACHE = {"at": 0, "rows": []}


def category_tags(kind):
    """Etiquetas de Modrinth para un tipo de contenido: [{name, label}]. Se cachean 6 h; si Modrinth falla, lista vacía."""
    if time.time() - _TAG_CACHE["at"] > 6 * 3600 or not _TAG_CACHE["rows"]:
        try:
            _TAG_CACHE["rows"] = http_json("https://api.modrinth.com/v2/tag/category")
            _TAG_CACHE["at"] = time.time()
        except Exception:  # noqa: BLE001 - sin etiquetas el filtro simplemente no se ofrece
            return []
    want = KINDS[kind]["mr_type"]
    out = []
    for r in _TAG_CACHE["rows"]:
        if r.get("project_type") == want and r.get("header") == "categories" and TAG_RE.fullmatch(str(r.get("name", ""))):
            out.append({"name": r["name"], "label": TAG_LABELS.get(r["name"], r["name"].replace("-", " ").capitalize())})
    return sorted(out, key=lambda t: t["label"].lower())


def search(source, q, loader, version, kind="mod", sort="auto", side="server", page=1, tags=(), paged=False):
    """Busca contenido. Con `paged` devuelve {items, total, page, pages, per_page}; si no, solo la lista (la usan los plugins)."""
    page = max(1, min(int(page or 1), MAX_PAGE))
    tags = [t for t in dict.fromkeys(tags or ()) if TAG_RE.fullmatch(t)][:6]
    res = _search(source, q, loader, version, kind, sort, side, page, tags)
    if not paged:
        return res["items"]
    total = max(res["total"], len(res["items"]))
    return {"items": res["items"], "total": total, "page": page, "per_page": PER_PAGE, "pages": max(1, -(-total // PER_PAGE))}


def _search(source, q, loader, version, kind, sort, side, page, tags):
    if kind not in KINDS:
        raise ValueError("tipo de contenido no válido")
    if kind == "mod" and loader not in CF_LOADER_TYPE:
        raise ValueError("loader no válido")
    q = (q or "").strip()
    if sort == "auto":  # lo más descargado al abrir; relevancia cuando se busca algo concreto
        sort = "relevance" if q else "downloads"
    if source == "modrinth":
        facets = [[f"project_type:{KINDS[kind]['mr_type']}"], [f"versions:{version}"]]
        params = {"query": q, "limit": PER_PAGE, "offset": (page - 1) * PER_PAGE, "index": sort if sort in MR_SORTS else "downloads"}
        facets.extend([f"categories:{t}"] for t in tags)   # cada etiqueta restringe más (Y, no O)
        if kind == "mod":
            facets.append([f"categories:{loader}"])
            if side in SIDE_FILTERS:
                params["filters"] = SIDE_FILTERS[side]
        elif kind == "plugin":
            facets.append(["categories:paper"])
        params["facets"] = json.dumps(facets)
        d = http_json("https://api.modrinth.com/v2/search?" + urllib.parse.urlencode(params))
        items = [{"source": "modrinth", "id": h["project_id"], "slug": h["slug"], "name": h["title"],
                  "summary": h["description"], "downloads": h["downloads"], "icon": h.get("icon_url")}
                 for h in d["hits"]]
        if q:
            items.sort(key=lambda it: _match_score(q, it))  # estable: conserva el orden de Modrinth
        return {"items": items, "total": int(d.get("total_hits", len(items)))}
    if source == "curseforge":
        key = load_cf_key()
        if not key:
            raise RuntimeError("falta la API key de CurseForge (config.json o CURSEFORGE_API_KEY)")
        params = {"gameId": 432, "classId": KINDS[kind]["cf_class"], "gameVersion": version, "pageSize": PER_PAGE,
                  "index": (page - 1) * PER_PAGE, "sortField": CF_SORTS.get(sort, 6), "sortOrder": "desc"}
        if q:
            params["searchFilter"] = q
        if kind == "mod":
            params["modLoaderType"] = CF_LOADER_TYPE[loader]
        resp = http_json("https://api.curseforge.com/v1/mods/search?" + urllib.parse.urlencode(params),
                         headers={"x-api-key": key})
        data = resp["data"]
        total = int((resp.get("pagination") or {}).get("totalCount", len(data)))
        if kind == "mod" and side in SIDE_FILTERS:
            data = [m for m in data if not _cf_client_only(m, version)]
        items = [{"source": "curseforge", "id": str(m["id"]), "slug": m["slug"], "name": m["name"],
                  "summary": m["summary"], "downloads": m["downloadCount"],
                  "icon": (m.get("logo") or {}).get("url")} for m in data]
        if q:
            # La búsqueda de CurseForge es difusa: se reordena por coincidencia de nombre y se
            # descartan los resultados que no mencionan la búsqueda en nombre ni identificador.
            items.sort(key=lambda it: _match_score(q, it))  # estable: conserva el orden por popularidad
            good = [it for it in items if _match_score(q, it) < 3]
            items = good if len(good) >= 3 else items
        return {"items": items[:PER_PAGE], "total": total}
    raise ValueError("fuente no válida")


def mod_files(source, project, slug, loader, version, kind="mod"):
    if kind not in KINDS:
        raise ValueError("tipo de contenido no válido")
    if source == "modrinth":
        loaders = [loader] if kind == "mod" else (["datapack"] if kind == "datapack" else
                  (["paper", "spigot", "bukkit", "purpur"] if kind == "plugin" else ["minecraft"]))
        q = urllib.parse.urlencode({"loaders": json.dumps(loaders), "game_versions": json.dumps([version])})
        vs = http_json(f"https://api.modrinth.com/v2/project/{urllib.parse.quote(project)}/version?{q}")
        out = []
        for v in vs[:10]:
            f = next((x for x in v["files"] if x.get("primary")), v["files"][0])
            out.append({"id": v["id"], "version": v["version_number"], "filename": f["filename"], "url": f["url"],
                        "sha1": f["hashes"].get("sha1"), "date": v["date_published"][:10], "page": None})
        return out
    if source == "curseforge":
        key = load_cf_key()
        if not key:
            raise RuntimeError("falta la API key de CurseForge")
        params = {"gameVersion": version}
        if kind == "mod":
            params["modLoaderType"] = CF_LOADER_TYPE[loader]
        d = http_json(f"https://api.curseforge.com/v1/mods/{int(project)}/files?" + urllib.parse.urlencode(params),
                      headers={"x-api-key": key})
        out = []
        for f in d["data"][:10]:
            sha1 = next((h["value"] for h in f.get("hashes", []) if h["algo"] == 1), None)
            out.append({"id": str(f["id"]), "version": f["displayName"], "filename": f["fileName"], "url": f.get("downloadUrl"),
                        "sha1": sha1, "date": f["fileDate"][:10],
                        "page": f"https://www.curseforge.com/minecraft/mc-mods/{slug}/files/{f['id']}"})
        return out
    raise ValueError("fuente no válida")


def _download(url, tmp, sha1, limit=MAX_MOD_BYTES):
    """Descarga a un archivo temporal con límite de tamaño y verificación SHA-1; limpia si algo falla."""
    h = hashlib.sha1()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
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
        if sha1 and h.hexdigest() != sha1:
            raise ValueError("el SHA-1 no coincide; descarga cancelada")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return h.hexdigest()


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


# ---------- ficha de un mod (página tipo CurseForge) ----------

SAFE_URL = re.compile(r"https?://[^\s\"'<>]{4,600}")


def _safe_href(url):
    return url if url and SAFE_URL.fullmatch(url) else None


_HTML_TAG_START = re.compile(r"^\s{0,3}<(/?[a-zA-Z][a-zA-Z0-9-]*|!--)")
_SAFE_LINK = re.compile(r"https?://[^\s\"'<>]{4,600}")


def _link_href(url):
    return url if _SAFE_LINK.fullmatch(url or "") else None


def _inline(t):
    """Markdown en línea. El texto se escapa; las etiquetas HTML se dejan pasar y las filtra después sanitize_html."""
    held = []

    def hold(h):
        held.append(h)
        return f"\x00{len(held) - 1}\x00"

    t = re.sub(r"\\([\\`*_{}\[\]()#+\-.!~|<>])", lambda m: hold(html.escape(m.group(1), quote=True)), t)
    t = re.sub(r"`([^`\n]+)`", lambda m: hold("<code>" + html.escape(m.group(1), quote=True) + "</code>"), t)

    def image(m):
        href = _link_href(m.group(2))
        if not href:
            return html.escape(m.group(0), quote=True)
        return hold(f'<img src="{html.escape(href, quote=True)}" alt="{html.escape(m.group(1), quote=True)}" loading="lazy">')

    def link(m):
        href = _link_href(m.group(2))
        if not href:
            return m.group(1)
        return hold(f'<a href="{html.escape(href, quote=True)}" target="_blank" rel="noopener nofollow">{m.group(1)}</a>')

    url = r"((?:[^\s()]|\([^\s()]*\))+)"
    t = re.sub(r"!\[([^\]\n]{0,200})\]\(" + url + r"(?:\s+\"[^\"]*\")?\)", image, t)
    t = re.sub(r"\[([^\]\n]{1,300})\]\(" + url + r"(?:\s+\"[^\"]*\")?\)", link, t)
    t = re.sub(r"<(https?://[^\s>]{4,600})>", lambda m: hold(
        f'<a href="{html.escape(m.group(1), quote=True)}" target="_blank" rel="noopener nofollow">{html.escape(m.group(1), quote=False)}</a>')
        if _link_href(m.group(1)) else m.group(0), t)
    t = re.sub(r"</?[a-zA-Z][^<>\n]{0,300}>", lambda m: hold(m.group(0)), t)
    t = html.escape(t, quote=False)
    t = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__",
               lambda m: "<strong>" + (m.group(1) or m.group(2)) + "</strong>", t)
    t = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"<del>\1</del>", t)
    t = re.sub(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])|(?<![\w_])_(?=\S)([^_\n]+?)(?<=\S)_(?![\w_])",
               lambda m: "<em>" + (m.group(1) or m.group(2)) + "</em>", t)
    t = re.sub(r"\x00(\d+)\x00", lambda m: held[int(m.group(1))], t)
    return t


def _heading_level(n):
    return min(n + 1, 5)  # la ficha ya tiene un h1: los títulos del mod empiezan en h2


def _is_block_start(line):
    return bool(re.match(r"^(#{1,6})\s", line) or re.match(r"^\s*(```|~~~)", line)
                or re.match(r"^\s*(\*\s*){3,}$|^\s*(-\s*){3,}$|^\s*(_\s*){3,}$", line)
                or re.match(r"^\s*>", line) or re.match(r"^\s*([-*+]|\d+[.)])\s+", line)
                or _HTML_TAG_START.match(line))


def _table_sep(line):
    return bool(re.match(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$", line))


def _cells(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _render_list(lines, i):
    base = len(lines[i]) - len(lines[i].lstrip())
    first = re.match(r"^\s*([-*+]|\d+[.)])\s+(.*)$", lines[i])
    ordered = first.group(1)[0].isdigit()
    tag = "ol" if ordered else "ul"
    items = []
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            if i + 1 < len(lines) and lines[i + 1].strip():
                nxt_indent = len(lines[i + 1]) - len(lines[i + 1].lstrip())
                if nxt_indent > base or (nxt_indent == base and re.match(r"^\s*([-*+]|\d+[.)])\s+", lines[i + 1])):
                    if items:
                        items[-1][1].append("")
                    i += 1
                    continue
            break
        indent = len(ln) - len(ln.lstrip())
        m = re.match(r"^\s*([-*+]|\d+[.)])\s+(.*)$", ln)
        if m and indent == base and m.group(1)[0].isdigit() != ordered:
            break  # otra lista distinta: empieza después
        if m and indent == base:
            items.append([m.group(2), []])
        elif indent > base and items:
            items[-1][1].append(ln[base + 2:] if len(ln) > base + 2 else ln.lstrip())
        elif items and indent == base and not _is_block_start(ln):
            items[-1][0] += " " + ln.strip()  # continuación perezosa
        else:
            break
        i += 1
    out = [f"<{tag}>"]
    for text, sub in items:
        body = _inline(text)
        if sub and any(x.strip() for x in sub):
            body += render_blocks(sub)
        out.append(f"<li>{body}</li>")
    out.append(f"</{tag}>")
    return "".join(out), i


def render_blocks(lines):
    out, i, n = [], 0, len(lines)
    while i < n:
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        fence = re.match(r"^\s*(```+|~~~+)\s*([\w+.-]*)", ln)
        if fence:
            marker, code = fence.group(1), []
            i += 1
            while i < n and not lines[i].strip().startswith(marker):
                code.append(lines[i])
                i += 1
            i += 1
            cls = f' class="language-{html.escape(fence.group(2), quote=True)}"' if fence.group(2) else ""
            out.append(f"<pre><code{cls}>{html.escape(chr(10).join(code), quote=True)}</code></pre>")
            continue
        h = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", ln)
        if h:
            lvl = _heading_level(len(h.group(1)))
            out.append(f"<h{lvl}>{_inline(h.group(2))}</h{lvl}>")
            i += 1
            continue
        if re.match(r"^\s*(\*\s*){3,}$|^\s*(-\s*){3,}$|^\s*(_\s*){3,}$", ln):
            out.append("<hr>")
            i += 1
            continue
        if re.match(r"^\s*>", ln):
            quote = []
            while i < n and re.match(r"^\s*>", lines[i]):
                quote.append(re.sub(r"^\s*> ?", "", lines[i]))
                i += 1
            out.append(f"<blockquote>{render_blocks(quote)}</blockquote>")
            continue
        if re.match(r"^\s*([-*+]|\d+[.)])\s+", ln):
            html_list, i = _render_list(lines, i)
            out.append(html_list)
            continue
        if "|" in ln and i + 1 < n and _table_sep(lines[i + 1]):
            head = _cells(ln)
            aligns = []
            for c in _cells(lines[i + 1]):
                aligns.append("right" if c.endswith(":") and not c.startswith(":") else "center" if c.startswith(":") and c.endswith(":") else "")
            i += 2
            rows = []
            while i < n and lines[i].strip() and "|" in lines[i]:
                rows.append(_cells(lines[i]))
                i += 1
            def cell(tag, c, k):
                al = f' style="text-align:{aligns[k]}"' if k < len(aligns) and aligns[k] else ""
                return f"<{tag}{al}>{_inline(c)}</{tag}>"
            body = "".join("<tr>" + "".join(cell("td", c, k) for k, c in enumerate(r)) + "</tr>" for r in rows)
            out.append("<table><thead><tr>" + "".join(cell("th", c, k) for k, c in enumerate(head))
                       + "</tr></thead><tbody>" + body + "</tbody></table>")
            continue
        if _HTML_TAG_START.match(ln):
            raw = []
            while i < n and lines[i].strip():
                raw.append(lines[i])
                i += 1
            out.append("\n".join(raw))
            continue
        para = []
        while i < n and lines[i].strip() and not (para and _is_block_start(lines[i])):
            para.append(lines[i])
            i += 1
        if para:
            parts = []
            for k, pl in enumerate(para):
                hard = pl.endswith("  ") or pl.endswith("\\")
                txt = _inline(pl.strip().rstrip("\\"))
                parts.append(txt + ("<br>" if hard and k < len(para) - 1 else ""))
            out.append("<p>" + " ".join(parts) + "</p>")
    return "\n".join(out)


def render_markdown(text):
    return render_blocks((text or "").replace("\r\n", "\n").replace("\t", "    ")[:120000].split("\n"))


def md_to_html(text):
    """Markdown de Modrinth/CurseForge a HTML seguro (el HTML crudo también pasa por el filtro)."""
    out = sanitize_html(render_markdown(text))
    # párrafos vacíos (espaciadores habituales en Modrinth): fuera, o dejan huecos enormes
    return re.sub(r"<p>(?:\s|&nbsp;|\xa0|<br>)*</p>", "", out)


class _SafeHTML(HTMLParser):
    """Filtro de lista blanca para la descripción HTML que devuelve CurseForge."""
    ALLOWED = {"p", "br", "strong", "b", "em", "i", "u", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5",
               "code", "pre", "blockquote", "a", "img", "hr", "span", "div", "center", "table", "tr", "td", "th", "thead", "tbody",
               "details", "summary", "kbd", "sub", "sup", "small", "del", "s", "mark"}
    VOID = {"br", "hr", "img"}
    KEEP_ATTR = {"code": ("class",), "pre": ("class",), "th": ("style",), "td": ("style",)}
    DROP = {"script", "style", "iframe", "object", "embed", "svg", "form", "input", "button", "video", "audio", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.stack, self.drop = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.DROP:
            self.drop += 1
            return
        if self.drop or tag not in self.ALLOWED:
            return
        a = dict(attrs)
        if tag == "a":
            href = _safe_href(a.get("href"))
            if not href:
                self.out.append("<span>"); self.stack.append("span"); return
            self.out.append(f'<a href="{html.escape(href, quote=True)}" target="_blank" rel="noopener nofollow">')
            self.stack.append("a")
        elif tag == "img":
            src = _safe_href(a.get("src"))
            if src:
                self.out.append(f'<img src="{html.escape(src, quote=True)}" alt="{html.escape(a.get("alt") or "", quote=True)}" loading="lazy">')
        elif tag in self.VOID:
            self.out.append(f"<{tag}>")
        else:
            extra = ""
            for k in self.KEEP_ATTR.get(tag, ()):
                v = a.get(k) or ""
                if k == "class" and re.fullmatch(r"language-[A-Za-z0-9+.#-]{1,30}", v):
                    extra += f' class="{v}"'
                if k == "style" and re.fullmatch(r"text-align:\s*(left|right|center)", v):
                    extra += f' style="{v}"'
            self.out.append(f"<{tag}{extra}>")
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.DROP:
            self.drop = max(0, self.drop - 1)
            return
        if self.drop or tag not in self.stack:
            return
        while self.stack:  # cierra lo que quedó abierto dentro de este elemento
            t = self.stack.pop()
            self.out.append(f"</{t}>")
            if t == tag:
                break

    def handle_data(self, data):
        if not self.drop:
            self.out.append(html.escape(data, quote=True))

    def close_all(self):
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")


def sanitize_html(raw):
    p = _SafeHTML()
    p.feed((raw or "")[:120000])
    p.close()
    p.close_all()
    return "".join(p.out)


def _body_to_html(body):
    """Descripción de Modrinth/CurseForge: markdown (con HTML embebido) renderizado y filtrado."""
    return md_to_html(body or "")


def _mr_members(pid):
    return [m["user"]["username"] for m in _mr(f"/project/{urllib.parse.quote(pid)}/members") if m.get("user")]


def mod_detail(source, ident, loader="neoforge", version="1.21.1"):
    if source == "modrinth":
        pid = urllib.parse.quote(str(ident), safe="")
        p = _mr(f"/project/{pid}")
        try:
            authors = _mr_members(pid)
        except (urllib.error.URLError, KeyError):
            authors = []
        vs = _mr(f"/project/{pid}/version?" + urllib.parse.urlencode({
            "loaders": json.dumps([loader]), "game_versions": json.dumps([version])}))
        return {
            "source": "modrinth", "id": p["id"], "slug": p["slug"], "name": p["title"], "summary": p["description"],
            "icon": p.get("icon_url"), "downloads": p.get("downloads", 0), "followers": p.get("followers", 0),
            "published": p.get("published"), "updated": p.get("updated"),
            "license": (p.get("license") or {}).get("id"), "categories": p.get("categories", []),
            "client": p.get("client_side"), "server": p.get("server_side"),
            "loaders": p.get("loaders", []), "game_versions": (p.get("game_versions") or [])[-8:],
            "authors": authors,
            "links": {"source": _safe_href(p.get("source_url")), "issues": _safe_href(p.get("issues_url")),
                      "wiki": _safe_href(p.get("wiki_url")), "discord": _safe_href(p.get("discord_url")),
                      "page": f"https://modrinth.com/mod/{p['slug']}"},
            "gallery": [{"url": g["url"], "title": g.get("title") or ""} for g in p.get("gallery", [])[:12]
                        if _safe_href(g.get("url"))],
            "body_html": _body_to_html(p.get("body") or ""),
            "files": mod_files("modrinth", p["id"], p["slug"], loader, version, "mod")[:8],
        }
    if source == "curseforge":
        key = load_cf_key()
        if not key:
            raise RuntimeError("falta la API key de CurseForge")
        hdr = {"x-api-key": key}
        m = http_json(f"https://api.curseforge.com/v1/mods/{int(ident)}", headers=hdr)["data"]
        try:
            desc = http_json(f"https://api.curseforge.com/v1/mods/{int(ident)}/description", headers=hdr)["data"]
        except urllib.error.URLError:
            desc = ""
        links = m.get("links") or {}
        cats = [c["name"] for c in m.get("categories", [])]
        return {
            "source": "curseforge", "id": str(m["id"]), "slug": m["slug"], "name": m["name"], "summary": m["summary"],
            "icon": (m.get("logo") or {}).get("url"), "downloads": m.get("downloadCount", 0), "followers": None,
            "published": m.get("dateCreated"), "updated": m.get("dateModified"), "license": None, "categories": cats,
            "client": None, "server": None, "loaders": [], "game_versions": [],
            "authors": [a["name"] for a in m.get("authors", [])],
            "links": {"source": _safe_href(links.get("sourceUrl")), "issues": _safe_href(links.get("issuesUrl")),
                      "wiki": _safe_href(links.get("wikiUrl")), "discord": None,
                      "page": _safe_href(links.get("websiteUrl")) or f"https://www.curseforge.com/minecraft/mc-mods/{m['slug']}"},
            "gallery": [{"url": s["url"], "title": s.get("title") or ""} for s in m.get("screenshots", [])[:12]
                        if _safe_href(s.get("url"))],
            "body_html": sanitize_html(desc),
            "files": mod_files("curseforge", str(m["id"]), m["slug"], loader, version, "mod")[:8],
        }
    raise ValueError("fuente no válida")


# ---------- dependencias de los mods ----------

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


def _mr(path):
    return http_json("https://api.modrinth.com/v2" + path)


def _resolve_mr(version_obj, installed, loader, version, via, out, warnings, seen):
    for d in version_obj.get("dependencies", []):
        pid = d.get("project_id") or (_mr(f"/version/{d['version_id']}")["project_id"] if d.get("version_id") else None)
        if not pid:
            continue
        kind = d.get("dependency_type")
        if kind == "incompatible":
            if ("modrinth", pid) in installed:
                try:
                    shown = _mr(f"/project/{pid}")["title"]
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
            proj = _mr(f"/project/{pid}")
            if ("slug", proj["slug"].lower()) in installed:
                continue
            if d.get("version_id"):
                v = _mr(f"/version/{d['version_id']}")
            else:
                vs = _mr(f"/project/{pid}/version?" + urllib.parse.urlencode(
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
        v = _mr(f"/version/{urllib.parse.quote(str(vid), safe='')}")
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


# ---------- identificación de mods por proveedor ----------

HASH_CACHE = {}  # (ruta, tamaño, mtime) -> {"sha1": ..., "cf": ...}


def http_post_json(url, body, headers=None):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "User-Agent": UA, "Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


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


# ---------- cliente compatible con el servidor ----------

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


# ---------- preset de rendimiento para el cliente (solo lado cliente, no cambia el servidor) ----------

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
    proj = _mr(f"/project/{slug}")
    vs = _mr(f"/project/{slug}/version?" + urllib.parse.urlencode({
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
            pid = d.get("project_id") or _mr(f"/version/{d['version_id']}")["project_id"]
            dep_slug = _mr(f"/project/{pid}")["slug"]
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


# ---------- datapacks ----------

def world_dir(name):
    p = server_path(name)
    level = "world"
    props = p / "server.properties"
    if props.exists():
        for line in props.read_text(errors="replace").splitlines():
            if line.startswith("level-name="):
                level = line.split("=", 1)[1].strip() or "world"
    w = (p / level).resolve()
    if w.parent != p.resolve():
        raise ValueError("level-name no válido en server.properties")
    return w


def datapacks_dir(name, create=False):
    d = world_dir(name) / "datapacks"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def list_datapacks(name):
    d = datapacks_dir(name)
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.iterdir(), key=lambda x: x.name.lower()):
        if f.is_file() and f.suffix == ".zip":
            out.append({"file": f.name, "kind": "zip", "size": f.stat().st_size})
        elif f.is_dir():
            out.append({"file": f.name, "kind": "carpeta", "size": None})
    return out


def finish_datapack(name, tmp, fname):
    if not zipfile.is_zipfile(tmp):
        tmp.unlink(missing_ok=True)
        raise ValueError("el archivo no es un zip válido")
    with zipfile.ZipFile(tmp) as z:
        if "pack.mcmeta" not in z.namelist():
            tmp.unlink(missing_ok=True)
            raise ValueError("no parece un datapack: falta pack.mcmeta en la raíz del zip")
    tmp.replace(datapacks_dir(name, create=True) / fname)


def delete_datapack(name, fname):
    fname = release.safe_zip_name(fname)
    p = datapacks_dir(name) / fname
    if not p.is_file():
        raise FileNotFoundError("datapack no encontrado")
    p.unlink()


# ---------- server.properties y pack de texturas del servidor ----------

# ---------- server.properties (opciones principales) ----------

PROP_SPECS = {
    "motd": ("text", 59), "server-port": ("int", 1024, 65535), "max-players": ("int", 1, 1000),
    "online-mode": ("bool",), "white-list": ("bool",), "enforce-whitelist": ("bool",),
    "difficulty": ("enum", "peaceful", "easy", "normal", "hard"),
    "gamemode": ("enum", "survival", "creative", "adventure", "spectator"),
    "force-gamemode": ("bool",), "pvp": ("bool",), "hardcore": ("bool",), "allow-flight": ("bool",),
    "allow-nether": ("bool",), "spawn-monsters": ("bool",), "spawn-animals": ("bool",),
    "spawn-npcs": ("bool",), "enable-command-block": ("bool",),
    "view-distance": ("int", 3, 32), "simulation-distance": ("int", 3, 32), "spawn-protection": ("int", 0, 1000),
    "level-name": ("name",), "level-seed": ("text", 40),
}


def properties_view(name):
    cur = read_properties(name)
    out = {}
    for k, spec in PROP_SPECS.items():
        out[k] = cur.get(k, "")
    return {"values": out, "running": status(name)["running"]}


def set_properties(name, updates):
    """Valida y escribe solo las claves de PROP_SPECS; el resto del archivo no se toca."""
    if not isinstance(updates, dict) or not updates:
        raise ValueError("nada que guardar")
    clean = {}
    for k, v in updates.items():
        if k not in PROP_SPECS:
            raise ValueError(f"«{k}» no es una opción editable desde el panel")
        spec = PROP_SPECS[k]
        sv = "true" if v is True else "false" if v is False else str(v).strip()
        if spec[0] == "bool":
            if sv not in ("true", "false"):
                raise ValueError(f"{k} debe ser sí o no")
        elif spec[0] == "int":
            if not re.fullmatch(r"-?\d{1,5}", sv) or not spec[1] <= int(sv) <= spec[2]:
                raise ValueError(f"{k} debe estar entre {spec[1]} y {spec[2]}")
        elif spec[0] == "enum":
            if sv not in spec[1:]:
                raise ValueError(f"{k} no es una opción válida")
        elif spec[0] == "name":
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", sv):
                raise ValueError("el nombre del mundo solo admite letras, números, puntos, guiones y guiones bajos")
        else:
            if len(sv) > spec[1] or re.search(r"[\x00-\x1f\x7f]", sv):
                raise ValueError(f"{k}: texto no válido (máximo {spec[1]} caracteres, sin saltos de línea)")
        clean[k] = sv
    if "server-port" in clean:
        others = used_ports() - {int(read_properties(name).get("server-port", 0) or 0)}
        if int(clean["server-port"]) in others:
            raise ValueError(f"el puerto {clean['server-port']} ya lo usa otro servidor")
    write_properties(name, clean)
    return clean


def delete_server(name):
    """Borra la carpeta del servidor y su registro. Solo se permite fuera del gestor y si está parado."""
    p = server_path(name)
    if status(name)["running"]:
        raise RuntimeError("para el servidor antes de borrarlo")
    if p == HERE or not str(p).startswith(str(SERVERS_DIR) + "/"):
        raise ValueError("ruta no permitida")
    with LOCK:
        PROCS.pop(name, None)
    if release.SHARE and release.SHARE.get("server") == name:
        release.stop_share()
    shutil.rmtree(p)
    shutil.rmtree(release.RELEASES / name, ignore_errors=True)
    db.delete_server_records(name)


def read_properties(name):
    f = server_path(name) / "server.properties"
    out = {}
    if f.exists():
        for line in f.read_text(errors="replace").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.replace("\\:", ":").replace("\\=", "=")
    return out


def write_properties(name, updates):
    f = server_path(name) / "server.properties"
    lines = f.read_text(errors="replace").splitlines() if f.exists() else []
    seen, out = set(), []
    for line in lines:
        k = line.split("=", 1)[0].strip() if ("=" in line and not line.lstrip().startswith("#")) else None
        if k in updates:
            out.append(f"{k}={updates[k]}")
            seen.add(k)
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in updates.items() if k not in seen]
    f.write_text("\n".join(out) + "\n")


def get_resourcepack(name):
    p = read_properties(name)
    prompt = p.get("resource-pack-prompt", "")
    try:
        j = json.loads(prompt)
        prompt = j.get("text", "") if isinstance(j, dict) else prompt
    except ValueError:
        pass
    return {"url": p.get("resource-pack", ""), "sha1": p.get("resource-pack-sha1", ""),
            "required": p.get("require-resource-pack", "false") == "true", "prompt": prompt}


def set_resourcepack(name, url, sha1, required, prompt):
    url, sha1, prompt = (url or "").strip(), (sha1 or "").strip().lower(), (prompt or "").strip()
    if url and not re.fullmatch(r"https?://[^\s\\]{4,480}", url):
        raise ValueError("la URL del pack no es válida")
    if sha1 and not re.fullmatch(r"[0-9a-f]{40}", sha1):
        raise ValueError("el SHA-1 debe tener 40 caracteres hexadecimales")
    if len(prompt) > 200 or re.search(r"[\x00-\x1f\x7f\\]", prompt):
        raise ValueError("el mensaje no es válido (máximo 200 caracteres, sin saltos de línea)")
    write_properties(name, {
        "resource-pack": url, "resource-pack-sha1": sha1 if url else "",
        "require-resource-pack": "true" if (required and url) else "false",
        "resource-pack-prompt": json.dumps({"text": prompt}, ensure_ascii=False) if (prompt and url) else ""})


def packs_dir(name):
    d = (HERE / "packs" / name).resolve()
    if d.parent != (HERE / "packs").resolve():
        raise ValueError("servidor no válido")
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_local_packs(name):
    d = packs_dir(name)
    out = []
    for row in db.packs_for(name):
        f = d / row["filename"]
        if f.is_file():
            out.append({"file": row["filename"], "size": f.stat().st_size, "sha1": row["sha1"], "token": row["token"]})
    return out


def finish_pack_upload(name, tmp, fname):
    if not zipfile.is_zipfile(tmp) or "pack.mcmeta" not in zipfile.ZipFile(tmp).namelist():
        tmp.unlink(missing_ok=True)
        raise ValueError("no parece un pack de texturas: falta pack.mcmeta en la raíz del zip")
    sha1 = hashlib.sha1(tmp.read_bytes()).hexdigest()
    tmp.replace(packs_dir(name) / fname)
    db.pack_add(name, fname, sha1)
    return sha1


def delete_local_pack(name, fname):
    fname = release.safe_zip_name(fname)
    p = packs_dir(name) / fname
    if not p.is_file():
        raise FileNotFoundError("pack no encontrado")
    row = next((r for r in db.packs_for(name) if r["filename"] == fname), None)
    p.unlink()
    db.pack_delete(name, fname)
    # Si el servidor lo estaba pidiendo a los jugadores, se quita para no apuntar a un archivo borrado.
    if row and row["token"] in get_resourcepack(name)["url"]:
        set_resourcepack(name, "", "", False, "")


def use_local_pack(name, fname, base_url, required, prompt):
    fname = release.safe_zip_name(fname)
    row = next((r for r in db.packs_for(name) if r["filename"] == fname), None)
    if not row:
        raise FileNotFoundError("pack no encontrado")
    base = (base_url or "").strip().rstrip("/")
    if not re.fullmatch(r"https?://[A-Za-z0-9.\-]+(:\d{1,5})?", base):
        raise ValueError("la dirección pública debe ser como http://192.168.10.18:8765")
    set_resourcepack(name, f"{base}/packs/{row['token']}/{urllib.parse.quote(fname)}", row["sha1"], required, prompt)


# ---------- jugadores ----------

PLAYER_RE = re.compile(r"[A-Za-z0-9_.]{1,20}")
PLAYER_ACTIONS = {"tell", "say", "kick", "ban", "pardon", "op", "deop", "whitelist_add", "whitelist_remove"}


def _json_list(path):
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _query_online(name, wait=2.5):
    """Envía `list` a la consola y lee la respuesta del log. Solo si el gestor controla el proceso."""
    p = server_path(name)
    lf = p / "logs" / "latest.log"
    size = lf.stat().st_size if lf.exists() else 0
    send_command(name, "list")
    rx = re.compile(r"There are (\d+) of a max of (\d+) players online:\s*(.*)$", re.M)
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(0.25)
        if lf.exists() and lf.stat().st_size > size:
            with open(lf, "rb") as fh:
                fh.seek(size)
                m = rx.search(fh.read().decode("utf-8", "replace"))
            if m:
                return [n.strip() for n in m.group(3).split(",") if n.strip()], int(m.group(2))
    return None, None


def players_info(name):
    p = server_path(name)
    st = status(name)
    known = {e["name"] for e in _json_list(p / "usercache.json") if isinstance(e, dict) and e.get("name")}
    ops = {e["name"] for e in _json_list(p / "ops.json") if isinstance(e, dict) and e.get("name")}
    bans = {e["name"]: e for e in _json_list(p / "banned-players.json") if isinstance(e, dict) and e.get("name")}
    wl = {e["name"] for e in _json_list(p / "whitelist.json") if isinstance(e, dict) and e.get("name")}
    online, max_players = (None, None)
    if st["running"] and st["control"]:
        online, max_players = _query_online(name)
    names = sorted(known | ops | wl | set(bans) | set(online or []), key=str.lower)
    return {
        "running": st["running"], "control": st["control"], "max": max_players,
        "online_count": len(online) if online is not None else None,
        "whitelist_enabled": read_properties(name).get("white-list") == "true",
        "players": [{"name": n, "online": (n in online) if online is not None else None, "op": n in ops,
                     "banned": n in bans, "ban_reason": (bans.get(n) or {}).get("reason"),
                     "whitelisted": n in wl} for n in names]}


def player_action(name, action, player=None, text=""):
    if action not in PLAYER_ACTIONS:
        raise ValueError("acción no válida")
    text = (text or "").strip()
    if len(text) > 200 or re.search(r"[\x00-\x1f\x7f]", text):
        raise ValueError("el texto no es válido (máximo 200 caracteres, sin saltos de línea)")
    if action != "say" and not PLAYER_RE.fullmatch(player or ""):
        raise ValueError("nombre de jugador no válido")
    if action in ("say", "tell") and not text:
        raise ValueError("escribe un mensaje")
    cmd = {"say": f"say {text}", "tell": f"tell {player} {text}", "kick": f"kick {player} {text}".strip(),
           "ban": f"ban {player} {text}".strip(), "pardon": f"pardon {player}", "op": f"op {player}",
           "deop": f"deop {player}", "whitelist_add": f"whitelist add {player}",
           "whitelist_remove": f"whitelist remove {player}"}[action]
    send_command(name, cmd)
    return cmd


# ---------- vista de servidores según permisos ----------

def _server_icon(saved, dest):
    """Icono de un servidor: el elegido si es de la lista; si no, el de su plantilla."""
    if saved in db.ICONS:
        return saved
    tpl = templates.server_template(dest)
    return tpl if tpl in db.ICONS else "vanilla"


def visible_servers(user):
    servers = list_servers()
    db.sync_servers([s["name"] for s in servers])
    meta = db.server_meta()
    perms = None if user["is_admin"] else db.user_perms(user["id"])
    out = []
    for s in servers:
        if user["is_admin"]:
            p = {k: True for k in db.PERMS}
        else:
            p = perms.get(s["name"])
            if not p:
                continue
        m = meta.get(s["name"], {})
        item = {"name": s["name"], "parent": s.get("parent"), "display_name": m.get("display_name") or s["name"],
                "icon": _server_icon(m.get("icon"), server_path(s["name"])),
                "mods": s["mods"], "permissions": p,
                "template": templates.server_template(server_path(s["name"])),
                "template_label": templates.TEMPLATES.get(templates.server_template(server_path(s["name"])), {}).get("label", ""),
                "kind": templates.kind_of(templates.server_template(server_path(s["name"]))),
                "status": s["status"] if user["is_admin"] else {"running": s["status"]["running"]}}
        if user["is_admin"]:
            item["memory"] = s["memory"]
        out.append(item)
    return out


# ---------- crear servidores desde plantilla ----------

def used_ports():
    out = set()
    for d in SERVERS_DIR.iterdir():
        f = d / "server.properties"
        if d.is_dir() and f.exists():
            for line in f.read_text(errors="replace").splitlines():
                if line.startswith("server-port="):
                    try:
                        out.add(int(line.split("=", 1)[1]))
                    except ValueError:
                        pass
    return out


def create_server(user, b):
    name = str(b.get("name", "")).strip()
    if not NAME_RE.fullmatch(name) or len(name) > 40:
        raise ValueError("nombre no válido (letras, números, puntos, guiones y guiones bajos; máximo 40)")
    if (SERVERS_DIR / name).exists():
        raise ValueError("ya existe una carpeta con ese nombre")
    template = b.get("template", "")
    if template not in templates.TEMPLATES:
        raise ValueError("plantilla no válida")
    mc = str(b.get("mc", ""))
    if mc not in templates.versions(template):
        raise ValueError(f"{templates.TEMPLATES[template]['label']} no tiene la versión {mc}")
    if b.get("accept_eula") is not True:
        raise ValueError("debes aceptar el EULA de Minecraft para crear el servidor")
    memory = str(b.get("memory") or "4G")
    if not MEM_RE.fullmatch(memory):
        raise ValueError("memoria no válida (ej. 4G o 4096M)")
    used = used_ports()
    if b.get("port") in (None, "", 0):
        port = next(p for p in range(25565, 25700) if p not in used)
    else:
        port = int(b["port"])
        if not 1024 <= port <= 65535:
            raise ValueError("el puerto debe estar entre 1024 y 65535")
        if port in used:
            raise ValueError(f"el puerto {port} ya lo usa otro servidor")
    display = str(b.get("display_name") or "").strip()[:40]
    loader_version = b.get("loader_version") or None
    if loader_version is not None and not re.fullmatch(r"[0-9A-Za-z._+-]{1,40}", str(loader_version)):
        raise ValueError("versión del loader no válida")
    wanted = extras.validate(b.get("extras"), templates.loader_of(template) or template)   # Vanilla no tiene cargador

    def on_done(n):
        db.sync_servers([n])
        db.audit(user, n, "crear servidor", f"{template} {mc}")
        extras.run(_plugin_ctx(), n, wanted, user)
        plugins.emit("server_created", n)

    perf = b.get("perf", True) is not False
    job = templates.start_job(SERVERS_DIR, name, template, mc, memory, port, display,
                              str(loader_version) if loader_version else None, on_done, perf=perf)
    db.audit(user, name, "iniciar creación", f"{template} {mc} · puerto {port} · {memory}")
    return job


def create_modpack_server(user, b):
    name = str(b.get("name", "")).strip()
    if not NAME_RE.fullmatch(name) or len(name) > 40:
        raise ValueError("nombre no válido (letras, números, puntos, guiones y guiones bajos; máximo 40)")
    if (SERVERS_DIR / name).exists():
        raise ValueError("ya existe una carpeta con ese nombre")
    source = b.get("source", "")
    if source not in ("modrinth", "curseforge"):
        raise ValueError("fuente no válida")
    project = str(b.get("project", ""))
    version_id = str(b.get("version", ""))
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", project) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", version_id):
        raise ValueError("modpack o versión no válidos")
    if b.get("accept_eula") is not True:
        raise ValueError("debes aceptar el EULA de Minecraft para crear el servidor")
    memory = str(b.get("memory") or "6G")
    if not MEM_RE.fullmatch(memory):
        raise ValueError("memoria no válida (ej. 6G o 6144M)")
    used = used_ports()
    if b.get("port") in (None, "", 0):
        port = next(p for p in range(25565, 25700) if p not in used)
    else:
        port = int(b["port"])
        if not 1024 <= port <= 65535:
            raise ValueError("el puerto debe estar entre 1024 y 65535")
        if port in used:
            raise ValueError(f"el puerto {port} ya lo usa otro servidor")
    display = str(b.get("display_name") or "").strip()[:40]
    wanted = extras.validate(b.get("extras"))   # el cargador de un modpack se sabe al instalarlo: si no encaja, se omite

    def on_done(n):
        db.sync_servers([n])
        db.audit(user, n, "crear servidor desde modpack", f"{source}:{project}:{version_id}")
        extras.run(_plugin_ctx(), n, wanted, user)
        plugins.emit("server_created", n)

    job = modpacks.start_job(SERVERS_DIR, name, source, project, version_id, memory, port, display,
                             bool(b.get("include_client", True)), on_done)
    db.audit(user, name, "iniciar creación desde modpack", f"{source}:{project} · puerto {port} · {memory}")
    return job


# ---------- HTTP ----------

ASSETS = {"style.css": "text/css; charset=utf-8", "app.js": "text/javascript; charset=utf-8",
          "icons.js": "text/javascript; charset=utf-8", "theme.js": "text/javascript; charset=utf-8",
          "fonts/Inter.ttf": "font/ttf",
          "brand/modnex-mark.png": "image/png", "brand/modnex-logo.png": "image/png",
          **{f"brand/servers/{n}.png": "image/png" for n in db.ICONS}}
CSP = ("default-src 'self'; img-src 'self' data: https:; style-src 'self'; script-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
MAX_DATAPACK = 256 * 1024 * 1024
MAX_RELEASE = 2 * 1024 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    server_version = "CobblemonManager/2.0"

    def log_message(self, *args):
        pass

    # --- utilidades ---
    def _send(self, code, payload, ctype="application/json; charset=utf-8", headers=None):
        data = json.dumps(payload).encode() if ctype.startswith("application/json") else payload
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy", CSP)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 1_000_000:
            raise ValueError("cuerpo demasiado grande")
        return json.loads(self.rfile.read(n) or b"{}")

    def _peer_loopback(self):
        return self.client_address[0] in ("127.0.0.1", "::1")

    def _client_ip(self):
        """IP real del cliente. Las cabeceras de un túnel solo se creen si la conexión llega desde esta
        misma máquina (el túnel conecta por loopback); desde la red local se ignoran, así no se pueden falsificar."""
        if self._peer_loopback():
            for h in ("Cf-Connecting-Ip", "X-Forwarded-For"):
                v = (self.headers.get(h) or "").split(",")[0].strip()
                if v:
                    return v[:64]
        return self.client_address[0]

    def _via_tunnel(self):
        return self._peer_loopback() and bool(self.headers.get("Cf-Connecting-Ip") or self.headers.get("X-Forwarded-For"))

    PRIVATE_SUFFIXES = (".local", ".lan", ".home", ".internal", ".localdomain", ".home.arpa")

    @staticmethod
    def _is_local_ip(value):
        """Local = no enrutable por internet (loopback, red local, ZeroTier, Tailscale, enlace local)."""
        try:
            ip = ipaddress.ip_address(str(value).strip())
        except ValueError:
            return False
        ip = getattr(ip, "ipv4_mapped", None) or ip
        return not ip.is_global

    def _host_is_public_name(self):
        """True si el Host de la petición es un nombre de dominio público (p. ej. el de un túnel)."""
        h = (self.headers.get("Host") or "").strip().lower()
        if h.startswith("["):
            return False                      # IPv6 literal
        h = h.rsplit(":", 1)[0] if h.count(":") == 1 else h
        try:
            ipaddress.ip_address(h)
            return False                      # IP literal: se juzga por la IP
        except ValueError:
            pass
        return "." in h and not h.endswith(self.PRIVATE_SUFFIXES)

    def _remote_origin(self):
        """True si la petición llega desde fuera de este equipo y de la red local.
        Se considera remota si pasa por un túnel (cabeceras de reenvío desde loopback), si la conexión viene
        de una IP enrutable, o si llega por loopback pero con un nombre de dominio público en `Host`."""
        if self._via_tunnel():
            return True
        peer = self.client_address[0]
        if not self._is_local_ip(peer):
            return True
        return self._peer_loopback() and self._host_is_public_name()

    def _admin_remote_blocked(self, user):
        """Los administradores solo entran desde el equipo o la red local, salvo `admin_remote: true` en config.json."""
        return bool(user and user.get("is_admin") and self._remote_origin() and load_config().get("admin_remote") is not True)

    def _https(self):
        return self._peer_loopback() and (self.headers.get("X-Forwarded-Proto") or "").lower() == "https"

    def _same_origin(self):
        origin = self.headers.get("Origin")
        return origin is None or urllib.parse.urlparse(origin).netloc == self.headers.get("Host", "")

    def _cookie(self):
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return urllib.parse.unquote(v)
        return None

    def _cookie_header(self, token, max_age):
        secure = "; Secure" if self._https() else ""
        return {"Set-Cookie": f"{COOKIE}={urllib.parse.quote(token)}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}{secure}"}

    def _serve_pack(self, token, fname):
        row = db.pack_lookup(token, fname)
        f = packs_dir(row["server_name"]) / row["filename"] if row else None
        if not row or not f.is_file():
            return self._send(404, {"error": "no encontrado"})
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(f.stat().st_size))
        self.send_header("Content-Disposition", f'attachment; filename="{row["filename"]}"')
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            with open(f, "rb") as fh:
                while chunk := fh.read(1 << 20):
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _save_upload(self, dest_dir, limit, namer=release.safe_zip_name):
        fname = namer(self.headers.get("X-Filename", ""))
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > limit:
            raise ValueError(f"tamaño no válido (máximo {limit // (1 << 20)} MB)")
        tmp = dest_dir / (fname + ".part")
        remaining = n
        with open(tmp, "wb") as fh:
            while remaining > 0:
                chunk = self.rfile.read(min(1 << 20, remaining))
                if not chunk:
                    break
                fh.write(chunk)
                remaining -= len(chunk)
        if remaining:
            tmp.unlink(missing_ok=True)
            raise ValueError("subida incompleta")
        return tmp, fname

    @staticmethod
    def _need(user, server, perm):
        if not db.can(user, server, perm):
            raise PermissionError("no tienes permiso para esto")

    @staticmethod
    def _need_admin(user):
        if not user["is_admin"]:
            raise PermissionError("solo administradores")

    # --- enrutado ---
    def _route(self, method):
        if not self._same_origin():
            return self._send(403, {"error": "origen no permitido"})
        u = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        path = u.path
        try:
            if method == "GET" and path == "/":
                # La landing pública es un sitio estático aparte (carpeta landing/). El gestor solo sirve el panel.
                return self._send(302, b"", "text/plain; charset=utf-8", headers={"Location": "/app"})
            if method == "GET" and path in ("/app", "/app/"):
                return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            m = re.fullmatch(r"/assets/([A-Za-z0-9_./-]+)", path)
            if method == "GET" and m and m.group(1) in ASSETS:
                return self._send(200, (STATIC / m.group(1)).read_bytes(), ASSETS[m.group(1)])

            mpl = re.fullmatch(r"/plugin/([A-Za-z0-9_.-]{1,60})", path)
            if method == "GET" and mpl:
                a = plugins.asset(mpl.group(1))
                if not a or not a[0].is_file():
                    return self._send(404, {"error": "no encontrado"})
                return self._send(200, a[0].read_bytes(), a[1])

            mp = re.fullmatch(r"/packs/([A-Za-z0-9_-]{10,40})/([^/]+)", path)
            if method == "GET" and mp:
                return self._serve_pack(mp.group(1), urllib.parse.unquote(mp.group(2)))

            if method == "POST" and path == "/api/waitlist":
                if not db.waitlist_rate_ok(self._client_ip()):
                    return self._send(429, {"error": "demasiados intentos; prueba más tarde"})
                try:
                    db.waitlist_add(self._body().get("email", ""))
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, {"ok": True})  # misma respuesta para correos nuevos y repetidos
            if method == "POST" and path == "/api/login":
                b = self._body()
                try:
                    user = db.authenticate(b.get("username", ""), b.get("password", ""), self._client_ip())
                except PermissionError as e:
                    return self._send(429, {"error": str(e)})
                if not user:
                    return self._send(401, {"error": "usuario o contraseña incorrectos"})
                if self._admin_remote_blocked(user):
                    # Misma respuesta que una contraseña errónea: desde fuera no se revela que la cuenta existe ni que es admin.
                    db.register_fail(self._client_ip())
                    db.audit(user, None, "acceso de administrador bloqueado", f"desde fuera de la red local ({self._client_ip()})")
                    return self._send(401, {"error": "usuario o contraseña incorrectos"})
                sf = plugins.second_factor(user, b, self._via_tunnel(), self._client_ip())
                if sf:
                    if len(sf) > 2 and sf[2]:
                        db.register_fail(self._client_ip())
                    return self._send(sf[0], sf[1])
                token = db.create_session(user["id"])
                db.audit(user, None, "login")
                return self._send(200, {"user": user}, headers=self._cookie_header(token, db.SESSION_TTL))
            if method == "POST" and path == "/api/logout":
                db.delete_session(self._cookie())
                return self._send(200, {"ok": True}, headers=self._cookie_header("", 0))

            user = db.user_for_token(self._cookie())
            if path.startswith("/api/") and not user:
                return self._send(401, {"error": "no autorizado"})
            if self._admin_remote_blocked(user):  # una sesión de administrador no sirve desde fuera, aunque se robe la cookie
                return self._send(403, {"error": "los administradores solo pueden usar el panel desde este equipo o la red local"})

            if method == "GET" and path == "/api/me":
                return self._send(200, {"user": user, "icons": db.ICONS})
            if method == "POST" and path == "/api/me/password":
                b = self._body()
                if not db.verify_password(user["id"], b.get("old", "")):
                    return self._send(400, {"error": "la contraseña actual no es correcta"})
                db.update_user(user["id"], password=b.get("new", ""))
                token = db.create_session(user["id"])  # update_user cerró las sesiones
                db.audit(user, None, "cambio de contraseña")
                return self._send(200, {"ok": True}, headers=self._cookie_header(token, db.SESSION_TTL))
            if method == "GET" and path == "/api/servers":
                return self._send(200, visible_servers(user))

            # búsqueda e instalación de mods
            if method == "GET" and path in ("/api/search", "/api/files"):
                kind = q.get("kind", "mod")
                if kind not in KINDS:
                    raise ValueError("tipo de contenido no válido")
                if not db.can_any(user, KINDS[kind]["perm"]):
                    raise PermissionError("no tienes permiso para buscar este contenido")
                loader, version = q.get("loader", "neoforge"), q.get("version", "1.21.1")
                sv = q.get("server")
                if sv:
                    self._need(user, sv, KINDS[kind]["perm"])
                    loader, kind = compat_for(sv, kind)
                    kind = kind if kind in KINDS else "mod"
                if path == "/api/search":
                    paged = "page" in q
                    res = search(q.get("source", "modrinth"), q.get("q", ""), loader, version, kind, q.get("sort", "auto"), q.get("side", "server"),
                                 int(q.get("page", 1) or 1), [t for t in q.get("tags", "").split(",") if t], paged)
                    return self._send(200, res)
                return self._send(200, mod_files(q["source"], q["project"], q.get("slug", ""), loader, version, kind))
            if method == "GET" and path == "/api/tags":
                kind = q.get("kind", "mod")
                if kind not in KINDS:
                    raise ValueError("tipo de contenido no válido")
                if not db.can_any(user, KINDS[kind]["perm"]):
                    raise PermissionError("no tienes permiso para este contenido")
                return self._send(200, category_tags(kind))
            if method == "GET" and path == "/api/templates":
                return self._send(200, [{"id": k, "label": v["label"], "kind": v["kind"], "desc": v["desc"], "loader": v["loader"],
                                         "perf": templates.perf_list(k)} for k, v in templates.TEMPLATES.items()])
            if method == "GET" and path == "/api/extras":
                return self._send(200, extras.listing())
            if method == "GET" and path == "/api/templates/versions":
                self._need_admin(user)
                return self._send(200, {"versions": templates.versions(q.get("template", ""))})
            if method == "GET" and path.startswith("/api/jobs/"):
                self._need_admin(user)
                st = templates.job_status(path.rsplit("/", 1)[1])
                if not st:
                    raise FileNotFoundError("trabajo no encontrado")
                return self._send(200, st)
            if method == "GET" and path == "/api/modpacks/search":
                self._need_admin(user)
                return self._send(200, modpacks.search(q.get("source", "modrinth"), q.get("q", ""), q.get("mc", "1.21.1")))
            if method == "GET" and path == "/api/modpacks/versions":
                self._need_admin(user)
                return self._send(200, modpacks.versions(q.get("source", "modrinth"), q["project"], q.get("mc", "1.21.1")))
            if method == "POST" and path == "/api/servers/create_modpack":
                self._need_admin(user)
                return self._send(200, {"job": create_modpack_server(user, self._body())})
            if method == "POST" and path == "/api/servers/create":
                self._need_admin(user)
                return self._send(200, {"job": create_server(user, self._body())})
            if method == "GET" and path == "/api/mod":
                if not db.can_any(user, "mods"):
                    raise PermissionError("no tienes permiso para ver fichas de mods")
                return self._send(200, mod_detail(q.get("source", "modrinth"), q["id"],
                                                  q.get("loader", "neoforge"), q.get("version", "1.21.1")))
            if method == "GET" and path == "/api/deps":
                self._need(user, q["server"], "mods")
                compat_for(q["server"], "mod")
                return self._send(200, resolve_deps(q["server"], q["source"], q["project"], q["vid"],
                                                    server_loader(q["server"]) or q.get("loader", "neoforge"),
                                                    q.get("version", "1.21.1")))
            if method == "POST" and path == "/api/install_many":
                b = self._body()
                self._need(user, b["server"], "mods")
                compat_for(b["server"], "mod")
                res = install_many(b["server"], b.get("items"))
                db.audit(user, b["server"], "instalar mods con dependencias", ", ".join(r["file"] for r in res if r["ok"])[:250])
                return self._send(200, {"results": res})
            if method == "POST" and path == "/api/install":
                b = self._body()
                kind = b.get("kind", "mod")
                if kind not in ("mod", "plugin", "datapack"):
                    raise ValueError("tipo no instalable")
                self._need(user, b["server"], KINDS[kind]["perm"])
                compat_for(b["server"], kind)  # lanza error si el tipo no encaja con el servidor
                fname = install(b["server"], b["url"], b["filename"], b.get("sha1"), kind)
                db.audit(user, b["server"], f"instalar {'datapack' if kind == 'datapack' else 'mod'}", fname)
                return self._send(200, {"installed": fname})

            # administración
            if path == "/api/users" or path.startswith("/api/users/") or path in ("/api/audit", "/api/share", "/api/share_stop", "/api/waitlist"):
                self._need_admin(user)
                if method == "GET" and path == "/api/users":
                    return self._send(200, db.list_users())
                if method == "POST" and path == "/api/users":
                    b = self._body()
                    uid = db.create_user(b.get("username", ""), b.get("password", ""), bool(b.get("is_admin")))
                    db.audit(user, None, "crear usuario", b.get("username"))
                    return self._send(200, {"id": uid})
                mu = re.fullmatch(r"/api/users/(\d+)/(update|delete|permissions)", path)
                if method == "POST" and mu:
                    uid, action = int(mu.group(1)), mu.group(2)
                    b = self._body()
                    target = db.get_user(uid)
                    if not target:
                        raise FileNotFoundError("usuario no encontrado")
                    if action == "update":
                        db.update_user(uid, password=b.get("password"), is_admin=b.get("is_admin"), active=b.get("active"))
                        db.audit(user, None, "editar usuario", target["username"])
                    elif action == "delete":
                        if uid == user["id"]:
                            raise ValueError("no puedes borrar tu propia cuenta")
                        db.delete_user(uid)
                        db.audit(user, None, "borrar usuario", target["username"])
                    elif "permissions" in b:  # guardado explícito de todos los permisos del usuario
                        perms = b["permissions"]
                        if not isinstance(perms, dict):
                            raise ValueError("permisos no válidos")
                        clean = {}
                        for srv, p in perms.items():
                            server_path(srv)
                            clean[srv] = {k: bool(p.get(k)) for k in db.PERMS}
                        db.set_all_permissions(uid, clean)
                        db.audit(user, None, "permisos", f"{target['username']}: " + ", ".join(
                            f"{s}[{'/'.join(k for k in db.PERMS if p[k]) or '-'}]" for s, p in clean.items()))
                    else:
                        server_path(b["server"])
                        db.set_permissions(uid, b["server"], {k: bool(b.get(k)) for k in db.PERMS})
                        db.audit(user, b["server"], "permisos", f"{target['username']}: {b}")
                    return self._send(200, {"ok": True})
                if method == "GET" and path == "/api/waitlist":
                    return self._send(200, [dict(r) for r in db.waitlist_list()])
                if method == "GET" and path == "/api/audit":
                    return self._send(200, db.recent_audit(int(q.get("limit", 100))))
                if method == "GET" and path == "/api/share":
                    return self._send(200, release.status())
                if method == "POST" and path == "/api/share_stop":
                    release.stop_share()
                    db.audit(user, None, "detener descarga pública")
                    return self._send(200, {"ok": True})

            if method == "GET" and path == "/api/plugins":
                return self._send(200, plugins.info())
            mg = re.fullmatch(r"/api/pro/([a-z0-9_]+)", path)
            if mg:
                gr = plugins.dispatch_global(method, user, mg.group(1), q, self._body)
                if gr is not None:
                    return self._send(gr[0], gr[1])

            # acciones por servidor
            ms = re.fullmatch(r"/api/servers/([^/]+)/([a-z_]+)", path)
            if ms:
                name, action = ms.groups()
                pr = plugins.dispatch(method, user, name, action, q, self._body)
                if pr is not None:
                    return self._send(pr[0], pr[1])
                if method == "GET":
                    if action == "metrics":
                        if not any(db.can(user, name, perm) for perm in db.PERMS):
                            raise PermissionError("no tienes permiso para esto")
                        return self._send(200, live_metrics(name))
                    if action == "installed":
                        self._need(user, name, "mods")
                        return self._send(200, installed_index(name, q.get("loader", "neoforge"), q.get("version", "1.21.1")))
                    if action == "log":
                        self._need(user, name, "logs")
                        return self._send(200, {"log": read_log(name, int(q.get("lines", 200)))})
                    if action == "mods":
                        self._need(user, name, "mods")
                        return self._send(200, identify_mods(name, q.get("loader", "neoforge"), q.get("version", "1.21.1")))
                    if action == "datapacks":
                        self._need(user, name, "datapacks")
                        return self._send(200, list_datapacks(name))
                    if action == "releases":
                        self._need_admin(user)
                        return self._send(200, release.list_releases(name))
                    if action == "properties":
                        self._need_admin(user)
                        server_path(name)
                        return self._send(200, properties_view(name))
                    if action == "client_plan":
                        self._need_admin(user)
                        return self._send(200, client_plan(name))
                    if action == "resourcepack":
                        self._need(user, name, "textures")
                        return self._send(200, {"current": get_resourcepack(name), "local": list_local_packs(name)})
                    if action == "players":
                        self._need(user, name, "players")
                        return self._send(200, players_info(name))
                if method == "POST":
                    # subidas en bruto (no JSON)
                    if action == "datapack_upload":
                        self._need(user, name, "datapacks")
                        tmp, fname = self._save_upload(datapacks_dir(name, create=True), MAX_DATAPACK)
                        finish_datapack(name, tmp, fname)
                        db.audit(user, name, "subir datapack", fname)
                        return self._send(200, {"uploaded": fname})
                    if action == "resourcepack_upload":
                        self._need(user, name, "textures")
                        tmp, fname = self._save_upload(packs_dir(name), MAX_DATAPACK)
                        finish_pack_upload(name, tmp, fname)
                        db.audit(user, name, "subir pack de texturas", fname)
                        return self._send(200, {"uploaded": fname})
                    if action == "release_upload":
                        self._need_admin(user)
                        tmp, fname = self._save_upload(release.release_dir(name), MAX_RELEASE, release.safe_release_name)
                        release.finish_upload(name, tmp, fname)
                        db.audit(user, name, "subir release", fname)
                        return self._send(200, {"uploaded": fname})
                    b = self._body()
                    if action in ("command", "memory", "meta", "release_delete", "release_share", "client_build",
                                  "properties", "delete"):
                        self._need_admin(user)
                    if action in ("start", "stop"):
                        self._need(user, name, "control")
                    if action == "start":
                        start(name)
                        db.audit(user, name, "arrancar")
                    elif action == "stop":
                        stop(name)
                        db.audit(user, name, "parar")
                    elif action == "command":
                        send_command(name, b.get("cmd", ""))
                        db.audit(user, name, "comando", b.get("cmd"))
                    elif action == "memory":
                        set_memory(name, b["xmx"], b["xms"])
                        db.audit(user, name, "memoria", f"{b['xmx']}/{b['xms']}")
                    elif action == "meta":
                        server_path(name)
                        db.set_server_meta(name, b.get("display_name"), b.get("icon"))
                    elif action == "mod_toggle":
                        self._need(user, name, "mods")
                        new = toggle_mod(name, b["file"])
                        _invalidate_installed(name)
                        db.audit(user, name, "activar/desactivar mod", new)
                        return self._send(200, {"file": new})
                    elif action == "mod_delete":
                        self._need(user, name, "mods")
                        delete_mod(name, b["file"])
                        _invalidate_installed(name)
                        db.audit(user, name, "borrar mod", b["file"])
                    elif action == "mod_update":
                        self._need(user, name, "mods")
                        new = update_mod(name, b["file"], b.get("loader", "neoforge"), b.get("version", "1.21.1"))
                        _invalidate_installed(name)
                        db.audit(user, name, "actualizar mod", new)
                        return self._send(200, {"installed": new})
                    elif action == "datapack_delete":
                        self._need(user, name, "datapacks")
                        delete_datapack(name, b["file"])
                        db.audit(user, name, "borrar datapack", b["file"])
                    elif action == "resourcepack_set":
                        self._need(user, name, "textures")
                        set_resourcepack(name, b.get("url"), b.get("sha1"), bool(b.get("required")), b.get("prompt"))
                        db.audit(user, name, "texturas del servidor", (b.get("url") or "(quitado)")[:120])
                    elif action == "resourcepack_use":
                        self._need(user, name, "textures")
                        use_local_pack(name, b["file"], b.get("base_url"), bool(b.get("required")), b.get("prompt"))
                        db.audit(user, name, "texturas del servidor (local)", b["file"])
                    elif action == "resourcepack_delete":
                        self._need(user, name, "textures")
                        delete_local_pack(name, b["file"])
                        db.audit(user, name, "borrar pack de texturas", b["file"])
                    elif action == "player":
                        self._need(user, name, "players")
                        cmd = player_action(name, b.get("action"), b.get("player"), b.get("text", ""))
                        db.audit(user, name, f"jugador: {b.get('action')}", cmd[:150])
                    elif action == "properties":
                        clean = set_properties(name, b.get("values"))
                        db.audit(user, name, "propiedades del servidor", ", ".join(sorted(clean)))
                        return self._send(200, {"ok": True, "values": properties_view(name)["values"]})
                    elif action == "delete":
                        if b.get("confirm") != name:
                            raise ValueError("escribe el nombre exacto del servidor para confirmar el borrado")
                        delete_server(name)
                        db.audit(user, None, "borrar servidor", name)
                    elif action == "client_build":
                        res = build_client(name, b.get("files"), b.get("format"), b.get("version"),
                                           bool(b.get("include_config")), b.get("pack_name"), user["username"], bool(b.get("reference_cf")),
                                           bool(b.get("presets")))
                        db.audit(user, name, "generar cliente", f"{res['file']} · {res['mods']} mods")
                        return self._send(200, res)
                    elif action == "release_delete":
                        release.delete_release(name, b["file"])
                        db.audit(user, name, "borrar release", b["file"])
                    elif action == "release_share":
                        server_path(name)
                        st = release.start_share(name, b["file"], b.get("minutes", release.DEFAULT_MINUTES))
                        db.audit(user, name, "publicar release", f"{b['file']} · {b.get('minutes', release.DEFAULT_MINUTES)} min")
                        return self._send(200, st)
                    else:
                        return self._send(404, {"error": "acción desconocida"})
                    return self._send(200, {"ok": True})
            return self._send(404, {"error": "no encontrado"})
        except PermissionError as e:
            return self._send(403, {"error": str(e)})
        except (ValueError, KeyError) as e:
            return self._send(400, {"error": str(e)})
        except (FileNotFoundError, LookupError) as e:
            return self._send(404, {"error": str(e)})
        except RuntimeError as e:
            return self._send(409, {"error": str(e)})
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return self._send(404, {"error": "no existe en el proveedor"})
            return self._send(502, {"error": f"el proveedor respondió {e.code}"})
        except Exception as e:  # noqa: BLE001 - se devuelve al cliente para depurar
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")


def _plugin_ctx():
    """Lo que el núcleo ofrece a un plugin: lo justo para actuar sobre servidores y datos propios."""
    import types
    ctx = types.SimpleNamespace(
        here=HERE, servers_dir=SERVERS_DIR, server_path=server_path, status=status, start=start, stop=stop,
        send_command=send_command, read_log=read_log, audit=db.audit, can=db.can, db_run=db.run,
        db_connect=db._connect, config=load_config, list_servers=list_servers,
        search=search, compat_for=compat_for, server_versions=server_versions, user_perms=db.user_perms,
        identify_mods=identify_mods, java_bin=templates._java, download=modpacks._download, port=PORT)
    ctx.install_modrinth = lambda name, slug, loaders=None, prefix=None: extras.install_modrinth(ctx, name, slug, loaders, prefix)
    return ctx


def main():
    cfg = ensure_config()
    db.init()
    plugins.load(_plugin_ctx(), cfg)
    if db.bootstrap_admin(cfg["access_token"]):
        print("Usuario inicial 'admin' creado: su contraseña es el access_token de config.json. "
              "Cámbiala desde el panel.", flush=True)
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))  # deja que atexit cierre el túnel
    bind = os.environ.get("MANAGER_BIND") or cfg.get("bind", "0.0.0.0")
    srv = ThreadingHTTPServer((bind, PORT), Handler)
    print(f"Gestor en http://{bind}:{PORT}  (servidores en {SERVERS_DIR})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
