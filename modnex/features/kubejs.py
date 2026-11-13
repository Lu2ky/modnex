"""Recetas de KubeJS desde el panel: catálogo de items de todos los mods, iconos y generación del script.

El catálogo sale de los archivos de idioma y de las texturas de los jars de `mods/`, así que no hace falta
arrancar el servidor. La lista de recetas (fuente de verdad) se guarda en `kubejs/modnex/recetas.json` y de ella
se genera `kubejs/server_scripts/modnex_recetas.js`. Las recetas se aplican con `/reload` en el servidor.
"""
import base64
import collections
import hashlib
import json
import os
import re
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from . import kubejs_create

ID_RE = re.compile(r"[a-z0-9_.-]+:[a-z0-9_./-]+")
SLUG_RE = re.compile(r"[a-z0-9_]{1,40}")
LANG_RE = re.compile(r"assets/([a-z0-9_.-]+)/lang/en_us\.json")
NAME_KEY = re.compile(r"(item|block)\.([a-z0-9_.-]+?)\.([a-z0-9_/.-]+)")
FLUID_KEY = re.compile(r"fluid(?:_type)?\.([a-z0-9_.-]+?)\.([a-z0-9_/.-]+)")
TEX_RE = re.compile(r"assets/([a-z0-9_.-]+)/textures/([a-z0-9_/.-]+)\.png")
LOOT_RE = re.compile(r"data/([a-z0-9_.-]+)/loot_tables?/(blocks|entities)/([a-z0-9_/.-]+)\.json")
ENTITY_KEY = re.compile(r"entity\.([a-z0-9_.-]+?)\.([a-z0-9_/.-]+)")
RECIPE_RE = re.compile(r"data/([a-z0-9_.-]+)/(?:recipe|recipes)/([a-z0-9_/.-]+)\.json")
MC_VERSION_RE = re.compile(r"\d+\.\d+(?:\.\d+)?")
MOJANG_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
MODEL_RE = re.compile(r"assets/([a-z0-9_.-]+)/models/([a-z0-9_/.-]+)\.json")
TEX_ORDER = ("layer0", "all", "side", "top", "front", "texture", "particle", "end", "north", "up")
SKIP_SUFFIX = (".tooltip", ".desc", ".description", ".hint", ".tip")
MAX_RESULTS = 120
MAX_COUNT = 64
CRAFT_TYPES = ("shaped", "shapeless")
COOK_TYPES = ("smelting", "blasting", "smoking", "campfire")
SINGLE_TYPES = COOK_TYPES + ("stonecutting",)
TYPES = CRAFT_TYPES + SINGLE_TYPES
DEFAULT_TIME = {"campfire": 600}

_LOCK = threading.Lock()
_CACHE = {"sig": None, "items": [], "textures": {}, "models": {}, "icons": {}, "zips": {}, "parsed": {},
          "recipe_refs": {}, "recipes": None, "names": {}, "fluids": {}, "blockmodels": {}, "texuris": {}, "loot": {"blocks": {}, "entities": {}}, "entities": {}}
_ICON_LOCK = threading.Lock()   # ZipFile no es seguro entre hilos: los iconos se calculan de uno en uno


def _mods_dir(ctx, name):
    return Path(ctx.server_path(name)) / "mods"


def _mc_version(ctx, name):
    try:
        v = json.loads((Path(ctx.server_path(name)) / ".manager.json").read_text(encoding="utf-8")).get("mc")
    except (OSError, ValueError):
        return None
    return v if isinstance(v, str) and MC_VERSION_RE.fullmatch(v) else None


def _client_cache(ctx, name):
    v = _mc_version(ctx, name)
    return Path(ctx.here) / "cache" / f"minecraft-{v}-client.jar" if v else None


# Interfaces de Minecraft que se usan de fondo en el editor de recetas. Se leen del cliente oficial que el panel ya
# descarga a su caché (nunca se guardan en el repositorio) y se entregan como data URI.
GUI_SKINS = {"crafting": "gui/container/crafting_table", "furnace": "gui/container/furnace", "blast_furnace": "gui/container/blast_furnace",
             "smoker": "gui/container/smoker", "stonecutter": "gui/container/stonecutter", "smithing": "gui/container/smithing",
             "campfire": "item/campfire"}   # la fogata no tiene interfaz: se dibuja su sprite y se coloca el item encima
_GUI = {"key": None, "tex": {}}


def gui_textures(ctx, name):
    """{piel: data URI} de las interfaces de vanilla. Vacío si el cliente de Minecraft aún no está descargado."""
    jar = _client_cache(ctx, name)
    if not jar or not jar.is_file():
        return {}
    st = jar.stat()
    key = (str(jar), st.st_mtime_ns, st.st_size)
    with _LOCK:
        if _GUI["key"] == key:
            return _GUI["tex"]
    out = {}
    try:
        with zipfile.ZipFile(jar) as z:
            for skin, fname in GUI_SKINS.items():
                try:
                    raw = z.read(f"assets/minecraft/textures/{fname}.png")
                except KeyError:
                    continue
                out[skin] = "data:image/png;base64," + base64.b64encode(raw).decode()
    except (OSError, zipfile.BadZipFile):
        return {}
    with _LOCK:
        _GUI["key"], _GUI["tex"] = key, out
    return out


def _vanilla_jars(ctx, name):
    """Jars de Minecraft: el cliente descargado (texturas, modelos, nombres) y el jar `-extra` del servidor
    (nombres y recetas de vanilla). Van primero para que vanilla gane sobre los mods en `minecraft:`."""
    out = []
    cli = _client_cache(ctx, name)
    if cli and cli.is_file():
        out.append(cli)
    extra = sorted((Path(ctx.server_path(name)) / "libraries" / "net" / "minecraft" / "server").glob("*/server-*-extra.jar"))
    return out + extra[-1:]


def vanilla_status(ctx, name):
    cli = _client_cache(ctx, name)
    return {"version": _mc_version(ctx, name), "client": bool(cli and cli.is_file()),
            "names": any(j.name.endswith("-extra.jar") for j in _vanilla_jars(ctx, name))}


