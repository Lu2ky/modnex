"""Estadísticas de jugadores a partir de los logs del servidor.

Entiende las dos formas de marca de tiempo que usa Minecraft: la completa de NeoForge
(`[09nov2026 19:57:46.239]`, con el mes según el idioma del sistema) y la corta de Vanilla
(`[19:57:46]`, que toma la fecha del archivo). Una sesión va de «joined the game» a
«left the game»; si el servidor se reinicia o cae sin esa línea, se cierra en el último
instante visto, no se queda abierta para siempre.
"""
import datetime as dt
import gzip
import re
from pathlib import Path

MONTHS = {"ene": 1, "jan": 1, "feb": 2, "mar": 3, "abr": 4, "apr": 4, "may": 5, "jun": 6, "jul": 7,
          "ago": 8, "aug": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12, "dec": 12}
LINE = re.compile(r"^\[(?:(\d{2})([A-Za-z]{3})(\d{4}) )?(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?\] \[[^\]]*\](?: \[[^\]]*\])?: (.*)$")
EVENT = re.compile(r"([A-Za-z0-9_.\-]{1,32}) (joined|left) the game$")
START = re.compile(r"Starting minecraft server version")
ROTATED = re.compile(r"(\d{4})-(\d{2})-(\d{2})-(\d+)\.log\.gz$")
MAX_FILES = 60
MAX_SESSION = 24 * 3600


def _ts(m, date):
    """datetime de una línea. date = fecha por defecto si la marca no la trae."""
    d, mon, y, hh, mm, ss = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5), m.group(6)
    if d:
        month = MONTHS.get(mon.lower())
        if not month:
            return None
        return dt.datetime(int(y), month, int(d), int(hh), int(mm), int(ss))
    return dt.datetime.combine(date, dt.time(int(hh), int(mm), int(ss)))


def parse(text, default_date):
    """Eventos (datetime, tipo, jugador) en orden: tipo = join | leave | start."""
    lines = [m for m in (LINE.match(l.rstrip("\r")) for l in text.split("\n")) if m]
    # Marcas cortas: cada vez que la hora retrocede mucho, es un día nuevo.
    rollovers, prev = 0, None
    for m in lines:
        if not m.group(1):
            t = (int(m.group(4)), int(m.group(5)))
            if prev and (prev[0] * 60 + prev[1]) - (t[0] * 60 + t[1]) > 12 * 60:
                rollovers += 1
            prev = t
    date = default_date - dt.timedelta(days=rollovers) if default_date and rollovers else default_date
    out, prev = [], None
    for m in lines:
        if not m.group(1):
            t = (int(m.group(4)), int(m.group(5)))
            if prev and (prev[0] * 60 + prev[1]) - (t[0] * 60 + t[1]) > 12 * 60:
                date += dt.timedelta(days=1)
            prev = t
        ts = _ts(m, date)
        if ts is None:
            continue
        msg = m.group(7)
        if START.search(msg):
            out.append((ts, "start", None))
            continue
        e = EVENT.fullmatch(msg.strip())
        if e:
            out.append((ts, "join" if e.group(2) == "joined" else "leave", e.group(1)))
        else:
            out.append((ts, "tick", None))  # solo sirve para saber el último instante visto
    return out


def sessions(events, online_at_end=False):
    """Lista de sesiones [(jugador, inicio, fin, abierta)] y jugadores conectados ahora."""
    open_, done, last = {}, [], None
    for ts, kind, who in events:
        if kind == "tick":
            last = ts
            continue
        last = ts
        if kind == "start":
            for p, s in open_.items():
                done.append((p, s, ts, False))  # el servidor se reinició sin 'left the game'
            open_.clear()
        elif kind == "join":
            if who in open_:
                done.append((who, open_[who], ts, False))
            open_[who] = ts
        elif kind == "leave" and who in open_:
            done.append((who, open_.pop(who), ts, False))
    online = []
    for p, s in open_.items():
        if online_at_end:
            online.append(p)
            done.append((p, s, last or s, True))
        else:
            done.append((p, s, last or s, False))
    return done, sorted(online)


def _split_hours(start, end):
    """Reparte [start, end) en trozos por hora: [(fecha, hora, segundos)]."""
    out, cur = [], start
    while cur < end:
        nxt = min(end, cur.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1))
        out.append((cur.date(), cur.hour, (nxt - cur).total_seconds()))
        cur = nxt
    return out


def compute(events, online_at_end=False, now=None):
    sess, online = sessions(events, online_at_end)
    players, hours, days = {}, [0.0] * 24, {}
    for who, s, e, _open in sess:
        secs = max(0.0, min((e - s).total_seconds(), MAX_SESSION))
        if secs <= 0 and s == e:
            pass
        e = s + dt.timedelta(seconds=secs)
        p = players.setdefault(who, {"name": who, "seconds": 0, "sessions": 0, "longest": 0, "last_seen": None})
        p["seconds"] += secs; p["sessions"] += 1; p["longest"] = max(p["longest"], secs)
        if p["last_seen"] is None or e > p["last_seen"]:
            p["last_seen"] = e
        for d, h, sec in _split_hours(s, e):
            hours[h] += sec
            days[d] = days.get(d, 0) + sec
    plist = sorted(players.values(), key=lambda x: -x["seconds"])
    for p in plist:
        p["seconds"], p["longest"] = int(p["seconds"]), int(p["longest"])
        p["last_seen"] = p["last_seen"].isoformat(timespec="seconds") if p["last_seen"] else None
        p["online"] = p["name"] in online
    last_days = sorted(days)[-30:]
    return {"players": plist, "hours": [int(h) for h in hours], "online": online,
            "days": [{"date": d.isoformat(), "seconds": int(days[d])} for d in last_days]}


# ---------- lectura de los logs del servidor ----------
_CACHE = {}


def _read(path):
    key = (str(path), path.stat().st_mtime_ns, path.stat().st_size)
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    opener = gzip.open if path.name.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    m = ROTATED.fullmatch(path.name)
    default = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else dt.date.fromtimestamp(path.stat().st_mtime)
    ev = parse(text, default)
    if len(_CACHE) > 200:
        _CACHE.clear()
    _CACHE[key] = ev
    return ev


def server_stats(logs_dir, running=False):
    d = Path(logs_dir)
    if not d.is_dir():
        return compute([])
    rotated = sorted((f for f in d.glob("*.log.gz") if ROTATED.fullmatch(f.name)), key=lambda f: ROTATED.fullmatch(f.name).groups())[-MAX_FILES:]
    files = list(rotated) + ([d / "latest.log"] if (d / "latest.log").exists() else [])
    events = []
    for f in files:
        try:
            events.extend(_read(f))
        except OSError:
            continue
    events.sort(key=lambda e: e[0])
    return compute(events, online_at_end=running)
