"""Base de datos SQLite del gestor: usuarios, servidores, permisos, sesiones y auditoría."""
import hashlib
import hmac
import json
import re
import secrets
import os
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

DB_FILE = Path(os.environ.get("MANAGER_DB") or Path(__file__).resolve().parent / "manager.db")
SESSION_TTL = 30 * 24 * 3600
PBKDF2_ITERS = 200_000
PERMS = ("logs", "mods", "datapacks", "textures", "players", "control")
# Nombres de iconos asignables a un servidor; el dibujo vive en static/icons.js.
ICONS = ["vanilla", "forge", "neoforge", "fabric", "quilt", "paper", "bukkit", "spigot", "purpur",
         "velocity", "sponge", "mohist", "catserver", "arclight", "thermos", "modded", "liteloader", "custom",
         "unknown", "disabled"]
USERNAME_RE = re.compile(r"[A-Za-z0-9_.-]{3,32}")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  pw_salt BLOB NOT NULL, pw_hash BLOB NOT NULL,
  is_admin INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS servers (
  name TEXT PRIMARY KEY,
  display_name TEXT,
  icon TEXT NOT NULL DEFAULT 'pokeball');
CREATE TABLE IF NOT EXISTS permissions (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  server_name TEXT NOT NULL REFERENCES servers(name) ON DELETE CASCADE,
  can_logs INTEGER NOT NULL DEFAULT 0,
  can_mods INTEGER NOT NULL DEFAULT 0,
  can_datapacks INTEGER NOT NULL DEFAULT 0,
  can_textures INTEGER NOT NULL DEFAULT 0,
  can_players INTEGER NOT NULL DEFAULT 0,
  can_control INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, server_name));
CREATE TABLE IF NOT EXISTS packs (
  token TEXT PRIMARY KEY,
  server_name TEXT NOT NULL,
  filename TEXT NOT NULL,
  sha1 TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  UNIQUE (server_name, filename));
CREATE TABLE IF NOT EXISTS client_builds (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  server_name TEXT NOT NULL, filename TEXT NOT NULL, version TEXT NOT NULL, fmt TEXT NOT NULL,
  minecraft TEXT, loader_version TEXT,
  included TEXT NOT NULL, server_mods TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL, username TEXT, server_name TEXT,
  action TEXT NOT NULL, detail TEXT);
