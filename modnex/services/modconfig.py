"""Configuración de mods: lectura y escritura de los TOML de NeoForge sin perder comentarios.

Un archivo TOML de NeoForge tiene, justo encima de cada clave, comentarios con metadatos:
`# Default: X`, `# Range: a ~ b`, `#Allowed Values: A, B`. Con eso se valida cada valor antes de escribirlo.
Al guardar solo cambia el valor de la línea editada; el resto del archivo queda igual.
"""

import json
import re
import shutil
import time
from pathlib import Path

from modnex.config import HERE
from modnex.services.servers import server_path

KEY_RE = re.compile(r'^\s*("[^"]+"|[A-Za-z0-9_.\-]+)\s*=\s*(.*?)\s*$')
SECTION_RE = re.compile(r"^\s*\[\s*([^\[\]]+?)\s*\]\s*$")
META_RE = re.compile(r"^(Default|Range|Allowed Values):\s*(.*)$")
MODID_RE = re.compile(r"^[a-z0-9_][a-z0-9_\-]{1,63}$")
NAME_OK = re.compile(r"^[A-Za-z0-9_\-./]{1,200}$")


def parse_value(raw):
    """Valor TOML crudo -> (tipo, valor de Python)."""
    raw = raw.strip()
    if raw in ("true", "false"):
        return "bool", raw == "true"
    if raw.startswith('"'):
        try:
            return "str", json.loads(raw)
        except ValueError:
            return "str", raw.strip('"')
    if raw.startswith("["):
        try:
            return "list", json.loads(raw)
        except ValueError:
            return "list", raw
    if re.fullmatch(r"[-+]?\d+", raw):
        return "int", int(raw)
    if re.fullmatch(r"[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?", raw):
        return "float", float(raw)
    return "raw", raw


def serialize(kind, value):
    """Valor de Python -> texto TOML, según el tipo original de la clave."""
    if kind == "bool":
        if not isinstance(value, bool):
            raise ValueError("el valor debe ser verdadero o falso")
        return "true" if value else "false"
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
            raise ValueError("el valor debe ser un número entero")
        return str(int(value))
    if kind == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("el valor debe ser un número")
        return repr(float(value))
    if kind == "str":
        if not isinstance(value, str) or re.search(r"[\x00-\x1f\x7f]", value):
            raise ValueError("el texto no es válido")
        return json.dumps(value, ensure_ascii=False)
    if kind == "list":
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise ValueError("la lista debe contener solo textos")
        return "[" + ", ".join(json.dumps(x, ensure_ascii=False) for x in value) + "]"
    raise ValueError("este tipo de valor no se puede editar desde el panel")


def _range(text):
    m = re.fullmatch(r"\s*([-+]?[\d.]+)\s*~\s*([-+]?[\d.]+)\s*", text or "")
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def check(entry, value):
    """Valida `value` contra lo que dice el archivo de configuración. Lanza ValueError con un mensaje claro."""
    kind = entry["type"]
    serialize(kind, value)    # tipo correcto
    if kind in ("int", "float"):
        rng = _range(entry.get("range"))
        if rng and not (rng[0] <= float(value) <= rng[1]):
            raise ValueError(f"fuera de rango: entre {rng[0]:g} y {rng[1]:g}")
    if kind == "str" and entry.get("allowed"):
        allowed = [x.strip() for x in entry["allowed"].split(",") if x.strip()]
        if allowed and value not in allowed:
            raise ValueError("debe ser uno de: " + ", ".join(allowed))


def parse(text):
    """Devuelve las entradas editables del TOML: sección, clave, tipo, valor, metadatos y línea."""
    entries, section, buf = [], "", []
    for idx, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if not stripped:
            buf = []
            continue
        if stripped.startswith("#"):
            buf.append(stripped[1:].strip())
            continue
        sm = SECTION_RE.match(line)
        if sm:
            section = sm.group(1).strip()
            buf = []
            continue
        km = KEY_RE.match(line)
        if km:
            key = km.group(1).strip('"')
            kind, value = parse_value(km.group(2))
            meta = {"default": None, "range": None, "allowed": None}
            desc = []
            for c in buf:
                mm = META_RE.match(c)
                if mm:
                    field = {"Default": "default", "Range": "range", "Allowed Values": "allowed"}[mm.group(1)]
                    meta[field] = mm.group(2).strip()
                else:
                    desc.append(c)
            entries.append({"section": section, "key": key, "type": kind, "value": value,
                            "description": " ".join(desc).strip(), "line": idx, **meta})
            buf = []
            continue
        buf = []
    return entries


