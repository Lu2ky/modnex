// KubeJS: interfaces de Minecraft (mesa de crafteo, horno, cortapiedras, mesa de herrería y fogata) como fondo de las recetas.
// Las texturas vienen del cliente oficial que el panel ya tiene en caché (no están en el repositorio). Las posiciones salen de
// las propias texturas: cada hueco es un cuadrado de 16×16 (o 24×24 en las salidas grandes) medido en píxeles del juego.
(function () {
  const grid = Object.fromEntries(Array.from({ length: 9 }, (_, i) => [`g${i}`, { x: 30 + 18 * (i % 3), y: 17 + 18 * Math.floor(i / 3), w: 16 }]));
  const furnaceLike = (title) => ({ title, tx: 88, ty: 6, center: true, slots: { g0: { x: 56, y: 17, w: 16 }, fuel: { x: 56, y: 53, w: 16, ro: true }, out: { x: 112, y: 31, w: 24 } } });
  const SKINS = {
    crafting: { title: 'Mesa de crafteo', tx: 29, ty: 6, slots: { ...grid, out: { x: 120, y: 31, w: 24 } } },
    furnace: furnaceLike('Horno'),
    blast_furnace: furnaceLike('Horno alto'),
    smoker: furnaceLike('Ahumador'),
    stonecutter: { title: 'Cortapiedras', tx: 8, ty: 4, slots: { g0: { x: 20, y: 33, w: 16 }, out: { x: 139, y: 29, w: 24 } } },
    smithing: { title: 'Mesa de herrería', tx: 44, ty: 15, slots: { template: { x: 8, y: 48, w: 16 }, base: { x: 26, y: 48, w: 16 }, addition: { x: 44, y: 48, w: 16 }, result: { x: 98, y: 48, w: 16 } } },
    // La fogata no tiene interfaz en el juego: se dibuja su sprite grande y el item se coloca encima de las llamas, como al cocinar.
    // El panel y los huecos se dibujan con CSS; la flecha se recorta de la textura del horno (por eso `needs`).
    campfire: { title: 'Fogata', tx: 88, ty: 5, center: true, custom: true, needs: ['campfire', 'furnace'],
      slots: { g0: { x: 51, y: 14, w: 16, draw: true }, out: { x: 124, y: 27, w: 24, draw: true } } },
  };
  const SKIN_OF = { shaped: 'crafting', shapeless: 'crafting', smelting: 'furnace', blasting: 'blast_furnace', smoking: 'smoker', campfire: 'campfire', stonecutting: 'stonecutter' };
  const cache = {};   // base -> Promise<{skin: dataURI}>

  function load(base) {
    if (!cache[base]) {
      cache[base] = window.Modnex.api(`${base}/kubejs_gui`).then((d) => d.textures || {}).catch(() => ({}));
    }
    return cache[base];
  }
  const reload = (base) => { delete cache[base]; return load(base); };

  let textures = {};
  const setTextures = (t) => { textures = t || {}; };
  const has = (skin) => !!SKINS[skin] && (SKINS[skin].needs || [skin]).every((k) => !!textures[k]);
  const skinFor = (type) => SKIN_OF[type] || type;

  // render(key) -> { inner, attrs, on, label, count } para cada hueco. opts.ro: solo para mirar (sin botones); opts.small: tamaño de lista.
  function html(skin, render, title, opts) {
    const o = opts || {}, sk = SKINS[skin];
    const slots = Object.entries(sk.slots).map(([key, g]) => {
      const r = render(key) || {};
      const quiet = g.ro || o.ro;                   // hueco decorativo o de solo lectura: no es un botón
      const x = g.draw ? g.x - 1 : g.x, y = g.draw ? g.y - 1 : g.y, w = g.draw ? g.w + 2 : g.w;
      const tag = quiet ? 'span' : 'button type="button"', end = quiet ? 'span' : 'button';
      const label = r.label || 'casilla vacía';
      const cls = `mc-slot${g.w === 24 ? ' big' : ''}${g.draw ? ' draw' : ''}${r.on ? ' on' : ''}${quiet ? ' ro' : ''}`;
      const who = quiet && !g.ro ? `title="${label}"` : '';
      return `<${tag} class="${cls}" data-mcx="${x}" data-mcy="${y}" data-mcw="${w}" ${g.ro ? 'aria-hidden="true"' : quiet ? `role="img" aria-label="${label}" ${who}` : `aria-label="${label}" ${r.attrs || ''}`}>${r.inner || ''}${r.count > 1 ? `<span class="mc-count">${r.count}</span>` : ''}</${end}>`;
    }).join('');
    const label = `<span class="mc-title${sk.center ? ' center' : ''}" data-mcx="${sk.tx}" data-mcy="${sk.ty}">${title || sk.title}</span>`;
    const cls = `mc-gui${o.small ? ' mc-sm' : ''}${sk.custom ? ' mc-custom' : ''}`;
    const body = sk.custom
      ? '<div class="mc-panel"></div><div class="mc-fire"></div><div class="mc-arrow"></div>'
      : '<div class="mc-top"></div><div class="mc-bottom"></div>';
    return `<div class="${cls}" data-skin="${skin}">${body}${label}${slots}</div>`;
  }

  // CSP: sin atributos style, así que las texturas y las posiciones se escriben con la API de estilos.
  function place(root) {
    root.querySelectorAll('.mc-gui').forEach((g) => {
      const sk = SKINS[g.dataset.skin] || {};
      if (sk.custom) {
        if (textures.campfire) g.style.setProperty('--skin', `url("${textures.campfire}")`);
        if (textures.furnace) g.style.setProperty('--skin2', `url("${textures.furnace}")`);
      } else if (textures[g.dataset.skin]) g.style.setProperty('--skin', `url("${textures[g.dataset.skin]}")`);
      g.querySelectorAll('.mc-title').forEach((t) => { t.style.setProperty('--x', t.dataset.mcx); t.style.setProperty('--y', t.dataset.mcy); });
      g.querySelectorAll('.mc-slot').forEach((s) => {
        s.style.setProperty('--x', s.dataset.mcx);
        s.style.setProperty('--y', s.dataset.mcy);
        s.style.setProperty('--w', s.dataset.mcw);
      });
    });
  }

  window.ModnexKjsGui = { load, reload, setTextures, has, html, place, skinFor, title: (type) => (SKINS[skinFor(type)] || {}).title };
})();
