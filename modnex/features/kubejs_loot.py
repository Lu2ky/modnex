"""KubeJS · Botín: tablas de botín de bloques y mobs con formularios.

Cada regla reemplaza la tabla de un bloque o un mob. Se escribe como archivo de datapack en kubejs/data/<mod>/loot_table/…,
con el formato de las tablas de vanilla (verificado sobre las ~1.100 del jar), y se aplica con /reload. Una regla es una lista de
«drops», cada uno con su cantidad, probabilidad y bonificación; cubre lo común. Las tablas con condiciones muy específicas
(estados del bloque, herramientas concretas) se muestran como «condicional» y no se pueden editar fielmente: se reemplazan.
"""
import json
import os
import re
from pathlib import Path

from . import kubejs

ID_RE = re.compile(r"[a-z0-9_.-]+:[a-z0-9_./-]+")
SLUG_RE = re.compile(r"[a-z0-9_]{1,40}")
KINDS = ("block", "entity")
DIR = {"block": "blocks", "entity": "entities"}
BONUS = ("", "fortune", "looting")
WHEN = ("always", "silk", "nosilk")
MAX_DROPS = 40
MAX_COUNT = 64
STORE = "modnex/loot.json"
SILK = {"condition": "minecraft:match_tool", "predicate": {"predicates": {"minecraft:enchantments": [{"enchantments": "minecraft:silk_touch", "levels": {"min": 1}}]}}}


def _id(v, label):
    if not isinstance(v, str) or not ID_RE.fullmatch(v):
        raise ValueError(f"{label}: id no válido")
    return v


def _int(v, label, lo, hi):
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ValueError(f"{label}: número no válido")
    if not lo <= n <= hi:
        raise ValueError(f"{label}: entre {lo} y {hi}")
    return n


def clean_rule(r):
    if not isinstance(r, dict):
        raise ValueError("regla no válida")
    kind = r.get("kind")
    if kind not in KINDS:
        raise ValueError("tipo de botín no válido (bloque o mob)")
    target = _id(r.get("target"), "objetivo")
    slug = str(r.get("id") or "")
    if not SLUG_RE.fullmatch(slug):
        raise ValueError(f"«{slug}»: el nombre solo puede tener minúsculas, números y _ (máx. 40)")
    drops = r.get("drops")
    if not isinstance(drops, list) or len(drops) > MAX_DROPS:
        raise ValueError(f"el botín admite hasta {MAX_DROPS} objetos (puede estar vacío: no suelta nada)")
    out = []
    for d in drops:
        if not isinstance(d, dict):
            raise ValueError("objeto del botín no válido")
        item = _id(d.get("item"), "objeto")
        lo, hi = _int(d.get("min", 1), f"{item}: cantidad mínima", 0, MAX_COUNT), _int(d.get("max", 1), f"{item}: cantidad máxima", 0, MAX_COUNT)
        if lo > hi:
            raise ValueError(f"{item}: la cantidad mínima no puede pasar de la máxima")
        drop = {"item": item, "min": lo, "max": hi}
        if d.get("chance") not in (None, "", 1, 1.0):
            try:
                ch = float(d["chance"])
            except (TypeError, ValueError):
                raise ValueError(f"{item}: probabilidad no válida")
            if not 0 < ch < 1:
                raise ValueError(f"{item}: la probabilidad va entre 0 y 1 (sin incluirlos)")
            drop["chance"] = round(ch, 4)
        bonus = d.get("bonus") or ""
        if bonus not in BONUS or (bonus == "fortune" and kind != "block") or (bonus == "looting" and kind != "entity"):
            raise ValueError(f"{item}: bonificación no válida para este tipo (fortuna es de bloques y saqueo de mobs)")
        if bonus:
            drop["bonus"] = bonus
        when = d.get("when") or "always"
        if when not in WHEN or (when != "always" and kind != "block"):
            raise ValueError(f"{item}: «con o sin toque de seda» solo existe en bloques")
        if when != "always":
            drop["when"] = when
        if d.get("player") is True:
            if kind != "entity":
                raise ValueError(f"{item}: «solo si lo mata un jugador» es de mobs")
            drop["player"] = True
        out.append(drop)
    return {"id": slug, "kind": kind, "target": target, "drops": out, "survives": kind == "block" and r.get("survives") is not False}


def clean_list(rules):
    if not isinstance(rules, list):
        raise ValueError("lista de reglas no válida")
    out, seen, slugs = [], set(), set()
    for r in rules:
        c = clean_rule(r)
        key = (c["kind"], c["target"])
        if key in seen:
            raise ValueError(f"«{c['target']}» ya tiene una regla: cada bloque o mob lleva una sola")
        if c["id"] in slugs:
            raise ValueError(f"«{c['id']}»: nombre repetido")
        seen.add(key); slugs.add(c["id"]); out.append(c)
    return out


