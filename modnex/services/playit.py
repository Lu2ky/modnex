"""Túneles de playit para los servidores creados desde el panel.

La clave del agente de playit se lee de su archivo (por defecto /etc/playit/playit.toml) cada vez que hace falta: no se guarda
en la base de datos, en el repositorio ni en los registros. Si playit no está configurado o la API falla, la creación del servidor
sigue adelante y el error queda registrado en el servidor.

Cada servidor guarda el id de su túnel en `.modnex-playit.json` dentro de su carpeta.
"""
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.playit.gg"
SECRET_PATH = Path(os.environ.get("MODNEX_PLAYIT_SECRET", "/etc/playit/playit.toml"))
RECORD = ".modnex-playit.json"
TUNNEL_TYPE = "minecraft-java"
NAME_MAX = 64
_KEY_RE = re.compile(r'secret_key\s*=\s*"([^"\s]{8,300})"')


class PlayitError(Exception):
    pass


def read_key(path=None):
    """La clave del agente, o None si no hay archivo. Nunca se devuelve en mensajes de error."""
    p = Path(path) if path else SECRET_PATH
    try:
        m = _KEY_RE.search(p.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    return m.group(1) if m else None


def _post(path, body, key, timeout=20):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": "Agent-Key " + key, "Content-Type": "application/json", "User-Agent": "Modnex"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8", "replace")).get("data", {}).get("message", "")
        except (ValueError, AttributeError):
            msg = ""
        raise PlayitError(f"playit respondió {e.code}" + (f": {msg}" if msg else "")) from None
    except (OSError, ValueError) as e:
        raise PlayitError(f"no se pudo contactar con playit ({type(e).__name__})") from None
    if data.get("status") != "success":
        raise PlayitError("playit devolvió un error")
    return data.get("data")


def rundata(key):
    return _post("/agents/rundata", {}, key)


def create_tunnel(key, name, local_port, agent_id=None):
    """Crea un túnel de Minecraft hacia 127.0.0.1:<local_port> en el agente de la cuenta. Devuelve su id."""
    if agent_id is None:
        agent_id = rundata(key)["agent_id"]
    body = {"name": name[:NAME_MAX], "tunnel_type": TUNNEL_TYPE, "port_type": "tcp", "port_count": 1, "enabled": True,
            "origin": {"type": "agent", "data": {"agent_id": agent_id, "local_ip": "127.0.0.1", "local_port": int(local_port)}}}
    return _post("/tunnels/create", body, key)["id"]


def _record(server_dir):
    try:
        return json.loads((Path(server_dir) / RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def ensure_tunnel(server_dir, name, port, key_path=None):
    """Crea el túnel del servidor si aún no tiene uno. Devuelve el registro, o None si playit no está configurado."""
    if _record(server_dir):
        return _record(server_dir)
    key = read_key(key_path)
    if not key:
        return None
    try:
        tid = create_tunnel(key, f"Minecraft {name}", port)
        rec = {"tunnel_id": tid, "local_port": int(port)}
    except PlayitError as e:
        rec = {"error": str(e), "local_port": int(port)}
    (Path(server_dir) / RECORD).write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return rec


def address(server_dir, key_path=None):
    """Dirección pública del túnel del servidor (dominio:puerto), o None si no está lista."""
    rec = _record(server_dir)
    key = read_key(key_path)
    if not rec or not rec.get("tunnel_id") or not key:
        return None
    try:
        for t in rundata(key).get("tunnels", []):
            if t.get("id") == rec["tunnel_id"] and t.get("assigned_domain") and isinstance(t.get("port"), dict):
                return f"{t['assigned_domain']}:{t['port']['from']}"
    except PlayitError:
        return None
    return None
