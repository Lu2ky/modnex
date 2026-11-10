// Landing: entradas al hacer scroll, demostración paso a paso, mascota que sigue al cursor e iconos de píxeles.
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

  // 4) Mascota: fija abajo a la derecha; sus ojos siguen el cursor.
  var mascot = document.getElementById('mascot');
  if (mascot && !reduce && window.matchMedia('(pointer: fine)').matches) {
    // mascota 8x8: orejas de gato, pelo violeta, mejillas rosadas. Claves: v/V pelo, p/P piel, b mejilla, m boca
    var PAL = { v: '#7c5cd6', V: '#5a3fb0', p: '#f1c9a8', P: '#d9a982', b: '#f08a9a', m: '#b04a5a', e: '#ffffff', i: '#262645' };
    var ROWS = [
      'vV....Vv',
      'vvvvvvvv',
      'vvvvvvvv',
      'pvpppvpp',
      'pppppppp',
      'pbppppbp',
      'ppppmppp',
      'pPPPPPPp'
    ];
    // ojos (2x2 en las filas 3–4); las pupilas se desplazan dentro de ellos
    var EYES = [[1, 3], [5, 3]];
    var rects = '';
    ROWS.forEach(function (row, y) {
      [].forEach.call(row, function (c, x) {
        if (c === '.' || !PAL[c]) return;
        rects += '<rect x="' + x + '" y="' + y + '" width="1" height="1" fill="' + PAL[c] + '"/>';
      });
    });
    var eyes = '';
    EYES.forEach(function (e) {
      var x = e[0], y = e[1];
      eyes += '<rect x="' + x + '" y="' + y + '" width="2" height="2" fill="' + PAL.e + '"/>';
    });
    // capa de ojos que se mueve: la pupila (iris 1x1) cambia de posición dentro del blanco del ojo
    var pupils = '<g id="mascot-pupils">' + EYES.map(function (e) {
      return '<rect x="' + (e[0] + 0.5) + '" y="' + (e[1] + 0.5) + '" width="1" height="1" fill="' + PAL.i + '"/>';
    }).join('') + '</g>';
    mascot.innerHTML =
      '<svg viewBox="0 0 8 8" width="96" height="96" shape-rendering="crispEdges" aria-hidden="true">' +
      rects + eyes + pupils + '</svg>';
    var pupilsEl = document.getElementById('mascot-pupils');
    // Cada eje es un resorte propio con amortiguación 1.0 (sin rebote) y respuesta 0.25 s. Se resuelve con la solución
    // exacta del resorte crítico, x(t) = obj + (A + B·t)·e^(−ω·t): es estable con cualquier dt, arrastra la velocidad y no
    // depende de los fotogramas por segundo (antes cada fotograma recorría un 25 % y en 120 Hz iba el doble de rápido).
    var W = (2 * Math.PI) / 0.25;
    var target = { x: 0, y: 0 }, now = { x: 0, y: 0 }, vel = { x: 0, y: 0 }, raf = null, last = 0;
    function aim(e) {
      var r = mascot.getBoundingClientRect();
      var cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      var dx = e.clientX - cx, dy = e.clientY - cy;
      var len = Math.hypot(dx, dy) || 1;
      // máximo desplazamiento: media casilla de píxel dentro del ojo
      target.x = Math.max(-0.5, Math.min(0.5, (dx / len) * 0.5 * Math.min(1, len / 240)));
      target.y = Math.max(-0.5, Math.min(0.5, (dy / len) * 0.5 * Math.min(1, len / 240)));
      if (!raf) { last = 0; raf = requestAnimationFrame(step); }
    }
    function spring(axis, dt) {
      var A = now[axis] - target[axis], B = vel[axis] + W * A, e = Math.exp(-W * dt);
      now[axis] = target[axis] + (A + B * dt) * e;
      vel[axis] = (B - W * (A + B * dt)) * e;
    }
    function step(t) {
      var dt = last ? Math.min((t - last) / 1000, 0.1) : 1 / 60;
      last = t;
      spring('x', dt); spring('y', dt);
      pupilsEl.setAttribute('transform', 'translate(' + now.x.toFixed(3) + ' ' + now.y.toFixed(3) + ')');
      var moving = Math.abs(target.x - now.x) > 0.002 || Math.abs(target.y - now.y) > 0.002 || Math.abs(vel.x) > 0.01 || Math.abs(vel.y) > 0.01;
      raf = moving ? requestAnimationFrame(step) : null;
    }
    window.addEventListener('pointermove', aim, { passive: true });
    // La mascota vive en el hero: aparece solo mientras el hero está en pantalla, para no tapar el resto.
    var hero = document.querySelector('.hero');
    if (hero && 'IntersectionObserver' in window) {
      new IntersectionObserver(function (es) {
        mascot.classList.toggle('on', es[0].isIntersecting);
      }, { threshold: 0.6 }).observe(hero);  // solo con el hero casi entero a la vista
    } else {
      mascot.classList.add('on');
    }
  }
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
