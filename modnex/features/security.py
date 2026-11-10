"""Verificación en dos pasos (TOTP, RFC 6238) con códigos de recuperación.

- El secreto se guarda en la base de datos del gestor (archivo con permisos 600) porque hace falta
  para verificar; los códigos de recuperación se guardan solo como hash.
- Un código TOTP no se puede usar dos veces (anti-repetición) y se aceptan ±1 ventana de 30 s.
- Tras 5 códigos erróneos de un mismo usuario se bloquea su verificación 10 minutos, aunque el
  atacante cambie de IP.
- Para entrar a través del túnel (acceso remoto) la cuenta debe tener 2FA activado.
"""
import base64
import hashlib
import hmac
import re
import secrets
import struct
import threading
import time
from urllib.parse import quote

from . import qr

SCHEMA = """
CREATE TABLE IF NOT EXISTS pro_totp (
  user_id INTEGER PRIMARY KEY,
  secret TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 0,
  last_counter INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS pro_recovery (
  user_id INTEGER NOT NULL,
  code_hash TEXT NOT NULL,
  used INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, code_hash));
"""
STEP, DIGITS, WINDOW = 30, 6, 1
MAX_FAILS, LOCK_SECONDS, FAIL_WINDOW = 5, 600, 600
RECOVERY_COUNT = 8
_FAILS = {}
_LOCK = threading.Lock()


# ---------- TOTP ----------
def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret_b32):
    s = secret_b32.upper().replace(" ", "")
    return base64.b32decode(s + "=" * (-len(s) % 8))


