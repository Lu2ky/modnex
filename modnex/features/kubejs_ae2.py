"""KubeJS · Applied Energistics 2: recetas de sus máquinas hechas con formularios.

Mismo esquema que Create: cada receta se valida, se guarda en `kubejs/modnex/ae2.json` y se escribe como JSON de AE2 (el mismo que trae
su jar) dentro de `server_scripts/modnex_ae2.js`, añadido con `event.custom`. Se aplica con /reload. Solo se cubren las máquinas que
transforman items o fluidos con una receta fija: inscriptor, cargador, transformación (en el mundo, con agua y cristales) y el
manipulador de entropía. Matter cannon, mejora de celdas y desensamblado no entran aquí.
"""
import json
import os
import re
from pathlib import Path

ID_RE = re.compile(r"[a-z0-9_.-]+:[a-z0-9_./-]+")
SLUG_RE = re.compile(r"[a-z0-9_]{1,40}")
MAX_RECIPES = 200
MAX_COUNT = 64
STORE = "modnex/ae2.json"
SCRIPT = "server_scripts/modnex_ae2.js"
INSCRIBER_MODES = ("inscribe", "press")
ENTROPY_MODES = ("heat", "cool")
CIRCUMSTANCES = ("none", "explosion")

# Etiqueta, máquina (item cuyo modelo se dibuja) y lo que admite cada tipo.
TYPES = {
    "inscriber": {"label": "Inscriptor", "machine": "ae2:inscriber"},
    "charger": {"label": "Cargador", "machine": "ae2:charger"},
    "transform": {"label": "Transformación (agua y cristales)", "machine": "ae2:quartz_block"},
    "entropy": {"label": "Manipulador de entropía", "machine": "ae2:entropy_manipulator"},
}


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


def _ing(v, label):
    """Un ingrediente de item o de tag (AE2 no usa fluidos en estas recetas)."""
    if not isinstance(v, dict) or v.get("k") not in ("item", "tag"):
        raise ValueError(f"{label}: ingrediente no válido")
    return {"k": v["k"], "id": _id(v.get("id"), label)}


def _result(v, label):
    if not isinstance(v, dict):
        raise ValueError(f"{label}: resultado no válido")
    return {"id": _id(v.get("id"), label), "count": _int(v.get("count", 1), f"{label}: cantidad", 1, MAX_COUNT)}


def _block_or_fluid(v, label):
    """Entrada o salida de un manipulador de entropía: un bloque o un fluido, por id exacto (sin tags)."""
    if not isinstance(v, dict) or v.get("k") not in ("block", "fluid"):
        raise ValueError(f"{label}: elige un bloque o un fluido")
    return {"k": v["k"], "id": _id(v.get("id"), label)}


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
    label = TYPES[kind]["label"]
    out = {"id": slug, "type": kind}
    if kind == "inscriber":
        mode = r.get("mode") or "inscribe"
        if mode not in INSCRIBER_MODES:
            raise ValueError(f"{label}: modo no válido")
        ing = r.get("ingredients") or {}
        if not isinstance(ing, dict) or not ing.get("middle") or not ing.get("top"):
            raise ValueError(f"{label}: pon el ingrediente de la parte de arriba y el del centro")
        if mode == "press" and not ing.get("bottom"):
            raise ValueError(f"{label}: el modo prensa necesita también la pieza de abajo")
        if mode == "inscribe" and ing.get("bottom"):
            raise ValueError(f"{label}: el modo inscribir no usa pieza de abajo (usa prensa)")
        out.update(mode=mode, ingredients={k: _ing(ing[k], f"{label}: {k}") for k in ("top", "middle", "bottom") if ing.get(k)},
                   result=_result(r.get("result"), f"{label}: resultado"))
        return out
    if kind == "charger":
        out.update(ingredient=_ing(r.get("ingredient"), f"{label}: ingrediente"), result=_result(r.get("result"), f"{label}: resultado"))
        return out
    if kind == "transform":
        ins = r.get("ingredients")
        if not isinstance(ins, list) or not 2 <= len(ins) <= 9:
            raise ValueError(f"{label}: entre 2 y 9 ingredientes")
        circ = r.get("circumstance") or "none"
        if circ not in CIRCUMSTANCES:
            raise ValueError(f"{label}: circunstancia no válida")
        out.update(ingredients=[_ing(i, f"{label}: ingrediente {n + 1}") for n, i in enumerate(ins)], circumstance=circ,
                   result=_result(r.get("result"), f"{label}: resultado"))
        return out
    if kind == "entropy":
        mode = r.get("mode")
        if mode not in ENTROPY_MODES:
            raise ValueError(f"{label}: modo no válido (calentar o enfriar)")
        inp, outp = _block_or_fluid(r.get("input"), f"{label}: entrada"), _block_or_fluid(r.get("output"), f"{label}: salida")
        if inp == outp:
            raise ValueError(f"{label}: la entrada y la salida no pueden ser lo mismo")
        out.update(mode=mode, input=inp, output=outp)
        return out
    raise ValueError(f"«{slug}»: tipo de receta no válido")


