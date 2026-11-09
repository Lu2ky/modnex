// Landing: entradas al hacer scroll, demostración paso a paso, Steve que sigue al cursor e iconos de píxeles.
(function () {
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;

  // 1) Aparición al hacer scroll. Cada bloque .rise entra una sola vez, cuando llega a la pantalla.
  //    Lo que ya está visible al cargar aparece de inmediato, sin animación.
  var items = document.querySelectorAll('.rise');
  var vh = window.innerHeight;
  if (!('IntersectionObserver' in window) || reduce) {
    items.forEach(function (el) { el.classList.add('in'); });
  } else {
    items.forEach(function (el) {
      if (el.getBoundingClientRect().top < vh) { el.classList.add('in', 'still'); }
    });
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
      });
    }, { threshold: 0.15 });
    items.forEach(function (el) { if (!el.classList.contains('in')) io.observe(el); });
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

// Clic de Minecraft: el sonido random/click del juego al pulsar botones y controles.
(function () {
  var reduceSound = false;
  document.addEventListener('click', function (e) {
    var t = e.target && e.target.closest ? e.target.closest('a, button, summary, .btn, .demo-tab') : null;
    if (!t || reduceSound) return;
    if (t.matches('a[href="/app"]')) return;  // ese clic lo gestiona el sonido de portal
    var a = new Audio('/assets/sounds/click.ogg');
    a.volume = 0.6;
    a.play().catch(function () { /* el navegador puede bloquear audio sin gesto previo */ });
  }, true);
})();

// Galerías: cada tarjeta pasa a la siguiente captura al hacer clic o con teclado (Enter, Espacio, flechas).
(function () {
  document.querySelectorAll('[data-gallery]').forEach(function (g) {
    var card = g.querySelector('.gallery-card');
    var slides = g.querySelectorAll('.gallery-slide');
    var dots = g.querySelectorAll('.gallery-dot');
    var count = g.querySelector('.gallery-count');
    var total = slides.length, idx = 0;
    function show(i) {
      idx = (i + total) % total;
      slides.forEach(function (s, k) { s.classList.toggle('on', k === idx); });
      dots.forEach(function (d, k) { d.classList.toggle('on', k === idx); });
      if (count) count.textContent = (idx + 1) + ' / ' + total;
    }
    card.addEventListener('click', function () { show(idx + 1); });
    card.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); show(idx + 1); }
      if (e.key === 'ArrowRight') { e.preventDefault(); show(idx + 1); }
      if (e.key === 'ArrowLeft') { e.preventDefault(); show(idx - 1); }
    });
    dots.forEach(function (d) {
      d.addEventListener('click', function () { show(Number(d.getAttribute('data-go'))); });
    });
  });
})();

// Entrar al panel: sonido y overlay del portal del Nether durante exactamente la duración del sonido;
// la navegación se hace al terminar.
(function () {
  var reduceMotion = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var portal = new Audio('/assets/sounds/portal-enter.ogg');
  portal.preload = 'auto';
  portal.volume = 0.7;
  var veil = document.createElement('div');
  veil.className = 'portal-veil';
  veil.setAttribute('aria-hidden', 'true');
  document.body.appendChild(veil);
  var busy = false;
  document.addEventListener('click', function (e) {
    var a = e.target && e.target.closest ? e.target.closest('a[href="/app"]') : null;
    if (!a || busy || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    busy = true;
    var secs = (isFinite(portal.duration) && portal.duration > 0) ? portal.duration : 2.85;
    portal.currentTime = 0;
    portal.play().catch(function () { /* sin audio: se entra igual */ });
    if (!reduceMotion) veil.classList.add('on');
    setTimeout(function () { location.href = '/app'; }, Math.round(secs * 1000));
  }, true);
})();
