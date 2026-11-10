# Funciones por servidor

En el panel, las pestañas de cada servidor se agrupan en cuatro secciones: **Operar** (resumen, consola, jugadores,
propiedades, ajustes, estadísticas), **Contenido** (mods, datapacks, texturas, actualizar mods, propuestas),
**Distribuir** (cliente, sincronización) y **Proteger** (copias, servidor de pruebas, diagnóstico, avisos).
A la derecha hay un riel de estado; incluye un bloque con la última copia de seguridad.

Las rutas por servidor cuelgan de `/api/servers/<nombre>/<acción>`; las globales, de `/api/features/<acción>`.
Todo requiere sesión. Salvo donde se indica, es solo para administradores.

## Copias de seguridad y tareas programadas — pestaña Copias

- Copia completa en `tar.gz` con sus metadatos; excluye registros, cachés y bibliotecas regenerables.
- Con el servidor en marcha, la copia "en caliente" desactiva el guardado, fuerza `save-all flush`
  y lo vuelve a activar. Si no hay consola disponible, se rechaza salvo que se fuerce.
- Restaurar exige el servidor parado y hace antes una copia de seguridad automática.
- Tareas programadas: copia o reinicio a una hora (`HH:MM`), una vez al día, con avisos 5 y 1 minuto antes.
- Rutas: `backups`, `backup_create`, `backup_restore`, `backup_delete`, `backup_diff`, `backup_pin`,
  `schedule_add`, `schedule_remove`, `schedule_toggle`, `retention_preview`, `retention_set`, `retention_apply`.
- Las copias están en `backups/<servidor>/` (o `backup_dir`).

### Árbol de versiones

El historial de la pestaña Copias se dibuja como un árbol, al estilo de `git log --graph`: cada punto es una
copia y la línea lo une con la copia de la que partía. Lo más reciente va arriba y **Estás aquí** marca la copia
de la que desciende el estado actual del servidor.

- Copiar encadena: la copia nueva cuelga de la anterior.
- **Restaurar una copia antigua mueve «Estás aquí» a ella.** Lo que copies después cuelga de esa copia, así que
  el historial se bifurca y la rama que dejaste atrás sigue visible (con su copia «Antes de restaurar»).
- Las copias anteriores a esta función no guardaban de quién partían: se encadenan por fecha.
- **Borrar una copia no borra su sitio en el árbol.** Se elimina el archivo (y su espacio), pero la copia queda como una
  lápida atenuada con la marca «Borrada», con sus metadatos y de quién partía. Así el historial no se pierde, ni a mano ni
  por las reglas de retención. De una borrada se puede ver qué cambió, y «Quitar del historial» elimina su rastro; no se
  puede restaurar ni fijar. Las copias que se borraron antes de esta función ya no están y, si faltaba su padre, sus hijos
  se enlazan con la anterior en el tiempo.

### Ciclo de vida de las copias

Reglas por servidor para borrar copias viejas solas. Se aplican después de cada copia y una vez al día
(a partir de las 3:00). En la pestaña Copias se editan, se ve **qué se borraría** antes de guardar o aplicar,
y se puede aplicar a mano.

| Regla | Por defecto | Qué hace |
|---|---|---|
| Seguridad previa: conservar las últimas | 3 | Las copias que se hacen antes de actualizar, fusionar o restaurar. 0 = sin límite. |
| …y borrar las de más de (días) | 14 | 0 = sin límite de edad. |
| Manuales: borrar las de más de (días) | 0 | 0 = nunca: una copia manual es una decisión deliberada. |
| Espacio máximo de las copias (GB) | 0 | 0 = sin límite. Si se supera, se borran las más antiguas. |
| Disco libre mínimo (GB) | 0 | 0 = sin mínimo. Si queda menos, se borran las más antiguas. |
| Automáticas sin tarea: conservar | 7 | Las automáticas respetan el menor «Conservar» de las tareas programadas; esta regla solo vale si no hay tareas. |

Garantías: **nunca se borra la copia más reciente ni las copias fijadas**, así que siempre queda al menos una.
Las fijadas no cuentan para ningún límite de cantidad. Si las reglas no se pueden cumplir sin tocar copias
protegidas, la vista previa lo avisa. Cada borrado queda en la auditoría y en el aviso a Discord (si está
configurado). Si hay una copia en curso, no se borra nada en ese momento.

