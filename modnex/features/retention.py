"""Ciclo de vida de las copias de seguridad: reglas que borran las copias viejas solas.

Reglas (por servidor; 0 significa «sin límite» salvo en auto_keep, que va de 1 a 90):
- Copias de seguridad previa (las que se hacen antes de actualizar, fusionar o restaurar): conservar las
  últimas `pre_keep` y borrar las de más de `pre_days` días.
- Copias manuales: borrar las de más de `manual_days` días (por defecto nunca).
- Copias automáticas: conservar las últimas N (el menor «Conservar» de las tareas programadas; si no hay
  tareas, `auto_keep`).
- Espacio: no pasar de `max_gb` GB por servidor y dejar al menos `min_free_gb` GB libres en el disco;
  si no se cumple, se borran las más antiguas.

Garantías, pase lo que pase: nunca se borra la copia más reciente, ni las copias fijadas, y las fijadas no
cuentan para ningún límite de cantidad. Así siempre queda al menos una copia.
"""
import shutil
import threading
import time

from . import backups, notify

SCHEMA = """
CREATE TABLE IF NOT EXISTS pro_retention (
  server TEXT PRIMARY KEY,
  pre_keep INTEGER NOT NULL DEFAULT 3,
  pre_days INTEGER NOT NULL DEFAULT 14,
  manual_days INTEGER NOT NULL DEFAULT 0,
  auto_keep INTEGER NOT NULL DEFAULT 7,
  max_gb INTEGER NOT NULL DEFAULT 0,
  min_free_gb INTEGER NOT NULL DEFAULT 0);
"""
DEFAULTS = {"pre_keep": 3, "pre_days": 14, "manual_days": 0, "auto_keep": 7, "max_gb": 0, "min_free_gb": 0}
LIMITS = {"pre_keep": (0, 50), "pre_days": (0, 3650), "manual_days": (0, 3650), "auto_keep": (1, 90),
          "max_gb": (0, 100_000), "min_free_gb": (0, 100_000)}
PRE_KINDS = ("pre-update", "pre-restore")
GIB = 2 ** 30
DAY = 86400
_DAILY = {}
_DAILY_LOCK = threading.Lock()


class RetentionError(ValueError):
    pass


def validate(values, partial=False):
    """Solo enteros dentro de rango y solo claves conocidas."""
    if not isinstance(values, dict):
        raise RetentionError("reglas no válidas")
    out = {}
    for k, v in values.items():
        if k not in LIMITS:
            raise RetentionError(f"regla desconocida: {k}")
        if isinstance(v, bool) or not isinstance(v, int):
            raise RetentionError(f"{k}: debe ser un número entero")
        lo, hi = LIMITS[k]
        if not lo <= v <= hi:
            raise RetentionError(f"{k}: entre {lo} y {hi}")
        out[k] = v
    if not partial:
        out = {**DEFAULTS, **out}
    return out


def get(ctx, name):
    try:
        r = ctx.db_run("SELECT * FROM pro_retention WHERE server = ?", (name,), one=True)
    except Exception:
        r = None
    return {k: int(r[k]) for k in DEFAULTS} if r else dict(DEFAULTS)


def save(ctx, name, values):
    p = validate({**get(ctx, name), **values})
    with ctx.db_connect() as c:
        c.execute("INSERT INTO pro_retention(server, pre_keep, pre_days, manual_days, auto_keep, max_gb, min_free_gb) VALUES(?,?,?,?,?,?,?) "
                  "ON CONFLICT(server) DO UPDATE SET pre_keep=excluded.pre_keep, pre_days=excluded.pre_days, manual_days=excluded.manual_days, "
                  "auto_keep=excluded.auto_keep, max_gb=excluded.max_gb, min_free_gb=excluded.min_free_gb",
                  (name, p["pre_keep"], p["pre_days"], p["manual_days"], p["auto_keep"], p["max_gb"], p["min_free_gb"]))
        c.commit()
    return p


def _auto_keep(ctx, name, policy):
    try:
        rows = ctx.db_run("SELECT keep FROM pro_schedules WHERE server = ? AND kind = 'backup'", (name,), many=True)
    except Exception:
        rows = []
    keeps = [int(r["keep"]) for r in rows]
    return min(keeps) if keeps else policy["auto_keep"]


