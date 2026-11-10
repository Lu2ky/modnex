"""`server.properties`: lectura, validación y escritura de las opciones principales."""

import re

from modnex.services.servers import server_path, status, used_ports


PROP_SPECS = {
    "motd": ("text", 59), "server-port": ("int", 1024, 65535), "max-players": ("int", 1, 1000),
    "online-mode": ("bool",), "white-list": ("bool",), "enforce-whitelist": ("bool",),
    "difficulty": ("enum", "peaceful", "easy", "normal", "hard"),
    "gamemode": ("enum", "survival", "creative", "adventure", "spectator"),
    "force-gamemode": ("bool",), "pvp": ("bool",), "hardcore": ("bool",), "allow-flight": ("bool",),
    "allow-nether": ("bool",), "spawn-monsters": ("bool",), "spawn-animals": ("bool",),
    "spawn-npcs": ("bool",), "enable-command-block": ("bool",),
    "view-distance": ("int", 3, 32), "simulation-distance": ("int", 3, 32), "spawn-protection": ("int", 0, 1000),
    "level-name": ("name",), "level-seed": ("text", 40),
}


def properties_view(name):
    cur = read_properties(name)
    out = {}
    for k, spec in PROP_SPECS.items():
        out[k] = cur.get(k, "")
    return {"values": out, "running": status(name)["running"]}


def set_properties(name, updates):
    """Valida y escribe solo las claves de PROP_SPECS; el resto del archivo no se toca."""
    if not isinstance(updates, dict) or not updates:
        raise ValueError("nada que guardar")
    clean = {}
    for k, v in updates.items():
        if k not in PROP_SPECS:
            raise ValueError(f"«{k}» no es una opción editable desde el panel")
        spec = PROP_SPECS[k]
        sv = "true" if v is True else "false" if v is False else str(v).strip()
        if spec[0] == "bool":
            if sv not in ("true", "false"):
                raise ValueError(f"{k} debe ser sí o no")
        elif spec[0] == "int":
            if not re.fullmatch(r"-?\d{1,5}", sv) or not spec[1] <= int(sv) <= spec[2]:
                raise ValueError(f"{k} debe estar entre {spec[1]} y {spec[2]}")
        elif spec[0] == "enum":
            if sv not in spec[1:]:
                raise ValueError(f"{k} no es una opción válida")
        elif spec[0] == "name":
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", sv):
                raise ValueError("el nombre del mundo solo admite letras, números, puntos, guiones y guiones bajos")
        else:
            if len(sv) > spec[1] or re.search(r"[\x00-\x1f\x7f]", sv):
                raise ValueError(f"{k}: texto no válido (máximo {spec[1]} caracteres, sin saltos de línea)")
        clean[k] = sv
    if "server-port" in clean:
        others = used_ports() - {int(read_properties(name).get("server-port", 0) or 0)}
        if int(clean["server-port"]) in others:
            raise ValueError(f"el puerto {clean['server-port']} ya lo usa otro servidor")
    write_properties(name, clean)
    return clean


def read_properties(name):
    f = server_path(name) / "server.properties"
    out = {}
    if f.exists():
        for line in f.read_text(errors="replace").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.replace("\\:", ":").replace("\\=", "=")
    return out


def write_properties(name, updates):
    f = server_path(name) / "server.properties"
    lines = f.read_text(errors="replace").splitlines() if f.exists() else []
    seen, out = set(), []
    for line in lines:
        k = line.split("=", 1)[0].strip() if ("=" in line and not line.lstrip().startswith("#")) else None
        if k in updates:
            out.append(f"{k}={updates[k]}")
            seen.add(k)
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in updates.items() if k not in seen]
    f.write_text("\n".join(out) + "\n")
