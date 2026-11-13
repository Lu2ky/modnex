"""KubeJS: modelos 3D de mobs de mods que usan modelos de datos (GeckoLib y Bedrock, archivos `.geo.json`).

Un `.geo.json` describe huesos con cubos, pivotes y giros, y sus coordenadas de textura. A diferencia de vanilla, ahí la forma sí está en
datos y se puede leer de cualquier mod. Lo que no está en datos es qué modelo y qué textura usa cada mob (eso lo decide el código del
mod), así que se empareja por el nombre: `zombie_clown` busca un modelo `zombieclown` y una textura con ese nombre. Si no hay pareja
clara no se dibuja nada y el mob se queda con su huevo de aparición. Los mods que dibujan sus mobs en código Java no se pueden leer.
"""
import json
import math
import re

from . import kubejs_mobs as M

MAX_BONES = 120
MAX_CUBES = 400
SUFFIXES = ("_not_despawn", "_stage_2", "_stage_3", "_copy", "_true_form", "_leader", "_2", "_3", "_head", "_clone")
SKIP_TEX_DIRS = ("block/", "item/", "particle/", "gui/", "mob_effect/", "screens/", "models/", "armor/")
# Los modelos de Bedrock miran hacia el mismo lado que los de Java una vez pasados a nuestro espacio (comprobado a ojo con modelos reales).
NEGATE_XY = True


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _variants(path):
    """El nombre del mob sin sufijos que solo distinguen variantes: `bonescaller_not_despawn` -> `bonescaller`."""
    out, cur = [path], path
    changed = True
    while changed:
        changed = False
        for suf in SUFFIXES:
            if cur.endswith(suf) and len(cur) > len(suf) + 2:
                cur = cur[: -len(suf)]; out.append(cur); changed = True
    return out


def _pick(key, table, min_len=5):
    """Entrada de `table` (clave normalizada -> id) que mejor encaja con `key`: igual, o una contiene a la otra (la más parecida en longitud)."""
    if key in table:
        return table[key]
    near = [k for k in table if len(k) >= min_len and (k.startswith(key) or key.startswith(k))]
    return table[min(near, key=lambda k: abs(len(k) - len(key)))] if near else None


def match(entity_id, geo_ids, texture_ids):
    """(id del modelo, id de la textura) que más se parecen al nombre del mob, o None si no hay una pareja clara."""
    ns, _, path = entity_id.partition(":")
    models = {}
    for g in geo_ids:
        gns, _, gp = g.partition(":")
        if gns == ns:
            name = _norm(gp.rsplit("/", 1)[-1])
            models.setdefault(name, g)
            models.setdefault(name.rstrip("0123456789"), g)           # boneimp2 -> boneimp
    tex = {}
    for t in texture_ids:
        tns, _, tp = t.partition(":")
        if tns != ns or any(tp.startswith(d) for d in SKIP_TEX_DIRS) or tp.endswith(("_e", "_glow", "_emissive", "_layer", "_overlay")):
            continue
        key = _norm(tp.rsplit("/", 1)[-1])
        if key not in tex or len(tp) < len(tex[key].partition(":")[2]):
            tex[key] = t
    for v in _variants(path.rsplit("/", 1)[-1]):
        k = _norm(v)
        g = _pick(k, models)
        t = _pick(_norm(g.partition(":")[2].rsplit("/", 1)[-1]), tex) if g else None
        t = t or _pick(k, tex)
        if g and t:
            return g, t
    return None


