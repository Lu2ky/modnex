"""KubeJS · Create: recetas de las máquinas de Create hechas con formularios.

Las recetas se escriben en el formato JSON que Create trae en su propio jar (el que sí carga en el juego) y se añaden con
`event.custom(...)`, que KubeJS documenta para cualquier receta de datapack. Así no depende de la API de KubeJS Create,
cuya sintaxis para 1.21.1 no está del todo documentada. Todo valor entra al script por json.dumps, nunca por interpolación.

Forma normalizada de una receta (la que guarda y entrega el panel):
  ins:  [{"k": "item"|"tag"|"fluid", "id": ..., "amount": mB}]          ingredientes
  outs: [{"k": "item"|"fluid", "id": ..., "count": n, "chance": 0..1, "amount": mB}]
"""
import json
import os
import re
from pathlib import Path

ID_RE = re.compile(r"[a-z0-9_.-]+:[a-z0-9_./-]+")
SLUG_RE = re.compile(r"[a-z0-9_]{1,40}")
KEY_RE = re.compile(r"[A-Z]")
MAX_RECIPES = 300
MAX_AMOUNT = 1_000_000
STORE = "modnex/create.json"
SCRIPT = "server_scripts/modnex_create.js"
SEQ_STEPS = ("deploying", "pressing", "cutting", "filling")

# Cada tipo: etiqueta, máquina (item cuyo icono se dibuja) y reglas. nin/nout = (mínimo, máximo).
TYPES = {
    "pressing": {"label": "Prensa mecánica", "machine": "create:mechanical_press", "nin": (1, 1), "nout": (1, 8)},
    "milling": {"label": "Muela", "machine": "create:millstone", "nin": (1, 1), "nout": (1, 8), "time": True},
    "crushing": {"label": "Ruedas trituradoras", "machine": "create:crushing_wheel", "nin": (1, 1), "nout": (1, 8), "time": True},
    "cutting": {"label": "Sierra mecánica", "machine": "create:mechanical_saw", "nin": (1, 1), "nout": (1, 8), "time": True},
    # El ventilador: el catalizador que tiene delante decide el tipo de receta. Fuego y lava usan las recetas de ahumador y de
    # horno alto de vanilla (así las lee Create); agua y fuego azul usan las suyas.
    "splashing": {"label": "Ventilador sobre agua (lavado)", "machine": "create:encased_fan", "extra": "minecraft:water_bucket", "catalyst": "Agua", "nin": (1, 1), "nout": (1, 8)},
    "smoking": {"label": "Ventilador sobre fuego (ahumado)", "machine": "create:encased_fan", "extra": "minecraft:campfire", "catalyst": "Fuego", "nin": (1, 1), "nout": (1, 1), "vanilla": True},
    "blasting": {"label": "Ventilador sobre lava (fundición)", "machine": "create:encased_fan", "extra": "minecraft:lava_bucket", "catalyst": "Lava", "nin": (1, 1), "nout": (1, 1), "vanilla": True},
    "haunting": {"label": "Ventilador sobre fuego azul (embrujo)", "machine": "create:encased_fan", "extra": "minecraft:soul_campfire", "catalyst": "Fuego azul", "nin": (1, 1), "nout": (1, 8)},
    "sandpaper_polishing": {"label": "Pulido con papel de lija", "machine": "create:sand_paper", "nin": (1, 1), "nout": (1, 1)},
    "mixing": {"label": "Mezcladora mecánica", "machine": "create:mechanical_mixer", "extra": "create:basin", "nin": (1, 9), "nout": (1, 8), "fluid_in": True, "fluid_out": True, "heat": True, "time": True},
    "compacting": {"label": "Compactación (prensa y cuenco)", "machine": "create:mechanical_press", "extra": "create:basin", "nin": (1, 9), "nout": (1, 8), "fluid_in": True, "fluid_out": True, "heat": True, "time": True},
    "deploying": {"label": "Desplegador", "machine": "create:deployer", "nin": (2, 2), "nout": (1, 8), "keep": True},
    "item_application": {"label": "Aplicar item sobre un bloque", "machine": "create:deployer", "nin": (2, 2), "nout": (1, 8)},
    "filling": {"label": "Surtidor (llenar)", "machine": "create:spout", "nin": (2, 2), "nout": (1, 1)},
    "emptying": {"label": "Drenador de items (vaciar)", "machine": "create:item_drain", "nin": (1, 1), "nout": (2, 2)},
    "mechanical_crafting": {"label": "Fabricador mecánico", "machine": "create:mechanical_crafter"},
    "sequenced_assembly": {"label": "Ensamblaje en secuencia", "machine": "create:mechanical_arm"},
}
FAN = {"water": "splashing", "fire": "smoking", "lava": "blasting", "soul_fire": "haunting"}   # catalizador -> tipo de receta
STEP_MACHINE = {"deploying": "create:deployer", "pressing": "create:mechanical_press", "cutting": "create:mechanical_saw", "filling": "create:spout"}


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


