"""Reglas de InControl (spawn.json, spawner.json, loot.json): catálogo, validación y escritura.

El catálogo sale de la documentación de InControl (mcjty.eu/docs/mods/control-mods/control-mods-20).
Tipos: S texto, S/[S] texto o lista de textos, I entero, F decimal, B verdadero/falso, E expresión
(p. ej. "gt(10)"), JSON objeto, [JSON] lista de objetos.
Lo que la documentación no dice con certeza se marca en UNVERIFIED y no se ofrece en el formulario.
"""

import json
import re

RULE_FILES = ("spawn.json", "spawner.json", "loot.json")

# Campos que van en la raíz de una regla de spawn.json (además de las condiciones).
SPAWN_META = {"when": "S", "result": "S", "continue": "B"}
WHEN_VALUES = ["position", "onjoin", "finalize", "despawn"]
RESULT_VALUES = ["allow", "default", "deny"]

# Condiciones de la tabla de la documentación (clave -> tipo).
CONDITIONS = {
    "phase": "S/[S]", "number": "JSON", "kubejs": "JSON/[JSON]", "firstjoin": "B",
    "mindaycount": "I", "maxdaycount": "I", "daycount": "I/E", "baby": "B", "spawner": "B",
    "spawntype": "S/[S]", "incontrol": "B", "eventspawn": "B", "area": "S",
    "minheight": "I", "maxheight": "I", "height": "E",
    "minlight": "I", "maxlight": "I", "minlight_sky": "I", "maxlight_sky": "I",
    "minlight_full": "I", "maxlight_full": "I", "light": "E",
    "mincount": "S/I/JSON", "maxcount": "S/I/JSON",
    "maxthis": "I", "maxtotal": "I", "maxpeaceful": "I", "maxhostile": "I", "maxneutral": "I", "maxlocal": "I",
    "minspawndist": "F", "maxspawndist": "F",
    "mintime": "I", "maxtime": "I", "time": "E",
    "mindifficulty": "F", "maxdifficulty": "F",
    "mindist": "I", "maxdist": "I", "minverticaldist": "I", "maxverticaldist": "I",
    "canspawnhere": "B", "norestrictions": "B",
    "inliquid": "B", "inwater": "B", "inlava": "B", "inair": "B", "notcolliding": "B",
    "difficulty": "S", "weather": "S", "category": "S/[S]", "biometags": "S/[S]",
    "hostile": "B", "passive": "B", "seesky": "B", "cave": "B", "slime": "B",
    "structure": "S/[S]", "structuretags": "S/[S]", "hasstructure": "B",
    "mob": "S/[S]", "mod": "S/[S]", "block": "S/[S]/JSON", "blockoffset": "JSON", "blocktest": "S/[S]/JSON",
    "biome": "S/[S]", "dimension": "S/[S]", "dimensionmod": "S/[S]", "random": "F",
    "npc": "JSON", "player": "B", "fakeplayer": "B", "realplayer": "B",
    "projectile": "B", "explosion": "B", "magic": "B", "fire": "B", "source": "S/[S]",
    "playerhelditem": "S/[S]/JSON", "offhanditem": "S/[S]/JSON", "bothhandsitem": "S/[S]/JSON",
    "lackhelditem": "S/[S]/JSON", "lackoffhanditem": "S/[S]/JSON",
    "helmet": "S/[S]/JSON", "chestplate": "S/[S]/JSON", "leggings": "S/[S]/JSON", "boots": "S/[S]/JSON",
    "lackhelmet": "S/[S]/JSON", "lackchestplate": "S/[S]/JSON", "lackleggings": "S/[S]/JSON", "lackboots": "S/[S]/JSON",
    "scoreboardtags_all": "S/[S]", "scoreboardtags_any": "S/[S]", "nodespawn": "B",
    "incity": "B", "instreet": "B", "insphere": "B", "inbuilding": "B", "inmultibuilding": "B",
    "building": "S/[S]", "multibuilding": "S/[S]", "gamestage": "S",
    "winter": "B", "summer": "B", "spring": "B", "autumn": "B",
    "state": "S", "pstate": "S",
}

# Acciones de spawn.json (con result distinto de deny).
SPAWN_ACTIONS = {"nbt": "JSON", "customname": "S",
                 "angry": "B", "potion": "S/[S]", "potionnoparticles": "S/[S]", "helditem": "S/[S]",
                 "armorboots": "S/[S]", "armorhelmet": "S/[S]", "armorlegs": "S/[S]", "armorchest": "S/[S]",
                 "ai": "JSON"}
for _attr in ("health", "speed", "damage", "armor", "armortoughness", "attackspeed", "followrange",
              "knockback", "knockbackresistance"):
    for _op in ("multiply", "add", "set"):
        SPAWN_ACTIONS[f"{_attr}{_op}"] = "F"
# Acciones comunes a todas las reglas.
COMMON_ACTIONS = {"setphase": "S", "clearphase": "S", "togglephase": "S", "changenumber": "S", "customevent": "S"}