## Diagnóstico — pestaña Diagnóstico

Analiza `latest.log` y los informes de crash y señala la causa probable con una sugerencia: Java de
versión incorrecta, mod de cliente en el servidor, falta de memoria, puerto ocupado, EULA sin aceptar,
dependencias que faltan, mods duplicados, fallo de mixin y retrasos («Can't keep up»). Ruta: `doctor`.

## Avisos a Discord — pestaña Avisos

Webhook de Discord (solo URL de `discord.com`/`discordapp.com`). Eventos: servidor arrancado, parado,
caído, copia hecha, jugadores que entran o salen y propuestas. Máximo 20 avisos por minuto y servidor,
y uno cada 2 s por clave; las menciones están desactivadas. Rutas: `notify`, `notify_set`,
`notify_remove`, `notify_test`.

## Actualizar mods — pestaña Actualizar mods

1. Busca mods con versión nueva (solo Modrinth; solo `https://cdn.modrinth.com`).
2. Crea una copia del servidor **sin mundo** en `sandbox/`, con las actualizaciones aplicadas, y la
   arranca de verdad hasta ver `Done (` o agotar 300 s.
3. Si falla, localiza la actualización culpable por lo que dice el registro y, si no basta, dividiendo
   en grupos (unos `log2(n)+2` arranques con un culpable; máximo 12). Detecta choques entre
   actualizaciones.
4. Solo se aplican al servidor real las que pasan, con el servidor parado y copia previa.

Exige memoria libre (`Xmx` + 1 GB) y el servidor real parado. Rutas: `safe_update`,
`safe_update_start`, `safe_update_apply`. **Probado con un servidor simulado, no con Minecraft real.**

## Servidor de pruebas — pestaña Servidor de pruebas

Un servidor permanente `<nombre>-prueba`, hijo del real en la barra lateral y administrable como
cualquier otro (mods, consola, registros, arranque).

- **Qué copia:** mods (con `reflink` si el sistema de archivos lo permite) y las carpetas `config`,
  `defaultconfigs`, `kubejs`, `scripts` y `global_packs`. **Nunca el mundo**: genera uno vacío
  (`mundo-prueba`). Puerto propio desde el 25566, memoria limitada a 4 GB, `libraries` enlazada.
- **Fusión con el real:** compara configuración y mods; tú eliges qué pasa al real.
  - Configuración: modificados y nuevos se copian; los borrados se quitan del real.
  - Mods: añadidos, quitados y cambiados; cada jar copiado se comprueba por SHA-1.
  - Requisitos: servidor real parado y copia previa automática. Se rechazan rutas fuera de las carpetas
    permitidas y enlaces simbólicos. `server.properties` y el mundo no se fusionan nunca.
- Borrar el servidor de pruebas no toca el real (el enlace a `libraries` se quita antes, sin seguirlo).
- Rutas: `staging`, `staging_create`, `staging_diff`, `staging_merge`, `staging_merge_mods`,
  `staging_delete`, `staging_sync_install`.

## Sincronización de clientes — pestaña Sincronización

Integra [AutoModpack](https://modrinth.com/mod/automodpack) (LGPL-3.0, mod aparte; no se incluye su código).

- AutoModpack es un extra opcional del asistente de creación de servidores (desmarcado por defecto) y el cliente
  generado lo lleva siempre.
- La pestaña permite probarlo en una copia aislada y ver qué publicaría a los clientes; instalarlo en
  el real exige prueba superada, servidor parado y copia previa.
- AutoModpack reutiliza el puerto de Minecraft (no hay que abrir otro). Los jugadores confirman la
  huella del certificado la primera vez.
- Rutas: `sync`, `sync_test_start`, `sync_install`.

## Estadísticas — pestaña Estadísticas

Tiempo de juego por jugador, sesiones y horas con más actividad, calculados a partir de los registros del servidor (entradas y salidas de jugadores). Requiere el
permiso `players`. Ruta: `player_stats`.

## Propuestas de mods — pestaña Propuestas

Cualquier usuario con acceso al servidor puede proponer un mod (máximo 5 pendientes por usuario y 500
por servidor, sin duplicados). Un administrador aprueba o rechaza; lo aprobado enlaza a la ficha del
mod para instalarlo. Rutas: `proposal_search`, `proposals`, `proposal_create`, `proposal_decide`,
`proposal_withdraw`.

## Seguridad — página Seguridad

- **Verificación en dos pasos** (TOTP, RFC 6238, SHA-1, 6 dígitos, 30 s, ±1 ventana). Al activarla se muestra
  un **código QR** para escanear con la app (Google Authenticator, Aegis, Authy…) y, como alternativa, la clave
  para escribirla a mano. El QR lo genera `modnex_pro/qr.py`, sin dependencias. Un código no se
  puede usar dos veces. 8 códigos de recuperación de un solo uso, guardados solo como hash. Tras 5
  códigos erróneos se bloquea al usuario 10 minutos, aunque cambie de IP. Un administrador puede
  restablecer la verificación de otro usuario.
- **Acceso remoto para usuarios:** abre un túnel público hacia el panel con `cloudflared` (túnel rápido,
  sin cuenta) o `ngrok` (necesita cuenta y token configurado en ngrok). Sirve para que usuarios con
  permisos administren sus servidores desde fuera. **Los administradores no pueden entrar por el túnel**
  (ver «Política de acceso de administradores»). Por el túnel solo entran cuentas con 2FA; se puede
  quitar ese requisito con `"remote_2fa": false`. La dirección es pública mientras esté abierto.
- Si el componente de 2FA falla, el inicio de sesión se rechaza (no se salta la verificación).
- Rutas globales: `2fa_status`, `2fa_begin`, `2fa_confirm`, `2fa_disable`, `2fa_reset`, `remote_status`,
  `remote_start`, `remote_stop`.

## Política de acceso de administradores (núcleo)

Los administradores solo pueden iniciar sesión y usar el panel desde **este equipo o la red local**
(loopback, redes privadas, ZeroTier, Tailscale y similares: cualquier IP no enrutable por internet).
Lo aplica el núcleo en cada petición, no solo al iniciar sesión, así que una cookie de administrador
robada tampoco sirve desde fuera.

Una petición se considera remota si:

- trae cabeceras de reenvío de un túnel (`Cf-Connecting-Ip` o `X-Forwarded-For`) y llega por loopback;
- llega desde una IP enrutable por internet (por ejemplo, con el puerto abierto en el router);
- llega por loopback con un nombre de dominio público en `Host` (como `*.trycloudflare.com`).

Las cabeceras de reenvío solo se creen si la conexión viene del propio equipo; desde la red local se
ignoran, así que un equipo de la LAN no puede falsearlas. Un administrador que intenta entrar desde
fuera recibe «usuario o contraseña incorrectos», igual que con una contraseña errónea, para no revelar
que la cuenta existe; el intento queda en la auditoría y cuenta para el bloqueo por IP.
Se puede relajar con `"admin_remote": true` en `config.json` (no recomendado).

Si usas otro túnel o proxy inverso que no envíe cabeceras de reenvío ni conserve el `Host` público,
las peticiones parecerán locales: configúralo para que las envíe.

## Qué no hace

Perfilar el rendimiento desde el panel (spark solo se instala; se usa con `/spark` en la consola), gestionar varios equipos, ni fusionar
`server.properties` o el mundo.

## Extras al crear un servidor

El asistente de **Nuevo servidor** tiene una sección «Extras opcionales», todos desmarcados por defecto:

| Extra | Qué hace | Disponible en |
|---|---|---|
| AutoModpack | Sincroniza los mods del servidor con los clientes al entrar. | Fabric, NeoForge y Forge, y modpacks NeoForge |
| spark | Perfilador: mide los TPS y qué mod gasta más tiempo por tick (comando `/spark`). Se instala en `mods/`. | Fabric, NeoForge y Forge, y modpacks NeoForge |

En Paper no se ofrece: lo trae incluido. Si un extra no se puede instalar (sin versión estable para esa versión de
Minecraft, sin red), el servidor se crea igual y el motivo queda en la auditoría.
