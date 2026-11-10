"""Servidor de pruebas: una instancia permanente junto al servidor real.

- Tiene sus propios mods (copia de los reales al crearlo) y su propia configuración, y genera su propio
  mundo vacío: nunca se copia ni se toca el mundo del servidor real.
- Se administra desde el panel como cualquier servidor (mods, consola, registros, arrancar y parar).
- Se fusionan con el real los cambios de configuración y los de mods (añadidos, quitados y cambiados),
  archivo por archivo y tras revisar la diferencia.
- Fusionar exige el servidor real parado y crea una copia de seguridad antes.
"""
import difflib
import filecmp
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import backups

SCHEMA = """
CREATE TABLE IF NOT EXISTS pro_staging (
  real TEXT PRIMARY KEY,
  staging TEXT NOT NULL UNIQUE,
  created_at INTEGER NOT NULL);
"""
CFG_DIRS = ("config", "defaultconfigs", "kubejs", "scripts", "global_packs")
COPY_FILES = ("eula.txt", "start.sh", "user_jvm_args.txt", "ops.json", "whitelist.json")
SKIP_SUFFIX = (".log", ".tmp", ".bak", ".part", ".lock")
MAX_FILES = 6000
MAX_DIFF_BYTES = 120_000
STAGING_XMX_MB = 4096
SUFFIX = "-prueba"
MOD_RE = re.compile(r"[A-Za-z0-9._+\-\[\]() ]{1,200}\.jar(\.disabled)?")
NAME_RE = re.compile(r"[A-Za-z0-9._-]+")


class StagingError(Exception):
    pass


def link(ctx, name):
    """(real, staging) si `name` es uno de los dos extremos de una pareja; si no, None."""
    r = ctx.db_run("SELECT real, staging FROM pro_staging WHERE real = ? OR staging = ?", (name, name), one=True)
    return (r["real"], r["staging"]) if r else None


def _root(ctx):
    return Path(ctx.servers_dir)


def _used_ports(ctx):
    ports = set()
    for d in _root(ctx).iterdir():
        try:
            for line in (d / "server.properties").read_text().splitlines():
                if line.startswith("server-port="):
                    ports.add(int(line.split("=", 1)[1]))
        except (OSError, ValueError):
            pass
    return ports


def _copy_tree(src, dst):
    """Copia con reflink si el sistema de archivos lo permite (rápido y sin duplicar espacio)."""
    r = subprocess.run(["cp", "-a", "--reflink=auto", str(src), str(dst)], capture_output=True, text=True)
    if r.returncode != 0:
        raise StagingError("no se pudo copiar: " + (r.stderr.strip() or "error desconocido")[:200])


def create(ctx, real):
    if link(ctx, real):
        raise StagingError("este servidor ya tiene un servidor de pruebas")
    src = Path(ctx.server_path(real))
    name = real + SUFFIX
    if not NAME_RE.fullmatch(name) or len(name) > 64:
        raise StagingError("el nombre resultante no es válido")
    dst = _root(ctx) / name
    if dst.exists():
        raise StagingError(f"ya existe una carpeta llamada {name}")
    dst.mkdir()
    try:
        for d in CFG_DIRS + ("mods",):
            if (src / d).is_dir():
                _copy_tree(src / d, dst / d)
        if (src / "libraries").is_dir():
            (dst / "libraries").symlink_to((src / "libraries").resolve())
        for f in COPY_FILES:
            if (src / f).is_file():
                shutil.copy2(src / f, dst / f)
        args = dst / "user_jvm_args.txt"
        if args.exists():
            t = args.read_text()
            t = re.sub(r"-Xmx(\d+)([GgMm])", lambda m: f"-Xmx{min(int(m.group(1)) * (1024 if m.group(2).lower() == 'g' else 1), STAGING_XMX_MB)}M", t)
            args.write_text(t)
        kv = {}
        if (src / "server.properties").is_file():
            for line in (src / "server.properties").read_text().splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k, _, v = line.partition("=")
                    kv[k.strip()] = v
        used = _used_ports(ctx)
        port = next(p for p in range(25566, 25700) if p not in used)
        kv.update({"server-port": str(port), "level-name": "mundo-prueba", "motd": "Servidor de pruebas", "enable-rcon": "false", "enable-query": "false"})
        (dst / "server.properties").write_text("\n".join(f"{k}={v}" for k, v in kv.items()) + "\n")
        meta = {}
        if (src / ".manager.json").is_file():
            try:
                meta = json.loads((src / ".manager.json").read_text())
            except ValueError:
                pass
        meta.pop("modpack", None)
        meta["parent"] = real          # el panel lo muestra como hijo del servidor real
        meta["staging_of"] = real
        (dst / ".manager.json").write_text(json.dumps(meta, indent=2))
        with ctx.db_connect() as c:
            c.execute("INSERT INTO pro_staging(real, staging, created_at) VALUES(?,?,?)", (real, name, int(time.time())))
            c.commit()
    except BaseException:
        _rmtree(dst)
        raise
    return {"staging": name, "port": port}


