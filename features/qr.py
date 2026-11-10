"""Generador de códigos QR sin dependencias (modo byte, corrección de errores M, versiones 1 a 10).

Basta para los enlaces `otpauth://` de la verificación en dos pasos (hasta ~210 bytes). Devuelve un SVG
con atributos de presentación (sin `style=`, compatible con la política de contenido del panel).
"""

# versión -> (codewords EC por bloque, bloques grupo 1, datos por bloque g1, bloques grupo 2, datos por bloque g2)
_BLOCKS_M = {1: (10, 1, 16, 0, 0), 2: (16, 1, 28, 0, 0), 3: (26, 1, 44, 0, 0), 4: (18, 2, 32, 0, 0), 5: (24, 2, 43, 0, 0),
             6: (16, 4, 27, 0, 0), 7: (18, 4, 31, 0, 0), 8: (22, 2, 38, 2, 39), 9: (22, 3, 36, 2, 37), 10: (26, 4, 43, 1, 44)}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50]}
MAX_VERSION = 10


class QRError(ValueError):
    pass


# ---------- Reed-Solomon en GF(256), polinomio 0x11D ----------
_EXP, _LOG = [0] * 512, [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gmul(a, b):
    return 0 if not a or not b else _EXP[_LOG[a] + _LOG[b]]


def _generator(n):
    g = [1]
    for i in range(n):
        nxt = [0] * (len(g) + 1)
        for j, c in enumerate(g):
            nxt[j] ^= c
            nxt[j + 1] ^= _gmul(c, _EXP[i])
        g = nxt
    return g


def _rs_remainder(data, n):
    g = _generator(n)
    rem = list(data) + [0] * n
    for i in range(len(data)):
        c = rem[i]
        if c:
            for j in range(1, len(g)):
                rem[i + j] ^= _gmul(g[j], c)
    return rem[len(data):]


# ---------- datos ----------
def _capacity(version):
    ec, g1, d1, g2, d2 = _BLOCKS_M[version]
    return g1 * d1 + g2 * d2


def _choose_version(n):
    for v in range(1, MAX_VERSION + 1):
        bits = 4 + (8 if v < 10 else 16) + 8 * n
        if bits <= 8 * _capacity(v):
            return v
    raise QRError("el texto es demasiado largo para este generador de QR")


def _codewords(data, version):
    bits = []

    def put(val, length):
        bits.extend((val >> i) & 1 for i in range(length - 1, -1, -1))
    put(0b0100, 4)
    put(len(data), 8 if version < 10 else 16)
    for b in data:
        put(b, 8)
    cap = 8 * _capacity(version)
    bits.extend([0] * min(4, cap - len(bits)))
    bits.extend([0] * (-len(bits) % 8))
    out = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(out) < _capacity(version):
        out.append(pad)
        pad ^= 0xEC ^ 0x11
    ec, g1, d1, g2, d2 = _BLOCKS_M[version]
    blocks, pos = [], 0
    for count, size in ((g1, d1), (g2, d2)):
        for _ in range(count):
            blocks.append(out[pos:pos + size])
            pos += size
    ecs = [_rs_remainder(b, ec) for b in blocks]
    inter = []
    for i in range(max(len(b) for b in blocks)):
        inter.extend(b[i] for b in blocks if i < len(b))
    for i in range(ec):
        inter.extend(e[i] for e in ecs)
    return inter


# ---------- matriz ----------
class _Matrix:
    def __init__(self, version):
        self.v, self.n = version, 17 + 4 * version
        self.m = [[False] * self.n for _ in range(self.n)]
        self.f = [[False] * self.n for _ in range(self.n)]
        self._function_patterns()

    def _set(self, x, y, dark):
        self.m[y][x] = bool(dark)
        self.f[y][x] = True

    def _function_patterns(self):
        n = self.n
        for i in range(n):
            self._set(6, i, i % 2 == 0)
            self._set(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        self._set(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = _ALIGN[self.v]
        for i, cy in enumerate(pos):
            for j, cx in enumerate(pos):
                if (i == 0 and j == 0) or (i == 0 and j == len(pos) - 1) or (i == len(pos) - 1 and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self._set(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)
        self._format(0)          # reserva las zonas de formato
        if self.v >= 7:
            rem = self.v
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.v << 12 | rem
            for i in range(18):
                a, b = n - 11 + i % 3, i // 3
                self._set(a, b, (bits >> i) & 1)
                self._set(b, a, (bits >> i) & 1)

    def _format(self, mask):
        n = self.n
        data = 0 << 3 | mask          # nivel M = 0b00
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        g = lambda i: (bits >> i) & 1
        for i in range(6):
            self._set(8, i, g(i))
        self._set(8, 7, g(6))
        self._set(8, 8, g(7))
        self._set(7, 8, g(8))
        for i in range(9, 15):
            self._set(14 - i, 8, g(i))
        for i in range(8):
            self._set(n - 1 - i, 8, g(i))
        for i in range(8, 15):
            self._set(8, n - 15 + i, g(i))
        self._set(8, n - 8, True)     # módulo oscuro

    def place(self, codewords):
        n, i = self.n, 0
        total = len(codewords) * 8
        right = n - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(n):
                for j in range(2):
                    x = right - j
                    y = n - 1 - vert if ((right + 1) & 2) == 0 else vert
                    if not self.f[y][x] and i < total:
                        self.m[y][x] = bool((codewords[i >> 3] >> (7 - (i & 7))) & 1)
                        i += 1
            right -= 2

    def apply_mask(self, mask):
        for y in range(self.n):
            for x in range(self.n):
                if self.f[y][x]:
                    continue
                inv = (
                    (x + y) % 2 == 0, y % 2 == 0, x % 3 == 0, (x + y) % 3 == 0, (x // 3 + y // 2) % 2 == 0,
                    x * y % 2 + x * y % 3 == 0, (x * y % 2 + x * y % 3) % 2 == 0, ((x + y) % 2 + x * y % 3) % 2 == 0,
                )[mask]
                if inv:
                    self.m[y][x] = not self.m[y][x]

    def penalty(self):
        n, m, score = self.n, self.m, 0
        for lines in (m, [list(col) for col in zip(*m)]):
            for row in lines:
                run, color = 1, row[0]
                for c in row[1:] + [None]:
                    if c == color:
                        run += 1
                    else:
                        if run >= 5:
                            score += 3 + run - 5
                        color, run = c, 1
                s = "".join("1" if c else "0" for c in row)
                for pat in ("00001011101", "10111010000"):
                    start = s.find(pat)
                    while start != -1:
                        score += 40
                        start = s.find(pat, start + 1)
        for y in range(n - 1):
            for x in range(n - 1):
                if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    score += 3
        dark = sum(c for row in m for c in row)
        k = abs(dark * 20 - n * n * 10) // (n * n)
        return score + k * 10


def matrix(text, mask=None):
    """Matriz de módulos (lista de listas de bool) para `text`. `mask` fuerza una máscara (0-7); se usa en pruebas."""
    data = text.encode("utf-8")
    version = _choose_version(len(data))
    words = _codewords(data, version)
    best = None
    for mk in ([mask] if mask is not None else range(8)):
        q = _Matrix(version)
        q.place(words)
        q.apply_mask(mk)
        q._format(mk)
        p = q.penalty()
        if best is None or p < best[0]:
            best = (p, q)
    return best[1].m


def svg(text, border=4, mask=None):
    m = matrix(text, mask)
    n = len(m)
    parts = []
    for y, row in enumerate(m):          # una pieza por tramo horizontal de módulos oscuros
        x = 0
        while x < n:
            if row[x]:
                start = x
                while x < n and row[x]:
                    x += 1
                parts.append(f"M{start + border},{y + border}h{x - start}v1h-{x - start}z")
            else:
                x += 1
    d = "".join(parts)
    size = n + 2 * border
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" shape-rendering="crispEdges" role="img" aria-label="Código QR">'
            f'<rect width="{size}" height="{size}" fill="#fff"/><path d="{d}" fill="#000"/></svg>')
