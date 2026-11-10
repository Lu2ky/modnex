# Instalación de Modnex

Modnex es un programa de Python que corre en tu propio equipo y se usa desde el navegador. No instala
dependencias: usa solo la biblioteca estándar de Python y SQLite.

## Qué necesitas

| Requisito | Detalle |
|---|---|
| Python 3 reciente | Probado con 3.14. Comprueba con `python3 --version`. |
| Java | Para los servidores de Minecraft. Minecraft 1.20.5 o posterior pide Java 21; de 1.18 a 1.20.4, Java 17. Comprueba con `java -version`. |
| Git | Solo para descargar el proyecto. También sirve bajar el `.zip` desde GitHub. |
| Espacio en disco | Cada servidor ocupa lo que ocupe su mundo y sus mods; reserva varios GB. |

Linux, macOS y Windows con WSL son los entornos probados. En Windows nativo no está probado.

## 1. Descargar

```bash
git clone https://github.com/Lu2ky/modnex.git
cd modnex
```

## 2. Elegir dónde viven los servidores (opcional)

Cada subcarpeta de la carpeta de servidores que tenga `start.sh`, `run.sh` o una carpeta `mods/` es un servidor.
Por defecto es `servers/` junto al proyecto y se crea sola en el primer arranque, así que puedes saltarte este paso.

Para usar otra carpeta, por ejemplo una donde ya tienes servidores de Minecraft, hay dos formas:

```bash
export SERVERS_DIR=~/minecraft-servers     # variable de entorno (añádela a ~/.bashrc o ~/.zshrc)
```

o la clave `"servers_dir": "/ruta/a/tus/servidores"` en `config.json`. La variable tiene prioridad sobre `config.json`.
Si ya tienes servidores en esa carpeta, el gestor los detecta.

## 3. Arrancar

```bash
./run.sh
```

Abre <http://127.0.0.1:8765/app>. En el primer arranque el gestor crea `config.json` con un
`access_token` aleatorio y un administrador llamado `admin` cuya contraseña es ese token:

```bash
grep access_token config.json
```

Entra con `admin` y ese token, y cámbialo desde **Usuarios y permisos**.

## 4. Crear tu primer servidor

1. En la barra lateral, pulsa **+ Nuevo servidor**.
2. Elige una plantilla (Vanilla, Fabric, NeoForge, Forge o Paper) o un modpack de Modrinth o CurseForge.
3. Indica nombre, versión de Minecraft, memoria y puerto, y marca que aceptas el EULA de Minecraft
   (el gestor escribe `eula.txt` por ti).
4. Pulsa **Crear servidor**. Cuando termine la instalación, abre el servidor y pulsa **Arrancar**.

Los jugadores se conectan a la IP de tu equipo y al puerto que elegiste. Si juegan desde fuera de tu red,
tienes que abrir ese puerto en tu router o usar un servicio de túnel; el gestor no lo hace por ti.

## Configuración opcional

`config.json` (no se versiona; contiene secretos):

| Clave | Para qué sirve |
|---|---|
| `curseforge_api_key` | Activa la búsqueda y descarga de CurseForge. Se consigue gratis en la consola de desarrolladores de CurseForge. |
| `bind` | Dirección en la que escucha el panel. Por defecto `0.0.0.0` (toda la red local). |
| `servers_dir` | Carpeta de los servidores (ver arriba). |
| `admin_remote` | Con `true`, los administradores pueden entrar desde fuera de tu red. No recomendado. |

Variables de entorno (tienen prioridad sobre `config.json`):

| Variable | Valor por defecto |
|---|---|
| `SERVERS_DIR` | `servers/` junto al proyecto (o `servers_dir` de `config.json`) |
| `MANAGER_PORT` | `8765` |
| `MANAGER_BIND` | `0.0.0.0` |
| `MANAGER_DB` | `manager.db` junto a `app.py` |
| `CURSEFORGE_API_KEY` | vacía |

Para que el panel solo se vea desde tu equipo:

```bash
MANAGER_BIND=127.0.0.1 ./run.sh
```

## Dejarlo en marcha

El gestor es un proceso normal. Para que siga vivo al cerrar la terminal:

```bash
setsid nohup ./run.sh > manager.log 2>&1 &
```

Para pararlo, busca su proceso (`pgrep -f "python3 app.py"`) y ciérralo con `kill`. Los servidores de
Minecraft que arrancó siguen corriendo; páralos antes desde el panel.

## Actualizar

```bash
git pull
```

Reinicia el gestor después: los cambios de `app.py` no se aplican hasta reiniciar. Tus servidores,
`config.json` y `manager.db` no se tocan.

## Si algo falla

| Síntoma | Qué mirar |
|---|---|
| El servidor no arranca | Pestaña **Logs** del servidor. Lo más común: una versión de Java que no corresponde. |
| «No hay Java» | Instala Java 21 (o 17) y comprueba que `java -version` funciona en la misma terminal desde la que lanzas `./run.sh`. |
| No veo mis servidores | `SERVERS_DIR` apunta a otra carpeta. Comprueba la línea «Gestor en … (servidores en …)» que imprime el arranque. |
| Olvidé la contraseña del admin | El administrador inicial solo se crea con la base de datos vacía. Si no tienes otros usuarios que conservar, para el gestor, mueve `manager.db` a otro sitio y arráncalo: vuelve a crear `admin` con el `access_token` de `config.json`. Se pierden usuarios, permisos y registro de actividad; los servidores no se tocan. |
| El puerto 8765 está ocupado | Cámbialo con `MANAGER_PORT=8800 ./run.sh`. |
