// Se carga en <head> para fijar el tema antes de pintar y evitar un parpadeo.
(function () {
  var t = null;
  try { t = localStorage.getItem('theme'); } catch (e) { /* sin almacenamiento */ }
  if (t !== 'light' && t !== 'dark') {
    t = 'dark';  // identidad: sala de control oscura; el claro solo si el usuario lo elige
  }
  document.documentElement.dataset.theme = t;
})();
