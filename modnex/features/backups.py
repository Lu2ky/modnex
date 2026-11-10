"""Copias de seguridad y versiones de un servidor.

Cada copia es un .tar.gz con todo lo necesario para volver a ese punto (mundo, mods, config,
propiedades...) más un .json con sus metadatos. Restaurar exige el servidor parado y crea antes
una copia de seguridad automática, así que siempre se puede deshacer.
"""
import json
import os
import re
import secrets
import shutil
import tarfile
import threading
import time
from pathlib import Path

ID_RE = re.compile(r"\d{8}-\d{6}-[a-f0-9]{4}")
EXCLUDE_NAMES = {"logs", "crash-reports", "libraries", "cache", ".mixin.out", "manager-console.log",
                 ".manager.pid", ".removed-client-mods", "installer.jar", "installer.jar.log",
                 "session.lock", ".restore-tmp", ".restore-old"}
EXCLUDE_SUFFIXES = (".log", ".tmp", ".lock", ".part")

_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
JOBS = {}   # servidor -> {"state": running|done|error, "msg": str, "id": str|None}


class BackupError(Exception):
    pass


def _lock(name):
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(name, threading.Lock())


def backup_dir(ctx, name):
    base = os.environ.get("MODNEX_BACKUP_DIR") or ctx.config().get("backup_dir") or str(Path(ctx.here) / "backups")
    d = Path(base) / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _head_file(ctx, name):
    return backup_dir(ctx, name) / "HEAD"


def get_head(ctx, name):
    """Id de la copia de la que desciende el estado actual del servidor (None si aún no hay)."""
    try:
        h = _head_file(ctx, name).read_text().strip()
    except OSError:
        return None
    return h if ID_RE.fullmatch(h) else None


def _set_head(ctx, name, bid):
    f = _head_file(ctx, name)
    tmp = f.with_suffix(".part")
    tmp.write_text(bid)
    tmp.replace(f)


def _excluded(rel_parts, filename=None):
    if rel_parts and rel_parts[0] in EXCLUDE_NAMES:
        return True
    last = filename if filename else (rel_parts[-1] if rel_parts else "")
    return last in EXCLUDE_NAMES or last.endswith(EXCLUDE_SUFFIXES)


def _walk(root):
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        dirnames[:] = [d for d in dirnames if not _excluded(rel_dir.parts + (d,)) and not os.path.islink(Path(dirpath) / d)]
        for f in filenames:
            if _excluded(rel_dir.parts, f) or os.path.islink(Path(dirpath) / f):
                continue
            yield Path(dirpath) / f, (rel_dir / f).as_posix()


def _server_meta(p):
    try:
        m = json.loads((p / ".manager.json").read_text())
    except (OSError, ValueError):
        m = {}
    return {"minecraft": m.get("mc"), "loader": m.get("loader"), "loader_version": m.get("loader_version")}


def _mods(p):
    d = p / "mods"
    return sorted([f.name, f.stat().st_size] for f in d.glob("*.jar")) if d.is_dir() else []


def _wait_saved(ctx, name, timeout=20):
    """Espera a que el servidor confirme `save-all flush`."""
    log = Path(ctx.server_path(name)) / "manager-console.log"
    start = log.stat().st_size if log.exists() else 0
    end = time.time() + timeout
    while time.time() < end:
        time.sleep(0.5)
        try:
            with open(log, "rb") as f:
                f.seek(start)
                data = f.read()
            if b"Saved the game" in data or b"Saved the world" in data:
                return True
        except OSError:
            pass
    return False


AFTER_CREATE = []   # funciones fn(ctx, name, meta) que se llaman al terminar cada copia (p. ej. las reglas de retención)


def create(ctx, name, label="", note="", kind="manual", allow_hot_without_console=False):
    """Crea una copia y avisa a los enganches de después. Devuelve sus metadatos."""
    meta = _create(ctx, name, label, note, kind, allow_hot_without_console)
    for fn in list(AFTER_CREATE):
        try:
            fn(ctx, name, meta)
        except Exception:
            pass          # unas reglas rotas no deben hacer fallar una copia que ya está hecha
    return meta