def _rmtree(path):
    p = Path(path)
    lib = p / "libraries"
    if lib.is_symlink():
        lib.unlink()            # nunca se sigue el enlace hacia los archivos del servidor real
    shutil.rmtree(p, ignore_errors=True)


def delete(ctx, name):
    pair = link(ctx, name)
    if not pair:
        raise StagingError("este servidor no tiene pareja de pruebas")
    real, stg = pair
    if ctx.status(stg)["running"]:
        raise StagingError("para el servidor de pruebas antes de borrarlo")
    path = _root(ctx) / stg
    if path.resolve().parent != _root(ctx).resolve() or path.resolve() == Path(ctx.server_path(real)).resolve():
        raise StagingError("ruta no válida")
    _rmtree(path)
    with ctx.db_connect() as c:
        c.execute("DELETE FROM pro_staging WHERE real = ?", (real,))
        c.commit()
    return {"deleted": stg}


# ---------- comparación ----------
def _files(base):
    out = {}
    for d in CFG_DIRS:
        root = Path(base) / d
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.is_symlink() or not p.is_file() or p.name.endswith(SKIP_SUFFIX):
                continue
            out[p.relative_to(base).as_posix()] = p
            if len(out) > MAX_FILES:
                raise StagingError("hay demasiados archivos de configuración para comparar")
    return out


def _text(p):
    try:
        if p.stat().st_size > MAX_DIFF_BYTES:
            return None
        return p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def _unified(a, b, name):
    la = _text(a).splitlines(True) if a else []
    lb = _text(b).splitlines(True) if b else []
    return "".join(difflib.unified_diff(la, lb, f"real/{name}", f"pruebas/{name}", n=2))[:40_000]


def _mods(base):
    d = Path(base) / "mods"
    return {p.name: p for p in d.iterdir() if p.is_file() and not p.is_symlink() and MOD_RE.fullmatch(p.name)} if d.is_dir() else {}


def diff(ctx, name):
    pair = link(ctx, name)
    if not pair:
        raise StagingError("este servidor no tiene servidor de pruebas")
    real, stg = pair
    rp, sp = Path(ctx.server_path(real)), Path(ctx.server_path(stg))
    fr, fs = _files(rp), _files(sp)
    changes = []
    for rel in sorted(set(fr) | set(fs)):
        a, b = fr.get(rel), fs.get(rel)
        if a and b:
            if filecmp.cmp(a, b, shallow=False):
                continue
            kind = "modified"
        else:
            kind = "added" if b else "removed"
        ta, tb = (_text(a) if a else ""), (_text(b) if b else "")
        textual = ta is not None and tb is not None
        changes.append({"path": rel, "kind": kind, "text": textual,
                        "diff": _unified(a, b, rel) if textual else "", "size": (b or a).stat().st_size})
    mr, ms = _mods(rp), _mods(sp)
    mod_changes = []
    for fn in sorted(set(mr) | set(ms)):
        a, b = mr.get(fn), ms.get(fn)
        if a and b:
            if filecmp.cmp(a, b, shallow=False):
                continue
            kind = "modified"
        else:
            kind = "added" if b else "removed"
        mod_changes.append({"file": fn, "kind": kind, "size": (b or a).stat().st_size})
    return {"real": real, "staging": stg, "changes": changes, "mod_changes": mod_changes,
            "mods": {"only_staging": sorted(set(ms) - set(mr)), "only_real": sorted(set(mr) - set(ms)),
                     "same": len(set(mr) & set(ms)) - len([m for m in mod_changes if m["kind"] == "modified"])},
            "staging_running": bool(ctx.status(stg)["running"]), "real_running": bool(ctx.status(real)["running"])}


# ---------- fusionar ----------
def _safe_rel(rel):
    if not isinstance(rel, str) or rel.startswith("/") or "\\" in rel or "\x00" in rel:
        raise StagingError("ruta no válida")
    parts = rel.split("/")
    if ".." in parts or "" in parts or parts[0] not in CFG_DIRS:
        raise StagingError("ruta no válida")
    return rel


