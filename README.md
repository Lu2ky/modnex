# Modnex

Gestor de servidores de Minecraft con mods que corre en tu propio equipo. Crea servidores desde
plantillas o modpacks, instala mods y plugins compatibles con su versión, administra jugadores,
consola, registros y `server.properties`, y genera el cliente que deben usar tus jugadores a partir
del propio servidor.

Solo usa la biblioteca estándar de Python (`http.server` + SQLite). No hay que instalar dependencias.

> Estado: proyecto personal en desarrollo, todo bajo licencia libre (AGPL-3.0, ver [LICENSING.md](LICENSING.md)).
> [PRODUCT.md](PRODUCT.md) y [DESIGN.md](DESIGN.md) explican el producto y el diseño; la carpeta [docs/](docs/) trae la guía
> de instalación, el detalle de cada función, la arquitectura, la API HTTP y la API de plugins.

## Qué hace

- **Servidores:** plantillas Vanilla, Fabric, NeoForge, Forge y Paper, o desde un modpack de
  Modrinth o CurseForge. Arranque, parada, consola, registros y memoria.
- **Mods, plugins y datapacks:** búsqueda con páginas y filtro por etiqueta (Modrinth), instalación con
  dependencias, marca «Instalado» en lo que ya tiene el servidor, comprobación de compatibilidad con la versión
  del servidor y filtro automático de mods que solo sirven en el cliente. Los administradores también pueden subir
  mods o plugins propios (`.jar`), que se validan contra el cargador del servidor.
- **Jugadores:** lista blanca, operadores, expulsiones, bloqueos y mensajes.
- **Extras al crear un servidor:** AutoModpack, para que los jugadores reciban los mods al entrar, y el perfilador
  spark. Son opcionales y vienen desmarcados; el cliente generado lleva siempre AutoModpack.
- **Cliente:** genera un modpack (`.mrpack` o `.zip`) con los mods que los jugadores necesitan y lo
  reparte con un enlace de descarga temporal.
- **Usuarios y permisos por servidor:** logs, mods, datapacks, texturas, jugadores, control
  (encender/apagar) y auditoría de actividad.
- **Panel:** secciones agrupadas (Operar, Contenido, Distribuir, Proteger), riel de estado en vivo a la derecha
  (estado, jugadores, memoria, avisos y errores, disco) y listas con ficha lateral en mods y usuarios.
- **Landing aparte** (`landing/`): sitio estático que presenta el proyecto; no forma parte del panel (ver su
  [README](landing/README.md)). En `/` el gestor solo redirige al panel.

Además, cada servidor tiene estas pestañas (detalle en [docs/funciones.md](docs/funciones.md)):

- **Copias de seguridad** con historial en árbol (ramas al restaurar), tareas programadas y reglas de ciclo de vida.
- **Actualizar mods** de forma segura: prueba las actualizaciones en un entorno aislado y aplica solo las que arrancan.
- **Servidor de pruebas** hijo, con sus propios mods, que se fusiona con el real.
- **Sincronización** de clientes con AutoModpack, probada en una copia aislada.
- **Diagnóstico** de crashes, **avisos** a Discord, **estadísticas** de jugadores y **propuestas** de mods.
- **Seguridad:** verificación en dos pasos con código QR y acceso remoto por túnel (Cloudflare o ngrok) para usuarios
  que no son administradores.

## Instalación

Modnex corre en tu propio equipo y se usa desde el navegador. No instala dependencias: usa solo la biblioteca
estándar de Python y SQLite.

**Necesitas**

- Python 3.12 o superior (probado con 3.12, 3.13 y 3.14): `python3 --version`.
- Java para los servidores: 21 para Minecraft 1.20.5 o posterior, 17 de 1.18 a 1.20.4. Compruébalo con `java -version`. Si hay un Java en
  `.runtime/java21` dentro de la carpeta de los servidores, el gestor usa ese.
- Git, solo para descargar el proyecto (también sirve el `.zip` de GitHub).

**1. Descargar**

```bash
git clone https://github.com/Lu2ky/modnex.git
cd modnex
```

**2. Elegir dónde viven los servidores (opcional).** Cada subcarpeta con `start.sh`, `run.sh` o `mods/` es un servidor.
Por defecto es `servers/` junto al proyecto, que se crea sola. Para usar otra carpeta, por ejemplo una donde ya tienes
servidores:

```bash
export SERVERS_DIR=~/minecraft-servers     # o "servers_dir" en config.json; añádelo a ~/.bashrc para no repetirlo
```

**3. Arrancar**

```bash
./run.sh                                   # panel en http://127.0.0.1:8765/app
```

En el primer arranque se crea `config.json` con un `access_token` aleatorio y un administrador `admin` cuya contraseña
inicial es ese token (`grep access_token config.json`). Entra con él y cámbiala desde «Usuarios y permisos».

> El gestor escucha por defecto en todas las interfaces (`0.0.0.0`), así que cualquiera en tu red
> local puede ver la pantalla de acceso. Para dejarlo solo en tu equipo: `MANAGER_BIND=127.0.0.1 ./run.sh`.

**4. Crear tu primer servidor.** En la barra lateral pulsa **+ Nuevo servidor**, elige una plantilla o un modpack,
indica nombre, versión, memoria y puerto, y marca que aceptas el EULA de Minecraft. Cuando termine, ábrelo y pulsa
**Arrancar**. Los jugadores se conectan a la IP de tu equipo y al puerto elegido; si juegan desde fuera de tu red,
abre ese puerto en tu router.