def _ing(v, label, fluid_ok):
    """Un ingrediente: item, tag o fluido."""
    if not isinstance(v, dict):
        raise ValueError(f"{label}: ingrediente no válido")
    k = v.get("k")
    if k in ("item", "tag"):
        return {"k": k, "id": _id(v.get("id"), label)}
    if k == "fluid":
        if not fluid_ok:
            raise ValueError(f"{label}: esta máquina no admite fluidos")
        fid = v.get("id")
        fid = "#" + _id(fid[1:], label) if isinstance(fid, str) and fid.startswith("#") else _id(fid, label)   # «#ns:tag»: un tag de fluidos
        return {"k": "fluid", "id": fid, "amount": _int(v.get("amount", 1000), f"{label}: cantidad", 1, MAX_AMOUNT)}
    raise ValueError(f"{label}: tipo de ingrediente no válido")


def _out(v, label, fluid_ok, chance_ok=True):
    if not isinstance(v, dict):
        raise ValueError(f"{label}: resultado no válido")
    if v.get("k") == "fluid":
        if not fluid_ok:
            raise ValueError(f"{label}: esta máquina no produce fluidos")
        return {"k": "fluid", "id": _id(v.get("id"), label), "amount": _int(v.get("amount", 1000), f"{label}: cantidad", 1, MAX_AMOUNT)}
    out = {"k": "item", "id": _id(v.get("id"), label), "count": _int(v.get("count", 1), f"{label}: cantidad", 1, 64)}
    if chance_ok and v.get("chance") not in (None, "", 1, 1.0):
        try:
            ch = float(v["chance"])
        except (TypeError, ValueError):
            raise ValueError(f"{label}: probabilidad no válida")
        if not 0 < ch <= 1:
            raise ValueError(f"{label}: la probabilidad va entre 0 y 1")
        out["chance"] = round(ch, 4)
    return out