def _index(ctx, name):
    """Items (id, nombre), texturas y modelos de vanilla y de todos los mods. Se recalcula si cambian los jars."""
    mods = _mods_dir(ctx, name)
    jars = _vanilla_jars(ctx, name) + (sorted(mods.glob("*.jar")) if mods.is_dir() else [])
    sig = tuple((j.name, j.stat().st_mtime_ns) for j in jars)
    with _LOCK:
        if _CACHE["sig"] == sig:
            return _CACHE["items"], _CACHE["textures"], _CACHE["models"]
    names, textures, models, recipe_refs, from_block, fluid_names = {}, {}, {}, {}, set(), {"minecraft:water": "Water", "minecraft:lava": "Lava"}
    loot_refs, entity_names = {"blocks": {}, "entities": {}}, {}
    for jar in jars:
        try:
            z = zipfile.ZipFile(jar)
        except (zipfile.BadZipFile, OSError):
            continue
        with z:
            for entry in z.namelist():
                if entry.endswith(".png"):
                    m = TEX_RE.fullmatch(entry)
                    if m:
                        textures.setdefault(f"{m.group(1)}:{m.group(2)}", (str(jar), entry))
                    continue
                if entry.endswith(".json") and "/models/" in entry:
                    m = MODEL_RE.fullmatch(entry)
                    if m:
                        models.setdefault(f"{m.group(1)}:{m.group(2)}", (str(jar), entry))
                    continue
                if entry.startswith("data/") and entry.endswith(".json"):
                    m = RECIPE_RE.fullmatch(entry)
                    if m:
                        recipe_refs.setdefault(f"{m.group(1)}:{m.group(2)}", (str(jar), entry))
                        continue
                    m = LOOT_RE.fullmatch(entry)
                    if m:
                        loot_refs[m.group(2)].setdefault(f"{m.group(1)}:{m.group(3)}", (str(jar), entry))
                    continue
                if not LANG_RE.fullmatch(entry):
                    continue
                try:
                    data = json.loads(z.read(entry).decode("utf-8", "replace"))
                except ValueError:
                    continue
                for key, val in data.items():
                    em = ENTITY_KEY.fullmatch(key)
                    if em and isinstance(val, str) and "." not in em.group(2):
                        entity_names.setdefault(f"{em.group(1)}:{em.group(2)}", val)
                        continue
                    fm = FLUID_KEY.fullmatch(key)
                    if fm and isinstance(val, str) and "." not in fm.group(2):
                        fluid_names.setdefault(f"{fm.group(1)}:{fm.group(2)}", val)
                        continue
                    m = NAME_KEY.fullmatch(key)
                    if not m or key.endswith(SKIP_SUFFIX) or not isinstance(val, str) or "." in m.group(3):
                        continue   # los ids con punto son variantes de traducción (estandartes, tooltips), no items
                    iid = f"{m.group(2)}:{m.group(3)}"
                    if re.search(r"%\d?\$?s", val):   # nombre dinámico («%1$s…»): se nombra a partir del id
                        val = m.group(3).replace("_", " ").replace("/", " ").title()
                    names.setdefault(iid, val)
                    if m.group(1) == "block":
                        from_block.add(iid)
    # un bloque solo es un item si tiene modelo de item (así se descartan carteles de pared, cultivos, etc.)
    for iid in list(names):
        ns, _, path = iid.partition(":")
        if iid in from_block and f"{ns}:item/{path}" not in models and f"{ns}:block/{path}" not in models:
            del names[iid]
    items = [{"id": k, "name": v} for k, v in sorted(names.items())]
    with _LOCK:
        old = _CACHE.get("zips", {})
        _CACHE.update(sig=sig, items=items, textures=textures, models=models, icons={}, zips={}, parsed={},
                      recipe_refs=recipe_refs, recipes=None, names=names, fluids=fluid_names, blockmodels={}, texuris={}, loot=loot_refs, entities=entity_names)
    for z in old.values():
        z.close()
    return items, textures, models


def _read(ref):
    """Bytes de una entrada de un jar. El zip se abre una vez y se reutiliza mientras no cambien los jars."""
    with _LOCK:
        z = _CACHE["zips"].get(ref[0])
        if z is None:
            try:
                z = zipfile.ZipFile(ref[0])
            except (zipfile.BadZipFile, OSError):
                return None
            _CACHE["zips"][ref[0]] = z
    try:
        return z.read(ref[1])
    except (KeyError, zipfile.BadZipFile, OSError):
        return None


def _model(models, mid):
    if mid not in models:
        return None
    with _LOCK:
        if mid in _CACHE["parsed"]:
            return _CACHE["parsed"][mid]
    raw = _read(models[mid])
    try:
        parsed = json.loads(raw.decode("utf-8", "replace")) if raw is not None else None
    except ValueError:
        parsed = None
    with _LOCK:
        _CACHE["parsed"][mid] = parsed
    return parsed


def _textures_of(models, mid, depth=0):
    """Texturas de un modelo siguiendo su cadena de `parent`; lo del hijo pisa a lo del padre."""
    m = _model(models, mid) if depth < 10 else None
    if not m:
        return {}
    parent = m.get("parent")
    base = {}
    if isinstance(parent, str) and not parent.startswith("builtin/"):
        base = _textures_of(models, parent if ":" in parent else "minecraft:" + parent, depth + 1)
    base.update(m.get("textures") or {})
    return base


def _resolve(tex, value):
    """Sigue las referencias «#clave» hasta llegar a una textura «ns:ruta»."""
    for _ in range(10):
        if not isinstance(value, str) or not value.startswith("#"):
            break
        value = tex.get(value[1:])
    return value if isinstance(value, str) and not value.startswith("#") else None


