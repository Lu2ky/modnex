/* Reglas de InControl: spawn.json, spawner.json y loot.json como formulario de tarjetas. */

const ICES = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const IC_FILES = {
  'spawn.json': { title: 'Aparición', help: 'Permite o bloquea las apariciones que ya ocurren, y puede cambiar sus atributos. No añade mobs nuevos.' },
  'spawner.json': { title: 'Generar mobs', help: 'Añade mobs nuevos en la dimensión, según las condiciones. Cada regla necesita un mob y una dimensión.' },
  'loot.json': { title: 'Botín', help: 'Cambia lo que sueltan los mobs al morir. Todas las reglas que coinciden se aplican.' },
};
// Nombres en español para las claves más usadas. El resto se deriva del nombre.
const IC_LABELS = {
  when: 'Momento', result: 'Resultado', continue: 'Seguir con las siguientes reglas', mob: 'Mob', phase: 'Fase',
  biome: 'Bioma', dimension: 'Dimensión', structure: 'Estructura', spawntype: 'Motivo de aparición', mindaycount: 'Día mínimo', maxdaycount: 'Día máximo',
  mintime: 'Hora mínima', maxtime: 'Hora máxima', random: 'Probabilidad', playerhelditem: 'Objeto en la mano', hostile: 'Solo hostiles',
  passive: 'Solo pasivos', seesky: 'Ve el cielo', maxhostile: 'Máximo de hostiles', maxtotal: 'Máximo total', mindist: 'Distancia mínima al jugador',
  maxdist: 'Distancia máxima al jugador', maxthis: 'Máximo de este mob', healthmultiply: 'Vida (multiplicar)', healthadd: 'Vida (sumar)', healthset: 'Vida (fijar)',
  speedmultiply: 'Velocidad (multiplicar)', damagemultiply: 'Daño (multiplicar)', damageadd: 'Daño (sumar)', customname: 'Nombre personalizado',
  angry: 'Ataca al jugador', item: 'Objeto', itemcount: 'Cantidad por nivel de Saqueo', remove: 'Quitar objeto', removeall: 'Quitar todo el botín',
  mobsfrombiome: 'Tipo de mob del bioma', attempts: 'Intentos', persecond: 'Probabilidad por segundo', amount: 'Cantidad', weights: 'Pesos', number: 'Número',
  addscoreboardtags: 'Etiquetas de scoreboard', and: 'Todas estas (y)', not: 'Ninguna de estas (no)', validspawn: 'Punto de spawn válido', sturdy: 'Bloque sólido',
};
const IC_ENUM = { when: ['position', 'onjoin', 'finalize', 'despawn'], result: ['allow', 'deny', 'default'], mobsfrombiome: ['monster', 'creature', 'ambient', 'water_creature', 'water_ambient', 'misc'], weather: ['rain', 'thunder'], difficulty: ['easy', 'normal', 'hard', 'peaceful'] };
const IC_HELP = {
  when: 'Cuándo se evalúa: position (antes del spawn), onjoin (al entrar al mundo), finalize (antes de aparecer; cambia atributos) o despawn.',
  result: 'allow permite, deny impide, default conserva la decisión de vanilla. Sin resultado se respeta lo que decidan otros mods.',
  continue: 'Si está activo, la regla aplica y se siguen evaluando las siguientes.',
  random: 'De 0 a 1: 0.1 equivale a un 10 %.',
};
const humanKey = (k) => IC_LABELS[k] || k.replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/[_.]/g, ' ').replace(/^./, (c) => c.toUpperCase());

