'use strict';

/* ---------- utilidades ---------- */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmtSize = (b) => (b == null ? '' : b >= 1048576 ? (b / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(b / 1024)) + ' KB');
const fmtNum = (n) => (n >= 1e6 ? (n / 1e6).toFixed(1) + ' M' : n >= 1e3 ? (n / 1e3).toFixed(1) + ' k' : String(n ?? ''));
const fmtTime = (ts) => new Date(ts * 1000).toLocaleString('es', { dateStyle: 'short', timeStyle: 'medium' });
const fmtLeft = (ts) => {
  const s = Math.max(0, ts - Math.floor(Date.now() / 1000));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h} h ${m} min` : m ? `${m} min` : `${s} s`;
};

class ApiError extends Error {
  constructor(message, status, data) { super(message); this.status = status; this.data = data || {}; }
}

async function api(path, { method = 'GET', body } = {}) {
  const opts = { method, headers: {} };
  if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (r.status === 401 && path !== '/api/login') {
    state.me = null;
    renderLogin();
    throw new ApiError('Sesión caducada', 401);
  }
  if (!r.ok) throw new ApiError(data.error || `Error ${r.status}`, r.status, data);
  return data;
}

// Subida con progreso (fetch no informa del progreso de subida).
function upload(path, file, onProgress) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open('POST', path);
    x.setRequestHeader('X-Filename', encodeURIComponent(file.name));
    x.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    x.onload = () => {
      let d = {};
      try { d = JSON.parse(x.responseText); } catch { /* sin cuerpo */ }
      if (x.status === 401) { state.me = null; renderLogin(); }
      x.status >= 200 && x.status < 300 ? resolve(d) : reject(new ApiError(d.error || `Error ${x.status}`, x.status));
    };
    x.onerror = () => reject(new ApiError('Fallo de red durante la subida'));
    x.send(file);
  });
}

// Confirmación con el mismo sistema visual (sustituye a confirm() del navegador).
// Resuelve true solo si el usuario pulsa el botón de confirmar.
function askConfirm(title, message, { confirmLabel = 'Confirmar', danger = false } = {}) {
  return new Promise((resolve) => {
    const d = openDialog(`
      <form class="dlg confirm-dlg" method="dialog" role="alertdialog" aria-labelledby="confirmTitle" aria-describedby="confirmMsg">
        <header><h2 id="confirmTitle">${esc(title)}</h2></header>
        <p id="confirmMsg" class="muted">${esc(message)}</p>
        <div class="row end">
          <button class="btn" value="cancel">Cancelar</button>
          <button class="btn ${danger ? 'danger' : 'primary'}" value="ok">${esc(confirmLabel)}</button>
        </div>
      </form>`);
    $('button[value=cancel]', d).focus();
    d.addEventListener('close', () => resolve(d.returnValue === 'ok'));
  });
}

function toast(message, kind = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.textContent = message;
  $('#toasts').append(el);
  const ttl = kind === 'error' ? 7000 : 3500;
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 180); }, ttl);
}
const fail = (e) => { if (!(e instanceof ApiError && e.status === 401)) toast(e.message || String(e), 'error'); };

function openDialog(html, wide = false) {
  $$('dialog').forEach((d) => d.close());
  const d = document.createElement('dialog');
  if (wide) d.className = 'wide';
  d.innerHTML = html;
  d.addEventListener('close', () => { if (d.querySelector('[data-user]')) state.draft = null; d.inert = true; setTimeout(() => d.remove(), 160); });  // deja que acabe la salida de 120 ms
  document.body.append(d);
  d.showModal();
  return d;
}

/* ---------- estado ---------- */
const state = {
  me: null, icons: [], servers: [], view: { kind: 'empty' }, timers: [],
  modsPane: 'installed',
  search: { source: 'modrinth', q: '', results: null, loading: false, error: null },
  loader: localStorage.getItem('loader') || 'neoforge',
  version: localStorage.getItem('version') || '1.21.1',
};
state.dpPane = 'installed'; state.texPane = 'providers'; state.draft = null; state.tex = null;
const srvIcon = (name, size = 32) => (state.icons.includes(name)
  ? `<img class="srv-img" src="/assets/brand/servers/${name}.png" width="${size}" height="${size}" alt="">`
  : pixelIcon('orb', size));
const isAdmin = () => !!(state.me && state.me.is_admin);
const server = (name) => state.servers.find((s) => s.name === name);
const current = () => (state.view.kind === 'server' ? server(state.view.name) : null);
state.starting = {}; state.ledError = {};
const ledClass = (s) => {
  if (state.ledError[s.name]) return 'error';
  if (s.status.running) return 'on';
  if (state.starting[s.name] && state.starting[s.name] > Date.now()) return 'starting';
  return '';
};
// Al repintar con innerHTML los LED se recrean ya en su color final y su transición nunca arranca:
// se recuerda la clase anterior y se vuelve a poner la nueva tras forzar un reflujo.
function setHTMLKeepLeds(el, html) {
  const prev = {};
  $$('.led[data-led]', el).forEach((l) => { prev[l.dataset.led] = l.className; });
  el.innerHTML = html;
  $$('.led[data-led]', el).forEach((l) => {
    const old = prev[l.dataset.led];
    if (old && old !== l.className) { const now = l.className; l.className = old; void l.offsetWidth; l.className = now; }
  });
}
// Entrada escalonada de una lista solo en su primera carga (ver .rows.enter en el CSS).
const enterOnce = (el) => { if (!el) return; el.classList.add('enter'); setTimeout(() => el.classList.remove('enter'), 700); };
const clearTimers = () => { state.timers.forEach(clearInterval); state.timers = []; };
const every = (ms, fn) => state.timers.push(setInterval(() => { if (!document.hidden) fn(); }, ms));

/* ---------- login ---------- */
function renderLogin() {
  clearTimers();
  $('#app').innerHTML = `
    <div class="login">
      <form class="login-card" id="loginForm" autocomplete="on">
        <div class="brand big"><img class="brand-img" src="/assets/brand/modnex-logo.png" alt="Modnex" width="200" height="125"></div>
        <h1>Entrar al panel</h1>
        <label>Usuario<input name="username" autocomplete="username" required autofocus></label>
        <label>Contraseña<input name="password" type="password" autocomplete="current-password" required></label>
        <label id="otpRow" hidden>Código de verificación<input name="otp" inputmode="numeric" autocomplete="one-time-code" maxlength="20" placeholder="123456 o un código de recuperación"></label>
        <p class="form-error" id="loginError" role="alert"></p>
        <button class="btn primary" type="submit">Entrar</button>
      </form>
    </div>`;
}

async function doLogin(form) {
  const err = $('#loginError');
  err.textContent = '';
  try {
    const body = { username: form.username.value.trim(), password: form.password.value };
    if (!$('#otpRow').hidden) body.otp = form.otp.value.trim();
    await api('/api/login', { method: 'POST', body });
    await boot();
  } catch (e) {
    err.textContent = e.message;
    if (e.data && e.data.need_otp) { $('#otpRow').hidden = false; form.otp.value = ''; form.otp.focus(); return; }  // falta el segundo factor
    form.password.value = ''; if (!$('#otpRow').hidden) form.otp.value = ''; form.password.focus();
  }
}

/* ---------- carcasa y navegación ---------- */
function parseHash() {
  const parts = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  if (parts[0] === 'users' && isAdmin()) return { kind: 'users' };
  if (parts[0] === 'audit' && isAdmin()) return { kind: 'audit' };
  if (parts[0] === 'p' && parts[1]) return { kind: 'plugin', id: parts[1] };
  if (parts[0] === 'm' && parts[1] && parts[2]) return { kind: 'mod', source: parts[1], id: decodeURIComponent(parts[2]) };
  if (parts[0] === 's' && parts[1]) return { kind: 'server', name: decodeURIComponent(parts[1]), tab: parts[2] };
  return { kind: 'auto' };
}

function route() {
  let v = parseHash();
  if (v.kind === 'auto' || (v.kind === 'server' && !server(v.name))) {
    v = state.servers.length ? { kind: 'server', name: state.servers[0].name } : { kind: 'empty' };
  }
  state.view = v;
  renderSide();
  renderMain();
}

function sideHTML() {
  const v = state.view;
  // Los servidores con `parent` cuelgan de su padre si el usuario también lo ve; si no, van sueltos.
  const names = new Set(state.servers.map((s) => s.name));
  const isChild = (s) => s.parent && names.has(s.parent);
  const ordered = [];
  state.servers.filter((s) => !isChild(s)).forEach((s) => { ordered.push(s); state.servers.filter((c) => c.parent === s.name).forEach((c) => ordered.push(c)); });
  const items = ordered.map((s) => `
    <a class="srv-item${isChild(s) ? ' child' : ''}${v.kind === 'server' && v.name === s.name ? ' on' : ''}" href="#/s/${encodeURIComponent(s.name)}">
      <span class="tile sm">${srvIcon(s.icon, 34)}</span>
      <span class="srv-name">${esc(s.display_name)}</span>
      <span class="srv-meta"><span class="srv-state">${({ on: 'en marcha', starting: 'arrancando', error: 'error', '': 'parado' })[ledClass(s)]}</span></span>
      <span class="led ${ledClass(s)}" data-led="side:${esc(s.name)}" aria-hidden="true"></span>
    </a>`).join('') || '<p class="muted pad">Sin servidores asignados.</p>';
  const admin = isAdmin() ? `
    <p class="side-title">Administración</p>
    <a class="nav-item${v.kind === 'users' ? ' on' : ''}" href="#/users">Usuarios y permisos</a>
    <a class="nav-item${v.kind === 'audit' ? ' on' : ''}" href="#/audit">Actividad</a>` : '';
  const pages = ((state.plugins && state.plugins.pages) || []).filter((p) => !p.admin || isAdmin())
    .map((p) => `<a class="nav-item${v.kind === 'plugin' && v.id === p.id ? ' on' : ''}" href="#/p/${esc(p.id)}">${esc(p.label)}</a>`).join('');
  const light = document.documentElement.dataset.theme === 'light';
  return `
    <div class="brand"><img class="brand-img" src="/assets/brand/modnex-mark.png" alt="" width="34" height="28"><span>MODNEX</span></div>
    <nav class="side-nav" aria-label="Servidores">
      <p class="side-title">Servidores</p>${isAdmin() ? '<button class="btn sm new-srv" data-action="new-server">+ Nuevo servidor</button>' : ''}${items}${admin}${pages ? `<p class="side-title">Cuenta</p>${pages}` : ''}
    </nav>
    <div class="side-foot">
      <div class="who"><strong>${esc(state.me.username)}</strong><span class="muted">${isAdmin() ? 'Administrador' : 'Usuario'}</span></div>
      <div class="foot-actions">
        <button class="btn ghost sm" data-action="theme" aria-label="Cambiar tema">${light ? 'Modo oscuro' : 'Modo claro'}</button>
        <button class="btn ghost sm" data-action="password">Contraseña</button>
        <button class="btn ghost sm" data-action="logout">Salir</button>
      </div>
    </div>`;
}

function renderShell() {
  $('#app').innerHTML = `<div class="shell"><aside class="side" id="side"></aside><main class="main" id="main" tabindex="-1"></main></div>`;
}
function renderSide() { const s = $('#side'); if (s) setHTMLKeepLeds(s, sideHTML()); }

function renderMain() {
  clearTimers();
  const v = state.view;
  $('#main').classList.toggle('wide', v.kind === 'mod');  // la ficha usa todo el ancho
  $('#main').classList.remove('srv');
  if (v.kind === 'server') return renderServer();
  if (v.kind === 'users') return renderUsers();
  if (v.kind === 'audit') return renderAudit();
  if (v.kind === 'mod') return renderModPage();
  if (v.kind === 'plugin') {
    const plug = window.ModnexPlugins && window.ModnexPlugins[v.id];
    const meta = ((state.plugins && state.plugins.pages) || []).find((p) => p.id === v.id);
    const body = $('#main');
    if (!plug || typeof plug.renderPage !== 'function' || !meta || (meta.admin && !isAdmin())) { body.innerHTML = '<div class="empty"><h1>Esta sección no está disponible</h1></div>'; return; }
    // El plugin recibe un contenedor propio y no #main: #main sobrevive al cambiar de vista, y los manejadores
    // (onclick, onsubmit…) que un plugin ate a lo que recibe seguirían activos en el resto del panel.
    body.innerHTML = '<div id="pluginPage"></div>';
    try { plug.renderPage($('#pluginPage')); } catch (e) { body.innerHTML = `<p class="muted">No se pudo mostrar esta sección: ${esc(e.message)}</p>`; }
    return;
  }
  $('#main').innerHTML = `
    <div class="empty">
      <h1>No tienes servidores asignados</h1>
      <p>Pide a un administrador que te dé acceso a uno o más servidores.</p>
    </div>`;
}

async function refreshServers() {
  try {
    state.servers = await api('/api/servers');
    state.servers.forEach((s) => { if (s.status.running) { delete state.starting[s.name]; delete state.ledError[s.name]; } });
    renderSide();
    const s = current();
    if (s && $('#srvHead')) setHTMLKeepLeds($('#srvHead'), headHTML(s));
  } catch (e) { fail(e); }
}

/* ---------- vista de servidor ---------- */
const GROUPS = [['operar', 'Operar'], ['contenido', 'Contenido'], ['distribuir', 'Distribuir'], ['proteger', 'Proteger'], ['mas', 'Más']];
function tabsFor(s) {
  const t = [];
  const add = (id, label, group) => t.push({ id, label, group });
  if (s.permissions.logs) add('logs', 'Consola', 'operar');
  if (s.permissions.players) add('players', 'Jugadores', 'operar');
  if (isAdmin()) add('props', 'Propiedades', 'operar'), add('settings', 'Ajustes', 'operar');
  if (s.permissions.mods && s.kind !== 'none') add('mods', s.kind === 'plugin' ? 'Plugins' : 'Mods', 'contenido');
  if (s.permissions.datapacks) add('datapacks', 'Datapacks', 'contenido');
  if (s.permissions.textures) add('textures', 'Texturas', 'contenido');
  if (isAdmin()) add('client', 'Cliente', 'distribuir');
  for (const p of (state.plugins && state.plugins.tabs) || []) if (p.perm === '*' ? (isAdmin() || Object.values(s.permissions).some(Boolean)) : p.perm ? (isAdmin() || s.permissions[p.perm]) : (!p.admin || isAdmin())) add('x-' + p.id, p.label, p.group || 'mas');
  const order = GROUPS.map(([g]) => g);
  t.sort((x, y) => order.indexOf(x.group) - order.indexOf(y.group));   // estable: dentro de cada grupo se conserva el orden
  if (t.length) t.unshift({ id: 'summary', label: 'Resumen', group: 'operar' });
  return t;
}

function headHTML(s) {
  const run = s.status.running;
  const canCtl = isAdmin() || !!(s.permissions && s.permissions.control);
  const ctl = canCtl ? (run
    ? `<button class="btn danger" data-action="stop">Parar servidor</button>`
    : `<button class="btn primary" data-action="start">Arrancar servidor</button>`) : '';
  const mem = isAdmin() && s.memory && s.memory.xmx ? ` · RAM ${esc(s.memory.xms || '?')}–${esc(s.memory.xmx)}` : '';
  return `
    <span class="tile lg">${srvIcon(s.icon, 52)}</span>
    <div class="head-text">
      <h1>${esc(s.display_name)}</h1>
      <p class="muted"><span class="led ${ledClass(s)}" data-led="head" aria-hidden="true"></span>${run ? 'En marcha' : state.starting[s.name] > Date.now() ? 'Arrancando…' : 'Parado'} · ${s.mods} mods${mem}${s.display_name !== s.name ? ` · carpeta ${esc(s.name)}` : ''}</p>
    </div>
    <div class="head-actions">${ctl}</div>`;
}

function renderServer() {
  const s = current();
  const tabs = tabsFor(s);
  if (!tabs.length) {
    const canCtl = isAdmin() || !!(s.permissions && s.permissions.control);
    $('#main').innerHTML = `${canCtl ? `<header class="srv-head" id="srvHead">${headHTML(s)}</header>` : ''}
      <div class="empty"><h1>${canCtl ? 'Solo puedes encender y apagar' : 'No tienes permisos'} en «${esc(s.display_name)}»</h1>
      <p class="muted">${canCtl ? 'No tienes acceso a logs, mods, datapacks, texturas ni jugadores de este servidor.' : 'Este servidor existe, pero aún no te han dado acceso a ninguna de sus secciones: logs, mods, datapacks, texturas, jugadores o encender y apagar.'}</p>
      <p class="muted">Pídele a quien administra el panel que active al menos un permiso.</p></div>`;
    return;
  }
  const tab = tabs.find((t) => t.id === state.view.tab) ? state.view.tab : tabs[0].id;
  state.view.tab = tab;
  const groupOf = (t) => t.group || 'mas';
  const activeGroup = groupOf(tabs.find((t) => t.id === tab));
  const groups = GROUPS.filter(([g]) => tabs.some((t) => groupOf(t) === g));
  const sub = tabs.filter((t) => groupOf(t) === activeGroup);
  const href = (id) => `#/s/${encodeURIComponent(s.name)}/${id}`;
  $('#main').classList.add('srv');
  $('#main').innerHTML = `
    <div class="srv-layout">
      <header class="srv-head" id="srvHead">${headHTML(s)}</header>
      <aside class="rail" id="rail" aria-label="Estado del servidor"><div id="railCore"></div><div id="railPlug"></div></aside>
      <nav class="groups" aria-label="Secciones del servidor">
        ${groups.map(([g, label]) => `<a class="group${g === activeGroup ? ' on' : ''}" href="${href(tabs.find((t) => groupOf(t) === g).id)}" ${g === activeGroup ? 'aria-current="true"' : ''}>${label}</a>`).join('')}
      </nav>
      ${sub.length > 1 ? `<nav class="tabs" aria-label="${esc(groups.find(([g]) => g === activeGroup)[1])}">
        ${sub.map((t) => `<a class="tab${t.id === tab ? ' on' : ''}" href="${href(t.id)}" ${t.id === tab ? 'aria-current="page"' : ''}>${t.label}</a>`).join('')}
      </nav>` : ''}
      <section class="tab-body" id="tabBody"></section>
    </div>`;
  placeInk($('.groups'), 'groups', 'all');
  placeInk($('.srv-layout > .tabs'), 'tabs', activeGroup);
  const core = { summary: tabSummary, logs: tabLogs, mods: tabMods, datapacks: tabDatapacks, textures: tabTextures, players: tabPlayers, client: tabClient, props: tabProps, settings: tabSettings };
  if (core[tab]) core[tab](s);
  else renderPluginTab(tab.replace(/^x-/, ''), s);
  mountRail(s);
}

