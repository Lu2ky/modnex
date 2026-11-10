"""Avisos a Discord por webhook: arranque, parada, caída y copias.

El webhook es una credencial: se guarda en la base de datos, nunca se devuelve completo a la
interfaz ni se escribe en logs. Solo se aceptan URLs de webhooks de Discord, para que esta función
no pueda usarse como salida hacia direcciones arbitrarias.
"""
import json
import re
import threading
import time
import urllib.request

SCHEMA = """
CREATE TABLE IF NOT EXISTS pro_notify (
  server TEXT PRIMARY KEY,
  webhook TEXT NOT NULL,
  events TEXT NOT NULL DEFAULT 'started,stopped,crashed,backup');
"""
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
    except Exception:
        return False  # un fallo de red no debe afectar al servidor
