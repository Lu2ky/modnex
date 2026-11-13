// KubeJS: dibuja un bloque o máquina como en el inventario del juego (vista isométrica) a partir de su modelo de cubos.
// El servidor entrega los cubos, las texturas y la transformación de inventario; aquí se proyectan, se ordenan por profundidad y se pintan.
(function () {
  const N = 96;                                         // tamaño del icono en píxeles
  const SHADE = { up: 1, down: 0.5, north: 0.8, south: 0.8, east: 0.6, west: 0.6 };
  const rad = (d) => (d * Math.PI) / 180;
  const cache = {};                                     // id -> data URL | null
  const imgs = {};                                      // data URI de textura -> Promise<Image>

  function faceQuads(f, t) {
    const [x1, y1, z1] = f, [x2, y2, z2] = t;
    return {
      north: [[x2, y2, z1], [x1, y2, z1], [x1, y1, z1], [x2, y1, z1]],
      south: [[x1, y2, z2], [x2, y2, z2], [x2, y1, z2], [x1, y1, z2]],
      east: [[x2, y2, z2], [x2, y2, z1], [x2, y1, z1], [x2, y1, z2]],
      west: [[x1, y2, z1], [x1, y2, z2], [x1, y1, z2], [x1, y1, z1]],
      up: [[x1, y2, z1], [x2, y2, z1], [x2, y2, z2], [x1, y2, z2]],
      down: [[x1, y1, z2], [x2, y1, z2], [x2, y1, z1], [x1, y1, z1]],
    };
  }
  function defaultUV(d, f, t) {
    const [x1, y1, z1] = f, [x2, y2, z2] = t;
    return { north: [16 - x2, 16 - y2, 16 - x1, 16 - y1], south: [x1, 16 - y2, x2, 16 - y1], east: [16 - z2, 16 - y2, 16 - z1, 16 - y1],
      west: [z1, 16 - y2, z2, 16 - y1], up: [x1, z1, x2, z2], down: [x1, 16 - z2, x2, 16 - z1] }[d];
  }
  function rotAxis(p, axis, deg) {
    const c = Math.cos(rad(deg)), s = Math.sin(rad(deg)), [x, y, z] = p;
    if (axis === 'y') return [x * c + z * s, y, -x * s + z * c];
    if (axis === 'x') return [x, y * c - z * s, y * s + z * c];
    return [x * c - y * s, x * s + y * c, z];
  }
  const loadImg = (uri) => (imgs[uri] || (imgs[uri] = new Promise((ok) => { const i = new Image(); i.onload = () => ok(i); i.onerror = () => ok(null); i.src = uri; })));

  async function draw(model) {
    const d = model.display, ctx = Object.assign(document.createElement('canvas'), { width: N, height: N }).getContext('2d');
    ctx.imageSmoothingEnabled = false;
    const faces = [];
    for (const el of model.elements) {
      const quads = faceQuads(el.from, el.to);
      for (const [dir, face] of Object.entries(el.faces)) {
        const uv = face.uv || defaultUV(dir, el.from, el.to);
        const corners = [[uv[0], uv[1]], [uv[2], uv[1]], [uv[2], uv[3]], [uv[0], uv[3]]];
        const turn = (face.r || 0) / 90;
        const pts = quads[dir].map((v, i) => {
          let p = v;
          if (el.rot) { const o = el.rot.o; p = rotAxis(p.map((c, k) => c - o[k]), el.rot.a, el.rot.d).map((c, k) => c + o[k]); }
          p = p.map((c) => (c - 8) / 16);
          p = rotAxis(rotAxis(rotAxis(p, 'z', d.rotation[2]), 'y', d.rotation[1]), 'x', d.rotation[0]);
          p = p.map((c, k) => c * d.scale[k] + d.translation[k] / 16);
          return { x: N * (0.5 + p[0]), y: N * (0.5 - p[1]), z: p[2], uv: corners[(i - turn + 4) % 4] };
        });
        const cross = (pts[1].x - pts[0].x) * (pts[3].y - pts[0].y) - (pts[1].y - pts[0].y) * (pts[3].x - pts[0].x);
        if (cross <= 0.01) continue;                    // cara de atrás
        faces.push({ pts, dir, t: face.t, z: pts.reduce((s, q) => s + q.z, 0) / 4 });
      }
    }
    faces.sort((a, b) => a.z - b.z);                    // de lejos a cerca
    for (const f of faces) {
      const img = await loadImg(model.textures[f.t]);
      if (!img) continue;
      const k = img.width / 16, [P0, P1, , P3] = f.pts;
      const a1 = [(P1.uv[0] - P0.uv[0]) * k, (P1.uv[1] - P0.uv[1]) * k], a3 = [(P3.uv[0] - P0.uv[0]) * k, (P3.uv[1] - P0.uv[1]) * k];
      const det = a1[0] * a3[1] - a1[1] * a3[0];
      if (Math.abs(det) < 1e-6) continue;
      const p1 = [P1.x - P0.x, P1.y - P0.y], p3 = [P3.x - P0.x, P3.y - P0.y];
      // M = [p1 p3] · inv([a1 a3]); x' = a·x + c·y + e, y' = b·x + d·y + f
      const a = (p1[0] * a3[1] - p3[0] * a1[1]) / det, c = (p3[0] * a1[0] - p1[0] * a3[0]) / det;
      const b = (p1[1] * a3[1] - p3[1] * a1[1]) / det, dd = (p3[1] * a1[0] - p1[1] * a3[0]) / det;
      const sx = P0.uv[0] * k, sy = P0.uv[1] * k;
      const e = P0.x - (a * sx + c * sy), fy = P0.y - (b * sx + dd * sy);
      const xs = f.pts.map((q) => q.uv[0] * k), ys = f.pts.map((q) => q.uv[1] * k);
      const x0 = Math.min(...xs), y0 = Math.min(...ys), w = Math.max(...xs) - x0, h = Math.max(...ys) - y0;
      if (w <= 0 || h <= 0 || y0 < 0 || x0 < 0 || x0 + w > img.width + 0.01 || y0 + h > img.height + 0.01) continue;   // uv fuera de la textura
      ctx.save();
      ctx.setTransform(a, b, c, dd, e, fy);
      ctx.drawImage(img, x0, y0, w, h, x0, y0, w, h);
      ctx.restore();
      ctx.beginPath(); f.pts.forEach((q, i) => (i ? ctx.lineTo(q.x, q.y) : ctx.moveTo(q.x, q.y))); ctx.closePath();
      ctx.save(); ctx.clip(); ctx.globalCompositeOperation = 'source-atop';
      ctx.fillStyle = `rgba(0,0,0,${1 - SHADE[f.dir]})`; ctx.fillRect(0, 0, N, N); ctx.restore();
    }
    return ctx.canvas.toDataURL('image/png');
  }

  // ids -> { id: dataURL | null }. null: sin modelo de cubos, se usa el icono plano.
  async function prepare(base, ids) {
    const need = ids.filter((i) => !(i in cache));
    if (need.length) {
      let models = {};
      try { models = (await window.Modnex.api(`${base}/kubejs_blocks?ids=${encodeURIComponent(need.join(','))}`)).models || {}; } catch (e) { /* sin modelos */ }
      for (const id of need) {
        try { cache[id] = models[id] ? await draw(models[id]) : null; } catch (e) { cache[id] = null; }
      }
    }
    return Object.fromEntries(ids.map((i) => [i, cache[i]]));
  }
  window.ModnexKjsBlock = { prepare, get: (id) => cache[id] || null, draw };
})();