# spawner.json: claves de la raíz de la regla.
SPAWNER_ROOT = {"mob": "S/[S]/JSON", "phase": "S/[S]", "number": "JSON/[JSON]", "weights": "[JSON]",
                "mobsfrombiome": "S", "addscoreboardtags": "S/[S]", "attempts": "I", "persecond": "F",
                "amount": "JSON", "conditions": "JSON"}
MOBSFROMBIOME = ["monster", "creature", "ambient", "water_creature", "water_ambient", "misc"]
# Condiciones que admite spawner.json (dentro de "conditions"): la documentación dice que solo son estas.
SPAWNER_CONDITIONS = {"dimension": "S/[S]", "mindaycount": "I", "maxdaycount": "I", "mindist": "I", "maxdist": "I",
                      "minverticaldist": "I", "maxverticaldist": "I", "minheight": "I", "maxheight": "I",
                      "norestrictions": "B", "inliquid": "B", "inwater": "B", "inlava": "B", "inair": "B",
                      "maxthis": "I", "maxtotal": "I", "maxpeaceful": "I", "maxhostile": "I", "maxneutral": "I",
                      "maxlocal": "I", "validspawn": "B", "sturdy": "B", "and": "JSON", "not": "JSON"}
SPAWNER_INNER = {"mintime": "I", "maxtime": "I", "minlight": "I", "maxlight": "I", "minlight_sky": "I",
                 "maxlight_sky": "I", "minlight_full": "I", "maxlight_full": "I", "biome": "S/[S]",
                 "biometags": "S/[S]", "seesky": "B", "cave": "B", "structure": "S/[S]", "structuretags": "S/[S]",
                 "hasstructure": "B", "incity": "B", "inbuilding": "B", "inmultibuilding": "B", "building": "S/[S]",
                 "multibuilding": "S/[S]", "instreet": "B", "insphere": "B", "gamestage": "S", "kubejs": "JSON/[JSON]",
                 "summer": "B", "winter": "B", "spring": "B", "autumn": "B"}

# loot.json: acciones documentadas. removeall no tiene tipo indicado en la documentación: se trata como B
# y se marca para comprobar en el juego.
LOOT_ACTIONS = {"item": "S/[S]", "itemcount": "S", "nbt": "JSON", "remove": "S/[S]", "removeall": "B"}
# Condiciones que la documentación usa en ejemplos de loot.json (no hay lista oficial para este archivo).
LOOT_CONDITIONS = {"mob": "S/[S]", "structure": "S/[S]", "player": "B", "playerhelditem": "S/[S]/JSON"}
UNVERIFIED = {"loot.json:removeall"}

RANGE_RE = re.compile(r"^(\d+|\d+\.\d+)-(\d+|\d+\.\d+)$")


def _matches(part, value):
    if part == "B": return isinstance(value, bool)
    if part == "I": return isinstance(value, int) and not isinstance(value, bool)
    if part == "F": return isinstance(value, (int, float)) and not isinstance(value, bool)
    if part in ("S", "E"): return isinstance(value, str)
    if part == "[S]": return isinstance(value, list) and all(isinstance(x, str) for x in value)
    if part == "JSON": return isinstance(value, dict)
    if part == "[JSON]": return isinstance(value, list) and all(isinstance(x, dict) for x in value)
    raise ValueError(f"tipo desconocido {part}")


def _check_type(kind, value):
    """Comprueba que `value` encaja con el tipo de la documentación (p. ej. "S/[S]": texto o lista de textos)."""
    if not any(_matches(part, value) for part in kind.split("/")):
        names = {"B": "verdadero/falso", "I": "número entero", "F": "número", "S": "texto", "E": "expresión",
                 "[S]": "lista de textos", "JSON": "objeto", "[JSON]": "lista de objetos"}
        raise ValueError("debe ser " + " o ".join(names[p] for p in kind.split("/")))


