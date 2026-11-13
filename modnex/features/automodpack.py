"""AutoModpack 5: qué archivos de KubeJS reciben los jugadores y cómo dejar fuera los que solo usa el servidor.

AutoModpack 5 se configura en `automodpack/server.conf` (texto tipo HOCON). Con `from-server: [..., kubejs/**]` publica toda la carpeta
`kubejs/` a los clientes, y cada vez que el panel escribe allí (estado del panel, datapacks de botín y recetas) los jugadores reciben
una actualización que no necesitan. Aquí se lee ese archivo, se calcula qué archivos de KubeJS se publicarían y se añaden a la lista
`exclude` solo las rutas que son del servidor. La edición es quirúrgica: el resto del archivo no se toca, y antes se guarda una copia.
"""
import os
import re
import threading
from pathlib import Path

CONF = "automodpack/server.conf"
BACKUP = "automodpack/server.conf.modnex.bak"
# Rutas de kubejs/ que solo usa el servidor: ningún cliente las necesita.
SERVER_ONLY = (
    ("kubejs/server_scripts/**", "scripts del servidor"),
    ("kubejs/modnex/**", "estado interno del panel"),
    ("kubejs/data/**", "recetas y botín del servidor"),
)
# Lo que sí usa el cliente: cambiar estos archivos sí pide actualizar, y los de startup además piden reiniciar el juego.
CLIENT_SIDE = ("kubejs/client_scripts/**", "kubejs/startup_scripts/**", "kubejs/assets/**")
MAX_FILES = 6000
_LOCK = threading.Lock()


# ---------- lectura del archivo ----------
def _split_top(body):
    """Separa los elementos de una lista por comas fuera de comillas y de llaves (`**/*.{tmp,bak}`)."""
    items, cur, depth, quote = [], [], 0, ""
    for ch in body:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch; cur.append(ch)
        elif ch == "{":
            depth += 1; cur.append(ch)
        elif ch == "}":
            depth -= 1; cur.append(ch)
        elif ch in ",\n" and depth == 0:
            items.append("".join(cur)); cur = []
        else:
            cur.append(ch)
    items.append("".join(cur))
    out = []
    for it in items:
        it = it.strip()
        if len(it) >= 2 and it[0] == it[-1] and it[0] in "\"'":
            it = it[1:-1]
        if it and not it.startswith("#"):
            out.append(it)
    return out


def _lists(text, key):
    """[(inicio, fin, [elementos], línea)] de cada `key: [ ... ]` del archivo; inicio y fin son los de lo que hay dentro de los corchetes."""
    found = []
    for m in re.finditer(r"(?m)^([ \t]*)" + re.escape(key) + r"[ \t]*[:=][ \t]*\[", text):
        start = m.end()
        depth, quote, i = 1, "", start
        while i < len(text) and depth:
            ch = text[i]
            if quote:
                if ch == quote:
                    quote = ""
            elif ch in "\"'":
                quote = ch
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
            i += 1
        if depth == 0:
            found.append((start, i - 1, _split_top(text[start:i - 1]), m.group(1)))
    return found


def parse(text):
    """[{from_server: [...], exclude: [...]}] una entrada por cada `from-server` (un grupo de archivos del paquete)."""
    froms = _lists(text, "from-server")
    excludes = _lists(text, "exclude")
    groups = []
    for n, (s, e, items, _) in enumerate(froms):
        limit = froms[n + 1][0] if n + 1 < len(froms) else len(text) + 1
        ex = next((x for x in excludes if s < x[0] < limit), None)
        groups.append({"from_server": items, "exclude": ex[2] if ex else []})
    return groups


# ---------- patrones ----------
def _glob(pattern):
    """Patrón de AutoModpack a expresión regular: `**` cruza carpetas, `*` y `?` no, `{a,b}` elige."""
    out, i, n = [], 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern[i:i + 3] == "**/":
                out.append("(?:.*/)?"); i += 3; continue
            if pattern[i:i + 2] == "**":
                out.append(".*"); i += 2; continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "{":
            j = pattern.find("}", i)
            if j == -1:
                out.append(re.escape(c))
            else:
                out.append("(?:" + "|".join(re.escape(p) for p in pattern[i + 1:j].split(",")) + ")"); i = j
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("".join(out))


def _matches(path, patterns):
    return any(_glob(p).fullmatch(path) for p in patterns)


