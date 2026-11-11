/* Configuración de mods: formulario por tarjetas. Cada opción se edita con un control según su tipo. */

const cfgEsc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const cfgBase = () => `/api/servers/${encodeURIComponent(current().name)}`;

// Textos en español para los mods que conocemos. Lo que no esté aquí se deriva del nombre de la clave.
const MOD_UI = {
  incontrol: {
    title: 'InControl',
    subtitle: 'Controla cómo aparecen los mobs y cuándo se activan las reglas.',
    sections: { general: 'General', common: 'Común', worldGen: 'Generación del mundo' },
    fields: {
      cacheRetentionTicks: { label: 'Duración de la caché', help: 'Cuántos ticks se guarda el recuento de mobs antes de volver a calcularlo. Con 0 se recalcula en cada tick: más exacto, pero más lento.', unit: 'ticks' },
      perPlayerRadius: { label: 'Radio por jugador', help: 'Distancia máxima, en bloques, para buscar al jugador más cercano cuando una regla depende de jugadores.', unit: 'bloques' },
    },
  },
};
const MOD_WORDS = { ticks: 'ticks', radius: 'radio', cache: 'caché', player: 'jugador', max: 'máximo', min: 'mínimo', enable: 'activar', enabled: 'activado', spawn: 'aparición', count: 'recuento', retention: 'duración', distance: 'distancia', time: 'tiempo', delay: 'retraso', chance: 'probabilidad', limit: 'límite', size: 'tamaño', amount: 'cantidad', speed: 'velocidad', damage: 'daño', health: 'vida', experience: 'experiencia', loot: 'botín', drop: 'caída', level: 'nivel', simulation: 'simulación', view: 'visión', allow: 'permitir', disable: 'desactivar', blacklist: 'lista negra', whitelist: 'lista blanca', denylist: 'lista de bloqueo' };

