"""Avisos a Discord por webhook: arranque, parada, caída y copias.

Un aviso se intenta enviar al momento; si Discord no responde (sin red, 5xx, 429), se guarda en una cola persistente
(`pro_notify_outbox`) y `drain()` lo reintenta con espera creciente, así una caída de Discord no hace perder el aviso
de que el servidor se cayó. Las entradas y salidas de jugadores no se encolan: no merece la pena entregarlas tarde.

El webhook es una credencial: se guarda en la base de datos, nunca se devuelve completo a la
interfaz ni se escribe en logs. Solo se aceptan URLs de webhooks de Discord, para que esta función
no pueda usarse como salida hacia direcciones arbitrarias.
"""
import json
import re
import threading
import time
import urllib.error
import urllib.request

SCHEMA = """
CREATE TABLE IF NOT EXISTS pro_notify (
  server TEXT PRIMARY KEY,
  webhook TEXT NOT NULL,
  events TEXT NOT NULL DEFAULT 'started,stopped,crashed,backup');
CREATE TABLE IF NOT EXISTS pro_notify_outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  server TEXT NOT NULL, text TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0, next_try INTEGER NOT NULL, created INTEGER NOT NULL);
"""
MAX_ATTEMPTS = 8
MAX_AGE = 24 * 3600
EPHEMERAL = ("players",)      # no se encolan
WEBHOOK_RE = re.compile(r"https://(?:discord|discordapp)\.com/api/webhooks/\d{5,25}/[A-Za-z0-9_-]{20,120}")
EVENTS = ("started", "stopped", "crashed", "backup", "players", "proposals")
_LAST = {}
_SENT = {}
MAX_PER_MINUTE = 20
_LAST_LOCK = threading.Lock()


def valid_webhook(url):
    return bool(WEBHOOK_RE.fullmatch(url or ""))


def _mask(url):
    m = re.match(r"(https://[^/]+/api/webhooks/\d+/)(.*)", url or "")
    return (m.group(1) + m.group(2)[:4] + "…") if m else ""


def get(ctx, name):
    r = ctx.db_run("SELECT webhook, events FROM pro_notify WHERE server = ?", (name,), one=True)
    if not r:
        return {"configured": False, "events": list(EVENTS), "webhook": ""}
    return {"configured": True, "events": [e for e in r["events"].split(",") if e in EVENTS], "webhook": _mask(r["webhook"])}


def set_config(ctx, name, webhook, events):
    if not valid_webhook(webhook):
        raise ValueError("el webhook debe ser una URL de webhook de Discord (https://discord.com/api/webhooks/…)")
    ev = [e for e in (events or EVENTS) if e in EVENTS]
    with ctx.db_connect() as c:
        c.execute("INSERT INTO pro_notify(server, webhook, events) VALUES(?,?,?) "
                  "ON CONFLICT(server) DO UPDATE SET webhook=excluded.webhook, events=excluded.events",
                  (name, webhook, ",".join(ev)))
        c.commit()


def remove(ctx, name):
    with ctx.db_connect() as c:
        c.execute("DELETE FROM pro_notify WHERE server = ?", (name,))
        c.commit()


def _post(url, text):
    payload = {"username": "Modnex", "content": text[:1800], "allowed_mentions": {"parse": []}}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "Modnex"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return 200 <= r.status < 300


def send(ctx, name, event, text, force=False):
    """Envía un aviso si el servidor tiene webhook y ese evento activo. Devuelve True si se envió."""
    r = ctx.db_run("SELECT webhook, events FROM pro_notify WHERE server = ?", (name,), one=True)
    if not r or not valid_webhook(r["webhook"]):
        return False
    if not force and event not in r["events"].split(","):
        return False
    with _LAST_LOCK:
        now = time.time()
        # como mucho un aviso del mismo tipo cada 2 s por servidor (las entradas de jugadores distintos no se pisan)
        key = (name, event, text if event == "players" else "")
        if not force and now - _LAST.get(key, 0) < 2:
            return False
        # y un tope general por servidor, para que una avalancha no sature el webhook
        recent = [t for t in _SENT.get(name, []) if now - t < 60]
        if not force and len(recent) >= MAX_PER_MINUTE:
            _SENT[name] = recent
            return False
        recent.append(now)
        _SENT[name] = recent
        _LAST[key] = now
    try:
        return _post(r["webhook"], text)
    except Exception as e:
        if not force and event not in EPHEMERAL and _retryable(e):
            _enqueue(ctx, name, text)
        return False  # un fallo de red no debe afectar al servidor


def _retryable(exc):
    """Reintentar errores de red y 5xx o 429; un 4xx (webhook borrado, texto no válido) no se arregla esperando."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500 or exc.code == 429
    return isinstance(exc, OSError)


def _backoff(attempts):
    return min(30 * 2 ** attempts, 1800)


def _enqueue(ctx, name, text, now=None):
    now = int(now or time.time())
    with ctx.db_connect() as c:
        c.execute("INSERT INTO pro_notify_outbox(server, text, attempts, next_try, created) VALUES(?,?,0,?,?)",
                  (name, text[:1800], now + _backoff(0), now))
        c.commit()


def drain(ctx, now=None, post=None):
    """Reintenta los avisos pendientes que ya tocan. Devuelve cuántos se entregaron. Descarta los que llevan demasiado
    tiempo o demasiados intentos, o cuyo servidor ya no tiene webhook."""
    now = int(now or time.time())
    post = post or _post
    sent = 0
    for row in ctx.db_run("SELECT * FROM pro_notify_outbox WHERE next_try <= ? ORDER BY id LIMIT 20", (now,), many=True):
        hook = ctx.db_run("SELECT webhook FROM pro_notify WHERE server = ?", (row["server"],), one=True)
        done = not hook or not valid_webhook(hook["webhook"]) or now - row["created"] > MAX_AGE
        if not done:
            try:
                post(hook["webhook"], row["text"])
                done, sent = True, sent + 1
            except Exception as e:
                done = not _retryable(e) or row["attempts"] + 1 >= MAX_ATTEMPTS
        with ctx.db_connect() as c:
            if done:
                c.execute("DELETE FROM pro_notify_outbox WHERE id = ?", (row["id"],))
            else:
                c.execute("UPDATE pro_notify_outbox SET attempts = attempts + 1, next_try = ? WHERE id = ?",
                          (now + _backoff(row["attempts"] + 1), row["id"]))
            c.commit()
    return sent
