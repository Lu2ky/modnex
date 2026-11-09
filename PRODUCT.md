# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Cualquier persona que quiera alojar servidores de Minecraft con mods en su propio equipo, de forma local. El caso típico es quien administra un servidor para un grupo de amigos: instala mods, decide quién entra y qué puede hacer, y reparte el cliente. Otros perfiles no están confirmados.

## Product Purpose

Modnex es un gestor de servidores de Minecraft con mods que corre en el equipo del usuario. Permite crear servidores desde plantillas (Vanilla, Fabric, NeoForge, Forge, Paper) o desde modpacks, instalar mods y plugins compatibles con la versión del servidor, administrar jugadores, consola, logs y `server.properties`, y generar el cliente que deben usar los jugadores. Éxito: el usuario deja de editar archivos a mano y sus amigos entran con el cliente correcto a la primera.

## Positioning

El cliente sale del propio servidor: mismas versiones de Minecraft y NeoForge, mismos mods del lado servidor y, cuando el servidor viene de un modpack, el cliente original del desarrollador sin cambios. Ningún otro panel general genera ese cliente desde el servidor que administra.

## Operating Context

- Se ejecuta en el equipo del usuario, con Java 21 y un único proceso Python. No depende de un servicio externo para funcionar.
- Acceso desde la red local por HTTP. Para compartir un archivo con alguien de fuera se usa un enlace temporal de Cloudflare Tunnel que se cierra solo.
- Los proveedores son Modrinth (sin clave) y CurseForge (con clave de API propia del usuario).

## Capabilities and Constraints

- Plantillas: Vanilla, Fabric, NeoForge (plena), Forge (parcial, con pocos mods de rendimiento disponibles) y Paper (plugins). Modpacks solo NeoForge.
- Mods y plugins se filtran por loader y versión del servidor; las dependencias obligatorias se instalan en cascada.
- Persistencia en SQLite local. Permisos por usuario y por servidor: logs, mods, datapacks, texturas, jugadores.
- Sin HTTPS: la contraseña viaja sin cifrar en la red local. No se expone a internet por diseño.
- Undecided: arranque automático al encender el equipo (requiere servicio del sistema; no decidido), copias de seguridad (no existen), panel de CPU y RAM (no existe).
- Terminología de la interfaz: español.

## Brand Commitments

- Nombre: **MODNEX** (la marca visible del producto). Logo: la M verde y violeta con el cubo, con el nombre debajo. Es fijo y no se redibuja.
- Paleta obligatoria: fondo `#111318`, superficies `#1B2029`, elevado `#272E3A`, bordes `#3B4655`; primario `#55D68B`, secundario violeta `#A78BFA`, acento cian `#42C6D9`, advertencia `#F0B85A`, error `#F16B72`, desconectado `#87909D`.
- Tipografía en uso: Inter.

## Evidence on Hand

- Logo original: `~/Descargas/f9c4aabb-90dc-4c36-8a1a-62301aa6790d.png` (fuera del repositorio; las versiones sin fondo viven en `static/brand/`).
- Iconos de servidor (20 loaders y plataformas): `static/brand/servers/`.
- No hay testimonios, clientes, casos de uso, benchmarks ni cifras de uso. Ninguna de esas cosas debe inventarse.

## Product Principles

- Local primero: el usuario controla su servidor, sus datos y su equipo.
- El servidor define el cliente: todo lo que se entrega a los jugadores se deriva de lo que corre en el servidor.
- Acceso mínimo: cada persona solo ve y hace lo que se le concedió en cada servidor.
- Las acciones destructivas piden confirmación explícita (borrar un servidor exige escribir su nombre).
- Lo que el producto no hace se dice tal cual; no se prometen copias de seguridad ni paneles que no existen.
