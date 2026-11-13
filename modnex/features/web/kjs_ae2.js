// KubeJS · Applied Energistics 2: recetas de inscriptor, cargador, transformación (agua y cristales) y manipulador de entropía,
// con formularios. Las máquinas se dibujan en 3D; los ingredientes se eligen de la lista de items del servidor o de sus tags.
(function () {
  const M = () => window.Modnex;
  const clone = (x) => JSON.parse(JSON.stringify(x));
  const MODE_LABEL = { inscribe: 'Inscribir (arriba y centro)', press: 'Prensar (arriba, centro y abajo)' };
  const ENTROPY_LABEL = { heat: 'Calentar (bloque → bloque o fluido)', cool: 'Enfriar (fluido → bloque)' };
  const CIRC_LABEL = { none: 'Sin condición', explosion: 'En una explosión' };
  const PIXEL = 'data:image/gif;base64,R0lGODlhAQABAAAAACwAAAAAAQABAAACAkQBADs=';

  function view(el, s) {
    const { api, esc, toast, askConfirm } = M();
    const base = `/api/servers/${encodeURIComponent(s.name)}`;
    let data = null, recipes = [], draft = null, editing = null, pick = null, q = '', items = [], info = {}, busy = false, timer = null;

    const label = (id) => (info[id] && info[id].name) || id;
    const icon = (id, cls, mode) => {
      const i = info[id];
      if (i && i.icon) return `<img class="${cls || 'kjs-ico'}" data-iid="${esc(id)}" src="${esc(i.icon)}" alt="">`;
      return `<span class="${cls || 'kjs-ico'} kjs-ph" aria-hidden="true">${esc((id || '?').split(':').pop().charAt(0).toUpperCase())}</span>`;
    };
    const remember = (list) => list.forEach((i) => { info[i.id] = { name: i.name, icon: i.icon }; });
    const machineOf = (type) => (data && data.types[type] ? data.types[type].machine : 'ae2:inscriber');
    const machineImg = (type) => `<img class="cr-machine" data-iid="${esc(machineOf(type))}" src="${PIXEL}" alt="" title="${esc(data.types[type].label)}">`;

    async function ensureInfo(ids) {
      const need = [...new Set(ids.filter(Boolean))].filter((id) => !info[id] && !id.startsWith('#'));
      await Promise.all(need.slice(0, 40).map(async (id) => { try { remember((await api(`${base}/kubejs_items?q=${encodeURIComponent(id)}&limit=20`)).items); } catch (e) { /* sin icono */ } }));
    }
    const idsOf = (r) => r.type === 'inscriber' ? Object.values(r.ingredients).map((i) => i.id).concat([r.result.id])
      : r.type === 'charger' ? [r.ingredient.id, r.result.id] : r.type === 'transform' ? r.ingredients.map((i) => i.id).concat([r.result.id])
      : [r.input.id, r.output.id];

    async function load() {
      try { const d = await api(`${base}/kubejs_appeng`); data = d; recipes = d.recipes; } catch (e) { el.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
      await ensureInfo(recipes.flatMap(idsOf)); draw();
    }

    function blank(type) {
      const d = { id: '', type, mode: type === 'inscriber' ? 'inscribe' : type === 'entropy' ? 'heat' : undefined, ingredients: {}, ingredient: null,
        ingredients_list: null, circumstance: 'none', result: { id: '', count: 1 }, input: { k: 'block', id: '' }, output: { k: 'block', id: '' } };
      if (type === 'transform') d.ingredients_list = [{ k: 'item', id: '' }, { k: 'item', id: '' }];
      return d;
    }
    function toForm(r) {
      const d = clone(r);
      if (r.type === 'transform') d.ingredients_list = clone(r.ingredients);
      if (r.type === 'inscriber') d.ingredients = clone(r.ingredients);
      return d;
    }
    function toRecipe(d) {
      if (d.type === 'inscriber') {
        const ing = {};
        ['top', 'middle', 'bottom'].forEach((k) => { if (d.ingredients[k] && d.ingredients[k].id && (k !== 'bottom' || d.mode === 'press')) ing[k] = d.ingredients[k]; });
        return { id: d.id, type: 'inscriber', mode: d.mode, ingredients: ing, result: d.result };
      }
      if (d.type === 'charger') return { id: d.id, type: 'charger', ingredient: d.ingredient, result: d.result };
      if (d.type === 'transform') return { id: d.id, type: 'transform', ingredients: d.ingredients_list.filter((i) => i.id), circumstance: d.circumstance, result: d.result };
      return { id: d.id, type: 'entropy', mode: d.mode, input: d.input, output: d.output };
    }

    // ---------- piezas ----------
    function slotBtn(key, ing, text) {
      const shown = ing && ing.id ? `${icon(ing.id, 'kjs-ico sm')}<span class="kjs-item-t">${esc(ing.k === 'tag' || ing.id.startsWith('#') ? '#' + ing.id.replace(/^#/, '') : label(ing.id))}<span class="muted small block">${esc(ing.id)}</span></span>` : `<span class="muted">${esc(text || 'Elige')}</span>`;
      return `<button type="button" class="cr-slot-pick ${pick === key ? 'on' : ''}" data-pick="${esc(key)}" aria-label="${esc(text || 'Elegir')}">${shown}</button>`;
    }
    function rowsFor() {
      if (!draft) return '';
      if (draft.type === 'inscriber') {
        const bottom = draft.mode === 'press';
        return `<div class="ae2-slots">${slotBtn('top', draft.ingredients.top, 'Arriba')}${slotBtn('middle', draft.ingredients.middle, 'Centro')}${bottom ? slotBtn('bottom', draft.ingredients.bottom, 'Abajo') : ''}${slotBtn('result', draft.result, 'Resultado')}</div>`;
      }
      if (draft.type === 'charger') return `<div class="ae2-slots">${slotBtn('ingredient', draft.ingredient, 'Ingrediente')}${slotBtn('result', draft.result, 'Resultado')}</div>`;
      if (draft.type === 'transform') return `<div class="ae2-slots">${draft.ingredients_list.map((i, n) => slotBtn('t' + n, i, `Ingrediente ${n + 1}`)).join('')}${slotBtn('result', draft.result, 'Resultado')}</div>
        <div class="ae2-row"><button type="button" class="btn sm" data-addt="1" ${draft.ingredients_list.length >= 9 ? 'disabled' : ''}>+ Ingrediente</button>
        ${draft.ingredients_list.length > 2 ? '<button type="button" class="btn sm danger" data-rmt="1">Quitar el último</button>' : ''}</div>`;
      const side = (k, lab) => `<div class="ae2-side"><span class="muted small">${lab}</span>
        <select data-ek="${k}"><option value="block" ${draft[k].k === 'block' ? 'selected' : ''}>Bloque</option><option value="fluid" ${draft[k].k === 'fluid' ? 'selected' : ''}>Fluido</option></select>
        ${slotBtn(k, draft[k], lab)}</div>`;
      return `<div class="ae2-slots ae2-ent">${side('input', 'Entrada')}<span class="cr-arrow" aria-hidden="true"></span>${side('output', 'Salida')}</div>`;
    }

    function formHTML() {
      const t = data.types[draft.type];
      const head = `<div class="ae2-head">${machineImg(draft.type)}<div><strong>${esc(t.label)}</strong></div></div>`;
      let body = '';
      if (draft.type === 'inscriber') body = `<label class="kjs-field">Modo<select data-f="mode" data-redraw="1">${Object.entries(MODE_LABEL).map(([k, l]) => `<option value="${k}" ${draft.mode === k ? 'selected' : ''}>${l}</option>`).join('')}</select></label>`;
      if (draft.type === 'entropy') body = `<label class="kjs-field">Modo<select data-f="mode" data-redraw="1">${Object.entries(ENTROPY_LABEL).map(([k, l]) => `<option value="${k}" ${draft.mode === k ? 'selected' : ''}>${l}</option>`).join('')}</select></label>`;
      if (draft.type === 'transform') body = `<label class="kjs-field">Condición<select data-f="circumstance" data-redraw="1">${Object.entries(CIRC_LABEL).map(([k, l]) => `<option value="${k}" ${draft.circumstance === k ? 'selected' : ''}>${l}</option>`).join('')}</select></label>`;
      const count = draft.type === 'entropy' ? '' : `<label class="kjs-field small">Cantidad del resultado<input type="number" min="1" max="64" data-f="result-count" value="${draft.result.count || 1}"></label>`;
      const picker = pick ? `<div class="kjs-browser-wrap"><div class="ae2-pickbar"><input class="kjs-search" data-isearch type="search" placeholder="Busca un item (ej. quartz, iron_ingot)" value="${esc(q)}" aria-label="Buscar item">
        <button type="button" class="btn sm" data-tag="1" title="Usar un tag (#namespace:ruta)">Usar tag…</button></div><div class="kjs-browser" data-items aria-live="polite"></div></div>` : '';
      return `${head}${body}${rowsFor()}${count}${picker}`;
    }

    function drawItems() {
      const box = el.querySelector('[data-items]'); if (!box) return;
      box.innerHTML = items.length ? items.map((it) => `<button type="button" class="kjs-item" data-id="${esc(it.id)}" title="${esc(it.id)}">${icon(it.id, 'kjs-ico sm')}<span class="kjs-item-t">${esc(it.name)}<span class="muted small block">${esc(it.id)}</span></span></button>`).join('') : '<p class="muted small">Escribe para buscar.</p>';
    }
    async function searchItems() {
      try {
        if (draft && draft.type === 'entropy' && (pick === 'input' || pick === 'output') && draft[pick].k === 'fluid') {
          const words = q.toLowerCase().split(/\s+/).filter(Boolean);
          items = ((await api(`${base}/kubejs_fluids`)).fluids || []).filter((f) => words.every((w) => (f.id + ' ' + f.name).toLowerCase().includes(w)));
          items.forEach((f) => { info[f.id] = { name: f.name, icon: f.icon }; });
        } else { items = (await api(`${base}/kubejs_items?q=${encodeURIComponent(q)}&limit=80`)).items; remember(items); }
      } catch (e) { toast(e.message, 'error'); }
      drawItems();
    }

    function draw() {
      const list = recipes.length ? `<ul class="ae2-list">${recipes.map((r, i) => `<li class="cr-card-row"><button type="button" class="cr-card ${editing === i ? 'on' : ''}" data-open="${i}">${data.types[r.type] ? `<img class="cr-machine" data-iid="${esc(machineOf(r.type))}" src="${PIXEL}" alt="">` : ''}
        <span class="t"><strong>${esc(r.id)}</strong><span class="muted small">${esc(data.types[r.type] ? data.types[r.type].label : r.type)} → ${esc(label(r.result ? r.result.id : r.output.id))}</span></span></button></li>`).join('')}</ul>`
        : '<p class="muted">Todavía no hay recetas de AE2. Crea una con el botón de abajo.</p>';
      const types = Object.entries(data.types).map(([k, t]) => `<button type="button" class="btn sm" data-new="${k}">${esc(t.label)}</button>`).join('');
      el.innerHTML = `<div class="ft-head"><h2>Applied Energistics 2</h2><span class="muted small">${recipes.length} ${recipes.length === 1 ? 'receta' : 'recetas'}</span></div>
        <p class="muted small">Recetas de las máquinas de AE2 con formulario. Se guardan en el servidor y se aplican con <code>/reload</code>. Las de la celda de almacenamiento y el matter cannon no se editan aquí.</p>
        ${list}
        ${draft ? `<div class="kjs-editor ae2-editor"><label class="kjs-field">Nombre de la receta<input data-f="id" value="${esc(draft.id)}" placeholder="ej. procesador_calculo"></label>
          ${formHTML()}
          <div class="ft-actions"><button class="btn" data-act="cancel">Cancelar</button><button class="btn primary" data-act="save" ${busy ? 'disabled' : ''}>Guardar receta</button>
          ${editing != null ? '<button class="btn danger" data-act="delete">Borrar receta</button>' : ''}</div></div>`
          : `<div class="ae2-new"><span class="muted small">Nueva receta:</span> ${types}</div>`}`;
      drawItems();
    }

    el.oninput = (e) => {
      const t = e.target;
      if (t.matches('[data-isearch]')) { q = t.value; clearTimeout(timer); timer = setTimeout(searchItems, 160); return; }
      if (t.matches('[data-f=id]') && draft) draft.id = t.value.trim();
      if (t.matches('[data-f=result-count]') && draft) draft.result.count = Math.min(64, Math.max(1, Number(t.value) || 1));
    };
    el.onchange = (e) => {
      const t = e.target; if (!draft) return;
      if (t.matches('[data-ek]')) { draft[t.dataset.ek] = { k: t.value, id: '' }; pick = null; return draw(); }
      if (t.dataset.f && t.dataset.redraw) { draft[t.dataset.f] = t.value; if (t.dataset.f === 'mode' && draft.type === 'inscriber' && draft.mode === 'inscribe') delete draft.ingredients.bottom; pick = null; return draw(); }
      if (t.dataset.f === 'circumstance') draft.circumstance = t.value;
      if (t.dataset.f === 'result-count') draft.result.count = Math.min(64, Math.max(1, Number(t.value) || 1));
    };

    el.onclick = async (e) => {
      const b = e.target.closest('button'); if (!b || b.disabled) return;
      const d = b.dataset;
      if (d.new) { draft = blank(d.new); editing = null; pick = null; q = ''; return draw(); }
      if (d.open != null) { const r = recipes[Number(d.open)]; editing = Number(d.open); draft = toForm(r); pick = null; await ensureInfo(idsOf(r)); return draw(); }
      if (d.act === 'cancel') { draft = null; editing = null; pick = null; return draw(); }
      if (d.addt) { draft.ingredients_list.push({ k: 'item', id: '' }); return draw(); }
      if (d.rmt) { draft.ingredients_list.pop(); return draw(); }
      if (d.tag) {
        const v = window.prompt('Tag (ej. c:dusts/certus_quartz, sin #):', '');
        if (!v || !/^[a-z0-9_.-]+:[a-z0-9_./-]+$/.test(v.trim())) return v ? toast('Tag no válido', 'error') : null;
        setPicked({ k: 'tag', id: v.trim() }); return;
      }
      if (d.pick != null) {
        pick = pick === d.pick ? null : d.pick; q = ''; items = [];
        if (pick) await searchItems();
        return draw();
      }
      if (d.id !== undefined && pick != null && b.classList.contains('kjs-item')) return setPicked({ k: 'item', id: d.id });
      if (d.act === 'delete') {
        if (!(await askConfirm('¿Borrar esta receta de AE2?', 'Se quita de la lista y del script al guardar.', { confirmLabel: 'Borrar', danger: true }))) return;
        return persist(recipes.filter((_, i) => i !== editing));
      }
      if (d.act === 'save') {
        let r;
        try { r = toRecipe(draft); } catch (err) { return toast(err.message, 'error'); }
        const next = editing != null ? recipes.map((x, i) => (i === editing ? r : x)) : [...recipes, r];
        return persist(next);
      }
    };

    function setPicked(v) {
      const key = pick;
      if (!draft) return;
      if (key === 'result') draft.result = { id: v.id, count: draft.result.count || 1 };
      else if (key === 'ingredient') draft.ingredient = v;
      else if (key === 'input' || key === 'output') draft[key] = { k: draft[key].k === 'fluid' ? 'fluid' : 'block', id: v.id };
      else if (key && key[0] === 't' && draft.type === 'transform') draft.ingredients_list[Number(key.slice(1))] = v;
      else if (draft.type === 'inscriber') draft.ingredients[key] = v;
      pick = null; q = ''; items = []; draw();
    }

    async function persist(next) {
      busy = true; draw();
      try {
        const r = await api(`${base}/kubejs_appeng_save`, { method: 'POST', body: { recipes: next } });
        recipes = r.recipes; await ensureInfo(recipes.flatMap(idsOf));
        toast('Receta guardada. Aplícala con /reload.', 'success'); draft = null; editing = null; pick = null;
      } catch (err) { toast(err.message, 'error'); }
      busy = false; draw();
    }

    el.innerHTML = '<p class="muted">Cargando…</p>';
    load();
  }
  window.ModnexKjsAe2 = { view };
})();
