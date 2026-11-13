"""KubeJS: modelos 3D de mobs de vanilla.

En Minecraft el cuerpo de un mob no es un modelo JSON como el de un bloque: está escrito en código (cubos con su desplazamiento
en la textura). Aquí se reescriben esos cubos para los mobs más comunes y se convierten en caras con coordenadas de textura,
que el navegador pinta con el mismo WebGL de los bloques. La textura se lee del cliente de Minecraft que ya está en caché;
no se guarda nada en el repositorio. Los mobs que no están aquí siguen mostrándose con su huevo de aparición."""
import math

# Cada pieza: caja (x, y, z, ancho, alto, fondo) en píxeles del modelo (y hacia abajo, el frente mira a -z), desplazamiento en la
# textura, punto de giro `p`, giro `r` en grados (x, y, z), `m` (espejada) y `g` (hinchazón, para las capas de encima).
def _humanoid(left_arm_uv, left_leg_uv, arm=4, arm_rot=0.0, leg=4):
    ax = -3 if arm == 4 else -1
    lx = -1 if arm == 4 else -1
    mirror = left_arm_uv is None
    return [
        {"b": (-4, -8, -4, 8, 8, 8), "uv": (0, 0)},
        {"b": (-4, 0, -2, 8, 12, 4), "uv": (16, 16)},
        {"b": (ax, -2, -2, arm, 12, arm), "uv": (40, 16), "p": (-5, 2, 0), "r": (arm_rot, 0, 0)},
        {"b": (lx, -2, -2, arm, 12, arm), "uv": left_arm_uv or (40, 16), "p": (5, 2, 0), "r": (arm_rot, 0, 0), "m": mirror},
        {"b": (-1 if leg == 2 else -2, 0, -2, leg, 12, leg), "uv": (0, 16), "p": (-1.9 if leg == 4 else -2, 12, 0)},
        {"b": (-1 if leg == 2 else -2, 0, -2, leg, 12, leg), "uv": left_leg_uv or (0, 16), "p": (1.9 if leg == 4 else 2, 12, 0), "m": left_leg_uv is None},
    ]


ZOMBIE = _humanoid((32, 48), (16, 48), arm_rot=-90)
SKELETON = _humanoid(None, None, arm=2, leg=2)


def _spider():
    parts = [
        {"b": (-4, -4, -8, 8, 8, 8), "uv": (32, 4), "p": (0, 15, -3)},
        {"b": (-3, -3, -3, 6, 6, 6), "uv": (0, 0), "p": (0, 15, 0)},
        {"b": (-5, -4, -6, 10, 8, 12), "uv": (0, 12), "p": (0, 15, 9)},
    ]
    f, f2 = math.degrees(math.pi / 4), math.degrees(math.pi / 8)
    legs = [(2, 2 * f2, -f), (1, f2, -f * 0.74), (0, -f2, -f * 0.74), (-1, -2 * f2, -f)]
    for z, yaw, roll in legs:
        parts.append({"b": (-15, -1, -1, 16, 2, 2), "uv": (18, 0), "p": (-4, 15, z), "r": (0, yaw, roll)})
        parts.append({"b": (-1, -1, -1, 16, 2, 2), "uv": (18, 0), "p": (4, 15, z), "r": (0, -yaw, -roll)})
    return parts


