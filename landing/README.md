# Landing de Modnex

Sitio estático y autónomo que presenta el proyecto. **No forma parte del panel**: el gestor (`app.py`) no la
sirve; en `/` solo redirige al panel (`/app`). Todos sus botones llevan al repositorio de GitHub.

```
landing/
  index.html            la página
  assets/               estilos, script, fuente, logo y capturas (rutas relativas)
```

## Probarla en local

```bash
python3 -m http.server 8000 --directory landing     # http://127.0.0.1:8000
```

## Publicarla

Es HTML, CSS y JavaScript sin paso de compilación: sirve cualquier alojamiento estático. Este repositorio la publica sola
en **https://lu2ky.github.io/modnex/** con GitHub Pages: el flujo `.github/workflows/pages.yml` sube esta carpeta cada vez
que cambia en `main`. Las rutas son relativas para que funcione colgando de `/modnex/`.

## Capturas del panel

`assets/shots/` son capturas del panel. Si el panel cambia mucho, conviene regenerarlas.

## Enlaces

El botón «Ir al proyecto» apunta a `https://github.com/Lu2ky/modnex`. Si el repositorio es privado, quien
llegue desde la landing verá un 404: haz público el repositorio antes de publicar la landing.
