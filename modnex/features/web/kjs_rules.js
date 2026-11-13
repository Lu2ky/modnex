// KubeJS · Reglas: etiquetas, reemplazos, herrería, comercios, tooltips, ocultar, propiedades, eventos y comandos, todo con formularios.
(function () {
  const M = () => window.Modnex;
  const num = (v) => (v === '' || v == null ? '' : Number(v));

  const CATS = [
    ['tag', 'Etiquetas', 'Agrupa items o bloques en una etiqueta para que las recetas los traten como equivalentes.'],
    ['replace', 'Reemplazar', 'Cambia un item por otro en todas las recetas, ya sea como ingrediente o como resultado.'],
    ['smithing', 'Herrería', 'Recetas de la mesa de herrería: plantilla, base y material.'],
    ['trade', 'Comercios', 'Qué venden y qué piden los aldeanos. Necesita el mod MoreJS.'],
    ['tooltip', 'Tooltips', 'Texto extra al pasar el cursor sobre un item. Cada jugador lo ve en su cliente.'],
    ['hide', 'Ocultar en EMI/JEI', 'Esconde items del visor de recetas. No los quita del juego.'],
    ['item_prop', 'Propiedades', 'Tamaño de pila, rareza, durabilidad o combustible de items que ya existen. Hace falta reiniciar el servidor.'],
    ['event', 'Eventos', 'Cuando pasa algo en el juego, haz algo: mensaje, regalo, comando o cancelar la acción.'],
    ['command', 'Comandos', 'Crea comandos propios que ejecutan acciones.'],
  ];
  const CAT_TYPES = { trade: ['trade', 'trade_clear'] };
  const TYPE_LABEL = { tag: 'Etiqueta', replace: 'Reemplazo', smithing: 'Herrería', trade: 'Comercio', trade_clear: 'Quitar comercios', tooltip: 'Tooltip',
    hide: 'Ocultar', item_prop: 'Propiedades', event: 'Evento', command: 'Comando' };
  const REG = [['item', 'Items'], ['block', 'Bloques'], ['fluid', 'Fluidos'], ['entity_type', 'Entidades']];
  const PROF = { armorer: 'Armero', butcher: 'Carnicero', cartographer: 'Cartógrafo', cleric: 'Clérigo', farmer: 'Granjero', fisherman: 'Pescador',
    fletcher: 'Flechero', leatherworker: 'Peletero', librarian: 'Bibliotecario', mason: 'Albañil', shepherd: 'Pastor', toolsmith: 'Herramentero', weaponsmith: 'Armero de armas' };
  const COLORS = { gris: 'Gris', blanco: 'Blanco', rojo: 'Rojo', dorado: 'Dorado', amarillo: 'Amarillo', verde: 'Verde', aqua: 'Aqua', azul: 'Azul', rosa: 'Rosa', morado: 'Morado' };
  const WHEN = [['siempre', 'Siempre'], ['shift', 'Solo con Shift'], ['sin_shift', 'Sin Shift']];
  const RAR = [['', 'Sin cambio'], ['COMMON', 'Común'], ['UNCOMMON', 'Poco común'], ['RARE', 'Rara'], ['EPIC', 'Épica']];
  const ACT = [['tell', 'Enviar mensaje'], ['give', 'Dar item'], ['command', 'Ejecutar comando'], ['cancel', 'Cancelar la acción']];
  const stack = () => ({ id: '', count: 1 });

  // make: borrador nuevo. show: cuándo se enseña el campo. Tipos de campo: select, text, num, bool, item, stack, list, lines, actions.
  const FORMS = {
    tag: { make: () => ({ type: 'tag', registry: 'item', tag: '', action: 'add', entries: [] }), fields: [
      ['select', 'registry', 'Qué agrupa', REG], ['text', 'tag', 'Nombre de la etiqueta', 'c:ingots/cobre'],
      ['select', 'action', 'Acción', [['add', 'Añadir a la etiqueta'], ['remove', 'Quitar de la etiqueta']]], ['list', 'entries', 'Elementos', { tags: true }]] },
    replace: { make: () => ({ type: 'replace', mode: 'input', source: '', target: '', only: '' }), fields: [
      ['select', 'mode', 'Dónde', [['input', 'Como ingrediente'], ['output', 'Como resultado']]], ['item', 'source', 'Item a cambiar'],
      ['item', 'target', 'Item nuevo', { tags: true }], ['item', 'only', 'Solo en recetas que producen… (opcional)', { optional: true }]] },
    smithing: { make: () => ({ type: 'smithing', result: '', template: '', base: '', addition: '' }), fields: [
      ['item', 'template', 'Plantilla'], ['item', 'base', 'Base'], ['item', 'addition', 'Material'], ['item', 'result', 'Resultado']] },
    trade: { make: () => ({ type: 'trade', profession: 'farmer', level: 1, inputs: [stack()], output: stack(), max_uses: 12, xp: 5 }), fields: [
      ['select', 'profession', 'Profesión', Object.entries(PROF)], ['select', 'level', 'Nivel del aldeano', [1, 2, 3, 4, 5].map((n) => [n, String(n)])],
      ['stack', 'inputs.0', 'El aldeano pide'], ['stack', 'inputs.1', 'Y además (opcional)', { optional: true }], ['stack', 'output', 'Y da a cambio'],
      ['num', 'max_uses', 'Usos antes de agotarse'], ['num', 'xp', 'Experiencia del aldeano']] },
    trade_clear: { make: () => ({ type: 'trade_clear', which: 'vanilla' }), fields: [
      ['select', 'which', 'Quitar', [['vanilla', 'Todos los comercios de vanilla'], ['modded', 'Todos los comercios de mods']]]] },
    tooltip: { make: () => ({ type: 'tooltip', item: '', lines: [''], color: 'gris', when: 'siempre' }), fields: [
      ['item', 'item', 'Item', { tags: true }], ['lines', 'lines', 'Líneas de texto'], ['select', 'color', 'Color', Object.entries(COLORS)], ['select', 'when', 'Cuándo se ve', WHEN]] },
    hide: { make: () => ({ type: 'hide', items: [] }), fields: [['list', 'items', 'Items a ocultar']] },
    item_prop: { make: () => ({ type: 'item_prop', item: '', stack: '', rarity: '', fire_resistant: false, burn_time: '', max_damage: '' }), fields: [
      ['item', 'item', 'Item'], ['num', 'stack', 'Tamaño de pila (1–99)'], ['select', 'rarity', 'Rareza', RAR], ['num', 'max_damage', 'Durabilidad'],
      ['num', 'burn_time', 'Combustible: ticks de quemado (200 = 1 objeto)'], ['bool', 'fire_resistant', 'Resiste el fuego y la lava']] },
    event: { make: () => ({ type: 'event', event: 'player_login', filter: '', actions: [{ do: 'tell', text: '' }] }), fields: [
      ['event', 'event', 'Cuando…'], ['item', 'filter', 'Cuál bloque o item', { show: (d, T) => T.events[d.event] && T.events[d.event].filter }], ['actions', 'actions', 'Entonces…']] },
    command: { make: () => ({ type: 'command', name: '', level: 2, actions: [{ do: 'tell', text: '' }] }), fields: [
      ['text', 'name', 'Nombre del comando (sin /)', 'hola'], ['select', 'level', 'Quién puede usarlo', [[0, 'Todos'], [2, 'Operadores'], [4, 'Solo el propietario']]], ['actions', 'actions', 'Hace esto…']] },
  };

  const get = (o, path) => path.split('.').reduce((a, k) => (a == null ? a : a[k]), o);
  function put(o, path, v) { const p = path.split('.'); const k = p.pop(); let t = o; p.forEach((x) => { t = t[x]; }); t[k] = v; }

  window.ModnexKjsRules = function (el, s) {
    const { api, esc, toast } = M();
    const base = `/api/servers/${encodeURIComponent(s.name)}`;
    let rules = [], T = { events: {} }, morejs = false, cat = 'tag', draft = null, editing = -1, pick = null, items = [], q = '', timer = null, busy = false;
    const info = {};
    const nameOf = (id) => (info[id] ? info[id].name : id);
    const ico = (id, cls = 'kjs-ico sm') => id && !id.startsWith('#')
      ? (info[id] && info[id].icon ? `<img class="${cls}" src="${esc(info[id].icon)}" alt="" loading="lazy">` : `<span class="${cls} kjs-ph" aria-hidden="true">${esc(id.split(':').pop().charAt(0).toUpperCase())}</span>`)
      : `<span class="${cls} kjs-ph" aria-hidden="true">#</span>`;
    const remember = (l) => l.forEach((i) => { info[i.id] = { name: i.name, icon: i.icon }; });
    const idsOf = (r) => [r.source, r.target, r.only, r.result, r.template, r.base, r.addition, r.item, r.filter, ...(r.entries || []), ...(r.items || []),
      ...(r.inputs || []).map((x) => x.id), r.output && r.output.id, ...(r.actions || []).map((a) => a.item)].filter((x) => x && !x.startsWith('#'));

    async function load() {
      let d;
      try { d = await api(`${base}/kubejs_rules`); } catch (e) { el.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
      rules = d.rules; T = d.types; morejs = d.morejs;
      await Promise.all([...new Set(rules.flatMap(idsOf))].filter((id) => !info[id]).slice(0, 40).map(async (id) => {
        try { remember((await api(`${base}/kubejs_items?q=${encodeURIComponent(id)}&limit=20`)).items); } catch (e) { /* sin icono */ }
      }));
      draw();
    }
    async function search() {
      try { items = (await api(`${base}/kubejs_items?q=${encodeURIComponent(q)}&limit=120`)).items; remember(items); } catch (e) { toast(e.message, 'error'); }
      drawPicker();
    }
    async function persist(next, okMsg) {
      busy = true;
      try { const d = await api(`${base}/kubejs_rules_save`, { method: 'POST', body: { rules: next } }); rules = d.rules; toast(okMsg, 'success'); return true; }
      catch (e) { toast(e.message, 'error'); return false; }
      finally { busy = false; }
    }

    // ----- resumen de una regla -----
    const chip = (id) => `<span class="kjs-ing-i" title="${esc(id)}">${ico(id)}<span class="small">${esc(id.startsWith('#') ? id : nameOf(id))}</span></span>`;
    const stk = (x) => `${chip(x.id)}<span class="muted small">×${x.count}</span>`;
    function summary(r) {
      switch (r.type) {
        case 'tag': return `${r.action === 'add' ? 'Añade a' : 'Quita de'} <code>#${esc(r.tag)}</code> (${esc((REG.find((x) => x[0] === r.registry) || [])[1] || r.registry)}): ${r.entries.slice(0, 6).map(chip).join('')}${r.entries.length > 6 ? `<span class="muted small">y ${r.entries.length - 6} más</span>` : ''}`;
        case 'replace': return `${r.mode === 'input' ? 'Ingrediente' : 'Resultado'}: ${chip(r.source)} → ${chip(r.target)}${r.only ? ` <span class="muted small">solo en recetas de</span> ${chip(r.only)}` : ''}`;
        case 'smithing': return `${chip(r.template)} + ${chip(r.base)} + ${chip(r.addition)} → ${chip(r.result)}`;
        case 'trade': return `${esc(PROF[r.profession])} (nivel ${r.level}): ${r.inputs.map(stk).join(' + ')} → ${stk(r.output)}`;
        case 'trade_clear': return r.which === 'vanilla' ? 'Quita todos los comercios de vanilla' : 'Quita todos los comercios de mods';
        case 'tooltip': return `${chip(r.item)} <span class="muted small">${esc(r.lines.join(' / '))}</span>`;
        case 'hide': return `${r.items.slice(0, 8).map(chip).join('')}${r.items.length > 8 ? `<span class="muted small">y ${r.items.length - 8} más</span>` : ''}`;
        case 'item_prop': return `${chip(r.item)} <span class="muted small">${[r.stack && `pila ${r.stack}`, r.rarity && r.rarity.toLowerCase(), r.max_damage && `durabilidad ${r.max_damage}`, r.burn_time != null && r.burn_time !== '' && `combustible ${r.burn_time}`, r.fire_resistant && 'resiste fuego'].filter(Boolean).join(' · ')}</span>`;
        case 'event': return `${esc((T.events[r.event] || {}).label || r.event)}${r.filter ? ` (${chip(r.filter)})` : ''} → <span class="muted small">${r.actions.map(actText).join(', ')}</span>`;
        default: return `<code>/${esc(r.name)}</code> <span class="muted small">${r.actions.map(actText).join(', ')}</span>`;
      }
    }
    const actText = (a) => ({ tell: `mensaje «${esc(a.text)}»`, give: `dar ${a.count}× ${esc(nameOf(a.item))}`, command: `comando /${esc(a.cmd)}`, cancel: 'cancelar' })[a.do];

    // ----- formulario -----
    const opt = (list, cur) => list.map(([v, l]) => `<option value="${esc(v)}" ${String(v) === String(cur) ? 'selected' : ''}>${esc(l)}</option>`).join('');
    function slot(path, id, count) {
      return `<button type="button" class="kjs-slot ${pick === path ? 'on' : ''}" data-pick="${path}" title="${id ? esc(id) : 'Elegir'}">${id ? ico(id, 'kjs-ico') : '<span class="kjs-empty"></span>'}</button>
        <span class="kjs-slot-n">${id ? esc(id.startsWith('#') ? id : nameOf(id)) : '<span class="muted small">Elegir de la lista</span>'}</span>`;
    }
    function field(f) {
      const [kind, key, label, extra] = f;
      const ex = (kind === 'select' || kind === 'text') ? null : extra;
      if (ex && ex.show && !ex.show(draft, T)) return '';
      if (kind === 'event' && !Object.keys(T.events).length) return '';
      const v = get(draft, key);
      const lab = (inner) => `<div class="kjs-field-blk"><span class="kjs-lab">${esc(label)}</span>${inner}</div>`;
      if (kind === 'select') return `<label class="kjs-field">${esc(label)}<select data-f="${key}" data-redraw="1">${opt(extra, v)}</select></label>`;
      if (kind === 'event') return `<label class="kjs-field">${esc(label)}<select data-f="${key}" data-redraw="1">${opt(Object.entries(T.events).map(([k, e]) => [k, e.label]), v)}</select></label>`;
      if (kind === 'text') return `<label class="kjs-field">${esc(label)}<input data-f="${key}" value="${esc(v || '')}" placeholder="${esc(extra || '')}" maxlength="200"></label>`;
      if (kind === 'num') return `<label class="kjs-field">${esc(label)}<input type="number" data-f="${key}" value="${esc(v)}" min="0"></label>`;
      if (kind === 'bool') return `<label class="kjs-check"><input type="checkbox" data-f="${key}" data-redraw="1" ${v ? 'checked' : ''}> ${esc(label)}</label>`;
      if (kind === 'item') {
        const tagIn = ex && ex.tags ? `<input class="kjs-tagin" data-tag="${key}" placeholder="…o un tag, ej. #c:ingots" value="${v && v.startsWith('#') ? esc(v) : ''}">` : '';
        return lab(`<div class="kjs-pickrow">${slot(key, v)}${v && ex && ex.optional ? `<button type="button" class="btn sm" data-clear="${key}">Quitar</button>` : ''}${tagIn}</div>`);
      }
      if (kind === 'stack') {
        if (!v && ex && ex.optional) return lab(`<button type="button" class="btn sm" data-addstack="${key}">Añadir</button>`);
        return lab(`<div class="kjs-pickrow">${slot(key, v && v.id)}<input class="kjs-count" type="number" min="1" max="64" data-f="${key}.count" value="${esc(v ? v.count : 1)}" aria-label="Cantidad">
          ${ex && ex.optional ? `<button type="button" class="btn sm" data-clear="${key}">Quitar</button>` : ''}</div>`);
      }
      if (kind === 'list') {
        return lab(`<div class="kjs-chips">${v.map((id, i) => `<span class="kjs-chip">${ico(id)}${esc(id.startsWith('#') ? id : nameOf(id))}<button type="button" class="kjs-x" data-rmi="${key}:${i}" aria-label="Quitar">×</button></span>`).join('')}
          <button type="button" class="kjs-slot kjs-add ${pick === key ? 'on' : ''}" data-pick="${key}">+ Elegir de la lista</button></div>
          ${extra && extra.tags ? `<input class="kjs-tagin" data-tagadd="${key}" placeholder="O escribe un tag y pulsa Enter, ej. #c:ingots">` : ''}`);
      }
      if (kind === 'lines') {
        return lab(`${v.map((t, i) => `<div class="kjs-pickrow"><input class="kjs-wide" data-f="${key}.${i}" value="${esc(t)}" maxlength="200" placeholder="Texto de la línea">
          ${v.length > 1 ? `<button type="button" class="btn sm" data-rmi="${key}:${i}">Quitar</button>` : ''}</div>`).join('')}
          ${v.length < 8 ? `<button type="button" class="btn sm" data-addline="${key}">+ Añadir línea</button>` : ''}`);
      }
      // actions
      const evCancel = draft.type === 'event' && (T.events[draft.event] || {}).cancel;
      return lab(`${v.map((a, i) => `<div class="kjs-act"><select data-f="${key}.${i}.do" data-redraw="1">${opt(ACT.filter(([k]) => k !== 'cancel' || evCancel), a.do)}</select>
        ${a.do === 'tell' ? `<input class="kjs-wide" data-f="${key}.${i}.text" value="${esc(a.text || '')}" placeholder="Mensaje para el jugador" maxlength="200">` : ''}
        ${a.do === 'give' ? `${slot(`${key}.${i}.item`, a.item)}<input class="kjs-count" type="number" min="1" max="64" data-f="${key}.${i}.count" value="${esc(a.count || 1)}" aria-label="Cantidad">` : ''}
        ${a.do === 'command' ? `<input class="kjs-wide" data-f="${key}.${i}.cmd" value="${esc(a.cmd || '')}" placeholder="Ej. give @s minecraft:apple 1" maxlength="200">` : ''}
        ${v.length > 1 ? `<button type="button" class="btn sm" data-rmi="${key}:${i}">Quitar</button>` : ''}</div>`).join('')}
        ${v.length < 12 ? `<button type="button" class="btn sm" data-addact="${key}">+ Añadir acción</button>` : ''}`);
    }

    function drawPicker() {
      const box = el.querySelector('.kjs-pickbox');
      if (!box) return;
      box.hidden = !pick;
      if (!pick) return;
      box.querySelector('.kjs-browser').innerHTML = items.length ? items.map((i) => `<button type="button" class="kjs-item" data-id="${esc(i.id)}" title="${esc(i.id)}">${i.icon ? `<img class="kjs-ico sm" src="${esc(i.icon)}" alt="" loading="lazy">` : `<span class="kjs-ico sm kjs-ph">${esc(i.name.charAt(0))}</span>`}<span class="kjs-item-t">${esc(i.name)}</span></button>`).join('')
        : '<p class="muted small">Sin resultados.</p>';
    }

    function draw() {
      const [, , blurb] = CATS.find((c) => c[0] === cat);
      const types = CAT_TYPES[cat] || [cat];
      const list = rules.map((r, i) => [r, i]).filter(([r]) => types.includes(r.type));
      const needMore = cat === 'trade' && !morejs;
      el.innerHTML = `
        <nav class="kjs-cats" aria-label="Tipo de regla">${CATS.map(([k, l]) => `<button class="${k === cat ? 'on' : ''}" data-cat="${k}">${l}${rules.some((r) => (CAT_TYPES[k] || [k]).includes(r.type)) ? ` <span class="kjs-n">${rules.filter((r) => (CAT_TYPES[k] || [k]).includes(r.type)).length}</span>` : ''}</button>`).join('')}</nav>
        <p class="muted small">${esc(blurb)} ${TYPE_SIDE(cat)}</p>
        ${needMore ? '<div class="kjs-banner"><span>MoreJS no está instalado en este servidor. Puedes preparar los comercios, pero no harán efecto hasta que instales el mod y reinicies.</span></div>' : ''}
        <ul class="kjs-rules">${list.map(([r, i]) => `<li class="kjs-rule ${r.on ? '' : 'off'}"><div class="kjs-rule-b">${summary(r)}</div>
          <div class="kjs-rule-a"><label class="kjs-check"><input type="checkbox" data-toggle="${i}" ${r.on ? 'checked' : ''}> Activa</label>
          <button class="btn sm" data-edit="${i}">Editar</button><button class="btn sm danger" data-del="${i}">Borrar</button></div></li>`).join('') || '<li class="muted small">Aún no hay reglas de este tipo.</li>'}</ul>
        ${draft ? `<div class="kjs-editor"><div class="ft-head"><h2>${editing < 0 ? 'Nueva regla' : 'Editar regla'} · ${esc(TYPE_LABEL[draft.type])}</h2></div>
          ${FORMS[draft.type].fields.map(field).join('')}
          <div class="kjs-pickbox" ${pick ? '' : 'hidden'}><input class="kjs-search" data-search placeholder="Buscar item (nombre o id)…" value="${esc(q)}" autocomplete="off"><div class="kjs-browser"></div></div>
          <div class="kjs-foot"><span></span><span><button class="btn" data-cancel>Cancelar</button> <button class="btn primary" data-save ${busy ? 'disabled' : ''}>Guardar regla</button></span></div></div>`
          : `<div class="ft-actions">${types.map((t) => `<button class="btn primary" data-new="${t}">Nueva regla${types.length > 1 ? ` · ${TYPE_LABEL[t]}` : ''}</button>`).join('')}</div>`}`;
      drawPicker();
    }
    const TYPE_SIDE = (c) => ({ item_prop: 'Se aplica al reiniciar el servidor.', tooltip: 'Cada jugador lo recibe al recargar o reiniciar su juego.', hide: 'Cada jugador lo recibe al recargar o reiniciar su juego.' })[c] || 'Se aplica con /reload en la consola.';

    // ----- eventos -----
    function assign(path, id) {
      const p = path.split('.'); const k = p.pop(); let o = draft; p.forEach((x) => { o = o[x]; });
      if (Array.isArray(o[k])) { if (!o[k].includes(id)) o[k].push(id); }
      else if (o[k] && typeof o[k] === 'object') o[k].id = id;
      else o[k] = id;
    }
    el.oninput = (e) => {
      const t = e.target;
      if (t.matches('[data-search]')) { q = t.value; clearTimeout(timer); timer = setTimeout(search, 160); return; }
      if (t.dataset.tag) { const v = t.value.trim(); put(draft, t.dataset.tag, v); return; }
      if (t.dataset.f && !t.dataset.redraw) put(draft, t.dataset.f, t.type === 'number' ? num(t.value) : t.value);
    };
    el.onchange = (e) => {
      const t = e.target;
      if (t.dataset.toggle != null) { const next = rules.map((r, i) => (i === +t.dataset.toggle ? { ...r, on: t.checked } : r)); persist(next, 'Regla actualizada').then(draw); return; }
      if (t.dataset.f && t.dataset.redraw) {
        put(draft, t.dataset.f, t.type === 'checkbox' ? t.checked : t.value);
        if (t.dataset.f === 'event') { draft.filter = ''; draft.actions = draft.actions.filter((a) => a.do !== 'cancel' || (T.events[draft.event] || {}).cancel); }
        if (/\.do$/.test(t.dataset.f)) { const [, i] = t.dataset.f.split('.'); const a = draft.actions[+i]; draft.actions[+i] = { do: a.do, ...(a.do === 'tell' ? { text: '' } : a.do === 'give' ? { item: '', count: 1 } : a.do === 'command' ? { cmd: '' } : {}) }; }
        draw();
      }
    };
    el.onkeydown = (e) => {
      const t = e.target;
      if (e.key === 'Enter' && t.dataset.tagadd) { e.preventDefault(); const v = t.value.trim(); if (v) { if (!draft[t.dataset.tagadd].includes(v)) draft[t.dataset.tagadd].push(v); draw(); } }
    };
    el.onclick = async (e) => {
      const b = e.target.closest('button'); if (!b) return;
      const d = b.dataset;
      if (d.cat) { cat = d.cat; draft = null; pick = null; return draw(); }
      if (d.new) { draft = FORMS[d.new].make(); editing = -1; pick = null; return draw(); }
      if (d.edit != null) { editing = +d.edit; draft = JSON.parse(JSON.stringify(rules[editing])); pick = null; return draw(); }
      if (d.del != null) {
        if (!window.confirm('¿Borrar esta regla?')) return;
        if (await persist(rules.filter((_, i) => i !== +d.del), 'Regla borrada')) draw();
        return;
      }
      if (b.hasAttribute('data-cancel')) { draft = null; pick = null; return draw(); }
      if (b.hasAttribute('data-save')) {
        const out = JSON.parse(JSON.stringify(draft));
        if (editing < 0) out.id = `${out.type}_${Date.now().toString(36)}`;
        if (out.type === 'trade') out.inputs = out.inputs.filter((x) => x && x.id);
        out.on = editing < 0 ? true : rules[editing].on;
        const next = editing < 0 ? [...rules, out] : rules.map((r, i) => (i === editing ? out : r));
        if (await persist(next, 'Regla guardada. Aplícala con /reload.')) { draft = null; pick = null; draw(); }
        return;
      }
      if (d.pick) { pick = pick === d.pick ? null : d.pick; if (pick && !items.length) await search(); draw(); if (pick) el.querySelector('[data-search]').focus(); return; }
      if (d.id && pick) {
        assign(pick, d.id);
        if (!Array.isArray(get(draft, pick))) pick = null;
        return draw();
      }
      if (d.clear) { put(draft, d.clear, /inputs\.1/.test(d.clear) ? null : ''); if (/inputs\.1/.test(d.clear)) draft.inputs.length = 1; pick = null; return draw(); }
      if (d.addstack) { draft.inputs[1] = stack(); return draw(); }
      if (d.rmi) { const [k, i] = d.rmi.split(':'); get(draft, k).splice(+i, 1); return draw(); }
      if (d.addline) { draft[d.addline].push(''); return draw(); }
      if (d.addact) { draft[d.addact].push({ do: 'tell', text: '' }); return draw(); }
    };
    load();
  };
})();
