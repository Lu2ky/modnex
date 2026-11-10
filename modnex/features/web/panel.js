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
  P.propuestas = { render: propuestas };
  P.actualizar = { render: actualizar };
  P.pruebas = { render: pruebas };
  P.sincronizacion = { render: sincronizacion };
  P.seguridad = { renderPage: seguridad };
})();