/* --- Indicador de selección que se desliza entre secciones y pestañas ---
   La barra se repinta entera en cada navegación, así que se recuerda dónde estaba el indicador y se anima desde ahí.
   Se mueve con transform/width (CSS), y las medidas se escriben con la API de estilos (no con atributos style). */
state.ink = {};
function placeInk(nav, kind, key) {
  if (!nav) return;
  const active = $('.on', nav);
  if (!active) return;
  const ink = document.createElement('span');
  ink.className = 'ink'; ink.setAttribute('aria-hidden', 'true');
  nav.append(ink);
  const set = (x, w) => { ink.style.setProperty('--x', `${x}px`); ink.style.setProperty('--w', `${w}px`); };
  const x = active.offsetLeft, w = active.offsetWidth, prev = state.ink[kind];
  ink.classList.add('no-anim');
  set(prev && prev.key === key ? prev.x : x, prev && prev.key === key ? prev.w : w);   // parte de donde estaba (si era el mismo conjunto)
  void ink.offsetWidth;                                                              // fija la posición inicial sin transición
  ink.classList.remove('no-anim');
  set(x, w);
  state.ink[kind] = { key, x, w };
  nav.dataset.ink = kind;
}
// Si cambia el ancho (fuente cargada, ventana), el indicador se recoloca sin animar.
function resyncInk() {
  $$('[data-ink]').forEach((nav) => {
    const ink = $('.ink', nav), active = $('.on', nav);
    if (!ink || !active) return;
    ink.classList.add('no-anim');
    ink.style.setProperty('--x', `${active.offsetLeft}px`); ink.style.setProperty('--w', `${active.offsetWidth}px`);
    void ink.offsetWidth; ink.classList.remove('no-anim');
    const k = nav.dataset.ink; if (state.ink[k]) { state.ink[k].x = active.offsetLeft; state.ink[k].w = active.offsetWidth; }
  });
}
window.addEventListener('resize', resyncInk);
if (document.fonts && document.fonts.ready) document.fonts.ready.then(resyncInk);

/* --- Riel de estado (derecha): datos en vivo del servidor --- */
state.metrics = {};
const fmtUp = (sec) => (sec == null ? '—' : sec >= 86400 ? `${Math.floor(sec / 86400)} d ${Math.floor((sec % 86400) / 3600)} h` : sec >= 3600 ? `${Math.floor(sec / 3600)} h ${Math.floor((sec % 3600) / 60)} min` : `${Math.max(1, Math.floor(sec / 60))} min`);
const toMb = (v) => { const m = /^(\d+)([GgMm])$/.exec(v || ''); return m ? Number(m[1]) * (m[2].toLowerCase() === 'g' ? 1024 : 1) : null; };
function railHTML(s, m) {
  const link = (tab) => `#/s/${encodeURIComponent(s.name)}/${tab}`;
  const xmx = toMb(s.memory && s.memory.xmx);
  const run = m.running;
  const players = !run ? '<p class="rail-empty">El servidor está parado.</p>'
    : m.players.length ? `<ul class="rail-players">${m.players.map((p) => `<li><span class="avatar-sm" aria-hidden="true">${esc(p[0].toUpperCase())}</span>${esc(p)}</li>`).join('')}</ul>`
    : '<p class="rail-empty">Nadie conectado.</p>';
  return `
    <section class="rail-block">
      <h2 class="rail-title">Estado</h2>
      <p class="rail-big"><span class="led ${ledClass(s)}" data-led="rail" aria-hidden="true"></span>${run ? 'En marcha' : state.starting[s.name] > Date.now() ? 'Arrancando…' : 'Parado'}</p>
      ${run ? `<p class="rail-sub">Activo desde hace ${fmtUp(m.uptime_s)}</p>` : ''}
    </section>
    <section class="rail-block">
      <h2 class="rail-title">Jugadores <span class="rail-count">${run ? `${m.players.length}${m.max_players ? ` / ${m.max_players}` : ''}` : '—'}</span></h2>
      ${players}
    </section>
    ${run && m.rss_mb != null ? `<section class="rail-block">
      <h2 class="rail-title">Memoria <span class="rail-count">${m.rss_mb >= 1024 ? (m.rss_mb / 1024).toFixed(1) + ' GB' : m.rss_mb + ' MB'}${xmx ? ` de ${xmx >= 1024 ? xmx / 1024 + ' GB' : xmx + ' MB'}` : ''}</span></h2>
      ${xmx ? `<meter class="rail-meter" min="0" max="${xmx}" low="${Math.round(xmx * 0.7)}" high="${Math.round(xmx * 0.9)}" optimum="0" value="${Math.min(m.rss_mb, xmx)}"></meter>` : ''}
    </section>` : ''}
    ${s.permissions.logs || isAdmin() ? `<section class="rail-block">
      <h2 class="rail-title">Registro reciente</h2>
      <p class="rail-sub"><a class="rail-stat ${m.error ? 'bad' : ''}" href="${link('logs')}">${m.error} ${m.error === 1 ? 'error' : 'errores'}</a> · <a class="rail-stat ${m.warn ? 'warn' : ''}" href="${link('logs')}">${m.warn} ${m.warn === 1 ? 'aviso' : 'avisos'}</a></p>
    </section>` : ''}
    <section class="rail-block">
      <h2 class="rail-title">Disco libre <span class="rail-count ${m.disk_free_gb < 5 ? 'bad' : ''}">${m.disk_free_gb} GB</span></h2>
      ${m.disk_free_gb < 5 ? '<p class="rail-sub">Queda poco espacio: las copias pueden fallar.</p>' : ''}
    </section>`;
}
async function loadRail(s) {
  if (!$('#railCore')) return;
  try {
    const m = await api(`/api/servers/${encodeURIComponent(s.name)}/metrics`);
    state.metrics[s.name] = m;
    const core = $('#railCore');
    if (core) setHTMLKeepLeds(core, railHTML(s, m));
  } catch (e) { /* el riel se queda con el último dato */ }
}
function mountRail(s) {
  loadRail(s);
  every(5000, () => loadRail(s));
  const host = $('#railPlug');
  for (const r of (state.plugins && state.plugins.rails) || []) {
    const plug = window.ModnexPlugins && window.ModnexPlugins[r.id];
    if (!plug || typeof plug.renderRail !== 'function') continue;
    const block = document.createElement('section');
    block.className = 'rail-block';
    block.innerHTML = `<h2 class="rail-title">${esc(r.label)}</h2><div class="rail-plug"></div>`;
    host.append(block);
    try { plug.renderRail($('.rail-plug', block), s); } catch (e) { $('.rail-plug', block).textContent = 'No disponible'; }
  }
}

/* --- Resumen --- */
function tabSummary(s) {
  const can = (k) => isAdmin() || !!s.permissions[k];
  const enc = encodeURIComponent(s.name);
  const quick = [
    ['logs', 'Abrir la consola', 'Registro completo y comandos', can('logs')],
    ['players', 'Jugadores', 'Quién está dentro y quién puede entrar', can('players')],
    ['mods', s.kind === 'plugin' ? 'Plugins' : 'Mods', 'Instalar, actualizar y quitar', can('mods') && s.kind !== 'none'],
    ['client', 'Generar el cliente', 'Lo que necesitan tus jugadores', isAdmin()],
  ].filter((q) => q[3]);
  $('#tabBody').innerHTML = `
    <div class="summary${isAdmin() ? '' : ' solo'}">
      <div class="summary-main">
        ${can('logs') ? `<section class="block"><div class="block-head"><h2>Últimas líneas del registro</h2><a href="#/s/${enc}/logs">Abrir la consola</a></div>
          <pre class="log mini" id="sumLog" aria-label="Últimas líneas del registro">Cargando…</pre></section>` : ''}
        <section class="block"><h2>Accesos rápidos</h2>
          <div class="quick">${quick.map(([id, t, d]) => `<a class="quick-item" href="#/s/${enc}/${id}"><strong>${t}</strong><span class="muted small">${d}</span></a>`).join('')}</div></section>
      </div>
      ${isAdmin() ? `<div class="summary-side"><section class="block"><h2>Actividad reciente</h2><div id="sumAudit"><p class="muted small">Cargando…</p></div></section>
        <section class="block"><h2>Quién tiene acceso</h2><div id="sumUsers"><p class="muted small">Cargando…</p></div></section></div>` : ''}
    </div>`;
  if (can('logs')) {
    const load = async () => {
      try {
        const { log } = await api(`/api/servers/${enc}/log?lines=16`);
        const pre = $('#sumLog'); if (!pre) return;
        pre.innerHTML = logHTML(stripAnsi(log || '(sin contenido todavía)'));
        pre.scrollTop = pre.scrollHeight;
      } catch (e) { /* se queda con lo anterior */ }
    };
    load(); every(5000, load);
  }
  if (isAdmin()) {
    api('/api/audit?limit=300').then((rows) => {
      const el = $('#sumAudit'); if (!el) return;
      const mine = rows.filter((r) => r.server_name === s.name).slice(0, 8);
      el.innerHTML = mine.length ? `<ul class="feed">${mine.map((r) => `<li><span class="feed-when">${fmtTime(r.ts)}</span><span><strong>${esc(r.username)}</strong> ${esc(r.action)}${r.detail ? ` <span class="muted">${esc(r.detail)}</span>` : ''}</span></li>`).join('')}</ul>` : '<p class="muted small">Todavía no hay actividad registrada en este servidor.</p>';
    }).catch(() => {});
    api('/api/users').then((users) => {
      const el = $('#sumUsers'); if (!el) return;
      const who = users.filter((u) => u.active && (u.is_admin || u.permissions[s.name]));
      el.innerHTML = who.length ? `<ul class="people">${who.map((u) => {
        const p = u.permissions[s.name] || {};
        const labels = u.is_admin ? 'Administrador' : Object.keys(PERM_LABELS).filter((k) => p[k]).map((k) => PERM_LABELS[k]).join(', ') || 'Sin permisos';
        return `<li><span class="avatar-sm" aria-hidden="true">${esc(u.username[0].toUpperCase())}</span><span><strong>${esc(u.username)}</strong><br><span class="muted small">${esc(labels)}</span></span></li>`;
      }).join('')}</ul>` : '<p class="muted small">Solo los administradores.</p>';
    }).catch(() => {});
  }
}

