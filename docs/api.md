# API HTTP del gestor

El panel (`static/app.js`) usa esta API; también sirve para automatizar. Todo va en JSON salvo las subidas de
archivos y las descargas. No hay compatibilidad garantizada entre versiones.

## Acceso

- **Sesión:** `POST /api/login` con `{"username", "password"}` devuelve una cookie `HttpOnly` y `SameSite=Strict`
  (con `Secure` si se entra por HTTPS a través de un túnel). Con la verificación en dos pasos de Pro activada, se
  añade `"otp"`; si falta, la respuesta es `401` con `need_otp: true`.
- **Origen:** las peticiones con cabecera `Origin` de otro sitio se rechazan (`403`).
- **Bloqueo:** 5 intentos fallidos de inicio de sesión desde una IP bloquean ese origen 5 minutos.
- **Administradores:** solo pueden usar el panel desde el propio equipo o la red local (ver README, `admin_remote`).
- **Errores:** `{"error": "mensaje"}` con `400` (datos no válidos), `401` (sin sesión), `403` (sin permiso),
  `404` (no existe) o `429` (demasiados intentos).
- **Permisos por servidor:** `logs`, `mods`, `datapacks`, `textures`, `players` y `control` (encender y apagar).
  «Admin» significa solo administradores; «alguno» significa cualquier permiso en ese servidor.

## Sesión y cuenta

| Método y ruta | Quién | Qué hace |
|---|---|---|
| `POST /api/login` | público | Inicia sesión. |
| `POST /api/logout` | sesión | La cierra. |
| `GET /api/me` | sesión | Usuario actual y lista de iconos de servidor. |
| `POST /api/me/password` | sesión | Cambia la contraseña propia (`old`, `new`); cierra las demás sesiones. |
| `GET /api/plugins` | sesión | Edición (`free`/`pro`), pestañas, páginas, bloques de riel y scripts de los plugins. |

## Servidores

| Método y ruta | Permiso | Qué hace |
|---|---|---|
| `GET /api/servers` | sesión | Los servidores que el usuario puede ver, con su estado y permisos. |
| `POST /api/servers/create` | admin | Crea un servidor desde una plantilla (trabajo en segundo plano). |
| `POST /api/servers/create_modpack` | admin | Crea un servidor desde un modpack de Modrinth o CurseForge. |
| `GET /api/jobs/<id>` | admin | Progreso de un trabajo de creación. |
| `GET /api/templates` · `GET /api/templates/versions` | admin | Plantillas y sus versiones. |
| `GET /api/modpacks/search` · `GET /api/modpacks/versions` | admin | Busca modpacks y lista sus versiones. |

### Acciones de un servidor: `/api/servers/<nombre>/<acción>`

`GET`:

| Acción | Permiso | Devuelve |
|---|---|---|
| `metrics` | alguno | Estado en vivo: `running`, `uptime_s`, `rss_mb`, `players` (según el registro, sin enviar comandos), `max_players`, `warn`, `error`, `disk_free_gb`. |
| `log` | `logs` | Últimas líneas (`?lines=`, máximo 2000). |
| `mods` | `mods` | Mods instalados identificados por proveedor (tarda: consulta a Modrinth y CurseForge). |
| `installed` | `mods` | Índice de lo instalado (`projects`, `versions`), con caché de 60 s. |
| `datapacks` | `datapacks` | Datapacks del mundo. |
| `resourcepack` | `textures` | Texturas activas y locales. |
| `players` | `players` | Jugadores conocidos, conectados, operadores, whitelist y bloqueos. |
| `properties` · `client_plan` · `releases` | admin | `server.properties`, plan del cliente y clientes generados. |

`POST`:

| Acción | Permiso | Qué hace |
|---|---|---|
| `start` · `stop` | `control` | Arranca o para el servidor. |
| `command` · `memory` · `meta` · `properties` · `delete` | admin | Consola, memoria, nombre e icono, propiedades, borrado. |
| `mod_toggle` · `mod_delete` · `mod_update` | `mods` | Activa o desactiva, borra o actualiza un mod. |
| `datapack_upload` · `datapack_delete` | `datapacks` | Sube o borra un datapack. |
| `resourcepack_upload` · `resourcepack_set` · `resourcepack_use` · `resourcepack_delete` | `textures` | Gestiona las texturas. |
| `player` | `players` | Acción sobre un jugador (mensaje, expulsar, banear, OP, whitelist). |
| `client_build` · `release_upload` · `release_delete` · `release_share` | admin | Genera, sube, borra o comparte un cliente. |

## Buscar e instalar

| Método y ruta | Permiso | Qué hace |
|---|---|---|
| `GET /api/search` | alguno (según el tipo) | Busca contenido. Con `page` devuelve `{items, total, page, pages, per_page}`; sin `page`, solo la lista. Parámetros: `source` (`modrinth`/`curseforge`), `q`, `kind` (`mod`, `plugin`, `datapack`, `resourcepack`), `sort`, `side`, `loader`, `version`, `server`, `tags` (etiquetas separadas por comas; solo Modrinth, se combinan con «y»). |
| `GET /api/tags` | alguno (según el tipo) | Etiquetas de Modrinth para un tipo (`?kind=`), con su nombre en español. |
| `GET /api/files` | alguno | Versiones descargables de un proyecto. |
| `GET /api/mod` | `mods` | Ficha de un mod. |
| `GET /api/deps` | `mods` | Dependencias que faltan para instalar una versión. |
| `POST /api/install` · `POST /api/install_many` | `mods` o `datapacks` | Instala un archivo, o varios con sus dependencias. Solo se descarga de hosts permitidos y se comprueba el hash. |

## Administración

| Método y ruta | Quién | Qué hace |
|---|---|---|
| `GET /api/users` · `POST /api/users` | admin | Lista y crea usuarios. |
| `POST /api/users/<id>/update` · `/delete` · `/permissions` | admin | Cambia, borra o fija los permisos de un usuario. |
| `GET /api/audit` | admin | Registro de actividad (`?limit=`). |
| `GET /api/share` · `POST /api/share_stop` | admin | Enlace temporal de descarga del cliente. |
| `GET /api/waitlist` · `POST /api/waitlist` | admin / público | Lista de espera de Pro. El `POST` es público y limita 5 envíos por hora y origen. |

## Plugins

Las rutas que añade un plugin cuelgan de `/api/servers/<nombre>/<acción>` o de `/api/pro/<acción>`. Ver
[plugins.md](plugins.md).
