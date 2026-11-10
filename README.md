# Modnex

Gestor de servidores de Minecraft con mods que corre en tu propio equipo. Crea servidores desde
plantillas o modpacks, instala mods y plugins compatibles con su versión, administra jugadores,
consola, registros y `server.properties`, y genera el cliente que deben usar tus jugadores a partir
del propio servidor.

Solo usa la biblioteca estándar de Python (`http.server` + SQLite). No hay que instalar dependencias.

> Estado: uso personal y en desarrollo. Mira [LICENSING.md](LICENSING.md) para saber qué es libre y
> qué es de pago, [PRODUCT.md](PRODUCT.md) / [DESIGN.md](DESIGN.md) para el producto y el diseño, y la carpeta
> [docs/](docs/) para la API HTTP y la API de plugins.

## Qué hace (edición gratuita)

- **Servidores:** plantillas Vanilla, Fabric, NeoForge, Forge y Paper, o desde un modpack de
  Modrinth o CurseForge. Arranque, parada, consola, registros y memoria.
- **Mods, plugins y datapacks:** búsqueda con páginas y filtro por etiqueta (Modrinth), instalación con
  dependencias, marca «Instalado» en lo que ya tiene el servidor, comprobación de compatibilidad con la versión
  del servidor y filtro automático de mods que solo sirven en el cliente.
- **Jugadores:** lista blanca, operadores, expulsiones, bloqueos y mensajes.
- **Cliente:** genera un modpack (`.mrpack` o `.zip`) con los mods que los jugadores necesitan y lo
  reparte con un enlace de descarga temporal.
- **Usuarios y permisos por servidor:** logs, mods, datapacks, texturas, jugadores, control
  (encender/apagar) y auditoría de actividad.
- **Panel:** secciones agrupadas (Operar, Contenido, Distribuir, Proteger), riel de estado en vivo a la derecha
  (estado, jugadores, memoria, avisos y errores, disco) y listas con ficha lateral en mods y usuarios.
- **Landing aparte** (`landing/`): sitio estático que presenta el proyecto; no forma parte del panel (ver su
  [README](landing/README.md)). En `/` el gestor solo redirige al panel.

La edición **Pro** añade copias de seguridad, tareas programadas, actualización segura de mods,
servidor de pruebas, sincronización de clientes, 2FA y acceso remoto. Vive en otro repositorio
(`modnex-pro`) y se carga como plugin; sin él, todo lo anterior funciona igual.

## Arrancar

Requisitos: Python 3 reciente (probado con 3.14) y Java para los servidores. Si existe un Java en `.runtime/java21` dentro de `SERVERS_DIR`, el gestor usa ese; si no, el `java` del sistema.

```bash
cp config.example.json config.json     # opcional; se crea sola al primer arranque
./run.sh                               # http://127.0.0.1:8765
```

En el primer arranque se crea `config.json` con un `access_token` aleatorio y un administrador
`admin` cuya contraseña inicial es ese token. Entra con él y cámbiala desde "Usuarios y permisos".

> El gestor escucha por defecto en todas las interfaces (`0.0.0.0`), así que cualquiera en tu red
> local puede ver la pantalla de acceso. Para dejarlo solo en tu equipo: `MANAGER_BIND=127.0.0.1 ./run.sh`.

## Configuración

`config.json` (no se versiona; contiene secretos):

| Clave | Para qué sirve |
|---|---|
| `access_token` | Contraseña inicial del administrador. Se genera sola. |
| `curseforge_api_key` | Opcional. Activa la búsqueda y descarga de CurseForge. |
| `bind` | Dirección en la que escucha. Por defecto `0.0.0.0`. |
| `admin_remote` | Con `true`, los administradores también pueden entrar desde fuera de la red local. No recomendado. |
| `pro_path`, `pro_dev` | Ruta del paquete Pro y activación de desarrollo (ver [LICENSING.md](LICENSING.md)). |

