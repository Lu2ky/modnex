"""KubeJS: reglas visuales (etiquetas, reemplazos, herrería, tooltips, propiedades, eventos y comandos).

Cada regla es un dato validado; el JS se genera siempre desde esos datos y nunca se interpola texto del usuario:
todo valor entra al script por json.dumps. Se escriben tres scripts propios, uno por lado, y se borran si queda vacío.
"""
import json
import os
import re
from pathlib import Path

ID_RE = re.compile(r"[a-z0-9_.-]+:[a-z0-9_./-]+")
TAG_RE = re.compile(r"[a-z0-9_.-]+:[a-z0-9_./-]+")
SLUG_RE = re.compile(r"[a-z0-9_]{1,40}")
CMD_NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,24}")
MAX_RULES = 300
MAX_ENTRIES = 200
MAX_TEXT = 200

REGISTRIES = ("item", "block", "fluid", "entity_type")
RARITIES = ("COMMON", "UNCOMMON", "RARE", "EPIC")
COLORS = {"gris": 0xAAAAAA, "blanco": 0xFFFFFF, "rojo": 0xFF5555, "dorado": 0xFFAA00, "amarillo": 0xFFFF55,
          "verde": 0x55FF55, "aqua": 0x55FFFF, "azul": 0x5555FF, "rosa": 0xFF55FF, "morado": 0xAA00AA}
WHEN = ("siempre", "shift", "sin_shift")
EVENTS = {
    "player_login": {"label": "Un jugador entra al servidor", "filter": False, "cancel": False},
    "block_broken": {"label": "Un jugador rompe un bloque", "filter": True, "cancel": True},
    "block_placed": {"label": "Un jugador coloca un bloque", "filter": True, "cancel": True},
    "item_right_click": {"label": "Un jugador usa un item (clic derecho)", "filter": True, "cancel": True},
}
ACTIONS = ("tell", "give", "command", "cancel")
PROFESSIONS = ("armorer", "butcher", "cartographer", "cleric", "farmer", "fisherman", "fletcher", "leatherworker",
               "librarian", "mason", "shepherd", "toolsmith", "weaponsmith")
SIDE = {"trade": "server", "trade_clear": "server", "tag": "server", "replace": "server", "smithing": "server", "event": "server", "command": "server",
        "tooltip": "client", "hide": "client", "item_prop": "startup"}
TYPE_NAME = {"tag": "Etiqueta", "replace": "Reemplazo", "smithing": "Herrería", "trade": "Comercio", "trade_clear": "Quitar comercios",
             "tooltip": "Tooltip", "hide": "Ocultar", "item_prop": "Propiedades", "event": "Evento", "command": "Comando"}
SCRIPT = {"server": "server_scripts/modnex_reglas.js", "client": "client_scripts/modnex_cliente.js",
          "startup": "startup_scripts/modnex_inicio.js"}


def _id(value, label):
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ValueError(f"{label}: id no válido")
    return value


def _entry(value, label):
    """Un item/bloque/fluido/entidad, o un tag con # delante."""
    if isinstance(value, str) and value.startswith("#"):
        if not TAG_RE.fullmatch(value[1:]):
            raise ValueError(f"{label}: tag no válido")
        return value
    return _id(value, label)


def _text(value, label, required=True):
    if not isinstance(value, str):
        raise ValueError(f"{label}: texto no válido")
    value = value.strip()
    if "\n" in value or "\r" in value or len(value) > MAX_TEXT:
        raise ValueError(f"{label}: una sola línea de hasta {MAX_TEXT} caracteres")
    if required and not value:
        raise ValueError(f"{label}: no puede estar vacío")
    return value


def _count(value, label, low=1, high=64):
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label}: número no válido")
    if not low <= n <= high:
        raise ValueError(f"{label}: entre {low} y {high}")
    return n


def _stack(v, label):
    if not isinstance(v, dict):
        raise ValueError(f"{label}: item no válido")
    return {"id": _id(v.get("id"), label), "count": _count(v.get("count", 1), f"{label}: cantidad")}


def _actions(raw, label, allow_cancel):
    if not isinstance(raw, list) or not 1 <= len(raw) <= 12:
        raise ValueError(f"{label}: añade entre 1 y 12 acciones")
    out, cancels = [], 0
    for a in raw:
        kind = a.get("do") if isinstance(a, dict) else None
        if kind not in ACTIONS:
            raise ValueError(f"{label}: acción no válida")
        if kind == "tell":
            out.append({"do": "tell", "text": _text(a.get("text"), f"{label}: mensaje")})
        elif kind == "give":
            out.append({"do": "give", "item": _id(a.get("item"), f"{label}: item"), "count": _count(a.get("count", 1), f"{label}: cantidad")})
        elif kind == "command":
            cmd = _text(a.get("cmd"), f"{label}: comando").lstrip("/").strip()
            if not cmd:
                raise ValueError(f"{label}: comando vacío")
            out.append({"do": "command", "cmd": cmd})
        else:
            if not allow_cancel:
                raise ValueError(f"{label}: este evento no se puede cancelar")
            cancels += 1
    if cancels > 1:
        raise ValueError(f"{label}: «cancelar» solo una vez")
    if cancels:
        out.append({"do": "cancel"})   # cancelar siempre al final
    return out