def _icon(textures, models, iid):
    ns, _, path = iid.partition(":")
    texture = None
    for mid in (f"{ns}:item/{path}", f"{ns}:block/{path}"):
        if mid not in models:
            continue
        tex = _textures_of(models, mid)
        for key in TEX_ORDER:
            texture = _resolve(tex, tex.get(key))
            if texture:
                break
        if not texture and tex:
            texture = next((v for v in (_resolve(tex, x) for x in tex.values()) if v), None)
        if texture:
            break
    if not texture:
        # sin modelo: a veces el nombre de la textura coincide con el del item
        texture = f"{ns}:item/{path}" if f"{ns}:item/{path}" in textures else (f"{ns}:block/{path}" if f"{ns}:block/{path}" in textures else None)
    if texture and ":" not in texture:
        texture = "minecraft:" + texture
    ref = textures.get(texture) if texture else None
    if not ref:
        return None
    raw = _read(ref)
    return ("data:image/png;base64," + base64.b64encode(raw).decode()) if raw else None


# ---------- modelos de bloque (para dibujar las máquinas como en el inventario del juego) ----------
MAX_MODEL_ELEMENTS = 160
MAX_MODEL_TEXTURE = 70_000
DEFAULT_GUI = {"rotation": [30, 225, 0], "translation": [0, 0, 0], "scale": [0.625, 0.625, 0.625]}
FACE_NAMES = ("north", "south", "east", "west", "up", "down")


def _model_chain(models, mid):
    out, seen = [], set()
    while mid and mid not in seen and len(out) < 12:
        seen.add(mid)
        m = _model(models, mid)
        if not m:
            break
        out.append(m)
        parent = m.get("parent")
        if not isinstance(parent, str) or parent.startswith("builtin/"):
            break
        mid = parent if ":" in parent else "minecraft:" + parent
    return out


def _nums(v, n, lo=-80.0, hi=80.0):
    if not isinstance(v, list) or len(v) != n:
        return None
    try:
        return [max(lo, min(hi, float(x))) for x in v]
    except (TypeError, ValueError):
        return None


def block_model(ctx, name, item_id):
    """Cubos, transformación de inventario y lista de texturas de un item/bloque, o None si su modelo no tiene cubos
    (items planos, modelos especiales, entidades): entonces se usa el icono plano. Se guarda en caché por conjunto de jars."""
    _check_id(item_id, "item")
    _, textures, models = _index(ctx, name)
    with _LOCK:
        cached = _CACHE["blockmodels"]
        if item_id in cached:
            return cached[item_id]
    result = _build_block_model(textures, models, item_id)
    with _LOCK:
        _CACHE["blockmodels"][item_id] = result
    return result


def _build_block_model(textures, models, item_id):
    ns, _, path = item_id.partition(":")
    mid = next((m for m in (f"{ns}:item/{path}", f"{ns}:block/{path}") if m in models), None)
    if not mid:
        return None
    chain = _model_chain(models, mid)
    elements = next((m["elements"] for m in chain if isinstance(m.get("elements"), list) and m["elements"]), None)
    if not elements or len(elements) > MAX_MODEL_ELEMENTS:
        return None
    tex = _textures_of(models, mid)
    display = {k: list(v) for k, v in DEFAULT_GUI.items()}
    for m in reversed(chain):
        gui = (m.get("display") or {}).get("gui")
        if isinstance(gui, dict):
            for k, lo, hi in (("rotation", -360.0, 360.0), ("translation", -80.0, 80.0), ("scale", 0.0, 4.0)):
                got = _nums(gui.get(k), 3, lo, hi)
                if got:
                    display[k] = got
    out, used = [], []
    for el in elements:
        if not isinstance(el, dict):
            continue
        frm, to = _nums(el.get("from"), 3, -16.0, 32.0), _nums(el.get("to"), 3, -16.0, 32.0)
        if not frm or not to:
            continue
        faces = {}
        for d in FACE_NAMES:
            f = (el.get("faces") or {}).get(d)
            if not isinstance(f, dict):
                continue
            t = _resolve(tex, f.get("texture"))
            if t and ":" not in t:
                t = "minecraft:" + t
            if not t or t not in textures:
                continue
            face = {"t": t}
            uv = _nums(f.get("uv"), 4, -16.0, 32.0)
            if uv:
                face["uv"] = uv
            if f.get("rotation") in (90, 180, 270):
                face["r"] = f["rotation"]
            if isinstance(f.get("tintindex"), int) and f["tintindex"] >= 0:
                face["tint"] = 1          # hierba, hojas...: el juego las tiñe según el bioma
            faces[d] = face
            if t not in used:
                used.append(t)
        if not faces:
            continue
        item = {"from": frm, "to": to, "faces": faces}
        rot = el.get("rotation")
        if isinstance(rot, dict) and rot.get("axis") in ("x", "y", "z"):
            origin, angle = _nums(rot.get("origin"), 3, -16.0, 32.0), rot.get("angle")
            if origin and isinstance(angle, (int, float)):
                item["rot"] = {"o": origin, "a": rot["axis"], "d": float(angle)}
        out.append(item)
    if not out:
        return None
    return {"elements": out, "tex": used, "display": display}


def texture_uris(ctx, name, ids):
    """{id de textura: data URI} (las demasiado grandes se omiten). Se guardan en caché porque muchos bloques las comparten."""
    _, textures, _ = _index(ctx, name)
    out = {}
    for t in ids:
        with _LOCK:
            have = t in _CACHE["texuris"]
            uri = _CACHE["texuris"].get(t)
        if not have:
            ref = textures.get(t)
            raw = _read(ref) if ref else None
            uri = ("data:image/png;base64," + base64.b64encode(raw).decode()) if raw and len(raw) <= MAX_MODEL_TEXTURE else None
            with _LOCK:
                _CACHE["texuris"][t] = uri
        if uri:
            out[t] = uri
    return out


def block_models(ctx, name, ids):
    """({id: modelo|None}, {textura: data URI}) para varios items; las texturas van una sola vez aunque las compartan."""
    models = {i: block_model(ctx, name, i) for i in ids}
    used = list(dict.fromkeys(t for m in models.values() if m for t in m["tex"]))
    return models, texture_uris(ctx, name, used)