/* --- Logs --- */
const stripAnsi = (t) => t.replace(/\x1b\[[0-9;]*m/g, '');
function logHTML(text) {
  return stripAnsi(text).split('\n').map((l) => {
    const c = /\b(ERROR|FATAL)\b|Exception/.test(l) ? 'err' : /\bWARN\b/.test(l) ? 'warn' : /\bDEBUG\b/.test(l) ? 'debug' : 'info';
    return `<span class="${c}">${esc(l)}</span>`;
  }).join('\n');
}

state.logLevel = 'all'; state.logQ = ''; state.logRaw = '';
function paintLog() {
  const pre = $('#log');
  if (!pre) return;
  const q = state.logQ.trim().toLowerCase();
  const keep = (l) => {
    if (state.logLevel === 'err' && !/\b(ERROR|FATAL)\b|Exception/.test(l)) return false;
    if (state.logLevel === 'warn' && !/\b(ERROR|FATAL|WARN)\b|Exception/.test(l)) return false;
    return !q || l.toLowerCase().includes(q);
  };
  const lines = stripAnsi(state.logRaw).split('\n').filter(keep);
  pre.innerHTML = lines.length ? logHTML(lines.join('\n')) : (state.logRaw ? '(ninguna línea coincide con el filtro)' : '(sin contenido todavía)');
  if ($('#follow') && $('#follow').checked) pre.scrollTop = pre.scrollHeight;
}
function tabLogs(s) {
  const cmd = isAdmin() ? `
    <form class="row" id="cmdForm">
      <input name="cmd" placeholder="Comando para la consola, por ejemplo: say hola" aria-label="Comando" autocomplete="off">
      <button class="btn" type="submit">Enviar</button>
    </form>` : '';
  $('#tabBody').classList.add('fill');
  $('.srv-layout').classList.add('is-fill');
  $('#tabBody').innerHTML = `
    <div class="toolbar"><div class="seg" role="group" aria-label="Nivel">${[['all', 'Todo'], ['warn', 'Avisos y errores'], ['err', 'Errores']].map(([id, t]) => `<button type="button" class="seg-btn${state.logLevel === id ? ' on' : ''}" data-action="log-level" data-level="${id}">${t}</button>`).join('')}</div>
      <input type="search" id="logQ" class="log-q" placeholder="Filtrar el registro" aria-label="Filtrar el registro" value="${esc(state.logQ)}">
      <label class="check"><input type="checkbox" id="follow" checked> Seguir al final</label></div>
    <pre class="log" id="log" tabindex="0" aria-label="Log del servidor"></pre>${cmd}`;
  const load = async () => {
    try {
      const { log } = await api(`/api/servers/${encodeURIComponent(s.name)}/log?lines=300`);
      const pre = $('#log');
      if (!pre) return;
      state.logRaw = log || '';
      paintLog();
    } catch (e) { fail(e); }
  };
  load();
  every(3000, load);
}

/* --- Mods --- */
const segHTML = (scope, items, cur, label) => `
  <div class="seg" role="tablist" aria-label="${label}">${items.map(([id, text]) =>
    `<button class="seg-btn${cur === id ? ' on' : ''}" role="tab" aria-selected="${cur === id}" data-action="pane" data-scope="${scope}" data-pane="${id}">${text}</button>`).join('')}</div>`;

state.modsSeq = 0;
function tabMods(s) {
  state.modsSeq++;   // cualquier repintado de la pestaña invalida las cargas de «Instalados» que sigan en curso
  const pane = state.modsPane, plugins = s.kind === 'plugin';
  const panes = [['installed', 'Instalados'], ['add', plugins ? 'Añadir plugins' : 'Añadir mods']];
  if (isAdmin()) panes.push(['upload', 'Subir el mío']);
  $('#tabBody').innerHTML = `${segHTML('mods', panes, pane, plugins ? 'Plugins' : 'Mods')}<div id="modsBody"></div>`;
  if (pane === 'upload' && isAdmin()) return mountUploadMod(s, plugins);
  pane === 'installed' ? loadInstalled(s) : mountFinder(s.kind === 'plugin' ? 'plugin' : 'mod', $('#modsBody'));
}

// Subir un mod o plugin propio (.jar). Solo administradores: un .jar es código que corre con los permisos del servidor.
function mountUploadMod(s, plugins) {
  const what = plugins ? 'plugin' : 'mod';
  $('#modsBody').innerHTML = `
    ${dropzoneHTML('modDrop', `Subir un ${what} desde tu equipo`, `Archivo .jar, hasta 256 MB. Debe ser ${plugins ? 'un plugin de Paper' : 'un mod del mismo cargador que el servidor'}. Se carga al reiniciar el servidor.`, '.jar')}
    <p class="muted small">Se comprueba que el archivo sea un ${what} válido y que encaje con el servidor, y no pisa otro con el mismo nombre. Un ${what} es código que se ejecuta con los permisos del servidor: sube solo los que conozcas y en los que confíes. Después aparece en «Instalados» como no reconocido, porque no viene de Modrinth ni CurseForge.</p>`;
  wireDrop('modDrop', `/api/servers/${encodeURIComponent(s.name)}/mod_upload`, () => { state.modsPane = 'installed'; refreshServers(); tabMods(s); });
}

const SRC = { modrinth: 'Modrinth', curseforge: 'CurseForge' };

state.modSel = null; state.modFilter = 'all'; state.modQ = ''; state.modsData = [];
const SIDE_TXT = { required: 'Necesario', optional: 'Opcional', unsupported: 'No funciona' };
const modFilters = (mods) => [
  ['all', 'Todos', mods.length],
  ['updates', 'Con actualización', mods.filter((m) => m.latest && m.source === 'modrinth').length],
  ['off', 'Desactivados', mods.filter((m) => !m.enabled).length],
  ['unknown', 'Sin reconocer', mods.filter((m) => !m.source).length],
];
function modMatches(m) {
  const f = state.modFilter, q = state.modQ.trim().toLowerCase();
  if (f === 'updates' && !(m.latest && m.source === 'modrinth')) return false;
  if (f === 'off' && m.enabled) return false;
  if (f === 'unknown' && m.source) return false;
  return !q || (m.name || '').toLowerCase().includes(q) || m.file.toLowerCase().includes(q);
}
function modDetailHTML(mods) {
  const m = mods.find((x) => x.file === state.modSel);
  if (!m) {
    const upd = mods.filter((x) => x.latest && x.source === 'modrinth').length, off = mods.filter((x) => !x.enabled).length;
    return `<div class="detail-empty"><h2>${mods.length} ${mods.length === 1 ? 'mod' : 'mods'}</h2>
      <p class="muted">${upd ? `${upd} con versión nueva. ` : 'Todos están al día. '}${off ? `${off} desactivados. ` : ''}Elige uno de la lista para ver su ficha y actuar sobre él.</p>
      <p class="muted small">Los cambios se aplican al reiniciar el servidor.</p></div>`;
  }
  const side = (v) => (v ? SIDE_TXT[v] || v : 'Sin datos');
  return `
    <div class="detail-head"><h2>${esc(m.name || m.file)}</h2>
      <p class="muted small mono">${esc(m.file)}</p>
      <div class="chips"><span class="chip">${m.source ? SRC[m.source] : 'Desconocido'}</span>${m.enabled ? '' : '<span class="chip bad">Desactivado</span>'}${m.latest && m.source === 'modrinth' ? '<span class="chip live">Actualización disponible</span>' : ''}</div></div>
    <dl class="facts">
      <dt>Versión instalada</dt><dd>${esc(m.installed || '—')}</dd>
      ${m.latest ? `<dt>Última versión</dt><dd>${esc(m.latest)}</dd>` : ''}
      <dt>En el servidor</dt><dd>${esc(side(m.server_side))}</dd>
      <dt>En el cliente</dt><dd>${esc(side(m.client_side))}</dd>
      <dt>Tamaño</dt><dd>${fmtSize(m.size)}</dd>
    </dl>
    ${m.name ? '' : '<p class="muted small">No se reconoce en Modrinth ni CurseForge, así que no se puede comprobar si hay versión nueva.</p>'}
    <div class="detail-acts">
      ${m.latest && m.source === 'modrinth' ? `<button class="btn primary" data-action="mod-update" data-file="${esc(m.file)}">Actualizar a ${esc(m.latest)}</button>` : ''}
      ${m.project_id && m.source ? `<a class="btn" href="#/m/${esc(m.source)}/${esc(m.project_id)}">Ver ficha</a>` : ''}
      ${m.source === 'curseforge' && m.slug ? `<a class="btn" target="_blank" rel="noopener" href="https://www.curseforge.com/minecraft/mc-mods/${esc(m.slug)}">Ver en CurseForge</a>` : ''}
      <button class="btn" data-action="mod-toggle" data-file="${esc(m.file)}">${m.enabled ? 'Desactivar' : 'Activar'}</button>
      <button class="btn danger" data-action="mod-delete" data-file="${esc(m.file)}">Borrar</button>
    </div>`;
}
function paintMods() {
  const body = $('#modsBody');
  if (!body) return;
  const mods = state.modsData;
  if (!$('#modList')) {
    body.innerHTML = `<div class="split">
      <div class="split-list">
        <div class="split-tools"><input type="search" id="modQ" placeholder="Buscar entre los instalados" aria-label="Buscar entre los instalados" value="${esc(state.modQ)}"><div class="chipbar" id="modFilters"></div></div>
        <div class="rows" id="modList"></div>
      </div>
      <aside class="split-detail" id="modDetail" aria-live="polite"></aside></div>`;
    enterOnce($('#modList'));
  }
  $('#modFilters').innerHTML = modFilters(mods).map(([id, t, n]) => `<button type="button" class="filter${state.modFilter === id ? ' on' : ''}" data-action="mod-filter" data-filter="${id}">${t} <span class="filter-n">${n}</span></button>`).join('');
  const list = mods.filter(modMatches);
  $('#modList').innerHTML = list.map((m) => `
    <button type="button" class="row-item row-btn${m.enabled ? '' : ' off'}${state.modSel === m.file ? ' sel' : ''}" data-action="mod-select" data-file="${esc(m.file)}">
      <span class="grow"><strong>${esc(m.name || m.file)}</strong>${m.name ? '' : '<span class="muted small block">Sin reconocer</span>'}</span>
      ${m.latest && m.source === 'modrinth' ? '<span class="dot-up" title="Actualización disponible"></span>' : ''}
      <span class="ver">${esc(m.installed || '—')}</span>
    </button>`).join('') || `<p class="muted pad pad-in">${mods.length ? 'Ningún mod coincide con el filtro.' : 'Este servidor no tiene mods.'}</p>`;
  $('#modDetail').innerHTML = modDetailHTML(mods);
}
async function loadInstalled(s) {
  const body = $('#modsBody');
  const seq = ++state.modsSeq;
  // Identificar los mods puede tardar varios segundos. Si mientras tanto se cambió de panel («Añadir mods»),
  // de pestaña o de servidor, la respuesta ya no es para lo que se ve y no debe pintarse encima.
  const stale = () => seq !== state.modsSeq || state.modsPane !== 'installed' || !$('#modsBody');
  body.innerHTML = '<p class="muted pad">Identificando mods…</p>';
  try {
    const q = new URLSearchParams({ loader: state.loader, version: state.version });
    const mods = await api(`/api/servers/${encodeURIComponent(s.name)}/mods?${q}`);
    if (stale()) return;
    state.modsData = mods;
    if (!mods.some((m) => m.file === state.modSel)) state.modSel = null;
    paintMods();
  } catch (e) { if (!stale()) body.innerHTML = ''; fail(e); }
}

/* --- Buscador en proveedores: mods, datapacks y texturas --- */
const KIND = {
  mod: { placeholder: 'Buscar mods (vacío: los más descargados)', empty: 'Sin resultados para esa búsqueda, loader y versión.' },
  plugin: { placeholder: 'Buscar plugins (vacío: los más descargados)', empty: 'Sin plugins para esa búsqueda y versión de Paper.' },
  datapack: { placeholder: 'Buscar datapacks (vacío: los más descargados)', empty: 'Sin resultados para esa búsqueda y versión.' },
  resourcepack: { placeholder: 'Buscar texturas (vacío: las más descargadas)', empty: 'Sin resultados para esa búsqueda y versión.' },
};
const SORTS = [['auto', 'Automático'], ['downloads', 'Más descargados'], ['relevance', 'Relevancia'], ['updated', 'Actualizados'], ['newest', 'Nuevos']];
const SIDES = [['server', 'Para servidor'], ['required', 'Solo los que exigen servidor'], ['all', 'Todos']];
const newFinder = () => ({ source: 'modrinth', q: '', sort: 'auto', side: 'server', results: null, error: null, loaded: false, page: 1, pages: 1, total: 0, tags: [] });
state.tagList = {};                       // kind -> [{name, label}] (etiquetas de Modrinth)
state.installed = { server: null, at: 0, projects: new Set(), versions: {} };   // índice de lo ya instalado en el servidor actual
const INSTALLED_TTL_MS = 60000;
const instKey = (h) => (state.installed.projects.has(`${h.source}:${h.id}`) || (h.slug && state.installed.projects.has(`slug:${String(h.slug).toLowerCase()}`)));
const instVersion = (source, id) => state.installed.versions[`${source}:${id}`];
state.finder = { mod: newFinder(), plugin: newFinder(), datapack: newFinder(), resourcepack: newFinder() };
const opts = (list, cur) => list.map(([v, l]) => `<option value="${v}"${cur === v ? ' selected' : ''}>${l}</option>`).join('');

function finderHTML(kind) {
  const f = state.finder[kind];
  return `
    <form class="search" data-finder="${kind}">
      <div class="search-main">
        <select name="source" aria-label="Proveedor">${opts(Object.entries(SRC), f.source)}</select>
        <input name="q" value="${esc(f.q)}" placeholder="${KIND[kind].placeholder}" aria-label="Buscar">
        <button class="btn primary" type="submit">Buscar</button>
      </div>
      <div class="search-filters">
        ${kind === 'mod' ? `<select name="loader" aria-label="Loader">${opts([['neoforge', 'NeoForge'], ['fabric', 'Fabric'], ['forge', 'Forge']], state.loader)}</select>` : ''}
        <input name="version" value="${esc(state.version)}" aria-label="Versión de Minecraft" class="short">
        ${kind === 'mod' ? `<select name="side" aria-label="Compatibilidad con servidor">${opts(SIDES, f.side)}</select>` : ''}
        <select name="sort" aria-label="Orden">${opts(SORTS, f.sort)}</select>
      </div>
      <div class="tagbar" id="tags-${kind}" role="group" aria-label="Filtrar por etiqueta">${tagbarHTML(kind)}</div>
    </form>
    <div class="bar" aria-hidden="true"></div>
    <div id="results-${kind}">${finderResultsHTML(kind)}</div>
    <div id="pager-${kind}">${pagerHTML(kind)}</div>`;
}

function tagbarHTML(kind) {
  const f = state.finder[kind], list = state.tagList[kind];
  if (f.source !== 'modrinth') return '<span class="muted small">El filtro por etiqueta solo está disponible con Modrinth.</span>';
  if (!list) return '<span class="muted small">Cargando etiquetas…</span>';
  if (!list.length) return '';
  return `<span class="tagbar-title muted small">Etiquetas</span>${list.map((t) => `<button type="button" class="filter${f.tags.includes(t.name) ? ' on' : ''}" data-action="finder-tag" data-kind="${kind}" data-tag="${esc(t.name)}" aria-pressed="${f.tags.includes(t.name)}">${esc(t.label)}</button>`).join('')}${f.tags.length ? `<button type="button" class="filter clear" data-action="finder-tag-clear" data-kind="${kind}">Quitar filtros</button>` : ''}`;
}
async function loadTags(kind) {
  if (state.tagList[kind]) return;
  try { state.tagList[kind] = await api(`/api/tags?kind=${kind}`); } catch (e) { state.tagList[kind] = []; }
  const box = $(`#tags-${kind}`); if (box) box.innerHTML = tagbarHTML(kind);
}

// Páginas: ventana de números alrededor de la actual, con la primera y la última siempre a mano.
function pagerHTML(kind) {
  const f = state.finder[kind];
  if (!f.results || f.pages <= 1) return f.results && f.total ? `<p class="muted small pager-info">${fmtNum(f.total)} ${f.total === 1 ? 'resultado' : 'resultados'}</p>` : '';
  const nums = [];
  for (let n = 1; n <= f.pages; n++) if (n === 1 || n === f.pages || Math.abs(n - f.page) <= 2) nums.push(n);
  const btn = (n, label, extra = '') => `<button type="button" class="page${n === f.page ? ' on' : ''}" data-action="finder-page" data-kind="${kind}" data-page="${n}" ${n === f.page ? 'aria-current="page"' : ''} ${extra}>${label}</button>`;
  const items = nums.map((n, i) => (i && n - nums[i - 1] > 1 ? '<span class="page-gap" aria-hidden="true">…</span>' : '') + btn(n, n)).join('');
  return `<nav class="pager" aria-label="Páginas de resultados">
      ${btn(f.page - 1, 'Anterior', f.page <= 1 ? 'disabled' : '')}${items}${btn(f.page + 1, 'Siguiente', f.page >= f.pages ? 'disabled' : '')}
    </nav><p class="muted small pager-info">Página ${f.page} de ${f.pages} · ${fmtNum(f.total)} resultados</p>`;
}

function finderResultsHTML(kind) {
  const f = state.finder[kind];
  if (f.error) return `<p class="form-error pad" role="alert">${esc(f.error)}</p>`;
  if (!f.results) return `<div aria-busy="true" aria-label="Cargando resultados">${Array.from({ length: 5 }, () => `
    <div class="skel-row"><span class="skel"></span><div class="skel-lines"><span class="skel"></span><span class="skel"></span></div></div>`).join('')}</div>`;
  if (!f.results.length) return `<p class="muted pad">${KIND[kind].empty}</p>`;
  return `<div class="rows">${f.results.map((h) => `
    <div class="result" data-kind="${kind}" data-id="${esc(h.id)}" data-slug="${esc(h.slug)}" data-source="${esc(h.source)}">
      ${h.icon ? `<img src="${esc(h.icon)}" alt="" loading="lazy">` : '<span class="img-ph"></span>'}
      <div class="grow"><strong><a class="result-link" href="#/m/${esc(h.source)}/${esc(h.id)}">${esc(h.name)}</a></strong>${(kind === 'mod' || kind === 'plugin') && instKey(h) ? ' <span class="chip live inst">Instalado</span>' : ''} <span class="muted small">${fmtNum(h.downloads)} descargas</span>
        <div class="muted small">${esc(h.summary)}</div>
        <div class="files" data-files></div></div>
      <button class="btn sm" data-action="finder-files">Ver versiones</button>
    </div>`).join('')}</div>`;
}

function depsDialog(btn, plan) {
  state.depsBtn = btn;
  const main = { name: btn.dataset.name, url: btn.dataset.url, sha1: btn.dataset.sha1 };
  const title = (btn.closest('.result') && $('strong', btn.closest('.result'))?.textContent) || main.name;
  const usable = plan.deps.filter((d) => d.status === 'ok').length;
  const row = (d, checked, disabled, note, extra = '') => `
    <label class="plan-row"><input type="checkbox" name="dep" ${checked ? 'checked' : ''} ${disabled ? 'disabled' : ''}
      data-url="${esc(d.url || '')}" data-name="${esc(d.filename || '')}" data-sha1="${esc(d.sha1 || '')}">
      <span class="grow"><strong>${esc(d.name)}</strong> <span class="muted small">${esc(d.version || '')}</span>
        <span class="muted small block">${note}</span></span>${extra}</label>`;
  openDialog(`
    <form class="dlg" id="depsForm">
      <header><h2>Instalar con dependencias</h2><button class="btn ghost sm" type="button" data-action="close">Cerrar</button></header>
      <p>${plan.deps.length
        ? `<strong>${esc(title)}</strong> necesita ${plan.deps.length} ${plan.deps.length === 1 ? 'mod más' : 'mods más'} para funcionar. Se instalarán juntos. Quitar una dependencia obligatoria puede impedir que el servidor arranque.`
        : `<strong>${esc(title)}</strong> no necesita más mods.`}</p>
      ${plan.warnings.map((w) => `<p class="notice warn">${esc(w)}</p>`).join('')}
      <div class="plan-list">
        ${row({ name: title, version: '', url: main.url, filename: main.name, sha1: main.sha1 }, true, true, `El mod que has elegido · ${esc(main.name)}`)}
        ${plan.deps.map((d) => d.status === 'ok'
          ? row(d, true, false, `Lo necesita ${esc(d.via || 'el mod elegido')} · ${SRC[d.source]}`)
          : row(d, false, true, esc(d.note || 'No disponible'), d.page ? `<a class="btn sm" target="_blank" rel="noopener" href="${esc(d.page)}">Abrir</a>` : '')).join('')}
      </div>
      ${plan.deps.length - usable ? '<p class="muted small">Las dependencias marcadas como no disponibles tendrás que instalarlas a mano.</p>' : ''}
      <p class="form-error" role="alert"></p>
      <div class="row end"><button class="btn" type="button" data-action="close">Cancelar</button><button class="btn primary" type="submit">Instalar seleccionados</button></div>
    </form>`, true);
}

function mountFinder(kind, host) {
  host.dataset.finderHost = kind;
  host.innerHTML = finderHTML(kind);
  loadTags(kind);
  ensureInstalled(kind);
  if (!state.finder[kind].loaded) runFinder(kind, $('form[data-finder]', host));  // al abrir: lo más descargado
}

// Qué hay ya instalado en este servidor: tarda (identifica los mods), así que se pide aparte y se marcan los resultados al llegar.
async function ensureInstalled(kind) {
  if ((kind !== 'mod' && kind !== 'plugin') || state.view.kind !== 'server') return;
  const name = state.view.name, st = state.installed;
  if (st.server === name && Date.now() - st.at < INSTALLED_TTL_MS) return markInstalledInDom(kind);
  try {
    const q = new URLSearchParams({ loader: state.loader, version: state.version });
    const idx = await api(`/api/servers/${encodeURIComponent(name)}/installed?${q}`);
    if (state.view.kind !== 'server' || state.view.name !== name) return;
    state.installed = { server: name, at: Date.now(), projects: new Set(idx.projects), versions: idx.versions || {} };
    markInstalledInDom(kind);
  } catch (e) { /* sin el índice simplemente no se marca nada */ }
}
function markInstalledInDom(kind) {
  $$(`#results-${kind} .result`).forEach((card) => {
    const h = { source: card.dataset.source, id: card.dataset.id, slug: card.dataset.slug };
    const has = $('.inst', card);
    if (instKey(h) && !has) $('strong', card).insertAdjacentHTML('afterend', ' <span class="chip live inst">Instalado</span>');
  });
}
function rememberInstalled(source, project, slug, version) {
  const st = state.installed;
  if (st.server !== state.view.name) return;
  st.projects.add(`${source}:${project}`);
  if (slug) st.projects.add(`slug:${String(slug).toLowerCase()}`);
  if (version) st.versions[`${source}:${project}`] = version;
  st.at = Date.now();
  markInstalledInDom(state.view.kind === 'server' && state.modsPane === 'add' ? 'mod' : 'mod');
  markInstalledInDom('plugin');
}

async function runFinder(kind, form, page = 1) {
  const f = state.finder[kind];
  if (form.source.value !== f.source) { f.tags = []; }   // las etiquetas son de Modrinth
  f.source = form.source.value; f.q = form.q.value.trim(); f.sort = form.sort.value;
  if (form.side) f.side = form.side.value;
  if (form.loader) { state.loader = form.loader.value; localStorage.setItem('loader', state.loader); }
  state.version = form.version.value.trim() || '1.21.1'; localStorage.setItem('version', state.version);
  f.error = null; f.results = null; f.page = page;
  const host = form.closest('[data-finder-host]'), bar = $('.bar', host);
  bar.classList.add('on');
  $(`#results-${kind}`).innerHTML = finderResultsHTML(kind);
  $(`#pager-${kind}`).innerHTML = '';
  const tg = $(`#tags-${kind}`); if (tg) tg.innerHTML = tagbarHTML(kind);
  try {
    const d = await api('/api/search?' + new URLSearchParams({
      kind, source: f.source, q: f.q, sort: f.sort, side: f.side, loader: state.loader, version: state.version, page,
      ...(f.source === 'modrinth' && f.tags.length ? { tags: f.tags.join(',') } : {}),
      ...(state.view.kind === 'server' ? { server: state.view.name } : {}) }));
    f.results = d.items; f.total = d.total; f.pages = d.pages; f.page = d.page;
  } catch (e) { f.error = e.message; }
  f.loaded = true;
  bar.classList.remove('on');
  const box = $(`#results-${kind}`);
  if (box) box.innerHTML = finderResultsHTML(kind);
  const pg = $(`#pager-${kind}`); if (pg) pg.innerHTML = pagerHTML(kind);
  loadTags(kind); ensureInstalled(kind);
}

/* --- Datapacks --- */
function dropzoneHTML(id, label, hint, accept = '.zip') {
  return `<label class="drop" id="${id}" tabindex="0">
      <input type="file" accept="${accept}" hidden>
      <strong>${label}</strong><span class="muted small">${hint}</span>
      <span class="progress" hidden><span class="progress-fill"></span></span>
    </label>`;
}

async function tabDatapacks(s) {
  const pane = state.dpPane;
  $('#tabBody').innerHTML = `${segHTML('dp', [['installed', 'Instalados'], ['add', 'Añadir desde proveedores']], pane, 'Datapacks')}<div id="dpBody"></div>`;
  if (pane === 'add') return mountFinder('datapack', $('#dpBody'));
  $('#dpBody').innerHTML = `
    ${dropzoneHTML('dpDrop', 'Subir un datapack desde tu equipo', 'Archivo .zip con pack.mcmeta en la raíz, hasta 256 MB. Se carga al reiniciar el servidor.')}
    <div id="dpList"></div>`;
  wireDrop('dpDrop', `/api/servers/${encodeURIComponent(s.name)}/datapack_upload`, () => { loadDatapacks(s); refreshServers(); });
  loadDatapacks(s);
}

async function loadDatapacks(s) {
  try {
    const list = await api(`/api/servers/${encodeURIComponent(s.name)}/datapacks`);
    if (!$('#dpList')) return;
    $('#dpList').innerHTML = list.length ? `<div class="rows">${list.map((d) => `
      <div class="row-item"><div class="grow"><strong>${esc(d.file)}</strong>
        <div class="muted small">${d.kind === 'zip' ? fmtSize(d.size) : 'Carpeta'}</div></div>
        ${d.kind === 'zip' ? `<button class="btn danger sm" data-action="dp-delete" data-file="${esc(d.file)}">Borrar</button>` : ''}
      </div>`).join('')}</div>` : '<p class="muted pad">No hay datapacks en el mundo de este servidor.</p>';
  } catch (e) { fail(e); }
}

function wireDrop(id, endpoint, done) {
  const drop = $('#' + id);
  if (!drop) return;
  const input = $('input', drop), bar = $('.progress', drop), fill = $('.progress-fill', drop);
  const send = async (file) => {
    if (!file) return;
    bar.hidden = false; fill.style.transform = 'scaleX(0)';
    try {
      const r = await upload(endpoint, file, (p) => { fill.style.transform = `scaleX(${p})`; });
      toast(`Subido: ${r.uploaded}`, 'ok');
      done();
    } catch (e) { fail(e); }
    bar.hidden = true; input.value = '';
  };
  input.addEventListener('change', () => send(input.files[0]));
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('over'); send(e.dataTransfer.files[0]); });
  drop.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
}