def clean_rule(r):
    """Valida una regla y devuelve su forma normalizada. Lanza ValueError con un mensaje legible."""
    if not isinstance(r, dict):
        raise ValueError("regla no válida")
    slug = str(r.get("id") or "")
    if not SLUG_RE.fullmatch(slug):
        raise ValueError(f"«{slug}»: el nombre solo puede tener minúsculas, números y _ (máx. 40)")
    kind = r.get("type")
    if kind not in SIDE:
        raise ValueError(f"«{slug}»: tipo de regla no válido")
    label = TYPE_NAME[kind]
    out = {"id": slug, "type": kind, "on": r.get("on") is not False}
    if kind == "tag":
        reg = r.get("registry")
        if reg not in REGISTRIES:
            raise ValueError(f"{label}: tipo de tag no válido")
        if not TAG_RE.fullmatch(str(r.get("tag") or "")):
            raise ValueError(f"{label}: nombre del tag no válido (ej. c:ingots/cobre)")
        if r.get("action") not in ("add", "remove"):
            raise ValueError(f"{label}: acción no válida")
        entries = r.get("entries")
        if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_ENTRIES:
            raise ValueError(f"{label}: añade entre 1 y {MAX_ENTRIES} elementos")
        out.update(registry=reg, tag=r["tag"], action=r["action"], entries=[_entry(e, label) for e in entries])
    elif kind == "replace":
        if r.get("mode") not in ("input", "output"):
            raise ValueError(f"{label}: modo no válido")
        out.update(mode=r["mode"], source=_id(r.get("source"), f"{label}: item a cambiar"), target=_entry(r.get("target"), f"{label}: item nuevo"))
        if r.get("source") == r.get("target"):
            raise ValueError(f"{label}: el item nuevo es igual al anterior")
        if r.get("only"):
            out["only"] = _id(r["only"], f"{label}: receta del item")
    elif kind == "smithing":
        out.update(result=_id(r.get("result"), f"{label}: resultado"), template=_id(r.get("template"), f"{label}: plantilla"),
                   base=_id(r.get("base"), f"{label}: base"), addition=_id(r.get("addition"), f"{label}: material"))
    elif kind == "trade":
        if r.get("profession") not in PROFESSIONS:
            raise ValueError(f"{label}: profesión no válida")
        ins = r.get("inputs")
        if not isinstance(ins, list) or not 1 <= len(ins) <= 2:
            raise ValueError(f"{label}: el aldeano pide 1 o 2 items")
        out.update(profession=r["profession"], level=_count(r.get("level", 1), f"{label}: nivel", 1, 5),
                   inputs=[_stack(i, f"{label}: pago") for i in ins], output=_stack(r.get("output"), f"{label}: venta"),
                   max_uses=_count(r.get("max_uses", 12), f"{label}: usos", 1, 9999),
                   xp=_count(r.get("xp", 5), f"{label}: experiencia", 0, 100))
    elif kind == "trade_clear":
        if r.get("which") not in ("vanilla", "modded"):
            raise ValueError(f"{label}: elige qué comercios quitar")
        out["which"] = r["which"]
    elif kind == "tooltip":
        lines = r.get("lines")
        if not isinstance(lines, list) or not 1 <= len(lines) <= 8:
            raise ValueError(f"{label}: añade entre 1 y 8 líneas")
        if r.get("color") not in COLORS or r.get("when", "siempre") not in WHEN:
            raise ValueError(f"{label}: color o condición no válidos")
        out.update(item=_entry(r.get("item"), f"{label}: item"), lines=[_text(x, f"{label}: línea") for x in lines],
                   color=r["color"], when=r.get("when", "siempre"))
    elif kind == "hide":
        items = r.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_ENTRIES:
            raise ValueError(f"{label}: añade entre 1 y {MAX_ENTRIES} items")
        out["items"] = [_id(i, label) for i in items]
    elif kind == "item_prop":
        props = {}
        if r.get("stack") not in (None, ""):
            props["stack"] = _count(r["stack"], f"{label}: tamaño de pila", 1, 99)
        if r.get("rarity") not in (None, ""):
            if r["rarity"] not in RARITIES:
                raise ValueError(f"{label}: rareza no válida")
            props["rarity"] = r["rarity"]
        if r.get("fire_resistant") is True:
            props["fire_resistant"] = True
        if r.get("burn_time") not in (None, ""):
            props["burn_time"] = _count(r["burn_time"], f"{label}: tiempo de combustión", 0, 1_000_000)
        if r.get("max_damage") not in (None, ""):
            props["max_damage"] = _count(r["max_damage"], f"{label}: durabilidad", 1, 100_000)
        if not props:
            raise ValueError(f"{label}: cambia al menos una propiedad")
        out.update(item=_id(r.get("item"), f"{label}: item"), **props)
    elif kind == "event":
        ev = r.get("event")
        if ev not in EVENTS:
            raise ValueError(f"{label}: evento no válido")
        out["event"] = ev
        if EVENTS[ev]["filter"]:
            out["filter"] = _id(r.get("filter"), f"{label}: bloque o item")
        out["actions"] = _actions(r.get("actions"), label, EVENTS[ev]["cancel"])
    else:  # command
        name = str(r.get("name") or "")
        if not CMD_NAME_RE.fullmatch(name):
            raise ValueError(f"{label}: el comando solo puede tener minúsculas, números y _ (máx. 25)")
        out.update(name=name, level=_count(r.get("level", 2), f"{label}: nivel de permiso", 0, 4),
                   actions=_actions(r.get("actions"), label, False))
    return out