def clean_recipe(r):
    """Valida una receta y devuelve su forma normalizada. Lanza ValueError con un mensaje legible."""
    if not isinstance(r, dict):
        raise ValueError("receta no válida")
    slug = str(r.get("id") or "")
    if not SLUG_RE.fullmatch(slug):
        raise ValueError(f"«{slug}»: el nombre solo puede tener minúsculas, números y _ (máx. 40)")
    kind = r.get("type")
    if kind not in TYPES:
        raise ValueError(f"«{slug}»: tipo de receta no válido")
    spec, label = TYPES[kind], TYPES[kind]["label"]
    out = {"id": slug, "type": kind}
    if kind == "mechanical_crafting":
        pattern, key = r.get("pattern"), r.get("key")
        if not isinstance(pattern, list) or not 1 <= len(pattern) <= 9 or not all(isinstance(p, str) and 1 <= len(p) <= 9 for p in pattern):
            raise ValueError(f"{label}: la cuadrícula va de 1×1 a 9×9")
        if len({len(p) for p in pattern}) != 1:
            raise ValueError(f"{label}: todas las filas deben medir lo mismo")
        used = {c for p in pattern for c in p if c != " "}
        if not used or not isinstance(key, dict) or used - set(key):
            raise ValueError(f"{label}: pon al menos un ingrediente y que cada letra tenga el suyo")
        if any(not KEY_RE.fullmatch(c) for c in used):
            raise ValueError(f"{label}: las letras de la cuadrícula deben ser mayúsculas")
        res = _out(r.get("result"), f"{label}: resultado", False, False)
        out.update(pattern=pattern, key={c: _ing(key[c], f"{label}: ingrediente {c}", False) for c in sorted(used)}, result=res)
        return out
    if kind == "sequenced_assembly":
        steps = r.get("steps")
        if not isinstance(steps, list) or not 1 <= len(steps) <= 12:
            raise ValueError(f"{label}: añade entre 1 y 12 pasos")
        outs = r.get("outs")
        if not isinstance(outs, list) or not 1 <= len(outs) <= 12:
            raise ValueError(f"{label}: añade entre 1 y 12 resultados")
        clean_steps = []
        for s in steps:
            t = s.get("t") if isinstance(s, dict) else None
            if t not in SEQ_STEPS:
                raise ValueError(f"{label}: paso no válido")
            step = {"t": t}
            if t == "deploying":
                step["held"] = _ing(s.get("held"), f"{label}: item del desplegador", False)
            elif t == "filling":
                step["fluid"] = _ing({**(s.get("fluid") or {}), "k": "fluid"}, f"{label}: fluido", True)
            elif t == "cutting" and s.get("time") not in (None, ""):
                step["time"] = _int(s["time"], f"{label}: tiempo", 1, 100000)
            clean_steps.append(step)
        cleaned = []
        for o in outs:
            c = _out({**o, "k": "item"} if isinstance(o, dict) else o, f"{label}: resultado", False, False)
            if isinstance(o, dict) and o.get("weight") not in (None, ""):
                try:
                    w = float(o["weight"])
                except (TypeError, ValueError):
                    raise ValueError(f"{label}: peso no válido")
                if not 0 < w <= 1000:
                    raise ValueError(f"{label}: el peso va entre 0 y 1000")
                c["weight"] = round(w, 3)
            cleaned.append(c)
        out.update(input=_ing(r.get("input"), f"{label}: ingrediente inicial", False),
                   transitional=_id(r.get("transitional"), f"{label}: item intermedio"), loops=_int(r.get("loops", 5), f"{label}: repeticiones", 1, 100),
                   steps=clean_steps, outs=cleaned)
        return out
    ins, outs = r.get("ins"), r.get("outs")
    lo, hi = spec["nin"]
    if not isinstance(ins, list) or not lo <= len(ins) <= hi:
        raise ValueError(f"{label}: necesita " + (f"{lo}" if lo == hi else f"entre {lo} y {hi}") + " ingredientes")
    lo, hi = spec["nout"]
    if not isinstance(outs, list) or not lo <= len(outs) <= hi:
        raise ValueError(f"{label}: necesita " + (f"{lo}" if lo == hi else f"entre {lo} y {hi}") + " resultados")
    out["ins"] = [_ing(i, f"{label}: ingrediente", spec.get("fluid_in", False) or kind == "filling") for i in ins]
    if spec.get("vanilla") and any(isinstance(o, dict) and o.get("chance") not in (None, "", 1, 1.0) for o in outs):
        raise ValueError(f"{label}: este tipo de receta no admite probabilidad")
    out["outs"] = [_out(o, f"{label}: resultado", spec.get("fluid_out", False) or kind == "emptying") for o in outs]
    if kind == "filling":
        kinds = sorted(i["k"] == "fluid" for i in out["ins"])
        if kinds != [False, True] or out["outs"][0]["k"] != "item":
            raise ValueError(f"{label}: un item y un fluido, y un item como resultado")
        out["ins"].sort(key=lambda i: i["k"] == "fluid")
    if kind == "emptying":
        if out["ins"][0]["k"] == "fluid" or sorted(o["k"] == "fluid" for o in out["outs"]) != [False, True]:
            raise ValueError(f"{label}: un item como entrada y un item y un fluido como resultado")
        out["outs"].sort(key=lambda o: o["k"] == "fluid")
    if kind in ("deploying", "item_application") and any(i["k"] == "fluid" for i in out["ins"]):
        raise ValueError(f"{label}: no admite fluidos")
    if spec.get("time") and r.get("time") not in (None, ""):
        out["time"] = _int(r["time"], f"{label}: tiempo", 1, 100000)
    if spec.get("heat") and r.get("heat") not in (None, ""):
        if r["heat"] not in ("heated", "superheated"):
            raise ValueError(f"{label}: calor no válido")
        out["heat"] = r["heat"]
    if spec.get("keep") and r.get("keep") is True:
        out["keep"] = True
    return out


