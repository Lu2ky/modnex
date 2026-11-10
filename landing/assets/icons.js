// Iconos pixel-art de 12x12 para los servidores. Cada icono se dibuja como SVG con
// un rect por tramo de píxeles iguales. Los nombres deben coincidir con db.ICONS.
(function () {
  const N = 12;

  // Construye una rejilla a partir de una forma (inside) y un relleno; el contorno es automático.
  function shape(inside, fill, outline = true) {
    const ins = (x, y) => x >= 0 && y >= 0 && x < N && y < N && inside(x, y);
    const rows = [];
    for (let y = 0; y < N; y++) {
      let row = '';
      for (let x = 0; x < N; x++) {
        if (!ins(x, y)) { row += '.'; continue; }
        const edge = !ins(x - 1, y) || !ins(x + 1, y) || !ins(x, y - 1) || !ins(x, y + 1);
        row += edge && outline ? 'k' : fill(x, y);
      }
      rows.push(row);
    }
    return rows;
  }

  // Dibujo a mano; el contorno oscuro se añade solo.
  function hand(rows, outline = true) {
    const ins = (x, y) => x >= 0 && y >= 0 && x < N && y < N && rows[y][x] !== '.';
    return rows.map((r, y) => [...r].map((c, x) => {
      if (c === '.') return '.';
      const edge = !ins(x - 1, y) || !ins(x + 1, y) || !ins(x, y - 1) || !ins(x, y + 1);
      return edge && outline ? 'k' : c;
    }).join(''));
  }

  const inPoly = (x, y, pts) => {
    let inside = false;
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      const [xi, yi] = pts[i], [xj, yj] = pts[j];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  };

  const ICONS = {
    pokeball: Array.from({ length: N }, (_, y) => [...Array(N)].map((_, x) => {
      const dx = x - 5.5, dy = y - 5.5, d = Math.hypot(dx, dy);
      if (d > 5.9) return '.';
      if (d < 2.2) return d > 1.5 ? 'k' : 'w';
      if (d > 4.9 || Math.abs(dy) < 0.8) return 'k';
      return dy < 0 ? 'r' : 'w';
    }).join('')),

    pickaxe: hand([
      '............', '...gggggg...', '..ggssssgg..', '.ggg.nn.ggg.', '.gg..nn..gg.', 'g....nn....g',
      '.....nn.....', '.....nn.....', '.....nn.....', '.....nn.....', '.....nn.....', '............'], false),

    sword: hand([
      '.....sg.....', '....ssgg....', '....ssgg....', '....ssgg....', '....ssgg....', '....ssgg....',
      '....ssgg....', '.yyyyyyyyyy.', '.....nn.....', '.....nn.....', '....yyyy....', '............'], false),

    shield: shape(
      (x, y) => Math.abs(x - 5.5) <= (y <= 6 ? 5.5 : 5.5 - (y - 6) * 1.12) && y <= 11,
      (x, y) => (x === 5 || x === 6 ? 'w' : x < 5 ? 'b' : 'v')),

    creeper: shape(() => true, (x, y) => {
      const eye = (y === 3 || y === 4) && ((x >= 2 && x <= 3) || (x >= 8 && x <= 9));
      const mouth = (y === 5 && x >= 5 && x <= 6) || ((y === 6 || y === 7) && x >= 4 && x <= 7) ||
        (y === 8 && (x === 4 || x === 7));
      if (eye || mouth) return 'k';
      return (x * 7 + y * 13) % 5 === 0 ? 'd' : 'l';
    }),

    heart: hand([
      '............', '.rrrr..rrrr.', 'rpprrrrrrrrr', 'rprrrrrrrrrr', 'rrrrrrrrrrrr', '.rrrrrrrrrr.',
      '..rrrrrrrr..', '...rrrrrr...', '....rrrr....', '.....rr.....', '............', '............']),

    diamond: shape(
      (x, y) => (y < 4 ? Math.abs(x - 5.5) <= 3.4 + y * 0.7 : Math.abs(x - 5.5) <= 6 - (y - 4) * 0.86) && y <= 11,
      (x, y) => (y === 4 ? 'w' : x > 5.5 ? 'b' : (x <= 3 && y <= 3 ? 'w' : 'c'))),

    gear: shape((x, y) => {
      const dx = x - 5.5, dy = y - 5.5, d = Math.hypot(dx, dy);
      if (d < 1.8) return false;
      const tooth = Math.cos(6 * Math.atan2(dy, dx)) > 0.1;
      return d <= (tooth ? 5.9 : 4.3);
    }, (x, y) => (x + y < 9 ? 's' : 'g'), false),

    flame: hand([
      '.......o....', '......oo....', '......ooo...', '.o...ooooo..', '.oo.ooooooo.', '.ooooooooooo',
      'oooooyyooooo', 'ooooyyyyoooo', 'ooooyyyyoooo', '.oooyywyooo.', '..oooyyooo..', '...oooooo...']),

    leaf: shape((x, y) => {
      const px = x - 5.5, py = y - 5.5;
      const s = (px - py) * 0.7071, w = (px + py) * 0.7071;
      const lens = Math.abs(w) <= 3.4 * (1 - Math.pow(s / 6.6, 2)) && Math.abs(s) <= 6.6;
      const stem = s < -5 && s > -8.2 && Math.abs(w) < 0.8;
      return lens || stem;
    }, (x, y) => {
      const px = x - 5.5, py = y - 5.5;
      const s = (px - py) * 0.7071, w = (px + py) * 0.7071;
      if (s < -5.5) return 'n';
      return Math.abs(w) < 0.7 ? 'd' : 'l';
    }),

    star: shape((x, y) => {
      const pts = [];
      for (let i = 0; i < 10; i++) {
        const a = -Math.PI / 2 + (i * Math.PI) / 5, r = i % 2 ? 2.5 : 6.2;
        pts.push([5.5 + r * Math.cos(a), 6.1 + r * Math.sin(a)]);
      }
      return inPoly(x + 0.5, y + 0.5, pts);
    }, (x, y) => (x + y < 9 ? 'w' : 'y')),

    crown: hand([
      '............', '.y...yy...y.', '.yy.yyyy.yy.', '.yyyyyyyyyy.', '.yyyyyyyyyy.', '.yyryyyyryy.',
      '.yyyyyyyyyy.', '.oooooooooo.', '.oooooooooo.', '............', '............', '............']),
  };

  // Devuelve el SVG del icono (tamaño en px). Cada fila se compacta en tramos del mismo color.
  window.pixelIcon = function (name, size) {
    const rows = ICONS[name] || ICONS.pokeball;
    let rects = '';
    rows.forEach((row, y) => {
      let x = 0;
      while (x < N) {
        const c = row[x];
        let e = x;
        while (e < N && row[e] === c) e++;
        if (c !== '.') rects += `<rect class="${c}" x="${x}" y="${y}" width="${e - x}" height="1"/>`;
        x = e;
      }
    });
    return `<svg class="px" width="${size}" height="${size}" viewBox="0 0 ${N} ${N}" shape-rendering="crispEdges" aria-hidden="true">${rects}</svg>`;
  };
  window.PIXEL_ICON_NAMES = Object.keys(ICONS);
})();