def _ghast():
    parts = [{"b": (-8, -8, -8, 16, 16, 16), "uv": (0, 0), "p": (0, 17, 0)}]
    for i in range(9):
        x = ((i % 3) - 1) * 5.0
        z = ((i // 3) - 1) * 5.0
        parts.append({"b": (-1, 0, -1, 2, 8 + (i * 5) % 5, 2), "uv": (0, 0), "p": (x, 24.6, z)})
    return parts


def _quad(legs_y, leg_h, front_z, back_z, x, uv=(0, 16), size=4):
    return [{"b": (-2, 0, -2, size, leg_h, 4), "uv": uv, "p": (sx * x, legs_y, z)} for sx in (-1, 1) for z in (back_z, front_z)]


_PIG = [
    {"b": (-4, -4, -8, 8, 8, 8), "uv": (0, 0), "p": (0, 12, -6)},
    {"b": (-2, 0, -9, 4, 3, 1), "uv": (16, 16), "p": (0, 12, -6)},
    {"b": (-5, -10, -7, 10, 16, 8), "uv": (28, 8), "p": (0, 11, 2), "r": (90, 0, 0)},
] + _quad(18, 6, -5, 7, 3)

_COW = [
    {"b": (-4, -4, -6, 8, 8, 6), "uv": (0, 0), "p": (0, 4, -8)},
    {"b": (-5, -5, -5, 1, 3, 1), "uv": (22, 0), "p": (0, 4, -8)},
    {"b": (4, -5, -5, 1, 3, 1), "uv": (22, 0), "p": (0, 4, -8)},
    {"b": (-6, -10, -7, 12, 18, 10), "uv": (18, 4), "p": (0, 5, 2), "r": (90, 0, 0)},
    {"b": (-2, 2, -8, 4, 6, 1), "uv": (52, 0), "p": (0, 5, 2), "r": (90, 0, 0)},
] + _quad(12, 12, -6, 7, 4)

_SHEEP = [
    {"b": (-3, -4, -6, 6, 6, 8), "uv": (0, 0), "p": (0, 6, -8)},
    {"b": (-4, -10, -7, 8, 16, 6), "uv": (28, 8), "p": (0, 5, 2), "r": (90, 0, 0)},
] + _quad(12, 12, -5, 7, 3)

_SHEEP_FUR = [
    {"b": (-3, -4, -4, 6, 6, 6), "uv": (0, 0), "p": (0, 6, -8), "g": 0.6},
    {"b": (-4, -10, -7, 8, 16, 6), "uv": (28, 8), "p": (0, 5, 2), "r": (90, 0, 0), "g": 1.75},
] + [dict(p, g=0.5) for p in _quad(12, 6, -5, 7, 3)]

_CHICKEN = [
    {"b": (-2, -6, -2, 4, 6, 3), "uv": (0, 0), "p": (0, 15, -4)},
    {"b": (-2, -4, -4, 4, 2, 2), "uv": (14, 0), "p": (0, 15, -4)},
    {"b": (-1, -2, -3, 2, 2, 2), "uv": (14, 4), "p": (0, 15, -4)},
    {"b": (-3, -4, -3, 6, 8, 6), "uv": (0, 9), "p": (0, 16, 0), "r": (90, 0, 0)},
    {"b": (-1, 0, -3, 3, 5, 3), "uv": (26, 0), "p": (-2, 19, 1)},
    {"b": (-1, 0, -3, 3, 5, 3), "uv": (26, 0), "p": (1, 19, 1)},
    {"b": (0, 0, -3, 1, 4, 6), "uv": (24, 13), "p": (-4, 13, 0)},
    {"b": (-1, 0, -3, 1, 4, 6), "uv": (24, 13), "p": (4, 13, 0)},
]

# id del mob -> { textura, tamaño de la textura, piezas, capas encima [(textura, piezas)], escala }
_E = "minecraft:entity/"
MOBS = {
    "minecraft:zombie": {"tex": _E + "zombie/zombie", "size": (64, 64), "parts": ZOMBIE},
    "minecraft:husk": {"tex": _E + "zombie/husk", "size": (64, 64), "parts": ZOMBIE, "scale": 1.0625},
    "minecraft:drowned": {"tex": _E + "zombie/drowned", "size": (64, 64), "parts": ZOMBIE,
                          "layers": [(_E + "zombie/drowned_outer_layer", ZOMBIE, 0.25)]},
    "minecraft:skeleton": {"tex": _E + "skeleton/skeleton", "size": (64, 32), "parts": SKELETON},
    "minecraft:stray": {"tex": _E + "skeleton/stray", "size": (64, 32), "parts": SKELETON,
                        "layers": [(_E + "skeleton/stray_overlay", SKELETON, 0.25)]},
    "minecraft:wither_skeleton": {"tex": _E + "skeleton/wither_skeleton", "size": (64, 32), "parts": SKELETON, "scale": 1.2},
    "minecraft:creeper": {"tex": _E + "creeper/creeper", "size": (64, 32), "parts": [
        {"b": (-4, -8, -4, 8, 8, 8), "uv": (0, 0), "p": (0, 6, 0)},
        {"b": (-4, 0, -2, 8, 12, 4), "uv": (16, 16), "p": (0, 6, 0)},
    ] + _quad(18, 6, -4, 4, 2)},
    "minecraft:pig": {"tex": _E + "pig/pig", "size": (64, 32), "parts": _PIG},
    "minecraft:cow": {"tex": _E + "cow/cow", "size": (64, 32), "parts": _COW},
    "minecraft:mooshroom": {"tex": _E + "cow/red_mooshroom", "size": (64, 32), "parts": _COW},
    "minecraft:sheep": {"tex": _E + "sheep/sheep", "size": (64, 32), "parts": _SHEEP, "layers": [(_E + "sheep/sheep_fur", _SHEEP_FUR, 0)]},
    "minecraft:chicken": {"tex": _E + "chicken", "size": (64, 32), "parts": _CHICKEN},
    "minecraft:spider": {"tex": _E + "spider/spider", "size": (64, 32), "parts": _spider()},
    "minecraft:cave_spider": {"tex": _E + "spider/cave_spider", "size": (64, 32), "parts": _spider(), "scale": 0.7},
    "minecraft:ghast": {"tex": _E + "ghast/ghast", "size": (64, 32), "parts": _ghast()},
}
_ENDERMAN = [
    {"b": (-4, -8, -4, 8, 8, 8), "uv": (0, 0), "p": (0, -14, 0)},
    {"b": (-4, 0, -2, 8, 12, 4), "uv": (32, 16), "p": (0, -14, 0)},
    {"b": (-1, -2, -1, 2, 30, 2), "uv": (56, 0), "p": (-5, -12, 0)},
    {"b": (-1, -2, -1, 2, 30, 2), "uv": (56, 0), "p": (5, -12, 0), "m": True},
    {"b": (-1, 0, -1, 2, 30, 2), "uv": (56, 0), "p": (-2, -5, 0)},
    {"b": (-1, 0, -1, 2, 30, 2), "uv": (56, 0), "p": (2, -5, 0), "m": True},
]
# Aldeano: cabeza con nariz, túnica larga y los brazos cruzados.
_VILLAGER = [
    {"b": (-4, -10, -4, 8, 10, 8), "uv": (0, 0)},
    {"b": (-1, -1, -6, 2, 4, 2), "uv": (24, 0), "p": (0, -2, 0)},
    {"b": (-4, 0, -3, 8, 12, 6), "uv": (16, 20)},
    {"b": (-4, 0, -3, 8, 18, 6), "uv": (0, 38), "g": 0.5},
    {"b": (-8, -2, -2, 4, 8, 4), "uv": (44, 22), "p": (0, 3, -1), "r": (-43, 0, 0)},
    {"b": (4, -2, -2, 4, 8, 4), "uv": (44, 22), "p": (0, 3, -1), "r": (-43, 0, 0), "m": True},
    {"b": (-4, 2, -2, 8, 4, 4), "uv": (40, 38), "p": (0, 3, -1), "r": (-43, 0, 0)},
    {"b": (-2, 0, -2, 4, 12, 4), "uv": (0, 22), "p": (-2, 12, 0)},
    {"b": (-2, 0, -2, 4, 12, 4), "uv": (0, 22), "p": (2, 12, 0), "m": True},
]
MOBS["minecraft:enderman"] = {"tex": _E + "enderman/enderman", "size": (64, 32), "parts": _ENDERMAN}
MOBS["minecraft:villager"] = {"tex": _E + "villager/villager", "size": (64, 64), "parts": _VILLAGER}
MOBS["minecraft:wandering_trader"] = {"tex": _E + "wandering_trader", "size": (64, 64), "parts": _VILLAGER}
# El cofre se dibuja con el mismo sistema (su modelo también está en código): tapa, base y cerradura, mirando al frente.
def _chest(tex):
    return {"tex": _E + tex, "size": (64, 64), "parts": [
        {"b": (0, 0, 0, 14, 10, 14), "uv": (0, 19), "p": (1, 9, 1)},
        {"b": (0, -5, 0, 14, 5, 14), "uv": (0, 0), "p": (1, 9, 1)},
        {"b": (7, -2, -1, 2, 4, 1), "uv": (0, 0), "p": (1, 9, 1)},
    ]}


MOBS["minecraft:chest"] = _chest("chest/normal")
MOBS["minecraft:trapped_chest"] = _chest("chest/trapped")
MOBS["minecraft:ender_chest"] = _chest("chest/ender")
# Vista de inventario de un mob: de frente, algo girado y desde arriba.
DISPLAY = {"rotation": [18.0, -32.0, 0.0], "translation": [0.0, 0.0, 0.0], "scale": [0.85, 0.85, 0.85]}
_SIDES = ((0, 0), (1, 0), (1, 1), (0, 1))


def _rotate(p, r):
    x, y, z = p
    rx, ry, rz = (math.radians(a) for a in r)
    if rx:
        c, s = math.cos(rx), math.sin(rx)
        y, z = y * c - z * s, y * s + z * c
    if ry:
        c, s = math.cos(ry), math.sin(ry)
        x, z = x * c + z * s, -x * s + z * c
    if rz:
        c, s = math.cos(rz), math.sin(rz)
        x, y = x * c - y * s, x * s + y * c
    return x, y, z


def _faces(part):
    """Las seis caras de una pieza: [(cuatro puntos en el espacio del modelo, cuatro (u, v) en píxeles de textura)]."""
    ox, oy, oz, w, h, d = part["b"]
    u, v = part["uv"]
    g, mirror = part.get("g", 0.0), bool(part.get("m"))
    x0, x1, y0, y1, z0, z1 = ox - g, ox + w + g, oy - g, oy + h + g, oz - g, oz + d + g
    X, Y, Z = (lambda s: x0 + s * (x1 - x0)), (lambda t: y0 + t * (y1 - y0)), (lambda s: z0 + s * (z1 - z0))
    right, left = (u + d + w, u) if mirror else (u, u + d + w)
    layout = [
        (u + d, v + d, w, h, lambda s, t: (X(s), Y(t), z0)),                 # frente (-z)
        (u + 2 * d + w, v + d, w, h, lambda s, t: (X(1 - s), Y(t), z1)),     # espalda
        (right, v + d, d, h, lambda s, t: (x0, Y(t), Z(1 - s))),             # lado -x
        (left, v + d, d, h, lambda s, t: (x1, Y(t), Z(s))),                  # lado +x
        (u + d, v, w, d, lambda s, t: (X(s), y0, Z(1 - t))),                 # arriba
        (u + d + w, v, w, d, lambda s, t: (X(s), y1, Z(t))),                 # abajo
    ]
    out = []
    for u0, v0, su, sv, fn in layout:
        pts = [fn(s, t) for s, t in _SIDES]
        uvs = [(u0 + ((1 - s) if mirror else s) * su, v0 + t * sv) for s, t in _SIDES]
        out.append((pts, uvs))
    return out


def _normal(pts):
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = pts[0], pts[1], pts[2]
    ux, uy, uz, vx, vy, vz = bx - ax, by - ay, bz - az, cx - bx, cy - by, cz - bz
    n = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
    m = math.sqrt(sum(c * c for c in n)) or 1.0
    return [-c / m for c in n]            # los puntos van en sentido (izq-arriba, der-arriba, der-abajo): el producto apunta hacia dentro


def build(entity_id, textures):
    """Modelo de un mob listo para el navegador: caras con puntos y coordenadas de textura normalizadas, o None si no hay uno
    para ese mob o falta su textura. `textures` es el conjunto de ids de textura disponibles."""
    spec = MOBS.get(entity_id)
    if not spec or spec["tex"] not in textures:
        return None
    W, H = spec["size"]
    scale = spec.get("scale", 1.0)
    passes = [(spec["tex"], spec["parts"], 0.0)] + [layer for layer in spec.get("layers", []) if layer[0] in textures]
    quads = []
    for tex, parts, grow in passes:
        for part in parts:
            part = dict(part, g=part.get("g", grow))
            px, py, pz = part.get("p", (0, 0, 0))
            rot = part.get("r", (0, 0, 0))
            for pts, uvs in _faces(part):
                world = []
                for q in pts:
                    x, y, z = _rotate(q, rot)
                    x, y, z = x + px, y + py, z + pz
                    x, y, z = x * scale, 24 + (y - 24) * scale, z * scale
                    world.append((x, 24 - y, -z))                     # y hacia arriba y el frente hacia +z, sin espejar
                quads.append({"t": tex, "p": world, "uv": [(a / W * 16, b / H * 16) for a, b in uvs]})
    return finish(quads, list(dict.fromkeys(q["t"] for q in quads)))


def finish(quads, textures, robust=False):
    """Encaja las caras en el cubo de 16 de un bloque, apoyadas en el suelo y centradas, y calcula las normales.
    `robust`: ignora el 2 % de puntos más alejados al calcular la escala (modelos con huesos de efectos muy lejos del cuerpo)."""
    xs, ys, zs = ([q["p"][i][k] for q in quads for i in range(4)] for k in range(3))
    span = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs), 1e-6)
    if robust and len(xs) >= 50:
        cut = lambda v: sorted(v)[int(len(v) * 0.98)] - sorted(v)[int(len(v) * 0.02)]
        span = max(span * 0.45, max(cut(xs), cut(ys), cut(zs)))
    f = 14.0 / span
    cx, cz, y0 = (max(xs) + min(xs)) / 2, (max(zs) + min(zs)) / 2, min(ys)
    for q in quads:
        q["p"] = [[round((x - cx) * f + 8, 3), round((y - y0) * f + 1, 3), round((z - cz) * f + 8, 3)] for x, y, z in q["p"]]
        q["uv"] = [[round(a, 4), round(b, 4)] for a, b in q["uv"]]
        q["n"] = [round(c, 3) for c in _normal(q["p"])]
    return {"quads": quads, "tex": list(textures), "display": {k: list(v) for k, v in DISPLAY.items()}, "ent": 1}
