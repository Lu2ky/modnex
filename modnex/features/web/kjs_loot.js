// KubeJS · Botín: lo que suelta un bloque al romperlo o un mob al morir. El objetivo se ve a la izquierda (el bloque en 3D, o el huevo del
// mob) y sus objetos a la derecha con cantidad y probabilidad. Cada regla reemplaza la tabla entera y se aplica con /reload.
(function () {
  const M = () => window.Modnex;
  const clone = (x) => JSON.parse(JSON.stringify(x));
  const WHEN = { always: 'Siempre', silk: 'Solo con toque de seda', nosilk: 'Solo sin toque de seda' };
  const BONUS = { '': 'Sin bonificación', fortune: 'Con fortuna', looting: 'Con saqueo' };

  function view(el, s) {
    const { api, esc, toast } = M();
    const base = `/api/servers/${encodeURIComponent(s.name)}`;
    let rules = [], kind = 'block', q = '', targets = [], target = null, cur = null, draft = null, pick = null, items = [], iq = '', timer = null, timer2 = null, busy = false;
    const info = {};
    const remember = (l) => l.forEach((i) => { info[i.id] = { name: i.name, icon: i.icon }; });
    const nameOf = (id) => (info[id] && info[id].name) || id;
    const icon = (id, cls) => (info[id] && info[id].icon ? `<img class="${cls || 'kjs-ico'}" data-iid="${esc(id)}" src="${esc(info[id].icon)}" alt="">` : `<span class="${cls || 'kjs-ico'} kjs-ph" aria-hidden="true">${esc((id || '?').split(':').pop().charAt(0).toUpperCase())}</span>`);
    const slug = (t) => t.split(':').pop().replace(/[^a-z0-9_]/g, '_').slice(0, 30);
    const pct = (c) => `${Math.round(c * 1000) / 10}%`;

    async function load() {
      try { rules = (await api(`${base}/kubejs_loot`)).rules; } catch (e) { el.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
      await Promise.all([...new Set(rules.flatMap((r) => [r.target, ...r.drops.map((d) => d.item)]))].slice(0, 40).map(async (id) => {
        try { remember((await api(`${base}/kubejs_items?q=${encodeURIComponent(id)}&limit=20`)).items); } catch (e) { /* sin icono */ }
      }));
      await searchTargets(); draw();
    }
    async function searchTargets() {
      try { targets = (await api(`${base}/kubejs_loot_targets?kind=${kind}&q=${encodeURIComponent(q)}`)).targets; targets.forEach((t) => { info[t.id] = { name: t.name, icon: t.icon }; }); } catch (e) { toast(e.message, 'error'); }
      drawTargets();
    }
    async function searchItems() {
      try { items = (await api(`${base}/kubejs_items?q=${encodeURIComponent(iq)}&limit=120`)).items; remember(items); } catch (e) { toast(e.message, 'error'); }
      drawItems();
    }
    async function choose(id) {
      target = id; pick = null;
      try { cur = await api(`${base}/kubejs_loot_current?kind=${kind}&target=${encodeURIComponent(id)}`); } catch (e) { toast(e.message, 'error'); return; }
      await Promise.all(cur.drops.filter((d) => !d.item.startsWith('#') && d.item !== '?' && !info[d.item]).slice(0, 30).map(async (d) => {
        try { remember((await api(`${base}/kubejs_items?q=${encodeURIComponent(d.item)}&limit=20`)).items); } catch (e) { /* sin icono */ }
      }));
      draft = cur.rule ? clone(cur.rule) : { id: slug(id), kind, target: id, drops: [], survives: kind === 'block' };
      draw();
    }

    // ---------- escena ----------
    const dropLabel = (d) => [nameOf(d.item), d.min === d.max ? `×${d.min}` : `${d.min}–${d.max}`, d.chance ? pct(d.chance) : '', d.bonus ? BONUS[d.bonus] : '', d.when && d.when !== 'always' ? WHEN[d.when] : '', d.player ? 'solo si lo mata un jugador' : ''].filter(Boolean).join(', ');
    function slot(d, i, ro) {
      const badge = d.min === d.max ? (d.min > 1 ? `<span class="cr-badge">${d.min}</span>` : '') : `<span class="cr-badge">${d.min}–${d.max}</span>`;
      const ch = d.chance ? `<span class="cr-chance">${pct(d.chance)}</span>` : '';
      const tags = [d.when === 'silk' ? '⛏' : d.when === 'nosilk' ? '⌀' : '', d.bonus === 'fortune' ? '✦' : d.bonus === 'looting' ? '⚔' : '', d.player ? '☠' : ''].filter(Boolean).join('');
      const tag = tags ? `<span class="cr-tagline">${tags}</span>` : '';
      const inner = d.item && d.item !== '?' ? (d.item.startsWith('#') ? '<span class="cr-tagmark">#</span>' : icon(d.item)) : '';
      return ro ? `<span class="cr-slot" role="img" aria-label="${esc(dropLabel(d))}" title="${esc(dropLabel(d))}">${inner}${badge}${ch}${tag}</span>`
        : `<button type="button" class="cr-slot ${pick === i ? 'on' : ''}" data-pick="${i}" aria-label="${esc(d.item ? dropLabel(d) : 'objeto vacío')}" title="${esc(d.item ? dropLabel(d) : 'objeto vacío')}">${inner}${badge}${ch}${tag}</button>`;
    }
    function targetVisual(id) {
      return info[id] && info[id].icon ? `<img class="cr-machine" data-iid="${esc(id)}" src="${esc(info[id].icon)}" alt="" title="${esc(nameOf(id))}">` : `<span class="cr-machine kjs-ph">${esc(id.split(':').pop().charAt(0).toUpperCase())}</span>`;
    }
    function scene(d, ro) {
      const slots = d.drops.length ? d.drops.map((x, i) => slot(x, i, ro)).join('') : '<span class="cr-meta"><span>No suelta nada</span></span>';
      return `<div class="cr-scene"><div class="cr-panel"><span class="cr-title">Botín de ${esc(nameOf(d.target))}</span>
        <div class="cr-body"><div class="cr-mid">${targetVisual(d.target)}<div class="cr-meta"><span>${d.kind === 'block' ? 'Al romperlo' : 'Al morir'}</span></div></div><span class="cr-arrow" aria-hidden="true"></span>
        <div class="cr-col">${slots}${ro ? '' : '<div class="cr-add"><button type="button" data-add="1">+ Objeto</button></div>'}</div></div></div></div>`;
    }

    // ---------- pantalla ----------
    function rows() {
      return draft.drops.map((d, i) => `<li class="cr-droprow ${pick === i ? 'on' : ''}"><button type="button" class="kjs-slot" data-pick="${i}" aria-label="Elegir objeto">${d.item ? icon(d.item) : '<span class="kjs-empty"></span>'}</button>
        <span class="cr-dn">${d.item ? esc(nameOf(d.item)) : '<span class="muted">Elige un objeto de la lista</span>'}</span>
        <label class="kjs-field small">Mín.<input type="number" min="0" max="64" data-f="${i}.min" value="${d.min}"></label>
        <label class="kjs-field small">Máx.<input type="number" min="0" max="64" data-f="${i}.max" value="${d.max}"></label>
        <label class="kjs-field small">Prob. (%)<input type="number" min="0.1" max="99.9" step="any" data-f="${i}.chance" value="${d.chance ? Math.round(d.chance * 1000) / 10 : ''}" placeholder="100"></label>
        <label class="kjs-field small">Bonificación<select data-f="${i}.bonus" data-redraw="1">${Object.entries(BONUS).filter(([k]) => !k || (k === 'fortune') === (draft.kind === 'block')).map(([k, l]) => `<option value="${k}" ${(d.bonus || '') === k ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
        ${draft.kind === 'block' ? `<label class="kjs-field small">Cuándo<select data-f="${i}.when" data-redraw="1">${Object.entries(WHEN).map(([k, l]) => `<option value="${k}" ${(d.when || 'always') === k ? 'selected' : ''}>${l}</option>`).join('')}</select></label>`
          : `<label class="kjs-check"><input type="checkbox" data-f="${i}.player" data-redraw="1" ${d.player ? 'checked' : ''}> Solo si lo mata un jugador</label>`}
        <button type="button" class="btn sm danger" data-rm="${i}">Quitar</button></li>`).join('');
    }
    function draw() {
      const list = rules.map((r, i) => `<button class="cr-card ${draft && draft.target === r.target && draft.kind === r.kind ? 'on' : ''}" data-open="${i}">${icon(r.target, 'kjs-ico big')}<span class="t"><strong>${esc(nameOf(r.target))}</strong>
        <span class="muted small">${r.kind === 'block' ? 'Bloque' : 'Mob'} · ${r.drops.length} ${r.drops.length === 1 ? 'objeto' : 'objetos'}</span></span></button>`).join('');
      const today = cur && cur.exists ? `<div class="cr-today"><h3>Lo que suelta hoy</h3>${cur.drops.length ? `<div class="cr-scene sm"><div class="cr-panel"><div class="cr-col">${cur.drops.map((d, i) => slot(d, i, true)).join('')}</div></div></div>` : '<p class="muted small">No suelta nada.</p>'}
        ${cur.complex ? '<p class="muted small">Algunos objetos dependen de condiciones que el panel no puede reproducir (tijeras, estado del bloque, cocinado al arder…). Si reemplazas la tabla, esas condiciones se pierden.</p>' : ''}
        <button type="button" class="btn sm" data-act="import" ${cur.drops.length ? '' : 'disabled'}>Usar como punto de partida</button></div>` : '';
      el.innerHTML = `<div class="ft-head"><h2>Botín</h2><span class="muted small">${rules.length} ${rules.length === 1 ? 'regla' : 'reglas'}</span></div>
        <p class="muted small">Cambia lo que suelta un bloque al romperlo o un mob al morir. Cada regla reemplaza la tabla entera. Se aplica con <code>/reload</code>; puede ser lo que dejes sin objetos para que no suelte nada.</p>
        ${list ? `<div class="cr-list">${list}</div>` : ''}
        <div class="cr-kinds" role="group" aria-label="Qué quieres cambiar"><button type="button" class="${kind === 'block' ? 'on' : ''}" data-kind="block">Bloques</button><button type="button" class="${kind === 'entity' ? 'on' : ''}" data-kind="entity">Mobs</button></div>
        <input class="kjs-search" data-tsearch type="search" placeholder="${kind === 'block' ? 'Buscar un bloque (ej. diamond, stone)' : 'Buscar un mob (ej. zombie, cow)'}" value="${esc(q)}" aria-label="Buscar">
        <div class="kjs-browser" data-targets aria-live="polite"></div>
        ${draft ? `<div class="kjs-editor">${scene(draft, false)}${today}
          <ul class="cr-drops">${rows()}</ul>
          ${draft.kind === 'block' ? `<label class="kjs-check"><input type="checkbox" data-f="survives" data-redraw="1" ${draft.survives ? 'checked' : ''}> Las explosiones pueden destruir los objetos (como en el juego)</label>` : ''}
          ${pick != null ? '<div class="kjs-browser-wrap"><input class="kjs-search" data-isearch type="search" placeholder="Buscar el objeto por nombre o id" aria-label="Buscar objeto"><div class="kjs-browser" data-items aria-live="polite"></div></div>' : ''}
          <div class="ft-actions"><button class="btn" data-act="cancel">Cancelar</button><button class="btn primary" data-act="save" ${busy ? 'disabled' : ''}>Guardar regla</button>
            ${cur && cur.rule ? '<button class="btn danger" data-act="delete">Volver al botín original</button>' : ''}</div></div>` : ''}`;
      drawTargets(); drawItems();
    }
    function drawTargets() {
      const box = el.querySelector('[data-targets]'); if (!box) return;
      box.innerHTML = targets.length ? targets.map((t) => `<button type="button" class="kjs-item ${target === t.id ? 'on' : ''}" data-target="${esc(t.id)}" title="${esc(t.id)}">${icon(t.id, 'kjs-ico sm')}<span class="kjs-item-t">${esc(t.name)}<span class="muted small block">${esc(t.id)}</span></span></button>`).join('') : '<p class="muted small">Ninguno coincide.</p>';
    }
    function drawItems() {
      const box = el.querySelector('[data-items]'); if (!box) return;
      box.innerHTML = items.length ? items.map((it) => `<button type="button" class="kjs-item" data-id="${esc(it.id)}" title="${esc(it.id)}">${icon(it.id, 'kjs-ico sm')}<span class="kjs-item-t">${esc(it.name)}<span class="muted small block">${esc(it.id)}</span></span></button>`).join('') : '<p class="muted small">Escribe para buscar.</p>';
    }

    el.oninput = (e) => {
      const t = e.target;
      if (t.matches('[data-tsearch]')) { q = t.value; clearTimeout(timer); timer = setTimeout(searchTargets, 180); return; }
      if (t.matches('[data-isearch]')) { iq = t.value; clearTimeout(timer2); timer2 = setTimeout(searchItems, 160); return; }
      if (!t.dataset.f || t.dataset.redraw || !draft) return;
      const [i, k] = t.dataset.f.split('.'), d = draft.drops[Number(i)];
      if (!d) return;
      if (k === 'chance') { const v = Number(t.value); d.chance = t.value && v > 0 && v < 100 ? Math.round(v * 10) / 1000 : undefined; }
      else d[k] = Number(t.value) || 0;
    };
    el.onchange = (e) => {
      const t = e.target;
      if (!t.dataset.f || !t.dataset.redraw || !draft) return;
      const v = t.type === 'checkbox' ? t.checked : t.value;
      if (t.dataset.f === 'survives') draft.survives = v;
      else { const [i, k] = t.dataset.f.split('.'), d = draft.drops[Number(i)]; if (k === 'bonus' || k === 'when') { if (v && v !== 'always') d[k] = v; else delete d[k]; } else if (v) d[k] = true; else delete d[k]; }
      draw();
    };
    el.onclick = async (e) => {
      const b = e.target.closest('button'); if (!b || b.disabled) return;
      const d = b.dataset;
      if (d.kind) { kind = d.kind; q = ''; target = null; cur = null; draft = null; pick = null; await searchTargets(); return draw(); }
      if (d.target) return choose(d.target);
      if (d.open != null) { const r = rules[Number(d.open)]; kind = r.kind; await searchTargets(); return choose(r.target); }
      if (d.add) { draft.drops.push({ item: '', min: 1, max: 1 }); pick = draft.drops.length - 1; if (!items.length) await searchItems(); return draw(); }
      if (d.pick != null) { pick = pick === Number(d.pick) ? null : Number(d.pick); if (pick != null && !items.length) await searchItems(); return draw(); }
      if (d.rm != null) { draft.drops.splice(Number(d.rm), 1); pick = null; return draw(); }
      if (d.id && pick != null) { draft.drops[pick].item = d.id; pick = null; return draw(); }
      if (d.act === 'import') { draft.drops = cur.drops.filter((x) => x.item !== '?' && !x.item.startsWith('#')).map(({ complex, ...rest }) => rest); pick = null; return draw(); }
      if (d.act === 'cancel') { draft = null; target = null; cur = null; pick = null; return draw(); }
      if (d.act === 'save' || d.act === 'delete') {
        const next = d.act === 'delete' ? rules.filter((r) => !(r.kind === draft.kind && r.target === draft.target))
          : [...rules.filter((r) => !(r.kind === draft.kind && r.target === draft.target)), { ...draft, drops: draft.drops.filter((x) => x.item) }];
        if (d.act === 'delete' && !window.confirm('¿Volver al botín original? Se borra el archivo de esta regla.')) return;
        busy = true;
        try { rules = (await api(`${base}/kubejs_loot_save`, { method: 'POST', body: { rules: next } })).rules; toast(d.act === 'delete' ? 'Vuelve el botín original al hacer /reload' : 'Regla guardada. Aplícala con /reload.', 'success'); draft = null; target = null; cur = null; pick = null; }
        catch (err) { toast(err.message, 'error'); }
        busy = false; draw();
      }
    };
    load();
  }

  window.ModnexKjsLoot = { view };
})();
