"""KubeJS: historial y deshacer de lo que escribe el panel.

Antes de cada guardado se guarda una versión de los archivos que gestiona el panel (el estado de cada pestaña en `kubejs/modnex/*.json`,
los scripts generados `modnex_*.js` y los datapacks de botín que él escribió). Cada versión es «cómo estaba todo antes de ese cambio», así
que restaurarla deshace el cambio. Se guardan en `kubejs/modnex/history/` (que AutoModpack no publica a los jugadores). Los scripts que
escribe el usuario a mano no se tocan: no son del panel.
"""
import hashlib
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path

HIST = "modnex/history"
KEEP = 40
MAX_FILES = 400
MAX_FILE_BYTES = 2_000_000
ID_RE = re.compile(r"\d{8}-\d{6}-\d{3}")
JSON_RE = re.compile(r"modnex/[a-z0-9_.-]+\.json")
SCRIPT_RE = re.compile(r"(?:server|client|startup)_scripts/modnex_[a-z0-9_.-]+\.js")
DATA_RE = re.compile(r"data/[a-z0-9_.-]+/loot_tables?/[a-z0-9_/.-]+\.json")
_LOCK = threading.Lock()


def _base(ctx, name):
    return Path(ctx.server_path(name)) / "kubejs"


def _loot_files(store):
    """Archivos de datapack que escribió el botín según su registro (`files` de loot.json), solo rutas con forma válida."""
    try:
        files = json.loads(store.read_text(encoding="utf-8")).get("files", [])
    except (OSError, ValueError, AttributeError):
        return []
    return [f for f in files if isinstance(f, str) and DATA_RE.fullmatch(f)] if isinstance(files, list) else []


def _is_managed(rel, loot_files):
    return bool(JSON_RE.fullmatch(rel) or SCRIPT_RE.fullmatch(rel) or (rel in loot_files and DATA_RE.fullmatch(rel)))


def managed(base):
    """Rutas (relativas a kubejs/) de todo lo que hoy gestiona el panel y existe."""
    out = []
    mod = base / "modnex"
    if mod.is_dir():
        out += [f"modnex/{p.name}" for p in sorted(mod.iterdir()) if p.is_file() and JSON_RE.fullmatch(f"modnex/{p.name}")]
    for d in ("server_scripts", "client_scripts", "startup_scripts"):
        sd = base / d
        if sd.is_dir():
            out += [f"{d}/{p.name}" for p in sorted(sd.iterdir()) if p.is_file() and SCRIPT_RE.fullmatch(f"{d}/{p.name}")]
    out += [f for f in _loot_files(base / "modnex" / "loot.json") if (base / f).is_file()]
    return out[:MAX_FILES]


def _digest(base, files):
    h = hashlib.sha1()
    for f in files:
        h.update(f.encode()); h.update(b"\0")
        try:
            h.update((base / f).read_bytes())
        except OSError:
            pass
        h.update(b"\1")
    return h.hexdigest()


def _meta(vdir):
    try:
        return json.loads((vdir / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _all(base):
    root = base / HIST
    if not root.is_dir():
        return []
    out = []
    for d in sorted(root.iterdir(), reverse=True):
        if d.is_dir() and ID_RE.fullmatch(d.name):
            m = _meta(d)
            if isinstance(m, dict) and isinstance(m.get("files"), list):
                out.append((d, m))
    return out


def snapshot(ctx, name, label, user=""):
    """Guarda cómo está todo ahora, antes de un cambio (también «todavía no hay nada», para poder deshacer el primero). No hace nada si es igual que la última versión."""
    base = _base(ctx, name)
    if not base.is_dir():
        return None
    with _LOCK:
        files = managed(base)
        digest = _digest(base, files)
        found = _all(base)
        if found and found[0][1].get("digest") == digest:
            return None
        stamp = time.strftime("%Y%m%d-%H%M%S")
        taken = [int(d.name.rsplit("-", 1)[1]) for d, _ in found if d.name.startswith(stamp + "-")]
        vid = f"{stamp}-{(max(taken) + 1) if taken else 0:03d}"      # crece siempre: ordenar por nombre es ordenar por antigüedad
        vdir = base / HIST / vid
        vdir.mkdir(parents=True, exist_ok=True)
        saved = []
        for f in files:
            src = base / f
            try:
                if src.stat().st_size > MAX_FILE_BYTES:
                    continue
                dst = vdir / "files" / f
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                saved.append(f)
            except OSError:
                continue
        (vdir / "meta.json").write_text(json.dumps({"id": vid, "ts": int(time.time()), "label": str(label)[:120], "user": str(user)[:60],
                                                    "files": saved, "digest": digest}, ensure_ascii=False, indent=1), encoding="utf-8")
        for d, _ in _all(base)[KEEP:]:
            shutil.rmtree(d, ignore_errors=True)
        return vid


def versions(ctx, name):
    """Versiones guardadas, de la más reciente a la más antigua, con lo que cambiaría restaurar cada una."""
    base = _base(ctx, name)
    current = {f: _file_hash(base / f) for f in managed(base)}
    out = []
    for d, m in _all(base):
        theirs = {f: _file_hash(d / "files" / f) for f in m["files"] if isinstance(f, str)}
        changes = [{"file": f, "status": "añadido" if f not in current else "cambiado"} for f in theirs if current.get(f) != theirs[f]]
        changes += [{"file": f, "status": "se borra"} for f in current if f not in theirs]
        out.append({"id": m.get("id", d.name), "ts": m.get("ts", 0), "label": m.get("label", ""), "user": m.get("user", ""), "files": len(theirs),
                    "changes": changes[:20], "change_count": len(changes), "same": not changes})
    return out


def _file_hash(path):
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()
    except OSError:
        return None


def restore(ctx, name, vid, user=""):
    """Devuelve los archivos del panel a como estaban en esa versión. Antes guarda el estado actual para poder volver atrás."""
    if not isinstance(vid, str) or not ID_RE.fullmatch(vid):
        raise ValueError("versión no válida")
    base = _base(ctx, name)
    vdir = base / HIST / vid
    meta = _meta(vdir) if vdir.is_dir() else None
    if not isinstance(meta, dict) or not isinstance(meta.get("files"), list):
        raise ValueError("esa versión ya no existe")
    snapshot(ctx, name, "Antes de restaurar una versión anterior", user)
    with _LOCK:
        theirs_store = vdir / "files" / "modnex" / "loot.json"
        theirs_loot = _loot_files(theirs_store)
        wanted = [f for f in meta["files"] if isinstance(f, str) and _is_managed(f, theirs_loot) and (vdir / "files" / f).is_file()]
        here = managed(base)
        for f in here:                                      # lo que hoy existe y la versión no tenía, se borra (solo lo que es del panel)
            if f not in wanted and _is_managed(f, _loot_files(base / "modnex" / "loot.json")):
                try:
                    (base / f).unlink()
                except OSError:
                    pass
        for f in wanted:
            dst = base / f
            if base.resolve() not in dst.resolve().parents:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_suffix(dst.suffix + ".tmp")
            shutil.copy2(vdir / "files" / f, tmp)
            os.replace(tmp, dst)
    return {"restored": vid, "files": len(wanted)}
