#!/usr/bin/env python3
"""Genera la escena lo-fi de la landing (Steve de espaldas, noche lluviosa) como SVG de píxeles.
Dibujo propio; usa solo formas y colores definidos aquí. Salida: SVG en stdout."""
import random
W, H = 96, 54
cv = [[None] * W for _ in range(H)]
rnd = random.Random(7)

def px(x, y, c):
    if 0 <= x < W and 0 <= y < H:
        cv[y][x] = c

def rect(x0, y0, x1, y1, c):
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            px(x, y, c)

def line(x0, y0, x1, y1, c):
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    while True:
        px(x0, y0, c)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy: err += dy; x0 += sx
        if e2 <= dx: err += dx; y0 += sy

def disc(cx, cy, r, c):
    for y in range(cy - r, cy + r + 1):
        for x in range(cx - r, cx + r + 1):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r * r + r:
                px(x, y, c)

# --- pared y ventana -------------------------------------------------------
rect(0, 0, 95, 53, "#2b2036")
for y0, y1, c in ((6, 13, "#161129"), (14, 21, "#1c1533"), (22, 29, "#231a3a"), (30, 37, "#2b1f3e")):
    rect(8, y0, 59, y1, c)
for cx, cy, r in ((16, 12, 4), (26, 14, 5), (40, 11, 4), (50, 15, 5), (34, 19, 4), (12, 20, 4)):
    disc(cx, cy, r, "#2c2345")
lit_windows = []
x = 8
while x < 59:  # ciudad lejana
    w = rnd.randint(3, 6); h = rnd.randint(8, 16)
    rect(x, 37 - h, min(x + w, 59), 37, "#3a2b5c"); x += w + 1
x = 8
while x < 59:  # ciudad cercana
    w = rnd.randint(4, 7); h = rnd.randint(4, 11)
    rect(x, 37 - h, min(x + w, 59), 37, "#1b1230")
    for yy in range(37 - h + 1, 37, 2):
        for xx in range(x + 1, min(x + w, 59), 2):
            if rnd.random() < 0.5:
                px(xx, yy, "#ffb25a" if rnd.random() < 0.6 else "#ff7a4a"); lit_windows.append((xx, yy))
    x += w + 1
rect(19, 9, 20, 37, "#2a1a3a")  # torre de neón
for yy in (14, 18, 22, 26):
    rect(18, yy, 21, yy + 1, "#e0409a")
rect(19, 7, 19, 8, "#e0409a")
# marco de la ventana
for c, args in (("#9a5236", (6, 4, 61, 5)), ("#9a5236", (6, 4, 7, 40)), ("#9a5236", (60, 4, 61, 40)),
                ("#9a5236", (33, 4, 34, 38)), ("#c0683c", (4, 38, 63, 40))):
    rect(*args, c)
# --- pared derecha, lámpara, póster, libros -----------------------------------
rect(62, 0, 95, 39, "#3a2a42")
rect(66, 14, 90, 36, "#42304a")  # zona iluminada por la lámpara
line(95, 2, 83, 9, "#241822")
for c, y0, y1, x0, x1 in (("#5a2a2a", 9, 13, 74, 88), ("#7a3a30", 14, 14, 72, 90)):
    rect(x0, y0, x1, y1, c)
rect(75, 15, 87, 15, "#ffb25a")
rect(80, 19, 89, 28, "#f0b8b0")  # póster con corazón
for hx, hy in ((82, 22), (83, 21), (84, 22), (85, 21), (86, 22)):
    px(hx, hy, "#c0405a")
rect(83, 23, 85, 24, "#c0405a"); px(84, 25, "#c0405a")
for i, (c, hgt) in enumerate((("#8a3a4a", 9), ("#3a6a5a", 8), ("#c0a060", 10), ("#4a4a8a", 8), ("#8a3a4a", 9))):
    rect(84 + i * 2, 39 - hgt, 85 + i * 2, 39, c)
# --- escritorio ------------------------------------------------------------------
rect(0, 40, 95, 42, "#c0683c"); rect(0, 40, 95, 40, "#d98050"); rect(0, 43, 95, 53, "#7a3d2a")
# planta
rect(1, 34, 8, 40, "#6a3a2a")
for (x1, y1) in ((0, 26), (8, 26), (4, 23), (1, 30), (7, 30), (4, 27)):
    line(4, 34, x1, y1, "#3f8f4a"); line(5, 34, x1 + 1, y1, "#2f7040")