def validate_rule(file, rule):
    """Valida una regla completa. Devuelve la lista de problemas (vacía si está bien)."""
    problems = []
    if not isinstance(rule, dict):
        return ["la regla debe ser un objeto"]
    if file == "spawn.json":
        for k, v in rule.items():
            if k in SPAWN_META:
                kind = SPAWN_META[k]
                try:
                    _check_type(kind, v)
                except ValueError as e:
                    problems.append(f"{k}: {e}")
                if k == "when" and v not in WHEN_VALUES: problems.append(f"when: debe ser uno de {', '.join(WHEN_VALUES)}")
                if k == "result" and v not in RESULT_VALUES: problems.append(f"result: debe ser uno de {', '.join(RESULT_VALUES)}")
            elif k in CONDITIONS or k in SPAWN_ACTIONS or k in COMMON_ACTIONS:
                kind = CONDITIONS.get(k) or SPAWN_ACTIONS.get(k) or COMMON_ACTIONS[k]
                try: _check_type(kind, v)
                except ValueError as e: problems.append(f"{k}: {e}")
            else:
                problems.append(f"«{k}» no es una opción conocida de spawn.json")
    elif file == "spawner.json":
        for k, v in rule.items():
            if k not in SPAWNER_ROOT:
                problems.append(f"«{k}» no es una clave de spawner.json")
                continue
            try: _check_type(SPAWNER_ROOT[k], v)
            except ValueError as e: problems.append(f"{k}: {e}")
            if k == "mobsfrombiome" and v not in MOBSFROMBIOME: problems.append(f"mobsfrombiome: debe ser uno de {', '.join(MOBSFROMBIOME)}")
            if k == "persecond" and isinstance(v, (int, float)) and not (0 < v <= 1): problems.append("persecond: entre 0 y 1")
            if k == "attempts" and isinstance(v, int) and v < 1: problems.append("attempts: al menos 1")
        if "mob" not in rule: problems.append("falta «mob», que es obligatorio")
        cond = rule.get("conditions", {})
        if isinstance(cond, dict):
            if "dimension" not in cond: problems.append("conditions: falta «dimension», que es obligatoria")
            for k, v in cond.items():
                if k not in SPAWNER_CONDITIONS:
                    problems.append(f"conditions.{k} no es una condición de spawner.json")
                    continue
                try: _check_type(SPAWNER_CONDITIONS[k], v)
                except ValueError as e: problems.append(f"conditions.{k}: {e}")
                if k in ("and", "not") and isinstance(v, dict):
                    for ik, iv in v.items():
                        if ik not in SPAWNER_INNER: problems.append(f"conditions.{k}.{ik} no se admite dentro de {k}")
    elif file == "loot.json":
        for k, v in rule.items():
            if k not in LOOT_ACTIONS and k not in LOOT_CONDITIONS:
                problems.append(f"«{k}» no es una opción conocida de loot.json")
                continue
            kind = LOOT_ACTIONS.get(k) or LOOT_CONDITIONS.get(k)
            try: _check_type(kind, v)
            except ValueError as e: problems.append(f"{k}: {e}")
            if k == "itemcount" and isinstance(v, str) and not all(RANGE_RE.match(p) or p.isdigit() for p in v.split("/")):
                problems.append("itemcount: formato como 5/7-10/20-30")
    else:
        problems.append("archivo no soportado")
    return problems


def validate_file(file, rules):
    if not isinstance(rules, list):
        return ["el archivo debe ser una lista de reglas"]
    out = []
    for n, r in enumerate(rules, 1):
        out += [f"regla {n}: {p}" for p in validate_rule(file, r)]
    return out


def dump(rules):
    return json.dumps(rules, ensure_ascii=False, indent=2) + "\n"


def catalog(file):
    """Lo que el formulario puede ofrecer para un archivo: campos de la regla y su tipo."""
    if file == "spawn.json":
        return {"meta": SPAWN_META, "conditions": CONDITIONS, "actions": {**SPAWN_ACTIONS, **COMMON_ACTIONS},
                "when": WHEN_VALUES, "result": RESULT_VALUES}
    if file == "spawner.json":
        return {"root": SPAWNER_ROOT, "conditions": SPAWNER_CONDITIONS, "inner": SPAWNER_INNER, "meta": {}, "mobsfrombiome": MOBSFROMBIOME}
    if file == "loot.json":
        return {"actions": LOOT_ACTIONS, "conditions": LOOT_CONDITIONS, "meta": {}, "unverified": sorted(UNVERIFIED)}
    raise ValueError("archivo no soportado")


# ---- archivos del servidor -------------------------------------------------

import shutil
import time
from pathlib import Path

from modnex.config import HERE
from modnex.services.servers import server_path


def _rules_path(name, file):
    if file not in RULE_FILES:
        raise ValueError("archivo de reglas no soportado")
    return server_path(name) / "config" / "incontrol" / file


def read_rules(name, file):
    p = _rules_path(name, file)
    if not p.is_file():
        return {"file": file, "rules": [], "catalog": catalog(file), "problems": [], "exists": False}
    text = p.read_text(encoding="utf-8")
    try:
        rules = json.loads(text or "[]")
    except ValueError:
        return {"file": file, "rules": None, "raw": text, "catalog": catalog(file), "problems": ["el archivo no es JSON válido"], "exists": True}
    return {"file": file, "rules": rules, "catalog": catalog(file), "problems": validate_file(file, rules), "exists": True}


def save_rules(name, file, rules):
    """Valida y guarda. No escribe nada si hay problemas. Antes copia el archivo original."""
    problems = validate_file(file, rules)
    if problems:
        raise ValueError("; ".join(problems[:5]) + (" …" if len(problems) > 5 else ""))
    p = _rules_path(name, file)
    p.parent.mkdir(parents=True, exist_ok=True)
    new = dump(rules)
    if p.is_file():
        if p.read_text(encoding="utf-8") == new:
            return {"changed": False}
        backup = HERE / "backups" / "configs" / name
        backup.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, backup / f"incontrol__{file}.{time.strftime('%Y%m%d-%H%M%S')}.bak")
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(new, encoding="utf-8")
    tmp.replace(p)
    return {"changed": True}
