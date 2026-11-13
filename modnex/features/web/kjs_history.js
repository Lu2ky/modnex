// KubeJS · Historial: cada guardado del panel deja antes una versión de lo que gestiona; aquí se ve y se puede volver a cualquiera.
(function () {
  const M = () => window.Modnex;
  function ago(ts) {
    const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
    if (s < 60) return 'hace un momento';
    if (s < 3600) return `hace ${Math.round(s / 60)} min`;
    if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
    return new Date(ts * 1000).toLocaleString('es', { dateStyle: 'medium', timeStyle: 'short' });
  }
  const NICE = (f) => f.replace(/^modnex\//, '').replace(/^(server|client|startup)_scripts\//, '$1 · ').replace(/^data\/[^/]+\/loot_tables?\//, 'botín · ');

  function view(el, s) {
    const { api, esc, toast, askConfirm } = M();
    const base = `/api/servers/${encodeURIComponent(s.name)}`;
    let list = [], busy = false;
    function draw() {
      el.innerHTML = `<div class="ft-head"><h2>Historial</h2><span class="muted small">${list.length} ${list.length === 1 ? 'versión' : 'versiones'}</span></div>
        <p class="muted small">Antes de cada cambio que haces en recetas, reglas, Create o botín se guarda cómo estaba todo. Restaurar una versión deshace ese cambio; antes de restaurar se guarda el estado actual, así que también se puede deshacer. Se aplica con <code>/reload</code>. Los scripts que escribes a mano no se tocan.</p>
        ${list.length ? `<ul class="kjs-hist">${list.map((v) => `<li class="kjs-hist-row ${v.same ? 'same' : ''}">
          <div><strong>${esc(v.label || 'Versión')}</strong><span class="muted small block">${esc(ago(v.ts))}${v.user ? ` · ${esc(v.user)}` : ''} · ${v.files ? `${v.files} ${v.files === 1 ? 'archivo' : 'archivos'}` : 'sin nada del panel todavía'}</span>
            ${v.same ? '<span class="muted small block">Igual que ahora.</span>'
              : `<span class="small block">Al restaurar: ${v.changes.map((c) => `${esc(NICE(c.file))} (${esc(c.status)})`).join(', ')}${v.change_count > v.changes.length ? ` y ${v.change_count - v.changes.length} más` : ''}</span>`}</div>
          <button type="button" class="btn sm" data-restore="${esc(v.id)}" ${v.same || busy ? 'disabled' : ''}>Restaurar</button></li>`).join('')}</ul>`
          : '<p class="muted">Todavía no hay versiones. Aparecen solas la próxima vez que guardes algo.</p>'}`;
    }
    el.onclick = async (e) => {
      const b = e.target.closest('[data-restore]'); if (!b || b.disabled) return;
      const v = list.find((x) => x.id === b.dataset.restore); if (!v) return;
      if (!(await askConfirm('¿Restaurar esta versión?', `Vuelven los archivos del panel a como estaban «${v.label || 'antes'}» (${ago(v.ts)}). Antes se guarda el estado actual. Después hay que hacer /reload.`, { confirmLabel: 'Restaurar' }))) return;
      busy = true; draw();
      try { const r = await api(`${base}/kubejs_history_restore`, { method: 'POST', body: { id: v.id } }); list = r.versions; toast('Restaurado. Aplícalo con /reload.', 'success'); }
      catch (err) { toast(err.message, 'error'); }
      busy = false; draw();
    };
    el.innerHTML = '<p class="muted">Cargando…</p>';
    api(`${base}/kubejs_history`).then((r) => { list = r.versions; draw(); }).catch((e) => { el.innerHTML = `<p class="muted">${esc(e.message)}</p>`; });
  }
  window.ModnexKjsHistory = { view };
})();
