// KubeJS: interfaces de Minecraft (mesa de crafteo, horno, cortapiedras, mesa de herrería) como fondo del editor de recetas.
// Las texturas vienen del cliente oficial que el panel ya tiene en caché (no están en el repositorio). Las posiciones salen de
// las propias texturas: cada hueco es un cuadrado de 16×16 (o 24×24 en las salidas grandes) medido en píxeles del juego.
(function () {
  const grid = Object.fromEntries(Array.from({ length: 9 }, (_, i) => [`g${i}`, { x: 30 + 18 * (i % 3), y: 17 + 18 * Math.floor(i / 3), w: 16 }]));
  const SKINS = {
    crafting: { title: 'Mesa de crafteo', tx: 29, ty: 6, slots: { ...grid, out: { x: 120, y: 31, w: 24 } } },
    furnace: { title: 'Horno', tx: 88, ty: 6, center: true, slots: { g0: { x: 56, y: 17, w: 16 }, fuel: { x: 56, y: 53, w: 16, ro: true }, out: { x: 112, y: 31, w: 24 } } },
    blast_furnace: { title: 'Horno alto', tx: 88, ty: 6, center: true, slots: { g0: { x: 56, y: 17, w: 16 }, fuel: { x: 56, y: 53, w: 16, ro: true }, out: { x: 112, y: 31, w: 24 } } },
    smoker: { title: 'Ahumador', tx: 88, ty: 6, center: true, slots: { g0: { x: 56, y: 17, w: 16 }, fuel: { x: 56, y: 53, w: 16, ro: true }, out: { x: 112, y: 31, w: 24 } } },
    stonecutter: { title: 'Cortapiedras', tx: 8, ty: 4, slots: { g0: { x: 20, y: 33, w: 16 }, out: { x: 139, y: 29, w: 24 } } },
    smithing: { title: 'Mesa de herrería', tx: 44, ty: 15, slots: { template: { x: 8, y: 48, w: 16 }, base: { x: 26, y: 48, w: 16 }, addition: { x: 44, y: 48, w: 16 }, result: { x: 98, y: 48, w: 16 } } },
  };
  // La fogata no tiene interfaz propia: usa la del horno, con su nombre.
  const SKIN_OF = { shaped: 'crafting', shapeless: 'crafting', smelting: 'furnace', blasting: 'blast_furnace', smoking: 'smoker', campfire: 'furnace', stonecutting: 'stonecutter' };
  const TITLE = { campfire: 'Fogata' };
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
  const has = (skin) => !!textures[skin];
  const skinFor = (type) => SKIN_OF[type] || type;

  // render(key) -> { inner, attrs, on, label } para cada hueco de la interfaz; ro = decorativo (el combustible del horno).
  function html(skin, render, title) {
    const sk = SKINS[skin];
    const slots = Object.entries(sk.slots).map(([key, g]) => {
      const r = render(key) || {};
      const tag = g.ro ? 'span' : 'button type="button"';
      const end = g.ro ? 'span' : 'button';
      return `<${tag} class="mc-slot${g.w === 24 ? ' big' : ''}${r.on ? ' on' : ''}${g.ro ? ' ro' : ''}" data-mcx="${g.x}" data-mcy="${g.y}" data-mcw="${g.w}" ${g.ro ? 'aria-hidden="true"' : `aria-label="${r.label || 'casilla vacía'}" ${r.attrs || ''}`}>${r.inner || ''}${r.count > 1 ? `<span class="mc-count">${r.count}</span>` : ''}</${end}>`;
    }).join('');
    return `<div class="mc-gui" data-skin="${skin}"><div class="mc-top"></div><div class="mc-bottom"></div><span class="mc-title${sk.center ? ' center' : ''}" data-mcx="${sk.tx}" data-mcy="${sk.ty}">${title || sk.title}</span>${slots}</div>`;
  }

  // CSP: sin atributos style, así que la textura y las posiciones se escriben con la API de estilos.
  function place(root) {
    root.querySelectorAll('.mc-gui').forEach((g) => {
      const tex = textures[g.dataset.skin];
      if (tex) g.style.setProperty('--skin', `url("${tex}")`);
      g.querySelectorAll('.mc-title').forEach((t) => { t.style.setProperty('--x', t.dataset.mcx); t.style.setProperty('--y', t.dataset.mcy); });
      g.querySelectorAll('.mc-slot').forEach((s) => {
        s.style.setProperty('--x', s.dataset.mcx);
        s.style.setProperty('--y', s.dataset.mcy);
        s.style.setProperty('--w', s.dataset.mcw);
      });
    });
  }

  window.ModnexKjsGui = { load, reload, setTextures, has, html, place, skinFor, title: (type) => TITLE[type] || (SKINS[skinFor(type)] || {}).title };
})();
