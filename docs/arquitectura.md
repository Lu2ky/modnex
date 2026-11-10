# Arquitectura

Modnex es un servidor HTTP de la biblioteca estándar de Python con SQLite, sin dependencias. El código está en el
paquete `modnex`, organizado en capas con una regla: **las dependencias apuntan hacia dentro** (la web conoce los
servicios, los servicios conocen la infraestructura, y nunca al revés).

```
app.py                  punto de entrada de cuatro líneas
modnex/
  config.py             ajustes: rutas, puerto, config.json
  composition.py        raíz de composición: construye lo que reciben los plugins y arranca el servidor
  plugins.py            API de plugins (docs/plugins.md)
  web/                  capa HTTP
    server.py           manejador fino: cabeceras, cookie, cuerpos, subidas
    router.py           tabla de rutas y control de acceso (@route, @server_action)
    routes/             una unidad por área: pages, auth, catalog, provisioning, admin, extensions, servers
    access.py           política de acceso: de dónde llega cada petición y si un admin puede usar el panel
    errors.py           excepción -> código HTTP, en un único sitio
  services/             lógica de la aplicación, sin saber que existe HTTP
    servers, addons, mods, catalog, deps, identify, detail, markdown, client, datapacks, properties,
    resourcepacks, players, creation, templates, modpacks, release, extras, autofilter
  infra/                adaptadores hacia el exterior
    db.py               SQLite
    net.py              HTTP hacia Modrinth y CurseForge, con circuit breaker
    breaker.py          circuit breaker por proveedor
    processes.py        puerto de procesos + adaptador POSIX
  features/             funciones por servidor, cargadas como plugins (copias, pruebas, seguridad...)
tests/                  unitarias y de extremo a extremo
```

## Patrones aplicados

| Patrón | Dónde | Por qué |
|---|---|---|
| **Raíz de composición** | `composition.py` | Es el único sitio que construye el contexto de los plugins y se lo entrega al servidor. Los servicios no importan desde la web: antes `creation` importaba el contexto de `app.py` y había un ciclo. |
| **Puertos y adaptadores** | `infra/processes.py` | `servers.py` no llama a `bash`, a señales ni a `/proc`: usa `processes.backend` (`spawn`, `is_java_alive`, `terminate`, `usage`). Hay un adaptador POSIX; uno para Windows nativo implementaría los mismos cuatro métodos, y las pruebas usan uno falso. |
| **Circuit breaker** | `infra/breaker.py`, `infra/net.py` | Tras 5 fallos seguidos de red, 5xx o 429, las llamadas a ese proveedor fallan al instante durante 30 s y luego pasa un intento de prueba. Una caída de Modrinth ya no deja esperando 20 s a cada petición. Es un `OSError` con código 503, así que quien ya trataba los fallos de red sigue degradando bien. |
| **Tabla de rutas** | `web/router.py`, `web/routes/` | Cada ruta declara su método, su patrón y quién puede usarla (`public`, `user`, `admin`); cada acción de servidor, su permiso. Quién puede qué se lee de un vistazo, no enterrado en el cuerpo de una cadena de `if`. |
| **Formato de error uniforme** | `web/errors.py` | Los servicios lanzan excepciones normales y nunca eligen un código HTTP; un solo mapa las traduce a `{"error": "..."}`. Quien necesite otro código pone `http_status` en su excepción. |
| **Entrega garantizada** | `features/notify.py` | Un aviso de Discord que falla se guarda en `pro_notify_outbox` y se reintenta con espera creciente (8 intentos, 24 h) en lugar de perderse. |
| **Plugins** | `plugins.py`, `features/` | Cada función (copias, servidor de pruebas, 2FA...) se engancha con `register(api)` sin tocar el núcleo. |

## Cómo añadir cosas

**Un endpoint.** En el módulo de `web/routes/` que corresponda:

```python
@route("GET", r"/api/algo", auth="admin")      # public | user | admin
def algo(req):
    return {"dato": servicio.calcular(req.q["x"])}   # un dict es un 200; lanza ValueError para un 400
```

**Una acción de servidor** (`/api/servers/<nombre>/<acción>`), indicando el permiso:

```python
@server_action("POST", "reiniciar", perm="control")   # None = solo admin; "*" = cualquier permiso del servidor
def reiniciar(req, name, body):
    ...
```

**Una función por servidor (pestaña).** Un módulo nuevo en `features/` con `register(api)`, y lo añades al manifiesto de
`features/__init__.py`. Ver [plugins.md](plugins.md).

**Un servicio nuevo.** En `services/`, sin importar nada de `web/`. Si necesita algo del exterior (red, procesos,
disco compartido), que lo pida a `infra/` o lo reciba como parámetro desde la raíz de composición.

## Pruebas

`tests/test_*.py` son unitarias (sin red); `tests/e2e_*.py` arrancan instancias aisladas con su propio `config.json`
temporal (`MODNEX_CONFIG`), su base de datos y su carpeta de servidores. Ver el [README](../README.md#contribuir).