def fluids(ctx, name):
    """Fluidos conocidos (vanilla y mods) con su nombre y su textura de «fluido quieto» (una tira vertical de fotogramas)."""
    _, textures, _ = _index(ctx, name)
    with _LOCK:
        names = dict(_CACHE["fluids"])
    out = []
    for fid, label in sorted(names.items()):
        ns, _, path = fid.partition(":")
        tex = next((textures[t] for t in (f"{ns}:fluid/{path}_still", f"{ns}:block/{path}_still", f"{ns}:fluid/{path}") if t in textures), None)
        raw = _read(tex) if tex else None
        item = {"id": fid, "name": label, "icon": ("data:image/png;base64," + base64.b64encode(raw).decode()) if raw and len(raw) < 60_000 else None}
        if fid == "minecraft:water":
            item["tint"] = "#3f76e4"   # el agua es gris en su textura: el juego la tiñe según el bioma
        out.append(item)
    return out


def search(ctx, name, q="", limit=MAX_RESULTS):
    items, textures, models = _index(ctx, name)
    words = [w for w in (q or "").lower().split() if w]
    out = []
    for it in items:
        hay = (it["id"] + " " + it["name"]).lower()
        if words and not all(w in hay for w in words):
            continue
        out.append(it)
        if len(out) >= min(limit, MAX_RESULTS):
            break
    return [{**it, "icon": _cached_icon(textures, models, it["id"])} for it in out]


def _cached_icon(textures, models, iid):
    with _LOCK:
        if iid in _CACHE["icons"]:
            return _CACHE["icons"][iid]
    with _ICON_LOCK:
        icon = _icon(textures, models, iid)
    with _LOCK:
        _CACHE["icons"][iid] = icon
    return icon


def _check_id(value, label):
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ValueError(f"{label}: id de item no válido")
    return value


def clean_recipe(r):
    """Valida una receta y devuelve su forma normalizada. Lanza ValueError con un mensaje legible.
    Las recetas de un solo ingrediente (horno, ahumador, fogata, cortapiedras) usan solo la casilla 0."""
    if not isinstance(r, dict):
        raise ValueError("receta no válida")
    slug = str(r.get("id") or "")
    if not SLUG_RE.fullmatch(slug):
        raise ValueError(f"«{slug}»: el nombre solo puede tener minúsculas, números y _ (máx. 40)")
    kind = r.get("type")
    if kind not in TYPES:
        raise ValueError(f"«{slug}»: tipo no válido")
    res = r.get("result") or {}
    out = _check_id(res.get("id"), f"«{slug}» resultado")
    try:
        count = int(res.get("count", 1))
    except (TypeError, ValueError):
        raise ValueError(f"«{slug}»: cantidad no válida")
    if not 1 <= count <= MAX_COUNT:
        raise ValueError(f"«{slug}»: la cantidad debe estar entre 1 y {MAX_COUNT}")
    grid = r.get("grid")
    if not isinstance(grid, list) or len(grid) != 9:
        raise ValueError(f"«{slug}»: la mesa tiene que tener 9 casillas")
    cells = [None if c in (None, "") else _check_id(c, f"«{slug}»") for c in grid]
    if kind in SINGLE_TYPES:
        if not cells[0]:
            raise ValueError(f"«{slug}»: pon el ingrediente")
        cells = [cells[0]] + [None] * 8
    elif not any(cells):
        raise ValueError(f"«{slug}»: pon al menos un ingrediente")
    if kind == "shapeless" and sum(1 for c in cells if c) > 9:
        raise ValueError(f"«{slug}»: demasiados ingredientes")
    out_r = {"id": slug, "type": kind, "grid": cells, "result": {"id": out, "count": count}}
    if kind in SINGLE_TYPES:
        try:
            xp = round(float(r.get("xp", 0) or 0), 2)
        except (TypeError, ValueError):
            raise ValueError(f"«{slug}»: experiencia no válida")
        if not 0 <= xp <= 100:
            raise ValueError(f"«{slug}»: la experiencia debe estar entre 0 y 100")
        out_r["xp"] = xp
    if kind in COOK_TYPES:
        try:
            raw = r.get("time")
            time = int(DEFAULT_TIME.get(kind, 200) if raw is None else raw)
        except (TypeError, ValueError):
            raise ValueError(f"«{slug}»: tiempo no válido")
        if not 1 <= time <= 6000:
            raise ValueError(f"«{slug}»: el tiempo debe estar entre 1 y 6000 ticks (5 min)")
        out_r["time"] = time
    return out_r


def clean_list(recipes):
    if not isinstance(recipes, list):
        raise ValueError("se esperaba una lista de recetas")
    seen, out = set(), []
    for r in recipes:
        c = clean_recipe(r)
        if c["id"] in seen:
            raise ValueError(f"hay dos recetas con el nombre «{c['id']}»")
        seen.add(c["id"])
        out.append(c)
    return out


def _shaped_pattern(grid):
    letters, keys, rows = {}, {}, []
    for r in range(3):
        row = ""
        for c in range(3):
            iid = grid[r * 3 + c]
            if iid is None:
                row += " "
            else:
                if iid not in letters:
                    letters[iid] = chr(ord("A") + len(letters))
                    keys[letters[iid]] = iid
                row += letters[iid]
        rows.append(row)
    used = [i for i, row in enumerate(rows) if row.strip()]
    top, bottom = used[0], used[-1]
    cols = [c for c in range(3) if any(rows[r][c] != " " for r in range(3))]
    left, right = cols[0], cols[-1]
    pattern = [rows[r][left:right + 1] for r in range(top, bottom + 1)]
    return pattern, {k: v for k, v in keys.items() if any(k in p for p in pattern)}


