"""Tareas programadas por servidor: copias de seguridad y reinicios con aviso en el juego."""
import datetime
import re
import threading
import time

from . import backups, notify, retention

SCHEMA = """
CREATE TABLE IF NOT EXISTS pro_schedules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  server TEXT NOT NULL,
  kind TEXT NOT NULL,
  hhmm TEXT NOT NULL,
  days TEXT NOT NULL DEFAULT '*',
  keep INTEGER NOT NULL DEFAULT 7,
  enabled INTEGER NOT NULL DEFAULT 1,
  last_run TEXT NOT NULL DEFAULT '');
"""
KINDS = ("backup", "restart")
HHMM = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
WARN_MINUTES = (5, 1)
_started = False
_warned = set()


def validate(kind, hhmm, days, keep):
    if kind not in KINDS:
        raise ValueError("tipo de tarea no válido")
    if not HHMM.fullmatch(hhmm or ""):
        raise ValueError("la hora debe ser HH:MM")
    if days != "*" and not re.fullmatch(r"[0-6](,[0-6]){0,6}", days or ""):
        raise ValueError("días no válidos (0=lunes … 6=domingo, o *)")
    keep = int(keep)
    if not 1 <= keep <= 90:
        raise ValueError("conservar entre 1 y 90 copias")
    return kind, hhmm, days, keep


def list_schedules(ctx, name):
    return [dict(r) for r in ctx.db_run("SELECT * FROM pro_schedules WHERE server = ? ORDER BY hhmm", (name,), many=True)]


def add(ctx, name, kind, hhmm, days="*", keep=7):
    kind, hhmm, days, keep = validate(kind, hhmm, days, keep)
    n = ctx.db_run("SELECT COUNT(*) AS n FROM pro_schedules WHERE server = ?", (name,), one=True)["n"]
    if n >= 20:
        raise ValueError("máximo 20 tareas por servidor")
    with ctx.db_connect() as c:
        cur = c.execute("INSERT INTO pro_schedules(server, kind, hhmm, days, keep) VALUES(?,?,?,?,?)", (name, kind, hhmm, days, keep))
        c.commit()
        return cur.lastrowid


def remove(ctx, name, sid):
    with ctx.db_connect() as c:
        c.execute("DELETE FROM pro_schedules WHERE id = ? AND server = ?", (int(sid), name))
        c.commit()


def set_enabled(ctx, name, sid, enabled):
    with ctx.db_connect() as c:
        c.execute("UPDATE pro_schedules SET enabled = ? WHERE id = ? AND server = ?", (int(bool(enabled)), int(sid), name))
        c.commit()


def day_ok(days, weekday):
    return days == "*" or str(weekday) in days.split(",")


def is_due(s, now):
    """¿Toca ejecutar la tarea ahora? Una vez al día como mucho."""
    today = now.strftime("%Y%m%d")
    return bool(s["enabled"]) and now.strftime("%H:%M") == s["hhmm"] and day_ok(s["days"], now.weekday()) and s["last_run"] != today


def warn_minutes(s, now):
    """Minutos de aviso que corresponden ahora a un reinicio (5 o 1 min antes), o None."""
    if s["kind"] != "restart" or not s["enabled"]:
        return None
    h, m = map(int, s["hhmm"].split(":"))
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    for w in WARN_MINUTES:
        t = target - datetime.timedelta(minutes=w)
        if now.strftime("%H:%M") == t.strftime("%H:%M") and day_ok(s["days"], t.weekday()):
            return w
    return None


def run_task(ctx, s):
    name = s["server"]
    if s["kind"] == "backup":
        try:
            m = backups.create(ctx, name, label="Programada", kind="auto")
            backups.prune(ctx, name, s["keep"], kind="auto")
            notify.send(ctx, name, "backup", f"Copia programada de «{name}» creada ({m['size'] // 2**20} MB).")
            ctx.audit("sistema", name, "copia programada", m["id"])
        except Exception as e:
            notify.send(ctx, name, "backup", f"La copia programada de «{name}» falló: {e}")
            ctx.audit("sistema", name, "copia programada fallida", str(e)[:200])
    elif s["kind"] == "restart":
        if not ctx.status(name)["running"]:
            return
        try:
            ctx.send_command(name, "say Reiniciando el servidor ahora")
        except Exception:
            pass
        ctx.stop(name)
        time.sleep(3)
        ctx.start(name)
        ctx.audit("sistema", name, "reinicio programado")


def tick(ctx, now=None):
    now = now or datetime.datetime.now()
    for r in ctx.db_run("SELECT * FROM pro_schedules WHERE enabled = 1", many=True):
        s = dict(r)
        w = warn_minutes(s, now)
        if w:
            key = (s["id"], now.strftime("%Y%m%d"), w)
            if key not in _warned:
                _warned.add(key)
                try:
                    ctx.send_command(s["server"], f"say Reinicio del servidor en {w} minuto{'s' if w != 1 else ''}")
                except Exception:
                    pass
        if is_due(s, now):
            with ctx.db_connect() as c:  # se marca antes de ejecutar para no repetir si tarda
                c.execute("UPDATE pro_schedules SET last_run = ? WHERE id = ?", (now.strftime("%Y%m%d"), s["id"]))
                c.commit()
            threading.Thread(target=run_task, args=(ctx, s), daemon=True).start()
    if len(_warned) > 500:
        _warned.clear()


def start(ctx):
    global _started
    if _started:
        return
    _started = True

    def loop():
        while True:
            try:
                tick(ctx)
            except Exception:
                pass
            try:
                retention.daily(ctx)
            except Exception:
                pass
            time.sleep(20)
    threading.Thread(target=loop, daemon=True).start()
