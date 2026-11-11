/* Configuración de mods: panel que se abre al detectar un mod con archivos de configuración. */

const cfgEsc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const cfgBase = () => `/api/servers/${encodeURIComponent(current().name)}`;

// Abre el panel con el primer mod de la lista; si hay varios, el desplegable permite cambiar de mod.
async function openConfigPanel(prompts, modid) {
  if (!prompts || !prompts.length) return;
  const pick = prompts.find((p) => p.modid === modid) || prompts[0];
  const choose = prompts.length > 1
    ? `<label class="cfg-pick">Mod <select id="cfgMod">${prompts.map((p) => `<option value="${cfgEsc(p.modid)}"${p.modid === pick.modid ? ' selected' : ''}>${cfgEsc(p.modid)}</option>`).join('')}</select></label>`
    : '';
  const d = openDialog(`
    <form method="dialog" class="cfg">
      <header class="cfg-head"><h2>Configuración · ${cfgEsc(pick.modid)}</h2>${choose}</header>
      <div id="cfgBody"><p class="muted pad">Cargando…</p></div>
      <footer class="cfg-foot">
        <span class="muted small" id="cfgNote"></span>
        <label class="small cfg-auto"><input type="checkbox" id="cfgAuto" ${pick.auto ? 'checked' : ''}> Abrir al detectar este mod</label>
        <button class="btn" value="cancel">Cerrar</button>
        <button class="btn primary" type="button" data-action="cfg-save">Guardar</button>
      </footer>
    </form>`, true);
  d.dataset.modid = pick.modid;
  d.querySelector('#cfgAuto').addEventListener('change', async (ev) => {
    try { await api(`${cfgBase()}/mod_config_auto`, { method: 'POST', body: { modid: pick.modid, on: ev.target.checked } }); }
    catch (e) { ev.target.checked = !ev.target.checked; toast(e.message || String(e), 'error'); }
  });
  const modSel = d.querySelector('#cfgMod');
  if (modSel) modSel.addEventListener('change', () => { d.remove(); openConfigPanel(prompts, modSel.value); });
  await loadConfigFile(d, pick.files[0]);
  if (pick.files.length > 1) {
    const sel = document.createElement('select'); sel.setAttribute('aria-label', 'Archivo');
    sel.innerHTML = pick.files.map((f) => `<option value="${cfgEsc(f)}">${cfgEsc(f)}</option>`).join('');
    sel.addEventListener('change', () => loadConfigFile(d, sel.value));
    d.querySelector('.cfg-head').append(sel);
  }
}

async function loadConfigFile(d, file) {
  d.dataset.file = file;
  const body = d.querySelector('#cfgBody');
  body.innerHTML = '<p class="muted pad">Cargando…</p>';
  try {
    const r = await api(`${cfgBase()}/mod_config_read?file=${encodeURIComponent(file)}`);
    d.dataset.kind = r.kind;
    body.innerHTML = r.kind === 'toml' ? tomlFormHTML(r.entries) : jsonFormHTML(r);
    d.querySelector('#cfgNote').textContent = 'Los cambios se aplican al reiniciar el servidor.';
  } catch (e) { body.innerHTML = `<p class="pad">No se pudo leer el archivo: ${cfgEsc(e.message)}</p>`; }
}

function tomlFormHTML(entries) {
  if (!entries.length) return '<p class="muted pad">Este archivo no tiene opciones editables.</p>';
  const sections = {};
  for (const e of entries) (sections[e.section || 'general'] ||= []).push(e);
  return Object.entries(sections).map(([sec, list]) => `
    <section class="cfg-sec"><h3>${cfgEsc(sec)}</h3>
      ${list.map(fieldHTML).join('')}
    </section>`).join('');
}