def _kubejs_files(root):
    base = Path(root) / "kubejs"
    out = []
    for dirpath, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            out.append(Path(dirpath, f).relative_to(root).as_posix())
            if len(out) >= MAX_FILES:
                return out
    return sorted(out)


# ---------- análisis y arreglo ----------
def _conf(ctx, name):
    return Path(ctx.server_path(name)) / CONF


def analyze(ctx, name):
    """Qué archivos de kubejs/ se publican a los jugadores y cuáles de ellos son solo del servidor."""
    path = _conf(ctx, name)
    root = Path(ctx.server_path(name))
    if not path.is_file():
        return {"configured": False, "published": [], "leaks": [], "client_files": [], "missing": [], "format": None}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {"configured": False, "published": [], "leaks": [], "client_files": [], "missing": [], "format": "unreadable"}
    groups = parse(text)
    files = _kubejs_files(root)
    published = []
    for f in files:
        if any(_matches(f, g["from_server"]) and not _matches(f, g["exclude"]) for g in groups):
            published.append(f)
    server_patterns = [p for p, _ in SERVER_ONLY]
    leaks = [f for f in published if _matches(f, server_patterns)]
    covers = any(_matches("kubejs/x", g["from_server"]) or _matches("kubejs/a/b", g["from_server"]) for g in groups)
    missing = []
    if covers:
        for pat, why in SERVER_ONLY:
            if any(pat not in g["exclude"] for g in groups if _matches("kubejs/a/b", g["from_server"])):
                missing.append({"pattern": pat, "why": why, "files": len([f for f in leaks if _glob(pat).fullmatch(f)])})
    return {"configured": True, "format": "conf", "publishes_kubejs": covers, "published": published[:200], "published_count": len(published),
            "leaks": leaks[:200], "leak_count": len(leaks), "missing": missing,
            "client_files": [f for f in published if _matches(f, list(CLIENT_SIDE))][:50]}


def _insert(text, add):
    """Texto con las rutas `add` añadidas a cada `exclude` de un grupo que publica kubejs/ (o con un `exclude` nuevo si no lo tiene)."""
    froms = _lists(text, "from-server")
    excludes = _lists(text, "exclude")
    edits = []                                    # (posición, texto a insertar)
    for n, (s, e, items, indent) in enumerate(froms):
        if not (_matches("kubejs/a/b", items)):
            continue
        limit = froms[n + 1][0] if n + 1 < len(froms) else len(text) + 1
        ex = next((x for x in excludes if s < x[0] < limit), None)
        if ex:
            have = set(ex[2])
            new = [p for p in add if p not in have]
            if new:
                inner = text[ex[0]:ex[1]]
                if "\n" in inner:                 # lista en varias líneas: una por línea, con la misma sangría
                    tail = inner.rstrip()
                    edits.append((ex[0] + len(tail), "".join(f"\n{indent}  {p}" for p in new) if not tail.endswith(",") else "".join(f"\n{indent}  {p}," for p in new)))
                else:
                    sep = "" if not inner.strip() else ", "
                    edits.append((ex[1], sep + ", ".join(new)))
        else:
            line_end = text.index("\n", e) if "\n" in text[e:] else len(text)
            edits.append((line_end, f"\n{indent}exclude: [{', '.join(add)}]"))
    for pos, ins in sorted(edits, reverse=True):
        text = text[:pos] + ins + text[pos:]
    return text, bool(edits)


def fix(ctx, name):
    """Deja fuera de AutoModpack lo que solo usa el servidor. Guarda una copia del archivo y solo toca la lista `exclude`."""
    path = _conf(ctx, name)
    if not path.is_file():
        raise ValueError("este servidor no tiene automodpack/server.conf (AutoModpack 5)")
    with _LOCK:
        text = path.read_text(encoding="utf-8")
        before = analyze(ctx, name)
        if not before.get("publishes_kubejs"):
            raise ValueError("AutoModpack no publica la carpeta kubejs/ en este servidor: no hay nada que excluir")
        new, changed = _insert(text, [p for p, _ in SERVER_ONLY])
        if not changed:
            return {"changed": False, **before}
        parse(new)                                 # debe seguir leyéndose igual
        bak = Path(ctx.server_path(name)) / BACKUP
        bak.write_text(text, encoding="utf-8")
        tmp = path.with_suffix(".conf.tmp")
        tmp.write_text(new, encoding="utf-8")
        os.replace(tmp, path)
    after = analyze(ctx, name)
    return {"changed": True, "backup": BACKUP, **after}
