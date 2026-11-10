"""Ajustes del gestor: rutas, puerto, archivo `config.json` y constantes compartidas."""

import json
import os
import re
import secrets
from pathlib import Path




HERE = Path(__file__).resolve().parent.parent   # raíz del proyecto


STATIC = HERE / "static"


CONFIG_FILE = Path(os.environ.get("MODNEX_CONFIG") or HERE / "config.json")


def _servers_dir():
    """Carpeta de los servidores: variable SERVERS_DIR, o «servers_dir» de config.json, o «servers» junto al proyecto."""
    v = os.environ.get("SERVERS_DIR")
    if not v:
        try:
            v = json.loads(CONFIG_FILE.read_text()).get("servers_dir")
        except (OSError, ValueError, AttributeError):
            v = None
    return Path(v or HERE / "servers").expanduser().resolve()


SERVERS_DIR = _servers_dir()


PORT = int(os.environ.get("MANAGER_PORT", "8765"))


UA = "cobblemon-server-manager/1.0 (local)"


ALLOWED_DL_HOSTS = {"cdn.modrinth.com", "mediafilez.forgecdn.net", "edge.forgecdn.net"}


CF_LOADER_TYPE = {"forge": 1, "fabric": 4, "neoforge": 6}


MAX_MOD_BYTES = 512 * 1024 * 1024


NAME_RE = re.compile(r"[A-Za-z0-9._-]+")


JAR_RE = re.compile(r"[A-Za-z0-9._+\-\[\]() ]+\.jar(\.disabled)?")


MEM_RE = re.compile(r"\d{1,2}[MG]")


def load_config():
    return json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}


def load_cf_key():
    if os.environ.get("CURSEFORGE_API_KEY"):
        return os.environ["CURSEFORGE_API_KEY"]
    return load_config().get("curseforge_api_key", "")


def ensure_config():
    """Crea config.json con una contraseña aleatoria si no existe o no tiene access_token."""
    cfg = load_config()
    if not cfg.get("access_token"):
        cfg["access_token"] = secrets.token_urlsafe(24)
        cfg.setdefault("bind", "0.0.0.0")
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n")
        os.chmod(CONFIG_FILE, 0o600)
        print(f"Contraseña generada en {CONFIG_FILE} (campo access_token)", flush=True)
    return cfg