function fieldHTML(e) {
  const id = `cfg-${cfgEsc(e.section)}-${cfgEsc(e.key)}`.replace(/[^A-Za-z0-9_-]/g, '_');
  const meta = [e.default !== null && e.default !== undefined ? `por defecto: ${e.default}` : '', e.range ? `rango: ${e.range}` : ''].filter(Boolean).join(' · ');
  const data = `data-section="${cfgEsc(e.section)}" data-key="${cfgEsc(e.key)}" data-type="${e.type}" data-orig="${cfgEsc(JSON.stringify(e.value))}"`;
  let control;
  if (e.type === 'bool') control = `<input type="checkbox" id="${id}" ${data} ${e.value ? 'checked' : ''}>`;
  else if ((e.type === 'int' || e.type === 'float') ) {
    const r = e.range ? e.range.split('~').map((x) => x.trim()) : [];
    control = `<input type="number" id="${id}" ${data} value="${cfgEsc(e.value)}" step="${e.type === 'int' ? 1 : 'any'}"${r[0] !== undefined ? ` min="${cfgEsc(r[0])}"` : ''}${r[1] !== undefined ? ` max="${cfgEsc(r[1])}"` : ''}>`;
  } else if (e.type === 'str' && e.allowed) {
    const opts = e.allowed.split(',').map((x) => x.trim()).filter(Boolean);
    control = `<select id="${id}" ${data}>${opts.map((o) => `<option value="${cfgEsc(o)}"${o === e.value ? ' selected' : ''}>${cfgEsc(o)}</option>`).join('')}</select>`;
  } else if (e.type === 'str') control = `<input type="text" id="${id}" ${data} value="${cfgEsc(e.value)}">`;
  else if (e.type === 'list') control = `<textarea id="${id}" ${data} rows="${Math.min(6, Math.max(2, e.value.length))}" placeholder="Un valor por línea">${cfgEsc((e.value || []).join('\n'))}</textarea>`;
  else control = `<code class="cfg-raw">${cfgEsc(e.value)}</code><span class="muted small"> (no editable desde el panel)</span>`;
  return `
    <div class="cfg-field${e.type === 'raw' ? ' cfg-ro' : ''}">
      <label for="${id}"><strong>${cfgEsc(e.key)}</strong></label>
      ${e.description ? `<p class="muted small">${cfgEsc(e.description)}</p>` : ''}
      ${control}
      ${e.allowed ? `<span class="muted small">Valores: ${cfgEsc(e.allowed)}</span>` : ''}
      ${meta ? `<span class="muted small block">${cfgEsc(meta)}</span>` : ''}
    </div>`;
}

function jsonFormHTML(r) {
  if (r.kind === 'json-invalido') return `<p class="pad">El archivo no es JSON válido; se muestra sin cambios:</p><pre class="cfg-raw">${cfgEsc(r.text)}</pre>`;
  return `<label class="cfg-field"><span class="muted small">Edita el JSON. Se valida antes de guardar.</span>
    <textarea id="cfgJson" rows="18" spellcheck="false">${cfgEsc(r.text)}</textarea></label>`;
}

// Lee los valores del formulario y devuelve solo los que cambiaron.
function collectUpdates(d) {
  const out = [];
  for (const el of d.querySelectorAll('[data-key]')) {
    const type = el.dataset.type;
    if (type === 'raw') continue;
    let value;
    if (type === 'bool') value = el.checked;
    else if (type === 'int') value = el.value === '' ? NaN : parseInt(el.value, 10);
    else if (type === 'float') value = el.value === '' ? NaN : parseFloat(el.value);
    else if (type === 'list') value = el.value.split('\n').map((x) => x.trim()).filter(Boolean);
    else value = el.value;
    if (Number.isNaN(value)) throw new Error(`«${el.dataset.key}» está vacío`);
    if (el.dataset.orig === JSON.stringify(value)) continue;   // solo se envía lo que cambió
    out.push({ section: el.dataset.section, key: el.dataset.key, value });
  }
  return out;
}

async function saveConfig(el) {
  const d = el.closest('dialog');
  const file = d.dataset.file;
  let body;
  try {
    if (d.dataset.kind === 'toml') body = { file, updates: collectUpdates(d) };
    else body = { file, json_text: d.querySelector('#cfgJson').value };
    const r = await api(`${cfgBase()}/mod_config_save`, { method: 'POST', body });
    toast(r.changed ? 'Configuración guardada. Reinicia el servidor para aplicarla.' : 'No había cambios', 'ok');
  } catch (e) { toast(e.message || String(e), 'error'); }
}