/* --- Cliente (releases + enlace temporal) --- */
async function tabClient(s) {
  $('#tabBody').innerHTML = `
    <div class="two-col">
    <div class="two-main"><section class="panel"><h2>Cliente compatible con este servidor</h2>
      <div id="clientInfo"><p class="muted">Analizando los mods del servidor…</p></div></section></div>
    <div class="two-side"><p class="lead">Los clientes generados y los archivos que subas aparecen aquí. Desde ahí puedes compartirlos con un enlace público que se cierra solo; ese enlace da acceso únicamente a ese archivo, nunca al panel.</p>
    <div id="shareBox"></div>
    ${dropzoneHTML('relDrop', 'Subir un cliente ya hecho (.zip o .mrpack)', 'Hasta 2 GB. Queda guardado en el gestor; aún no es público.')}
    <div id="relList"></div></div></div>`;
  loadClientPlan(s);
  wireDrop('relDrop', `/api/servers/${encodeURIComponent(s.name)}/release_upload`, () => loadReleases(s));
  loadReleases(s);
  loadShare();
  every(5000, loadShare);
}

const ascii = (t) => (t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^A-Za-z0-9._ -]/g, '').trim().slice(0, 48);

async function loadClientPlan(s) {
  try {
    const p = await api(`/api/servers/${encodeURIComponent(s.name)}/client_plan`);
    state.plan = p;
    const box = $('#clientInfo');
    if (!box) return;
    const inc = p.mods.filter((m) => m.include).length, unk = p.mods.filter((m) => !m.source).length, st = p.stale;
    const changes = st && st.stale
      ? `<p class="notice warn">El servidor cambió desde esa versión${st.versions_changed ? ' (cambió Minecraft o NeoForge)' : ''}${st.added.length ? `. Nuevos: ${st.added.map(esc).join(', ')}` : ''}${st.removed.length ? `. Quitados: ${st.removed.map(esc).join(', ')}` : ''}. Los jugadores que tengan la versión anterior pueden no poder entrar; genera una nueva.</p>`
      : st ? '<p class="muted small">El cliente generado está al día con el servidor.</p>' : '';
    box.innerHTML = `
      <p>Minecraft <strong>${esc(p.minecraft || 'desconocido')}</strong> · NeoForge <strong>${esc(p.loader_version || 'desconocido')}</strong> · ${p.mods.length} mods en el servidor, ${inc} para el cliente.${unk ? ` <span class="muted">${unk} sin reconocer.</span>` : ''}</p>
      ${p.last_build ? `<p class="muted small">Última versión generada: <strong>${esc(p.last_build.version)}</strong> (${esc(p.last_build.fmt)}) · ${fmtTime(p.last_build.created_at)} · ${p.last_build.mods} mods</p>` : '<p class="muted small">Todavía no has generado ningún cliente.</p>'}
      ${changes}
      <button class="btn primary" data-action="client-plan">Generar cliente…</button>`;
  } catch (e) {
    fail(e);
    const box = $('#clientInfo');
    if (box) box.innerHTML = '<p class="muted">No se pudo analizar el servidor.</p>';
  }
}

async function loadReleases(s) {
  try {
    const list = await api(`/api/servers/${encodeURIComponent(s.name)}/releases`);
    if (!$('#relList')) return;
    $('#relList').innerHTML = list.length ? `<div class="rows">${list.map((r) => `
      <div class="row-item"><div class="grow"><strong>${esc(r.file)}</strong>
        <div class="muted small">${fmtSize(r.size)} · ${fmtTime(r.mtime)}</div></div>
        <div class="acts">
          <button class="btn primary sm" data-action="share" data-file="${esc(r.file)}">Compartir con enlace temporal…</button>
          <button class="btn danger sm" data-action="rel-delete" data-file="${esc(r.file)}">Borrar</button>
        </div></div>`).join('')}</div>` : '<p class="muted pad">Todavía no hay releases para este servidor.</p>';
  } catch (e) { fail(e); }
}

async function loadShare() {
  try {
    const sh = await api('/api/share');
    const box = $('#shareBox');
    if (!box) return;
    if (!sh.active) { box.innerHTML = ''; return; }
    box.innerHTML = `
      <div class="share">
        <div class="share-head"><span class="led on"></span><strong>Descarga pública activa</strong>
          <span class="muted small">${esc(sh.file)} · ${esc(sh.server)} · caduca en ${fmtLeft(sh.expires_at)} · ${sh.downloads} ${sh.downloads === 1 ? 'descarga' : 'descargas'}</span></div>
        ${sh.ready ? '' : '<p class="muted small">El enlace puede tardar unos segundos más en responder desde fuera.</p>'}
        <div class="row"><input readonly value="${esc(sh.url)}" aria-label="Enlace público" id="shareUrl">
          <button class="btn" data-action="copy-url">Copiar enlace</button>
          <button class="btn danger" data-action="share-stop">Detener ahora</button></div>
      </div>`;
  } catch (e) { /* el sondeo no debe molestar con avisos */ }
}

/* --- Propiedades (server.properties, opciones principales) --- */
const PROP_GROUPS = [
  ['General', [
    ['motd', 'Descripción (MOTD)', 'text'], ['server-port', 'Puerto', 'number', 1024, 65535],
    ['max-players', 'Máximo de jugadores', 'number', 1, 1000], ['level-name', 'Nombre del mundo', 'text'],
    ['level-seed', 'Semilla del mundo', 'text']]],
  ['Mundo', [
    ['difficulty', 'Dificultad', 'select', ['peaceful', 'easy', 'normal', 'hard']],
    ['gamemode', 'Modo de juego', 'select', ['survival', 'creative', 'adventure', 'spectator']],
    ['view-distance', 'Distancia de visión', 'number', 3, 32], ['simulation-distance', 'Distancia de simulación', 'number', 3, 32],
    ['spawn-protection', 'Protección del spawn (bloques)', 'number', 0, 1000]]],
  ['Jugadores y reglas', [
    ['online-mode', 'Cuentas oficiales (online-mode)', 'bool'], ['white-list', 'Lista blanca activa', 'bool'],
    ['enforce-whitelist', 'Expulsar a quien no esté en la lista', 'bool'], ['force-gamemode', 'Forzar el modo de juego', 'bool'],
    ['pvp', 'PvP', 'bool'], ['hardcore', 'Hardcore', 'bool'], ['allow-flight', 'Permitir volar', 'bool'],
    ['allow-nether', 'Permitir el Nether', 'bool'], ['spawn-monsters', 'Monstruos', 'bool'],
    ['spawn-animals', 'Animales', 'bool'], ['spawn-npcs', 'Aldeanos', 'bool'],
    ['enable-command-block', 'Bloques de comando', 'bool']]],
];

async function tabProps(s) {
  let d;
  try { d = await api(sPath('properties')); } catch (e) { return fail(e); }
  const v = d.values;
  $('#tabBody').innerHTML = `
    <p class="lead">Opciones de <code>server.properties</code>. Cambian al reiniciar el servidor; el resto del archivo no se toca.</p>
    ${d.running ? '<p class="notice warn">El servidor está en marcha: para cambiar el puerto o el nombre del mundo, páralo antes.</p>' : ''}
    <form class="form wide-form" id="propsForm">
      ${PROP_GROUPS.map(([title, fields]) => `
        <section class="panel"><h2>${esc(title)}</h2>
          <div class="prop-grid">${fields.map(([key, label, type, a, b]) => {
            const val = v[key] ?? '';
            if (type === 'bool') return `<label class="check"><input type="checkbox" name="${key}" ${val === 'true' ? 'checked' : ''}> ${esc(label)}</label>`;
            if (type === 'select') return `<label>${esc(label)}<select name="${key}">${a.map((o) => `<option ${o === val ? 'selected' : ''}>${o}</option>`).join('')}</select></label>`;
            if (type === 'number') return `<label>${esc(label)}<input type="number" name="${key}" value="${esc(val)}" min="${a}" max="${b}"></label>`;
            return `<label>${esc(label)}<input name="${key}" value="${esc(val)}" maxlength="${key === 'motd' ? 59 : 40}"></label>`;
          }).join('')}</div>
        </section>`).join('')}
      <p class="form-error" role="alert"></p>
      <div class="row end"><button class="btn primary" type="submit">Guardar propiedades</button></div>
    </form>`;
}

/* --- Ajustes --- */
function tabSettings(s) {
  const run = s.status.running;
  $('#tabBody').innerHTML = `
    <form class="form" id="metaForm">
      <h2>Identidad</h2>
      <label>Nombre visible<input name="display_name" maxlength="40" value="${esc(s.display_name === s.name ? '' : s.display_name)}" placeholder="${esc(s.name)}"></label>
      <fieldset class="icon-pick"><legend>Icono</legend>
        <div class="icon-grid">${state.icons.map((n) => `
          <label class="icon-opt"><input type="radio" name="icon" value="${n}"${n === s.icon ? ' checked' : ''}>
            <span class="tile">${srvIcon(n, 40)}</span><span class="sr">${n}</span></label>`).join('')}</div>
      </fieldset>
      <button class="btn primary" type="submit">Guardar identidad</button>
    </form>
    <form class="form" id="memForm">
      <h2>Memoria</h2>
      ${run ? '<p class="notice">Para el servidor antes de cambiar la memoria.</p>' : ''}
      <div class="row">
        <label>Máxima (Xmx)<input name="xmx" value="${esc(s.memory?.xmx || '')}" placeholder="8G" ${run ? 'disabled' : ''}></label>
        <label>Inicial (Xms)<input name="xms" value="${esc(s.memory?.xms || '')}" placeholder="4G" ${run ? 'disabled' : ''}></label>
      </div>
      <button class="btn" type="submit" ${run ? 'disabled' : ''}>Guardar memoria</button>
    </form>
    <section class="panel danger-zone">
      <h2>Zona peligrosa</h2>
      <p class="muted">Borra la carpeta del servidor con su mundo, mods y configuración, y quita sus permisos. No se puede deshacer.</p>
      ${run ? '<p class="notice warn">Para el servidor antes de borrarlo.</p>' : ''}
      <form class="row" id="deleteForm" data-name="${esc(s.name)}">
        <label class="grow">Escribe <code>${esc(s.name)}</code> para confirmar<input name="confirm" autocomplete="off" ${run ? 'disabled' : ''}></label>
        <button class="btn danger" type="submit" ${run ? 'disabled' : ''}>Borrar servidor</button>
      </form>
      <p class="form-error" role="alert"></p>
    </section>`;
}