# computador retro
rect(14, 31, 28, 40, "#4a8fd6"); rect(14, 31, 28, 31, "#6fb0f0"); rect(15, 32, 27, 38, "#2e6fb0")
rect(16, 33, 26, 37, "#14141c")
rect(15, 39, 27, 40, "#d9b88a")
for kx in range(16, 27, 2): px(kx, 39, "#a07a52")
# papel y bolígrafo
rect(34, 40, 43, 41, "#d9c8a8")
# silla
rect(47, 37, 65, 53, "#2e2230"); rect(49, 35, 63, 37, "#2e2230")
# --- Steve de espaldas ----------------------------------------------------------------
rect(49, 20, 63, 33, "#3e2a1a"); rect(50, 20, 62, 21, "#6a4a30"); rect(52, 22, 60, 23, "#4a3322"); rect(49, 31, 63, 33, "#2e1f13"); rect(49, 27, 50, 29, "#b98458"); rect(62, 27, 63, 29, "#b98458"); rect(48, 21, 48, 32, "#2a1a10"); rect(64, 21, 64, 32, "#2a1a10"); rect(49, 19, 63, 19, "#2a1a10")
rect(53, 34, 59, 35, "#b98458")
rect(46, 35, 66, 41, "#2f8f96"); rect(46, 35, 66, 36, "#4cc0c6"); rect(46, 40, 66, 41, "#26757b"); rect(55, 36, 57, 41, "#26757b")
rect(44, 38, 49, 42, "#2f8f96"); rect(63, 38, 71, 42, "#2f8f96")
rect(41, 40, 44, 42, "#b98458"); rect(72, 39, 74, 41, "#b98458")
# --- taza --------------------------------------------------------------------------------
rect(76, 34, 81, 40, "#e9e4d8"); rect(76, 34, 81, 34, "#c98a4a"); rect(82, 35, 83, 38, "#e9e4d8")
px(78, 33, "#e9e4d8"); px(79, 32, "#e9e4d8")  # hilo de la bolsita
# --- salida SVG ---------------------------------------------------------------------------------
def runs():
    out = []
    for y in range(H):
        x = 0
        while x < W:
            c = cv[y][x]
            if c is None:
                x += 1; continue
            e = x
            while e < W and cv[y][e] == c: e += 1
            out.append(f'<rect x="{x}" y="{y}" width="{e - x}" height="1" fill="{c}"/>')
            x = e
    return "".join(out)

rain = "".join(f'<rect x="{x}" y="{y}" width="1" height="3" fill="#8fa4d6" opacity="0.55"/>'
               for x, y in [(rnd.randint(9, 58), rnd.randint(6, 30)) for _ in range(26)])
lights = "".join(f'<rect x="{x}" y="{3 + int(2 * ((x - 48) / 48) ** 2) - 1}" width="2" height="2" fill="#ffd27a"/>' for x in range(3, 95, 12))
flick = "".join(f'<rect x="{x}" y="{y}" width="1" height="1" fill="#14101f"/>' for x, y in rnd.sample(lit_windows, min(6, len(lit_windows))))
screens = ("".join(f'<rect x="{17 + i * 2}" y="{34 + (i % 2)}" width="2" height="2" fill="{c}"/>' for i, c in enumerate(("#ff6b9a", "#6bf0ff", "#ffd27a", "#9aff9a", "#ff6b9a")))
           + "|" + '<rect x="19" y="34" width="6" height="2" fill="#ff6b9a"/><rect x="21" y="36" width="2" height="1" fill="#ff6b9a"/>'
           + "|" + '<rect x="17" y="35" width="8" height="1" fill="#6bf0ff"/>')
s1, s2, s3 = screens.split("|")
steam = '<rect x="77" y="29" width="1" height="2" fill="#d9dde8"/><rect x="79" y="28" width="1" height="2" fill="#d9dde8"/><rect x="78" y="30" width="1" height="2" fill="#d9dde8"/>'
svg = (f'<svg class="lofi-scene" viewBox="0 0 {W} {H}" shape-rendering="crispEdges" role="img" aria-label="Steve de espaldas, trabajando de noche con una taza de té y lluvia en la ventana">'
       f'<g>{runs()}</g><g class="l-rain">{rain}</g><g class="l-flick">{flick}</g><g class="l-lights">{lights}</g>'
       f'<g class="l-scr l-s1">{s1}</g><g class="l-scr l-s2">{s2}</g><g class="l-scr l-s3">{s3}</g><g class="l-steam">{steam}</g></svg>')
print(svg)
