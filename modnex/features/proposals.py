"""Propuestas de mods: los jugadores piden un mod y el administrador lo aprueba o lo rechaza.

Instalar sigue siendo cosa del administrador, con la ficha del mod del panel (que resuelve las
dependencias). Aquí solo se gestiona la petición y su estado.
"""
import re
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS pro_proposals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  server TEXT NOT NULL,
  user_id INTEGER NOT NULL,
  username TEXT NOT NULL,
  source TEXT NOT NULL,
  project_id TEXT NOT NULL,
  slug TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL,
  icon TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  created_at INTEGER NOT NULL,
  decided_by TEXT NOT NULL DEFAULT '',
  decided_at INTEGER NOT NULL DEFAULT 0,
  reason TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS pro_proposals_server ON pro_proposals(server, status);
"""
SOURCES = ("modrinth", "curseforge")
ID_RE = re.compile(r"[A-Za-z0-9_\-]{1,40}")
MAX_PENDING_PER_USER = 5
MAX_PER_SERVER = 500


class ProposalError(Exception):
    pass


def _clean(text, n):
    return re.sub(r"[\r\n\t]+", " ", str(text or "")).strip()[:n]


def _icon_ok(url):
    return url if re.fullmatch(r"https://(?:cdn\.modrinth\.com|media\.forgecdn\.net|cdn\.curseforge\.com)/[\w./%\-]{1,300}", url or "") else ""


def create(ctx, server, user, source, project_id, title, slug="", icon="", note=""):
    if source not in SOURCES:
        raise ProposalError("proveedor no válido")
    if not ID_RE.fullmatch(str(project_id or "")):
        raise ProposalError("identificador de mod no válido")
    title = _clean(title, 120)
    if not title:
        raise ProposalError("falta el nombre del mod")
    if slug and not ID_RE.fullmatch(str(slug)):
        slug = ""
    pid = str(project_id)
    dup = ctx.db_run("SELECT status FROM pro_proposals WHERE server = ? AND source = ? AND project_id = ? AND status IN ('pending','approved')",
                     (server, source, pid), one=True)
    if dup:
        raise ProposalError("ese mod ya está propuesto" if dup["status"] == "pending" else "ese mod ya fue aprobado")
    n = ctx.db_run("SELECT COUNT(*) AS n FROM pro_proposals WHERE server = ? AND user_id = ? AND status = 'pending'", (server, user["id"]), one=True)["n"]
    if n >= MAX_PENDING_PER_USER:
        raise ProposalError(f"tienes {MAX_PENDING_PER_USER} propuestas pendientes; espera a que se resuelvan")
    if ctx.db_run("SELECT COUNT(*) AS n FROM pro_proposals WHERE server = ?", (server,), one=True)["n"] >= MAX_PER_SERVER:
        raise ProposalError("este servidor tiene demasiadas propuestas; el administrador debe limpiar la lista")
    with ctx.db_connect() as c:
        cur = c.execute("INSERT INTO pro_proposals(server, user_id, username, source, project_id, slug, title, icon, note, created_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (server, user["id"], user["username"], source, pid, slug or "", title, _icon_ok(icon), _clean(note, 300), int(time.time())))
        c.commit()
        return cur.lastrowid


def list_for(ctx, server):
    rows = ctx.db_run("SELECT * FROM pro_proposals WHERE server = ? ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, created_at DESC LIMIT 300", (server,), many=True)
    return [dict(r) for r in rows]


def decide(ctx, server, admin, pid, decision, reason=""):
    if decision not in ("approve", "reject"):
        raise ProposalError("decisión no válida")
    r = ctx.db_run("SELECT status FROM pro_proposals WHERE id = ? AND server = ?", (int(pid), server), one=True)
    if not r:
        raise ProposalError("esa propuesta no existe")
    if r["status"] != "pending":
        raise ProposalError("esa propuesta ya se resolvió")
    status = "approved" if decision == "approve" else "rejected"
    with ctx.db_connect() as c:
        c.execute("UPDATE pro_proposals SET status = ?, decided_by = ?, decided_at = ?, reason = ? WHERE id = ?",
                  (status, admin["username"], int(time.time()), _clean(reason, 200), int(pid)))
        c.commit()
    return status


def withdraw(ctx, server, user, pid):
    r = ctx.db_run("SELECT user_id, status FROM pro_proposals WHERE id = ? AND server = ?", (int(pid), server), one=True)
    if not r:
        raise ProposalError("esa propuesta no existe")
    if r["user_id"] != user["id"] and not user.get("is_admin"):
        raise ProposalError("solo quien la propuso puede retirarla")
    if r["status"] != "pending":
        raise ProposalError("solo se pueden retirar propuestas pendientes")
    with ctx.db_connect() as c:
        c.execute("DELETE FROM pro_proposals WHERE id = ?", (int(pid),))
        c.commit()


def search_results(raw):
    """Reduce los resultados del buscador del núcleo a lo que la interfaz necesita."""
    out = []
    for r in raw or []:
        pid = str(r.get("id") or "")
        if not ID_RE.fullmatch(pid):
            continue
        out.append({"source": r.get("source") or "modrinth", "project_id": pid, "slug": r.get("slug") or "",
                    "title": _clean(r.get("name"), 120), "description": _clean(r.get("summary"), 200),
                    "icon": _icon_ok(r.get("icon") or ""), "downloads": r.get("downloads", 0)})
    return out[:20]