/* --- Texturas (el servidor las pide a los jugadores) --- */
async function tabTextures(s) {
  const pane = state.texPane;
  $('#tabBody').innerHTML = `
    <div id="texCurrent"></div>
    ${segHTML('tex', [['providers', 'Buscar en proveedores'], ['local', 'Subir desde tu equipo']], pane, 'Origen del pack')}
    <div id="texBody"></div>`;
  if (pane === 'providers') mountFinder('resourcepack', $('#texBody'));
  else {
    $('#texBody').innerHTML = `
      <p class="lead">El servidor ofrecerá este pack a los jugadores desde el propio gestor. Para ello necesitan poder llegar a la dirección de abajo: en tu red local sirve la IP del equipo; para jugadores de fuera hace falta una dirección pública.</p>
      <label class="form-row">Dirección del gestor que verán los jugadores
        <input id="packBase" value="${esc(localStorage.getItem('packBase') || location.origin)}" aria-describedby="packBaseHelp"></label>
      <p class="muted small" id="packBaseHelp">Ejemplo: http://192.168.10.18:8765</p>
      ${dropzoneHTML('texDrop', 'Subir un pack de texturas (.zip)', 'Debe tener pack.mcmeta en la raíz, hasta 256 MB.')}
      <div id="texLocalList"></div>`;
    wireDrop('texDrop', `/api/servers/${encodeURIComponent(s.name)}/resourcepack_upload`, () => loadTex(s));
  }
  loadTex(s);
}

async function loadTex(s) {
  try {
    state.tex = await api(`/api/servers/${encodeURIComponent(s.name)}/resourcepack`);
  } catch (e) { return fail(e); }
  const c = state.tex.current, box = $('#texCurrent');
  if (box) box.innerHTML = `
    <section class="panel">
      <h2>Pack que pide el servidor</h2>
      ${c.url ? `<p class="mono small">${esc(c.url)}</p><p class="muted small">SHA-1 ${esc(c.sha1 || 'sin comprobar')}</p>`
        : '<p class="muted">El servidor no pide ningún pack de texturas a los jugadores.</p>'}
      <form class="row" id="texForm">
        <label class="check"><input type="checkbox" name="required" ${c.required ? 'checked' : ''} ${c.url ? '' : 'disabled'}> Obligatorio para entrar</label>
        <input name="prompt" maxlength="200" value="${esc(c.prompt)}" placeholder="Mensaje para el jugador (opcional)" aria-label="Mensaje al jugador" ${c.url ? '' : 'disabled'}>
        <button class="btn" type="submit" ${c.url ? '' : 'disabled'}>Guardar opciones</button>
        <button class="btn danger" type="button" data-action="tex-clear" ${c.url ? '' : 'disabled'}>Quitar pack</button>
      </form>
      <p class="muted small">Los cambios se aplican al reiniciar el servidor.</p>
    </section>`;
  const list = $('#texLocalList');
  if (list) list.innerHTML = state.tex.local.length ? `<div class="rows">${state.tex.local.map((p) => `
    <div class="row-item"><div class="grow"><strong>${esc(p.file)}</strong>
      <div class="muted small">${fmtSize(p.size)} · SHA-1 ${esc(p.sha1.slice(0, 10))}…</div></div>
      <div class="acts">
        <button class="btn primary sm" data-action="tex-use-local" data-file="${esc(p.file)}">Usar en el servidor</button>
        <button class="btn danger sm" data-action="tex-delete-local" data-file="${esc(p.file)}">Borrar</button>
      </div></div>`).join('')}</div>` : '<p class="muted pad">Todavía no has subido ningún pack.</p>';
}

/* --- Jugadores --- */
const PL_DONE = { tell: 'Mensaje enviado', say: 'Mensaje enviado a todos', kick: 'Expulsión enviada', ban: 'Ban enviado', pardon: 'Ban retirado',
  op: 'OP concedido', deop: 'OP retirado', whitelist_add: 'Añadido a la whitelist', whitelist_remove: 'Quitado de la whitelist' };

state.plSel = null;
function tabPlayers(s) {
  $('#tabBody').innerHTML = `
    <div id="plStatus" class="notice"></div>
    <div class="pl-forms">
      <form class="row" data-form="say">
        <input name="text" maxlength="200" placeholder="Mensaje para todos los jugadores conectados" aria-label="Mensaje para todos" required>
        <button class="btn" type="submit">Enviar a todos</button>
      </form>
      <form class="row" data-form="byname">
        <input name="player" maxlength="20" pattern="[A-Za-z0-9_.]{1,20}" placeholder="Jugador por nombre, aunque no esté en la lista" aria-label="Nombre de jugador" required>
        <button class="btn" type="submit" value="whitelist_add">Añadir a la whitelist</button>
        <button class="btn danger" type="submit" value="ban">Banear</button>
      </form>
    </div>
    <div id="plList"><p class="muted pad">Cargando…</p></div>`;
  loadPlayers(s);
  every(8000, () => loadPlayers(s));
}

function paintPlayers() {
  const d = state.players, host = $('#plList');
  if (!d || !host) return;
  const ctl = d.running && d.control;
  if (!d.players.some((p) => p.name === state.plSel)) state.plSel = null;
  const cols = [
    ['En línea', (p) => p.online === true, 'Nadie conectado.'],
    ['Operadores', (p) => p.op, 'Ninguno.'],
    ['Whitelist', (p) => p.whitelisted, 'Vacía.'],
    ['Baneados', (p) => p.banned, 'Nadie baneado.'],
  ];
  const chip = (p) => `<button type="button" class="pname${state.plSel === p.name ? ' sel' : ''}" data-action="pl-select" data-player="${esc(p.name)}"><span class="avatar-sm" aria-hidden="true">${esc(p.name[0].toUpperCase())}</span>${esc(p.name)}</button>`;
  const sel = d.players.find((p) => p.name === state.plSel);
  const btn = (p, act, label, cls = '') => `<button class="btn sm ${cls}" data-action="pl-act" data-act="${act}" data-player="${esc(p.name)}" ${ctl ? '' : 'disabled'}>${label}</button>`;
  const bar = sel ? `
    <div class="pl-bar"><div class="grow"><strong>${esc(sel.name)}</strong>
      <div class="chips">${sel.online === true ? '<span class="chip live">En línea</span>' : ''}${sel.op ? '<span class="chip">OP</span>' : ''}${sel.whitelisted ? '<span class="chip">Whitelist</span>' : ''}${sel.banned ? '<span class="chip bad">Baneado</span>' : ''}</div></div>
      <div class="acts">
        ${sel.online ? btn(sel, 'tell', 'Mensaje') + btn(sel, 'kick', 'Expulsar') : ''}
        ${sel.banned ? btn(sel, 'pardon', 'Perdonar') : btn(sel, 'ban', 'Banear', 'danger')}
        ${sel.op ? btn(sel, 'deop', 'Quitar OP') : btn(sel, 'op', 'Dar OP')}
        ${sel.whitelisted ? btn(sel, 'whitelist_remove', 'Quitar de whitelist') : btn(sel, 'whitelist_add', 'Añadir a whitelist')}
      </div></div>` : `<div class="pl-bar pl-hint"><span class="muted">Elige a un jugador para actuar sobre él: mensaje, expulsar, banear, OP o whitelist.</span></div>`;
  host.innerHTML = d.players.length ? `${bar}
    <div class="board">${cols.map(([title, pick, empty]) => {
      const list = d.players.filter(pick);
      return `<section class="board-col"><h2 class="board-title">${title} <span class="filter-n">${list.length}</span></h2>
        <div class="board-list">${list.map(chip).join('') || `<p class="muted small board-empty">${empty}</p>`}</div></section>`;
    }).join('')}</div>` : '<p class="muted pad">Todavía no ha entrado ningún jugador a este servidor.</p>';
}

async function loadPlayers(s) {
  try {
    const d = await api(`/api/servers/${encodeURIComponent(s.name)}/players`);
    state.players = d;
    const st = $('#plStatus');
    if (!st) return;
    st.textContent = !d.running ? 'El servidor está parado. Se muestran los jugadores conocidos por sus archivos; para actuar sobre ellos arranca el servidor desde el gestor.'
      : !d.control ? 'Este servidor se arrancó fuera del gestor, así que no puedo enviarle órdenes. Páralo y vuelve a arrancarlo desde aquí.'
      : d.online_count == null ? 'El servidor no respondió a la lista de jugadores; puede estar todavía arrancando.'
      : `${d.online_count} de ${d.max} jugadores conectados${d.whitelist_enabled ? ' · whitelist activada' : ''}`;
    paintPlayers();
  } catch (e) { fail(e); }
}

async function runPlayerAction(action, player, text) {
  await api(sPath('player'), { method: 'POST', body: { action, player, text } });
  toast(`${PL_DONE[action]}${player ? `: ${player}` : ''}`, 'ok');
  setTimeout(() => state.view.tab === 'players' && loadPlayers(current()), 900);
}

/* ---------- ficha de un mod (como la página de CurseForge) ---------- */
const skelPage = () => `
  <div class="skel-head"><span class="skel sq"></span><div class="skel-lines"><span class="skel"></span><span class="skel"></span></div></div>
  <span class="skel block-lg"></span><span class="skel block-lg"></span><span class="skel"></span><span class="skel"></span>`;

async function renderModPage() {
  const v = state.view;
  $('#main').innerHTML = `<div class="modpage"><article class="modpage-main" id="mpMain" aria-busy="true">${skelPage()}</article><aside class="modpage-side" id="mpSide" aria-label="Instalar"></aside></div>`;
  let d;
  try {
    d = await api('/api/mod?' + new URLSearchParams({ source: v.source, id: v.id, loader: state.loader, version: state.version }));
  } catch (e) {
    if (state.view !== v) return;
    $('#main').innerHTML = `<div class="empty"><h1>No se pudo abrir el mod</h1><p class="form-error" role="alert">${esc(e.message)}</p>
      <p><a href="#/s/${encodeURIComponent(state.servers[0] ? state.servers[0].name : '')}">Volver</a></p></div>`;
    return;
  }
  if (state.view !== v) return;  // el usuario ya se fue a otra pantalla

  const targets = state.servers.filter((s) => isAdmin() || (s.permissions && s.permissions.mods));
  const SRC_NAME = { modrinth: 'Modrinth', curseforge: 'CurseForge' };
  const meta = [
    `${fmtNum(d.downloads)} descargas`,
    d.followers ? `${fmtNum(d.followers)} seguidores` : null,
    d.updated ? `Actualizado ${fmtTime(Date.parse(d.updated) / 1000).split(',')[0]}` : null,
    d.license ? `Licencia ${esc(d.license)}` : null,
  ].filter(Boolean);

  $('#mpMain').setAttribute('aria-busy', 'false');
  $('#mpMain').innerHTML = `
    <header class="mp-head">
      <span class="mp-icon">${d.icon ? `<img src="${esc(d.icon)}" alt="">` : '<span class="img-ph"></span>'}</span>
      <div class="grow">
        <h1>${esc(d.name)}</h1>
        <p class="mp-summary">${esc(d.summary)}</p>
        <p class="mp-meta muted small">${meta.map(esc).join(' · ')}</p>
        <div class="chips">
          <span class="chip src">${SRC_NAME[d.source]}</span>
          ${d.client ? `<span class="chip">Cliente: ${esc(d.client)}</span>` : ''}
          ${d.server ? `<span class="chip">Servidor: ${esc(d.server)}</span>` : ''}
          ${(d.loaders || []).map((l) => `<span class="chip violet">${esc(l)}</span>`).join('')}
          ${d.categories.slice(0, 6).map((c) => `<span class="chip">${esc(c)}</span>`).join('')}
        </div>
      </div>
    </header>
    ${d.gallery.length ? `<div class="gallery" aria-label="Capturas">${d.gallery.map((g) => `
      <figure class="shot"><img src="${esc(g.url)}" alt="${esc(g.title)}" loading="lazy">${g.title ? `<figcaption class="small muted">${esc(g.title)}</figcaption>` : ''}</figure>`).join('')}</div>` : ''}
    <section class="prose" aria-label="Descripción">${d.body_html || '<p class="muted">Este mod no tiene descripción.</p>'}</section>`;

  const links = Object.entries({ Página: d.links.page, Código: d.links.source, Incidencias: d.links.issues, Wiki: d.links.wiki, Discord: d.links.discord })
    .filter(([, u]) => u);
  $('#mpSide').innerHTML = `
    <section class="panel install-card">
      <h2>Instalar</h2>
      ${targets.length ? `
        <label class="stack">Servidor de destino
          <select id="mpTarget">${targets.map((s) => `<option value="${esc(s.name)}">${esc(s.display_name)}</option>`).join('')}</select>
        </label>
        <p class="muted small">Versiones para Minecraft ${esc(state.version)} · ${esc(state.loader)}</p>
        <div class="versions">${d.files.length ? d.files.map((f) => `
          <div class="file">
            <span><strong>${esc(f.version)}</strong><span class="muted small block">${esc(f.date)}</span></span>
            ${f.url ? `<button class="btn sm" data-action="page-install" data-kind="mod" data-source="${esc(d.source)}" data-project="${esc(d.id)}" data-vid="${esc(f.id)}" data-url="${esc(f.url)}" data-name="${esc(f.filename)}" data-sha1="${esc(f.sha1 || '')}">Instalar</button>`
              : `<span class="muted small">Sin descarga directa</span>`}
          </div>`).join('') : '<p class="muted small">Sin versiones para esta combinación de Minecraft y loader.</p>'}</div>`
        : '<p class="muted small">No tienes permiso para instalar mods en ningún servidor.</p>'}
    </section>
    <section class="panel">
      <h2>Enlaces</h2>
      <ul class="links">${links.map(([k, u]) => `<li><a href="${esc(u)}" target="_blank" rel="noopener nofollow">${esc(k)}</a></li>`).join('') || '<li class="muted small">Sin enlaces</li>'}</ul>
      ${d.authors.length ? `<h3>Autores</h3><p>${d.authors.map(esc).join(', ')}</p>` : ''}
    </section>`;
}

/* ---------- crear un servidor desde plantilla ---------- */
const TPL_ICON = { vanilla: 'orb', fabric: 'gear', neoforge: 'diamond', forge: 'shield', paper: 'leaf' };
const TPL_KIND = { none: 'Sin mods ni plugins', mod: 'Admite mods', plugin: 'Admite plugins' };
const SRV_STEPS = ['Preparando la carpeta', 'Descargando e instalando el servidor', 'Instalando el preset de rendimiento', 'Escribiendo la configuración', 'Listo'];

