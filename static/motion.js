// Iconos SVG animados para las interacciones del panel: confirmaciones, avisos, subidas, borrados y estados vacíos.
// Son SVG en línea (para que el CSS llegue a sus trazos) y cada trazo lleva pathLength="1": así se dibujan de golpe con
// stroke-dashoffset sin medir nada con JavaScript. La animación vive en style.css; aquí solo está el dibujo.
(function () {
  // d = trazo que se dibuja al aparecer (d1…d5 escalonan el inicio); el resto de clases las usa style.css.
  const p = (cls, d) => `<path class="d ${cls}" pathLength="1" d="${d}"/>`;
  const RING = 'M12 3a9 9 0 1 1 0 18a9 9 0 1 1 0-18';

  const ICONS = {
    check: { vb: 24, body: p('d1', RING) + p('d3', 'M7.8 12.6l3 3l5.6-6.2') },
    error: { vb: 24, body: p('d1', RING) + p('d3', 'M9 9l6 6') + p('d4', 'M15 9l-6 6') },
    info: { vb: 24, body: p('d1', RING) + p('d3', 'M12 11v5') + p('d4', 'M12 8h.01') },
    trash: {
      vb: 24,
      body: p('d2', 'M6.5 9l.9 10.2a1.5 1.5 0 0 0 1.5 1.3h6.2a1.5 1.5 0 0 0 1.5-1.3L17.5 9') + p('d3', 'M10 12.5v4') + p('d3', 'M14 12.5v4') +
        `<g class="lid">${p('d1', 'M4.5 6.5h15')}${p('d1', 'M9.5 6.5V4.5a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1v2')}</g>`,
    },
    upload: {
      vb: 24,
      body: p('d1', 'M4 15.5V18a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2.5') + `<g class="arrow">${p('d2', 'M12 15V4.5')}${p('d3', 'M8 8.5l4-4l4 4')}</g>`,
    },
    // El dibujo de «copiar» no usa la animación de trazo: pasa a un tick con una transición cuando se le pone .is-done
    copy: {
      vb: 24,
      body: '<g class="sheets"><path pathLength="1" d="M9 8.5V6.5a1.5 1.5 0 0 1 1.5-1.5h8A1.5 1.5 0 0 1 20 6.5v8a1.5 1.5 0 0 1-1.5 1.5H17"/>' +
        '<rect x="4" y="8.5" width="11" height="11.5" rx="1.8"/></g><path class="tick" pathLength="1" d="M6.2 14.4l2.9 2.9l5.4-6"/>',
    },
    // ---- ilustraciones de estados vacíos (48×48, trazo más fino) ----
    box: {
      vb: 48, cls: 'mi-empty',
      body: p('d1', 'M6 28l5.4-14.2a3 3 0 0 1 2.8-1.9h19.6a3 3 0 0 1 2.8 1.9L42 28v8a3 3 0 0 1-3 3H9a3 3 0 0 1-3-3z') +
        p('d2', 'M6 28h11l1.6 3.2a3 3 0 0 0 2.7 1.7h5.4a3 3 0 0 0 2.7-1.7L31 28h11') +
        `<g class="acc"><path class="d d4" pathLength="1" d="M37 5v6"/><path class="d d4" pathLength="1" d="M34 8h6"/><path class="d d5" pathLength="1" d="M11 4v4"/><path class="d d5" pathLength="1" d="M9 6h4"/></g>`,
    },
    search: {
      vb: 48, cls: 'mi-empty',
      body: `<g class="lens">${p('d1', 'M21 10a11 11 0 1 1 0 22a11 11 0 1 1 0-22')}${p('d2', 'M29.2 29.2L40 40')}</g>` + p('d3', 'M17.6 17.6l6.8 6.8') + p('d4', 'M24.4 17.6l-6.8 6.8'),
    },
    list: {
      vb: 48, cls: 'mi-empty',
      body: p('d1', 'M16 14h22') + p('d2', 'M16 24h22') + p('d3', 'M16 34h14') +
        `<g class="acc">${p('d1', 'M9.5 14h.01')}${p('d2', 'M9.5 24h.01')}${p('d3', 'M9.5 34h.01')}</g>`,
    },
  };

  // Devuelve el SVG de un icono. Es decorativo: el texto que lo acompaña es lo que lee un lector de pantalla.
  window.motionIcon = function (name, size) {
    const i = ICONS[name];
    if (!i) return '';
    const px = size || (i.vb === 48 ? 56 : 20);
    return `<svg class="mi mi-${name}${i.cls ? ' ' + i.cls : ''}" viewBox="0 0 ${i.vb} ${i.vb}" width="${px}" height="${px}" fill="none" ` +
      `stroke="currentColor" stroke-width="${i.vb === 48 ? 1.75 : 2}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${i.body}</svg>`;
  };

  // Estado vacío: una ilustración que se dibuja una vez al aparecer, el mensaje y, si hace falta, una pista.
  window.emptyState = function (icon, text, hint) {
    const esc = (t) => String(t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    return `<div class="empty-state">${window.motionIcon(icon)}<p>${esc(text)}</p>${hint ? `<p class="muted small">${esc(hint)}</p>` : ''}</div>`;
  };
})();
