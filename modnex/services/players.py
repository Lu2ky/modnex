"""Jugadores: conectados, listas del servidor y acciones por consola."""

import json
import re
import time

from modnex.services.properties import read_properties
from modnex.services.servers import send_command, server_path, status


PLAYER_RE = re.compile(r"[A-Za-z0-9_.]{1,20}")


PLAYER_ACTIONS = {"tell", "say", "kick", "ban", "pardon", "op", "deop", "whitelist_add", "whitelist_remove"}


def _json_list(path):
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _query_online(name, wait=2.5):
    """Envía `list` a la consola y lee la respuesta del log. Solo si el gestor controla el proceso."""
    p = server_path(name)
    lf = p / "logs" / "latest.log"
    size = lf.stat().st_size if lf.exists() else 0
    send_command(name, "list")
    rx = re.compile(r"There are (\d+) of a max of (\d+) players online:\s*(.*)$", re.M)
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(0.25)
        if lf.exists() and lf.stat().st_size > size:
            with open(lf, "rb") as fh:
                fh.seek(size)
                m = rx.search(fh.read().decode("utf-8", "replace"))
            if m:
                return [n.strip() for n in m.group(3).split(",") if n.strip()], int(m.group(2))
    return None, None


def players_info(name):
    p = server_path(name)
    st = status(name)
    known = {e["name"] for e in _json_list(p / "usercache.json") if isinstance(e, dict) and e.get("name")}
    ops = {e["name"] for e in _json_list(p / "ops.json") if isinstance(e, dict) and e.get("name")}
    bans = {e["name"]: e for e in _json_list(p / "banned-players.json") if isinstance(e, dict) and e.get("name")}
    wl = {e["name"] for e in _json_list(p / "whitelist.json") if isinstance(e, dict) and e.get("name")}
    online, max_players = (None, None)
    if st["running"] and st["control"]:
        online, max_players = _query_online(name)
    names = sorted(known | ops | wl | set(bans) | set(online or []), key=str.lower)
    return {
        "running": st["running"], "control": st["control"], "max": max_players,
        "online_count": len(online) if online is not None else None,
        "whitelist_enabled": read_properties(name).get("white-list") == "true",
        "players": [{"name": n, "online": (n in online) if online is not None else None, "op": n in ops,
                     "banned": n in bans, "ban_reason": (bans.get(n) or {}).get("reason"),
                     "whitelisted": n in wl} for n in names]}


def player_action(name, action, player=None, text=""):
    if action not in PLAYER_ACTIONS:
        raise ValueError("acción no válida")
    text = (text or "").strip()
    if len(text) > 200 or re.search(r"[\x00-\x1f\x7f]", text):
        raise ValueError("el texto no es válido (máximo 200 caracteres, sin saltos de línea)")
    if action != "say" and not PLAYER_RE.fullmatch(player or ""):
        raise ValueError("nombre de jugador no válido")
    if action in ("say", "tell") and not text:
        raise ValueError("escribe un mensaje")
    cmd = {"say": f"say {text}", "tell": f"tell {player} {text}", "kick": f"kick {player} {text}".strip(),
           "ban": f"ban {player} {text}".strip(), "pardon": f"pardon {player}", "op": f"op {player}",
           "deop": f"deop {player}", "whitelist_add": f"whitelist add {player}",
           "whitelist_remove": f"whitelist remove {player}"}[action]
    send_command(name, cmd)
    return cmd