def _create(ctx, name, label="", note="", kind="manual", allow_hot_without_console=False):
    """Crea una copia. Devuelve sus metadatos."""
    p = Path(ctx.server_path(name))
    lk = _lock(name)
    if not lk.acquire(blocking=False):
        raise BackupError("ya hay una copia en curso para este servidor")
    try:
        files = list(_walk(p))
        total = sum(f.stat().st_size for f, _ in files)
        out_dir = backup_dir(ctx, name)
        free = shutil.disk_usage(out_dir).free
        if free < total:  # gzip suele comprimir, pero no se asume
            raise BackupError(f"no hay espacio suficiente: hacen falta ~{total // 2**20} MB y hay {free // 2**20} MB libres")
        st = ctx.status(name)
        hot = bool(st["running"])
        saved_off = False
        if hot:
            if not st.get("control") and not allow_hot_without_console:
                raise BackupError("el servidor está en marcha sin control directo del gestor; "
                                  "páralo o arráncalo desde el gestor para copiar en caliente")
            if st.get("control"):
                ctx.send_command(name, "save-off")
                saved_off = True
                ctx.send_command(name, "save-all flush")
                _wait_saved(ctx, name)
        try:
            bid = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
            tmp = out_dir / f"{bid}.tar.gz.part"
            with tarfile.open(tmp, "w:gz", compresslevel=3) as tar:
                for f, arc in files:
                    try:
                        tar.add(f, arcname=arc, recursive=False)
                    except FileNotFoundError:
                        continue  # un archivo desapareció durante la copia (p. ej. temporal)
            final = out_dir / f"{bid}.tar.gz"
            tmp.rename(final)
        finally:
            if saved_off:
                try:
                    ctx.send_command(name, "save-on")
                except Exception:
                    pass
        meta = {"id": bid, "parent": get_head(ctx, name), "created": int(time.time()), "label": re.sub(r"[\r\n]+", " ", label or "")[:80],
                "note": (note or "")[:500], "kind": kind, "size": final.stat().st_size, "files": len(files),
                "hot": hot, "mods": _mods(p), **_server_meta(p)}
        (out_dir / f"{bid}.json").write_text(json.dumps(meta, ensure_ascii=False))
        _set_head(ctx, name, bid)
        return meta
    finally:
        lk.release()


def list_backups(ctx, name, include_deleted=False):
    """Copias disponibles, de la más reciente a la más antigua. Con `include_deleted` salen también las borradas, que
    solo conservan sus metadatos (ver `delete`) y llevan `deleted: True`."""
    d = backup_dir(ctx, name)
    out = []
    for f in sorted(d.glob("*.json"), reverse=True):
        try:
            m = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if (d / f"{m.get('id')}.tar.gz").exists():
            out.append(m)
        elif include_deleted and ID_RE.fullmatch(str(m.get("id") or "")):
            out.append({**m, "deleted": True})   # sin archivo: borrada, o el archivo se quitó a mano
    return out


def graph(ctx, name):
    """Historial como árbol, estilo `git log --graph`: cada copia es un commit y `parent` es la copia de la que partía.

    Restaurar una copia antigua y seguir copiando abre una rama. Las copias anteriores a esta función no guardaban
    padre: se encadenan por fecha. Las copias borradas siguen en el árbol como lápidas (`deleted`), así el historial no
    se pierde con la retención; solo si falta del todo el padre (borrado de versiones anteriores) se enlaza con la anterior.
    Devuelve {"head", "lanes", "nodes": [{... meta, "row", "lane", "parent", "edges": [{"to", "lane"}]}]},
    de la más reciente a la más antigua.
    """
    found = list_backups(ctx, name, include_deleted=True)
    by_id = {m["id"]: m for m in found}

    def depth(bid, seen=()):
        p = by_id[bid].get("parent")
        return 0 if p not in by_id or p in seen or p == bid else 1 + depth(p, seen + (bid,))

    # con la misma fecha (segundos) manda el padre: un hijo es siempre más reciente que su padre
    items = sorted(found, key=lambda m: (m.get("created", 0), depth(m["id"]), m["id"]), reverse=True)
    ids = set(by_id)
    parent = {}
    for i, m in enumerate(items):
        older = items[i + 1]["id"] if i + 1 < len(items) else None
        if "parent" in m:
            p = m["parent"]
            parent[m["id"]] = p if p in ids and p != m["id"] else (older if p else None)
        else:
            parent[m["id"]] = older
    row = {m["id"]: i for i, m in enumerate(items)}
    # un padre siempre más antiguo que su hijo; si el orden por fecha lo contradice, se corta el enlace
    for k, p in list(parent.items()):
        if p is not None and row[p] <= row[k]:
            parent[k] = None
    head = get_head(ctx, name)
    lanes = []          # lanes[i] = id de la copia que espera esa columna (su padre) o None
    nodes = []
    for m in items:
        bid = m["id"]
        mine = [i for i, x in enumerate(lanes) if x == bid]
        if mine:
            lane = mine[0]
        elif None in lanes:
            lane = lanes.index(None)
        else:
            lanes.append(None)
            lane = len(lanes) - 1
        for i in mine:
            lanes[i] = None
        lanes[lane] = parent[bid]
        node = {**m, "row": row[bid], "lane": lane, "parent": parent[bid], "head": bid == head, "deleted": bool(m.get("deleted"))}
        nodes.append(node)
    lane_of = {n["id"]: n["lane"] for n in nodes}
    for n in nodes:
        n["edge"] = None if n["parent"] is None else {"to": row[n["parent"]], "lane": lane_of[n["parent"]]}
    return {"head": head, "lanes": max((n["lane"] for n in nodes), default=0) + 1, "nodes": nodes}


def _find(ctx, name, bid):
    if not ID_RE.fullmatch(bid or ""):
        raise BackupError("identificador de copia no válido")
    d = backup_dir(ctx, name)
    if not (d / f"{bid}.tar.gz").exists():
        raise BackupError("esa copia no existe")
    return d, bid