async function openNewServer() {
  let tpls;
  let extras = [];
  try { tpls = await api('/api/templates'); } catch (e) { return fail(e); }
  try { extras = await api('/api/extras'); } catch (e) { extras = []; }   // un gestor sin reiniciar aún no tiene la ruta
  const d = openDialog(`
    <form class="dlg wizard" id="wizardForm" aria-labelledby="wizTitle">
      <header><h2 id="wizTitle">Nuevo servidor</h2><button class="btn ghost sm" type="button" data-action="close">Cerrar</button></header>
      <fieldset class="tpl-set">
        <legend>Tipo de servidor</legend>
        <div class="tpl-grid">${tpls.map((t, i) => `
          <label class="tpl-card">
            <input type="radio" name="template" value="${esc(t.id)}" ${i === 0 ? 'checked' : ''}>
            <span class="tile">${srvIcon(t.id, 34)}</span>
            <span class="grow"><strong>${esc(t.label)}</strong><span class="muted small block">${esc(t.desc)}</span>
              <span class="chip">${TPL_KIND[t.kind]}</span></span>
          </label>`).join('')}
          <label class="tpl-card">
            <input type="radio" name="template" value="modpack">
            <span class="tile">${pixelIcon('star', 34)}</span>
            <span class="grow"><strong>Jugar con modpack</strong><span class="muted small block">Un modpack ya armado, con su servidor oficial y los mods del lado servidor.</span>
              <span class="chip">Modpack NeoForge</span></span>
          </label>
        </div>
      </fieldset>
      <section class="modpack-box" id="wizModpack" hidden>
        <div class="search-main">
          <select name="mp_source" aria-label="Fuente del modpack"><option value="modrinth">Modrinth</option><option value="curseforge">CurseForge</option></select>
          <input name="mp_q" placeholder="Buscar modpacks (vacío: los más descargados)" aria-label="Buscar modpacks">
          <button class="btn" type="button" data-action="mp-search">Buscar</button>
        </div>
        <div class="mp-results" id="mpResults"><p class="muted small">Elige una fuente y busca.</p></div>
        <div class="row wiz-row" id="mpPick" hidden>
          <label class="grow">Modpack elegido<input name="mp_name" readonly></label>
          <label class="grow">Versión<select name="mp_version"></select></label>
        </div>
        <label class="check"><input type="checkbox" name="mp_client" checked> Guardar también el cliente original del modpack, sin cambios, para compartirlo</label>
      </section>
      <div class="row wiz-row" id="wizMcRow">
        <label class="grow">Versión de Minecraft<select name="mc" required aria-busy="true" aria-describedby="mcHelp"><option>Cargando…</option></select><span id="mcHelp" class="muted small">La versión que descargará el servidor. Los mods se filtran por esta versión.</span></label>
        <label>Memoria<select name="memory">${['2G', '4G', '6G', '8G'].map((m) => `<option ${m === '4G' ? 'selected' : ''}>${m}</option>`).join('')}</select></label>
      </div>
      <div class="row wiz-row">
        <label class="grow">Nombre interno (carpeta)<input name="name" required pattern="[A-Za-z0-9._-]{1,40}" maxlength="40" placeholder="survival-2026" autocomplete="off" aria-describedby="nameHelp"><span id="nameHelp" class="muted small">Solo letras, números, puntos y guiones. Es la carpeta en tu equipo.</span></label>
        <label class="grow">Nombre visible<input name="display_name" maxlength="40" placeholder="Opcional"></label>
        <label>Puerto<input name="port" type="number" min="1024" max="65535" placeholder="Automático"></label>
      </div>
      <fieldset class="preset" id="wizPerf" hidden>
        <label class="check"><input type="checkbox" name="perf" checked>
          <span><strong>Preset de rendimiento</strong> <span class="chip">solo servidor</span>
            <span class="muted small block" id="wizPerfDesc"></span></span></label>
        <ul class="preset-list" id="wizPerfList"></ul>
      </fieldset>
      <fieldset class="preset" id="wizExtras" hidden>
        <legend>Extras opcionales</legend>
        ${extras.map((x) => `<label class="check" data-extra="${esc(x.id)}" data-loaders="${esc((x.loaders || []).join(','))}">
          <input type="checkbox" name="extra" value="${esc(x.id)}">
          <span><strong>${esc(x.label)}</strong>
            <span class="muted small block">${esc(x.desc)}</span></span></label>`).join('')}
      </fieldset>
      <label class="check"><input type="checkbox" name="accept_eula" required> Acepto el <a href="https://www.minecraft.net/eula" target="_blank" rel="noopener">EULA de Minecraft</a></label>
      <p class="form-error" role="alert"></p>
      <div id="wizProgress" class="srv-progress" hidden></div>
      <div class="row end"><button class="btn" type="button" data-action="close">Cancelar</button><button class="btn primary" type="submit">Crear servidor</button></div>
    </form>`, true);
  const form = $('#wizardForm', d);
  const showPerf = () => {
    const isMp = form.template.value === 'modpack';
    $('#wizModpack', d).hidden = !isMp;
    $('#wizMcRow', d).hidden = isMp;
    form.mc.disabled = isMp;
    const t = tpls.find((x) => x.id === form.template.value);
    const list = isMp ? [] : ((t && t.perf) || []);
    $('#wizPerf', d).hidden = list.length === 0;
    $('#wizPerfDesc', d).textContent = list.length ? `${list.length} mods de optimización que se instalan por defecto. Puedes quitar la casilla.` : '';
    $('#wizPerfList', d).innerHTML = list.map((m) => `<li><strong>${esc(m.title)}</strong> <span class="muted small">${esc(m.desc)}</span></li>`).join('');
    // Extras: solo los que valen para el cargador elegido (un modpack es NeoForge). Al ocultarse, se desmarcan.
    const loader = isMp ? 'neoforge' : (t && t.loader) || '';
    let shown = 0;
    d.querySelectorAll('#wizExtras [data-extra]').forEach((lb) => {
      const ok = !lb.dataset.loaders || lb.dataset.loaders.split(',').includes(loader);
      lb.hidden = !ok; shown += ok ? 1 : 0;
      if (!ok) lb.querySelector('input').checked = false;
    });
    $('#wizExtras', d).hidden = shown === 0;
  };
  form.template.forEach((r) => r.addEventListener('change', showPerf));
  showPerf();
  const loadVersions = async () => {
    const tpl = form.template.value;
    if (tpl === 'modpack') return;
    const sel = form.mc;
    sel.setAttribute('aria-busy', 'true'); sel.innerHTML = '<option>Cargando…</option>';
    try {
      const { versions } = await api('/api/templates/versions?' + new URLSearchParams({ template: tpl }));
      sel.innerHTML = versions.slice(0, 80).map((v) => `<option>${esc(v)}</option>`).join('');
      sel.removeAttribute('aria-busy');
    } catch (e) { sel.innerHTML = '<option value="">No disponible</option>'; sel.removeAttribute('aria-busy'); fail(e); }
  };
  form.template.forEach((r) => r.addEventListener('change', loadVersions));
  loadVersions();
  form.name.addEventListener('input', () => { form.name.value = form.name.value.replace(/[^A-Za-z0-9._-]/g, ''); });
  form.mp_q.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); searchModpacks(form, d); } });
  d.addEventListener('close', () => { clearInterval(state.srvTimer); });
  $('input[name=name]', d).focus();
}

async function searchModpacks(f, d) {
  const box = $('#mpResults', d);
  box.innerHTML = '<p class="muted small" aria-busy="true">Buscando…</p>';
  try {
    const p = new URLSearchParams({ source: f.mp_source.value, q: f.mp_q.value.trim(), mc: '1.21.1' });
    const hits = await api('/api/modpacks/search?' + p);
    box.innerHTML = hits.length ? hits.map((h) => `
      <button type="button" class="mp-hit" data-action="mp-pick" data-source="${esc(h.source)}" data-id="${esc(h.id)}" data-name="${esc(h.name)}">
        ${h.icon ? `<img src="${esc(h.icon)}" alt="" width="40" height="40">` : '<span class="img-ph"></span>'}
        <span class="grow"><strong>${esc(h.name)}</strong><span class="muted small block">${esc(h.summary)}</span></span>
        <span class="chip">${fmtNum(h.downloads)}</span>
      </button>`).join('') : '<p class="muted small">Sin modpacks con servidor para esa búsqueda.</p>';
  } catch (e) { box.innerHTML = `<p class="form-error">${esc(e.message)}</p>`; }
}

async function pickModpack(btn, d) {
  const f = $('#wizardForm', d);
  f.mp_name.value = btn.dataset.name;
  f.mp_name.dataset.id = btn.dataset.id;
  f.mp_name.dataset.source = btn.dataset.source;
  $('#mpPick', d).hidden = false;
  const sel = f.mp_version;
  sel.innerHTML = '<option>Cargando…</option>';
  try {
    const vs = await api('/api/modpacks/versions?' + new URLSearchParams({ source: btn.dataset.source, project: btn.dataset.id, mc: '1.21.1' }));
    sel.innerHTML = vs.length ? vs.map((v) => `<option value="${esc(v.id)}">${esc(v.name)} · ${esc(v.date)}</option>`).join('') : '<option value="">Sin versiones con servidor</option>';
  } catch (e) { sel.innerHTML = '<option value="">No disponible</option>'; fail(e); }
  if (!f.name.value) f.name.value = btn.dataset.name.replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40);
}

async function createModpackFromForm(f) {
  const err = $('.form-error', f), btn = $('button[type=submit]', f);
  err.textContent = '';
  if (!f.mp_name.dataset.id) { err.textContent = 'Elige un modpack primero.'; return; }
  if (!f.mp_version.value) { err.textContent = 'Ese modpack no tiene versión con servidor.'; return; }
  const body = {
    source: f.mp_name.dataset.source, project: f.mp_name.dataset.id, version: f.mp_version.value, include_client: f.mp_client.checked,
    name: f.name.value.trim(), display_name: f.display_name.value.trim(), memory: f.memory.value,
    port: f.port.value ? Number(f.port.value) : null, accept_eula: f.accept_eula.checked, extras: pickedExtras(f),
  };
  btn.disabled = true; btn.textContent = 'Creando…';
  let job;
  try { ({ job } = await api('/api/servers/create_modpack', { method: 'POST', body })); }
  catch (e) { btn.disabled = false; btn.textContent = 'Crear servidor'; err.textContent = e.message; return; }
  return followJob(f, job, body.name);
}

const pickedExtras = (f) => [...f.querySelectorAll('input[name=extra]:checked')].filter((i) => !i.closest('[hidden]')).map((i) => i.value);

async function createServerFromForm(f) {
  if (f.template.value === 'modpack') return createModpackFromForm(f);
  return createTemplateServerFromForm(f);
}

async function createTemplateServerFromForm(f) {
  const err = $('.form-error', f), btn = $('button[type=submit]', f);
  err.textContent = '';
  const body = {
    template: f.template.value, mc: f.mc.value, memory: f.memory.value, name: f.name.value.trim(),
    display_name: f.display_name.value.trim(), port: f.port.value ? Number(f.port.value) : null, accept_eula: f.accept_eula.checked,
    perf: !!(f.perf && !f.perf.closest('[hidden]') && f.perf.checked), extras: pickedExtras(f),
  };
  btn.disabled = true; btn.textContent = 'Creando…';
  let job;
  try { ({ job } = await api('/api/servers/create', { method: 'POST', body })); }
  catch (e) { btn.disabled = false; btn.textContent = 'Crear servidor'; err.textContent = e.message; return; }
  return followJob(f, job, body.name);
}

// Cambia el formulario por el progreso del trabajo y lo sigue hasta que termina o falla.
function followJob(f, job, name) {
  f.querySelectorAll('fieldset, .wiz-row, label, .row.end, .modpack-box').forEach((n) => { if (!n.closest('#wizProgress')) n.hidden = true; });
  const box = $('#wizProgress', f);
  box.hidden = false;
  const paintList = (steps) => {
    box.innerHTML = `<ol class="progress-steps">${steps.map((s) => `<li data-state="todo">${esc(s)}</li>`).join('')}</ol>
      <p class="form-error" role="alert"></p><div class="row end"><button class="btn" type="button" data-action="close" data-wiz-close>Cerrar</button></div>`;
    return $$('li', box);
  };
  let items = paintList(SRV_STEPS);
  clearInterval(state.srvTimer);
  state.srvTimer = setInterval(async () => {
    let st;
    try { st = await api(`/api/jobs/${job}`); } catch (e) { return; }
    if (st.steps && st.steps.length !== items.length) items = paintList(st.steps);
    items.forEach((li, i) => { li.dataset.state = i < st.step ? 'done' : i === st.step ? (st.state === 'error' ? 'error' : 'run') : 'todo'; });
    if (st.state === 'done') items.forEach((li) => { li.dataset.state = 'done'; });
    if (st.state === 'error') {
      clearInterval(state.srvTimer);
      $('.form-error', box).textContent = st.error || 'No se pudo crear el servidor';
    }
    if (st.state === 'done') {
      clearInterval(state.srvTimer);
      const perf = st.perf || [];
      const bad = perf.filter((m) => m.status !== 'ok');
      toast(`Servidor «${name}» creado${perf.length ? ` · ${perf.length - bad.length}/${perf.length} mods de rendimiento` : ''}`, 'ok');
      bad.forEach((m) => toast(`${m.title}: ${m.note}`, 'error'));
      await refreshServers();
      actions.close();
      location.hash = `#/s/${encodeURIComponent(name)}`;
    }
  }, 1200);
}

/* ---------- administración ---------- */
async function renderUsers(selectId) {
  state.draft = null;
  $('#main').innerHTML = `
    <header class="page-head"><h1>Usuarios y permisos</h1>
      <button class="btn primary" data-action="user-new">Nuevo usuario</button></header>
    <div class="split users-split"><div class="split-list" id="usersBody"><p class="muted pad">Cargando…</p></div>
      <section class="split-detail" id="userPane" aria-live="polite"></section></div>`;
  try {
    const users = await api('/api/users');
    state.users = users;
    $('#usersBody').innerHTML = `<div class="rows">${users.map((u) => {
      const n = Object.keys(u.permissions).length;
      return `<button type="button" class="row-item row-btn${u.active ? '' : ' off'}" data-action="user-select" data-id="${u.id}">
        <span class="tile sm avatar" aria-hidden="true">${esc(u.username[0].toUpperCase())}</span>
        <span class="grow"><strong>${esc(u.username)}</strong>
          <span class="muted small block">${u.is_admin ? 'Administrador: acceso total' : n ? `Acceso a ${n} ${n === 1 ? 'servidor' : 'servidores'}` : 'Sin acceso a ningún servidor'}${u.active ? '' : ' · desactivado'}</span></span></button>`;
    }).join('')}</div>`;
    enterOnce($('#usersBody .rows'));
    const pick = users.find((u) => u.id === selectId);
    if (pick) mountUserEditor(pick);
    else $('#userPane').innerHTML = `<div class="detail-empty"><h2>${users.length} ${users.length === 1 ? 'usuario' : 'usuarios'}</h2>
      <p class="muted">Elige un usuario de la lista para ver y cambiar a qué servidores accede y qué puede hacer en cada uno.</p></div>`;
  } catch (e) { fail(e); }
}

const PERM_LABELS = { logs: 'Ver logs', mods: 'Instalar mods', datapacks: 'Datapacks', textures: 'Texturas', players: 'Jugadores', control: 'Encender y apagar' };
const PERM_KEYS = Object.keys(PERM_LABELS);
const clone = (o) => JSON.parse(JSON.stringify(o));
// Forma canónica para comparar: solo servidores con algún permiso y todas las claves como booleanos.
const norm = (d) => ({
  active: !!d.active, is_admin: !!d.is_admin,
  permissions: Object.fromEntries(Object.entries(d.permissions)
    .map(([srv, p]) => [srv, Object.fromEntries(PERM_KEYS.map((k) => [k, !!p[k]]))])
    .filter(([, p]) => PERM_KEYS.some((k) => p[k])).sort(([a], [b]) => a.localeCompare(b))),
});
const isDirty = () => !!state.draft && JSON.stringify(norm(state.draft.cur)) !== JSON.stringify(norm(state.draft.base));
function refreshDirty() {
  const dirty = isDirty(), btn = $('#saveBtn'), note = $('#dirtyNote');
  if (btn) btn.disabled = !dirty;
  if (note) { note.textContent = dirty ? 'Hay cambios sin guardar' : 'Sin cambios'; note.classList.toggle('warn', dirty); }
}

function userEditorHTML(u, embedded) {
  const self = u.id === state.me.id;
  const rows = state.servers.map((s) => {
    const p = u.permissions[s.name] || {};
    return `<tr><th scope="row"><span class="tile sm">${srvIcon(s.icon, 22)}</span>${esc(s.display_name)}</th>${PERM_KEYS.map((k) =>
      `<td><input type="checkbox" data-perm="${k}" data-server="${esc(s.name)}" aria-label="${PERM_LABELS[k]} en ${esc(s.display_name)}" ${p[k] ? 'checked' : ''} ${u.is_admin ? 'disabled' : ''}></td>`).join('')}</tr>`;
  }).join('');
  return `
    <div class="dlg${embedded ? ' embedded' : ''}" data-user="${u.id}">
      <header><h2>${esc(u.username)}</h2>${embedded ? '' : '<button class="btn ghost sm" data-action="user-close">Cerrar</button>'}</header>
      ${u.is_admin ? '<p class="notice">Los administradores tienen acceso total; los permisos por servidor no aplican.</p>' : ''}
      <h3>Permisos por servidor</h3>
      <div class="table-wrap"><table class="perm-table"><thead><tr><th>Servidor</th>${PERM_KEYS.map((k) => `<th>${PERM_LABELS[k]}</th>`).join('')}</tr></thead>
        <tbody>${rows || '<tr><td colspan="7" class="muted">No hay servidores.</td></tr>'}</tbody></table></div>
      <h3>Cuenta</h3>
      <div class="row">
        <label class="check"><input type="checkbox" data-acct="active" ${u.active ? 'checked' : ''} ${self ? 'disabled' : ''}> Cuenta activa</label>
        <label class="check"><input type="checkbox" data-acct="is_admin" ${u.is_admin ? 'checked' : ''} ${self ? 'disabled' : ''}> Administrador</label>
      </div>
      <div class="savebar">
        <span id="dirtyNote" class="muted small">Sin cambios</span>
        <button class="btn primary" id="saveBtn" data-action="user-save" disabled>Guardar cambios</button>
      </div>
      <h3>Contraseña</h3>
      <div class="row"><input id="uPass" type="password" placeholder="Nueva contraseña (mínimo 8 caracteres)" autocomplete="new-password" aria-label="Nueva contraseña">
        <button class="btn" type="button" data-action="user-pass" data-id="${u.id}">Cambiar contraseña</button></div>
      ${self ? '' : `<div class="row end"><button class="btn danger" type="button" data-action="user-delete" data-id="${u.id}">Borrar usuario</button></div>`}
    </div>`;
}
function mountUserEditor(u) {
  $('#userPane').innerHTML = userEditorHTML(u, true);
  $$('#usersBody .row-btn').forEach((b) => b.classList.toggle('sel', Number(b.dataset.id) === u.id));
  const base = { active: u.active, is_admin: u.is_admin, permissions: clone(u.permissions) };
  state.draft = { id: u.id, base, cur: clone(base) };
}
function userDialog(u) {
  const base = { active: u.active, is_admin: u.is_admin, permissions: clone(u.permissions) };
  openDialog(userEditorHTML(u, false), true);
  state.draft = { id: u.id, base, cur: clone(base) };  // después de abrir: el cierre del diálogo anterior limpia el borrador
}