def rel_path(r):
    ns, _, path = r["target"].partition(":")
    return f"data/{ns}/loot_table/{DIR[r['kind']]}/{path}.json"


def to_json(r):
    """La regla como tabla de botín de datapack (una piscina por objeto, para que cada uno tenga su propia probabilidad)."""
    pools = []
    for d in r["drops"]:
        entry, fns, conds = {"type": "minecraft:item", "name": d["item"]}, [], []
        if d["min"] == d["max"]:
            if d["min"] != 1:
                fns.append({"function": "minecraft:set_count", "count": float(d["min"]), "add": False})
        else:
            fns.append({"function": "minecraft:set_count", "count": {"type": "minecraft:uniform", "min": float(d["min"]), "max": float(d["max"])}, "add": False})
        if d.get("bonus") == "fortune":
            fns.append({"function": "minecraft:apply_bonus", "enchantment": "minecraft:fortune", "formula": "minecraft:ore_drops"})
        elif d.get("bonus") == "looting":
            fns.append({"function": "minecraft:enchanted_count_increase", "enchantment": "minecraft:looting", "count": {"type": "minecraft:uniform", "min": 0.0, "max": 1.0}})
        if fns:
            entry["functions"] = fns
        if "chance" in d:
            conds.append({"condition": "minecraft:random_chance", "chance": d["chance"]})
        if d.get("when") == "silk":
            conds.append(json.loads(json.dumps(SILK)))
        elif d.get("when") == "nosilk":
            conds.append({"condition": "minecraft:inverted", "term": json.loads(json.dumps(SILK))})
        if d.get("player"):
            conds.append({"condition": "minecraft:killed_by_player"})
        if r["kind"] == "block" and r.get("survives", True):
            conds.append({"condition": "minecraft:survives_explosion"})
        pool = {"rolls": 1.0, "bonus_rolls": 0.0, "entries": [entry]}
        if conds:
            pool["conditions"] = conds
        pools.append(pool)
    ns, _, path = r["target"].partition(":")
    return {"type": "minecraft:" + r["kind"], "pools": pools, "random_sequence": f"{ns}:{DIR[r['kind']]}/{path}"}


# ---------- lectura de la tabla actual ----------
def _count(fn):
    c = fn.get("count")
    if isinstance(c, (int, float)):
        return int(c), int(c), True
    if isinstance(c, dict) and c.get("type") in ("minecraft:uniform", "uniform"):
        try:
            return int(float(c["min"])), int(float(c["max"])), True
        except (KeyError, TypeError, ValueError):
            pass
    return 1, 1, False


def _is_silk(c):
    return isinstance(c, dict) and c.get("condition") == "minecraft:match_tool" and "silk_touch" in json.dumps(c)


def _entry(e, silk_before, drops, pool_conds):
    """Aplana una entrada de la tabla en «drops» editables. `complex` marca lo que no se puede reproducir fielmente."""
    kind = str(e.get("type", ""))
    if kind == "minecraft:alternatives":
        seen_silk = False
        for ch in e.get("children") or []:
            _entry(ch, seen_silk, drops, pool_conds)
            if any(_is_silk(c) for c in ch.get("conditions") or []):
                seen_silk = True
        return
    name = e.get("name")
    if kind not in ("minecraft:item", "minecraft:tag") or not isinstance(name, str):
        drops.append({"item": "?", "min": 1, "max": 1, "complex": True})
        return
    d = {"item": ("#" if kind == "minecraft:tag" else "") + name, "min": 1, "max": 1}
    complex_ = kind == "minecraft:tag"
    for fn in e.get("functions") or []:
        f = fn.get("function")
        if f == "minecraft:set_count":
            lo, hi, ok = _count(fn)
            d["min"], d["max"] = lo, hi
            complex_ = complex_ or not ok or bool(fn.get("conditions"))
        elif f == "minecraft:apply_bonus" and "fortune" in json.dumps(fn):
            d["bonus"] = "fortune"
        elif f == "minecraft:enchanted_count_increase" and "looting" in json.dumps(fn):
            d["bonus"] = "looting"
        elif f in ("minecraft:explosion_decay",):
            pass
        else:
            complex_ = True
    when = "nosilk" if silk_before else "always"
    for c in list(e.get("conditions") or []) + list(pool_conds):
        cond = c.get("condition") if isinstance(c, dict) else None
        if cond == "minecraft:survives_explosion":
            continue
        if cond == "minecraft:random_chance" and isinstance(c.get("chance"), (int, float)):
            d["chance"] = round(float(c["chance"]), 4)
        elif cond == "minecraft:random_chance_with_enchanted_bonus" and isinstance(c.get("unenchanted_chance"), (int, float)):
            d["chance"] = round(float(c["unenchanted_chance"]), 4); d["bonus"] = d.get("bonus") or "looting"
        elif cond == "minecraft:table_bonus" and isinstance(c.get("chances"), list) and c["chances"]:
            d["chance"] = round(float(c["chances"][0]), 4); d["bonus"] = "fortune"
        elif _is_silk(c):
            when = "silk"
        elif cond == "minecraft:inverted" and _is_silk(c.get("term")):
            when = "nosilk"
        elif cond == "minecraft:killed_by_player":
            d["player"] = True
        else:
            complex_ = True
    if when != "always":
        d["when"] = when
    if complex_:
        d["complex"] = True
    drops.append(d)


