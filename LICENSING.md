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

Estas funciones hoy viven en el código del núcleo. Antes de publicar el repositorio hay que
separarlas en un módulo Pro propio, que se cargue solo con licencia válida.

## Activos de terceros

- **Inter** y **IBM Plex Sans**: licencia SIL OFL 1.1. Compatible con AGPL; hay que conservar su aviso.
- **Activos de Mojang** (fuente de píxeles, sonidos de clic y portal, textura del portal): no son
  del proyecto. Deben sustituirse o retirarse antes de publicar el repositorio o vender nada.

## Pendiente

- Añadir `LICENSE` con el texto oficial de la AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.txt).
- Separar el módulo Pro del núcleo.
- Sustituir los activos de Mojang.
