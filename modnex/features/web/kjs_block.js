// KubeJS: dibuja bloques y máquinas con su modelo real, en 3D (WebGL), como en el inventario del juego.
// El servidor entrega los cubos, las texturas y la transformación de inventario de cada modelo; aquí se pintan con búfer de
// profundidad e iluminación de Minecraft. Los iconos planos de los items que son bloques se sustituyen solos (`apply`), y las
// máquinas giran al pasar el ratón (`spin`). Sin WebGL se usa un rasterizador 2D más simple.
(function () {
  const SIZE = 128;                                   // píxeles del icono generado
  const rad = (d) => (d * Math.PI) / 180;
  const models = new Map();                           // id -> modelo con sus texturas { elements, display, textures }
  const icons = new Map();                            // id -> data URL | null (null: sin modelo de cubos, se queda el icono plano)
  const pending = new Set();                          // ids por pedir
  let timer = null;
  const GRASS = [0.57, 0.74, 0.35];                   // tinte por defecto de hierba y hojas

  // ---------- geometría compartida ----------
  const NORMAL = { north: [0, 0, -1], south: [0, 0, 1], east: [1, 0, 0], west: [-1, 0, 0], up: [0, 1, 0], down: [0, -1, 0] };
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
  // Caras del modelo: 4 vértices en el espacio del modelo (0..16), esquinas de textura, normal y textura.
  function buildFaces(model) {
    const faces = [];
    for (const el of model.elements) {
      const quads = faceQuads(el.from, el.to);
      for (const [dir, face] of Object.entries(el.faces)) {
        const uv = face.uv || defaultUV(dir, el.from, el.to);
        const corners = [[uv[0], uv[1]], [uv[2], uv[1]], [uv[2], uv[3]], [uv[0], uv[3]]], turn = (face.r || 0) / 90;
        let normal = NORMAL[dir];
        const verts = quads[dir].map((v, i) => {
          let p = v;
          if (el.rot) { const o = el.rot.o; p = rotAxis(p.map((c, k) => c - o[k]), el.rot.a, el.rot.d).map((c, k) => c + o[k]); }
          return { p, uv: corners[(i - turn + 4) % 4] };
        });
        if (el.rot) normal = rotAxis(normal, el.rot.a, el.rot.d);
        faces.push({ dir, t: face.t, tint: !!face.tint, verts, normal });
      }
    }
    return faces;
  }
  const shadeOf = ([x, y, z]) => x * x * 0.6 + y * y * (y > 0 ? 1 : 0.5) + z * z * 0.8;   // el sombreado de caras de Minecraft

  // ---------- WebGL ----------
  const VS = 'attribute vec3 a_pos; attribute vec2 a_uv; attribute vec2 a_sh; uniform mat4 u_mvp; varying vec2 v_uv; varying vec2 v_sh;\n void main(){ gl_Position = u_mvp * vec4(a_pos, 1.0); v_uv = a_uv; v_sh = a_sh; }';
  const FS = 'precision mediump float; uniform sampler2D u_tex; uniform vec3 u_tint; varying vec2 v_uv; varying vec2 v_sh;\n'
    + 'void main(){ vec4 c = texture2D(u_tex, v_uv); if (c.a < 0.05) discard; vec3 rgb = c.rgb * v_sh.x; if (v_sh.y > 0.5) rgb *= u_tint; gl_FragColor = vec4(rgb * c.a, c.a); }';
  let gl = null, glTried = false, prog = null, loc = null, buf = null;
  const texCache = new Map();                          // data URI -> Promise<{ tex, w, h }>

  function initGL() {
    if (glTried) return !!gl;
    glTried = true;
    try {
      const cv = document.createElement('canvas'); cv.width = cv.height = SIZE;
      gl = cv.getContext('webgl', { antialias: true, alpha: true, premultipliedAlpha: true, preserveDrawingBuffer: true });
      if (!gl) return false;
      const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
      prog = gl.createProgram(); gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS)); gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error('enlace');
      loc = { pos: gl.getAttribLocation(prog, 'a_pos'), uv: gl.getAttribLocation(prog, 'a_uv'), sh: gl.getAttribLocation(prog, 'a_sh'),
        mvp: gl.getUniformLocation(prog, 'u_mvp'), tex: gl.getUniformLocation(prog, 'u_tex'), tint: gl.getUniformLocation(prog, 'u_tint') };
      buf = gl.createBuffer();
      gl.enable(gl.DEPTH_TEST); gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
      return true;
    } catch (e) { gl = null; return false; }
  }
  function texture(uri) {
    if (!texCache.has(uri)) {
      texCache.set(uri, new Promise((ok) => {
        const img = new Image();
        img.onload = () => {
          const tex = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, tex);
          gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
          ok({ tex, w: img.width, h: img.height });
        };
        img.onerror = () => ok(null);
        img.src = uri;
      }));
    }
    return texCache.get(uri);
  }
  // Prepara un modelo para GL: texturas cargadas y un lote de vértices por textura.
  async function ensure(model) {
    if (model._gl) return model._gl;
    const loaded = {};
    for (const t of new Set(Object.values(model.faces3d || (model.faces3d = buildFaces(model))).map((f) => f.t))) {
      const uri = model.textures[t]; loaded[t] = uri ? await texture(uri) : null;
    }
    const batches = new Map();
    for (const f of model.faces3d) {
      const tx = loaded[f.t]; if (!tx) continue;
      const b = batches.get(f.t) || { tex: tx.tex, data: [] }, k = tx.w / tx.h, sh = shadeOf(f.normal);
      const v = f.verts.map((q) => [(q.p[0] - 8) / 16, (q.p[1] - 8) / 16, (q.p[2] - 8) / 16, q.uv[0] / 16, (q.uv[1] / 16) * k, sh, f.tint ? 1 : 0]);
      [0, 1, 2, 0, 2, 3].forEach((i) => b.data.push(...v[i]));
      batches.set(f.t, b);
    }
    model._gl = [...batches.values()].map((b) => ({ tex: b.tex, data: new Float32Array(b.data), count: b.data.length / 7 }));
    return model._gl;
  }
  const mul = (a, b) => { const o = new Float32Array(16); for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) { let s = 0; for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k]; o[c * 4 + r] = s; } return o; };
  const rotX = (a) => { const c = Math.cos(rad(a)), s = Math.sin(rad(a)); return new Float32Array([1, 0, 0, 0, 0, c, s, 0, 0, -s, c, 0, 0, 0, 0, 1]); };
  const rotY = (a) => { const c = Math.cos(rad(a)), s = Math.sin(rad(a)); return new Float32Array([c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 0, 0, 0, 1]); };
  const rotZ = (a) => { const c = Math.cos(rad(a)), s = Math.sin(rad(a)); return new Float32Array([c, s, 0, 0, -s, c, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]); };
  const scaleM = ([x, y, z]) => new Float32Array([x, 0, 0, 0, 0, y, 0, 0, 0, 0, z, 0, 0, 0, 0, 1]);
  const moveM = ([x, y, z]) => new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1]);
  const ORTHO = new Float32Array([2, 0, 0, 0, 0, 2, 0, 0, 0, 0, -0.4, 0, 0, 0, 0, 1]);

  // Pinta el modelo (ya preparado) en el lienzo de GL; devuelve ese lienzo. yaw: giro extra sobre la vista de inventario.
  function renderGL(model, yaw) {
    const d = model.display, r = d.rotation;
    let m = mul(ORTHO, moveM(d.translation.map((c) => c / 16)));
    m = mul(m, scaleM(d.scale)); m = mul(m, rotX(r[0])); m = mul(m, rotY(r[1] + (yaw || 0))); m = mul(m, rotZ(r[2]));
    gl.viewport(0, 0, SIZE, SIZE); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.useProgram(prog); gl.uniformMatrix4fv(loc.mvp, false, m); gl.uniform1i(loc.tex, 0); gl.uniform3fv(loc.tint, GRASS);
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    for (const b of model._gl) {
      gl.bindTexture(gl.TEXTURE_2D, b.tex); gl.bufferData(gl.ARRAY_BUFFER, b.data, gl.DYNAMIC_DRAW);
      gl.enableVertexAttribArray(loc.pos); gl.vertexAttribPointer(loc.pos, 3, gl.FLOAT, false, 28, 0);
      gl.enableVertexAttribArray(loc.uv); gl.vertexAttribPointer(loc.uv, 2, gl.FLOAT, false, 28, 12);
      gl.enableVertexAttribArray(loc.sh); gl.vertexAttribPointer(loc.sh, 2, gl.FLOAT, false, 28, 20);
      gl.drawArrays(gl.TRIANGLES, 0, b.count);
    }
    return gl.canvas;
  }

  // ---------- respaldo 2D (sin WebGL) ----------
  const loadImg = (uri) => new Promise((ok) => { const i = new Image(); i.onload = () => ok(i); i.onerror = () => ok(null); i.src = uri; });
  async function draw2d(model) {
    const N = SIZE, d = model.display, ctx = Object.assign(document.createElement('canvas'), { width: N, height: N }).getContext('2d');
    ctx.imageSmoothingEnabled = false;
    const SH = { up: 1, down: 0.5, north: 0.8, south: 0.8, east: 0.6, west: 0.6 }, faces = [];
    for (const f of model.faces3d || (model.faces3d = buildFaces(model))) {
      const pts = f.verts.map((q) => {
        let p = q.p.map((c) => (c - 8) / 16);
        p = rotAxis(rotAxis(rotAxis(p, 'z', d.rotation[2]), 'y', d.rotation[1]), 'x', d.rotation[0]);
        p = p.map((c, k) => c * d.scale[k] + d.translation[k] / 16);
        return { x: N * (0.5 + p[0]), y: N * (0.5 - p[1]), z: p[2], uv: q.uv };
      });
      const cross = (pts[1].x - pts[0].x) * (pts[3].y - pts[0].y) - (pts[1].y - pts[0].y) * (pts[3].x - pts[0].x);
      if (cross > 0.01) faces.push({ pts, dir: f.dir, t: f.t, z: pts.reduce((s, q) => s + q.z, 0) / 4 });
    }
    faces.sort((a, b) => a.z - b.z);
    for (const f of faces) {
      const img = model.textures[f.t] && (await loadImg(model.textures[f.t])); if (!img) continue;
      const k = img.width / 16, [P0, P1, , P3] = f.pts;
      const a1 = [(P1.uv[0] - P0.uv[0]) * k, (P1.uv[1] - P0.uv[1]) * k], a3 = [(P3.uv[0] - P0.uv[0]) * k, (P3.uv[1] - P0.uv[1]) * k], det = a1[0] * a3[1] - a1[1] * a3[0];
      if (Math.abs(det) < 1e-6) continue;
      const p1 = [P1.x - P0.x, P1.y - P0.y], p3 = [P3.x - P0.x, P3.y - P0.y];
      const a = (p1[0] * a3[1] - p3[0] * a1[1]) / det, c = (p3[0] * a1[0] - p1[0] * a3[0]) / det, b = (p1[1] * a3[1] - p3[1] * a1[1]) / det, dd = (p3[1] * a1[0] - p1[1] * a3[0]) / det;
      const sx = P0.uv[0] * k, sy = P0.uv[1] * k, xs = f.pts.map((q) => q.uv[0] * k), ys = f.pts.map((q) => q.uv[1] * k);
      const x0 = Math.min(...xs), y0 = Math.min(...ys), w = Math.max(...xs) - x0, h = Math.max(...ys) - y0;
      if (w <= 0 || h <= 0 || y0 < 0 || x0 < 0 || x0 + w > img.width + 0.01 || y0 + h > img.height + 0.01) continue;
      ctx.save(); ctx.setTransform(a, b, c, dd, P0.x - (a * sx + c * sy), P0.y - (b * sx + dd * sy)); ctx.drawImage(img, x0, y0, w, h, x0, y0, w, h); ctx.restore();
      ctx.beginPath(); f.pts.forEach((q, i) => (i ? ctx.lineTo(q.x, q.y) : ctx.moveTo(q.x, q.y))); ctx.closePath();
      ctx.save(); ctx.clip(); ctx.globalCompositeOperation = 'source-atop'; ctx.fillStyle = `rgba(0,0,0,${1 - SH[f.dir]})`; ctx.fillRect(0, 0, N, N); ctx.restore();
    }
    return ctx.canvas.toDataURL('image/png');
  }
  async function iconOf(model) {
    if (initGL()) { await ensure(model); if (model._gl.length) return renderGL(model, 0).toDataURL('image/png'); }
    return draw2d(model);
  }

  // ---------- carga ----------
  async function fetchModels(base, ids) {
    let res = { models: {}, textures: {} };
    try { res = await window.Modnex.api(`${base}/kubejs_blocks?ids=${encodeURIComponent(ids.join(','))}`); } catch (e) { /* sin modelos */ }
    for (const id of ids) {
      const m = (res.models || {})[id];
      if (!m) { icons.set(id, null); continue; }
      m.textures = Object.fromEntries((m.tex || []).map((t) => [t, res.textures[t]]).filter(([, u]) => u));
      models.set(id, m);
      try { icons.set(id, await iconOf(m)); } catch (e) { icons.set(id, null); }
    }
  }
  // prepare(base, ids) -> { id: data URL | null }
  async function prepare(base, ids) {
    const need = ids.filter((i) => !icons.has(i));
    for (let i = 0; i < need.length; i += 40) await fetchModels(base, need.slice(i, i + 40));
    return Object.fromEntries(ids.map((i) => [i, icons.get(i) || null]));
  }

  // Cambia el icono plano de los items que son bloques por su render con modelo. Los <img data-iid="id"> se piden por lotes.
  function apply(root, base) {
    let missing = false;
    root.querySelectorAll('img[data-iid]').forEach((img) => {
      const id = img.dataset.iid;
      if (icons.has(id)) {
        const u = icons.get(id);
        if (u && img.dataset.iso !== '1') { img.src = u; img.classList.add('iso'); img.dataset.iso = '1'; }
      } else { pending.add(id); missing = true; }
    });
    if (missing) {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const ids = [...pending].slice(0, 120); ids.forEach((i) => pending.delete(i));
        await prepare(base, ids);
        apply(root, base);
      }, 60);
    }
  }

  // Observa un contenedor: cada vez que aparece un icono de item nuevo, se sustituye si es un bloque. Una sola vez por contenedor.
  function watch(root, base) {
    if (root._isoBase === base) return;
    root._isoBase = base;
    let queued = false;
    const run = () => { queued = false; apply(root, base); };
    new MutationObserver(() => { if (!queued) { queued = true; requestAnimationFrame(run); } }).observe(root, { childList: true, subtree: true });
    apply(root, base);
  }

  // Las máquinas giran mientras el puntero está encima (un lienzo sustituye a la imagen y se restaura al salir).
  document.addEventListener('mouseover', (e) => {
    const img = e.target.closest && e.target.closest('img[data-spin]');
    if (!img || img.dataset.spinning) return;
    const model = models.get(img.dataset.spin);
    if (!model || !initGL() || !model._gl) return;
    const cv = document.createElement('canvas'); cv.width = cv.height = SIZE; cv.className = `${img.className} spin`; cv.title = img.title;
    const ctx = cv.getContext('2d'); let yaw = 0, raf = 0;
    img.dataset.spinning = '1'; img.replaceWith(cv);
    const loop = () => { yaw += 2.4; renderGL(model, yaw); ctx.clearRect(0, 0, SIZE, SIZE); ctx.drawImage(gl.canvas, 0, 0); raf = requestAnimationFrame(loop); };
    loop();
    cv.addEventListener('mouseleave', () => { cancelAnimationFrame(raf); delete img.dataset.spinning; cv.replaceWith(img); }, { once: true });
  });

  window.ModnexKjsBlock = { prepare, apply, watch, get: (id) => icons.get(id) || null, has: (id) => models.has(id), webgl: () => initGL() };
})();