def delete(ctx, name, bid):
    """Borra el archivo de la copia y libera su espacio, pero conserva sus metadatos como una lápida (`deleted`): el
    árbol de versiones sigue mostrando de dónde partía cada rama aunque la copia ya no exista."""
    d, bid = _find(ctx, name, bid)
    (d / f"{bid}.tar.gz").unlink(missing_ok=True)
    f = d / f"{bid}.json"
    try:
        meta = json.loads(f.read_text())
    except (OSError, ValueError):
        meta = {"id": bid}
    meta.update(deleted=True, deleted_at=int(time.time()), pinned=False)
    tmp = f.with_suffix(".json.part")
    tmp.write_text(json.dumps(meta, ensure_ascii=False))
    tmp.replace(f)


def forget(ctx, name, bid):
    """Quita del historial una copia que ya estaba borrada. Es lo único que borra su rastro."""
    if not ID_RE.fullmatch(bid or ""):
        raise BackupError("identificador de copia no válido")
    d = backup_dir(ctx, name)
    if (d / f"{bid}.tar.gz").exists():
        raise BackupError("esa copia todavía existe: bórrala primero")
    if not (d / f"{bid}.json").exists():
        raise BackupError("esa copia no está en el historial")
    (d / f"{bid}.json").unlink()


def set_pinned(ctx, name, bid, pinned):
    """Fija o suelta una copia: una copia fijada no la borra ninguna regla automática."""
    d, bid = _find(ctx, name, bid)
    f = d / f"{bid}.json"
    meta = json.loads(f.read_text())
    meta["pinned"] = bool(pinned)
    tmp = f.with_suffix(".json.part")
    tmp.write_text(json.dumps(meta, ensure_ascii=False))
    tmp.replace(f)
    return meta


def prune(ctx, name, keep, kind="auto"):
    """Borra las copias más antiguas de un tipo, dejando las `keep` más recientes. Las fijadas no cuentan ni se borran."""
    mine = [m for m in list_backups(ctx, name) if m.get("kind") == kind and not m.get("pinned")]
    for m in mine[keep:]:
        delete(ctx, name, m["id"])
    return max(0, len(mine) - keep)


def restore(ctx, name, bid):
    """Vuelve a una copia. Exige el servidor parado y guarda antes una copia 'pre-restore'."""
    d, bid = _find(ctx, name, bid)
    if ctx.status(name)["running"]:
        raise BackupError("para el servidor antes de restaurar una copia")
    p = Path(ctx.server_path(name))
    safety = create(ctx, name, label="Antes de restaurar", kind="pre-restore")
    tmp = p / ".restore-tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    try:
        with tarfile.open(d / f"{bid}.tar.gz", "r:gz") as tar:
            tar.extractall(tmp, filter="data")  # rechaza rutas absolutas, '..' y enlaces peligrosos
        for entry in sorted(tmp.iterdir()):
            target = p / entry.name
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            elif target.exists() or target.is_symlink():
                target.unlink()
            shutil.move(str(entry), str(target))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    _set_head(ctx, name, bid)   # lo que se copie a partir de ahora cuelga de la copia restaurada: una rama nueva
    return {"restored": bid, "safety": safety["id"]}


def diff(ctx, name, a, b):
    """Diferencias de mods y versiones entre dos copias, o entre una copia y el estado actual (b='current')."""
    def snap(x):
        if x == "current":
            p = Path(ctx.server_path(name))
            return {"mods": _mods(p), **_server_meta(p)}
        if not ID_RE.fullmatch(x or ""):
            raise BackupError("identificador de copia no válido")
        f = backup_dir(ctx, name) / f"{x}.json"      # también vale para una copia borrada: basta con sus metadatos
        if not f.exists():
            raise BackupError("esa copia no existe")
        return json.loads(f.read_text())
    sa, sb = snap(a), snap(b)
    ma, mb = {n: s for n, s in sa.get("mods", [])}, {n: s for n, s in sb.get("mods", [])}
    return {"added": sorted(set(mb) - set(ma)), "removed": sorted(set(ma) - set(mb)),
            "changed": sorted(n for n in set(ma) & set(mb) if ma[n] != mb[n]),
            "versions": {k: [sa.get(k), sb.get(k)] for k in ("minecraft", "loader", "loader_version") if sa.get(k) != sb.get(k)}}


def run_job(ctx, name, on_done=None, **kw):
    """Lanza una copia en segundo plano; el estado se consulta con JOBS[name].
    on_done(meta, error) se llama al terminar (meta o error según el resultado)."""
    if JOBS.get(name, {}).get("state") == "running":
        raise BackupError("ya hay una copia en curso para este servidor")
    started = int(time.time())
    JOBS[name] = {"state": "running", "msg": "", "id": None, "started": started}

    def work():
        meta = err = None
        try:
            meta = create(ctx, name, **kw)
            JOBS[name] = {"state": "done", "msg": "", "id": meta["id"], "started": started}
        except Exception as e:
            err = e
            JOBS[name] = {"state": "error", "msg": str(e), "id": None, "started": started}
        if on_done:
            try:
                on_done(meta, err)
            except Exception:
                pass
    threading.Thread(target=work, daemon=True).start()