def png_size(raw):
    """(ancho, alto) de un PNG leyendo su cabecera, o None."""
    if len(raw) >= 24 and raw[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")
    return None


# ---------- geometría ----------
def _rot(p, r, pivot):
    """Gira el punto `p` alrededor de `pivot` (grados x, y, z; se aplica primero x, luego y y al final z)."""
    x, y, z = (p[i] - pivot[i] for i in range(3))
    rx, ry, rz = (math.radians(a) for a in r)
    if rx:
        c, s = math.cos(rx), math.sin(rx); y, z = y * c - z * s, y * s + z * c
    if ry:
        c, s = math.cos(ry), math.sin(ry); x, z = x * c + z * s, -x * s + z * c
    if rz:
        c, s = math.cos(rz), math.sin(rz); x, y = x * c - y * s, x * s + y * c
    return [x + pivot[0], y + pivot[1], z + pivot[2]]


def _vec(v, n=3, default=0.0):
    if isinstance(v, list) and len(v) == n and all(isinstance(a, (int, float)) for a in v):
        return [float(a) for a in v]
    return [default] * n


def _euler(r):
    r = _vec(r)
    return [-r[0], -r[1], r[2]] if NEGATE_XY else r


def _cube_faces(cube, mirror):
    """Caras de un cubo: [(cuatro puntos en espacio Bedrock, cuatro (u, v) en píxeles)]. Admite UV de caja o UV por cara.
    En Bedrock la caja se despliega como este-norte-oeste-sur (la de Java, derecha-frente-izquierda-espalda, es su espejo) y el frente
    del modelo es la cara norte (-z). Cada cara se ordena para que su normal mire hacia fuera."""
    ox, oy, oz = _vec(cube.get("origin")); w, h, d = _vec(cube.get("size"))
    g = float(cube["inflate"]) if isinstance(cube.get("inflate"), (int, float)) else 0.0
    x0, x1, y0, y1, z0, z1 = ox - g, ox + w + g, oy - g, oy + h + g, oz - g, oz + d + g
    W, H, D = x1 - x0, y1 - y0, z1 - z0
    # cara -> (punto en (s, t): s avanza con u y t con v)
    point = {
        "north": lambda s, t: (x1 - s * W, y1 - t * H, z0), "south": lambda s, t: (x0 + s * W, y1 - t * H, z1),
        "east": lambda s, t: (x1, y1 - t * H, z1 - s * D), "west": lambda s, t: (x0, y1 - t * H, z0 + s * D),
        "up": lambda s, t: (x1 - s * W, y1, z1 - t * D), "down": lambda s, t: (x1 - s * W, y0, z0 + t * D),
    }
    uv = cube.get("uv")
    regions = {}
    if isinstance(uv, list) and len(uv) == 2:
        u, v = _vec(uv, 2)
        east, west = (u + d + w, u) if mirror else (u, u + d + w)
        regions = {"north": (u + d, v + d, w, h), "east": (east, v + d, d, h), "south": (u + 2 * d + w, v + d, w, h), "west": (west, v + d, d, h),
                   "up": (u + d, v, w, d), "down": (u + d + w, v, w, d)}
    elif isinstance(uv, dict):
        for face in point:
            f = uv.get(face)
            if isinstance(f, dict) and isinstance(f.get("uv"), list) and len(f["uv"]) == 2:
                sz = _vec(f.get("uv_size"), 2, 0.0)
                regions[face] = (_vec(f["uv"], 2)[0], _vec(f["uv"], 2)[1], sz[0], sz[1])
    else:
        return []
    centre = ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
    out = []
    for face, (u0, v0, su, sv) in regions.items():
        pts = [list(point[face](s, t)) for s, t in M._SIDES]
        uvs = [(u0 + ((1 - s) if mirror and isinstance(uv, list) else s) * su, v0 + t * sv) for s, t in M._SIDES]
        if sum((sum(p[k] for p in pts) / 4 - centre[k]) * M._normal(pts)[k] for k in range(3)) < 0:
            pts, uvs = pts[::-1], uvs[::-1]                          # normal hacia dentro: se invierte el orden de los vértices
        out.append((pts, uvs))
    return out


def build(geo, tex_id, size=None):
    """Modelo de un `.geo.json` en el formato que dibuja el navegador, o None si no se entiende. `size` = (ancho, alto) de la textura."""
    try:
        data = geo["minecraft:geometry"][0] if "minecraft:geometry" in geo else None
        if data is None:                                         # formato antiguo: {"geometry.x": {...}}
            key = next(k for k in geo if k.startswith("geometry."))
            data = geo[key]
        desc = data.get("description") or {}
        tw = float(desc.get("texture_width") or data.get("texturewidth") or 64)
        th = float(desc.get("texture_height") or data.get("textureheight") or 64)
        bones = data["bones"]
    except (KeyError, StopIteration, TypeError, AttributeError, IndexError, ValueError):
        return None
    if not isinstance(bones, list) or not bones or len(bones) > MAX_BONES:
        return None
    if size and (abs(size[0] - tw) > 0.5 or abs(size[1] - th) > 0.5):
        tw, th = float(size[0]), float(size[1])                 # la textura manda: sus píxeles son los que se ven
    by = {b["name"]: b for b in bones if isinstance(b, dict) and isinstance(b.get("name"), str)}

    def chain(b):
        out, seen = [], set()
        while isinstance(b, dict) and b["name"] not in seen:
            seen.add(b["name"]); out.append(b); b = by.get(b.get("parent"))
        return out                                              # del hueso a la raíz

    quads, cubes = [], 0
    for bone in bones:
        if not isinstance(bone, dict) or not isinstance(bone.get("cubes"), list):
            continue
        parents = chain(bone)
        for cube in bone["cubes"]:
            cubes += 1
            if cubes > MAX_CUBES or not isinstance(cube, dict):
                return None if cubes > MAX_CUBES else None
            mirror = bool(cube.get("mirror", bone.get("mirror", False)))
            crot, cpivot = cube.get("rotation"), _vec(cube.get("pivot"))
            for pts, uvs in _cube_faces(cube, mirror):
                world = []
                for p in pts:
                    if crot:
                        p = _rot(p, _euler(crot), cpivot)
                    for b in parents:
                        r = b.get("rotation")
                        if r:
                            p = _rot(p, _euler(r), _vec(b.get("pivot")))
                    world.append([-p[0], p[1], -p[2]])         # giro de media vuelta: el frente (-z) pasa a mirar al visor, sin espejar
                quads.append({"t": tex_id, "p": world, "uv": [(a / tw * 16, b / th * 16) for a, b in uvs]})
    if not quads:
        return None
    return M.finish(quads, [tex_id], robust=True)