def patch(text, section, key, new_raw):
    """Cambia solo el valor de la línea de `section.key`. Devuelve el texto nuevo."""
    lines = text.splitlines(keepends=True)
    current = ""
    for idx, line in enumerate(lines):
        sm = SECTION_RE.match(line)
        if sm:
            current = sm.group(1).strip()
            continue
        km = KEY_RE.match(line)
        if km and current == section and km.group(1).strip('"') == key:
            indent = line[: len(line) - len(line.lstrip())]
            eol = "\n" if line.endswith("\n") else ""
            lines[idx] = f"{indent}{km.group(1)} = {new_raw}{eol}"
            return "".join(lines)
    raise KeyError(f"no existe {section}.{key}")


def apply_updates(text, updates):
    """updates: lista de {section, key, value}. Valida cada valor con el tipo y rango del archivo."""
    entries = {(e["section"], e["key"]): e for e in parse(text)}
    for u in updates:
        e = entries.get((u["section"], u["key"]))
        if not e:
            raise KeyError(f"no existe {u['section']}.{u['key']}")
        check(e, u["value"])
        text = patch(text, u["section"], u["key"], serialize(e["type"], u["value"]))
    return text


# ---- archivos del servidor -------------------------------------------------

def _cfg_dir(name):
    d = server_path(name) / "config"
    return d


def mod_config_files(name, modid):
    """Archivos de configuración de un mod: `config/<modid>-*.toml` y `config/<modid>/*.json|toml`."""
    if not MODID_RE.match(modid or ""):
        return []
    cfg = _cfg_dir(name)
    out = []
    if cfg.is_dir():
        for f in sorted(cfg.glob(f"{modid}-*.toml")):
            if f.is_file():
                out.append(f.name)
        sub = cfg / modid
        if sub.is_dir():
            for f in sorted(sub.rglob("*")):
                if f.is_file() and f.suffix in (".json", ".toml"):
                    out.append(f"{modid}/" + f.relative_to(sub).as_posix())
    return out


def _safe_rel(rel):
    if not NAME_OK.match(rel) or ".." in rel.split("/") or rel.startswith("/"):
        raise ValueError("archivo no válido")
    return rel


def read_config(name, rel):
    rel = _safe_rel(rel)
    p = _cfg_dir(name) / rel
    if not p.is_file():
        raise FileNotFoundError("archivo no encontrado")
    text = p.read_text(encoding="utf-8")
    if rel.endswith(".toml"):
        return {"file": rel, "kind": "toml", "entries": parse(text)}
    if rel.endswith(".json"):
        try:
            data = json.loads(text)
        except ValueError:
            return {"file": rel, "kind": "json-invalido", "text": text}
        return {"file": rel, "kind": "json", "text": json.dumps(data, ensure_ascii=False, indent=2)}
    raise ValueError("tipo de archivo no editable")


def save_config(name, rel, updates=None, json_text=None):
    """Guarda cambios: `updates` para TOML, `json_text` para JSON. Antes copia el archivo original."""
    rel = _safe_rel(rel)
    p = _cfg_dir(name) / rel
    if not p.is_file():
        raise FileNotFoundError("archivo no encontrado")
    original = p.read_text(encoding="utf-8")
    if rel.endswith(".toml"):
        new = apply_updates(original, updates or [])
    elif rel.endswith(".json"):
        try:
            new = json.dumps(json.loads(json_text or ""), ensure_ascii=False, indent=2) + "\n"
        except ValueError as exc:
            raise ValueError(f"el JSON no es válido: {exc}") from exc
    else:
        raise ValueError("tipo de archivo no editable")
    if new == original:
        return {"changed": False}
    backup_dir = HERE / "backups" / "configs" / name
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(p, backup_dir / f"{rel.replace('/', '__')}.{stamp}.bak")
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(new, encoding="utf-8")
    tmp.replace(p)
    return {"changed": True, "backup": f"{rel.replace('/', '__')}.{stamp}.bak"}


AUTO_FILE = HERE / "modconfig-auto.json"
AUTO_DEFAULT = ["incontrol"]


def auto_mods():
    """Mods que abren su panel al detectarse en «Instalados». Por defecto, solo InControl."""
    try:
        data = json.loads(AUTO_FILE.read_text(encoding="utf-8"))
        return {m for m in data if isinstance(m, str)}
    except (OSError, ValueError):
        return set(AUTO_DEFAULT)


def set_auto(modid, on):
    if not MODID_RE.match(modid or ""):
        raise ValueError("identificador de mod no válido")
    mods = auto_mods()
    (mods.add if on else mods.discard)(modid)
    AUTO_FILE.write_text(json.dumps(sorted(mods)), encoding="utf-8")
    return sorted(mods)


def mods_with_config(name, modids):
    """De los mods instalados, cuáles tienen archivos de configuración y cuáles abren el panel solos."""
    auto = auto_mods()
    return [{"modid": m, "files": mod_config_files(name, m), "auto": m in auto}
            for m in sorted(modids) if mod_config_files(name, m)]