def clean_list(recipes):
    if not isinstance(recipes, list):
        raise ValueError("lista de recetas no válida")
    if len(recipes) > MAX_RECIPES:
        raise ValueError(f"demasiadas recetas (máx. {MAX_RECIPES})")
    out, seen = [], set()
    for r in recipes:
        c = clean_recipe(r)
        if c["id"] in seen:
            raise ValueError(f"«{c['id']}»: nombre repetido")
        seen.add(c["id"])
        out.append(c)
    return out


# ---------- JSON de Create (el mismo formato de las recetas que trae el mod) ----------
def ing_json(i):
    if i["k"] == "item":
        return {"item": i["id"]}
    if i["k"] == "tag":
        return {"tag": i["id"]}
    if i["id"].startswith("#"):
        return {"type": "neoforge:tag", "tag": i["id"][1:], "amount": i["amount"]}
    return {"type": "neoforge:single", "fluid": i["id"], "amount": i["amount"]}


def out_json(o):
    if o["k"] == "fluid":
        return {"id": o["id"], "amount": o["amount"]}
    j = {"id": o["id"]}
    if o.get("count", 1) > 1:
        j["count"] = o["count"]
    if "chance" in o:
        j["chance"] = o["chance"]
    return j


def to_json(r):
    """La receta como JSON de datapack de Create."""
    kind = r["type"]
    if kind == "mechanical_crafting":
        return {"type": "create:mechanical_crafting", "accept_mirrored": False, "category": "misc", "pattern": r["pattern"],
                "key": {c: ing_json(i) for c, i in r["key"].items()}, "result": out_json(r["result"]), "show_notification": False}
    if kind == "sequenced_assembly":
        t = {"item": r["transitional"]}
        seq = []
        for s in r["steps"]:
            base = {"type": "create:" + s["t"], "ingredients": [dict(t)], "results": [{"id": r["transitional"]}]}
            if s["t"] == "deploying":
                base["ingredients"].append(ing_json(s["held"]))
            elif s["t"] == "filling":
                base["ingredients"].append(ing_json(s["fluid"]))
            elif s["t"] == "cutting" and "time" in s:
                base["processing_time"] = s["time"]
            seq.append(base)
        results = []
        for o in r["outs"]:
            j = out_json(o)
            if "weight" in o:
                j["chance"] = o["weight"]
            results.append(j)
        return {"type": "create:sequenced_assembly", "ingredient": ing_json(r["input"]), "loops": r["loops"], "results": results,
                "sequence": seq, "transitional_item": {"id": r["transitional"]}}
    if TYPES[kind].get("vanilla"):
        return {"type": "minecraft:" + kind, "category": "misc", "ingredient": ing_json(r["ins"][0]), "result": out_json(r["outs"][0]),
                "cookingtime": 100, "experience": 0.0}
    j = {"type": "create:" + kind, "ingredients": [ing_json(i) for i in r["ins"]], "results": [out_json(o) for o in r["outs"]]}
    if "time" in r:
        j["processing_time"] = r["time"]
    if "heat" in r:
        j["heat_requirement"] = r["heat"]
    if r.get("keep"):
        j["keep_held_item"] = True
    return j


