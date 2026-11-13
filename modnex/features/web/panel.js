// Modnex Pro: pestañas Copias, Diagnóstico y Avisos. Usa el API mínimo que el panel expone en window.Modnex.
(function () {
  const link = document.createElement('link');
  link.rel = 'stylesheet'; link.href = '/plugin/panel.css';
  document.head.appendChild(link);

  const M = () => window.Modnex;
  const fmtSize = (n) => n >= 2 ** 30 ? (n / 2 ** 30).toFixed(1) + ' GB' : n >= 2 ** 20 ? Math.round(n / 2 ** 20) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';
  const fmtDate = (ts) => new Date(ts * 1000).toLocaleString('es');
  const KIND = { manual: 'Manual', auto: 'Programada', 'pre-restore': 'Antes de restaurar', 'pre-update': 'Antes de actualizar' };
  const DAYS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];
  const url = (s, a, q = '') => `/api/servers/${encodeURIComponent(s.name)}/${a}${q}`;
  let pollTimer = null;

  // Árbol de versiones: cada copia es un punto y las líneas unen cada una con la copia de la que partía (como `git log --graph`).
  const VT = { row: 64, col: 20, pad: 14, r: 6 };
  function treeHTML(g, d) {
    const { esc } = M();
    const x = (lane) => VT.pad + lane * VT.col, y = (row) => row * VT.row + VT.row / 2;
    const gw = VT.pad * 2 + (g.lanes - 1) * VT.col;
    const edges = g.nodes.filter((n) => n.edge).map((n) => {
      const x1 = x(n.lane), y1 = y(n.row), x2 = x(n.edge.lane), y2 = y(n.edge.to);
      const dpath = x1 === x2 ? `M${x1} ${y1}V${y2}` : `M${x1} ${y1}V${y2 - 26}C${x1} ${y2 - 12} ${x2} ${y2 - 16} ${x2} ${y2}`;
      return `<path class="vt-edge vl${n.lane % 6}" d="${dpath}"/>`;
    }).join('');
    const dots = g.nodes.map((n) => `<circle class="vt-dot vl${n.lane % 6}${n.head ? ' head' : ''}${n.deleted ? ' gone' : ''}" cx="${x(n.lane)}" cy="${y(n.row)}" r="${n.head ? VT.r + 1 : VT.r}"/>`).join('');
    const rows = g.nodes.map((b) => {
      const kids = g.nodes.filter((n) => n.parent === b.id).length;
      const info = [fmtDate(b.created), b.deleted ? 'archivo borrado' : fmtSize(b.size), `${(b.mods || []).length} mods`, b.minecraft, b.loader].filter(Boolean).join(' · ');
      const title = b.label || KIND[b.kind] || b.kind;
      const actions = b.deleted
        ? `<button class="btn sm" data-act="diff" data-id="${esc(b.id)}">Ver cambios</button>
          <button class="btn sm" data-act="forget" data-id="${esc(b.id)}" title="Quita este punto del historial. Solo se pierde el rastro de dónde partía.">Quitar del historial</button>`
        : `<button class="btn sm" data-act="diff" data-id="${esc(b.id)}">Ver cambios</button>
          <button class="btn sm" data-act="pin" data-id="${esc(b.id)}" data-on="${b.pinned ? 0 : 1}" title="${b.pinned ? 'Vuelve a quedar sujeta a las reglas de retención' : 'Ninguna regla la borrará'}">${b.pinned ? 'Soltar' : 'Fijar'}</button>
          <button class="btn sm" data-act="restore" data-id="${esc(b.id)}" ${d.running ? 'disabled title="Para el servidor antes de restaurar"' : ''}>Restaurar</button>
          <button class="btn sm danger" data-act="delete" data-id="${esc(b.id)}">Borrar</button>`;
      return `<div class="vt-row${b.head ? ' is-head' : ''}${b.deleted ? ' is-gone' : ''}">
        <div class="vt-main">
          <div class="vt-title"><strong>${esc(title)}</strong>
            ${b.label && b.label !== (KIND[b.kind] || b.kind) ? `<span class="chip">${esc(KIND[b.kind] || b.kind)}</span>` : ''}${b.deleted ? ' <span class="chip">Borrada</span>' : ''}${b.pinned ? ' <span class="chip live">Fijada</span>' : ''}${b.head ? ' <span class="chip ok">Estás aquí</span>' : ''}${kids > 1 ? ` <span class="chip">${kids} ramas parten de aquí</span>` : ''}</div>
          <div class="vt-info muted small">${esc(info)}</div>
        </div>
        <div class="ft-actions">${actions}</div></div>`;
    }).join('');
    return `<div class="vt" data-gw="${gw}">
      <svg class="vt-graph" width="${gw}" height="${g.nodes.length * VT.row}" aria-hidden="true">${edges}${dots}</svg>
      <div class="vt-rows">${rows}</div></div>
      <p class="muted small">Cada punto es una copia y la línea lo une con la copia de la que partía. Si restauras una copia antigua y sigues copiando, el historial se bifurca en una rama nueva. Las copias que borras (a mano o por las reglas de retención) siguen en el árbol, atenuadas, para que no se pierda el historial; solo se quita su archivo. Arriba, lo más reciente.</p>`;
  }

  // ---------- Copias ----------
  function copias(el, s) {
    const { api, esc, toast, askConfirm } = M();
    clearTimeout(pollTimer);

    async function load() {
      let d;
      try { d = await api(url(s, 'backups')); } catch (e) { el.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
      draw(d);
      if (d.job && d.job.state === 'running') pollTimer = setTimeout(() => { if (el.isConnected) load(); }, 2000);
    }

    const RET = [
      ['pre_keep', 'Seguridad previa: conservar las últimas', 'copias; 0 = sin límite'],
      ['pre_days', '…y borrar las de más de', 'días; 0 = sin límite'],
      ['manual_days', 'Manuales: borrar las de más de', 'días; 0 = nunca'],
      ['max_gb', 'Espacio máximo de las copias', 'GB; 0 = sin límite'],
      ['min_free_gb', 'Disco libre mínimo', 'GB; 0 = sin mínimo'],
      ['auto_keep', 'Automáticas sin tarea: conservar', 'copias'],
    ];
    const planHTML = (p) => p.delete.length
      ? `<div class="ft-card warn"><h3>Se borrarían ${p.delete.length} ${p.delete.length === 1 ? 'copia' : 'copias'} y se liberarían ${esc(fmtSize(p.freed))}</h3>
          <ul class="ft-checks">${p.delete.map((x) => `<li>${esc(fmtDate(x.created))} · ${esc(x.label || KIND[x.kind] || x.kind)} · ${esc(fmtSize(x.size))}<span class="muted small block">${esc(x.reason)}</span></li>`).join('')}</ul>
          ${p.unmet.length ? `<p class="muted small">${esc(p.unmet.join('. '))}</p>` : ''}</div>`
      : `<div class="ft-card info"><h3>No se borraría nada</h3><p class="muted small">Con estas reglas se conservan las ${p.kept} copias.${p.unmet.length ? ' ' + esc(p.unmet.join('. ')) : ''}</p></div>`;
    function retentionHTML(r) {
      return `<div class="ft-section">
        <div class="ft-head"><h2>Ciclo de vida de las copias</h2></div>
        <p class="muted small">Reglas para borrar copias viejas solas, después de cada copia y una vez al día. <strong>La copia más reciente y las fijadas nunca se borran</strong>, así que siempre queda al menos una.</p>
        <form class="ft-form" data-form="retention">
          ${RET.map(([k, label, unit]) => `<label>${label}<input name="${k}" type="number" min="${k === 'auto_keep' ? 1 : 0}" value="${esc(r.policy[k])}" required><span class="muted small">${unit}</span></label>`).join('')}
          <button class="btn" type="button" data-act="ret-preview">Ver qué se borraría</button>
          <button class="btn primary" type="submit">Guardar reglas</button>
          <button class="btn danger" type="button" data-act="ret-apply">Aplicar ahora</button>
        </form>
        <div id="ftRet">${planHTML(r.plan)}</div>
      </div>`;
    }
    const retValues = (f) => Object.fromEntries(RET.map(([k]) => [k, Number(f[k].value)]));

    function draw(d) {
      const busy = d.job && d.job.state === 'running';
      const err = d.job && d.job.state === 'error' ? `<p class="ft-note">La última copia falló: ${esc(d.job.msg)}</p>` : '';
      const sched = d.schedules.map((t) => `<tr>
        <td>${t.kind === 'backup' ? 'Copia de seguridad' : 'Reinicio'}</td><td>${esc(t.hhmm)}</td>
        <td>${t.days === '*' ? 'Todos los días' : esc(t.days.split(',').map((x) => DAYS[+x]).join(', '))}</td>
        <td>${t.kind === 'backup' ? esc(t.keep) + ' copias' : '—'}</td>
        <td><div class="ft-actions">
          <button class="btn sm" data-act="toggle" data-id="${esc(t.id)}" data-on="${t.enabled ? 0 : 1}">${t.enabled ? 'Pausar' : 'Activar'}</button>
          <button class="btn sm danger" data-act="unsched" data-id="${esc(t.id)}">Quitar</button></div></td></tr>`).join('');
      el.innerHTML = `
        <div class="ft-head"><h2>Copias de seguridad</h2><span class="muted small">Espacio libre: ${esc(fmtSize(d.free))}</span></div>
        ${d.running ? '<p class="ft-note">El servidor está en marcha: la copia se hace en caliente (se guarda el mundo antes). Para restaurar hay que pararlo.</p>' : ''}
        ${err}
        <form class="ft-form" data-form="create">
          <label>Etiqueta (opcional)<input name="label" maxlength="80" placeholder="Antes de actualizar mods"></label>
          <button class="btn primary" type="submit" ${busy ? 'disabled' : ''}>${busy ? 'Copiando…' : 'Crear copia'}</button>
        </form>
        ${d.graph.nodes.length ? treeHTML(d.graph, d) : M().emptyState('box', 'Todavía no hay copias.', 'Crea la primera con el botón de arriba.')}
        <div class="ft-diff" id="ftDiff"></div>
        ${retentionHTML(d.retention)}
        <div class="ft-section">
          <div class="ft-head"><h2>Tareas programadas</h2></div>
          ${sched ? `<table class="ft-table"><thead><tr><th>Tarea</th><th>Hora</th><th>Días</th><th>Conservar</th><th></th></tr></thead><tbody>${sched}</tbody></table>` : '<p class="muted">Sin tareas programadas.</p>'}
          <form class="ft-form ft-mt" data-form="sched">
            <label>Tarea<select name="kind"><option value="backup">Copia de seguridad</option><option value="restart">Reinicio (avisa 5 y 1 min antes)</option></select></label>
            <label>Hora<input name="hhmm" type="time" value="04:00" required></label>
            <label>Conservar<input name="keep" type="number" min="1" max="90" value="7"></label>
            <label>Días<span class="ft-days">${DAYS.map((n, i) => `<label><input type="checkbox" name="d" value="${i}" checked> ${n}</label>`).join('')}</span></label>
            <button class="btn" type="submit">Añadir tarea</button>
          </form>
        </div>`;
      const vt = el.querySelector('.vt');
      if (vt) vt.style.setProperty('--gw', vt.dataset.gw + 'px');
    }

    el.onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target, kind = f.getAttribute('data-form');
      try {
        if (kind === 'create') {
          await api(url(s, 'backup_create'), { method: 'POST', body: { label: f.label.value } });
          toast('Copia iniciada', 'ok');
        } else if (kind === 'retention') {
          const r = await api(url(s, 'retention_set'), { method: 'POST', body: retValues(f) });
          toast('Reglas guardadas', 'ok'); M().$('#ftRet').innerHTML = planHTML(r.plan); return;
        } else if (kind === 'sched') {
          const days = [...f.querySelectorAll('input[name=d]:checked')].map((x) => x.value);
          if (!days.length) { toast('Elige al menos un día', 'error'); return; }
          await api(url(s, 'schedule_add'), { method: 'POST', body: { kind: f.kind.value, hhmm: f.hhmm.value, days: days.length === 7 ? '*' : days.join(','), keep: Number(f.keep.value) } });
          toast('Tarea añadida', 'ok');
        }
        load();
      } catch (err) { toast(err.message, 'error'); }
    };

    el.onclick = async (e) => {
      const b = e.target.closest('[data-act]');
      if (!b) return;
      const id = b.getAttribute('data-id'), act = b.getAttribute('data-act');
      try {
        if (act === 'restore') {
          if (!(await askConfirm('¿Restaurar esta copia?', 'El servidor vuelve al estado de esa copia (mundo, mods y configuración). Antes se guarda una copia automática, así que se puede deshacer.', { confirmLabel: 'Restaurar', danger: true }))) return;
          await api(url(s, 'backup_restore'), { method: 'POST', body: { id, confirm: s.name } });
          toast('Copia restaurada', 'ok'); load();
        } else if (act === 'delete') {
          if (!(await askConfirm('¿Borrar esta copia?', 'Se elimina del disco. No se puede deshacer.', { confirmLabel: 'Borrar copia', danger: true }))) return;
          await api(url(s, 'backup_delete'), { method: 'POST', body: { id } }); load();
        } else if (act === 'diff') {
          const d = await api(url(s, 'backup_diff', `?a=${encodeURIComponent(id)}&b=current`));
          const list = (t, a) => a.length ? `<p><strong>${t}</strong></p><ul>${a.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : '';
          const v = Object.entries(d.versions).map(([k, [a, b2]]) => `<li>${esc(k)}: ${esc(a)} → ${esc(b2)}</li>`).join('');
          M().$('#ftDiff').innerHTML = `<div class="ft-card info"><h3>Cambios desde esa copia hasta ahora</h3>${
            list('Mods añadidos', d.added) + list('Mods quitados', d.removed) + list('Mods con otra versión', d.changed) + (v ? `<p><strong>Versiones</strong></p><ul>${v}</ul>` : '')
            || '<p class="muted">Sin diferencias en mods ni versiones.</p>'}</div>`;
        } else if (act === 'forget') {
          if (!(await askConfirm('¿Quitar del historial?', 'La copia ya estaba borrada. Solo se pierde el rastro de dónde partía en el árbol.', { confirmLabel: 'Quitar', danger: true }))) return;
          await api(url(s, 'backup_forget'), { method: 'POST', body: { id } }); load();
        } else if (act === 'pin') {
          await api(url(s, 'backup_pin'), { method: 'POST', body: { id, pinned: b.getAttribute('data-on') === '1' } }); load();
        } else if (act === 'ret-preview') {
          const p = await api(url(s, 'retention_preview'), { method: 'POST', body: retValues(b.closest('form')) });
          M().$('#ftRet').innerHTML = planHTML(p);
        } else if (act === 'ret-apply') {
          const p = await api(url(s, 'retention_preview'), { method: 'POST', body: retValues(b.closest('form')) });
          if (!p.delete.length) { M().$('#ftRet').innerHTML = planHTML(p); toast('No hay nada que borrar', 'ok'); return; }
          if (!(await askConfirm(`¿Borrar ${p.delete.length} ${p.delete.length === 1 ? 'copia' : 'copias'} ahora?`, `Se liberan ${fmtSize(p.freed)}. No se puede deshacer. Se aplican las reglas guardadas; si has cambiado algo, guárdalo antes.`, { confirmLabel: 'Borrar', danger: true }))) return;
          const r = await api(url(s, 'retention_apply'), { method: 'POST', body: {} });
          toast(`${r.deleted.length} copias borradas`, 'ok'); load();
        } else if (act === 'toggle') {
          await api(url(s, 'schedule_toggle'), { method: 'POST', body: { id, enabled: b.getAttribute('data-on') === '1' } }); load();
        } else if (act === 'unsched') {
          await api(url(s, 'schedule_remove'), { method: 'POST', body: { id } }); load();
        }
      } catch (err) { toast(err.message, 'error'); }
    };
    load();
  }

  // ---------- Diagnóstico ----------
  function diagnostico(el, s) {
    const { api, esc, toast } = M();
    async function run() {
      el.innerHTML = '<p class="muted">Analizando los logs…</p>';
      let d;
      try { d = await api(url(s, 'doctor')); } catch (e) { el.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
      el.innerHTML = `
        <div class="ft-head"><h2>Diagnóstico</h2><button class="btn" data-act="again">Analizar de nuevo</button></div>
        <p class="muted small">Se leen el último arranque y el reporte de crash más reciente${d.crash_report ? ` (${esc(d.crash_report)})` : ''}.</p>
        ${d.findings.length ? d.findings.map((f) => `<div class="ft-card ${esc(f.severity)}">
            <h3>${esc(f.title)}</h3><p>${esc(f.detail)}</p>${f.fix ? `<p><strong>Qué hacer:</strong> ${esc(f.fix)}</p>` : ''}</div>`).join('')
          : '<p class="muted">No hay nada que analizar todavía: el servidor aún no ha arrancado.</p>'}`;
    }
    el.onclick = (e) => { if (e.target.closest('[data-act=again]')) run().catch((x) => toast(x.message, 'error')); };
    run();
  }

  // ---------- Avisos ----------
  function avisos(el, s) {
    const { api, esc, toast } = M();
    const EV = [['started', 'Arranque'], ['stopped', 'Parada'], ['crashed', 'Caída'], ['backup', 'Copias'], ['players', 'Entradas y salidas'], ['proposals', 'Propuestas de mods']];
    async function load() {
      let d;
      try { d = await api(url(s, 'notify')); } catch (e) { el.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
      el.innerHTML = `
        <div class="ft-head"><h2>Avisos a Discord</h2></div>
        <p class="muted small">Pega la URL de un webhook de tu canal. Se envía un mensaje cuando ocurre algo en este servidor. No se mencionará a nadie.</p>
        <p class="ft-note">${d.configured ? `Webhook configurado: <code>${esc(d.webhook)}</code>` : 'Todavía no hay webhook configurado.'}</p>
        <form class="ft-form" data-form="notify">
          <label class="ft-grow">Webhook de Discord<input name="webhook" type="password" autocomplete="off" placeholder="https://discord.com/api/webhooks/…" ${d.configured ? '' : 'required'}></label>
          <label>Avisar de<span class="ft-days">${EV.map(([k, n]) => `<label><input type="checkbox" name="e" value="${k}" ${d.events.includes(k) ? 'checked' : ''}> ${n}</label>`).join('')}</span></label>
          <button class="btn primary" type="submit">Guardar</button>
          ${d.configured ? '<button class="btn" type="button" data-act="test">Enviar prueba</button><button class="btn danger" type="button" data-act="remove">Quitar</button>' : ''}
        </form>`;
    }
    el.onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target;
      try {
        const webhook = f.webhook.value.trim();
        if (!webhook) { toast('Pega la URL del webhook para guardar los cambios', 'error'); return; }
        await api(url(s, 'notify_set'), { method: 'POST', body: { webhook, events: [...f.querySelectorAll('input[name=e]:checked')].map((x) => x.value) } });
        toast('Avisos guardados', 'ok'); load();
      } catch (err) { toast(err.message, 'error'); }
    };
    el.onclick = async (e) => {
      const b = e.target.closest('[data-act]');
      if (!b) return;
      try {
        if (b.getAttribute('data-act') === 'test') { await api(url(s, 'notify_test'), { method: 'POST', body: {} }); toast('Prueba enviada', 'ok'); }
        if (b.getAttribute('data-act') === 'remove') { await api(url(s, 'notify_remove'), { method: 'POST', body: {} }); toast('Avisos quitados', 'ok'); load(); }
      } catch (err) { toast(err.message, 'error'); }
    };
    load();
  }


  // ---------- Estadísticas de jugadores ----------
  function estadisticas(el, s) {
    const { api, esc } = M();
    const dur = (n) => { const h = Math.floor(n / 3600), m = Math.floor((n % 3600) / 60); return h ? `${h} h ${String(m).padStart(2, '0')} min` : `${m} min`; };
    const ago = (iso) => { if (!iso) return '—'; const d = (Date.now() - new Date(iso).getTime()) / 1000; return d < 90 ? 'ahora' : d < 3600 ? `hace ${Math.round(d / 60)} min` : d < 86400 ? `hace ${Math.round(d / 3600)} h` : new Date(iso).toLocaleDateString('es'); };
    function bars(values, labels, title) {
      const max = Math.max(1, ...values), W = 480, H = 110, bw = W / values.length;
      return `<svg class="ft-chart" viewBox="0 0 ${W} ${H + 18}" role="img" aria-label="${esc(title)}">${values.map((v, i) => {
        const h = Math.round((v / max) * H);
        return `<rect x="${(i * bw + 1).toFixed(1)}" y="${H - h}" width="${(bw - 2).toFixed(1)}" height="${Math.max(h, v ? 2 : 0)}" rx="2" class="ft-bar"><title>${esc(labels[i])}: ${esc(dur(v))}</title></rect>`;
      }).join('')}${[0, 6, 12, 18, 23].map((h) => `<text x="${(h * bw + bw / 2).toFixed(1)}" y="${H + 13}" text-anchor="middle" class="ft-axis">${String(h).padStart(2, '0')}h</text>`).join('')}</svg>`;
    }
    async function load() {
      let d;
      try { d = await api(url(s, 'player_stats')); } catch (e) { el.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
      const rows = d.players.map((p) => `<tr><td>${esc(p.name)} ${p.online ? '<span class="chip">conectado</span>' : ''}</td>
        <td>${esc(dur(p.seconds))}</td><td>${esc(p.sessions)}</td><td>${esc(dur(p.longest))}</td><td>${esc(ago(p.last_seen))}</td></tr>`).join('');
      el.innerHTML = `
        <div class="ft-head"><h2>Estadísticas de jugadores</h2><button class="btn" data-act="reload">Actualizar</button></div>
        <p class="muted small">Se calculan a partir de los logs del servidor. ${d.online.length ? `Conectados ahora: ${esc(d.online.join(', '))}.` : ''}</p>
        ${d.players.length ? `<table class="ft-table"><thead><tr><th>Jugador</th><th>Tiempo jugado</th><th>Sesiones</th><th>Sesión más larga</th><th>Visto</th></tr></thead><tbody>${rows}</tbody></table>
          <div class="ft-section"><div class="ft-head"><h2>Actividad por hora del día</h2></div>${bars(d.hours, d.hours.map((_, i) => `${String(i).padStart(2, '0')}:00`), 'Tiempo jugado por hora del día')}</div>
          ${d.days.length > 1 ? `<div class="ft-section"><div class="ft-head"><h2>Últimos días</h2></div>${bars(d.days.map((x) => x.seconds), d.days.map((x) => x.date), 'Tiempo jugado por día')}</div>` : ''}`
          : M().emptyState('list', 'Todavía no hay entradas de jugadores en los logs.')}`;
    }
    el.onclick = (e) => { if (e.target.closest('[data-act=reload]')) load(); };
    load();
  }


  // ---------- Rendimiento (spark) ----------
  function rendimiento(el, s) {
    const { api, esc, toast } = M();
    let out = null, busy = '';
    async function load() {
      let d;
      try { d = await api(url(s, 'performance')); } catch (e) { el.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
      draw(d);
    }
    function draw(d) {
      const can = d.installed && d.running && d.control;
      const why = !d.installed ? 'spark no está instalado en este servidor.'
        : !d.running ? 'El servidor está apagado.'
        : !d.control ? 'El servidor no lo arrancó este gestor, así que no puede enviarle comandos. Reinícialo desde el panel para poder usar estos botones; mientras tanto puedes escribir /spark en la consola del juego.' : '';
      const btn = (act, label, primary) => `<button class="btn${primary ? ' primary' : ''}" data-act="${act}" ${can && !busy ? '' : 'disabled'}>${busy === act ? 'Esperando…' : label}</button>`;
      const lag = d.lag_count
        ? `<p><strong>${esc(d.lag_count)}</strong> avisos de «Can't keep up» en el log actual.</p><ul class="small">${d.lag_last.map((x) => `<li>${esc(x.time)} · ${esc(x.ticks)} ticks (${esc(x.ms)} ms) de retraso</li>`).join('')}</ul>`
        : '<p class="muted">Sin avisos de lag en el log actual.</p>';
      const res = out ? `<div class="ft-section"><div class="ft-head"><h2>Resultado</h2></div>
        <pre class="ft-pre">${esc(out.lines.join('\n') || 'spark no respondió a tiempo. Mira la consola.')}</pre>
        ${out.url ? `<p><a class="btn primary" href="${esc(out.url)}" target="_blank" rel="noopener noreferrer">Abrir informe</a></p>` : ''}</div>` : '';
      el.innerHTML = `
        <div class="ft-head"><h2>Rendimiento</h2><button class="btn" data-act="reload">Actualizar</button></div>
        <p class="muted small">${d.installed ? esc(d.jar) : 'spark no instalado'}${d.background === true ? ' · perfilador en segundo plano activo' : d.background === false ? ' · perfilador en segundo plano apagado' : ''}</p>
        <div class="ft-actions">${btn('tps', 'Ver TPS', true)}${btn('health', 'Estado general')}${btn('profiler_start', 'Iniciar perfil')}${btn('profiler_stop', 'Terminar y ver informe')}</div>
        ${why ? `<p class="muted small">${esc(why)}</p>` : ''}
        ${res}
        <div class="ft-section"><div class="ft-head"><h2>Lag registrado</h2></div>${lag}</div>`;
    }
    el.onclick = async (e) => {
      const b = e.target.closest('[data-act]');
      if (!b || b.disabled) return;
      const act = b.getAttribute('data-act');
      if (act === 'reload') return load();
      busy = act; load();
      try { out = await api(url(s, 'performance_run'), { method: 'POST', body: { action: act } }); }
      catch (err) { toast(err.message, 'error'); }
      busy = ''; load();
    };
    load();
  }


  // ---------- KubeJS: sección con recetas visuales, scripts y diagnóstico ----------
  const KJS_MAP = [
    ['Al abrir el juego (startup_scripts)', [
      ['Ítems personalizados: comida, herramientas, armaduras, escudos', 'code'],
      ['Bloques personalizados: modelos, luz, resistencia, sonidos', 'code'],
      ['Fluidos y gases', 'code'],
      ['Efectos de poción y encantamientos', 'code'],
      ['Pestañas creativas', 'code'],
      ['Propiedades de ítems existentes (pila, rareza, durabilidad, combustible)', 'visual'],
    ]],
    ['En el servidor (server_scripts)', [
      ['Recetas de mesa, horno, horno alto, ahumador, fogata y cortapiedras (añadir)', 'visual'],
      ['Eliminar recetas de fábrica y de mods', 'visual'],
      ['Recetas de Create: prensa, muela, mezcladora, desplegador, fabricador, ensamblaje y más (requiere Create)', 'visual'],
      ['Reemplazar ingredientes y resultados, y recetas de mesa de herrería', 'visual'],
      ['Tablas de botín de bloques y mobs', 'visual'],
      ['Tablas de botín de cofres y de otros tipos', 'todo'],
      ['Tags de ítems, bloques, fluidos y entidades', 'visual'],
      ['Comercios de aldeanos (requiere MoreJS)', 'visual'],
      ['Eventos: entrar, romper, colocar, usar item (mensaje, regalo, comando, cancelar)', 'visual'],
      ['Comandos personalizados', 'visual'],
      ['Datos persistentes (NBT / PersistentData)', 'code'],
      ['Lectura y escritura de archivos (JsonIO)', 'code'],
    ]],
    ['En el cliente del jugador (client_scripts)', [
      ['Tooltips de texto fijo', 'visual'],
      ['JEI / EMI / REI: ocultar ítems', 'visual'],
      ['HUD y dibujo en pantalla (Painter)', 'code'],
      ['Sonidos y partículas', 'code'],
    ]],
    ['Herramientas avanzadas', [
      ['Java.loadClass (clases de Java directas)', 'code'],
      ['Networking cliente ↔ servidor', 'code'],
      ['Depuración: /kubejs hand, /kubejs inventory', 'game'],
    ]],
  ];
  const KJS_STATE = { visual: ['Visual', 'ok'], code: ['Código en Scripts', ''], todo: ['Editor visual pendiente', 'warn'], game: ['Comando del juego', ''] };
  const KJS_FOLDERS = {
    startup_scripts: 'Se ejecuta una vez al abrir el juego: hace falta reiniciar el servidor para aplicarlo.',
    server_scripts: 'Se recarga con /reload en la consola, sin reiniciar.',
    client_scripts: 'Corre en el cliente de cada jugador: se aplica cuando el jugador recarga o reinicia su juego.',
  };

  function kubejsSection(el, s) {
    const VIEWS = [['recetas', 'Recetas'], ...((s.addons || []).includes('create') ? [['create', 'Create']] : []), ['quitar', 'Quitar recetas'], ['reglas', 'Reglas'], ['botin', 'Botín'], ['scripts', 'Scripts'], ['diag', 'Diagnóstico']];
    let view = 'recetas';
    el.innerHTML = `<nav class="kjs-nav" role="tablist" aria-label="KubeJS">${VIEWS.map(([k, l]) =>
      `<button role="tab" data-view="${k}" aria-selected="${k === view}" class="${k === view ? 'on' : ''}">${l}</button>`).join('')}</nav>
      <div class="kjs-testbar"><button class="btn sm" data-act="kjs-test">Probar en el servidor</button>
        <span class="muted small">Envía <code>/reload</code> al servidor en marcha y comprueba si los scripts cargan sin errores.</span></div>
      <div class="kjs-test-out" aria-live="polite"></div><div class="kjs-sub"></div>`;
    const sub = el.querySelector('.kjs-sub');
    if (window.ModnexKjsBlock) window.ModnexKjsBlock.watch(sub, `/api/servers/${encodeURIComponent(s.name)}`);   // los items que son bloques se ven con su modelo
    function show() {
      el.querySelectorAll('.kjs-nav button').forEach((b) => { const on = b.getAttribute('data-view') === view; b.classList.toggle('on', on); b.setAttribute('aria-selected', on); });
      sub.onclick = sub.oninput = sub.onkeydown = null;
      sub.innerHTML = '';
      ({ recetas, quitar: kjsQuitar, create: (e, sv) => (window.ModnexKjsCreate ? window.ModnexKjsCreate.view(e, sv) : (e.innerHTML = '<p class="muted">Recarga la página para cargar Create.</p>')), botin: (e, sv) => (window.ModnexKjsLoot ? window.ModnexKjsLoot.view(e, sv) : (e.innerHTML = '<p class="muted">Recarga la página para cargar el botín.</p>')), reglas: (e, sv) => (window.ModnexKjsRules ? window.ModnexKjsRules(e, sv) : (e.innerHTML = '<p class="muted">Recarga la página para cargar las reglas.</p>')), scripts: kjsScripts, diag: kjsDiag })[view](sub, s);
    }
    el.querySelector('.kjs-testbar').onclick = async (e) => {
      const b = e.target.closest('[data-act=kjs-test]'); if (!b || b.disabled) return;
      const { api, esc, toast } = M(), out = el.querySelector('.kjs-test-out');
      if (!window.confirm('Esto ejecuta /reload en el servidor en marcha. Si hay jugadores conectados notarán un pequeño tirón. ¿Continuar?')) return;
      b.disabled = true; b.textContent = 'Recargando…'; out.innerHTML = '<p class="muted small">Esperando a que el servidor termine de recargar…</p>';
      try {
        const r = await api(`/api/servers/${encodeURIComponent(s.name)}/kubejs_test`, { method: 'POST', body: {} });
        const rc = r.recipes;
        const head = !r.finished ? ['warn', 'No se vio el final del reload'] : r.ok ? ['ok', `Recargado sin errores en ${r.seconds} s`] : ['bad', (() => { const n = r.problems.filter((p) => p.level === 'error').length || r.kubejs_errors || 0; return n ? `Recargado con ${n} ${n === 1 ? 'error' : 'errores'}` : 'Recargado con errores'; })()];
        out.innerHTML = `<div class="kjs-result ${head[0]}"><strong>${head[1]}</strong>
          ${rc ? `<p class="small">KubeJS: ${rc.added} recetas añadidas, ${rc.modified} modificadas, ${rc.removed} quitadas, ${rc.failed} fallidas.</p>` : ''}
          ${r.summary.length ? `<ul class="kjs-lines">${r.summary.map((l) => `<li>${esc(l)}</li>`).join('')}</ul>` : ''}
          ${r.problems.length ? `<ul class="kjs-lines">${r.problems.map((p) => `<li class="${p.level}"><span class="chip ${p.level === 'error' ? 'bad' : 'warn'}">${p.level === 'error' ? 'Error' : 'Aviso'}</span> <code>${esc(p.text)}</code></li>`).join('')}</ul>` : ''}
          ${r.notes.length ? `<ul class="kjs-notes">${r.notes.map((n) => `<li class="muted small">${esc(n)}</li>`).join('')}</ul>` : ''}</div>`;
      } catch (err) { out.innerHTML = `<div class="kjs-result bad"><strong>No se pudo probar</strong><p class="small">${esc(err.message)}</p></div>`; toast(err.message, 'error'); }
      b.disabled = false; b.textContent = 'Probar en el servidor';
    };
    el.querySelector('.kjs-nav').onclick = (e) => { const b = e.target.closest('[data-view]'); if (b) { view = b.getAttribute('data-view'); show(); } };
    show();
  }

  const RECIPE_TYPE = {
    'minecraft:crafting_shaped': 'Mesa · con forma', 'minecraft:crafting_shapeless': 'Mesa · sin forma',
    'minecraft:crafting_transmute': 'Mesa · transformar', 'minecraft:smelting': 'Horno', 'minecraft:blasting': 'Horno alto',
    'minecraft:smoking': 'Ahumador', 'minecraft:campfire_cooking': 'Fogata', 'minecraft:stonecutting': 'Cortapiedras',
    'minecraft:smithing_transform': 'Mesa de herrería', 'minecraft:smithing_trim': 'Mesa de herrería (diseño)',
  };

  function kjsQuitar(el, s) {
    const { api, esc, toast } = M();
    const base = `/api/servers/${encodeURIComponent(s.name)}`;
    let removals = [], items = [], q = '', timer = null, sel = null, found = null, dirty = false, status = '', createData = null;
    const names = {};
    const ico = (id, icon, cls = 'kjs-ico') => icon
      ? `<img class="${cls}" data-iid="${esc(id)}" src="${esc(icon)}" alt="" loading="lazy">`
      : `<span class="${cls} kjs-ph" aria-hidden="true">${(id || '').startsWith('#') ? '#' : esc((id || '?').split(':').pop().charAt(0).toUpperCase())}</span>`;
    const nameOf = (id) => names[id] || id;
    // La receta en la interfaz del juego, solo para mirar. Si no se sabe dibujar (otro mod, formato raro) se usa la lista de ingredientes.
    const recipeGui = (r) => {
      const G = window.ModnexKjsGui, L = r.layout;
      if (L && L.skin === 'create' && createData) {
        const icon = (e) => (e.icon ? `<img class="kjs-ico" data-iid="${esc(e.id)}" src="${esc(e.icon)}" alt="">` : `<span class="kjs-ph kjs-ico" aria-hidden="true">${esc((e.id || '?').charAt(0).toUpperCase())}</span>`);
        return `<div class="kjs-recipe-gui">${window.ModnexKjsCreate.scene(createData, L, { ro: true, small: true, icon, name: (e) => e.name })}</div>`;
      }
      if (!G || !r.layout || !G.has(r.layout.skin)) return '';
      return `<div class="kjs-recipe-gui">${G.html(L.skin, (key) => {
        const sl = L.slots[key];
        if (!sl) return {};
        return { inner: ico(sl.id, sl.icon), label: esc(sl.tag ? sl.id : sl.name), count: sl.count };
      }, undefined, { ro: true, small: true })}</div>`;
    };
    const queued = (kind, value) => removals.some((r) => r.kind === kind && r.value === value);
    async function search() {
      try { const d = await api(`${base}/kubejs_items?q=${encodeURIComponent(q)}&limit=120`); items = d.items; items.forEach((i) => { names[i.id] = i.name; }); } catch (e) { toast(e.message, 'error'); }
      drawBrowser();
    }
    async function init() {
      try { removals = (await api(`${base}/kubejs_state`)).removals || []; } catch (e) { el.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
      if (window.ModnexKjsGui) window.ModnexKjsGui.setTextures(await window.ModnexKjsGui.load(base));
      if (window.ModnexKjsCreate) createData = await window.ModnexKjsCreate.prepare(base);
      await Promise.all([...new Set(removals.filter((r) => r.kind === 'output').map((r) => r.value))].slice(0, 30).map(async (id) => {
        try { (await api(`${base}/kubejs_items?q=${encodeURIComponent(id)}&limit=120`)).items.forEach((i) => { names[i.id] = i.name; }); } catch (e) { /* sin nombre */ }
      }));
      draw(); search();
    }
    function draw() {
      const list = removals.map((r, i) => `<li class="kjs-rm"><span>${r.kind === 'output'
        ? `Todas las recetas de <strong>${esc(nameOf(r.value))}</strong>` : `Receta <code>${esc(r.value)}</code>`}</span>
        <button class="btn sm" data-act="undo" data-i="${i}">Deshacer</button></li>`).join('');
      const selHTML = !sel ? '' : `<div class="kjs-editor"><div class="ft-head"><h2>${ico(sel.id, sel.icon)} ${esc(nameOf(sel.id))}</h2>
        <button class="btn sm danger" data-act="rm-output" ${queued('output', sel.id) ? 'disabled' : ''}>${queued('output', sel.id) ? 'Ya se quitan todas' : 'Quitar todas las recetas de este item'}</button></div>
        ${!found ? '<p class="muted small">Buscando recetas…</p>' : !found.recipes.length ? '<p class="muted small">Ningún mod ni vanilla tiene una receta para este item.</p>'
          : `<p class="muted small">${found.recipes.length} ${found.recipes.length === 1 ? 'receta' : 'recetas'} lo producen. Quita todas o solo las que no quieras. Las recetas agregadas desde el panel no les afecta «quitar todas»: se borran con su propio botón.</p>
            <ul class="kjs-recipes">${found.recipes.map((r) => `<li class="kjs-recipe">
              <div class="kjs-recipe-t"><span class="chip">${esc(RECIPE_TYPE[r.type] || (r.type.startsWith('create:') && createData && createData.types[r.type.slice(7)] ? 'Create · ' + createData.types[r.type.slice(7)].label : r.type.replace(/^[a-z0-9_.-]+:/, '')))}</span>${r.source === 'panel' ? ' <span class="chip ok">Agregada desde el panel</span>' : ''} <code>${esc(r.id)}</code></div>
              ${recipeGui(r) || `<div class="kjs-ing">${r.ingredients.map((i) => `<span class="kjs-ing-i" title="${esc(i.id)}">${ico(i.id, i.icon, 'kjs-ico sm')}<span class="muted small">${esc(i.tag ? i.id : i.name)}</span></span>`).join('') || '<span class="muted small">Sin ingredientes reconocibles</span>'}</div>`}
              ${r.source === 'panel' ? `<button class="btn sm danger" data-act="del-panel" data-slug="${esc(r.slug)}">Borrar receta</button>`
                : `<button class="btn sm" data-act="rm-id" data-id="${esc(r.id)}" ${queued('id', r.id) || queued('output', sel.id) ? 'disabled' : ''}>${queued('id', r.id) ? 'Se quita' : 'Quitar esta'}</button>`}</li>`).join('')}</ul>`}</div>`;
      el.innerHTML = `
        <div class="ft-head"><h2>Quitar recetas</h2><span class="muted small">${removals.length} ${removals.length === 1 ? 'eliminación' : 'eliminaciones'}</span></div>
        <p class="muted small">Busca un item, mira qué recetas lo producen y quita las que no quieras, también las de vanilla y las de otros mods. Se aplica con <code>/reload</code>.</p>
        ${removals.length ? `<ul class="kjs-rmlist">${list}</ul>` : ''}
        ${selHTML}
        <div class="kjs-browser-wrap"><div class="ft-head"><h2>Items</h2></div>
          <input class="kjs-search" type="search" placeholder="Buscar el item cuyas recetas quieres quitar" value="${esc(q)}" aria-label="Buscar item">
          <div class="kjs-browser" aria-live="polite"></div></div>
        <div class="kjs-foot"><span class="muted small">${status ? esc(status) : dirty ? 'Hay cambios sin guardar.' : ''}</span>
          <button class="btn primary" data-act="save" ${dirty ? '' : 'disabled'}>Guardar en el servidor</button></div>`;
      drawBrowser();
      if (window.ModnexKjsGui) window.ModnexKjsGui.place(el);
      if (window.ModnexKjsCreate) window.ModnexKjsCreate.place(el);
    }
    function drawBrowser() {
      const box = el.querySelector('.kjs-browser');
      if (!box) return;
      box.innerHTML = items.length ? items.map((it) => `<button class="kjs-item ${sel && sel.id === it.id ? 'on' : ''}" data-act="pick" data-id="${esc(it.id)}" title="${esc(it.id)}">${ico(it.id, it.icon)}<span class="kjs-item-t">${esc(it.name)}<span class="muted small block">${esc(it.id)}</span></span></button>`).join('')
        : '<p class="muted small">Ningún item coincide.</p>';
    }
    el.oninput = (e) => { if (e.target.classList.contains('kjs-search')) { q = e.target.value; clearTimeout(timer); timer = setTimeout(search, 180); } };
    el.onclick = async (e) => {
      const b = e.target.closest('[data-act]');
      if (!b || b.disabled) return;
      const act = b.getAttribute('data-act');
      if (act === 'pick') {
        const id = b.getAttribute('data-id'); sel = items.find((x) => x.id === id) || { id }; found = null; draw();
        try { found = await api(`${base}/kubejs_recipes_for?item=${encodeURIComponent(id)}`); } catch (err) { toast(err.message, 'error'); found = { recipes: [] }; }
        draw();
      }
      if (act === 'del-panel') {
        if (!window.confirm('¿Borrar esta receta de la lista del panel? Se aplica al guardar el script con el servidor.')) return;
        try { await api(`${base}/kubejs_recipe_delete`, { method: 'POST', body: { slug: b.getAttribute('data-slug') } }); toast('Receta borrada', 'ok'); found = await api(`${base}/kubejs_recipes_for?item=${encodeURIComponent(sel.id)}`); status = 'Receta borrada. Aplícalo con /reload en la consola del servidor.'; draw(); }
        catch (err) { toast(err.message, 'error'); }
      }
      if (act === 'rm-output') { removals.push({ kind: 'output', value: sel.id }); dirty = true; status = ''; draw(); }
      if (act === 'rm-id') { removals.push({ kind: 'id', value: b.getAttribute('data-id') }); dirty = true; status = ''; draw(); }
      if (act === 'undo') { removals.splice(Number(b.getAttribute('data-i')), 1); dirty = true; status = ''; draw(); }
      if (act === 'save') {
        b.disabled = true;
        try { const d = await api(`${base}/kubejs_removals_save`, { method: 'POST', body: { removals } }); removals = d.removals; dirty = false; status = 'Guardado. Aplícalo con /reload en la consola del servidor.'; toast('Eliminaciones guardadas', 'ok'); draw(); }
        catch (err) { toast(err.message, 'error'); b.disabled = false; }
      }
    };
    init();
  }

  function kjsScripts(el, s) {
    const { api, esc, toast } = M();
    const base = `/api/servers/${encodeURIComponent(s.name)}`;
    let list = [], cur = null, text = '', dirty = false;
    const folderLabel = { startup_scripts: 'startup', server_scripts: 'server', client_scripts: 'client' };
    async function load(keep) {
      try { list = (await api(`${base}/kubejs_scripts`)).scripts; } catch (e) { el.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
      if (keep && cur) { /* mantiene el script abierto */ } else if (!cur && list.length) await open(list[0].path);
      draw();
    }
    async function open(path) {
      try { const d = await api(`${base}/kubejs_script?path=${encodeURIComponent(path)}`); cur = d; text = d.text; dirty = false; } catch (e) { toast(e.message, 'error'); }
    }
    function draw() {
      const groups = Object.keys(folderLabel).map((f) => {
        const rows = list.filter((x) => x.folder === f);
        return `<div class="kjs-files-group"><span class="muted small">${esc(f)}</span>${rows.map((x) =>
          `<button class="kjs-file ${cur && cur.path === x.path ? 'on' : ''}" data-act="open" data-path="${esc(x.path)}">${esc(x.path.slice(f.length + 1))}${x.generated ? ' <span class="chip">generado</span>' : ''}</button>`).join('') || '<span class="muted small block">Sin scripts</span>'}</div>`;
      }).join('');
      const folder = cur ? cur.path.split('/')[0] : '';
      el.innerHTML = `<div class="kjs-scripts">
        <aside class="kjs-files">${groups}
          <div class="kjs-newfile"><select class="kjs-nfolder" aria-label="Carpeta">${Object.keys(folderLabel).map((f) => `<option value="${f}">${esc(f)}</option>`).join('')}</select>
            <input class="kjs-nname" placeholder="nombre.js" maxlength="64" aria-label="Nombre del script">
            <button class="btn sm" data-act="new">Crear</button></div></aside>
        <section class="kjs-editorpane">${cur ? `
          <div class="ft-head"><h2>${esc(cur.path)}</h2>
            <div class="ft-actions">${cur.generated ? '' : `<button class="btn sm danger" data-act="delete">Borrar</button><button class="btn sm primary" data-act="save" ${dirty ? '' : 'disabled'}>Guardar</button>`}</div></div>
          <p class="muted small">${esc(KJS_FOLDERS[folder] || '')}${cur.generated ? ' Este script lo genera el panel desde la vista Recetas y no se edita aquí.' : ''}</p>
          <textarea class="kjs-code" spellcheck="false" ${cur.generated ? 'readonly' : ''} aria-label="Código del script">${esc(text)}</textarea>`
          : '<p class="muted">Elige un script o crea uno nuevo.</p>'}</section></div>`;
    }
    el.oninput = (e) => {
      if (e.target.classList.contains('kjs-code')) { text = e.target.value; if (!dirty) { dirty = true; const b = el.querySelector('[data-act=save]'); if (b) b.disabled = false; } }
    };
    el.onkeydown = (e) => {
      if (e.key === 'Tab' && e.target.classList.contains('kjs-code') && !e.target.readOnly) {
        e.preventDefault(); const t = e.target, a = t.selectionStart;
        t.setRangeText('  ', a, t.selectionEnd, 'end'); text = t.value; dirty = true;
        const b = el.querySelector('[data-act=save]'); if (b) b.disabled = false;
      }
    };
    el.onclick = async (e) => {
      const b = e.target.closest('[data-act]');
      if (!b) return;
      const act = b.getAttribute('data-act');
      if (act === 'open') {
        if (dirty && !window.confirm('Hay cambios sin guardar en este script. ¿Descartarlos?')) return;
        await open(b.getAttribute('data-path')); draw();
      }
      if (act === 'save') {
        try { await api(`${base}/kubejs_script_save`, { method: 'POST', body: { path: cur.path, text } }); dirty = false; toast('Script guardado', 'ok'); draw(); }
        catch (err) { toast(err.message, 'error'); }
      }
      if (act === 'new') {
        const folder = el.querySelector('.kjs-nfolder').value, filename = el.querySelector('.kjs-nname').value.trim();
        try { await api(`${base}/kubejs_script_new`, { method: 'POST', body: { folder, filename } }); cur = null; dirty = false; await load(); await open(`${folder}/${filename}`); draw(); toast('Script creado', 'ok'); }
        catch (err) { toast(err.message, 'error'); }
      }
      if (act === 'delete') {
        if (!window.confirm(`¿Borrar ${cur.path}? No se puede deshacer.`)) return;
        try { await api(`${base}/kubejs_script_delete`, { method: 'POST', body: { path: cur.path } }); cur = null; dirty = false; toast('Script borrado', 'ok'); await load(); }
        catch (err) { toast(err.message, 'error'); }
      }
    };
    load();
  }

  function kjsDiag(el, s) {
    const { api, esc } = M();
    (async () => {
      let d;
      try { d = await api(`/api/servers/${encodeURIComponent(s.name)}/kubejs_diag`); } catch (e) { el.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
      const map = KJS_MAP.map(([g, rows]) => `<div class="ft-section"><div class="ft-head"><h2>${esc(g)}</h2></div>
        <table class="ft-table"><tbody>${rows.map(([name, st]) => `<tr><td>${esc(name)}</td><td><span class="chip ${esc(KJS_STATE[st][1])}">${esc(KJS_STATE[st][0])}</span></td></tr>`).join('')}</tbody></table></div>`).join('');
      el.innerHTML = `
        <div class="ft-head"><h2>Estado de KubeJS</h2></div>
        <p class="muted small">${d.jars.map(esc).join(' · ') || 'Sin jars de KubeJS'}</p>
        <p class="small">Scripts: <strong>${d.counts.startup_scripts}</strong> startup · <strong>${d.counts.server_scripts}</strong> server · <strong>${d.counts.client_scripts}</strong> client</p>
        <div class="ft-section"><div class="ft-head"><h2>Avisos y errores en el log</h2></div>
          ${d.log.length ? `<pre class="ft-pre">${esc(d.log.join('\n'))}</pre>` : '<p class="muted">Sin avisos ni errores de KubeJS en el log actual.</p>'}</div>
        <div class="ft-head"><h2>Qué se gestiona desde aquí</h2></div>
        <p class="muted small">Lo marcado como código se escribe en la vista Scripts. Lo visual se hace con formularios.</p>${map}`;
    })();
  }

  // ---------- Recetas KubeJS (mesa de crafteo y hornos, todo visual) ----------
  function recetas(el, s) {
    const { api, esc, toast } = M();
    const SLOTS = 9;
    const TYPES = {
      shaped: { label: 'Mesa · con forma', craft: true, hint: 'Con forma: la posición de los items importa.' },
      shapeless: { label: 'Mesa · sin forma', craft: true, hint: 'Sin forma: el orden de las casillas no importa.' },
      smelting: { label: 'Horno', cook: 200 },
      blasting: { label: 'Horno alto', cook: 200 },
      smoking: { label: 'Ahumador', cook: 200 },
      campfire: { label: 'Fogata', cook: 600 },
      stonecutting: { label: 'Cortapiedras', cut: true },
    };
    const isCraft = (t) => !!(TYPES[t] && TYPES[t].craft);
    const isCook = (t) => !!(TYPES[t] && TYPES[t].cook);
    const single = (t) => !isCraft(t);
    let recipes = [], total = 0, script = false, kubejs = true, vanilla = null, fetching = false;
    let items = [], q = '', timer = null;
    const info = {};                 // id -> { name, icon }
    let edit = null;                 // { index, id, type, grid[9], result, count, xp, time }
    let target = null;               // 'g0'..'g8' | 'out' | null
    let status = '', dirty = false;
    const fresh = () => ({ index: -1, id: '', type: 'shaped', grid: Array(SLOTS).fill(null), result: null, count: 1, xp: 0, time: 200 });
    const base = `/api/servers/${encodeURIComponent(s.name)}`;

    const label = (id) => (info[id] ? info[id].name : id);
    const icon = (id, cls = 'kjs-ico') => {
      const i = info[id];
      if (i && i.icon) return `<img class="${cls}" data-iid="${esc(id)}" src="${esc(i.icon)}" alt="" loading="lazy">`;
      const ch = (id || '?').split(':').pop().charAt(0).toUpperCase();
      return `<span class="${cls} kjs-ph" aria-hidden="true">${esc(ch)}</span>`;
    };
    function remember(list) { list.forEach((it) => { info[it.id] = { name: it.name, icon: it.icon }; }); }
    async function search() {
      try {
        const d = await api(`${base}/kubejs_items?q=${encodeURIComponent(q)}&limit=120`);
        items = d.items; remember(items);
      } catch (e) { toast(e.message, 'error'); }
      drawBrowser();
    }
    async function load() {
      let d;
      try { d = await api(`${base}/kubejs_state`); }
      catch (e) { el.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
      recipes = d.recipes; total = d.items; script = d.script; kubejs = d.kubejs; vanilla = d.vanilla || null;
      if (window.ModnexKjsGui) window.ModnexKjsGui.setTextures(await window.ModnexKjsGui.load(base));
      const need = [...new Set(recipes.flatMap((r) => [r.result.id, ...r.grid.filter(Boolean)]))].filter((id) => !info[id]);
      await Promise.all(need.map(async (id) => {
        try { const x = await api(`${base}/kubejs_items?q=${encodeURIComponent(id)}&limit=120`); remember(x.items); } catch (e) { /* sin icono */ }
      }));
      draw();
    }
    function draw() {
      if (!kubejs) { el.innerHTML = `<p class="muted">Este servidor no tiene KubeJS. Instálalo y arráncalo una vez para poder crear recetas.</p>`; return; }
      el.innerHTML = `
        <div class="ft-head"><h2>Recetas KubeJS</h2>
          <span class="muted small">${total} items en los mods · ${recipes.length} ${recipes.length === 1 ? 'receta' : 'recetas'}</span></div>
        <p class="muted small">Se guardan en el servidor y se aplican con <code>/reload</code> en la consola. Las recetas de fábrica no se tocan (para quitarlas usa «Quitar recetas»).</p>
        ${vanilla && vanilla.version && !vanilla.client ? `<div class="kjs-banner"><span>Los items de vanilla salen sin icono. Descarga el cliente oficial de Minecraft ${esc(vanilla.version)} (unos 27 MB, se guarda una vez) para ver sus texturas.</span>
          <button class="btn sm primary" data-act="vanilla" ${fetching ? 'disabled' : ''}>${fetching ? 'Descargando…' : 'Descargar texturas'}</button></div>` : ''}
        <div class="kjs-list">${recipes.map((r, i) => `
          <button class="kjs-card ${edit && edit.index === i ? 'on' : ''}" data-act="open" data-i="${i}">
            ${icon(r.result.id)}
            <span class="kjs-card-t"><strong>${esc(label(r.result.id))}</strong>
              <span class="muted small">${r.result.count}× · ${esc((TYPES[r.type] || {}).label || r.type)} · ${esc(r.id)}</span></span></button>`).join('')}
          <button class="kjs-card kjs-new" data-act="new">+ Nueva receta</button></div>
        ${recipes.length ? '' : '<p class="muted small">Todavía no hay recetas. Crea la primera con el botón de arriba.</p>'}
        ${edit ? editorHTML() : ''}
        <div class="kjs-browser-wrap"><div class="ft-head"><h2>Items</h2></div>
          <input class="kjs-search" type="search" placeholder="Buscar por nombre o id (ej. «cobre», «create:»)" value="${esc(q)}" aria-label="Buscar item">
          <div class="kjs-browser" aria-live="polite"></div></div>
        <div class="kjs-foot">
          <span class="muted small">${status ? esc(status) : (dirty ? 'Hay cambios sin guardar.' : (script ? 'Script generado en el servidor.' : 'Todavía no hay script generado.'))}</span>
          <button class="btn primary" data-act="save" ${dirty ? '' : 'disabled'}>Guardar en el servidor</button>
        </div>`;
      drawBrowser();
      if (window.ModnexKjsGui) window.ModnexKjsGui.place(el);
    }
    function typeChips() {
      return Object.entries(TYPES).map(([k, t]) => `<button class="${edit.type === k ? 'on' : ''}" data-act="type" data-type="${k}" aria-pressed="${edit.type === k}">${esc(t.label)}</button>`).join('');
    }
    function editorHTML() {
      const craft = isCraft(edit.type);
      const cell = (i) => {
        const id = edit.grid[i];
        return `<button class="kjs-slot ${target === 'g' + i ? 'on' : ''}" data-act="slot" data-slot="g${i}"
          aria-label="${id ? esc(label(id)) : 'casilla vacía'}">${id ? icon(id) : '<span class="kjs-empty"></span>'}</button>`;
      };
      const inputs = craft
        ? `<div class="kjs-grid">${Array.from({ length: SLOTS }, (_, i) => cell(i)).join('')}</div>`
        : `<div class="kjs-single">${cell(0)}<span class="muted small">Ingrediente</span></div>`;
      const outBtn = `<button class="kjs-slot big ${target === 'out' ? 'on' : ''}" data-act="slot" data-slot="out"
          aria-label="${edit.result ? esc(label(edit.result)) : 'resultado vacío'}">${edit.result ? icon(edit.result, 'kjs-ico big') : '<span class="kjs-empty"></span>'}</button>`;
      // Con las texturas del cliente de Minecraft se pinta la interfaz real del juego; sin ellas, la cuadrícula sencilla.
      const G = window.ModnexKjsGui, skin = G && G.skinFor(edit.type);
      const mcGui = G && G.has(skin) ? G.html(skin, (key) => {
        if (key === 'out') return { inner: edit.result ? icon(edit.result) : '', attrs: 'data-act="slot" data-slot="out"', on: target === 'out', label: edit.result ? esc(label(edit.result)) : 'resultado vacío', count: edit.count };
        const i = Number(key.slice(1)), id = edit.grid[i];
        return { inner: id ? icon(id) : '', attrs: `data-act="slot" data-slot="g${i}"`, on: target === key, label: id ? esc(label(id)) : 'casilla vacía' };
      }, G.title(edit.type)) : '';
      const timeSec = (edit.time / 20).toFixed(edit.time % 20 ? 2 : 0);
      const extras = [];
      if (isCook(edit.type) || edit.type === 'stonecutting') {
        extras.push(`<label class="kjs-field small">Experiencia<input class="kjs-xp" type="number" min="0" max="100" step="0.05" value="${esc(edit.xp)}"></label>`);
      }
      if (isCook(edit.type)) {
        extras.push(`<label class="kjs-field small">Tiempo (s)<input class="kjs-time" type="number" min="0.05" max="300" step="0.5" value="${esc(timeSec)}"></label>`);
      }
      return `<div class="kjs-editor">
        <div class="kjs-row">
          <label class="kjs-field">Nombre de la receta<input class="kjs-name" value="${esc(edit.id)}" maxlength="40" placeholder="ej. cobre_bloque"></label>
        </div>
        <div class="kjs-types" role="group" aria-label="Tipo de receta">${typeChips()}</div>
        ${mcGui ? `<div class="kjs-craft-mc">${mcGui}
          <label class="kjs-field small">Cantidad del resultado<input class="kjs-count" type="number" min="1" max="64" value="${esc(edit.count)}"></label></div>` : `<div class="kjs-craft">
          ${inputs}
          <span class="kjs-arrow" aria-hidden="true">→</span>
          <div class="kjs-out">${outBtn}
            <label class="kjs-field small">Cantidad<input class="kjs-count" type="number" min="1" max="64" value="${esc(edit.count)}"></label>
          </div>
        </div>`}
        ${extras.length ? `<div class="kjs-extras">${extras.join('')}</div>` : ''}
        <p class="muted small">Elige una casilla y luego un item de la lista. ${esc(TYPES[edit.type].hint || '')}</p>
        <div class="ft-actions">
          <button class="btn" data-act="clear" ${target ? '' : 'disabled'}>Casilla vacía</button>
          <button class="btn" data-act="cancel">Cancelar</button>
          <button class="btn primary" data-act="keep">Añadir a la lista</button>
        </div></div>`;
    }
    function drawBrowser() {
      const box = el.querySelector('.kjs-browser');
      if (!box) return;
      box.innerHTML = items.length ? items.map((it) => `<button class="kjs-item" data-act="pick" data-id="${esc(it.id)}"
          title="${esc(it.id)}">${icon(it.id)}<span class="kjs-item-t">${esc(it.name)}<span class="muted small block">${esc(it.id)}</span></span></button>`).join('')
        : '<p class="muted small">Ningún item coincide.</p>';
    }
    function pick(id) {
      if (!edit) edit = fresh();
      if (!target) {
        const free = single(edit.type) ? (edit.grid[0] ? -1 : 0) : edit.grid.findIndex((c) => !c);
        target = free >= 0 ? 'g' + free : 'out';
      }
      if (target === 'out') edit.result = id;
      else edit.grid[Number(target.slice(1))] = id;
      if (!edit.id && edit.result) edit.id = edit.result.split(':').pop().replace(/[^a-z0-9_]/g, '_').slice(0, 40);
      dirty = true; status = ''; target = null; draw();
    }
    function readFields() {
      const v = (sel, d) => { const x = el.querySelector(sel); return x ? x.value : d; };
      edit.id = v('.kjs-name', edit.id);
      edit.count = Number(v('.kjs-count', edit.count)) || 1;
      edit.xp = Number(v('.kjs-xp', edit.xp)) || 0;
      const sec = Number(v('.kjs-time', edit.time / 20));
      edit.time = Math.round((sec || 0) * 20) || 1;
    }
    function commit() {
      readFields();
      if (!edit.result) return toast('Elige el resultado', 'error');
      const filled = isCraft(edit.type) ? edit.grid.some(Boolean) : !!edit.grid[0];
      if (!filled) return toast(isCraft(edit.type) ? 'Pon al menos un ingrediente' : 'Pon el ingrediente', 'error');
      const r = { id: edit.id.trim(), type: edit.type, grid: isCraft(edit.type) ? edit.grid.slice() : [edit.grid[0], ...Array(8).fill(null)],
        result: { id: edit.result, count: edit.count } };
      if (single(edit.type)) r.xp = edit.xp;
      if (isCook(edit.type)) r.time = edit.time;
      if (edit.index >= 0) recipes[edit.index] = r; else recipes.push(r);
      edit = null; target = null; dirty = true; status = 'Receta lista. Guarda la lista en el servidor para aplicarla.'; draw();
    }
    el.oninput = (e) => {
      if (e.target.classList.contains('kjs-search')) { q = e.target.value; clearTimeout(timer); timer = setTimeout(search, 180); }
      if (edit && e.target.classList.contains('kjs-name')) { edit.id = e.target.value; dirty = true; }
    };
    el.onclick = async (e) => {
      const b = e.target.closest('[data-act]');
      if (!b) return;
      const act = b.getAttribute('data-act');
      if (act === 'vanilla') {
        fetching = true; draw();
        try { vanilla = await api(`${base}/kubejs_vanilla_fetch`, { method: 'POST', body: {} }); toast('Texturas de vanilla listas', 'ok'); await search(); } catch (err) { toast(err.message, 'error'); }
        fetching = false; draw();
      }
      if (act === 'new') { edit = fresh(); target = null; status = ''; draw(); }
      if (act === 'open') {
        const i = Number(b.getAttribute('data-i')); const r = recipes[i];
        edit = { index: i, id: r.id, type: r.type, grid: r.grid.slice(), result: r.result.id, count: r.result.count,
          xp: r.xp || 0, time: r.time || (TYPES[r.type] && TYPES[r.type].cook) || 200 };
        target = null; draw();
      }
      if (act === 'type') {
        readFields();
        const t = b.getAttribute('data-type');
        edit.type = t;
        if (single(t)) edit.grid = [edit.grid[0], ...Array(8).fill(null)];
        if (TYPES[t].cook && !edit.time) edit.time = TYPES[t].cook;
        target = null; draw();
      }
      if (act === 'slot') { const t = b.getAttribute('data-slot'); target = target === t ? null : t; draw(); }
      if (act === 'pick') pick(b.getAttribute('data-id'));
      if (act === 'clear') {
        if (target === 'out') edit.result = null; else if (target) edit.grid[Number(target.slice(1))] = null;
        target = null; dirty = true; draw();
      }
      if (act === 'cancel') { edit = null; target = null; draw(); }
      if (act === 'keep') commit();
      if (act === 'save') {
        b.disabled = true;
        try {
          const d = await api(`${base}/kubejs_save`, { method: 'POST', body: { recipes } });
          recipes = d.recipes; script = d.script; dirty = false; edit = null; target = null;
          status = 'Guardado. Aplícalo con /reload en la consola del servidor.'; toast('Recetas guardadas', 'ok'); draw();
        } catch (err) { toast(err.message, 'error'); b.disabled = false; }
      }
    };
    load().then(search);
  }

  // ---------- Propuestas de mods ----------
  function propuestas(el, s) {
    const { api, esc, toast } = M();
    const ST = { pending: ['Pendiente', ''], approved: ['Aprobada', 'ok'], rejected: ['Rechazada', 'bad'] };
    let results = [], searching = false, lastQ = '';
    async function load() {
      let d;
      try { d = await api(url(s, 'proposals')); } catch (e) { el.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
      draw(d);
    }
    function draw(d) {
      const found = results.map((r, i) => `<li class="ft-result"><div class="grow"><strong>${esc(r.title)}</strong><span class="muted small block">${esc(r.description)}</span></div>
        <button class="btn sm" data-act="propose" data-i="${i}">Proponer</button></li>`).join('');
      const rows = d.proposals.map((p) => `<tr>
        <td><strong>${esc(p.title)}</strong><span class="muted small block">${esc(p.source)}${p.note ? ' · ' + esc(p.note) : ''}</span></td>
        <td>${esc(p.username)}</td>
        <td><span class="chip ${esc(ST[p.status][1])}">${esc(ST[p.status][0])}</span>${p.reason ? `<span class="muted small block">${esc(p.reason)}</span>` : ''}</td>
        <td><div class="ft-actions">
          ${p.status === 'pending' && d.can_decide ? `<button class="btn sm" data-act="approve" data-id="${esc(p.id)}">Aprobar</button><button class="btn sm danger" data-act="reject" data-id="${esc(p.id)}">Rechazar</button>` : ''}
          ${p.status === 'approved' && d.can_decide ? `<a class="btn sm primary" href="#/m/${esc(p.source)}/${encodeURIComponent(p.project_id)}">Ver e instalar</a>` : ''}
          ${p.status === 'pending' && (p.user_id === d.me || d.can_decide) ? `<button class="btn sm" data-act="withdraw" data-id="${esc(p.id)}">Retirar</button>` : ''}
        </div></td></tr>`).join('');
      el.innerHTML = `
        <div class="ft-head"><h2>Propuestas de mods</h2></div>
        <p class="muted small">Busca un mod compatible con este servidor y propónlo. Quien administra decide si se instala.</p>
        <form class="ft-form" data-form="search">
          <label class="ft-grow">Buscar mod<input name="q" maxlength="80" value="${esc(lastQ)}" placeholder="Sodium, Create, JEI…"></label>
          <label>Motivo (opcional)<input name="note" maxlength="300" placeholder="Para qué lo quieres"></label>
          <button class="btn" type="submit" ${searching ? 'disabled' : ''}>${searching ? 'Buscando…' : 'Buscar'}</button>
        </form>
        ${found ? `<ul class="ft-results">${found}</ul>` : ''}
        <div class="ft-section"><div class="ft-head"><h2>Propuestas</h2></div>
          ${d.proposals.length ? `<table class="ft-table"><thead><tr><th>Mod</th><th>Propuesto por</th><th>Estado</th><th></th></tr></thead><tbody>${rows}</tbody></table>` : '<p class="muted">Todavía no hay propuestas.</p>'}
        </div>`;
    }
    el.onsubmit = async (e) => {
      e.preventDefault();
      lastQ = e.target.q.value.trim(); searching = true; load();
      try { results = (await api(url(s, 'proposal_search', `?q=${encodeURIComponent(lastQ)}`))).results; }
      catch (err) { results = []; toast(err.message, 'error'); }
      searching = false; load();
    };
    el.onclick = async (e) => {
      const b = e.target.closest('[data-act]');
      if (!b) return;
      const act = b.getAttribute('data-act'), id = b.getAttribute('data-id');
      try {
        if (act === 'propose') {
          const r = results[Number(b.getAttribute('data-i'))], note = el.querySelector('input[name=note]').value;
          await api(url(s, 'proposal_create'), { method: 'POST', body: { source: r.source, project_id: r.project_id, slug: r.slug, title: r.title, icon: r.icon, note } });
          toast('Propuesta enviada', 'ok'); results = results.filter((x) => x !== r);
        } else if (act === 'approve' || act === 'reject') {
          const reason = act === 'reject' ? (window.prompt('Motivo del rechazo (opcional)') || '') : '';
          await api(url(s, 'proposal_decide'), { method: 'POST', body: { id: Number(id), decision: act, reason } });
        } else if (act === 'withdraw') {
          await api(url(s, 'proposal_withdraw'), { method: 'POST', body: { id: Number(id) } });
        }
        load();
      } catch (err) { toast(err.message, 'error'); }
    };
    load();
  }

  // ---------- Actualizar mods (prueba aislada) ----------
  function actualizar(el, s) {
    const { api, esc, toast, askConfirm } = M();
    clearTimeout(pollTimer);
    async function load() {
      let d;
      try { d = await api(url(s, 'safe_update')); } catch (e) { el.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
      draw(d);
      if (d.state === 'running') pollTimer = setTimeout(() => { if (el.isConnected) load(); }, 2500);
    }
    const mod = (m) => `${esc(m.name)} <span class="muted small">${esc(m.installed || '?')} → ${esc(m.latest)}</span>`;
    function draw(d) {
      const stopNote = d.running ? '<p class="ft-note">El servidor está en marcha. Páralo para probar o aplicar: la prueba usa su memoria y sus puertos.</p>' : '';
      let body = '';
      if (d.state === 'running') {
        body = `<div class="ft-card info"><h3>Probando…</h3><p>${esc(d.step || '')}</p><p class="muted small">Arranques de prueba hechos: ${esc(d.boots || 0)}. Puede tardar varios minutos.</p></div>`;
      } else if (d.state === 'error') {
        body = `<div class="ft-card error"><h3>La prueba no pudo completarse</h3><p>${esc(d.error)}</p></div>`;
      } else if (d.state === 'done') {
        if (d.note) body = `<p class="muted">${esc(d.note)}</p>`;
        else body = `
          ${d.safe.length ? `<div class="ft-card info"><h3>Se pueden actualizar sin problemas (${d.safe.length})</h3>
            <form data-form="apply"><ul class="ft-checks">${d.safe.map((m) => `<li><label><input type="checkbox" name="f" value="${esc(m.file)}" checked> ${mod(m)}</label></li>`).join('')}</ul>
            <button class="btn primary" type="submit" ${d.running ? 'disabled title="Para el servidor primero"' : ''}>Aplicar las seleccionadas</button></form></div>` : ''}
          ${d.bad.length ? `<div class="ft-card error"><h3>No se actualizan (${d.bad.length})</h3><ul class="ft-checks">${d.bad.map((m) => `<li>${mod(m)}<span class="muted small block">${esc(m.kind === 'conflict' ? 'Choca con otra actualización: ' : '')}${esc(m.reason)}</span></li>`).join('')}</ul></div>` : ''}
          ${d.unknown && d.unknown.length ? `<div class="ft-card warn"><h3>Sin comprobar</h3><p>Se alcanzó el límite de arranques de prueba. Quedan sin probar: ${esc(d.unknown.join(', '))}.</p></div>` : ''}
          <p class="muted small">Se hicieron ${esc(d.boots || 0)} arranques de prueba en un entorno aparte, sin tocar tu mundo ni tus mods.</p>`;
      } else {
        body = '<p class="muted">Mira qué mods tienen una versión nueva y comprueba, arrancando una copia aislada del servidor, que no rompen nada. Solo se aplican las que pasan la prueba.</p>';
      }
      el.innerHTML = `
        <div class="ft-head"><h2>Actualizar mods</h2><button class="btn primary" data-act="start" ${d.state === 'running' || d.running ? 'disabled' : ''}>${d.state === 'done' ? 'Probar de nuevo' : 'Probar actualizaciones'}</button></div>
        ${stopNote}${body}`;
    }
    el.onclick = async (e) => {
      if (!e.target.closest('[data-act=start]')) return;
      try { await api(url(s, 'safe_update_start'), { method: 'POST', body: {} }); toast('Prueba iniciada', 'ok'); load(); } catch (err) { toast(err.message, 'error'); }
    };
    el.onsubmit = async (e) => {
      e.preventDefault();
      const files = [...e.target.querySelectorAll('input[name=f]:checked')].map((x) => x.value);
      if (!files.length) { toast('Elige al menos un mod', 'error'); return; }
      if (!(await askConfirm('¿Aplicar estas actualizaciones?', `Se actualizan ${files.length} mod(s). Antes se guarda una copia de seguridad automática.`, { confirmLabel: 'Aplicar' }))) return;
      try { const r = await api(url(s, 'safe_update_apply'), { method: 'POST', body: { files } }); toast(`${r.applied.length} mods actualizados`, 'ok'); load(); } catch (err) { toast(err.message, 'error'); }
    };
    load();
  }

  // ---------- Seguridad: verificación en dos pasos y acceso remoto ----------
  function seguridad(host) {
    // Los manejadores se atan a un contenedor propio y NO al elemento que recibe la página (#main): ese elemento
    // sobrevive al cambiar de vista, y sus onclick/onsubmit seguían vivos y repintaban esta página al usar cualquier
    // botón o formulario del panel.
    const el = document.createElement('div');
    host.replaceChildren(el);
    const { api, esc, toast, askConfirm, isAdmin } = M();
    let setup = null, recovery = null, users = [];
    async function load() {
      let st, rem = null;
      try {
        st = await api('/api/features/2fa_status');
        if (isAdmin()) { rem = await api('/api/features/remote_status'); users = await api('/api/users').catch(() => []); }
      } catch (e) { el.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
      draw(st, rem);
    }
    function draw(st, rem) {
      let two = '';
      if (recovery) {
        two = `<div class="ft-card warn"><h3>Guarda estos códigos de recuperación</h3>
          <p>Cada uno sirve una vez si pierdes el móvil. <strong>No se volverán a mostrar.</strong></p>
          <ul class="ft-codes">${recovery.map((c) => `<li><code>${esc(c)}</code></li>`).join('')}</ul>
          <button class="btn" data-act="done-codes">Ya los guardé</button></div>`;
      } else if (st.enabled) {
        two = `<div class="ft-card info"><h3>Verificación en dos pasos activada</h3><p>Te quedan ${esc(st.recovery_left)} códigos de recuperación.</p>
          <form class="ft-form" data-form="off"><label>Código para desactivarla<input name="code" autocomplete="one-time-code" required placeholder="123456 o un código de recuperación"></label>
          <button class="btn danger" type="submit">Desactivar</button></form></div>`;
      } else if (setup) {
        two = `<div class="ft-card"><h3>Añade la cuenta a tu app de autenticación</h3>
          ${setup.qr ? `<p>Escanea este código con tu app (Google Authenticator, Aegis, Authy…):</p><div class="ft-qr">${setup.qr}</div><p class="muted small">¿No puedes escanearlo? En la app elige «introducir clave manualmente» y escribe esta clave:</p>`
            : '<p>En la app (Google Authenticator, Aegis, Authy…) elige «introducir clave manualmente» y escribe:</p>'}
          <p><code class="ft-secret">${esc(setup.secret)}</code></p>
          <p class="muted small">Tipo: basado en tiempo · 6 dígitos · 30 s.</p>
          <form class="ft-form" data-form="on"><label>Código que muestra la app<input name="code" inputmode="numeric" autocomplete="one-time-code" required maxlength="8" placeholder="123456"></label>
          <button class="btn primary" type="submit">Activar</button><button class="btn" type="button" data-act="cancel-2fa">Cancelar</button></form></div>`;
      } else {
        two = `<p class="muted">Pide un código de tu móvil además de la contraseña al iniciar sesión. Es obligatorio para entrar por el acceso remoto.</p>
          <button class="btn primary" data-act="begin-2fa">Activar verificación en dos pasos</button>`;
      }
      let remoteHtml = '';
      if (rem) {
        const provs = Object.entries(rem.providers || {});
        remoteHtml = `<div class="ft-section"><div class="ft-head"><h2>Acceso remoto para usuarios</h2></div>
          <p class="muted small">Abre un túnel público hacia este panel para que los usuarios con permisos puedan administrar sus servidores desde fuera de tu red. <strong>Los administradores no pueden entrar por el túnel</strong>: solo desde este equipo o la red local. ${rem.require_2fa ? 'Los usuarios necesitan la verificación en dos pasos, que deben activar antes desde la red local.' : 'La verificación en dos pasos no es obligatoria (desactivada en la configuración).'}</p>
          <p class="muted small">La dirección es pública mientras esté abierto. Cloudflare cambia de dirección cada vez y no ofrece garantías; ngrok necesita una cuenta con su token configurado.</p>
          ${!rem.available ? '<p class="ft-note">No encuentro <code>cloudflared</code> ni <code>ngrok</code>, así que no se puede abrir el túnel.</p>' : ''}
          ${rem.active ? `<div class="ft-card warn"><h3>Acceso remoto abierto (${esc((rem.providers[rem.provider] || {}).label || rem.provider)})</h3><p><a href="${esc(rem.url)}" target="_blank" rel="noopener noreferrer">${esc(rem.url)}</a></p>
            <p class="muted small">Pasa esta dirección solo a quien deba usarla. Ciérralo cuando no lo uses.</p>
            <button class="btn danger" data-act="remote-stop">Cerrar acceso remoto</button></div>`
          : `${rem.error ? `<p class="muted small">${esc(rem.error)}</p>` : ''}
            <form class="ft-form" data-form="remote-open"><label>Túnel<select name="provider">${provs.map(([k, v]) => `<option value="${esc(k)}" ${v.available ? '' : 'disabled'}>${esc(v.label)}${v.available ? '' : ' (no instalado)'}</option>`).join('')}</select></label>
            <button class="btn primary" type="submit" ${rem.available ? '' : 'disabled'}>Abrir acceso remoto</button></form>`}
          <div class="ft-section"><div class="ft-head"><h2>Restablecer la verificación de un usuario</h2></div>
            <p class="muted small">Si alguien pierde el móvil y sus códigos de recuperación, quita su verificación para que pueda activarla de nuevo.</p>
            <form class="ft-form" data-form="reset"><label>Usuario<select name="uid">${users.map((u) => `<option value="${esc(u.id)}">${esc(u.username)}</option>`).join('')}</select></label>
            <button class="btn danger" type="submit">Restablecer</button></form></div></div>`;
      }
      el.innerHTML = `<div class="ft-head"><h2>Seguridad de la cuenta</h2></div>
        <div class="ft-section ft-first"><div class="ft-head"><h2>Verificación en dos pasos</h2></div>${two}</div>${remoteHtml}`;
    }
    el.onclick = async (e) => {
      const b = e.target.closest('[data-act]');
      if (!b) return;
      const act = b.getAttribute('data-act');
      try {
        if (act === 'begin-2fa') { setup = await api('/api/features/2fa_begin', { method: 'POST', body: {} }); }
        else if (act === 'cancel-2fa') { setup = null; }
        else if (act === 'done-codes') { recovery = null; }
        else if (act === 'remote-stop') { await api('/api/features/remote_stop', { method: 'POST', body: {} }); toast('Acceso remoto cerrado', 'ok'); }
        load();
      } catch (err) { toast(err.message, 'error'); }
    };
    el.onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target, kind = f.getAttribute('data-form');
      try {
        if (kind === 'on') { const r = await api('/api/features/2fa_confirm', { method: 'POST', body: { code: f.code.value } }); recovery = r.recovery; setup = null; toast('Verificación activada', 'ok'); }
        else if (kind === 'remote-open') {
          if (!(await askConfirm('¿Abrir el acceso remoto?', 'El panel quedará accesible desde internet mediante una dirección pública. Los administradores no podrán entrar por ahí; los usuarios necesitan su contraseña y, por defecto, el código de verificación.', { confirmLabel: 'Abrir acceso remoto', danger: true }))) return;
          await api('/api/features/remote_start', { method: 'POST', body: { provider: f.provider.value } }); toast('Acceso remoto abierto', 'ok');
        } else if (kind === 'off') {
          if (!(await askConfirm('¿Desactivar la verificación en dos pasos?', 'Tu cuenta quedará protegida solo por la contraseña y no podrás entrar por el acceso remoto.', { confirmLabel: 'Desactivar', danger: true }))) return;
          await api('/api/features/2fa_disable', { method: 'POST', body: { code: f.code.value } }); toast('Verificación desactivada', 'ok');
        } else if (kind === 'reset') {
          if (!(await askConfirm('¿Restablecer la verificación de este usuario?', 'Podrá iniciar sesión solo con su contraseña hasta que la vuelva a activar.', { confirmLabel: 'Restablecer', danger: true }))) return;
          await api('/api/features/2fa_reset', { method: 'POST', body: { user_id: Number(f.uid.value) } }); toast('Verificación restablecida', 'ok');
        }
        load();
      } catch (err) { toast(err.message, 'error'); }
    };
    load();
  }

  // ---------- Sincronización de clientes (AutoModpack) ----------
  function sincronizacion(el, s) {
    const { api, esc, toast, askConfirm } = M();
    clearTimeout(pollTimer);
    async function load() {
      let d;
      try { d = await api(url(s, 'sync')); } catch (e) { el.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
      draw(d);
      if (d.state === 'running') pollTimer = setTimeout(() => { if (el.isConnected) load(); }, 2500);
    }
    function draw(d) {
      const inst = d.installed || [];
      let body = '';
      if (inst.length) {
        body += `<div class="ft-card info"><h3>Instalado en el servidor</h3><p>${esc(inst.join(', '))}</p>
          ${d.fingerprint ? `<p>Huella del certificado que deben aceptar los jugadores la primera vez:</p><p><code class="ft-secret">${esc(d.fingerprint)}</code></p>`
            : '<p class="muted small">La huella aparece aquí cuando el servidor arranque con el mod.</p>'}</div>`;
      }
      if (d.state === 'running') {
        body += `<div class="ft-card info"><h3>Probando…</h3><p>${esc(d.step || '')}</p><p class="muted small">Puede tardar un par de minutos. No afecta a tu mundo.</p></div>`;
      } else if (d.state === 'error') {
        body += `<div class="ft-card error"><h3>La prueba no pudo completarse</h3><p>${esc(d.error)}</p></div>`;
      } else if (d.state === 'done' && d.ok === false) {
        body += `<div class="ft-card error"><h3>El servidor no arrancó con AutoModpack ${esc(d.version || '')}</h3><p>${esc(d.reason || '')}</p></div>`;
      } else if (d.state === 'done') {
        body += `<div class="ft-card info"><h3>Funciona: AutoModpack ${esc(d.version)} arrancó en ${esc(d.seconds)} s</h3>
          <p>Los jugadores descargarían <strong>${d.published.length} mods</strong>${d.other_files ? ` y ${esc(d.other_files)} archivos más` : ''}.
          ${d.host_on_game_port ? 'Se sirve por el mismo puerto de Minecraft: no hay que abrir otro.' : ''}</p>
          ${d.excluded.length ? `<p class="muted small">No se publican (solo de servidor): ${esc(d.excluded.join(', '))}</p>` : ''}
          <details><summary>Lista de mods que recibirían los jugadores</summary><ul class="ft-checks">${d.published.map((m) => `<li>${esc(m)}</li>`).join('')}</ul></details>
          <p class="muted small">La huella del certificado de esta prueba no es la del servidor real; la del real aparece al instalarlo y arrancar.</p>
          ${inst.length ? '' : `<button class="btn primary" data-act="install" ${d.running ? 'disabled title="Para el servidor primero"' : ''}>Instalar en el servidor</button>${d.running ? '<span class="muted small"> Para el servidor para instalarlo.</span>' : ''}`}</div>`;
      } else if (!inst.length) {
        body += '<p class="muted">AutoModpack hace que los jugadores reciban solos los mods del servidor cada vez que entran. Antes de instalarlo, pruébalo aquí: se arranca una copia aislada del servidor, sin tu mundo, y se ve qué publicaría.</p>';
      }
      el.innerHTML = `<div class="ft-head"><h2>Sincronización de clientes</h2>
        <button class="btn ${inst.length ? '' : 'primary'}" data-act="test" ${d.state === 'running' ? 'disabled' : ''}>${d.state === 'done' ? 'Probar de nuevo' : 'Probar en una copia aislada'}</button></div>
        ${d.running ? '<p class="ft-note">El servidor está en marcha. La prueba usa hasta 4 GB de memoria y baja prioridad; si notas lag, espera a que termine.</p>' : ''}${body}`;
    }
    el.onclick = async (e) => {
      const b = e.target.closest('[data-act]');
      if (!b) return;
      try {
        if (b.getAttribute('data-act') === 'test') { await api(url(s, 'sync_test_start'), { method: 'POST', body: {} }); toast('Prueba iniciada', 'ok'); }
        else if (b.getAttribute('data-act') === 'install') {
          if (!(await askConfirm('¿Instalar AutoModpack en el servidor?', 'Se guarda una copia de seguridad antes. Los jugadores necesitarán AutoModpack en su cliente.', { confirmLabel: 'Instalar' }))) return;
          const r = await api(url(s, 'sync_install'), { method: 'POST', body: {} }); toast(`Instalado ${r.installed}`, 'ok');
        }
        load();
      } catch (err) { toast(err.message, 'error'); }
    };
    load();
  }

  // ---------- Servidor de pruebas ----------
  function pruebas(el, s) {
    const { api, esc, toast, askConfirm } = M();
    let diffData = null;
    async function load() {
      let st;
      try { st = await api(url(s, 'staging')); } catch (e) { el.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
      diffData = null;
      if (st.exists) { try { diffData = await api(url(s, 'staging_diff')); } catch (e) { toast(e.message, 'error'); } }
      draw(st);
    }
    const KIND = { modified: 'Modificado', added: 'Nuevo', removed: 'Borrado en pruebas' };
    const MODKIND = { modified: 'Contenido distinto', added: 'Solo en pruebas: se añade al real', removed: 'Solo en el real: se quita del real' };
    function draw(st) {
      if (!st.exists) {
        el.innerHTML = `<div class="ft-head"><h2>Servidor de pruebas</h2></div>
          <p class="muted">Crea una copia de este servidor para probar mods y cambios de configuración sin tocar el real. Tiene sus propios mods, su propia configuración y un mundo nuevo y vacío: no se copia nada de tu mundo. Lo que cambies en su configuración se puede fusionar después con el servidor real.</p>
          <button class="btn primary" data-act="create">Crear servidor de pruebas</button>`;
        return;
      }
      const d = diffData;
      const mods = d ? d.mods : { only_staging: [], only_real: [], same: 0 };
      const rows = d ? d.changes.map((c, i) => `<li class="ft-change">
          <label><input type="checkbox" name="p" value="${i}" ${c.kind === 'removed' ? '' : 'checked'}> <code>${esc(c.path)}</code> <span class="muted small">${esc(KIND[c.kind])}</span></label>
          ${c.text && c.diff ? `<details><summary class="muted small">Ver diferencias</summary><pre class="ft-diff">${esc(c.diff)}</pre></details>` : (c.text ? '' : '<span class="muted small block">Archivo binario o grande: no se muestra la diferencia.</span>')}
        </li>`).join('') : '';
      const other = st.viewing === 'staging' ? st.real : st.staging;
      el.innerHTML = `<div class="ft-head"><h2>Servidor de pruebas</h2><button class="btn" data-act="refresh">Comparar de nuevo</button></div>
        <p>${st.viewing === 'staging' ? `Este es el servidor de pruebas de <strong>${esc(st.real)}</strong>.` : `Servidor de pruebas: <a href="#/s/${encodeURIComponent(st.staging)}"><strong>${esc(st.staging)}</strong></a> ${st.staging_running ? '<span class="muted small">(en marcha)</span>' : '<span class="muted small">(parado)</span>'}`}</p>
        <div class="ft-section"><div class="ft-head"><h2>Mods</h2></div>
          <p class="muted small">${esc(mods.same)} mods iguales en los dos servidores.</p>
          ${d && d.mod_changes.length ? `<form data-form="merge-mods"><ul class="ft-checks">${d.mod_changes.map((m, i) => `<li class="ft-change"><label><input type="checkbox" name="m" value="${i}" ${m.kind === 'removed' ? '' : 'checked'}> <code>${esc(m.file)}</code> <span class="muted small">${esc(MODKIND[m.kind])}</span></label></li>`).join('')}</ul>
            <button class="btn primary" type="submit" ${st.real_running ? 'disabled title="Para el servidor real primero"' : ''}>Fusionar mods en el servidor real</button>
            ${st.real_running ? '<span class="muted small"> Para el servidor real para fusionar.</span>' : ''}</form>` : '<p class="muted">Los mods son iguales.</p>'}
          ${st.staging_running ? '' : '<button class="btn" data-act="amp">Instalar AutoModpack en el servidor de pruebas</button>'}</div>
        <div class="ft-section"><div class="ft-head"><h2>Cambios de configuración</h2></div>
          ${d && d.changes.length ? `<form data-form="merge"><ul class="ft-checks">${rows}</ul>
            <button class="btn primary" type="submit" ${st.real_running ? 'disabled title="Para el servidor real primero"' : ''}>Fusionar en el servidor real</button>
            ${st.real_running ? '<span class="muted small"> Para el servidor real para fusionar.</span>' : ''}</form>` : '<p class="muted">La configuración es igual en los dos servidores.</p>'}</div>
        <div class="ft-section"><button class="btn danger" data-act="delete" ${st.staging_running ? 'disabled' : ''}>Borrar el servidor de pruebas</button></div>`;
    }
    el.onclick = async (e) => {
      const b = e.target.closest('[data-act]');
      if (!b) return;
      const act = b.getAttribute('data-act');
      try {
        if (act === 'create') { const r = await api(url(s, 'staging_create'), { method: 'POST', body: {} }); toast(`Creado ${r.staging} (puerto ${r.port})`, 'ok'); }
        else if (act === 'amp') { const r = await api(url(s, 'staging_sync_install'), { method: 'POST', body: {} }); toast(`Instalado ${r.installed}`, 'ok'); }
        else if (act === 'delete') {
          if (!(await askConfirm('¿Borrar el servidor de pruebas?', 'Se borran su carpeta, sus mods y su mundo de pruebas. El servidor real no se toca.', { confirmLabel: 'Borrar', danger: true }))) return;
          await api(url(s, 'staging_delete'), { method: 'POST', body: {} }); toast('Servidor de pruebas borrado', 'ok');
        }
        load();
      } catch (err) { toast(err.message, 'error'); }
    };
    el.onsubmit = async (e) => {
      e.preventDefault();
      if (e.target.getAttribute('data-form') === 'merge-mods') {
        const picks = [...e.target.querySelectorAll('input[name=m]:checked')].map((x) => {
          const m = diffData.mod_changes[Number(x.value)];
          return { file: m.file, action: m.kind === 'removed' ? 'delete' : 'copy' };
        });
        if (!picks.length) { toast('Elige al menos un mod', 'error'); return; }
        if (!(await askConfirm('¿Fusionar estos mods en el servidor real?', `Se aplican ${picks.length} cambio(s) de mods. Antes se guarda una copia de seguridad. Reinicia el servidor real después.`, { confirmLabel: 'Fusionar' }))) return;
        try { const r = await api(url(s, 'staging_merge_mods'), { method: 'POST', body: { picks } }); toast(`${r.merged.length} mods fusionados`, 'ok'); load(); } catch (err) { toast(err.message, 'error'); }
        return;
      }
      const picks = [...e.target.querySelectorAll('input[name=p]:checked')].map((x) => {
        const c = diffData.changes[Number(x.value)];
        return { path: c.path, action: c.kind === 'removed' ? 'delete' : 'copy' };
      });
      if (!picks.length) { toast('Elige al menos un archivo', 'error'); return; }
      if (!(await askConfirm('¿Fusionar estos cambios en el servidor real?', `Se aplican ${picks.length} archivo(s) de configuración. Antes se guarda una copia de seguridad.`, { confirmLabel: 'Fusionar' }))) return;
      try { const r = await api(url(s, 'staging_merge'), { method: 'POST', body: { picks } }); toast(`${r.merged.length} archivos fusionados`, 'ok'); load(); } catch (err) { toast(err.message, 'error'); }
    };
    load();
  }

  // ---------- Bloque «Copias» del riel de estado ----------
  function railCopias(el, s) {
    const { api, esc, isAdmin } = M();
    const block = el.closest('.rail-block');
    if (!isAdmin()) { if (block) block.hidden = true; return; }
    const ago = (ts) => {
      const m = Math.max(1, Math.round((Date.now() / 1000 - ts) / 60));
      return m < 60 ? `hace ${m} min` : m < 2880 ? `hace ${Math.round(m / 60)} h` : `hace ${Math.round(m / 1440)} días`;
    };
    async function load() {
      if (!el.isConnected) return;
      try {
        const d = await api(url(s, 'backups'));
        const last = (d.backups || [])[0];
        const old = last && Date.now() / 1000 - last.created > 7 * 86400;
        const sched = (d.schedules || []).filter((x) => x.enabled !== 0 && x.enabled !== false).length;
        el.innerHTML = `<p class="rail-big rail-copia ${!last || old ? 'warn' : ''}">${last ? esc(ago(last.created)) : 'Sin copias'}</p>
          <p class="rail-sub">${last ? `${Math.round(last.size / 1048576)} MB` : 'Todavía no hay ninguna copia de este servidor.'}${old ? ' · hace más de una semana' : ''}</p>
          <p class="rail-sub">${sched ? `${sched} ${sched === 1 ? 'tarea programada' : 'tareas programadas'}` : 'Sin tareas programadas'} · <a href="#/s/${encodeURIComponent(s.name)}/x-copias">Abrir copias</a></p>`;
      } catch (e) { el.textContent = 'No disponible'; }
    }
    load();
    const t = setInterval(() => { if (!el.isConnected) clearInterval(t); else if (!document.hidden) load(); }, 60000);
  }

  const P = window.ModnexPlugins = window.ModnexPlugins || {};
  P.copias = { render: copias, renderRail: railCopias };
  P.diagnostico = { render: diagnostico };
  P.avisos = { render: avisos };
  P.estadisticas = { render: estadisticas };
  P.rendimiento = { render: rendimiento };
  P.kubejs = { render: kubejsSection };
  P.propuestas = { render: propuestas };
  P.actualizar = { render: actualizar };
  P.pruebas = { render: pruebas };
  P.sincronizacion = { render: sincronizacion };
  P.seguridad = { renderPage: seguridad };
})();
