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
KINDS = ("block", "entity", "chest")
DIR = {"block": "blocks", "entity": "entities", "chest": "chests"}
MAX_CHEST_DROPS = 80
MAX_POOLS = 8
MAX_WEIGHT = 1000
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
        raise ValueError("tipo de botín no válido (bloque, mob o cofre)")
    target = _id(r.get("target"), "objetivo")
    slug = str(r.get("id") or "")
    if not SLUG_RE.fullmatch(slug):
        raise ValueError(f"«{slug}»: el nombre solo puede tener minúsculas, números y _ (máx. 40)")
    if kind == "chest":
        return _clean_chest(slug, target, r)
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


def _clean_chest(slug, target, r):
    """Un cofre tiene grupos («pools») con su número de tiradas; cada tirada saca un objeto según su peso."""
    pools = r.get("pools")
    if not isinstance(pools, list) or not 1 <= len(pools) <= MAX_POOLS:
        raise ValueError(f"un cofre lleva entre 1 y {MAX_POOLS} grupos de objetos")
    clean_pools = []
    for i, p in enumerate(pools):
        if not isinstance(p, dict):
            raise ValueError("grupo no válido")
        lo, hi = _int(p.get("min", 1), f"grupo {i + 1}: tiradas mínimas", 0, MAX_COUNT), _int(p.get("max", 1), f"grupo {i + 1}: tiradas máximas", 0, MAX_COUNT)
        if lo > hi:
            raise ValueError(f"grupo {i + 1}: las tiradas mínimas no pueden pasar de las máximas")
        clean_pools.append({"min": lo, "max": hi})
    drops = r.get("drops")
    if not isinstance(drops, list) or len(drops) > MAX_CHEST_DROPS:
        raise ValueError(f"un cofre admite hasta {MAX_CHEST_DROPS} objetos")
    out = []
    for d in drops:
        if not isinstance(d, dict):
            raise ValueError("objeto del cofre no válido")
        item = _id(d.get("item"), "objeto")
        lo, hi = _int(d.get("min", 1), f"{item}: cantidad mínima", 0, MAX_COUNT), _int(d.get("max", 1), f"{item}: cantidad máxima", 0, MAX_COUNT)
        if lo > hi:
            raise ValueError(f"{item}: la cantidad mínima no puede pasar de la máxima")
        weight = _int(d.get("weight", 10), f"{item}: peso", 1, MAX_WEIGHT)
        pool = _int(d.get("pool", 0), f"{item}: grupo", 0, len(clean_pools) - 1)
        out.append({"item": item, "min": lo, "max": hi, "weight": weight, "pool": pool})
    return {"id": slug, "kind": "chest", "target": target, "pools": clean_pools, "drops": out, "survives": False}


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
    if r["kind"] == "chest":
        return _chest_json(r)
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


def _set_count(d):
    if d["min"] == d["max"]:
        return [] if d["min"] == 1 else [{"function": "minecraft:set_count", "count": float(d["min"]), "add": False}]
    return [{"function": "minecraft:set_count", "count": {"type": "minecraft:uniform", "min": float(d["min"]), "max": float(d["max"])}, "add": False}]


def _chest_json(r):
    pools = []
    for i, p in enumerate(r["pools"]):
        entries = []
        for d in r["drops"]:
            if d["pool"] != i:
                continue
            e = {"type": "minecraft:item", "name": d["item"], "weight": d["weight"]}
            if _set_count(d):
                e["functions"] = _set_count(d)
            entries.append(e)
        rolls = float(p["min"]) if p["min"] == p["max"] else {"type": "minecraft:uniform", "min": float(p["min"]), "max": float(p["max"])}
        pools.append({"rolls": rolls, "bonus_rolls": 0.0, "entries": entries})
    ns, _, path = r["target"].partition(":")
    return {"type": "minecraft:chest", "pools": pools, "random_sequence": f"{ns}:chests/{path}"}


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


def _rolls(v):
    if isinstance(v, (int, float)):
        return int(v), int(v), True
    if isinstance(v, dict) and v.get("type") in ("minecraft:uniform", "uniform"):
        try:
            return int(float(v["min"])), int(float(v["max"])), True
        except (KeyError, TypeError, ValueError):
            pass
    return 1, 1, False


def summarize_chest(table):
    """({pools: [{min, max}], drops: [{item, min, max, weight, pool, complex?}]}). `complex` marca encantamientos, NBT,
    condiciones, etiquetas, tiradas especiales o entradas anidadas: el panel no las reproduce y se pierden al reemplazar la tabla."""
    pools, drops = [], []
    for pool in (table.get("pools") if isinstance(table, dict) else None) or []:
        lo, hi, ok = _rolls(pool.get("rolls"))
        idx = len(pools)
        pools.append({"min": lo, "max": hi, "complex": (not ok) or bool(pool.get("conditions")) or bool(pool.get("functions")) or bool(pool.get("bonus_rolls"))})

        def add(e, nested):
            kind = str(e.get("type", ""))
            if kind == "minecraft:alternatives" or kind == "minecraft:group" or kind == "minecraft:sequence":
                for ch in e.get("children") or []:
                    add(ch, True)
                return
            name = e.get("name")
            if kind not in ("minecraft:item", "minecraft:tag") or not isinstance(name, str):
                drops.append({"item": "?", "min": 1, "max": 1, "weight": 1, "pool": idx, "complex": True})
                return
            d = {"item": ("#" if kind == "minecraft:tag" else "") + name, "min": 1, "max": 1, "pool": idx}
            w = e.get("weight", 1)
            d["weight"] = int(w) if isinstance(w, (int, float)) and w >= 1 else 1
            bad = nested or kind == "minecraft:tag" or bool(e.get("conditions")) or e.get("quality") not in (None, 0)
            for fn in e.get("functions") or []:
                if fn.get("function") == "minecraft:set_count" and not fn.get("conditions"):
                    lo2, hi2, ok2 = _count(fn)
                    d["min"], d["max"] = lo2, hi2
                    bad = bad or not ok2
                else:
                    bad = True
            if bad:
                d["complex"] = True
            drops.append(d)

        for e in pool.get("entries") or []:
            add(e, False)
    return {"pools": pools[:MAX_POOLS], "drops": drops[:MAX_CHEST_DROPS]}


def targets(ctx, name, kind, q="", limit=120):
    if kind not in KINDS:
        raise ValueError("tipo no válido")
    _, textures, models = kubejs._index(ctx, name)
    with kubejs._LOCK:
        refs = dict(kubejs._CACHE["loot"][DIR[kind]])
        names = dict(kubejs._CACHE["names"]) if kind == "block" else dict(kubejs._CACHE["entities"]) if kind == "entity" else {}
    words = [w for w in (q or "").lower().split() if w]
    out = []
    for tid in sorted(refs):
        label = names.get(tid) or tid.split(":", 1)[1].replace("/", " ").replace("_", " ").title()
        if words and not all(w in (tid + " " + label).lower() for w in words):
            continue
        egg = tid + "_spawn_egg" if kind == "entity" else "minecraft:chest" if kind == "chest" else tid
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
    rule = next((r for r in load(ctx, name)["rules"] if r["kind"] == kind and r["target"] == target), None)
    if kind == "chest":
        got = summarize_chest(table) if table else {"pools": [], "drops": []}
        complex_ = any(d.get("complex") for d in got["drops"]) or any(p.get("complex") for p in got["pools"])
        return {"exists": bool(ref), "drops": got["drops"], "pools": got["pools"], "complex": complex_, "rule": rule}
    drops = summarize(table) if table else []
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