"""


def _connect():
    c = sqlite3.connect(DB_FILE, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


def run(sql, args=(), one=False, many=False):
    """Ejecuta una consulta y hace commit. Devuelve una fila, una lista o el id insertado."""
    with closing(_connect()) as c:
        cur = c.execute(sql, args)
        c.commit()
        if one:
            r = cur.fetchone()
            return dict(r) if r else None
        if many:
            return [dict(r) for r in cur.fetchall()]
        return cur.lastrowid


def init():
    with closing(_connect()) as c:
        c.execute("PRAGMA journal_mode = WAL")
        c.executescript(SCHEMA)
        have = {r[1] for r in c.execute("PRAGMA table_info(permissions)")}
        for p in PERMS:
            if f"can_{p}" not in have:
                c.execute(f"ALTER TABLE permissions ADD COLUMN can_{p} INTEGER NOT NULL DEFAULT 0")
        c.commit()
    try:
        DB_FILE.chmod(0o600)
    except OSError:
        pass


# ---------- contraseñas ----------

def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERS)


def _check_password_rules(password):
    if len(password) < 8 or len(password) > 128:
        raise ValueError("la contraseña debe tener entre 8 y 128 caracteres")


# ---------- usuarios ----------

def user_count():
    return run("SELECT COUNT(*) AS n FROM users", one=True)["n"]


def create_user(username, password, is_admin=False):
    if not USERNAME_RE.fullmatch(username or ""):
        raise ValueError("usuario no válido (3-32 caracteres: letras, números, . _ -)")
    _check_password_rules(password)
    salt = secrets.token_bytes(16)
    try:
        return run("INSERT INTO users (username, pw_salt, pw_hash, is_admin, created_at) VALUES (?,?,?,?,?)",
                   (username, salt, _hash(password, salt), int(bool(is_admin)), int(time.time())))
    except sqlite3.IntegrityError:
        raise ValueError("ese usuario ya existe")


def bootstrap_admin(initial_password):
    """Crea el administrador inicial si la base de datos está vacía."""
    if user_count() == 0:
        create_user("admin", initial_password, is_admin=True)
        return True
    return False


def _public(u):
    return {"id": u["id"], "username": u["username"], "is_admin": bool(u["is_admin"]), "active": bool(u["active"])}


def get_user(user_id):
    u = run("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    return _public(u) if u else None


def list_users():
    users = run("SELECT * FROM users ORDER BY username COLLATE NOCASE", many=True)
    perms = run("SELECT * FROM permissions", many=True)
    out = []
    for u in users:
        p = {r["server_name"]: _row_perms(r) for r in perms if r["user_id"] == u["id"]}
        out.append({**_public(u), "permissions": p})
    return out


def admin_count():
    return run("SELECT COUNT(*) AS n FROM users WHERE is_admin = 1 AND active = 1", one=True)["n"]


def update_user(user_id, password=None, is_admin=None, active=None):
    u = get_user(user_id)
    if not u:
        raise LookupError("usuario no encontrado")
    removing_admin = u["is_admin"] and u["active"] and (is_admin is False or active is False)
    if removing_admin and admin_count() <= 1:
        raise ValueError("debe quedar al menos un administrador activo")
    if password is not None:
        _check_password_rules(password)
        salt = secrets.token_bytes(16)
        run("UPDATE users SET pw_salt=?, pw_hash=? WHERE id=?", (salt, _hash(password, salt), user_id))
        run("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    if is_admin is not None:
        run("UPDATE users SET is_admin=? WHERE id=?", (int(bool(is_admin)), user_id))
    if active is not None:
        run("UPDATE users SET active=? WHERE id=?", (int(bool(active)), user_id))
        if not active:
            run("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def delete_user(user_id):
    u = get_user(user_id)
    if not u:
        raise LookupError("usuario no encontrado")
    if u["is_admin"] and u["active"] and admin_count() <= 1:
        raise ValueError("debe quedar al menos un administrador activo")
    run("DELETE FROM users WHERE id = ?", (user_id,))


# ---------- autenticación y sesiones ----------

_DUMMY_SALT = secrets.token_bytes(16)
_FAILS = {}  # ip -> [intentos, inicio_ventana, bloqueado_hasta]
_FAILS_LOCK = threading.Lock()
MAX_FAILS, WINDOW, LOCKOUT = 5, 300, 300


def login_blocked(ip):
    with _FAILS_LOCK:
        rec = _FAILS.get(ip)
        return bool(rec and rec[2] > time.time())


def _register_fail(ip):
    now = time.time()
    with _FAILS_LOCK:
        rec = _FAILS.get(ip)
        if not rec or now - rec[1] > WINDOW:
            rec = _FAILS[ip] = [0, now, 0]
        rec[0] += 1
        if rec[0] >= MAX_FAILS:
            rec[2] = now + LOCKOUT


def authenticate(username, password, ip="?"):
    """Devuelve el usuario si las credenciales son válidas. Tiempo similar exista o no el usuario."""
    if login_blocked(ip):
        raise PermissionError("demasiados intentos; espera unos minutos")
    u = run("SELECT * FROM users WHERE username = ?", (username or "",), one=True)
    salt = u["pw_salt"] if u else _DUMMY_SALT
    candidate = _hash(password or "", salt)
    ok = bool(u) and hmac.compare_digest(candidate, u["pw_hash"]) and bool(u["active"])
    if not ok:
        _register_fail(ip)
        return None
    with _FAILS_LOCK:
        _FAILS.pop(ip, None)
    return _public(u)


def create_session(user_id):
    token = secrets.token_urlsafe(32)
    run("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?,?,?)",
        (hashlib.sha256(token.encode()).hexdigest(), user_id, int(time.time()) + SESSION_TTL))
    run("DELETE FROM sessions WHERE expires_at < ?", (int(time.time()),))
    return token


def user_for_token(token):
    if not token:
        return None
    row = run("""SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
                 WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1""",
              (hashlib.sha256(token.encode()).hexdigest(), int(time.time())), one=True)
    return _public(row) if row else None


def delete_session(token):
    if token:
        run("DELETE FROM sessions WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))


def verify_password(user_id, password):
    u = run("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    return bool(u) and hmac.compare_digest(_hash(password or "", u["pw_salt"]), u["pw_hash"])


# ---------- servidores y permisos ----------

def sync_servers(names):
    for n in names:
        run("INSERT OR IGNORE INTO servers (name) VALUES (?)", (n,))


def server_meta():
    return {r["name"]: {"display_name": r["display_name"], "icon": r["icon"]}
            for r in run("SELECT * FROM servers", many=True)}


def set_server_meta(name, display_name, icon):
    if icon not in ICONS:
        raise ValueError("icono no válido")
    display_name = (display_name or "").strip()[:40] or None
    run("INSERT OR IGNORE INTO servers (name) VALUES (?)", (name,))
    run("UPDATE servers SET display_name=?, icon=? WHERE name=?", (display_name, icon, name))


def _row_perms(r):
    return {p: bool(r[f"can_{p}"]) for p in PERMS}


def _upsert_permissions(c, user_id, server_name, perms):
    flags = [int(bool(perms.get(p))) for p in PERMS]
    if not any(flags):
        c.execute("DELETE FROM permissions WHERE user_id=? AND server_name=?", (user_id, server_name))
        return
    c.execute("INSERT OR IGNORE INTO servers (name) VALUES (?)", (server_name,))
    cols = ", ".join(f"can_{p}" for p in PERMS)
    marks = ", ".join("?" for _ in PERMS)
    sets = ", ".join(f"can_{p}=excluded.can_{p}" for p in PERMS)
    c.execute(f"INSERT INTO permissions (user_id, server_name, {cols}) VALUES (?, ?, {marks}) "
              f"ON CONFLICT(user_id, server_name) DO UPDATE SET {sets}", (user_id, server_name, *flags))


def set_permissions(user_id, server_name, perms):
    """Permisos de un usuario sobre un servidor. perms: {logs, mods, datapacks, textures, players}."""
    if not get_user(user_id):
        raise LookupError("usuario no encontrado")
    with closing(_connect()) as c:
        _upsert_permissions(c, user_id, server_name, perms)
        c.commit()


def set_all_permissions(user_id, perms_by_server):
    """Sustituye de una vez todos los permisos del usuario (guardado explícito desde el panel)."""
    if not get_user(user_id):
        raise LookupError("usuario no encontrado")
    with closing(_connect()) as c:
        c.execute("DELETE FROM permissions WHERE user_id=?", (user_id,))
        for server_name, perms in perms_by_server.items():
            _upsert_permissions(c, user_id, server_name, perms)
        c.commit()


def user_perms(user_id):
    return {r["server_name"]: _row_perms(r)
            for r in run("SELECT * FROM permissions WHERE user_id = ?", (user_id,), many=True)}


def can(user, server, perm):
    if not user:
        return False
    if user["is_admin"]:
        return True
    if perm not in PERMS:
        return False
    return bool(user_perms(user["id"]).get(server, {}).get(perm))


def can_any(user, perm):
    if user["is_admin"]:
        return True
    return any(p.get(perm) for p in user_perms(user["id"]).values())


# ---------- auditoría ----------

def audit(user, server, action, detail=None):
    run("INSERT INTO audit (ts, username, server_name, action, detail) VALUES (?,?,?,?,?)",
        (int(time.time()), user["username"] if isinstance(user, dict) else user, server, action,
         (detail or "")[:300]))


def recent_audit(limit=100):
    return run("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),), many=True)


# ---------- packs de texturas locales (se sirven por una ruta con token) ----------

def pack_add(server_name, filename, sha1):
    old = run("SELECT token FROM packs WHERE server_name=? AND filename=?", (server_name, filename), one=True)
    token = old["token"] if old else secrets.token_urlsafe(18)
    if old:
        run("UPDATE packs SET sha1=? WHERE token=?", (sha1, token))
    else:
        run("INSERT INTO packs (token, server_name, filename, sha1, created_at) VALUES (?,?,?,?,?)",
            (token, server_name, filename, sha1, int(time.time())))
    return token


def pack_lookup(token, filename):
    return run("SELECT * FROM packs WHERE token=? AND filename=?", (token, filename), one=True)


def packs_for(server_name):
    return run("SELECT * FROM packs WHERE server_name=? ORDER BY created_at DESC", (server_name,), many=True)


def pack_delete(server_name, filename):
    run("DELETE FROM packs WHERE server_name=? AND filename=?", (server_name, filename))


# ---------- versiones del cliente generadas ----------

def add_build(server_name, filename, version, fmt, minecraft, loader_version, included, server_mods):
    run("INSERT INTO client_builds (server_name, filename, version, fmt, minecraft, loader_version, included, server_mods, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (server_name, filename, version, fmt, minecraft, loader_version, json.dumps(included),
         json.dumps(server_mods), int(time.time())))


def builds_for(server_name, limit=10):
    out = []
    for r in run("SELECT * FROM client_builds WHERE server_name=? ORDER BY id DESC LIMIT ?", (server_name, limit), many=True):
        r["included"] = json.loads(r["included"])
        r["server_mods"] = json.loads(r["server_mods"])
        out.append(r)
    return out


def delete_server_records(server_name):
    """Quita un servidor del registro; sus permisos, packs y builds de cliente se borran en cascada."""
    with closing(_connect()) as c:
        c.execute("DELETE FROM packs WHERE server_name = ?", (server_name,))
        c.execute("DELETE FROM client_builds WHERE server_name = ?", (server_name,))
        c.execute("DELETE FROM permissions WHERE server_name = ?", (server_name,))
        c.execute("DELETE FROM servers WHERE name = ?", (server_name,))
        c.commit()
