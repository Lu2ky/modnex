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

Es HTML, CSS y JavaScript sin paso de compilación: sirve cualquier alojamiento estático (GitHub Pages, Vercel,
Netlify, un bucket…). Sube el contenido de esta carpeta tal cual.

## Lista de espera de Pro

La landing es estática, así que no puede guardar correos por sí sola. El formulario **está oculto** salvo que
indiques un servidor que los reciba, en `index.html`:

```html
<meta name="modnex-waitlist" content="https://tu-servidor/api/waitlist">
```

El servidor debe aceptar `POST` con `{"email": "…"}` y permitir el origen de la landing (CORS). El gestor de
Modnex trae un endpoint así (`/api/waitlist`), pero solo escucha en tu equipo y no envía cabeceras CORS: para
usarlo desde una landing publicada habría que exponerlo y permitir su origen, lo que hoy no está hecho.

## Capturas del panel

`assets/shots/` son capturas del panel. Si el panel cambia mucho, conviene regenerarlas.

## Enlaces

El botón «Ir al proyecto» apunta a `https://github.com/Lu2ky/modnex`. Si el repositorio es privado, quien
llegue desde la landing verá un 404: haz público el repositorio antes de publicar la landing.