def clean_rules(rules):
    if not isinstance(rules, list):
        raise ValueError("lista de reglas no válida")
    if len(rules) > MAX_RULES:
        raise ValueError(f"demasiadas reglas (máx. {MAX_RULES})")
    out, seen = [], set()
    for r in rules:
        c = clean_rule(r)
        if c["id"] in seen:
            raise ValueError(f"«{c['id']}»: nombre repetido")
        seen.add(c["id"])
        out.append(c)
    return out


# ---------- generación de JS ----------
def _j(value):
    return json.dumps(value, ensure_ascii=False)


def _action_js(a, ev):
    """Una acción como una línea de JS. `ev` es la variable del evento o del contexto de comando."""
    if a["do"] == "tell":
        return f"if ({ev}.player) {ev}.player.tell({_j(a['text'])})"
    if a["do"] == "give":
        return f"if ({ev}.player) {ev}.player.give(Item.of({_j(a['item'])}, {a['count']}))"
    if a["do"] == "command":
        return f"{ev}.server.runCommandSilent({_j(a['cmd'])})"
    return f"{ev}.cancel()"


def _server_js(rules):
    parts = []
    tags = [r for r in rules if r["type"] == "tag"]
    for reg in REGISTRIES:
        mine = [r for r in tags if r["registry"] == reg]
        if not mine:
            continue
        body = "\n".join(f"  event.{r['action']}({_j(r['tag'])}, {_j(r['entries'])})" for r in mine)
        parts.append(f"ServerEvents.tags({_j(reg)}, event => {{\n{body}\n}})")
    trades = [f"  event.removeVanillaTrades()" if r["which"] == "vanilla" else "  event.removeModdedTrades()"
              for r in rules if r["type"] == "trade_clear"]
    for r in rules:
        if r["type"] == "trade":
            def st(x):
                return _j(f"{x['count']}x {x['id']}" if x["count"] > 1 else x["id"])
            ins = "[" + ", ".join(st(i) for i in r["inputs"]) + "]"
            trades.append(f"  event.addTrade({_j(r['profession'])}, {r['level']}, {ins}, {st(r['output'])})"
                          f".maxUses({r['max_uses']}).villagerExperience({r['xp']})")
    if trades:
        parts.append("// Requiere el mod MoreJS\nMoreJSEvents.villagerTrades(event => {\n" + "\n".join(trades) + "\n})")
    recipes = []
    for r in rules:
        if r["type"] == "replace":
            flt = {"input" if r["mode"] == "input" else "output": r["source"]}
            if r.get("only"):
                flt["output"] = r["only"]
            fn = "replaceInput" if r["mode"] == "input" else "replaceOutput"
            target = f"Ingredient.of({_j(r['target'])})" if r["mode"] == "input" and r["target"].startswith("#") else _j(r["target"])
            recipes.append(f"  event.{fn}({_j(flt)}, {_j(r['source'])}, {target})")
        elif r["type"] == "smithing":
            recipes.append(f"  event.smithing({_j(r['result'])}, {_j(r['template'])}, {_j(r['base'])}, {_j(r['addition'])}).id({_j('modnex:' + r['id'])})")
    if recipes:
        parts.append("ServerEvents.recipes(event => {\n" + "\n".join(recipes) + "\n})")
    for r in rules:
        if r["type"] == "event":
            body = "\n".join("  " + _action_js(a, "event") for a in r["actions"])
            if r["event"] == "player_login":
                head = "PlayerEvents.loggedIn(event => {"
            else:
                fn = {"block_broken": "BlockEvents.broken", "block_placed": "BlockEvents.placed", "item_right_click": "ItemEvents.rightClicked"}[r["event"]]
                head = f"{fn}({_j(r['filter'])}, event => {{"
            parts.append(f"// {r['id']}\n{head}\n{body}\n}})")
    cmds = [r for r in rules if r["type"] == "command"]
    if cmds:
        regs = []
        for r in cmds:
            body = "\n".join("      " + _action_js(a, "ctx.source") for a in r["actions"])
            regs.append(f"  event.register(Commands.literal({_j(r['name'])})\n    .requires(source => source.hasPermission({r['level']}))\n"
                        f"    .executes(ctx => {{\n{body}\n      return 1\n    }}))")
        parts.append("ServerEvents.commandRegistry(event => {\n  const { commands: Commands } = event\n" + "\n".join(regs) + "\n})")
    return parts