def plan(ctx, name, policy=None, now=None, free=None):
    """Qué se borraría con estas reglas. No toca nada. `free` (bytes) se inyecta en las pruebas."""
    policy = validate(policy, partial=False) if policy is not None else get(ctx, name)
    now = time.time() if now is None else now
    newest_first = sorted(backups.list_backups(ctx, name), key=lambda m: (m.get("created", 0), m.get("id", "")), reverse=True)
    protected = {m["id"] for m in newest_first if m.get("pinned")}
    if newest_first:
        protected.add(newest_first[0]["id"])
    doomed = {}

    def mark(m, why):
        if m["id"] not in protected and m["id"] not in doomed:
            doomed[m["id"]] = why

    def loose(pred):
        return [m for m in newest_first if pred(m) and not m.get("pinned")]

    pre = loose(lambda m: m.get("kind") in PRE_KINDS)
    if policy["pre_keep"]:
        for m in pre[policy["pre_keep"]:]:
            mark(m, f"más de {policy['pre_keep']} copias de seguridad previa")
    if policy["pre_days"]:
        for m in pre:
            if now - m.get("created", 0) > policy["pre_days"] * DAY:
                mark(m, f"copia de seguridad previa de más de {policy['pre_days']} días")
    if policy["manual_days"]:
        for m in loose(lambda m: m.get("kind") == "manual"):
            if now - m.get("created", 0) > policy["manual_days"] * DAY:
                mark(m, f"copia manual de más de {policy['manual_days']} días")
    keep = _auto_keep(ctx, name, policy)
    for m in loose(lambda m: m.get("kind") == "auto")[keep:]:
        mark(m, f"más de {keep} copias automáticas")

    unmet = []
    remaining = [m for m in newest_first if m["id"] not in doomed]
    oldest_removable = lambda: next((m for m in reversed(remaining) if m["id"] not in protected and m["id"] not in doomed), None)
    if policy["max_gb"]:
        limit = policy["max_gb"] * GIB
        total = sum(m.get("size", 0) for m in remaining)
        while total > limit:
            m = oldest_removable()
            if not m:
                unmet.append(f"las copias protegidas ocupan más de {policy['max_gb']} GB")
                break
            mark(m, f"supera el límite de {policy['max_gb']} GB por servidor")
            total -= m.get("size", 0)
            remaining.remove(m)
    if policy["min_free_gb"]:
        free = shutil.disk_usage(backups.backup_dir(ctx, name)).free if free is None else free
        freed = sum(m.get("size", 0) for m in newest_first if m["id"] in doomed)
        while free + freed < policy["min_free_gb"] * GIB:
            m = oldest_removable()
            if not m:
                unmet.append(f"no se puede llegar a {policy['min_free_gb']} GB libres sin tocar copias protegidas")
                break
            mark(m, f"queda poco espacio libre en el disco (mínimo {policy['min_free_gb']} GB)")
            freed += m.get("size", 0)
            remaining.remove(m)

    delete = [{"id": m["id"], "kind": m.get("kind"), "created": m.get("created"), "label": m.get("label", ""), "size": m.get("size", 0),
               "reason": doomed[m["id"]]} for m in reversed(newest_first) if m["id"] in doomed]
    return {"delete": delete, "freed": sum(d["size"] for d in delete), "kept": len(newest_first) - len(delete), "total": len(newest_first),
            "unmet": unmet, "policy": policy}


def apply(ctx, name, policy=None, now=None, free=None):
    """Borra lo que dicen las reglas. Si hay una copia en curso, no hace nada."""
    lk = backups._lock(name)
    if not lk.acquire(blocking=False):
        return {"skipped": "hay una copia en curso", "deleted": [], "freed": 0}
    try:
        pl = plan(ctx, name, policy, now, free)
        done = []
        for d in pl["delete"]:
            try:
                backups.delete(ctx, name, d["id"])
                done.append(d)
            except backups.BackupError:
                continue
    finally:
        lk.release()
    freed = sum(d["size"] for d in done)
    if done:
        ctx.audit({"username": "Modnex"}, name, "copias borradas por las reglas de retención", f"{len(done)} copias, {freed // 2**20} MB")
        notify.send(ctx, name, "backup", f"Se borraron {len(done)} copias viejas de «{name}» por las reglas de retención ({freed // 2**20} MB liberados).")
    return {"deleted": done, "freed": freed, "unmet": pl["unmet"]}


def after_create(ctx, name, meta):
    apply(ctx, name)


def daily(ctx, now=None):
    """Una pasada al día (después de las 3:00) por servidor, por si el espacio libre cambió por otras causas."""
    import datetime
    now = now or datetime.datetime.now()
    if now.hour < 3:
        return
    day = now.strftime("%Y%m%d")
    for s in ctx.list_servers():
        name = s["name"]
        with _DAILY_LOCK:
            if _DAILY.get(name) == day:
                continue
            _DAILY[name] = day
        try:
            apply(ctx, name)
        except Exception:
            pass