async function renderAudit() {
  $('#main').innerHTML = `<header class="page-head"><h1>Actividad</h1></header><div id="auditBody"><p class="muted pad">Cargando…</p></div>`;
  try {
    const rows = await api('/api/audit?limit=200');
    $('#auditBody').innerHTML = rows.length ? `<table class="table"><thead><tr><th>Cuándo</th><th>Usuario</th><th>Servidor</th><th>Acción</th><th>Detalle</th></tr></thead><tbody>${rows.map((r) => `
      <tr><td>${fmtTime(r.ts)}</td><td>${esc(r.username)}</td><td>${esc(r.server_name || '')}</td><td>${esc(r.action)}</td><td class="muted">${esc(r.detail || '')}</td></tr>`).join('')}</tbody></table>`
      : '<p class="muted pad">Todavía no hay actividad registrada.</p>';
  } catch (e) { fail(e); }
}

async function startInstall(server, el) {
  const { kind } = el.dataset;
  busy(el, true); el.textContent = kind === 'mod' ? 'Comprobando…' : 'Instalando…';
  try {
    if (kind === 'mod') {  // antes de instalar, ver qué otros mods necesita
      let plan = null;
      try {
        plan = await api('/api/deps?' + new URLSearchParams({ server: server, source: el.dataset.source, project: el.dataset.project, vid: el.dataset.vid, loader: state.loader, version: state.version }));
      } catch (e) {
        if (e.status === 401) throw e;
        if (!(await askConfirm('No se pudieron comprobar las dependencias', `${e.message}. ¿Instalar solo este mod?`, { confirmLabel: 'Instalar solo este mod' }))) { busy(el, false); el.textContent = 'Instalar'; return; }
      }
      if (plan && (plan.deps.length || plan.warnings.length)) { busy(el, false); el.textContent = 'Instalar'; return depsDialog(el, plan); }
      el.textContent = 'Instalando…';
    }
    const r = await api('/api/install', { method: 'POST', body: { server: server, kind, url: el.dataset.url, filename: el.dataset.name, sha1: el.dataset.sha1 || null } });
    toast(`Instalado ${r.installed}. Reinicia el servidor para cargarlo.`, 'ok');
    el.textContent = 'Instalado';
    const card = el.closest('.result');
    if (card && (kind === 'mod' || kind === 'plugin')) rememberInstalled(el.dataset.source, el.dataset.project, card.dataset.slug, $('.file span', el.closest('.file'))?.textContent);
    refreshServers();
  } catch (e) { fail(e); busy(el, false); el.textContent = 'Instalar'; }
}

/* ---------- acciones (delegación de eventos) ---------- */
const sName = () => state.view.name;
const sPath = (suffix) => `/api/servers/${encodeURIComponent(sName())}/${suffix}`;
const busy = (el, on) => { el.disabled = on; };

const actions = {
  'finder-tag'(el) {
    const f = state.finder[el.dataset.kind], t = el.dataset.tag;
    f.tags = f.tags.includes(t) ? f.tags.filter((x) => x !== t) : [...f.tags, t];
    runFinder(el.dataset.kind, $(`form[data-finder="${el.dataset.kind}"]`));
  },
  'finder-tag-clear'(el) { state.finder[el.dataset.kind].tags = []; runFinder(el.dataset.kind, $(`form[data-finder="${el.dataset.kind}"]`)); },
  'finder-page'(el) {
    const kind = el.dataset.kind, form = $(`form[data-finder="${kind}"]`);
    runFinder(kind, form, Number(el.dataset.page));
    const top = $(`#results-${kind}`); if (top && top.scrollIntoView) top.scrollIntoView({ block: 'start', behavior: 'auto' });
  },
  'pl-select'(el) { state.plSel = state.plSel === el.dataset.player ? null : el.dataset.player; paintPlayers(); },
  'mod-select'(el) { state.modSel = state.modSel === el.dataset.file ? null : el.dataset.file; paintMods(); },
  'mod-filter'(el) { state.modFilter = el.dataset.filter; paintMods(); },
  'log-level'(el) { state.logLevel = el.dataset.level; $$('[data-action=log-level]').forEach((b) => b.classList.toggle('on', b === el)); paintLog(); },
  theme() {
    const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
    document.documentElement.dataset.theme = next;
    localStorage.setItem('theme', next);
    renderSide();
  },
  async logout() { try { await api('/api/logout', { method: 'POST', body: {} }); } catch { /* ya cerrada */ } state.me = null; renderLogin(); },
  password() {
    const d = openDialog(`
      <form class="dlg" id="pwForm"><header><h2>Cambiar contraseña</h2></header>
        <label>Contraseña actual<input name="old" type="password" autocomplete="current-password" required></label>
        <label>Nueva contraseña<input name="new" type="password" autocomplete="new-password" minlength="8" required></label>
        <label>Repite la nueva<input name="again" type="password" autocomplete="new-password" minlength="8" required></label>
        <p class="form-error" role="alert"></p>
        <div class="row end"><button class="btn" type="button" data-action="close">Cancelar</button><button class="btn primary" type="submit">Guardar</button></div>
      </form>`);
    $('input', d).focus();
  },
  close() { $$('dialog').forEach((d) => d.close()); },

  async start(el) {
    busy(el, true);
    const name = sName();
    try {
      await api(sPath('start'), { method: 'POST', body: {} });
      state.starting[name] = Date.now() + 90000;  // cian con pulso hasta que el servidor responda
      toast('Servidor arrancando…', 'ok');
    } catch (e) { fail(e); state.ledError[name] = true; setTimeout(() => { delete state.ledError[name]; renderSide(); }, 1400); }
    setTimeout(refreshServers, 800);
  },
  async stop(el) {
    if (!(await askConfirm('¿Parar el servidor?', 'Se guardará el mundo antes de cerrarlo. Los jugadores conectados se desconectarán.', { confirmLabel: 'Parar servidor', danger: true }))) return;
    busy(el, true); el.textContent = 'Parando…';
    try { await api(sPath('stop'), { method: 'POST', body: {} }); toast('Servidor parado', 'ok'); } catch (e) { fail(e); }
    refreshServers();
  },

  pane(el) {
    state[`${el.dataset.scope}Pane`] = el.dataset.pane;
    ({ mods: tabMods, dp: tabDatapacks, tex: tabTextures })[el.dataset.scope](current());
  },
  async 'mod-toggle'(el) {
    state.installed.at = 0;
    try { await api(sPath('mod_toggle'), { method: 'POST', body: { file: el.dataset.file } }); loadInstalled(current()); } catch (e) { fail(e); }
  },
  async 'mod-delete'(el) {
    state.installed.at = 0;
    if (!(await askConfirm('¿Borrar este mod?', `${el.dataset.file} se elimina de la carpeta mods/. No se puede deshacer.`, { confirmLabel: 'Borrar mod', danger: true }))) return;
    try { await api(sPath('mod_delete'), { method: 'POST', body: { file: el.dataset.file } }); toast('Mod borrado', 'ok'); loadInstalled(current()); refreshServers(); } catch (e) { fail(e); }
  },
  async 'mod-update'(el) {
    state.installed.at = 0;
    busy(el, true); el.textContent = 'Actualizando…';
    try {
      const r = await api(sPath('mod_update'), { method: 'POST', body: { file: el.dataset.file, loader: state.loader, version: state.version } });
      toast(`Actualizado a ${r.installed}`, 'ok');
    } catch (e) { fail(e); }
    loadInstalled(current());
  },
  async 'finder-files'(el) {
    const card = el.closest('.result'), box = $('[data-files]', card), kind = card.dataset.kind;
    if (box.dataset.open) { box.innerHTML = ''; delete box.dataset.open; el.textContent = 'Ver versiones'; return; }
    busy(el, true);
    try {
      const p = new URLSearchParams({ kind, source: card.dataset.source, project: card.dataset.id, slug: card.dataset.slug, loader: state.loader, version: state.version,
        ...(state.view.kind === 'server' ? { server: state.view.name } : {}) });
      const files = await api('/api/files?' + p);
      box.dataset.open = '1'; el.textContent = 'Ocultar';
      box.innerHTML = files.map((f) => {
        const act = !f.url ? (f.page ? `<a class="btn sm" target="_blank" rel="noopener" href="${esc(f.page)}">Descargar a mano</a>` : '')
          : kind === 'resourcepack'
            ? `<button class="btn sm" data-action="pack-use-remote" data-url="${esc(f.url)}" data-sha1="${esc(f.sha1 || '')}">Usar en el servidor</button>`
            : (kind === 'mod' || kind === 'plugin') && instVersion(card.dataset.source, card.dataset.id) === f.version
              ? '<button class="btn sm" disabled>Instalado</button>'
              : `<button class="btn sm" data-action="finder-install" data-kind="${kind}" data-source="${esc(card.dataset.source)}" data-project="${esc(card.dataset.id)}" data-vid="${esc(f.id)}" data-url="${esc(f.url)}" data-name="${esc(f.filename)}" data-sha1="${esc(f.sha1 || '')}">Instalar</button>`;
        return `<div class="file"><span>${esc(f.version)}</span><span class="muted small">${esc(f.date)} · ${esc(f.filename)}</span>${act}</div>`;
      }).join('') || '<span class="muted small">Sin versiones para esta combinación.</span>';
    } catch (e) { fail(e); }
    busy(el, false);
  },
  async 'finder-install'(el) { return startInstall(sName(), el); },
  async 'page-install'(el) { return startInstall($('#mpTarget').value, el); },
  async 'pack-use-remote'(el) {
    busy(el, true);
    const c = state.tex ? state.tex.current : { required: false, prompt: '' };
    try {
      await api(sPath('resourcepack_set'), { method: 'POST', body: { url: el.dataset.url, sha1: el.dataset.sha1, required: c.required, prompt: c.prompt } });
      toast('El servidor pedirá este pack a los jugadores. Reinícialo para aplicarlo.', 'ok');
      loadTex(current());
    } catch (e) { fail(e); }
    busy(el, false);
  },
  async 'tex-use-local'(el) {
    const base = $('#packBase').value.trim(), c = state.tex.current;
    try {
      await api(sPath('resourcepack_use'), { method: 'POST', body: { file: el.dataset.file, base_url: base, required: c.required, prompt: c.prompt } });
      localStorage.setItem('packBase', base);
      toast('El servidor pedirá este pack a los jugadores. Reinícialo para aplicarlo.', 'ok');
      loadTex(current());
    } catch (e) { fail(e); }
  },
  async 'tex-delete-local'(el) {
    if (!(await askConfirm('¿Borrar este pack?', `${el.dataset.file} se elimina. Si el servidor lo está pidiendo, dejará de pedirse.`, { confirmLabel: 'Borrar pack', danger: true }))) return;
    try { await api(sPath('resourcepack_delete'), { method: 'POST', body: { file: el.dataset.file } }); toast('Pack borrado', 'ok'); loadTex(current()); } catch (e) { fail(e); }
  },
  async 'tex-clear'() {
    if (!(await askConfirm('¿Quitar el pack del servidor?', 'Los jugadores dejarán de recibir texturas al reiniciar el servidor.', { confirmLabel: 'Quitar pack', danger: true }))) return;
    try { await api(sPath('resourcepack_set'), { method: 'POST', body: { url: '', sha1: '', required: false, prompt: '' } }); toast('Pack quitado', 'ok'); loadTex(current()); } catch (e) { fail(e); }
  },
  async 'pl-act'(el) {
    const { act, player } = el.dataset;
    if (['tell', 'kick', 'ban'].includes(act)) {
      const label = { tell: 'Enviar mensaje', kick: 'Expulsar', ban: 'Banear' }[act];
      const d = openDialog(`
        <form class="dlg" id="plForm" data-act="${act}" data-player="${esc(player)}"><header><h2>${label}: ${esc(player)}</h2></header>
          <label>${act === 'tell' ? 'Mensaje' : 'Motivo (opcional)'}<input name="text" maxlength="200" ${act === 'tell' ? 'required' : ''} autocomplete="off"></label>
          <p class="form-error" role="alert"></p>
          <div class="row end"><button class="btn" type="button" data-action="close">Cancelar</button><button class="btn ${act === 'tell' ? 'primary' : 'danger'}" type="submit">${label}</button></div>
        </form>`);
      return $('input', d).focus();
    }
    if (act === 'op' && !(await askConfirm(`¿Dar OP a ${player}?`, 'Podrá ejecutar comandos de administrador en el servidor.', { confirmLabel: 'Dar OP', danger: true }))) return;
    runPlayerAction(act, player, '').catch(fail);
  },

  async 'dp-delete'(el) {
    if (!(await askConfirm('¿Borrar este datapack?', `${el.dataset.file} se elimina del mundo. No se puede deshacer.`, { confirmLabel: 'Borrar datapack', danger: true }))) return;
    try { await api(sPath('datapack_delete'), { method: 'POST', body: { file: el.dataset.file } }); toast('Datapack borrado', 'ok'); loadDatapacks(current()); } catch (e) { fail(e); }
  },

  share(el) {
    const d = openDialog(`
      <form class="dlg" id="shareForm" data-file="${esc(el.dataset.file)}"><header><h2>Compartir con enlace temporal</h2></header>
        <p>Se creará un enlace público para <strong>${esc(el.dataset.file)}</strong> con un túnel de Cloudflare. Cualquiera que tenga el enlace podrá descargarlo hasta que caduque o lo detengas.</p>
        <label>Duración<select name="minutes">
          <option value="30">30 minutos</option><option value="60" selected>1 hora</option>
          <option value="180">3 horas</option><option value="720">12 horas</option></select></label>
        <p class="form-error" role="alert"></p>
        <div class="row end"><button class="btn" type="button" data-action="close">Cancelar</button><button class="btn primary" type="submit">Crear enlace</button></div>
      </form>`);
    $('select', d).focus();
  },
  'client-plan'() {
    const p = state.plan, s = current();
    if (!p) return;
    const t = new Date(), ver = `${t.getFullYear()}.${String(t.getMonth() + 1).padStart(2, '0')}.${String(t.getDate()).padStart(2, '0')}`;
    openDialog(`
      <form class="dlg" id="clientBuildForm">
        <header><h2>Generar cliente</h2><button class="btn ghost sm" type="button" data-action="close">Cerrar</button></header>
        <p class="muted small">El cliente usará exactamente la misma versión del servidor: Minecraft ${esc(p.minecraft || '?')} y NeoForge ${esc(p.loader_version || '?')}. Marca los mods que deben ir en él.</p>
        <div class="plan-list">${p.mods.map((m) => `
          <label class="plan-row"><input type="checkbox" name="mod" value="${esc(m.file)}" ${m.include ? 'checked' : ''}${m.locked ? ' disabled' : ''}>
            <span class="grow"><strong>${esc(m.name || m.file)}</strong><span class="muted small block">${esc(m.reason)}</span></span>
            <span class="chip">${m.source ? SRC[m.source] : 'Sin reconocer'}</span></label>`).join('')}</div>
        <fieldset class="fmt"><legend>Formato</legend>
          <label class="check"><input type="radio" name="format" value="mrpack" checked><span><strong>Paquete .mrpack</strong> (recomendado). Pesa poco: Modrinth App, Prism Launcher o ATLauncher instalan NeoForge y descargan los mods solos.</span></label>
          <label class="check"><input type="radio" name="format" value="zip"><span><strong>Zip para CurseForge y Prism Launcher</strong>. Es un modpack con <code>manifest.json</code> y <code>overrides/</code>: se importa tal cual en la app de CurseForge o en Prism Launcher («Añadir instancia → Importar»).</span></label>
          <label class="check sub"><input type="checkbox" name="reference_cf" id="refCf" disabled><span>Referenciar en CurseForge los mods que estén allí. El zip pesa mucho menos (megas en vez de cientos), pero esos mods se descargan desde CurseForge al importar; los demás van dentro. ${p.curseforge ? '' : '<em>No disponible: falta la API key de CurseForge.</em>'}</span></label>
        </fieldset>
        <div class="row"><label>Nombre<input name="pack_name" value="${esc(ascii(s.display_name) || 'Cliente')}" maxlength="48" required></label>
          <label>Versión<input name="version" value="${ver}" maxlength="32" required></label></div>
        ${p.preset && p.preset.items.length ? `
        <fieldset class="preset">
          <label class="check"><input type="checkbox" name="presets" ${p.preset.available ? 'checked' : 'disabled'}>
            <span><strong>Añadir preset de ${esc(p.preset.label)}</strong> <span class="chip">solo cliente</span>
              <span class="muted small block">${esc(p.preset.desc)} El servidor no cambia.</span></span></label>
          <ul class="preset-list">${p.preset.items.map((i) => `<li class="${i.status === 'ok' ? '' : 'off'}">
            <strong>${esc(i.name)}</strong>${i.status === 'ok' ? ` <span class="muted small">${esc(i.version)}</span>` : ` <span class="muted small">${esc(i.note || 'No disponible')}</span>`}</li>`).join('')}</ul>
        </fieldset>` : ''}
        <label class="check"><input type="checkbox" name="include_config"><span>Incluir la carpeta <code>config</code> del servidor. Se omiten los archivos con «token», «secret» o «password» en el nombre, pero revisa que no contengan datos privados.</span></label>
        <p class="form-error" role="alert"></p>
        <div class="row end"><button class="btn" type="button" data-action="close">Cancelar</button><button class="btn primary" type="submit">Generar cliente</button></div>
      </form>`, true);
  },
  async 'share-stop'() { try { await api('/api/share_stop', { method: 'POST', body: {} }); toast('Descarga pública detenida', 'ok'); loadShare(); } catch (e) { fail(e); } },
  async 'copy-url'() {
    const input = $('#shareUrl');
    try { await navigator.clipboard.writeText(input.value); toast('Enlace copiado', 'ok'); } catch { input.select(); toast('Selecciona y copia el enlace manualmente'); }
  },
  async 'rel-delete'(el) {
    if (!(await askConfirm('¿Borrar esta release?', `${el.dataset.file} se elimina del gestor. Si hay un enlace público activo, se cierra antes.`, { confirmLabel: 'Borrar release', danger: true }))) return;
    try { await api(sPath('release_delete'), { method: 'POST', body: { file: el.dataset.file } }); toast('Release borrada', 'ok'); loadReleases(current()); } catch (e) { fail(e); }
  },

  'new-server'() { openNewServer(); },
  'mp-search'(el) { const d = el.closest('dialog'); searchModpacks($('#wizardForm', d), d); },
  'mp-pick'(el) { pickModpack(el, el.closest('dialog')); },
  'user-new'() {
    const d = openDialog(`
      <form class="dlg" id="newUserForm"><header><h2>Nuevo usuario</h2></header>
        <label>Usuario<input name="username" required minlength="3" maxlength="32" pattern="[A-Za-z0-9_.\\-]+" autocomplete="off"></label>
        <label>Contraseña inicial<input name="password" type="password" required minlength="8" autocomplete="new-password"></label>
        <label class="check"><input type="checkbox" name="is_admin"> Administrador</label>
        <p class="muted small">Después podrás asignarle servidores y permisos.</p>
        <p class="form-error" role="alert"></p>
        <div class="row end"><button class="btn" type="button" data-action="close">Cancelar</button><button class="btn primary" type="submit">Crear</button></div>
      </form>`);
    $('input', d).focus();
  },
  'user-edit'(el) { userDialog(state.users.find((u) => u.id === Number(el.dataset.id))); },
  async 'user-select'(el) {
    const id = Number(el.dataset.id);
    if (state.draft && state.draft.id === id) return;
    if (isDirty() && !(await askConfirm('Hay cambios sin guardar', 'Si cambias de usuario ahora, se pierden.', { confirmLabel: 'Descartar cambios', danger: true }))) return;
    mountUserEditor(state.users.find((u) => u.id === id));
  },
  async 'user-close'() {
    if (isDirty() && !(await askConfirm('Hay cambios sin guardar', 'Si cierras ahora, se pierden.', { confirmLabel: 'Descartar cambios', danger: true }))) return;
    actions.close();
  },
  async 'user-save'(el) {
    const d = state.draft, cur = norm(d.cur), base = norm(d.base);
    el.disabled = true; el.textContent = 'Guardando…';
    try {
      if (cur.active !== base.active || cur.is_admin !== base.is_admin) {
        await api(`/api/users/${d.id}/update`, { method: 'POST', body: { active: cur.active, is_admin: cur.is_admin } });
      }
      if (JSON.stringify(cur.permissions) !== JSON.stringify(base.permissions)) {
        await api(`/api/users/${d.id}/permissions`, { method: 'POST', body: { permissions: cur.permissions } });
      }
      const embedded = !!$('#userPane [data-user]');
      state.draft = null;
      actions.close();
      toast('Cambios guardados', 'ok');
      renderUsers(embedded ? d.id : undefined);
    } catch (e) { fail(e); el.disabled = false; el.textContent = 'Guardar cambios'; }
  },
  async 'user-pass'(el) {
    const v = $('#uPass').value;
    try { await api(`/api/users/${el.dataset.id}/update`, { method: 'POST', body: { password: v } }); toast('Contraseña cambiada y sesiones cerradas', 'ok'); $('#uPass').value = ''; } catch (e) { fail(e); }
  },
  async 'user-delete'(el) {
    const u = state.users.find((x) => x.id === Number(el.dataset.id));
    if (!(await askConfirm(`¿Borrar a ${u.username}?`, 'Pierde el acceso al panel y sus permisos. No se puede deshacer.', { confirmLabel: 'Borrar usuario', danger: true }))) return;
    try { await api(`/api/users/${u.id}/delete`, { method: 'POST', body: {} }); actions.close(); toast('Usuario borrado', 'ok'); renderUsers(); } catch (e) { fail(e); }
  },
};

