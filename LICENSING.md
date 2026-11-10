# Licenciamiento

Modnex usa un modelo **open core**.

## Núcleo (AGPL-3.0)

El código de este repositorio es software libre bajo la GNU Affero General Public License v3.0.
Cualquiera puede usarlo, estudiarlo, modificarlo y redistribuirlo, siempre bajo esa licencia,
incluido ofrecerlo como servicio en red (la AGPL obliga a publicar esos cambios).

Incluye: crear y arrancar servidores, plantillas, instalación de mods y plugins con sus dependencias,
modpacks, generación del cliente, consola, logs, propiedades de `server.properties`, releases con
enlace temporal y el filtro de mods de cliente.

## Licencia Pro (propietaria)

Funciones de pago, en código que **no** se publica en este repositorio:

- **Gestión de permisos:** usuarios, permisos por servidor (logs, mods, datapacks, texturas,
  jugadores y encender/apagar) y auditoría de accesos.
- **Copias de seguridad:** copias programadas y restauración de mundos y configuración.
- **Versionado del servidor:** historial de versiones del servidor con vuelta atrás.

## Cómo se separa (estado actual)

El núcleo no contiene código de Pro. `plugins.py` carga de forma opcional un paquete externo
(`modnex_pro`, en su propio repositorio) mediante cuatro enganches: rutas por servidor, pestañas del
panel, tablas propias y eventos de arranque, parada y caída. Sin el paquete, o si falla al cargarse,
el núcleo funciona como edición gratuita.

- Ya está en el paquete Pro: copias de seguridad y versiones, tareas programadas, diagnóstico de
  crashes y avisos a Discord.
- **Todavía está en el núcleo y hay que moverlo:** la gestión de permisos por usuario y servidor
  (`db.py`, `app.py`). Hasta entonces, la edición gratuita incluye usuarios y permisos.
- La validación de licencias **no está implementada**: Pro solo se activa con `MODNEX_PRO_DEV=1` o
  `"pro_dev": true` en `config.json`. Sirve para desarrollar, no protege nada.

Para probar Pro en local: `MODNEX_PRO_PATH=<ruta a modnex-pro> MODNEX_PRO_DEV=1 python3 app.py`.

## Activos de terceros

- **Inter** y **IBM Plex Sans**: licencia SIL OFL 1.1. Compatible con AGPL; hay que conservar su aviso.
- **Activos de Mojang** (fuente de píxeles, sonidos de clic y portal, textura del portal): no son
  del proyecto. Deben sustituirse o retirarse antes de publicar el repositorio o vender nada.

## Pendiente

- Añadir `LICENSE` con el texto oficial de la AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.txt).
- Separar el módulo Pro del núcleo.
- Sustituir los activos de Mojang.