// Pestaña "Reglas" del panel de InControl. Se llama desde modconfig.js.
async function openRulesTab(d) {
  d.dataset.tab = 'rules';
  d.querySelector('.cfg-tools').hidden = true;
  d.querySelector('.cfg-save').hidden = false;
  const body = d.querySelector('.cfg-body');
  body.innerHTML = `
    <div class="ic-files" role="tablist" aria-label="Archivo de reglas">${Object.entries(IC_FILES).map(([f, m]) => `<button type="button" role="tab" class="cfg-mod" data-ic-file="${f}">${m.title}</button>`).join('')}</div>
    <div class="ic-intro"></div><div class="ic-list" aria-live="polite"></div>`;
  body.addEventListener('click', (ev) => icClick(d, ev));
  body.addEventListener('input', (ev) => icInput(d, ev));
  body.addEventListener('change', (ev) => icInput(d, ev));
  body.addEventListener('keydown', (ev) => icKey(d, ev));
  await icLoad(d, d._icFile || 'spawn.json');
}

async function icLoad(d, file) {
  d._icFile = file;
  d.querySelectorAll('[data-ic-file]').forEach((b) => b.classList.toggle('on', b.dataset.icFile === file));
  d.querySelector('.ic-intro').innerHTML = `<p class="muted">${ICES(IC_FILES[file].help)}</p>`;
  const list = d.querySelector('.ic-list');
  list.innerHTML = '<p class="muted pad">Cargando reglas…</p>';
  try {
    const r = await api(`${cfgBase()}/incontrol_rules?file=${encodeURIComponent(file)}`);
    if (r.rules === null) { list.innerHTML = `<p class="cfg-error pad">${ICES(r.problems[0])}. Revísalo a mano antes de editar.</p>`; d._icModel = null; return; }
    d._icModel = { file, rules: r.rules, cat: r.catalog, dirty: false };
    icRender(d);
  } catch (e) { list.innerHTML = `<p class="cfg-error pad">No se pudieron leer las reglas: ${ICES(e.message)}</p>`; }
}

// Filas que se ven en una regla: [clave, tipo] según el archivo.
function icKeys(file, rule, cat) {
  if (file === 'spawner.json') {
    return { root: Object.keys(rule).filter((k) => k !== 'conditions').map((k) => [k, cat.root[k] || 'S']),
             conds: Object.entries(rule.conditions || {}).map(([k]) => [k, cat.conditions[k] || 'S']) };
  }
  const all = Object.keys(rule).map((k) => [k, (cat.conditions || {})[k] || (cat.actions || {})[k] || (cat.meta || {})[k] || 'S']);
  return { meta: all.filter(([k]) => k === 'when' || k === 'result' || k === 'continue'),
           conds: all.filter(([k]) => !['when', 'result', 'continue'].includes(k) && (cat.conditions || {})[k]),
           acts: all.filter(([k]) => !['when', 'result', 'continue'].includes(k) && !(cat.conditions || {})[k]) };
}

function icRender(d) {
  const m = d._icModel;
  const list = d.querySelector('.ic-list');
  if (!m.rules.length) { list.innerHTML = `<p class="muted pad">Todavía no hay reglas en este archivo.</p><button type="button" class="btn primary" data-ic="add">Añadir regla</button>`; return; }
  list.innerHTML = m.rules.map((rule, i) => ruleHTML(m.file, rule, i, m.cat)).join('') +
    `<button type="button" class="btn primary ic-add" data-ic="add">Añadir regla</button>`;
  icSaveState(d);
}