document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-action]');
  if (el && actions[el.dataset.action]) { e.preventDefault(); actions[el.dataset.action](el); }
});

document.addEventListener('submit', async (e) => {
  const f = e.target;
  if (f.matches('.dlg[method=dialog]') ) return;
  e.preventDefault();
  const err = $('.form-error', f);
  const setErr = (m) => { if (err) err.textContent = m || ''; else if (m) toast(m, 'error'); };
  try {
    if (f.id === 'loginForm') return doLogin(f);
    if (f.dataset.finder) return runFinder(f.dataset.finder, f);
    if (f.id === 'texForm') {
      const c = state.tex.current;
      await api(sPath('resourcepack_set'), { method: 'POST', body: { url: c.url, sha1: c.sha1, required: f.required.checked, prompt: f.prompt.value } });
      toast('Opciones guardadas. Se aplican al reiniciar el servidor.', 'ok');
      return loadTex(current());
    }
    if (f.dataset.form === 'say') {
      await runPlayerAction('say', null, f.text.value);
      f.text.value = '';
      return;
    }
    if (f.dataset.form === 'byname') {
      const act = e.submitter && e.submitter.value, name = f.player.value.trim();
      if (act === 'ban' && !(await askConfirm(`¿Banear a ${name}?`, 'No podrá entrar al servidor hasta que lo perdones.', { confirmLabel: 'Banear', danger: true }))) return;
      await runPlayerAction(act, name, '');
      f.player.value = '';
      return;
    }
    if (f.id === 'wizardForm') return createServerFromForm(f);
    if (f.id === 'propsForm') {
      const values = {};
      $$('input[name],select[name]', f).forEach((el) => { values[el.name] = el.type === 'checkbox' ? el.checked : el.value; });
      await api(sPath('properties'), { method: 'POST', body: { values } });
      toast('Propiedades guardadas. Reinicia el servidor para aplicarlas.', 'ok');
      return;
    }
    if (f.id === 'deleteForm') {
      const name = f.dataset.name, typed = f.confirm.value.trim();
      if (typed !== name) { err.textContent = 'El nombre no coincide.'; return; }
      if (!(await askConfirm(`¿Borrar «${name}»?`, 'Se elimina la carpeta, el mundo, los mods y la configuración. No se puede deshacer.', { confirmLabel: 'Borrar servidor', danger: true }))) return;
      await api(sPath('delete'), { method: 'POST', body: { confirm: name } });
      toast(`Servidor «${name}» borrado`, 'ok');
      await refreshServers();
      location.hash = '#/';
      return;
    }
    if (f.id === 'depsForm') {
      const items = $$('input[name=dep]:checked', f).map((i) => ({ url: i.dataset.url, filename: i.dataset.name, sha1: i.dataset.sha1 || null }));
      const btn = $('button[type=submit]', f); btn.disabled = true; btn.textContent = 'Instalando…';
      try {
        const { results } = await api('/api/install_many', { method: 'POST', body: { server: sName(), items } });
        const bad = results.filter((r) => !r.ok), good = results.length - bad.length;
        actions.close();
        if (good) toast(`Instalado${good === 1 ? '' : 's'} ${good} ${good === 1 ? 'mod' : 'mods'}. Reinicia el servidor para cargarlos.`, 'ok');
        bad.forEach((r) => toast(`${r.file}: ${r.error}`, 'error'));
        if (good && state.depsBtn) {
          state.depsBtn.textContent = 'Instalado'; state.depsBtn.disabled = true;
          const card = state.depsBtn.closest('.result');
          if (card) rememberInstalled(state.depsBtn.dataset.source, state.depsBtn.dataset.project, card.dataset.slug, $('.file span', state.depsBtn.closest('.file'))?.textContent);
        }
        refreshServers();
      } catch (er) { btn.disabled = false; btn.textContent = 'Instalar seleccionados'; throw er; }
      return;
    }
    if (f.id === 'clientBuildForm') {
      const files = $$('input[name=mod]:checked', f).map((i) => i.value);
      const btn = $('button[type=submit]', f); btn.disabled = true; btn.textContent = 'Generando…';
      try {
        const r = await api(sPath('client_build'), { method: 'POST', body: {
          files, format: f.format.value, version: f.version.value.trim(), pack_name: f.pack_name.value.trim(), include_config: f.include_config.checked,
          reference_cf: f.reference_cf.checked && !f.reference_cf.disabled, presets: !!(f.presets && f.presets.checked) } });
        actions.close();
        toast(`Cliente generado: ${r.file} (${r.mods} mods${r.referenced ? `, ${r.referenced} referenciados en CurseForge` : ''}${r.embedded.length ? `, ${r.embedded.length} dentro del paquete` : ''})`, 'ok');
        loadReleases(current()); loadClientPlan(current());
      } catch (er) { btn.disabled = false; btn.textContent = 'Generar cliente'; throw er; }
      return;
    }
    if (f.id === 'plForm') {
      await runPlayerAction(f.dataset.act, f.dataset.player, f.text.value);
      actions.close();
      return;
    }
    if (f.id === 'cmdForm') {
      const cmd = f.cmd.value.trim();
      if (!cmd) return;
      await api(sPath('command'), { method: 'POST', body: { cmd } });
      f.cmd.value = '';
      return;
    }
    if (f.id === 'metaForm') {
      await api(sPath('meta'), { method: 'POST', body: { display_name: f.display_name.value, icon: f.icon.value } });
      toast('Identidad guardada', 'ok');
      return refreshServers();
    }
    if (f.id === 'memForm') {
      await api(sPath('memory'), { method: 'POST', body: { xmx: f.xmx.value.trim(), xms: f.xms.value.trim() } });
      toast('Memoria guardada. Se aplica en el próximo arranque.', 'ok');
      return refreshServers();
    }
    if (f.id === 'shareForm') {
      const btn = $('button[type=submit]', f); btn.disabled = true; btn.textContent = 'Creando túnel…';
      try {
        await api(sPath('release_share'), { method: 'POST', body: { file: f.dataset.file, minutes: Number(f.minutes.value) } });
        actions.close(); toast('Enlace creado', 'ok'); loadShare();
      } catch (er) { btn.disabled = false; btn.textContent = 'Crear enlace'; throw er; }
      return;
    }
    if (f.id === 'newUserForm') {
      await api('/api/users', { method: 'POST', body: { username: f.username.value.trim(), password: f.password.value, is_admin: f.is_admin.checked } });
      actions.close(); toast('Usuario creado', 'ok');
      return renderUsers();
    }
    if (f.id === 'pwForm') {
      if (f.new.value !== f.again.value) return setErr('Las contraseñas nuevas no coinciden.');
      await api('/api/me/password', { method: 'POST', body: { old: f.old.value, new: f.new.value } });
      actions.close(); toast('Contraseña actualizada', 'ok');
    }
  } catch (er) {
    if (f.id === 'loginForm') return;
    if (er instanceof ApiError && er.status === 401) return;
    setErr(er.message);
  }
});

document.addEventListener('input', (e) => {
  if (e.target.id === 'logQ') { state.logQ = e.target.value; paintLog(); }
  if (e.target.id === 'modQ') { state.modQ = e.target.value; paintMods(); }
});
// Las casillas del diálogo de usuario solo actualizan un borrador; nada se guarda hasta pulsar «Guardar cambios».
document.addEventListener('change', (e) => {
  const t = e.target, d = state.draft;
  if (!d || !t.closest('dialog, #userPane')) return;
  if (t.dataset.perm) {
    const srv = t.dataset.server;
    d.cur.permissions[srv] = { ...(d.cur.permissions[srv] || {}), [t.dataset.perm]: t.checked };
  } else if (t.dataset.acct) {
    d.cur[t.dataset.acct] = t.checked;
    if (t.dataset.acct === 'is_admin') $$('[data-perm]').forEach((c) => { c.disabled = t.checked; });
  } else return;
  refreshDirty();
});
// En el diálogo de cliente, «referenciar CurseForge» solo tiene sentido con el formato zip y con API key.
document.addEventListener('change', (e) => {
  if (e.target.name !== 'format') return;
  const ref = $('#refCf');
  if (!ref) return;
  const ok = e.target.value === 'zip' && state.plan && state.plan.curseforge;
  ref.disabled = !ok;
  if (!ok) ref.checked = false;
});
// Esc o clic fuera: avisa si hay cambios sin guardar.
document.addEventListener('cancel', (e) => {
  if (!e.target.querySelector('[data-user]') || !isDirty()) return;
  e.preventDefault();
  askConfirm('Hay cambios sin guardar', 'Si cierras ahora, se pierden.', { confirmLabel: 'Descartar cambios', danger: true })
    .then((ok) => { if (ok) { state.draft = null; e.target.close(); } });
}, true);

/* ---------- arranque ---------- */
// --- Plugins: el panel solo sabe cargar scripts y pintar las pestañas que ellos declaran ---
window.ModnexPlugins = window.ModnexPlugins || {};
function renderPluginTab(id, s) {
  const plug = window.ModnexPlugins[id];
  const body = $('#tabBody');
  if (!plug || typeof plug.render !== 'function') { body.innerHTML = '<p class="muted">Esta sección no está disponible.</p>'; return; }
  try { plug.render(body, s); } catch (e) { body.innerHTML = `<p class="muted">No se pudo mostrar esta sección: ${esc(e.message)}</p>`; }
}
async function loadPlugins() {
  state.plugins = { tabs: [], scripts: [] };
  try { state.plugins = await api('/api/plugins'); } catch { return; }
  window.Modnex = { api, esc, $, toast, askConfirm, isAdmin, current, state };
  await Promise.all((state.plugins.scripts || []).map((src) => new Promise((ok) => {
    const el = document.createElement('script');
    el.src = src; el.onload = ok; el.onerror = ok;
    document.head.appendChild(el);
  })));
}

async function boot() {
  try {
    const me = await api('/api/me');
    state.me = me.user; state.icons = me.icons;
    state.servers = await api('/api/servers');
    await loadPlugins();
  } catch (e) { return; }
  renderShell();
  route();
  const reconnect = setInterval(() => { if (state.me && !document.hidden) refreshServers(); }, 5000);
  boot.reconnect && clearInterval(boot.reconnect);
  boot.reconnect = reconnect;
}

window.addEventListener('hashchange', () => { if (state.me) route(); });
boot().then(() => { if (!state.me) renderLogin(); });