def _client_js(rules):
    parts = []
    tips = [r for r in rules if r["type"] == "tooltip"]
    if tips:
        lines = []
        for r in tips:
            texts = ", ".join(f"Text.of({_j(x)}).color({COLORS[r['color']]})" for x in r["lines"])
            req = {"shift": "{ shift: true }, ", "sin_shift": "{ shift: false }, "}.get(r["when"], "")
            lines.append(f"  event.add({_j(r['item'])}, {req}[{texts}])")
        parts.append("ItemEvents.modifyTooltips(event => {\n" + "\n".join(lines) + "\n})")
    hidden = sorted({i for r in rules if r["type"] == "hide" for i in r["items"]})
    if hidden:
        parts.append(f"RecipeViewerEvents.removeEntries('item', event => {{\n  {_j(hidden)}.forEach(id => event.remove(id))\n}})")
    return parts


def _startup_js(rules):
    mods = []
    for r in rules:
        if r["type"] != "item_prop":
            continue
        sets = []
        if "stack" in r:
            sets.append(f"    item.maxStackSize = {r['stack']}")
        if "rarity" in r:
            sets.append(f"    item.rarity = {_j(r['rarity'])}")
        if r.get("fire_resistant"):
            sets.append("    item.fireResistant = true")
        if "burn_time" in r:
            sets.append(f"    item.burnTime = {r['burn_time']}")
        if "max_damage" in r:
            sets.append(f"    item.maxDamage = {r['max_damage']}")
        mods.append(f"  event.modify({_j(r['item'])}, item => {{\n" + "\n".join(sets) + "\n  })")
    return ["ItemEvents.modification(event => {\n" + "\n".join(mods) + "\n})"] if mods else []


def build_scripts(rules):
    """{lado: texto JS o None}. Solo cuentan las reglas activas."""
    live = [r for r in rules if r.get("on", True)]
    head = ("// Generado por Modnex desde la sección Reglas. No lo edites a mano: se reescribe al guardar.\n"
            "// %s\n\n")
    note = {"server": "Se aplica con /reload.", "client": "Corre en el cliente de cada jugador.", "startup": "Hace falta reiniciar el servidor."}
    out = {}
    for side, fn in (("server", _server_js), ("client", _client_js), ("startup", _startup_js)):
        parts = fn([r for r in live if SIDE[r["type"]] == side])
        out[side] = (head % note[side]) + "\n\n".join(parts) + "\n" if parts else None
    return out


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
    src = Path(ctx.server_path(name)) / "kubejs" / "modnex" / "reglas.json"
    try:
        rules = clean_rules(json.loads(src.read_text(encoding="utf-8")).get("rules", [])) if src.is_file() else []
    except (ValueError, OSError, AttributeError):
        rules = []
    return {"rules": rules, "types": schema()}


def save(ctx, name, rules):
    rules = clean_rules(rules)
    base = _base(ctx, name)
    _write(base / "modnex" / "reglas.json", json.dumps({"rules": rules}, ensure_ascii=False, indent=2) + "\n")
    for side, text in build_scripts(rules).items():
        target = base / SCRIPT[side]
        if text is None:
            if target.is_file():
                target.unlink()
        else:
            _write(target, text)
    return rules


def schema():
    """Datos de apoyo para que la interfaz pinte los formularios sin repetir listas."""
    return {"professions": list(PROFESSIONS), "registries": list(REGISTRIES), "rarities": list(RARITIES), "colors": list(COLORS), "when": list(WHEN),
            "events": {k: {"label": v["label"], "filter": v["filter"], "cancel": v["cancel"]} for k, v in EVENTS.items()},
            "side": SIDE}