function ruleHTML(file, rule, i, cat) {
  const k = icKeys(file, rule, cat);
  const rowAdd = (group) => `<div class="ic-add-row"><select class="ic-pick" aria-label="Añadir ${group}">${optionsFor(file, group, cat, rule)}</select><button type="button" class="btn" data-ic="addrow" data-r="${i}" data-group="${group}">Añadir</button></div>`;
  const rows = (list, group) => list.map(([key, t]) => rowHTML(i, key, t, rule, group, file)).join('');
  let body;
  if (file === 'spawner.json') {
    body = `<div class="ic-sec"><h5>Qué genera</h5>${rows(k.root, 'root')}${rowAdd('root')}</div>
            <div class="ic-sec"><h5>Dónde y cuándo (condiciones)</h5>${rows(k.conds, 'conds')}${rowAdd('conds')}</div>`;
  } else {
    body = `${file === 'spawn.json' ? `<div class="ic-sec"><h5>Cuándo y resultado</h5>${rows(k.meta, 'meta')}${rowAdd('meta')}</div>` : ''}
            <div class="ic-sec"><h5>Condiciones (todas deben cumplirse)</h5>${rows(k.conds, 'conds')}${rowAdd('conds')}</div>
            ${file === 'spawn.json' || file === 'loot.json' ? `<div class="ic-sec"><h5>Acciones</h5>${rows(k.acts, 'acts')}${rowAdd('acts')}</div>` : ''}`;
  }
  return `
    <article class="ic-rule" data-r="${i}">
      <header class="ic-rule-head"><h4>Regla ${i + 1}</h4>
        <span class="ic-rule-tools">
          <button type="button" class="link-btn" data-ic="up" data-r="${i}" aria-label="Subir">↑</button>
          <button type="button" class="link-btn" data-ic="down" data-r="${i}" aria-label="Bajar">↓</button>
          <button type="button" class="link-btn" data-ic="json" data-r="${i}">Ver JSON</button>
          <button type="button" class="link-btn danger" data-ic="del" data-r="${i}">Borrar</button>
        </span></header>
      ${body}
      <pre class="ic-json" hidden>${ICES(JSON.stringify(rule, null, 2))}</pre>
    </article>`;
}

function optionsFor(file, group, cat, rule) {
  const used = new Set(Object.keys(rule).concat(rule.conditions ? Object.keys(rule.conditions) : []));
  const names = (obj) => Object.keys(obj || {}).filter((n) => !used.has(n));
  let list;
  if (group === 'root') list = names(cat.root);
  else if (group === 'conds') list = names(cat.conditions);
  else if (group === 'acts') list = names(cat.actions);
  else list = names(cat.meta);
  return `<option value="">Elige una opción…</option>` + list.map((n) => `<option value="${ICES(n)}">${ICES(humanKey(n))} (${ICES(n)})</option>`).join('');
}

function rowHTML(i, key, type, rule, group, file) {
  const val = group === 'conds' && file === 'spawner.json' ? (rule.conditions || {})[key] : rule[key];
  const inner = `data-r="${i}" data-k="${ICES(key)}" data-t="${ICES(type)}" data-g="${group}"`;
  return `
    <div class="ic-row">
      <div class="ic-row-head"><span class="ic-key" title="${ICES(key)}">${ICES(humanKey(key))}</span><button type="button" class="link-btn danger" data-ic="delrow" ${inner}>Quitar</button></div>
      ${IC_HELP[key] ? `<p class="muted small">${ICES(IC_HELP[key])}</p>` : ''}
      ${valueHTML(key, type, val, inner)}
    </div>`;
}

function valueHTML(key, type, val, attrs) {
  if (IC_ENUM[key]) return `<select ${attrs} aria-label="${ICES(humanKey(key))}">${IC_ENUM[key].map((o) => `<option${o === val ? ' selected' : ''}>${o}</option>`).join('')}</select>`;
  if (type === 'B') return `<label class="switch"><input type="checkbox" ${attrs} ${val ? 'checked' : ''}><span class="track" aria-hidden="true"><span class="knob"></span></span><span class="switch-text">${val ? 'Sí' : 'No'}</span></label>`;
  if (type === 'I' || type === 'F') return `<input type="number" ${attrs} value="${ICES(val ?? '')}" step="${type === 'I' ? 1 : 'any'}" aria-label="${ICES(humanKey(key))}">`;
  if (type === 'S/[S]' || type === '[S]' || type === 'S/[S]/JSON' || type === 'S/I/JSON') {
    const items = Array.isArray(val) ? val : (val !== undefined && typeof val === 'string' ? [val] : []);
    return `<div class="cfg-chips ic-chips" ${attrs}>${items.map((v, n) => `<span class="cfg-chip">${ICES(v)}<button type="button" class="cfg-chip-x" data-ic="chipx" data-n="${n}" ${attrs} aria-label="Quitar ${ICES(v)}">×</button></span>`).join('')}<input type="text" class="cfg-chip-input" data-chip ${attrs} placeholder="Escribe y pulsa Intro" aria-label="Añadir valor"></div>`;
  }
  if (type === 'JSON' || type === 'JSON/[JSON]' || type === '[JSON]') return `<textarea rows="3" class="ic-json-in" ${attrs} spellcheck="false" aria-label="${ICES(humanKey(key))}">${ICES(val === undefined ? '' : JSON.stringify(val, null, 2))}</textarea>`;
  return `<input type="text" ${attrs} value="${ICES(val ?? '')}" aria-label="${ICES(humanKey(key))}">`;
}

