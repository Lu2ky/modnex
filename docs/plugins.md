# API de plugins

El núcleo no contiene código de Pro ni depende de él. `plugins.py` carga de forma opcional un
paquete Python con una función `register(api)` y le ofrece la API de abajo. Si el paquete no existe,
o falla al cargarse, el núcleo sigue funcionando como edición gratuita (`GET /api/plugins` devuelve
`edition: "free"` y el motivo del fallo en `error`).

## Cargar un plugin

El paquete se busca en `MODNEX_PRO_PATH` o en `pro_path` de `config.json`. Debe poder importarse como
`modnex_pro` y exponer:

```python
def register(api):
    ...
```

## `api` (PluginAPI)

| Método | Para qué |
|---|---|
| `route(method, action)` | Ruta por servidor: `/api/servers/<nombre>/<acción>`. La función recibe `(ctx, user, servidor, q, body)` y devuelve `(status, dict)`. |
| `global_route(method, action)` | Ruta que no es de un servidor: `/api/pro/<acción>`. Exige sesión; la autorización la decide el plugin. Recibe `(ctx, user, q, body)`. |
| `tab(id, label, admin=True, perm=None, group=None)` | Pestaña en la página de un servidor. `perm` es el permiso por servidor que basta para verla; `"*"` significa cualquiera. `group` la coloca en una sección del panel: `operar`, `contenido`, `distribuir` o `proteger` (sin grupo va a «Más»). |
| `rail(id, label)` | Bloque en el riel de estado de la derecha de cada servidor. La interfaz llama a `ModnexPlugins[id].renderRail(el, server)`. |
| `page(id, label, admin=False)` | Entrada en la barra lateral (`#/p/<id>`). La interfaz llama a `ModnexPlugins[id].renderPage(el)`. |
| `add_schema(sql)` | Tablas propias del plugin, creadas al cargarse. |
| `on(event)` | Se suscribe a un evento (ver abajo). |
| `asset(nombre, ruta, mime, script=False)` | Archivo estático servido en `/plugin/<nombre>`. Con `script=True` el panel lo carga. |
| `second_factor(fn)` | Comprobación extra tras acertar la contraseña. Recibe `(ctx, user, body, remote, ip)`; `None` deja pasar y `(status, dict[, contar_fallo])` rechaza. |
| `client_include(fn)` | Mods que el cliente generado debe llevar siempre. Recibe `(ctx, name, rows)` y devuelve nombres de archivo. |

Las rutas de servidor solo se despachan para servidores que el usuario puede ver. Las rutas globales
reciben `user=None` si no hay sesión; compruébalo.

## Datos en vivo del núcleo

`GET /api/servers/<nombre>/metrics` devuelve, para quien tenga algún permiso en ese servidor, el estado en vivo que pinta el riel:
`running`, `uptime_s`, `rss_mb`, `players` (según el registro, sin enviar comandos a la consola), `max_players`,
`warn` y `error` (recuento en las últimas líneas) y `disk_free_gb`.

## Eventos

| Evento | Argumentos | Cuándo |
|---|---|---|
| `server_started` | `name` | El servidor arrancó. |
| `server_stopped` | `name, motivo` | Parada normal o pedida por un usuario. |
| `server_crashed` | `name, motivo` | Cayó o falló al arrancar. |
| `server_created` | `name` | Se terminó de crear un servidor (plantilla o modpack). |

Cada manejador corre en su propio hilo y sus errores no llegan al núcleo.

## `ctx`: lo que el núcleo ofrece

`here`, `servers_dir`, `port`, `server_path(name)`, `status(name)`, `start`, `stop`,
`send_command`, `read_log`, `audit(user, servidor, acción, detalle)`, `can(user, servidor, permiso)`,
`db_run(sql, args, one=, many=)`, `db_connect()`, `config()`, `list_servers()`, `search`,
`compat_for`, `server_versions(name)`, `user_perms`, `identify_mods(name, loader, mc)`,
`java_bin()`, `download(url, destino, sha1=)`.

## Reglas para plugins

- **Falla cerrado en seguridad.** Si un `second_factor` lanza una excepción, el login se rechaza.
- **Falla abierto en lo demás.** Un `client_include` roto no impide generar el cliente.
- **Sin estilos ni scripts en línea.** La política de seguridad de contenido bloquea `style=` y
  `<script>` incrustados: usa clases CSS y archivos servidos con `asset`.
- **Interfaz.** El script del plugin registra `window.ModnexPlugins[<id de pestaña>] = { render(el, server) }`
  y puede usar `window.Modnex` (`api`, `esc`, `$`, `toast`, `askConfirm`, `isAdmin`, `current`, `state`).
- **Servidores hijo.** Un plugin puede crear servidores hijo escribiendo `"parent": "<padre>"` en el
  `.manager.json` del hijo; el panel los anida bajo su padre.

## Sin garantías de estabilidad

La API es pequeña pero todavía puede cambiar. Los nombres de este documento reflejan `plugins.py`.