def hotp(secret_b32, counter, digits=DIGITS):
    mac = hmac.new(_key(secret_b32), struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def totp(secret_b32, t=None, digits=DIGITS):
    return hotp(secret_b32, int((time.time() if t is None else t) // STEP), digits)


def uri(secret_b32, username):
    return f"otpauth://totp/Modnex:{quote(username, safe='')}?secret={secret_b32}&issuer=Modnex&algorithm=SHA1&digits={DIGITS}&period={STEP}"


def match_counter(secret_b32, code, now=None, after=0):
    """Contador cuyo código coincide (±WINDOW), o None. `after` impide repetir un código ya usado."""
    code = re.sub(r"\s+", "", str(code or ""))
    if not re.fullmatch(r"[0-9]{%d}" % DIGITS, code):  # solo dígitos ASCII (\d aceptaría otros alfabetos)
        return None
    c = int((time.time() if now is None else now) // STEP)
    found = None
    for cand in range(c - WINDOW, c + WINDOW + 1):
        if hmac.compare_digest(hotp(secret_b32, cand), code) and cand > after:
            found = cand if found is None else max(found, cand)
    return found


# ---------- recuperación ----------
def _norm(code):
    return re.sub(r"[^A-Z0-9]", "", str(code or "").upper())


def _hash(code):
    return hashlib.sha256(_norm(code).encode()).hexdigest()


def new_recovery_codes():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return ["".join(secrets.choice(alphabet) for _ in range(5)) + "-" + "".join(secrets.choice(alphabet) for _ in range(5))
            for _ in range(RECOVERY_COUNT)]


# ---------- bloqueo por usuario ----------
def locked(user_id, now=None):
    now = now or time.time()
    with _LOCK:
        rec = _FAILS.get(user_id)
        return bool(rec and rec[2] > now)


def register_fail(user_id, now=None):
    now = now or time.time()
    with _LOCK:
        rec = _FAILS.get(user_id)
        if not rec or now - rec[1] > FAIL_WINDOW:
            rec = _FAILS[user_id] = [0, now, 0]
        rec[0] += 1
        if rec[0] >= MAX_FAILS:
            rec[2] = now + LOCK_SECONDS


def clear_fails(user_id):
    with _LOCK:
        _FAILS.pop(user_id, None)


# ---------- almacenamiento ----------
def row(ctx, user_id):
    return ctx.db_run("SELECT * FROM pro_totp WHERE user_id = ?", (user_id,), one=True)


def status(ctx, user_id):
    r = row(ctx, user_id)
    left = ctx.db_run("SELECT COUNT(*) AS n FROM pro_recovery WHERE user_id = ? AND used = 0", (user_id,), one=True)["n"]
    return {"enabled": bool(r and r["enabled"]), "pending": bool(r and not r["enabled"]), "recovery_left": left if r and r["enabled"] else 0}


def begin(ctx, user):
    r = row(ctx, user["id"])
    if r and r["enabled"]:
        raise ValueError("la verificación en dos pasos ya está activada")
    secret = new_secret()
    with ctx.db_connect() as c:
        c.execute("INSERT INTO pro_totp(user_id, secret, enabled, last_counter, created_at) VALUES(?,?,0,0,?) "
                  "ON CONFLICT(user_id) DO UPDATE SET secret=excluded.secret, enabled=0, last_counter=0, created_at=excluded.created_at",
                  (user["id"], secret, int(time.time())))
        c.commit()
    link = uri(secret, user["username"])
    try:
        code = qr.svg(link)
    except qr.QRError:
        code = None            # nombre de usuario excesivamente largo: queda la clave manual
    return {"secret": secret, "uri": link, "qr": code}


def confirm(ctx, user, code):
    r = row(ctx, user["id"])
    if not r or r["enabled"]:
        raise ValueError("no hay una activación en curso")
    if locked(user["id"]):
        raise PermissionError("demasiados códigos incorrectos; espera unos minutos")
    counter = match_counter(r["secret"], code)
    if counter is None:
        register_fail(user["id"])
        raise ValueError("el código no es correcto")
    codes = new_recovery_codes()
    with ctx.db_connect() as c:
        c.execute("UPDATE pro_totp SET enabled = 1, last_counter = ? WHERE user_id = ?", (counter, user["id"]))
        c.execute("DELETE FROM pro_recovery WHERE user_id = ?", (user["id"],))
        c.executemany("INSERT INTO pro_recovery(user_id, code_hash) VALUES(?,?)", [(user["id"], _hash(x)) for x in codes])
        c.commit()
    clear_fails(user["id"])
    return codes


def _use_recovery(ctx, user_id, code):
    h = _hash(code)
    with ctx.db_connect() as c:
        cur = c.execute("UPDATE pro_recovery SET used = 1 WHERE user_id = ? AND code_hash = ? AND used = 0", (user_id, h))
        c.commit()
        return cur.rowcount == 1


def check_code(ctx, user_id, code):
    """True si el código es un TOTP válido (no repetido) o un código de recuperación sin usar."""
    r = row(ctx, user_id)
    if not r or not r["enabled"]:
        return False
    counter = match_counter(r["secret"], code, after=r["last_counter"])
    if counter is not None:
        with ctx.db_connect() as c:
            cur = c.execute("UPDATE pro_totp SET last_counter = ? WHERE user_id = ? AND last_counter < ?", (counter, user_id, counter))
            c.commit()
            return cur.rowcount == 1  # si dos peticiones usan el mismo código a la vez, solo una pasa
    return _use_recovery(ctx, user_id, code)


def disable(ctx, user, code):
    if locked(user["id"]):
        raise PermissionError("demasiados códigos incorrectos; espera unos minutos")
    if not check_code(ctx, user["id"], code):
        register_fail(user["id"])
        raise ValueError("el código no es correcto")
    remove(ctx, user["id"])


def remove(ctx, user_id):
    with ctx.db_connect() as c:
        c.execute("DELETE FROM pro_totp WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM pro_recovery WHERE user_id = ?", (user_id,))
        c.commit()
    clear_fails(user_id)


def admins_without_2fa(ctx):
    rows = ctx.db_run("SELECT u.username FROM users u LEFT JOIN pro_totp t ON t.user_id = u.id AND t.enabled = 1 "
                      "WHERE u.is_admin = 1 AND u.active = 1 AND t.user_id IS NULL ORDER BY u.username", many=True)
    return [r["username"] for r in rows]


# ---------- gancho del inicio de sesión ----------
def _remote_needs_2fa(ctx):
    try:
        return ctx.config().get("remote_2fa", ctx.config().get("pro_remote_2fa")) is not False
    except AttributeError:
        return True


def login_hook(ctx, user, body, remote, ip):
    """None = dejar pasar. Si no, (status, dict[, contar_fallo])."""
    enabled = bool((row(ctx, user["id"]) or {"enabled": 0})["enabled"])
    if remote and not enabled and _remote_needs_2fa(ctx):
        return 403, {"error": "para entrar desde fuera necesitas activar antes la verificación en dos pasos, desde la red local"}
    if not enabled:
        return None
    code = str((body or {}).get("otp") or "").strip()
    if not code:
        return 401, {"error": "escribe el código de verificación", "need_otp": True}
    if locked(user["id"]):
        return 429, {"error": "demasiados códigos incorrectos; espera unos minutos", "need_otp": True}
    if check_code(ctx, user["id"], code):
        clear_fails(user["id"])
        return None
    register_fail(user["id"])
    return 401, {"error": "código incorrecto", "need_otp": True}, True