// Escribe el valor de una fila en el modelo. Los campos JSON se validan al escribir.
function setRowValue(d, el, raw, checked) {
  const m = d._icModel;
  const i = +el.dataset.r, key = el.dataset.k, type = el.dataset.t, group = el.dataset.g;
  const rule = m.rules[i];
  let v;
  if (type === 'B') v = checked;
  else if (type === 'I') v = raw === '' ? undefined : parseInt(raw, 10);
  else if (type === 'F') v = raw === '' ? undefined : parseFloat(raw);
  else if (type.includes('JSON')) {
    try { v = JSON.parse(raw || 'null'); el.classList.remove('bad'); } catch (e) { el.classList.add('bad'); return; }
  } else v = raw;
  const target = group === 'conds' && m.file === 'spawner.json' ? (rule.conditions ||= {}) : rule;
  if (v === undefined || v === null || v === '') delete target[key]; else target[key] = v;
  m.dirty = true;
  icSaveState(d);
}

function icInput(d, ev) {
  const el = ev.target;
  if (!d._icModel || el.dataset.r === undefined || el.dataset.k === undefined) return;
  if (el.dataset.chip !== undefined) return;     // las listas se confirman con Intro o al perder el foco
  setRowValue(d, el, el.type === 'checkbox' ? '' : el.value, el.checked);
  if (el.type === 'checkbox') el.closest('.switch').querySelector('.switch-text').textContent = el.checked ? 'Sí' : 'No';
}

function icKey(d, ev) {
  const el = ev.target;
  if (ev.key !== 'Enter' || !el.matches('[data-chip]') || !d._icModel) return;
  ev.preventDefault();
  const v = el.value.trim(); if (!v) return;
  const i = +el.dataset.r, key = el.dataset.k, group = el.dataset.g;
  const rule = d._icModel.rules[i];
  const target = group === 'conds' && d._icModel.file === 'spawner.json' ? (rule.conditions ||= {}) : rule;
  const cur = Array.isArray(target[key]) ? target[key] : (typeof target[key] === 'string' ? [target[key]] : []);
  target[key] = [...cur, v];
  d._icModel.dirty = true;
  icRender(d);
  d.querySelector(`.ic-row [data-r="${i}"][data-k="${CSS.escape(key)}"][data-chip]`)?.focus();
}