def merge(ctx, name, picks):
    """picks: lista de {"path", "action"}; action ∈ {"copy", "delete"}. Solo vale lo que está en la diferencia actual."""
    pair = link(ctx, name)
    if not pair:
        raise StagingError("este servidor no tiene servidor de pruebas")
    real, stg = pair
    if ctx.status(real)["running"]:
        raise StagingError("para el servidor real antes de fusionar los cambios")
    if not isinstance(picks, list) or not picks or len(picks) > MAX_FILES:
        raise StagingError("no hay cambios seleccionados")
    current = {c["path"]: c["kind"] for c in diff(ctx, name)["changes"]}
    plan = []
    for p in picks:
        if not isinstance(p, dict):
            raise StagingError("selección no válida")
        rel = _safe_rel(p.get("path"))
        kind = current.get(rel)
        action = p.get("action")
        if kind is None:
            raise StagingError(f"{rel} ya no tiene cambios; vuelve a comparar")
        if (kind == "removed") != (action == "delete") or action not in ("copy", "delete"):
            raise StagingError(f"acción no válida para {rel}")
        plan.append((rel, action))
    if len({r for r, _ in plan}) != len(plan):
        raise StagingError("hay archivos repetidos en la selección")
    rp, sp = Path(ctx.server_path(real)).resolve(), Path(ctx.server_path(stg)).resolve()
    safety = backups.create(ctx, real, label="Antes de fusionar la configuración de pruebas", kind="pre-update")
    done = []
    for rel, action in plan:
        dst = (rp / rel)
        if rp not in dst.resolve().parents:
            raise StagingError("ruta fuera del servidor")
        if action == "delete":
            dst.unlink(missing_ok=True)
        else:
            srcf = sp / rel
            if srcf.is_symlink() or not srcf.is_file() or sp not in srcf.resolve().parents:
                raise StagingError(f"{rel} no es un archivo normal")
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(dst.name + ".part")
            shutil.copy2(srcf, tmp)
            os.replace(tmp, dst)
        done.append(rel)
    return {"merged": done, "backup": safety["id"]}


def status(ctx, name):
    pair = link(ctx, name)
    if not pair:
        return {"exists": False, "real_running": bool(ctx.status(name)["running"])}
    real, stg = pair
    return {"exists": True, "real": real, "staging": stg, "viewing": "staging" if name == stg else "real",
            "staging_running": bool(ctx.status(stg)["running"]), "real_running": bool(ctx.status(real)["running"])}


def merge_mods(ctx, name, picks):
    """picks: [{"file", "action"}]; copy = añadir o reemplazar en el real, delete = quitar del real."""
    pair = link(ctx, name)
    if not pair:
        raise StagingError("este servidor no tiene servidor de pruebas")
    real, stg = pair
    if ctx.status(real)["running"]:
        raise StagingError("para el servidor real antes de fusionar los mods")
    if not isinstance(picks, list) or not picks or len(picks) > 500:
        raise StagingError("no hay mods seleccionados")
    current = {c["file"]: c["kind"] for c in diff(ctx, name)["mod_changes"]}
    plan = []
    for p in picks:
        if not isinstance(p, dict):
            raise StagingError("selección no válida")
        fn, action = p.get("file"), p.get("action")
        if not isinstance(fn, str) or not MOD_RE.fullmatch(fn) or fn not in current:
            raise StagingError(f"{fn!r} ya no tiene cambios; vuelve a comparar")
        if action not in ("copy", "delete") or (current[fn] == "removed") != (action == "delete"):
            raise StagingError(f"acción no válida para {fn}")
        plan.append((fn, action))
    if len({f for f, _ in plan}) != len(plan):
        raise StagingError("hay mods repetidos en la selección")
    rmods, smods = Path(ctx.server_path(real)).resolve() / "mods", Path(ctx.server_path(stg)).resolve() / "mods"
    safety = backups.create(ctx, real, label="Antes de fusionar los mods de pruebas", kind="pre-update")
    done = []
    for fn, action in plan:
        if action == "delete":
            (rmods / fn).unlink(missing_ok=True)
        else:
            src = smods / fn
            if src.is_symlink() or not src.is_file():
                raise StagingError(f"{fn} no es un archivo normal")
            rmods.mkdir(exist_ok=True)
            tmp = rmods / (fn + ".part")
            shutil.copy2(src, tmp)
            if hashlib.sha1(tmp.read_bytes()).hexdigest() != hashlib.sha1(src.read_bytes()).hexdigest():
                tmp.unlink(missing_ok=True)
                raise StagingError(f"la copia de {fn} no coincide con el original")
            os.replace(tmp, rmods / fn)
        done.append(fn)
    return {"merged": done, "backup": safety["id"]}