**Dejarlo en marcha:** `setsid nohup ./run.sh > manager.log 2>&1 &`. **Actualizar:** `git pull` y reinicia el gestor
(los cambios de `app.py` no se aplican hasta reiniciar; tus servidores y datos no se tocan).

**Si algo falla:** el servidor no arranca → pestaña **Logs** (lo más común es una versión de Java que no corresponde);
no ves tus servidores → `SERVERS_DIR` apunta a otra carpeta (el arranque imprime cuál usa); el puerto 8765 está
ocupado → `MANAGER_PORT=8800 ./run.sh`.

La guía completa, con la configuración opcional y cómo recuperar el acceso de administrador, está en
[docs/instalacion.md](docs/instalacion.md).

## Configuración

`config.json` (no se versiona; contiene secretos):

| Clave | Para qué sirve |
|---|---|
| `access_token` | Contraseña inicial del administrador. Se genera sola. |
| `curseforge_api_key` | Opcional. Activa la búsqueda y descarga de CurseForge. |
| `bind` | Dirección en la que escucha. Por defecto `0.0.0.0`. |
| `admin_remote` | Con `true`, los administradores también pueden entrar desde fuera de la red local. No recomendado. |
| `servers_dir` | Carpeta de los servidores (ver abajo). |
| `backup_dir`, `sandbox_dir` | Dónde se guardan las copias y los entornos de prueba. |
| `remote_2fa` | Con `false`, los usuarios no necesitan 2FA para entrar por el túnel. |
| `cloudflared_path`, `ngrok_path` | Rutas de los túneles, si no están en `bin/` o en el `PATH`. |

Variables de entorno (tienen prioridad sobre `config.json`):

| Variable | Valor por defecto |
|---|---|
| `SERVERS_DIR` | Carpeta de los servidores. Por defecto, `servers/` junto al proyecto (se crea sola); también se puede fijar con `servers_dir` en `config.json`. |
| `MANAGER_PORT` | `8765` |
| `MANAGER_BIND` | `0.0.0.0` |
| `MANAGER_DB` | `manager.db` junto a `app.py` |
| `CURSEFORGE_API_KEY` | vacía |
| `MODNEX_CONFIG` | Ruta del `config.json` (por defecto, junto a `app.py`) |
| `MODNEX_BACKUP_DIR`, `MODNEX_CLOUDFLARED`, `MODNEX_NGROK` | Sustituyen a `backup_dir`, `cloudflared_path` y `ngrok_path` |

El panel está en `http://127.0.0.1:8765/app` (la raíz `/` redirige ahí).

Cada subcarpeta de `SERVERS_DIR` con `start.sh`, `run.sh` o `mods/` es un servidor. Una subcarpeta con
`"parent": "<otro-servidor>"` en su `.manager.json` se muestra como hijo de ese servidor en el panel.

## Estructura

El código vive en el paquete `modnex`, en capas (web → servicios → infraestructura). Resumen; la explicación completa y
los patrones de diseño aplicados están en [docs/arquitectura.md](docs/arquitectura.md).

| Ruta | Responsabilidad |
|---|---|
| `app.py` | Punto de entrada (`python3 app.py`). |
| `modnex/web/` | Capa HTTP: manejador, tabla de rutas (`router.py`, `routes/`), política de acceso y errores. |
| `modnex/services/` | Lógica de la aplicación: servidores, mods, catálogo, cliente, plantillas, modpacks, releases... |
| `modnex/infra/` | Adaptadores: SQLite, HTTP con circuit breaker, procesos. |
| `modnex/features/` | Funciones por servidor (copias, servidor de pruebas, seguridad...), cargadas como plugins ([docs/plugins.md](docs/plugins.md)). |
| `modnex/composition.py` | Raíz de composición: lo que reciben los plugins y el arranque. |
| `static/` | Panel (`index.html`, `app.js`, `style.css`). |
| `landing/` | Landing pública: sitio estático autónomo, separado del panel. |
| `tests/` | Pruebas unitarias y de extremo a extremo. |
| `docs/` | Instalación, funciones, arquitectura, API HTTP y API de plugins. |
| `tools/` | Utilidades de desarrollo (generador de iconos de servidor). |

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
  [docs/funciones.md](docs/funciones.md); la clave es `admin_remote` en `config.json`.

## Datos que genera

`config.json`, `manager.db`, `manager.log`, `servers/`, `releases/` (clientes generados), `backups/`, `sandbox/` y
`bin/` (binarios descargados). Todos están en `.gitignore`.

## Contribuir

- `main` está protegida: no se sube directamente. Cada cambio va en su propia rama (`feat/…` o `fix/…`) y entra
  por un pull request; un cambio por rama y un commit por cambio, con un mensaje que diga qué cambia, por qué y
  cómo se verificó.
- Pruebas: `python3 -I -m unittest discover -s tests` (unitarias, sin red) y los `tests/e2e_*.py` (extremo a extremo
  sobre instancias aisladas; `e2e_ui.py` necesita Playwright). Ejecútalas antes de abrir el pull request.
- El panel no admite estilos ni scripts en línea (política de seguridad de contenido): usa clases CSS y archivos.
- No incluyas secretos (`config.json`, claves de API, tokens).

## Licencia

GNU AGPL-3.0 ([LICENSE](LICENSE)). Mira [LICENSING.md](LICENSING.md) para los componentes de terceros.