function humanize(key) {
  const words = key.replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/[_\-.]+/g, ' ').toLowerCase().split(' ').filter(Boolean);
  const text = words.map((w) => MOD_WORDS[w] || w).join(' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}
const sectionLabel = (modid, sec) => (MOD_UI[modid]?.sections || {})[sec] || humanize(sec);

function parseDefault(type, raw) {
  if (raw === null || raw === undefined || raw === '') return undefined;
  if (type === 'bool') return raw === 'true';
  if (type === 'int') return parseInt(raw, 10);
  if (type === 'float') return parseFloat(raw);
  if (type === 'str') return raw.replace(/^"|"$/g, '');
  if (type === 'list') { try { return JSON.parse(raw); } catch (e) { return undefined; } }
  return undefined;
}

// Abre el panel con el primer mod de la lista; si hay varios, se cambia con las píldoras de arriba.
async function openConfigPanel(prompts, modid) {
  if (!prompts || !prompts.length) return;
  const pick = prompts.find((p) => p.modid === modid) || prompts[0];
  const ui = MOD_UI[pick.modid] || {};
  const pills = prompts.length > 1
    ? `<div class="cfg-mods" role="tablist" aria-label="Mods con configuración">${prompts.map((p) => `<button type="button" role="tab" class="cfg-mod${p.modid === pick.modid ? ' on' : ''}" data-modid="${cfgEsc(p.modid)}" aria-selected="${p.modid === pick.modid}">${cfgEsc((MOD_UI[p.modid] || {}).title || p.modid)}</button>`).join('')}</div>`
    : '';
  const d = openDialog(`
    <div class="cfg">
      <header class="cfg-head">
        <div class="cfg-title">
          <h2>${cfgEsc(ui.title || pick.modid)}</h2>
          <p class="muted">${cfgEsc(ui.subtitle || 'Opciones de configuración de este mod.')}${ui.subtitle ? '' : ' Los textos de ayuda vienen del mod (en inglés).'}</p>
        </div>
        ${pills}
      </header>
      <div class="cfg-tools">
        <input type="search" class="cfg-search" placeholder="Buscar una opción" aria-label="Buscar una opción">
        <label class="cfg-check"><input type="checkbox" class="cfg-tech"> Mostrar nombres técnicos</label>
        <select class="cfg-file" aria-label="Archivo de configuración"></select>
      </div>
      <div class="cfg-body" aria-live="polite"><p class="muted pad">Cargando…</p></div>
      <footer class="cfg-foot">
        <span class="cfg-status muted" role="status"></span>
        <label class="cfg-auto"><input type="checkbox" class="cfg-autochk" ${pick.auto ? 'checked' : ''}> Abrir al detectar este mod</label>
        <form method="dialog" class="cfg-close"><button class="btn" value="cancel">Cerrar</button></form>
        <button class="btn primary cfg-save" type="button" disabled>Guardar cambios</button>
      </footer>
    </div>`, true);
  d.dataset.modid = pick.modid;
  d.classList.add('cfg-dialog');
  d._files = pick.files;
  d._prompts = prompts;

  d.querySelector('.cfg-autochk').addEventListener('change', async (ev) => {
    try { await api(`${cfgBase()}/mod_config_auto`, { method: 'POST', body: { modid: d.dataset.modid, on: ev.target.checked } }); }
    catch (e) { ev.target.checked = !ev.target.checked; toast(e.message || String(e), 'error'); }
  });
  d.querySelector('.cfg-tech').addEventListener('change', (ev) => d.classList.toggle('show-tech', ev.target.checked));
  d.querySelector('.cfg-search').addEventListener('input', (ev) => filterCards(d, ev.target.value));
  d.querySelector('.cfg-save').addEventListener('click', () => saveConfig(d));
  const body = d.querySelector('.cfg-body');   // una sola vez: los controles se reconstruyen dentro
  body.addEventListener('input', (ev) => d._fields && onInput(d, ev));
  body.addEventListener('change', (ev) => d._fields && onInput(d, ev));
  body.addEventListener('click', (ev) => d._fields && onClick(d, ev));
  d.addEventListener('click', (ev) => {
    const pill = ev.target.closest('.cfg-mod');
    if (pill) { d.close(); openConfigPanel(prompts, pill.dataset.modid); }
  });
  const sel = d.querySelector('.cfg-file');
  if (pick.files.length > 1) {
    sel.innerHTML = pick.files.map((f) => `<option value="${cfgEsc(f)}">${cfgEsc(f)}</option>`).join('');
    sel.addEventListener('change', () => loadConfigFile(d, sel.value));
  } else sel.hidden = true;
  await loadConfigFile(d, pick.files[0]);
}

async function loadConfigFile(d, file) {
  d.dataset.file = file;
  d.querySelector('.cfg-file').value = file;
  const body = d.querySelector('.cfg-body');
  body.innerHTML = '<p class="muted pad">Cargando…</p>';
  setStatus(d, '');
  try {
    const r = await api(`${cfgBase()}/mod_config_read?file=${encodeURIComponent(file)}`);
    d.dataset.kind = r.kind;
    if (r.kind === 'toml') buildForm(d, r.entries);
    else buildJson(d, r);
  } catch (e) { body.innerHTML = `<p class="cfg-error pad">No se pudo leer el archivo: ${cfgEsc(e.message)}</p>`; }
}

function buildForm(d, entries) {
  const modid = d.dataset.modid;
  d._fields = entries.map((e, i) => {
    const r = e.range ? e.range.split('~').map((x) => parseFloat(x.trim())) : null;
    return { i, section: e.section || 'general', key: e.key, type: e.type, original: e.value, value: e.value,
             help: e.description, range: r && r.length === 2 && r.every(Number.isFinite) ? r : null,
             allowed: e.allowed ? e.allowed.split(',').map((x) => x.trim()).filter(Boolean) : null,
             def: parseDefault(e.type, e.default), defRaw: e.default };
  });
  const fields = d._fields;
  if (!fields.length) { d.querySelector('.cfg-body').innerHTML = '<p class="muted pad">Este archivo no tiene opciones que se puedan editar.</p>'; updateSave(d); return; }
  const groups = {};
  for (const f of fields) (groups[f.section] ||= []).push(f);
  const label = (f) => (MOD_UI[modid]?.fields || {})[f.key] || {};
  d.querySelector('.cfg-body').innerHTML = Object.entries(groups).map(([sec, list]) => `
    <section class="cfg-group" data-section="${cfgEsc(sec)}">
      <h3 class="cfg-group-title">${cfgEsc(sectionLabel(modid, sec))}</h3>
      <div class="cfg-grid">${list.map((f) => cardHTML(modid, f, label(f))).join('')}</div>
    </section>`).join('') + '<p class="cfg-empty muted pad" hidden>Ninguna opción coincide con la búsqueda.</p>';
  updateSave(d);
}

function cardHTML(modid, f, lab) {
  // Una clave de una sola palabra («enabled») no dice nada por sí sola: se añade su sección.
  const generic = !lab.label && humanize(f.key).split(' ').length === 1 && f.section !== 'general';
  const title = lab.label || (generic ? `${humanize(f.key)} · ${sectionLabel(modid, f.section).toLowerCase()}` : humanize(f.key));
  const help = lab.help || f.help || '';
  const bits = [];
  if (f.def !== undefined) bits.push(`Por defecto: ${f.type === 'list' ? (f.def.length ? f.def.join(', ') : 'vacía') : f.type === 'bool' ? (f.def ? 'activado' : 'desactivado') : f.def}`);
  if (f.range) bits.push(`Entre ${f.range[0]} y ${f.range[1]}${lab.unit ? ' ' + lab.unit : ''}`);
  if (f.allowed && f.allowed.length > 5) bits.push(`Valores: ${f.allowed.join(', ')}`);
  return `
    <article class="cfg-card" data-i="${f.i}">
      <div class="cfg-card-top">
        <div class="cfg-card-title">
          <h4>${cfgEsc(title)}</h4>
          <code class="cfg-key">${cfgEsc(f.key)}</code>
        </div>
        <span class="cfg-badge" hidden>Cambiado</span>
      </div>
      ${help ? `<p class="cfg-help">${cfgEsc(help)}</p>` : ''}
      <div class="cfg-control">${controlHTML(f)}</div>
      <div class="cfg-card-foot">
        <span class="cfg-hint muted small">${cfgEsc(bits.join(' · '))}</span>
        <button type="button" class="link-btn" data-reset="${f.i}" hidden>Restablecer</button>
      </div>
      <p class="cfg-error" hidden></p>
    </article>`;
}

function controlHTML(f) {
  const id = `cfg-f${f.i}`;
  if (f.type === 'bool') return `
    <label class="switch"><input type="checkbox" id="${id}" data-i="${f.i}" ${f.value ? 'checked' : ''}>
      <span class="track" aria-hidden="true"><span class="knob"></span></span><span class="switch-text">${f.value ? 'Activado' : 'Desactivado'}</span></label>`;
  if ((f.type === 'int' || f.type === 'float')) {
    const step = f.type === 'int' ? 1 : 'any';
    const lim = f.range ? ` min="${f.range[0]}" max="${f.range[1]}"` : '';
    const slider = f.range && (f.range[1] - f.range[0]) <= 100000
      ? `<input type="range" class="cfg-range" data-i="${f.i}" aria-label="Valor"${lim} step="${step}" value="${f.value}">` : '';
    return `<div class="cfg-numrow">${slider}<input type="number" id="${id}" data-i="${f.i}" value="${f.value}" step="${step}"${lim} aria-label="Valor" class="cfg-num"></div>`;
  }
  if (f.type === 'str' && f.allowed && f.allowed.length && f.allowed.length <= 5) return `
    <div class="cfg-seg" role="radiogroup" aria-label="Elige una opción">${f.allowed.map((o) => `<button type="button" role="radio" aria-checked="${o === f.value}" class="seg-btn${o === f.value ? ' on' : ''}" data-i="${f.i}" data-val="${cfgEsc(o)}">${cfgEsc(o)}</button>`).join('')}</div>`;
  if (f.type === 'str' && f.allowed && f.allowed.length) return `
    <select id="${id}" data-i="${f.i}" aria-label="Valor">${f.allowed.map((o) => `<option value="${cfgEsc(o)}"${o === f.value ? ' selected' : ''}>${cfgEsc(o)}</option>`).join('')}</select>`;
  if (f.type === 'str') return `<input type="text" id="${id}" data-i="${f.i}" value="${cfgEsc(f.value)}" aria-label="Valor">`;
  if (f.type === 'list') return `
    <div class="cfg-chips" data-i="${f.i}">
      ${f.value.map((v, n) => `<span class="cfg-chip">${cfgEsc(v)}<button type="button" class="cfg-chip-x" data-rm="${n}" aria-label="Quitar ${cfgEsc(v)}">×</button></span>`).join('')}
      <input type="text" class="cfg-chip-input" placeholder="Añadir y pulsa Intro" aria-label="Añadir un valor">
    </div>`;
  return `<code class="cfg-raw">${cfgEsc(f.value)}</code><span class="muted small block">Este valor solo se puede cambiar editando el archivo.</span>`;
}

function onInput(d, ev) {
  const el = ev.target;
  if (el.classList.contains('cfg-chip-input')) return;
  const i = el.dataset.i !== undefined ? +el.dataset.i : null;
  if (i === null) return;
  const f = d._fields[i];
  if (el.type === 'checkbox') f.value = el.checked;
  else if (f.type === 'int') f.value = el.value === '' ? NaN : parseInt(el.value, 10);
  else if (f.type === 'float') f.value = el.value === '' ? NaN : parseFloat(el.value);
  else f.value = el.value;
  if (el.type === 'range' || el.type === 'number') {
    const card = el.closest('.cfg-card');
    const other = card.querySelector(el.type === 'range' ? '.cfg-num' : '.cfg-range');
    if (other) other.value = el.value;
  }
  if (f.type === 'bool') el.closest('.switch').querySelector('.switch-text').textContent = f.value ? 'Activado' : 'Desactivado';
  refreshCard(d, i);
}

function onClick(d, ev) {
  const seg = ev.target.closest('.seg-btn');
  if (seg) {
    const i = +seg.dataset.i, f = d._fields[i];
    f.value = seg.dataset.val;
    seg.parentElement.querySelectorAll('.seg-btn').forEach((b) => { const on = b === seg; b.classList.toggle('on', on); b.setAttribute('aria-checked', on); });
    return refreshCard(d, i);
  }
  const rm = ev.target.closest('[data-rm]');
  if (rm) {
    const box = rm.closest('.cfg-chips'), i = +box.dataset.i, f = d._fields[i];
    f.value = f.value.filter((_, n) => n !== +rm.dataset.rm);
    buildChipsAndRefresh(d, i);
    return;
  }
  const reset = ev.target.closest('[data-reset]');
  if (reset) {
    const i = +reset.dataset.reset, f = d._fields[i];
    f.value = f.def !== undefined ? f.def : f.original;
    rebuildCard(d, i);
  }
}

// Las listas (chips) se añaden con Intro dentro del propio campo.
document.addEventListener('keydown', (ev) => {
  const inp = ev.target;
  if (!inp.classList || !inp.classList.contains('cfg-chip-input') || ev.key !== 'Enter') return;
  ev.preventDefault();
  const box = inp.closest('.cfg-chips'), dialog = inp.closest('dialog');
  const d = dialog && dialog.querySelector('.cfg') ? dialog : null;
  const v = inp.value.trim();
  if (!d || !v) return;
  const i = +box.dataset.i, f = d._fields[i];
  if (!f.value.includes(v)) f.value = [...f.value, v];
  buildChipsAndRefresh(d, i);
  const again = d.querySelector(`.cfg-chips[data-i="${i}"] .cfg-chip-input`);
  if (again) again.focus();
});

function buildChipsAndRefresh(d, i) { rebuildCard(d, i); }

function rebuildCard(d, i) {
  const f = d._fields[i];
  const old = d.querySelector(`.cfg-card[data-i="${i}"]`);
  if (!old) return;
  const tmp = document.createElement('div');
  tmp.innerHTML = cardHTML(d.dataset.modid, f, (MOD_UI[d.dataset.modid]?.fields || {})[f.key] || {});
  old.replaceWith(tmp.firstElementChild);
  refreshCard(d, i);
  if (f.type === 'list') d.querySelector(`.cfg-chips[data-i="${i}"] .cfg-chip-input`)?.focus();
}

function validate(f) {
  const v = f.value;
  if (f.type === 'int' || f.type === 'float') {
    if (typeof v !== 'number' || Number.isNaN(v)) return 'Escribe un número.';
    if (f.type === 'int' && !Number.isInteger(v)) return 'Debe ser un número entero.';
    if (f.range && (v < f.range[0] || v > f.range[1])) return `Debe estar entre ${f.range[0]} y ${f.range[1]}.`;
  }
  if (f.type === 'str' && f.allowed && f.allowed.length && !f.allowed.includes(v)) return 'Elige una de las opciones.';
  return '';
}

const changed = (f) => JSON.stringify(f.value) !== JSON.stringify(f.original);

function refreshCard(d, i) {
  const f = d._fields[i];
  const card = d.querySelector(`.cfg-card[data-i="${i}"]`);
  if (!card) return updateSave(d);
  const err = validate(f);
  card.classList.toggle('changed', changed(f));
  card.classList.toggle('invalid', !!err);
  card.querySelector('.cfg-badge').hidden = !changed(f);
  card.querySelector('[data-reset]').hidden = !changed(f);
  const p = card.querySelector('.cfg-error');
  p.hidden = !err; p.textContent = err;
  updateSave(d);
}

function filterCards(d, q) {
  const needle = q.trim().toLowerCase();
  let shown = 0;
  d.querySelectorAll('.cfg-card').forEach((c) => {
    const txt = c.textContent.toLowerCase();
    const ok = !needle || txt.includes(needle);
    c.hidden = !ok; if (ok) shown++;
  });
  d.querySelectorAll('.cfg-group').forEach((g) => { g.hidden = ![...g.querySelectorAll('.cfg-card')].some((c) => !c.hidden); });
  const empty = d.querySelector('.cfg-empty'); if (empty) empty.hidden = shown > 0;
}

function updateSave(d) {
  const fields = d._fields || [];
  const n = fields.filter(changed).length;
  const bad = fields.filter((f) => validate(f)).length;
  const btn = d.querySelector('.cfg-save');
  if (btn) btn.disabled = !n || bad > 0;
  if (d.dataset.kind === 'toml') setStatus(d, bad ? `${bad} ${bad === 1 ? 'valor no válido' : 'valores no válidos'}` : n ? `${n} ${n === 1 ? 'cambio sin guardar' : 'cambios sin guardar'}` : 'Sin cambios', bad ? 'bad' : n ? 'pending' : '');
}

function setStatus(d, text, tone = '') {
  const s = d.querySelector('.cfg-status');
  if (!s) return;
  s.textContent = text;
  s.className = `cfg-status muted${tone ? ' ' + tone : ''}`;
}

function buildJson(d, r) {
  d._fields = null;
  d.querySelector('.cfg-body').innerHTML = r.kind === 'json-invalido'
    ? `<p class="cfg-error pad">El archivo no es JSON válido, así que no se puede editar aquí.</p><pre class="cfg-raw">${cfgEsc(r.text)}</pre>`
    : `<div class="cfg-json"><p class="muted small">Edita el texto con cuidado: se comprueba que sea JSON válido antes de guardar.</p><textarea id="cfgJson" rows="18" spellcheck="false">${cfgEsc(r.text)}</textarea></div>`;
  const ta = d.querySelector('#cfgJson');
  if (ta) ta.addEventListener('input', () => { d.querySelector('.cfg-save').disabled = false; setStatus(d, 'Cambios sin guardar', 'pending'); });
  d.querySelector('.cfg-save').disabled = true;
  setStatus(d, r.kind === 'json-invalido' ? '' : 'Sin cambios');
}

async function saveConfig(d) {
  const file = d.dataset.file;
  let body;
  if (d.dataset.kind === 'toml') {
    const updates = d._fields.filter(changed).map((f) => ({ section: f.section, key: f.key, value: f.value }));
    if (!updates.length) return;
    body = { file, updates };
  } else body = { file, json_text: d.querySelector('#cfgJson').value };
  const btn = d.querySelector('.cfg-save');
  btn.disabled = true; setStatus(d, 'Guardando…');
  try {
    const r = await api(`${cfgBase()}/mod_config_save`, { method: 'POST', body });
    toast(r.changed ? 'Configuración guardada. Reinicia el servidor para aplicarla.' : 'No había cambios', 'ok');
    loadConfigFile(d, file);
  } catch (e) {
    toast(e.message || String(e), 'error');
    setStatus(d, e.message || String(e), 'bad');
    btn.disabled = false;
  }
}
