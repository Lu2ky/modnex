// KubeJS · Create: recetas de las máquinas de Create con formularios. Cada máquina se dibuja como bloque (vista de inventario)
// y la receta fluye de los ingredientes, por la máquina, a los resultados. Las mismas escenas, en solo lectura, se usan en «Quitar recetas».
(function () {
  const M = () => window.Modnex;
  const cache = {};
  const get = (o, p) => p.split('.').reduce((a, k) => (a == null ? a : a[k]), o);
  const put = (o, p, v) => { const a = p.split('.'); const k = a.pop(); let t = o; a.forEach((x) => { t = t[x]; }); t[k] = v; };
  const clone = (x) => JSON.parse(JSON.stringify(x));
  const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
  const STEP_LABEL = { deploying: 'Desplegador', pressing: 'Prensa', cutting: 'Sierra', filling: 'Surtidor' };

  // Tipos de receta, fluidos e iconos de las máquinas (isométricos si el modelo lo permite; si no, el icono plano). Se pide una vez por servidor.
  function prepare(base) {
    if (!cache[base]) {
      cache[base] = (async () => {
        const { api } = M();
        const [st, fl] = await Promise.all([api(`${base}/kubejs_create`).catch(() => null), api(`${base}/kubejs_fluids`).catch(() => ({ fluids: [] }))]);
        const types = st ? st.types : {}, stepMachine = st ? st.step_machine : {};
        const ids = [...new Set([...Object.values(types).flatMap((t) => [t.machine, t.extra]), ...Object.values(stepMachine), 'create:blaze_burner'].filter(Boolean))];
        if (window.ModnexKjsBlock) await window.ModnexKjsBlock.prepare(base, ids);
        const flat = {};
        await Promise.all(ids.map(async (id) => {
          if (window.ModnexKjsBlock && window.ModnexKjsBlock.get(id)) return;
          try { const r = (await api(`${base}/kubejs_items?q=${encodeURIComponent(id)}&limit=20`)).items.find((i) => i.id === id); if (r) flat[id] = r; } catch (e) { /* sin icono */ }
        }));
        return { types, stepMachine, fluids: Object.fromEntries((fl.fluids || []).map((f) => [f.id, f])), flat, installed: st ? st.installed : false };
      })();
    }
    return cache[base];
  }

  // ---------- dibujo de la escena ----------
  const esc = (v) => M().esc(v);
  function machine(D, id, cls) {
    const iso = window.ModnexKjsBlock && window.ModnexKjsBlock.get(id), flat = D.flat[id], src = iso || (flat && flat.icon);
    return src ? `<img class="cr-machine ${cls || ''}" ${iso ? `data-spin="${esc(id)}"` : ''} src="${esc(src)}" alt="" title="${esc(flat ? flat.name : id)}">`
      : `<span class="cr-machine ${cls || ''} kjs-ph" aria-hidden="true">${esc((id || '?').split(':').pop().charAt(0).toUpperCase())}</span>`;
  }
  const fluidName = (D, e) => (D.fluids[e.id] && D.fluids[e.id].name) || e.name || e.id;
  function fluidHTML(D, e) {
    const f = D.fluids[e.id];
    return f && f.icon ? `<span class="cr-fluid"><img src="${esc(f.icon)}" alt="">${f.tint ? '<span class="cr-tint"></span>' : ''}</span>` : '<span class="kjs-ph cr-tagmark" aria-hidden="true">~</span>';
  }
  function slot(D, o, path, e, big) {
    const has = e && e.id;
    let inner = '', label = 'casilla vacía', badge = '';
    if (has && e.k === 'fluid') {
      inner = fluidHTML(D, e); label = `${e.id.startsWith('#') ? e.id : fluidName(D, e)}, ${e.amount} mB`;
      badge = `<span class="cr-badge">${e.amount}</span>`;
    } else if (has && e.k === 'tag') {
      inner = '<span class="cr-tagmark" aria-hidden="true">#</span>'; label = `etiqueta #${e.id}`;
    } else if (has) {
      inner = o.icon(e); label = (o.name && o.name(e)) || e.id;
      if (e.count > 1) badge = `<span class="cr-badge">${e.count}</span>`;
    }
    if (has && e.chance) badge += `<span class="cr-chance">${Math.round(e.chance * 100)}%</span>`;
    if (has && e.weight) badge += `<span class="cr-chance">×${e.weight}</span>`;
    const on = o.on && o.on(path), cls = `cr-slot${big ? ' big' : ''}${on ? ' on' : ''}`;
    return o.ro ? `<span class="${cls}" role="img" aria-label="${esc(label)}" title="${esc(label)}">${inner}${badge}</span>`
      : `<button type="button" class="${cls}" data-slot="${path}" aria-label="${esc(label)}" title="${esc(label)}">${inner}${badge}</button>`;
  }
  const arrow = '<span class="cr-arrow" aria-hidden="true"></span>';

  function meta(D, m) {
    const chips = [];
    if (m.heat) chips.push(`<span class="${m.heat}">${m.heat === 'heated' ? 'Con calor (quemador)' : 'Calor extremo (quemador azul)'}</span>`);
    if (m.time) chips.push(`<span>${(m.time / 20).toFixed(m.time % 20 ? 1 : 0)} s</span>`);
    if (m.keep) chips.push('<span>Conserva el item</span>');
    return chips.length ? `<div class="cr-meta">${chips.join('')}</div>` : '';
  }
  function midHTML(D, m, T) {
    let icons = machine(D, T.machine);
    if (T.extra) icons = (m.type === 'mixing' || m.type === 'compacting') ? `<div class="stack">${machine(D, T.machine)}${machine(D, T.extra, 'small')}</div>` : `<div class="row">${machine(D, T.machine)}${machine(D, T.extra, 'small')}</div>`;
    if (m.heat) icons += machine(D, 'create:blaze_burner', 'small');
    return `<div class="cr-mid">${icons}${meta(D, m)}</div>`;
  }
  function cellsOf(m) {
    if (m.cells) return { w: m.w, h: m.h, cells: m.cells };
    const w = (m.pattern[0] || '').length, h = m.pattern.length, cells = [];
    m.pattern.forEach((row) => [...row].forEach((ch) => cells.push(ch === ' ' ? null : (m.key || {})[ch] || null)));
    return { w, h, cells };
  }
  function stdBody(D, m, o, T) {
    const ins = (m.ins || []).map((e, i) => slot(D, o, `ins.${i}`, e)).join('');
    const outs = (m.outs || []).map((e, i) => slot(D, o, `outs.${i}`, e, m.outs.length === 1 && (e.k === 'item'))).join('');
    return `<div class="cr-body"><div class="cr-col">${ins}${(o.adders && o.adders.ins) || ''}</div>${arrow}${midHTML(D, m, T)}${arrow}<div class="cr-col">${outs}${(o.adders && o.adders.outs) || ''}</div></div>`;
  }
  function craftBody(D, m, o, T) {
    const { w, h, cells } = cellsOf(m);
    const grid = Array.from({ length: w * h }, (_, i) => slot(D, o, `cells.${i}`, cells[i])).join('');
    const res = m.result || (m.outs && m.outs[0]);
    return `<div class="cr-body"><div class="cr-col grid" data-cols="${w}">${grid}</div>${arrow}<div class="cr-mid">${machine(D, T.machine)}</div>${arrow}${slot(D, o, 'result', res, true)}</div>`;
  }
  function seqBody(D, m, o, T) {
    const input = m.input || (m.ins && m.ins[0]), trans = m.transitional && typeof m.transitional === 'object' ? m.transitional : { k: 'item', id: m.transitional || '' };
    const steps = (m.steps || []).map((st, i) => `<div class="cr-step"><span class="n">${i + 1}</span>${machine(D, D.stepMachine[st.t], 'small')}
      ${st.t === 'deploying' ? slot(D, o, `steps.${i}.held`, st.held) : st.t === 'filling' ? slot(D, o, `steps.${i}.fluid`, st.fluid) : `<span class="cr-meta"><span>${STEP_LABEL[st.t]}</span></span>`}</div>`).join(arrow);
    const outs = (m.outs || []).map((e, i) => slot(D, o, `outs.${i}`, e, i === 0)).join('');
    return `<div class="cr-seq">${slot(D, o, 'input', input)}${arrow}<div class="cr-step"><span class="cr-meta"><span>Item intermedio</span></span>${slot(D, o, 'transitional', trans)}<span class="cr-loops">×${m.loops || 5}</span></div>${steps ? arrow + steps : ''}${arrow}<div class="cr-col">${outs}${(o.adders && o.adders.outs) || ''}</div></div>`;
  }
  // scene(D, receta, { ro, small, icon(e), name(e), on(path), adders }) -> HTML
  function scene(D, m, o) {
    const T = D.types[m.type] || { label: m.type, machine: 'create:mechanical_crafter' };
    const body = m.type === 'mechanical_crafting' ? craftBody(D, m, o, T) : m.type === 'sequenced_assembly' ? seqBody(D, m, o, T) : stdBody(D, m, o, T);
    return `<div class="cr-scene${o.small ? ' sm' : ''}" data-type="${m.type}"><div class="cr-panel"><span class="cr-title">${esc(T.label)}</span>${body}</div></div>`;
  }
  // CSP: sin atributos style. Las columnas de la cuadrícula se ponen con la API de estilos.
  function place(root) {
    root.querySelectorAll('.cr-col.grid').forEach((g) => { g.style.setProperty('grid-template-columns', `repeat(${g.dataset.cols}, calc(18 * var(--u)))`); });
  }

  // ---------- editor ----------
  function view(el, s) {
    const { api, toast } = M();
    const base = `/api/servers/${encodeURIComponent(s.name)}`;
    let D = null, recipes = [], draft = null, editing = -1, sel = null, q = '', items = [], timer = null, busy = false;
    const info = {};
    const remember = (l) => l.forEach((i) => { info[i.id] = { name: i.name, icon: i.icon }; });
    const nameOf = (e) => (info[e.id] ? info[e.id].name : e.id);
    const itemIcon = (e) => (info[e.id] && info[e.id].icon ? `<img class="kjs-ico" data-iid="${esc(e.id)}" src="${esc(info[e.id].icon)}" alt="">` : `<span class="kjs-ph kjs-ico" aria-hidden="true">${esc((e.id || '?').split(':').pop().charAt(0).toUpperCase())}</span>`);
    const T = () => D.types[draft.type];
    const empty = (k) => (k === 'fluid' ? { k, id: '', amount: 1000 } : { k, id: '' });

    function fresh(type) {
      const sp = D.types[type], d = { id: draft ? draft.id : '', type };
      if (type === 'mechanical_crafting') return { ...d, w: 3, h: 3, cells: Array(81).fill(null), result: { k: 'item', id: '', count: 1 } };
      if (type === 'sequenced_assembly') return { ...d, input: empty('item'), transitional: empty('item'), loops: 5, steps: [], outs: [{ k: 'item', id: '', count: 1, weight: '' }] };
      const ins = Array.from({ length: sp.nin[0] }, () => empty('item')), outs = Array.from({ length: sp.nout[0] }, () => ({ k: 'item', id: '', count: 1 }));
      if (type === 'filling') ins[1] = empty('fluid');
      if (type === 'emptying') outs[1] = empty('fluid');
      return { ...d, ins, outs, time: '', heat: '', keep: false };
    }
    function toDraft(r) {
      const d = clone(r);
      if (d.type === 'mechanical_crafting') {
        const w = d.pattern[0].length, h = d.pattern.length, cells = Array(81).fill(null);
        d.pattern.forEach((row, ri) => [...row].forEach((ch, ci) => { if (ch !== ' ') cells[ri * w + ci] = d.key[ch]; }));
        return { id: d.id, type: d.type, w, h, cells, result: d.result };
      }
      if (d.type === 'sequenced_assembly') return { ...d, transitional: { k: 'item', id: d.transitional } };
      d.time = d.time || ''; d.heat = d.heat || ''; d.keep = !!d.keep;
      return d;
    }
    const cleanIng = (e) => (e.k === 'fluid' ? { k: 'fluid', id: e.id, amount: Number(e.amount) || 1000 } : { k: e.k, id: e.id });
    const cleanOut = (e) => {
      if (e.k === 'fluid') return { k: 'fluid', id: e.id, amount: Number(e.amount) || 1000 };
      const o = { k: 'item', id: e.id, count: Number(e.count) || 1 };
      if (e.chance) o.chance = e.chance;
      return o;
    };
    function toStored() {
      const d = draft, base0 = { id: d.id, type: d.type };
      if (d.type === 'mechanical_crafting') {
        const sigs = new Map(), key = {}, pattern = [];
        for (let r = 0; r < d.h; r++) {
          let row = '';
          for (let c = 0; c < d.w; c++) {
            const e = d.cells[r * d.w + c];
            if (!e || !e.id) { row += ' '; continue; }
            const sig = `${e.k}:${e.id}`;
            if (!sigs.has(sig)) { if (sigs.size >= 26) throw new Error('Máximo 26 ingredientes distintos en el fabricador'); sigs.set(sig, LETTERS[sigs.size]); key[LETTERS[sigs.size - 1]] = { k: e.k, id: e.id }; }
            row += sigs.get(sig);
          }
          pattern.push(row);
        }
        return { ...base0, pattern, key, result: { k: 'item', id: d.result.id, count: Number(d.result.count) || 1 } };
      }
      if (d.type === 'sequenced_assembly') {
        return { ...base0, input: cleanIng(d.input), transitional: d.transitional.id, loops: Number(d.loops) || 5,
          steps: d.steps.map((st) => (st.t === 'deploying' ? { t: st.t, held: cleanIng(st.held || empty('item')) } : st.t === 'filling' ? { t: st.t, fluid: cleanIng(st.fluid || empty('fluid')) } : { t: st.t })),
          outs: d.outs.map((o) => ({ k: 'item', id: o.id, count: Number(o.count) || 1, ...(o.weight ? { weight: Number(o.weight) } : {}) })) };
      }
      const out = { ...base0, ins: d.ins.map(cleanIng), outs: d.outs.map(cleanOut) };
      if (d.time) out.time = Number(d.time);
      if (d.heat) out.heat = d.heat;
      if (d.keep) out.keep = true;
      return out;
    }
    const slug = (t) => (t || 'receta').replace(/[^a-z0-9_]/g, '_').slice(0, 30);
    function autoName() {
      if (draft.id) return;
      const out = draft.type === 'mechanical_crafting' ? draft.result : draft.outs && draft.outs[0];
      if (!out || !out.id) return;
      let n = `${slug(out.id.split(':').pop())}_${draft.type.slice(0, 8)}`, i = 2;
      const taken = (x) => recipes.some((r, ix) => r.id === x && ix !== editing);
      let cand = n; while (taken(cand)) cand = `${n}_${i++}`;
      draft.id = cand;
    }

    // qué clases de contenido admite cada casilla
    function kinds(path) {
      const t = draft.type, sp = D.types[t] || {}, i = Number(path.split('.')[1]);
      if (path.startsWith('ins.')) return t === 'filling' ? (i === 1 ? ['fluid'] : ['item', 'tag']) : sp.fluid_in ? ['item', 'tag', 'fluid'] : ['item', 'tag'];
      if (path.startsWith('outs.')) return t === 'emptying' ? (i === 1 ? ['fluid'] : ['item']) : t === 'sequenced_assembly' ? ['item'] : sp.fluid_out ? ['item', 'fluid'] : ['item'];
      if (path.startsWith('cells.') || path === 'input') return ['item', 'tag'];
      if (/steps\.\d+\.held/.test(path)) return ['item', 'tag'];
      if (/steps\.\d+\.fluid/.test(path)) return ['fluid'];
      return ['item'];
    }
    const removable = (path) => {
      const [side] = path.split('.');
      if (!['ins', 'outs'].includes(side) || !draft[side] || ['filling', 'emptying'].includes(draft.type)) return false;
      const min = draft.type === 'sequenced_assembly' ? 1 : (D.types[draft.type][side === 'ins' ? 'nin' : 'nout'] || [1, 1])[0];
      return draft[side].length > min;
    };

    async function load() {
      try { D = await prepare(base); const d = await api(`${base}/kubejs_create`); recipes = d.recipes; } catch (e) { el.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
      const ids = new Set();
      recipes.forEach((r) => { const all = [...(r.ins || []), ...(r.outs || []), ...(r.input ? [r.input] : []), ...(r.result ? [r.result] : []), ...Object.values(r.key || {})]; all.forEach((e) => e.k !== 'fluid' && ids.add(e.id)); });
      await Promise.all([...ids].slice(0, 40).map(async (id) => { try { remember((await api(`${base}/kubejs_items?q=${encodeURIComponent(id)}&limit=20`)).items); } catch (e) { /* sin icono */ } }));
      draw();
    }
    async function search() {
      try { items = (await api(`${base}/kubejs_items?q=${encodeURIComponent(q)}&limit=120`)).items; remember(items); } catch (e) { toast(e.message, 'error'); }
      drawBrowser();
    }
    function adders() {
      const a = { ins: '', outs: '' }, t = draft.type, sp = T();
      if (['mechanical_crafting', 'filling', 'emptying'].includes(t)) return a;
      if (t === 'sequenced_assembly') {
        if (draft.outs.length < 12) a.outs = '<div class="cr-add"><button type="button" data-add="outs:item">+ Resultado</button></div>';
        return a;
      }
      if (draft.ins.length < sp.nin[1]) a.ins = `<div class="cr-add"><button type="button" data-add="ins:item">+ Item</button>${sp.fluid_in ? '<button type="button" data-add="ins:fluid">+ Fluido</button>' : ''}</div>`;
      if (draft.outs.length < sp.nout[1]) a.outs = `<div class="cr-add"><button type="button" data-add="outs:item">+ Resultado</button>${sp.fluid_out ? '<button type="button" data-add="outs:fluid">+ Fluido</button>' : ''}</div>`;
      return a;
    }
    function detailHTML() {
      if (!sel) return '';
      const e = get(draft, sel) || empty('item'), ks = kinds(sel), isOut = sel.startsWith('outs.') || sel === 'result';
      const seqOut = draft.type === 'sequenced_assembly' && sel.startsWith('outs.');
      const fl = D.fluids;
      let body = '';
      if (e.k === 'tag') body = `<label class="kjs-field">Etiqueta (ej. c:ingots/hierro)<input class="cr-tag" data-sf="id" value="${esc(e.id)}" maxlength="120"></label>`;
      else if (e.k === 'fluid') {
        body = `<div class="cr-fl">${Object.values(fl).map((f) => `<button type="button" class="${e.id === f.id ? 'on' : ''}" data-fluid="${esc(f.id)}">${fluidHTML(D, { id: f.id })}${esc(f.name)}</button>`).join('')}</div>
          <div class="cr-opts"><label class="kjs-field small">Otro fluido (id)<input data-sf="id" value="${esc(e.id)}" placeholder="mod:fluido o #mod:etiqueta" maxlength="120"></label>
          <label class="kjs-field small">Cantidad (mB)<input type="number" min="1" max="1000000" data-sf="amount" value="${esc(e.amount || 1000)}"></label></div>`;
      } else body = '<p class="muted small">Elige un item en la lista de abajo.</p>';
      const extra = e.k === 'item' && isOut ? `<div class="cr-opts"><label class="kjs-field small">Cantidad<input type="number" min="1" max="64" data-sf="count" value="${esc(e.count || 1)}"></label>
        ${seqOut ? `<label class="kjs-field small">Peso (más peso, más probable)<input type="number" min="0" step="any" data-sf="weight" value="${esc(e.weight || '')}"></label>`
          : draft.type !== 'mechanical_crafting' ? `<label class="kjs-field small">Probabilidad (%)<input type="number" min="1" max="100" data-sf="chance" value="${e.chance ? Math.round(e.chance * 100) : ''}" placeholder="100"></label>` : ''}</div>` : '';
      return `<div class="cr-detail"><h3>Casilla seleccionada</h3>
        ${ks.length > 1 ? `<div class="cr-kinds" role="group" aria-label="Qué va en la casilla">${ks.map((k) => `<button type="button" class="${e.k === k ? 'on' : ''}" data-kind="${k}">${{ item: 'Item', tag: 'Etiqueta', fluid: 'Fluido' }[k]}</button>`).join('')}</div>` : ''}
        ${body}${extra}
        <div class="ft-actions"><button class="btn sm" data-act="empty">Vaciar casilla</button>${removable(sel) ? '<button class="btn sm danger" data-act="remove">Quitar casilla</button>' : ''}</div></div>`;
    }
    function optsHTML() {
      const sp = T();
      if (!sp || draft.type === 'mechanical_crafting' || draft.type === 'sequenced_assembly') return '';
      const out = [];
      if (sp.time) out.push(`<label class="kjs-field small">Tiempo (ticks, vacío = el normal)<input type="number" min="1" data-f="time" value="${esc(draft.time || '')}"></label>`);
      if (sp.heat) out.push(`<label class="kjs-field small">Calor<select data-f="heat" data-redraw="1"><option value="">Sin calor</option><option value="heated" ${draft.heat === 'heated' ? 'selected' : ''}>Quemador (heated)</option><option value="superheated" ${draft.heat === 'superheated' ? 'selected' : ''}>Quemador azul (superheated)</option></select></label>`);
      if (sp.keep) out.push(`<label class="kjs-check"><input type="checkbox" data-f="keep" data-redraw="1" ${draft.keep ? 'checked' : ''}> El desplegador conserva su item</label>`);
      return out.length ? `<div class="cr-opts">${out.join('')}</div>` : '';
    }
    function extraEditors() {
      if (draft.type === 'mechanical_crafting') {
        const sizes = (k, label) => `<label class="kjs-field small">${label}<select data-f="${k}" data-redraw="1">${[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => `<option ${n === draft[k] ? 'selected' : ''}>${n}</option>`).join('')}</select></label>`;
        return `<div class="cr-size">${sizes('w', 'Columnas')}${sizes('h', 'Filas')}<label class="kjs-field small">Cantidad del resultado<input type="number" min="1" max="64" data-f="result.count" value="${esc(draft.result.count || 1)}"></label></div>`;
      }
      if (draft.type === 'sequenced_assembly') {
        const rows = draft.steps.map((st, i) => `<li class="cr-steprow">${i + 1}. ${STEP_LABEL[st.t]} <button class="btn sm" data-step="up:${i}" ${i ? '' : 'disabled'} aria-label="Subir">↑</button><button class="btn sm" data-step="down:${i}" ${i < draft.steps.length - 1 ? '' : 'disabled'} aria-label="Bajar">↓</button><button class="btn sm danger" data-step="del:${i}">Quitar</button></li>`).join('');
        return `<div class="cr-opts"><label class="kjs-field small">Repeticiones de la secuencia<input type="number" min="1" max="100" data-f="loops" value="${esc(draft.loops)}"></label></div>
          <div class="cr-kinds" role="group" aria-label="Añadir un paso">${Object.keys(STEP_LABEL).map((t) => `<button type="button" data-addstep="${t}">+ ${STEP_LABEL[t]}</button>`).join('')}</div>
          ${rows ? `<ul class="cr-steps">${rows}</ul>` : '<p class="muted small">Añade los pasos en el orden en que ocurren. El item intermedio entra y sale de cada paso.</p>'}`;
      }
      return '';
    }
    function draw() {
      if (!D) return;
      if (!D.installed) {
        el.innerHTML = '<div class="kjs-banner"><span>Create no está instalado en este servidor. Puedes preparar recetas, pero no harán efecto hasta que lo instales.</span></div>';
      } else el.innerHTML = '';
      const sceneOpts = (e) => ({ icon: itemIcon, name: nameOf, on: (p) => p === sel, adders: adders(), ...e });
      const list = recipes.map((r, i) => {
        const out = r.type === 'mechanical_crafting' ? r.result : (r.outs || [])[0];
        const label = out ? (out.k === 'fluid' ? fluidName(D, out) : nameOf(out)) : r.id;
        return `<button class="cr-card ${editing === i ? 'on' : ''}" data-open="${i}">${machine(D, D.types[r.type].machine)}<span class="t"><strong>${esc(label)}</strong><span class="muted small">${esc(D.types[r.type].label)} · ${esc(r.id)}</span></span></button>`;
      }).join('');
      const picker = Object.entries(D.types).map(([k, t]) => `<button type="button" class="cr-type ${draft && draft.type === k ? 'on' : ''}" data-type="${k}" aria-pressed="${!!draft && draft.type === k}">${machine(D, t.machine)}<span>${esc(t.label)}</span></button>`).join('');
      el.insertAdjacentHTML('beforeend', `
        <div class="ft-head"><h2>Recetas de Create</h2><span class="muted small">${recipes.length} ${recipes.length === 1 ? 'receta' : 'recetas'}</span></div>
        <p class="muted small">Elige la máquina, rellena la receta y guárdala. Se aplica con <code>/reload</code> en la consola. Las recetas se escriben en el formato de Create, no hace falta ningún otro mod.</p>
        <div class="cr-list">${list}<button class="cr-card kjs-new" data-act="new">+ Nueva receta</button></div>
        ${draft ? `<div class="kjs-editor">
          <label class="kjs-field">Nombre de la receta<input class="kjs-name" data-f="id" value="${esc(draft.id)}" maxlength="40" placeholder="ej. lingote_de_hierro"></label>
          <p class="muted small">¿En qué máquina se hace?</p><div class="cr-types">${picker}</div>
          ${scene(D, draft, sceneOpts({}))}
          ${extraEditors()}${optsHTML()}${detailHTML()}
          ${sel && get(draft, sel) && get(draft, sel).k === 'item' ? `<div class="kjs-browser-wrap"><input class="kjs-search" type="search" placeholder="Buscar item por nombre o id" value="${esc(q)}" aria-label="Buscar item"><div class="kjs-browser" aria-live="polite"></div></div>` : ''}
          <div class="ft-actions"><button class="btn" data-act="cancel">Cancelar</button><button class="btn primary" data-act="save" ${busy ? 'disabled' : ''}>Guardar receta</button>
            ${editing >= 0 ? '<button class="btn danger" data-act="delete">Borrar receta</button>' : ''}</div></div>` : ''}`);
      place(el);
      drawBrowser();
    }
    function drawBrowser() {
      const box = el.querySelector('.kjs-browser');
      if (!box) return;
      box.innerHTML = items.length ? items.map((it) => `<button type="button" class="kjs-item" data-id="${esc(it.id)}" title="${esc(it.id)}">${it.icon ? `<img class="kjs-ico sm" data-iid="${esc(it.id)}" src="${esc(it.icon)}" alt="" loading="lazy">` : `<span class="kjs-ico sm kjs-ph">${esc(it.name.charAt(0))}</span>`}<span class="kjs-item-t">${esc(it.name)}<span class="muted small block">${esc(it.id)}</span></span></button>`).join('') : '<p class="muted small">Escribe para buscar.</p>';
    }

    el.oninput = (e) => {
      const t = e.target;
      if (t.matches('.kjs-search')) { q = t.value; clearTimeout(timer); timer = setTimeout(search, 160); return; }
      let v = t.type === 'checkbox' ? t.checked : t.value;
      if (t.dataset.sf && sel) {                       // campo de la casilla seleccionada
        if (t.dataset.sf === 'chance') v = v ? Math.min(1, Math.max(0.01, Number(v) / 100)) : '';
        else if (['amount', 'count', 'weight'].includes(t.dataset.sf) && v !== '') v = Number(v);
        put(draft, `${sel}.${t.dataset.sf}`, v);
      } else if (t.dataset.f && !t.dataset.redraw) put(draft, t.dataset.f, v);
    };
    el.onchange = (e) => {
      const t = e.target;
      if (!t.dataset.f || !t.dataset.redraw) return;
      const v = t.type === 'checkbox' ? t.checked : (t.dataset.f === 'w' || t.dataset.f === 'h') ? Number(t.value) : t.value;
      if (t.dataset.f === 'w' || t.dataset.f === 'h') {
        const w0 = draft.w, h0 = draft.h, old = draft.cells.slice(), nw = t.dataset.f === 'w' ? v : w0, nh = t.dataset.f === 'h' ? v : h0, cells = Array(81).fill(null);
        for (let r = 0; r < Math.min(h0, nh); r++) for (let c = 0; c < Math.min(w0, nw); c++) cells[r * nw + c] = old[r * w0 + c];
        draft.w = nw; draft.h = nh; draft.cells = cells; sel = null;
      } else put(draft, t.dataset.f, v);
      draw();
    };
    el.onclick = async (e) => {
      const b = e.target.closest('button'); if (!b || b.disabled) return;
      const d = b.dataset;
      if (b.dataset.act === 'new') { draft = fresh('pressing'); draft.id = ''; editing = -1; sel = null; return draw(); }
      if (d.open != null) { editing = Number(d.open); draft = toDraft(recipes[editing]); sel = null; return draw(); }
      if (d.type) { draft = fresh(d.type); sel = null; return draw(); }
      if (d.slot) {
        sel = sel === d.slot ? null : d.slot;
        if (sel && !get(draft, sel)) put(draft, sel, empty('item'));      // una casilla vacía de la cuadrícula es null
        if (sel && !items.length) await search();
        return draw();
      }
      if (d.kind) { const old = get(draft, sel) || {}; put(draft, sel, { ...(d.kind === 'fluid' ? { k: 'fluid', id: '', amount: 1000 } : { k: d.kind, id: '' }), ...(old.count ? { count: old.count } : {}) }); return draw(); }
      if (d.fluid) { const old = get(draft, sel); put(draft, sel, { ...old, k: 'fluid', id: d.fluid }); return draw(); }
      if (d.add) { const [side, k] = d.add.split(':'); draft[side].push(side === 'outs' && k === 'item' ? { k, id: '', count: 1 } : empty(k)); sel = `${side}.${draft[side].length - 1}`; if (k === 'item' && !items.length) await search(); return draw(); }
      if (d.addstep) { draft.steps.push({ t: d.addstep, ...(d.addstep === 'deploying' ? { held: empty('item') } : {}), ...(d.addstep === 'filling' ? { fluid: empty('fluid') } : {}) }); sel = null; return draw(); }
      if (d.step) { const [a, i] = d.step.split(':'), n = Number(i), st = draft.steps; if (a === 'del') st.splice(n, 1); else { const j = a === 'up' ? n - 1 : n + 1; [st[n], st[j]] = [st[j], st[n]]; } sel = null; return draw(); }
      if (d.id && sel) { const old = get(draft, sel) || {}; put(draft, sel, { ...old, k: 'item', id: d.id }); autoName(); return draw(); }
      if (d.act === 'empty') { const old = get(draft, sel); put(draft, sel, old.k === 'fluid' ? { ...old, id: '' } : { ...old, id: '' }); return draw(); }
      if (d.act === 'remove') { const [side, i] = sel.split('.'); draft[side].splice(Number(i), 1); sel = null; return draw(); }
      if (d.act === 'cancel') { draft = null; sel = null; editing = -1; return draw(); }
      if (d.act === 'delete') {
        if (!window.confirm('¿Borrar esta receta?')) return;
        busy = true; try { const out = await api(`${base}/kubejs_create_save`, { method: 'POST', body: { recipes: recipes.filter((_, i) => i !== editing) } }); recipes = out.recipes; draft = null; editing = -1; sel = null; toast('Receta borrada', 'success'); } catch (err) { toast(err.message, 'error'); }
        busy = false; return draw();
      }
      if (d.act === 'save') {
        let stored;
        try { autoName(); stored = toStored(); } catch (err) { return toast(err.message, 'error'); }
        const next = editing >= 0 ? recipes.map((r, i) => (i === editing ? stored : r)) : [...recipes, stored];
        busy = true;
        try { const out = await api(`${base}/kubejs_create_save`, { method: 'POST', body: { recipes: next } }); recipes = out.recipes; toast('Receta guardada. Aplícala con /reload.', 'success'); draft = null; editing = -1; sel = null; }
        catch (err) { toast(err.message, 'error'); }
        busy = false; draw();
      }
    };
    load();
  }

  window.ModnexKjsCreate = { prepare, scene, place, view };
})();
