// Landing: entradas al hacer scroll, demostración paso a paso, Steve que sigue al cursor e iconos de píxeles.
(function () {
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;

  // 1) Desintegración ligada al scroll. Cada bloque .rise se deshace (ruido + desplazamiento + opacidad)
  //    al salir de pantalla y se reconstruye al entrar. Solo se animan los bloques en transición.
  var items = [].slice.call(document.querySelectorAll('.rise'));
  var NS = 'http://www.w3.org/2000/svg';
  var defs = document.getElementById('dissolve-defs');
  var fx = [];
  var K = 12;  // pendiente de la máscara de ruido (más alto, borde más nítido)

  function makeFilter(i) {
    var f = document.createElementNS(NS, 'filter');
    f.setAttribute('id', 'dz-' + i);
    f.setAttribute('x', '-10%'); f.setAttribute('y', '-10%');
    f.setAttribute('width', '120%'); f.setAttribute('height', '120%');
    f.setAttribute('color-interpolation-filters', 'sRGB');
    var t = document.createElementNS(NS, 'feTurbulence');
    t.setAttribute('type', 'fractalNoise'); t.setAttribute('baseFrequency', '0.6');
    t.setAttribute('numOctaves', '2'); t.setAttribute('seed', String(i + 3)); t.setAttribute('result', 'n');
    var m = document.createElementNS(NS, 'feColorMatrix');
    m.setAttribute('in', 'n'); m.setAttribute('type', 'matrix'); m.setAttribute('result', 'mask');
    var d = document.createElementNS(NS, 'feDisplacementMap');
    d.setAttribute('in', 'SourceGraphic'); d.setAttribute('in2', 'n'); d.setAttribute('scale', '0');
    d.setAttribute('xChannelSelector', 'R'); d.setAttribute('yChannelSelector', 'G'); d.setAttribute('result', 'disp');
    var c = document.createElementNS(NS, 'feComposite');
    c.setAttribute('in', 'disp'); c.setAttribute('in2', 'mask'); c.setAttribute('operator', 'in');
    f.appendChild(t); f.appendChild(m); f.appendChild(d); f.appendChild(c);
    defs.appendChild(f);
    return { t: t, m: m, d: d };
  }

  function clamp01(x) { return x < 0 ? 0 : x > 1 ? 1 : x; }

  function paint(el, p) {
    // p = 1: visible y nítido; p = 0: deshecho y oculto.
    // Fuera de pantalla no queda nada: p = 0 es invisible y deshecho del todo.
    if (p <= 0.001) { el.style.opacity = '0'; el.style.filter = 'none'; return; }
    if (p >= 0.999) { el.style.opacity = '1'; el.style.filter = 'none'; return; }
    var e = p * p * (3 - 2 * p);
    el.style.opacity = String(Math.min(1, e * 1.4));
    var fi = el.__fx || (el.__fx = makeFilter(el.__idx));
    var t = 0.05 + 0.9 * (1 - e);            // umbral del ruido: casi todo se deshace cerca de p = 0
    fi.m.setAttribute('values', '0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  ' + K + ' 0 0 0 ' + (-K * t).toFixed(3));
    fi.d.setAttribute('scale', String(((1 - e) * 110).toFixed(1)));   // desplazamiento fuerte al deshacerse
    fi.t.setAttribute('baseFrequency', (0.45 + 0.5 * (1 - e)).toFixed(3)); // grano más fino al desaparecer
    el.style.filter = 'url(#dz-' + el.__idx + ')';
  }

  function progress(el) {
    var vh = window.innerHeight, r = el.getBoundingClientRect();
    // Zonas amplias: el bloque se deshace durante casi todo su recorrido hacia fuera.
    var entry = (vh * 0.95 - r.top) / (vh * 0.4);    // 0 al pasar el borde inferior, 1 al llegar a 55 %
    var exit = r.bottom / (vh * 0.45);               // 1 con 45 % visible, 0 al salir por arriba
    return clamp01(Math.min(entry, exit));
  }

  if (!defs || !('IntersectionObserver' in window) || reduce) {
    items.forEach(function (el) { el.style.opacity = '1'; });
  } else {
    items.forEach(function (el, i) { el.__idx = i; });
    var queued = false;
    function frame() {
      queued = false;
      items.forEach(function (el) { paint(el, progress(el)); });
    }
    function schedule() { if (!queued) { queued = true; requestAnimationFrame(frame); } }
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule);
    frame();
  }

  // 2) Iconos de píxeles (mismos dibujos que el panel).
  document.querySelectorAll('[data-pixel]').forEach(function (el) {
    el.innerHTML = window.pixelIcon(el.getAttribute('data-pixel'), Number(el.getAttribute('data-size')) || 32);
  });

  // 3) Demostración paso a paso: avanza sola mientras está en pantalla; el usuario puede elegir un paso.
  var demo = document.getElementById('demo');
  if (demo) {
    var tabs = demo.querySelectorAll('.demo-tab');
    var scenes = demo.querySelectorAll('.scene');
    var fill = demo.querySelector('.demo-fill');
    var DURATION = 4200, current = 0, timer = null, visible = false;

    function show(i) {
      current = i;
      tabs.forEach(function (t, k) {
        t.classList.toggle('on', k === i);
        t.setAttribute('aria-selected', k === i ? 'true' : 'false');
      });
      scenes.forEach(function (s, k) {
        s.classList.toggle('on', k === i);
        // cada línea entra con su propio retardo
        s.querySelectorAll('[data-i]').forEach(function (n) { n.classList.remove('in'); });
        if (k === i) {
          requestAnimationFrame(function () {
            s.querySelectorAll('[data-i]').forEach(function (n) { n.classList.add('in'); });
          });
        }
      });
      // la barra de progreso se reinicia y corre durante el paso
      fill.style.transition = 'none';
      fill.style.transform = 'scaleX(0)';
      void fill.offsetWidth;
      if (visible && !reduce) {
        fill.style.transition = 'transform ' + DURATION + 'ms linear';
        fill.style.transform = 'scaleX(1)';
      } else {
        fill.style.transform = 'scaleX(1)';
      }
    }
    function tick() { show((current + 1) % tabs.length); }
    var paused = false, pauseBtn = demo.querySelector('.demo-pause');
    function play() { clearInterval(timer); if (!reduce && !paused) timer = setInterval(tick, DURATION); }
    if (pauseBtn) pauseBtn.addEventListener('click', function () {
      paused = !paused;
      pauseBtn.setAttribute('aria-pressed', paused ? 'true' : 'false');
      pauseBtn.textContent = paused ? 'Reanudar' : 'Pausar';
      pauseBtn.setAttribute('aria-label', paused ? 'Reanudar la demostración' : 'Pausar la demostración');
      if (paused) clearInterval(timer); else play();
    });

    tabs.forEach(function (t, k) {
      t.addEventListener('click', function () { show(k); play(); });
    });
    if (window.IntersectionObserver) {
      new IntersectionObserver(function (es) {
        visible = es[0].isIntersecting;
        if (visible) { show(current); play(); } else { clearInterval(timer); }
      }, { threshold: 0.35 }).observe(demo);
    }
    show(0);
    if (reduce) { scenes.forEach(function (s) { s.classList.add('on'); s.querySelectorAll('[data-i]').forEach(function (n) { n.classList.add('in'); }); }); }
  }

  // 4) Steve: fijo abajo a la izquierda; sus ojos siguen el cursor, como el personaje del inventario.
  var steve = document.getElementById('steve');
  if (steve && !reduce && window.matchMedia('(pointer: fine)').matches) {
    // cabeza 8x8 con sombreado; claves de color: h pelo, s piel, e blanco ojo, i iris, m boca, c camisa
    var PAL = { h: '#4a3322', H: '#34231a', s: '#e0ad84', S: '#c48e66', e: '#f5f7fa', i: '#2f6fb0', m: '#a2573a', t: '#2c2c2c', c: '#3cb6c8', d: '#2a8fa0' };
    var ROWS = [
      'HHHHHHHH',
      'HhhhhhhH',
      'hhhhhhhh',
      'hssssssh',
      'hsssssss',
      'sssssssS',
      'SsssmsSS',
      'SSSSSSSS'
    ];
    // ojos (2x2 en la fila 3–4); las pupilas se desplazan dentro de ellos
    var EYES = [[1, 3], [5, 3]];
    var rects = '';
    ROWS.forEach(function (row, y) {
      [].forEach.call(row, function (c, x) {
        var color = PAL[c] || PAL[c.toLowerCase()];
        if (c === 's' || c === 'S' || c === 'h' || c === 'H') rects += '<rect x="' + x + '" y="' + y + '" width="1" height="1" fill="' + (c === 'h' ? PAL.h : c === 'H' ? PAL.H : c === 'S' ? PAL.S : PAL.s) + '"/>';
        else if (c === 'm') rects += '<rect x="' + x + '" y="' + y + '" width="1" height="1" fill="' + PAL.m + '"/>';
      });
    });
    var eyes = '';
    EYES.forEach(function (e) {
      var x = e[0], y = e[1];
      eyes += '<rect x="' + x + '" y="' + y + '" width="2" height="2" fill="' + PAL.e + '"/>';
    });
    // capa de ojos que se mueve: la pupila (iris 1x1) cambia de posición dentro del blanco del ojo
    var pupils = '<g id="steve-pupils">' + EYES.map(function (e) {
      return '<rect x="' + (e[0] + 0.5) + '" y="' + (e[1] + 0.5) + '" width="1" height="1" fill="' + PAL.i + '"/>';
    }).join('') + '</g>';
    steve.innerHTML =
      '<svg viewBox="0 0 8 8" width="96" height="96" shape-rendering="crispEdges" aria-hidden="true">' +
      rects + eyes + pupils + '</svg>';
    var pupilsEl = document.getElementById('steve-pupils');
    var target = { x: 0, y: 0 }, now = { x: 0, y: 0 }, raf = null;
    function aim(e) {
      var r = steve.getBoundingClientRect();
      var cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      var dx = e.clientX - cx, dy = e.clientY - cy;
      var len = Math.hypot(dx, dy) || 1;
      // máximo desplazamiento: media casilla de píxel dentro del ojo
      target.x = Math.max(-0.5, Math.min(0.5, (dx / len) * 0.5 * Math.min(1, len / 240)));
      target.y = Math.max(-0.5, Math.min(0.5, (dy / len) * 0.5 * Math.min(1, len / 240)));
      if (!raf) raf = requestAnimationFrame(step);
    }
    function step() {
      now.x += (target.x - now.x) * 0.25;
      now.y += (target.y - now.y) * 0.25;
      pupilsEl.setAttribute('transform', 'translate(' + now.x.toFixed(3) + ' ' + now.y.toFixed(3) + ')');
      raf = (Math.abs(target.x - now.x) > 0.01 || Math.abs(target.y - now.y) > 0.01) ? requestAnimationFrame(step) : null;
    }
    window.addEventListener('pointermove', aim, { passive: true });
    // Steve vive en el hero: aparece solo mientras el hero está en pantalla, para no tapar el resto.
    var hero = document.querySelector('.hero');
    if (hero && 'IntersectionObserver' in window) {
      new IntersectionObserver(function (es) {
        steve.classList.toggle('on', es[0].isIntersecting);
      }, { threshold: 0.6 }).observe(hero);  // solo con el hero casi entero a la vista
    } else {
      steve.classList.add('on');
    }
  }
})();