def clean_list(recipes):
    if not isinstance(recipes, list) or len(recipes) > MAX_RECIPES:
        raise ValueError(f"hasta {MAX_RECIPES} recetas de AE2")
    out, slugs = [], set()
    for r in recipes:
        c = clean_recipe(r)
        if c["id"] in slugs:
            raise ValueError(f"«{c['id']}»: nombre repetido")
        slugs.add(c["id"]); out.append(c)
    return out


def ing_json(i):
    return {"item": i["id"]} if i["k"] == "item" else {"tag": i["id"]}


def res_json(r):
    return {"count": r["count"], "id": r["id"]}


def to_json(r):
    """La receta como JSON de AE2 (formatos verificados en appliedenergistics2-19.2.19.jar)."""
    kind = r["type"]
    if kind == "inscriber":
        return {"type": "ae2:inscriber", "mode": r["mode"], "ingredients": {k: ing_json(v) for k, v in r["ingredients"].items()}, "result": res_json(r["result"])}
    if kind == "charger":
        return {"type": "ae2:charger", "ingredient": ing_json(r["ingredient"]), "result": res_json(r["result"])}
    if kind == "transform":
        j = {"type": "ae2:transform", "ingredients": [ing_json(i) for i in r["ingredients"]], "result": res_json(r["result"])}
        if r["circumstance"] != "none":
            j["circumstance"] = {"type": r["circumstance"]}
        return j
    def side(v):
        return {"block": {"id": v["id"]}} if v["k"] == "block" else {"fluid": {"id": v["id"]}}
    return {"type": "ae2:entropy", "mode": r["mode"], "input": side(r["input"]), "output": side(r["output"])}


def item_ids(r):
    """Items que la receta nombra (sin tags ni fluidos). El script salta la receta si alguno no existe en el servidor."""
    found = []
    if r["type"] == "inscriber":
        found += [i["id"] for i in r["ingredients"].values() if i["k"] == "item"] + [r["result"]["id"]]
    elif r["type"] == "charger":
        found += [r["ingredient"]["id"] if r["ingredient"]["k"] == "item" else None, r["result"]["id"]]
    elif r["type"] == "transform":
        found += [i["id"] for i in r["ingredients"] if i["k"] == "item"] + [r["result"]["id"]]
    else:
        found += [v["id"] for v in (r["input"], r["output"]) if v["k"] == "block" and v["id"] != "minecraft:air"]
    return sorted({f for f in found if f})


def build_script(recipes):
    payload = [{"id": r["id"], "items": item_ids(r), "recipe": to_json(r)} for r in recipes]
    data = json.dumps(payload, ensure_ascii=False, indent=1)
    return f"""// Generado por Modnex desde la sección Applied Energistics 2. No lo edites a mano: se reescribe al guardar.
// Las recetas usan el formato JSON de AE2 y se añaden con event.custom. Se aplica con /reload.
// Si algún item de una receta no existe en el servidor, esa receta se salta y se avisa en el log.
const MODNEX_AE2 = {data}

ServerEvents.recipes(event => {{
  let added = 0
  MODNEX_AE2.forEach(r => {{
    const missing = r.items.filter(id => !Item.exists(id))
    if (missing.length) {{
      console.warn(`[modnex] receta de AE2 ${{r.id}} saltada: no existen ${{missing.join(', ')}}`)
      return
    }}
    try {{
      event.custom(r.recipe).id('modnex:ae2_' + r.id)
      added++
    }} catch (e) {{
      console.error(`[modnex] receta de AE2 ${{r.id}} falló: ${{e}}`)
    }}
  }})
  console.info(`[modnex] ${{added}} de ${{MODNEX_AE2.length}} recetas de AE2 añadidas`)
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
    return {"recipes": recipes, "types": TYPES, "modes": {"inscriber": INSCRIBER_MODES, "entropy": ENTROPY_MODES}, "circumstances": CIRCUMSTANCES}


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