def build_script(recipes, removals=()):
    """Devuelve el JS del script generado. Una receta se añade solo si todos sus items existen en el servidor."""
    payload = []
    for r in recipes:
        ids = [c for c in r["grid"] if c] + [r["result"]["id"]]
        entry = {"id": r["id"], "type": r["type"], "ids": sorted(set(ids)), "result": r["result"]}
        if r["type"] == "shaped":
            pattern, keys = _shaped_pattern(r["grid"])
            entry.update(pattern=pattern, keys=keys)
        elif r["type"] == "shapeless":
            entry.update(ingredients=[c for c in r["grid"] if c])
        else:
            entry.update(input=r["grid"][0], xp=r.get("xp", 0), time=r.get("time", 200))
        payload.append(entry)
    data = json.dumps(payload, ensure_ascii=False, indent=1)
    quitar = json.dumps(list(removals), ensure_ascii=False, indent=1)
    return f"""// Generado por Modnex desde la interfaz de Recetas. No lo edites a mano: se reescribe al guardar.
// Se aplica con /reload. Si algún item de una receta no existe en el servidor, esa receta se salta y se avisa en el log.
const MODNEX_QUITAR = {quitar}
const MODNEX_RECETAS = {data}

ServerEvents.recipes(event => {{
  // Primero se quita y después se añade, para que las recetas nuevas no se vean afectadas.
  MODNEX_QUITAR.forEach(r => {{
    if (r.kind === 'output') {{
      if (Item.exists(r.value)) event.remove({{ output: r.value }})
      else console.warn(`[modnex] no se quitan recetas de ${{r.value}}: el item no existe`)
    }} else event.remove({{ id: r.value }})
  }})
  let added = 0
  MODNEX_RECETAS.forEach(r => {{
    const missing = r.ids.filter(id => !Item.exists(id))
    if (missing.length) {{
      console.warn(`[modnex] receta ${{r.id}} saltada: no existen ${{missing.join(', ')}}`)
      return
    }}
    const out = Item.of(r.result.id, r.result.count)
    const id = 'modnex:' + r.id
    if (r.type === 'shaped') event.shaped(out, r.pattern, r.keys).id(id)
    else if (r.type === 'shapeless') event.shapeless(out, r.ingredients).id(id)
    else if (r.type === 'campfire') event.campfireCooking(out, r.input, r.xp, r.time).id(id)
    else if (r.type === 'stonecutting') event.stonecutting(out, r.input).id(id)
    else if (r.type === 'smelting') event.smelting(out, r.input).xp(r.xp).cookingTime(r.time).id(id)
    else if (r.type === 'blasting') event.blasting(out, r.input).xp(r.xp).cookingTime(r.time).id(id)
    else event.smoking(out, r.input).xp(r.xp).cookingTime(r.time).id(id)
    added++
  }})
  console.info(`[modnex] ${{added}} de ${{MODNEX_RECETAS.length}} recetas añadidas`)
}})
"""


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _read_store(base):
    """Lee recetas y eliminaciones guardadas. Acepta el formato antiguo (una lista de recetas)."""
    src = base / "modnex" / "recetas.json"
    if not src.is_file():
        return [], []
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return clean_list(data), []
        return clean_list(data.get("recipes", [])), clean_removals(data.get("removals", []))
    except (ValueError, OSError, AttributeError):
        return [], []


def _store(ctx, name, recipes, removals):
    base = Path(ctx.server_path(name)) / "kubejs"
    if not base.is_dir():
        raise ValueError("este servidor no tiene carpeta kubejs (arráncalo una vez con KubeJS instalado)")
    _write(base / "modnex" / "recetas.json", json.dumps({"recipes": recipes, "removals": removals}, ensure_ascii=False, indent=2) + "\n")
    _write(base / "server_scripts" / "modnex_recetas.js", build_script(recipes, removals))


def load(ctx, name):
    base = Path(ctx.server_path(name)) / "kubejs"
    recipes, removals = _read_store(base)
    script = base / "server_scripts" / "modnex_recetas.js"
    return {"recipes": recipes, "removals": removals, "script": script.is_file(), "kubejs": base.is_dir(),
            "items": len(_index(ctx, name)[0]), "vanilla": vanilla_status(ctx, name)}


def save(ctx, name, recipes):
    recipes = clean_list(recipes)
    _, removals = _read_store(Path(ctx.server_path(name)) / "kubejs")
    _store(ctx, name, recipes, removals)
    return recipes


def save_removals(ctx, name, removals):
    removals = clean_removals(removals)
    recipes, _ = _read_store(Path(ctx.server_path(name)) / "kubejs")
    _store(ctx, name, recipes, removals)
    return removals


# ---------- scripts (editor de código) y diagnóstico ----------

KUBEJS_JAR = re.compile(r"kubejs-neoforge-.*\.jar")
SCRIPT_DIRS = ("startup_scripts", "server_scripts", "client_scripts")
SCRIPT_PATH = re.compile(r"(startup_scripts|server_scripts|client_scripts)/([a-z0-9_-]{1,60}/)?[a-z0-9_-]{1,60}\.js")
GENERATED = "server_scripts/modnex_recetas.js"
MAX_SCRIPT = 200_000


def installed(ctx, name):
    mods = _mods_dir(ctx, name)
    return mods.is_dir() and any(KUBEJS_JAR.fullmatch(j.name) for j in mods.iterdir())


def _kjs_base(ctx, name):
    if not installed(ctx, name):
        raise ValueError("KubeJS no está instalado en este servidor")
    return Path(ctx.server_path(name)) / "kubejs"


def _script_file(ctx, name, rel):
    if not isinstance(rel, str) or not SCRIPT_PATH.fullmatch(rel):
        raise ValueError("ruta de script no válida")
    base = _kjs_base(ctx, name).resolve()
    p = (base / rel).resolve()
    if base not in p.parents:
        raise ValueError("ruta de script no válida")
    return base, p


def scripts(ctx, name):
    base = _kjs_base(ctx, name)
    out = []
    for d in SCRIPT_DIRS:
        folder = base / d
        if not folder.is_dir():
            continue
        for f in sorted(folder.rglob("*.js")):
            rel = f.relative_to(base).as_posix()
            if SCRIPT_PATH.fullmatch(rel):
                out.append({"path": rel, "folder": d, "size": f.stat().st_size, "generated": rel == GENERATED})
    return out


def read_script(ctx, name, rel):
    _, p = _script_file(ctx, name, rel)
    if not p.is_file():
        raise ValueError("ese script no existe")
    return {"path": rel, "text": p.read_text(encoding="utf-8", errors="replace"), "generated": rel == GENERATED}


