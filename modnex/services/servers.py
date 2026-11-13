"""Servidores de Minecraft: carpetas, estado, arranque y parada, consola, métricas, memoria y vista según permisos."""

import collections
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from modnex import plugins
from modnex.infra import db, processes
from modnex.services import autofilter
from modnex.services import release
from modnex.services import templates
from modnex.config import HERE, MEM_RE, NAME_RE, SERVERS_DIR


PROCS = {}  # nombre -> Popen (solo los arrancados desde este gestor)


LOCK = threading.Lock()


def server_path(name):
    if not NAME_RE.fullmatch(name or ""):
        raise ValueError("nombre de servidor no válido")
    p = (SERVERS_DIR / name).resolve()
    if p.parent != SERVERS_DIR or not p.is_dir():
        raise FileNotFoundError(f"no existe el servidor {name}")
    return p


def _alive(pid):
    return processes.backend.is_java_alive(pid)


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
    proc = processes.backend.spawn(script, p, env, log)
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
            processes.backend.terminate(st["pid"])
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
        out.update(processes.backend.usage(pid))
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
                "addons": addons_of(server_path(s["name"])),
                "status": s["status"] if user["is_admin"] else {"running": s["status"]["running"]}}
        if user["is_admin"]:
            item["memory"] = s["memory"]
        out.append(item)
    return out


# Complementos que habilitan pestañas propias en el panel: id -> patrón del jar principal.
ADDON_JARS = {"kubejs": re.compile(r"kubejs-(neoforge|forge|fabric)-.*\.jar"), "morejs": re.compile(r"morejs-.*\.jar", re.IGNORECASE)}


def addons_of(path):
    mods = Path(path) / "mods"
    if not mods.is_dir():
        return []
    names = [j.name for j in mods.iterdir()]
    return [a for a, rx in ADDON_JARS.items() if any(rx.fullmatch(n) for n in names)]


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