Variables de entorno (tienen prioridad sobre `config.json`):

| Variable | Valor por defecto |
|---|---|
| `SERVERS_DIR` | `/home/luky/servers`: carpeta donde viven los servidores. |
| `MANAGER_PORT` | `8765` |
| `MANAGER_BIND` | `0.0.0.0` |
| `MANAGER_DB` | `manager.db` junto a `app.py` |
| `CURSEFORGE_API_KEY` | vacía |
| `MODNEX_PRO_PATH` | ruta del paquete Pro, si lo usas |

El panel está en `http://127.0.0.1:8765/app` (la raíz `/` redirige ahí).

Cada subcarpeta de `SERVERS_DIR` con `start.sh`, `run.sh` o `mods/` es un servidor. Una subcarpeta con
`"parent": "<otro-servidor>"` en su `.manager.json` se muestra como hijo de ese servidor en el panel.

## Estructura

| Archivo | Responsabilidad |
|---|---|
| `app.py` | Servidor HTTP, rutas, arranque de servidores, mods, cliente y plugins. |
| `db.py` | SQLite: usuarios, sesiones, permisos, auditoría y lista de espera. |
| `templates.py` | Plantillas de servidor (Vanilla, Fabric, NeoForge, Forge, Paper) y Java. |
| `modpacks.py` | Importación de modpacks de Modrinth y CurseForge. |
| `release.py` | Enlace de descarga temporal del cliente. |
| `autofilter.py` | Detección de mods que solo funcionan en el cliente. |
| `plugins.py` | Carga opcional de plugins ([docs/plugins.md](docs/plugins.md)). |
| `static/` | Panel (`index.html`, `app.js`, `style.css`) y landing. |
| `landing/` | Landing pública: sitio estático autónomo, separado del panel. |
| `docs/` | Documentación: [API HTTP](docs/api.md) y [API de plugins](docs/plugins.md). |
| `tools/make_scene.py` | Genera la ilustración de la landing. |

## Seguridad

- Contraseñas con hash y sal; sesión en cookie `HttpOnly` y `SameSite=Strict` (más `Secure` si se
  entra por HTTPS a través de un túnel).
- Bloqueo tras 5 intentos fallidos desde una misma IP durante 5 minutos.
- Política de seguridad de contenido estricta (`script-src 'self'`, `style-src 'self'`): el panel no
  admite scripts ni estilos en línea.
- Los nombres de servidor y de archivo se validan con listas permitidas; las descargas de mods solo
  salen a hosts conocidos y se comprueban por hash.
- Los permisos se aplican en el servidor, no solo en la interfaz.
- **Los administradores solo entran desde este equipo o la red local.** El núcleo lo comprueba en cada
  petición (login y sesión), también si la petición llega por un túnel. Detalles y cómo relajarlo en
  la documentación de Pro; la clave es `admin_remote` en `config.json`.

## Datos que genera

`config.json`, `manager.db`, `manager.log`, `releases/` (clientes generados), `backups/` y `sandbox/`
(solo con Pro), `bin/` (binarios descargados). Todos están en `.gitignore`.

## Contribuir

- `main` está protegida: no se sube directamente. Cada cambio va en su propia rama (`feat/…` o `fix/…`) y entra
  por un pull request; un cambio por rama y un commit por cambio, con un mensaje que diga qué cambia, por qué y
  cómo se verificó.
- Este repositorio **todavía no incluye pruebas automáticas**: las del gestor (unitarias, de API y de navegador)
  viven hoy en el repositorio de Pro, que es privado. Hasta que se publiquen, verifica a mano lo que toques y
  describe en el pull request cómo lo comprobaste.
- El panel no admite estilos ni scripts en línea (política de seguridad de contenido): usa clases CSS y archivos.
- No incluyas secretos (`config.json`, claves de API, tokens).

## Licencia

Núcleo bajo GNU AGPL-3.0 ([LICENSE](LICENSE)). El paquete Pro es propietario.