function icClick(d, ev) {
  const b = ev.target.closest('[data-ic], [data-ic-file]');
  if (!b || !d._icModel) return;
  if (b.dataset.icFile) return icLoad(d, b.dataset.icFile);
  const m = d._icModel, act = b.dataset.ic, i = +b.dataset.r;
  if (act === 'add') { m.rules.push(m.file === 'spawner.json' ? { mob: 'minecraft:zombie', conditions: { dimension: 'minecraft:overworld' } } : { result: 'allow' }); m.dirty = true; return icRender(d); }
  if (act === 'del') { if (!confirm('¿Borrar esta regla?')) return; m.rules.splice(i, 1); m.dirty = true; return icRender(d); }
  if (act === 'up' && i > 0) { [m.rules[i - 1], m.rules[i]] = [m.rules[i], m.rules[i - 1]]; m.dirty = true; return icRender(d); }
  if (act === 'down' && i < m.rules.length - 1) { [m.rules[i + 1], m.rules[i]] = [m.rules[i], m.rules[i + 1]]; m.dirty = true; return icRender(d); }
  if (act === 'json') { const pre = b.closest('.ic-rule').querySelector('.ic-json'); pre.hidden = !pre.hidden; return; }
  if (act === 'delrow') {
    const key = b.dataset.k, group = b.dataset.g, rule = m.rules[i];
    if (group === 'conds' && m.file === 'spawner.json') delete rule.conditions[key]; else delete rule[key];
    m.dirty = true; return icRender(d);
  }
  if (act === 'chipx') {
    const key = b.dataset.k, group = b.dataset.g, rule = m.rules[i];
    const target = group === 'conds' && m.file === 'spawner.json' ? rule.conditions : rule;
    const list = [...target[key]]; list.splice(+b.dataset.n, 1);
    if (list.length) target[key] = list; else delete target[key];
    m.dirty = true; return icRender(d);
  }
  if (act === 'addrow') {
    const sel = b.parentElement.querySelector('.ic-pick');
    const key = sel.value; if (!key) return;
    const group = b.dataset.group, rule = m.rules[i];
    const type = (group === 'root' ? m.cat.root : group === 'conds' ? m.cat.conditions : group === 'acts' ? m.cat.actions : m.cat.meta)[key] || 'S';
    const seed = type === 'B' ? false : type === 'I' || type === 'F' ? 0 : type.includes('JSON') ? {} : type.includes('[') ? [] : '';
    if (group === 'conds' && m.file === 'spawner.json') (rule.conditions ||= {})[key] = seed; else rule[key] = seed;
    m.dirty = true; return icRender(d);
  }
}

function icSaveState(d) {
  const m = d._icModel;
  const n = m ? m.rules.length : 0;
  const bad = m ? validateLocal(m) : [];
  const status = d.querySelector('.cfg-status');
  if (status) {
    status.textContent = bad.length ? bad[0] : (m && m.dirty ? 'Cambios sin guardar' : `${n} ${n === 1 ? 'regla' : 'reglas'}`);
    status.className = `cfg-status muted${bad.length ? ' bad' : m && m.dirty ? ' pending' : ''}`;
  }
  const btn = d.querySelector('.cfg-save');
  if (btn) btn.disabled = !(m && m.dirty) || bad.length > 0;
}

// Comprobación rápida en el navegador; el servidor vuelve a validar al guardar.
function validateLocal(m) {
  const out = [];
  m.rules.forEach((r, i) => {
    if (m.file === 'spawner.json') {
      if (!r.mob) out.push(`Regla ${i + 1}: falta el mob`);
      if (!r.conditions || !r.conditions.dimension) out.push(`Regla ${i + 1}: falta la dimensión`);
      if (r.persecond !== undefined && (r.persecond <= 0 || r.persecond > 1)) out.push(`Regla ${i + 1}: la probabilidad por segundo va de 0 a 1`);
    }
  });
  return out;
}

async function saveRules(d) {
  const m = d._icModel;
  const btn = d.querySelector('.cfg-save');
  btn.disabled = true;
  try {
    await api(`${cfgBase()}/incontrol_rules_save`, { method: 'POST', body: { file: m.file, rules: m.rules } });
    m.dirty = false;
    toast('Reglas guardadas. Reinicia el servidor para aplicarlas.', 'ok');
    icSaveState(d);
  } catch (e) {
    toast(e.message || String(e), 'error');
    btn.disabled = false;
    const status = d.querySelector('.cfg-status');
    if (status) { status.textContent = e.message || String(e); status.className = 'cfg-status bad'; }
  }
}
