// Se carga en <head> para fijar el tema antes de pintar y evitar un parpadeo.
(function () {
  var t = null;
  try { t = localStorage.getItem('theme'); } catch (e) { /* sin almacenamiento */ }
  if (t !== 'light' && t !== 'dark') {
    t = window.matchMedia && matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }
  document.documentElement.dataset.theme = t;
})();