def item_ids(r):
    """Items (no tags ni fluidos) que la receta nombra: el script la salta si alguno no existe en el servidor."""
    found = []
    pools = [r.get("ins", []), r.get("outs", []), list((r.get("key") or {}).values()), [r["result"]] if r.get("result") else [],
             [r["input"]] if r.get("input") else [], [s.get("held") for s in r.get("steps", []) if s.get("held")]]
    for pool in pools:
        found += [i["id"] for i in pool if i and i.get("k") == "item"]
    if r.get("transitional"):
        found.append(r["transitional"])
    return sorted(set(found))


def build_script(recipes):
    payload = [{"id": r["id"], "items": item_ids(r), "recipe": to_json(r)} for r in recipes]
    data = json.dumps(payload, ensure_ascii=False, indent=1)
    return f"""// Generado por Modnex desde la sección Create. No lo edites a mano: se reescribe al guardar.
// Las recetas usan el formato JSON de Create y se añaden con event.custom. Se aplica con /reload.
// Si algún item de una receta no existe en el servidor, esa receta se salta y se avisa en el log.
const MODNEX_CREATE = {data}

ServerEvents.recipes(event => {{
  let added = 0
  MODNEX_CREATE.forEach(r => {{
    const missing = r.items.filter(id => !Item.exists(id))
    if (missing.length) {{
      console.warn(`[modnex] receta de Create ${{r.id}} saltada: no existen ${{missing.join(', ')}}`)
      return
    }}
    try {{
      event.custom(r.recipe).id('modnex:create_' + r.id)
      added++
    }} catch (e) {{
      console.error(`[modnex] receta de Create ${{r.id}} falló: ${{e}}`)
    }}
  }})
  console.info(`[modnex] ${{added}} de ${{MODNEX_CREATE.length}} recetas de Create añadidas`)
}})
"""


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
        recipes = clean_list(json.loads(src.read_text(encoding="utf-8")).get("recipes", [])) if src.is_file() else []
    except (ValueError, OSError, AttributeError):
        recipes = []
    return {"recipes": recipes, "types": {k: {kk: vv for kk, vv in v.items()} for k, v in TYPES.items()}, "step_machine": STEP_MACHINE, "fan": FAN}


def save(ctx, name, recipes):
    recipes = clean_list(recipes)
    base = _base(ctx, name)
    _write(base / STORE, json.dumps({"recipes": recipes}, ensure_ascii=False, indent=2) + "\n")
    target = base / SCRIPT
    if recipes:
        _write(target, build_script(recipes))
    elif target.is_file():
        target.unlink()
    return recipes


def output_ids(r):
    """Items que produce la receta (para buscarla por su resultado)."""
    if r["type"] == "mechanical_crafting":
        return {r["result"]["id"]}
    return {o["id"] for o in r.get("outs", []) if o["k"] == "item"}


def as_layout(r):
    """La receta guardada en la forma que usa el dibujo de recetas existentes (la misma que lee kubejs.create_layout)."""
    kind = r["type"]
    if kind == "mechanical_crafting":
        return {"skin": "create", "type": kind, "pattern": r["pattern"], "key": r["key"], "outs": [r["result"]]}
    if kind == "sequenced_assembly":
        return {"skin": "create", "type": kind, "ins": [r["input"]], "outs": r["outs"], "transitional": r["transitional"], "loops": r["loops"], "steps": r["steps"]}
    lay = {"skin": "create", "type": kind, "ins": r["ins"], "outs": r["outs"]}
    for k in ("time", "heat", "keep"):
        if k in r:
            lay[k] = r[k]
    return lay


def delete(ctx, name, slug):
    recipes = load(ctx, name)["recipes"]
    kept = [r for r in recipes if r["id"] != slug]
    if len(kept) == len(recipes):
        raise ValueError("esa receta no existe en la lista de Create")
    return save(ctx, name, kept)