def summarize(table):
    """Lo que suelta una tabla, aplanado: [{item, min, max, chance?, bonus?, when?, player?, complex?}]."""
    drops = []
    for pool in (table.get("pools") if isinstance(table, dict) else None) or []:
        pc = pool.get("conditions") or []
        for e in pool.get("entries") or []:
            _entry(e, False, drops, pc)
    return drops[:60]


def targets(ctx, name, kind, q="", limit=120):
    if kind not in KINDS:
        raise ValueError("tipo no válido")
    _, textures, models = kubejs._index(ctx, name)
    with kubejs._LOCK:
        refs = dict(kubejs._CACHE["loot"][DIR[kind]])
        names = dict(kubejs._CACHE["names"] if kind == "block" else kubejs._CACHE["entities"])
    words = [w for w in (q or "").lower().split() if w]
    out = []
    for tid in sorted(refs):
        label = names.get(tid) or tid.split(":", 1)[1].replace("/", " ").replace("_", " ").title()
        if words and not all(w in (tid + " " + label).lower() for w in words):
            continue
        egg = tid + "_spawn_egg" if kind == "entity" else tid
        out.append({"id": tid, "name": label, "icon": kubejs._cached_icon(textures, models, egg)})
        if len(out) >= limit:
            break
    return out


def current(ctx, name, kind, target):
    """La tabla que hay hoy (de vanilla o del mod) resumida, y la regla del panel si ya existe."""
    _id(target, "objetivo")
    kubejs._index(ctx, name)
    with kubejs._LOCK:
        ref = kubejs._CACHE["loot"][DIR[kind]].get(target)
    table = None
    if ref:
        raw = kubejs._read(ref)
        try:
            table = json.loads(raw.decode("utf-8", "replace")) if raw else None
        except ValueError:
            table = None
    drops = summarize(table) if table else []
    rule = next((r for r in load(ctx, name)["rules"] if r["kind"] == kind and r["target"] == target), None)
    return {"exists": bool(ref), "drops": drops, "complex": any(d.get("complex") for d in drops), "rule": rule}


# ---------- almacenamiento ----------
def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _base(ctx, name):
    base = Path(ctx.server_path(name)) / "kubejs"
    if not base.is_dir():
        raise ValueError("este servidor no tiene carpeta kubejs (arráncalo una vez con KubeJS instalado)")
    return base


def load(ctx, name):
    src = Path(ctx.server_path(name)) / "kubejs" / STORE
    try:
        data = json.loads(src.read_text(encoding="utf-8")) if src.is_file() else {}
        rules = clean_list(data.get("rules", []))
    except (ValueError, OSError, AttributeError):
        rules = []
    return {"rules": rules}


def save(ctx, name, rules):
    rules = clean_list(rules)
    base = _base(ctx, name)
    old = []
    try:
        old = json.loads((base / STORE).read_text(encoding="utf-8")).get("files", []) if (base / STORE).is_file() else []
    except (ValueError, OSError, AttributeError):
        pass
    files = [rel_path(r) for r in rules]
    for r in rules:
        _write(base / rel_path(r), json.dumps(to_json(r), ensure_ascii=False, indent=2) + "\n")
    for rel in old:                      # solo se borran archivos que escribió el panel y ya no tienen regla
        target = (base / rel).resolve()
        if rel not in files and isinstance(rel, str) and rel.startswith("data/") and base.resolve() in target.parents and target.is_file():
            target.unlink()
    _write(base / STORE, json.dumps({"rules": rules, "files": files}, ensure_ascii=False, indent=2) + "\n")
    return rules