def save_script(ctx, name, rel, text, create=False):
    if rel == GENERATED:
        raise ValueError("este script lo genera el panel desde la pestaña Recetas; edítalo ahí")
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_SCRIPT:
        raise ValueError("el script está vacío o es demasiado grande")
    _, p = _script_file(ctx, name, rel)
    if create and p.exists():
        raise ValueError("ya existe un script con ese nombre")
    if not create and not p.is_file():
        raise ValueError("ese script no existe")
    _write(p, text)
    return {"path": rel}


def new_script_path(folder, filename):
    if folder not in SCRIPT_DIRS:
        raise ValueError("carpeta no válida")
    if not re.fullmatch(r"[a-z0-9_-]{1,60}\.js", filename or ""):
        raise ValueError("nombre no válido: minúsculas, números, _ o - y terminado en .js")
    return f"{folder}/{filename}"


def delete_script(ctx, name, rel):
    if rel == GENERATED:
        raise ValueError("este script lo genera el panel; no se borra a mano")
    _, p = _script_file(ctx, name, rel)
    if not p.is_file():
        raise ValueError("ese script no existe")
    p.unlink()


LOG_KJS = re.compile(r"\[kubejs|KubeJS|\[modnex\]", re.IGNORECASE)
LOG_LEVEL = re.compile(r"/(WARN|ERROR)\]")


def diagnostics(ctx, name):
    base = _kjs_base(ctx, name)
    jars = sorted(j.name for j in _mods_dir(ctx, name).glob("*.jar") if re.match(r"kubejs", j.name))
    counts = {d: len([f for f in (base / d).rglob("*.js")]) if (base / d).is_dir() else 0 for d in SCRIPT_DIRS}
    log = Path(ctx.server_path(name)) / "logs" / "latest.log"
    lines = []
    if log.is_file():
        with open(log, errors="replace") as fh:
            tail = collections.deque(fh, maxlen=6000)
        lines = [ln.rstrip() for ln in tail if LOG_KJS.search(ln) and LOG_LEVEL.search(ln)][-30:]
    return {"jars": jars, "counts": counts, "log": lines}


# ---------- vanilla: descarga del cliente (texturas) ----------

def _http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Modnex"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_vanilla(ctx, name):
    """Descarga el jar de cliente oficial de Mojang para la versión del servidor y lo guarda en la caché del gestor.
    Solo se lee para sacar texturas y modelos de los items de vanilla; no se modifica ni se redistribuye."""
    ver = _mc_version(ctx, name)
    dest = _client_cache(ctx, name)
    if not ver or not dest:
        raise ValueError("no sé qué versión de Minecraft usa este servidor (falta .manager.json)")
    if dest.is_file():
        return vanilla_status(ctx, name)
    try:
        manifest = _http_json(MOJANG_MANIFEST)
        entry = next((v for v in manifest["versions"] if v["id"] == ver), None)
        if not entry:
            raise ValueError(f"Mojang no publica la versión {ver}")
        client = _http_json(entry["url"])["downloads"]["client"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        h = hashlib.sha1()
        req = urllib.request.Request(client["url"], headers={"User-Agent": "Modnex"})
        with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as fh:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                h.update(chunk)
                fh.write(chunk)
        if h.hexdigest() != client["sha1"]:
            tmp.unlink(missing_ok=True)
            raise ValueError("la descarga no coincide con la huella que publica Mojang; no se ha guardado")
        os.replace(tmp, dest)
    except (OSError, KeyError, ValueError, urllib.error.URLError) as e:
        if isinstance(e, ValueError):
            raise
        raise ValueError(f"no se pudo descargar el cliente de Mojang: {e}")
    with _LOCK:
        _CACHE["sig"] = None   # fuerza a releer los jars con vanilla incluido
    return vanilla_status(ctx, name)


# ---------- quitar recetas ----------

REMOVAL_KINDS = ("output", "id")
RESULT_KEYS = ("result", "results", "output", "outputs")
PANEL_TYPE = {"shaped": "minecraft:crafting_shaped", "shapeless": "minecraft:crafting_shapeless", "smelting": "minecraft:smelting",
              "blasting": "minecraft:blasting", "smoking": "minecraft:smoking", "campfire": "minecraft:campfire_cooking",
              "stonecutting": "minecraft:stonecutting"}


def _ids_in(v, found):
    if isinstance(v, str):
        if ID_RE.fullmatch(v):
            found.append(v)
    elif isinstance(v, dict):
        for k in ("id", "item"):
            if isinstance(v.get(k), str) and ID_RE.fullmatch(v[k]):
                found.append(v[k])
        for k in ("result", "results", "output", "outputs", "items"):
            if k in v:
                _ids_in(v[k], found)
    elif isinstance(v, list):
        for x in v:
            _ids_in(x, found)


def _ingredient_ids(v, found):
    if isinstance(v, dict):
        for k, x in v.items():
            if k == "item" and isinstance(x, str):
                found.append(x)
            elif k == "tag" and isinstance(x, str):
                found.append("#" + x)
            else:
                _ingredient_ids(x, found)
    elif isinstance(v, list):
        for x in v:
            _ingredient_ids(x, found)


RECIPE_SKIN = {"minecraft:crafting_shaped": "crafting", "minecraft:crafting_shapeless": "crafting", "minecraft:smelting": "furnace",
               "minecraft:blasting": "blast_furnace", "minecraft:smoking": "smoker", "minecraft:campfire_cooking": "campfire",
               "minecraft:stonecutting": "stonecutter", "minecraft:smithing_transform": "smithing"}


def _pick_ingredient(v):
    """Un ingrediente de receta -> id de item, '#tag' o None. Si ofrece varias opciones se toma la primera."""
    if isinstance(v, str):
        return v if ID_RE.fullmatch(v) else None
    if isinstance(v, dict):
        if isinstance(v.get("item"), str):
            return v["item"]
        if isinstance(v.get("tag"), str):
            return "#" + v["tag"]
    if isinstance(v, list):
        for x in v:
            got = _pick_ingredient(x)
            if got:
                return got
    return None


def _result_of(data):
    r = data.get("result")
    if isinstance(r, str):
        return r, 1
    if isinstance(r, dict):
        rid = r.get("id") or r.get("item")
        if isinstance(rid, str):
            try:
                return rid, max(1, int(r.get("count", 1)))
            except (TypeError, ValueError):
                return rid, 1
    return None, 1


def _create_ing(v):
    """Ingrediente de una receta de Create -> {"k", "id", "amount"?}. Con varias opciones se toma la primera."""
    if isinstance(v, list):
        for x in v:
            got = _create_ing(x)
            if got:
                return got
        return None
    if not isinstance(v, dict):
        return None
    if v.get("type") == "neoforge:compound":        # varias opciones (compatibilidad con otros mods): se muestra la primera
        return _create_ing(v.get("ingredients"))
    if isinstance(v.get("item"), str):
        return {"k": "item", "id": v["item"]}
    if isinstance(v.get("fluids"), str):             # fluido con componentes (pociones): se muestra su fluido
        return {"k": "fluid", "id": v["fluids"], "amount": v["amount"] if isinstance(v.get("amount"), int) else 1000}
    if isinstance(v.get("tag"), str) and "amount" not in v:
        return {"k": "tag", "id": v["tag"]}          # un tag de items no lleva cantidad; el de fluidos sí
    amount = v.get("amount") if isinstance(v.get("amount"), int) else 1000
    if isinstance(v.get("fluid"), str):
        return {"k": "fluid", "id": v["fluid"], "amount": amount}
    if isinstance(v.get("tag"), str):
        return {"k": "fluid", "id": "#" + v["tag"], "amount": amount}
    return None


def _create_out(v):
    if not isinstance(v, dict) or not isinstance(v.get("id"), str):
        return None
    if isinstance(v.get("amount"), int):
        return {"k": "fluid", "id": v["id"], "amount": v["amount"]}
    out = {"k": "item", "id": v["id"], "count": v["count"] if isinstance(v.get("count"), int) else 1}
    if isinstance(v.get("chance"), (int, float)) and 0 < v["chance"] < 1:
        out["chance"] = round(float(v["chance"]), 4)
    return out


def create_layout(data):
    """Receta de Create -> forma normalizada (la misma que guarda el panel), o None si no se sabe dibujar."""
    kind = str(data.get("type", ""))[7:]
    if kind == "mechanical_crafting":
        pattern, key = data.get("pattern"), data.get("key")
        res = _create_out(data.get("result"))
        if not isinstance(pattern, list) or not isinstance(key, dict) or not res or not pattern or len(pattern) > 9:
            return None
        keys = {c: _create_ing(v) for c, v in key.items()}
        return {"skin": "create", "type": kind, "pattern": [str(p) for p in pattern], "key": {c: v for c, v in keys.items() if v}, "outs": [res]}
    if kind == "sequenced_assembly":
        ing, trans = _create_ing(data.get("ingredient")), (data.get("transitional_item") or {}).get("id")
        outs = []
        for r in data.get("results") or []:
            o = _create_out(r)
            if o:
                if o["k"] == "item" and isinstance(r.get("chance"), (int, float)):
                    o.pop("chance", None)
                    o["weight"] = r["chance"]      # aquí «chance» es un peso relativo, no una probabilidad
                outs.append(o)
        steps = []
        for st in data.get("sequence") or []:
            t = str(st.get("type", ""))[7:] if isinstance(st, dict) else ""
            if t not in kubejs_create.SEQ_STEPS:
                continue
            rest = [_create_ing(i) for i in (st.get("ingredients") or [])[1:]]
            step = {"t": t}
            if t == "deploying" and rest and rest[0]:
                step["held"] = rest[0]
            if t == "filling" and rest and rest[0]:
                step["fluid"] = rest[0]
            steps.append(step)
        if not ing or not outs:
            return None
        return {"skin": "create", "type": kind, "ins": [ing], "outs": outs, "transitional": trans, "loops": data.get("loops", 5), "steps": steps}
    if kind not in kubejs_create.TYPES:
        return None
    ins = [i for i in (_create_ing(x) for x in data.get("ingredients") or []) if i]
    outs = [o for o in (_create_out(x) for x in data.get("results") or []) if o]
    if not ins or not outs:
        return None
    lay = {"skin": "create", "type": kind, "ins": ins, "outs": outs}
    if isinstance(data.get("processing_time"), int):
        lay["time"] = data["processing_time"]
    if data.get("heat_requirement") in ("heated", "superheated"):
        lay["heat"] = data["heat_requirement"]
    if data.get("keep_held_item") is True:
        lay["keep"] = True
    return lay


def recipe_layout(data):
    """Dónde va cada ingrediente en la interfaz del juego: {"skin": ..., "slots": {hueco: {"id", "count"?}}} o None si no se sabe dibujar."""
    if not isinstance(data, dict):
        return None
    if str(data.get("type", "")).startswith("create:"):
        return create_layout(data)
    skin = RECIPE_SKIN.get(str(data.get("type", "")))
    rid, count = _result_of(data)
    if not skin or not rid:
        return None
    slots = {}
    kind = data["type"]
    if kind == "minecraft:crafting_shaped":
        pattern, key = data.get("pattern"), data.get("key")
        if not isinstance(pattern, list) or not isinstance(key, dict) or len(pattern) > 3:
            return None
        for r, row in enumerate(pattern):
            if not isinstance(row, str) or len(row) > 3:
                return None
            for c, ch in enumerate(row):
                got = _pick_ingredient(key.get(ch)) if ch != " " else None
                if got:
                    slots[f"g{r * 3 + c}"] = {"id": got}
    elif kind == "minecraft:crafting_shapeless":
        ings = data.get("ingredients")
        if not isinstance(ings, list) or len(ings) > 9:
            return None
        for i, ing in enumerate(ings):
            got = _pick_ingredient(ing)
            if got:
                slots[f"g{i}"] = {"id": got}
    elif kind == "minecraft:smithing_transform":
        for k in ("template", "base", "addition"):
            got = _pick_ingredient(data.get(k))
            if got:
                slots[k] = {"id": got}
        slots["result"] = {"id": rid, "count": count}
        return {"skin": skin, "slots": slots} if len(slots) > 1 else None
    else:   # horno, horno alto, ahumador, fogata y cortapiedras: un ingrediente
        got = _pick_ingredient(data.get("ingredient"))
        if got:
            slots["g0"] = {"id": got}
    if not any(k.startswith("g") for k in slots):
        return None
    slots["out"] = {"id": rid, "count": count}
    return {"skin": skin, "slots": slots}


def _recipes_index(ctx, name):
    """item de salida -> recetas (de vanilla y de los mods) que lo producen. Se calcula una vez por conjunto de jars."""
    _index(ctx, name)
    with _LOCK:
        if _CACHE["recipes"] is not None:
            return _CACHE["recipes"]
        refs = dict(_CACHE["recipe_refs"])
    by_item = {}
    for rid, ref in refs.items():
        raw = _read(ref)
        try:
            data = json.loads(raw.decode("utf-8", "replace")) if raw else None
        except ValueError:
            data = None
        if not isinstance(data, dict):
            continue
        outs = []
        for k in RESULT_KEYS:
            if k in data:
                _ids_in(data[k], outs)
        if not outs:
            continue
        ing = []
        _ingredient_ids({k: v for k, v in data.items() if k not in RESULT_KEYS}, ing)
        entry = {"id": rid, "type": str(data.get("type", "")), "ingredients": list(dict.fromkeys(ing))[:12], "layout": recipe_layout(data)}
        for o in set(outs):
            by_item.setdefault(o, []).append(entry)
    with _LOCK:
        _CACHE["recipes"] = by_item
    return by_item


def recipes_for(ctx, name, item):
    _check_id(item, "item")
    entries = _recipes_index(ctx, name).get(item, [])
    _, textures, models = _index(ctx, name)
    with _LOCK:
        names = _CACHE["names"]

    def ing(i):
        if i.startswith("#"):
            return {"id": i, "name": i, "icon": None, "tag": True}
        return {"id": i, "name": names.get(i, i), "icon": _cached_icon(textures, models, i), "tag": False}
    with _LOCK:
        fluid_names = dict(_CACHE["fluids"])

    def rich(e):
        if not isinstance(e, dict):
            return e
        e = dict(e)
        if e.get("k") == "fluid":
            e["name"] = fluid_names.get(e["id"], e["id"])
        elif e.get("k") in ("item", "tag"):
            e.update({kk: vv for kk, vv in ing(("#" if e["k"] == "tag" else "") + e["id"]).items() if kk != "id"})
        return e

    def lay_create(L):
        out = dict(L)
        for k in ("ins", "outs"):
            if k in out:
                out[k] = [rich(x) for x in out[k]]
        if "key" in out:
            out["key"] = {c: rich(v) for c, v in out["key"].items()}
        if isinstance(out.get("transitional"), str):
            out["transitional"] = rich({"k": "item", "id": out["transitional"]})
        if "steps" in out:
            out["steps"] = [{**st, **({"held": rich(st["held"])} if "held" in st else {}), **({"fluid": rich(st["fluid"])} if "fluid" in st else {})} for st in out["steps"]]
        return out

    def lay(layout):
        if not layout:
            return None
        if layout["skin"] == "create":
            return lay_create(layout)
        return {"skin": layout["skin"], "slots": {k: {**ing(v["id"]), **({"count": v["count"]} if v.get("count", 1) > 1 else {})} for k, v in layout["slots"].items()}}
    out = []
    # primero las que se agregaron desde el panel (viven en kubejs/modnex/recetas.json, no en los jars)
    mine, _ = _read_store(Path(ctx.server_path(name)) / "kubejs")
    for r in mine:
        if r["result"]["id"] != item:
            continue
        ings = list(dict.fromkeys(c for c in r["grid"] if c))
        slots = {f"g{i}": {"id": c} for i, c in enumerate(r["grid"]) if c}
        slots["out"] = {"id": r["result"]["id"], "count": r["result"]["count"]}
        skin = {"shaped": "crafting", "shapeless": "crafting", "smelting": "furnace", "blasting": "blast_furnace", "smoking": "smoker",
                "campfire": "campfire", "stonecutting": "stonecutter"}[r["type"]]
        out.append({"id": f"modnex:{r['id']}", "slug": r["id"], "source": "panel", "type": PANEL_TYPE.get(r["type"], r["type"]),
                    "ingredients": [ing(i) for i in ings], "layout": lay({"skin": skin, "slots": slots})})
    for r in kubejs_create.load(ctx, name)["recipes"]:
        if item in kubejs_create.output_ids(r):
            out.append({"id": f"modnex:create_{r['id']}", "slug": r["id"], "store": "create", "source": "panel", "type": "create:" + r["type"],
                        "ingredients": [ing(i) for i in kubejs_create.item_ids(r)], "layout": lay(kubejs_create.as_layout(r))})
    for e in sorted(entries, key=lambda x: x["id"])[:60]:
        out.append({"id": e["id"], "source": "pack", "type": e["type"], "ingredients": [ing(i) for i in e["ingredients"]], "layout": lay(e.get("layout"))})
    return {"item": item, "recipes": out}


def delete_recipe(ctx, name, slug):
    """Borra una receta agregada desde el panel (las eliminaciones guardadas se conservan)."""
    base = Path(ctx.server_path(name)) / "kubejs"
    recipes, removals = _read_store(base)
    kept = [r for r in recipes if r["id"] != slug]
    if len(kept) == len(recipes):
        raise ValueError("esa receta no existe en la lista del panel")
    _store(ctx, name, kept, removals)
    return kept


def clean_removal(r):
    if not isinstance(r, dict) or r.get("kind") not in REMOVAL_KINDS:
        raise ValueError("eliminación no válida")
    return {"kind": r["kind"], "value": _check_id(r.get("value"), "eliminación")}


def clean_removals(removals):
    if not isinstance(removals, list):
        raise ValueError("se esperaba una lista de eliminaciones")
    out, seen = [], set()
    for r in removals:
        c = clean_removal(r)
        key = (c["kind"], c["value"])
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out
