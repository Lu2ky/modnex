---
name: Modnex
description: Sala de control para servidores de Minecraft con mods, que corre en tu propio equipo.
colors:
  primary: "#55d68b"
  primary-ink: "#04160d"
  neutral-bg: "#111318"
  neutral-surface: "#1b2029"
  neutral-elevated: "#272e3a"
  neutral-border: "#3b4655"
  text: "#eef2f6"
  text-muted: "#98a3b3"
  violet: "#a78bfa"
  cyan: "#42c6d9"
  warning: "#f0b85a"
  error: "#f16b72"
  offline: "#87909d"
  log-bg: "#0c0f14"
  brand-mint: "#59f8b8"
  brand-violet: "#9a80f3"
  brand-deep: "#0da673"
typography:
  body:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "0em"
  headline:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "24px"
    fontWeight: 650
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "17px"
    fontWeight: 600
    lineHeight: 1.2
  label:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "12px"
    fontWeight: 600
    lineHeight: 1.4
  mono:
    fontFamily: "ui-monospace, JetBrains Mono, Menlo, Consolas, monospace"
    fontSize: "12.5px"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  sm: "6px"
  md: "8px"
  lg: "10px"
  xl: "12px"
  pill: "99px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "24px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-ink}"
    rounded: "{rounded.md}"
    padding: "7px 14px"
  button-primary-hover:
    backgroundColor: "#6ce09b"
  button-secondary:
    backgroundColor: "{colors.neutral-elevated}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: "7px 14px"
  button-danger:
    backgroundColor: "{colors.neutral-elevated}"
    textColor: "{colors.error}"
    rounded: "{rounded.md}"
    padding: "7px 14px"
  chip:
    backgroundColor: "{colors.neutral-elevated}"
    textColor: "{colors.text-muted}"
    rounded: "{rounded.pill}"
    padding: "2px 8px"
  input:
    backgroundColor: "{colors.neutral-surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: "8px 10px"
  panel:
    backgroundColor: "{colors.neutral-surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.lg}"
    padding: "14px 16px"
  nav-item:
    backgroundColor: "{colors.neutral-surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: "7px 8px"
---

<!-- Fuente: escaneo de static/style.css y static/landing.css (mayo de 2026). Los valores son los que existen hoy. -->

# Design System: Modnex

## Overview

**Creative North Star: "The Control Room"**

Modnex es una sala de control para servidores de Minecraft con mods: se ve qué está en marcha, qué mods hay, quién puede hacer qué, y el cliente que van a usar los jugadores. La interfaz es plana. La jerarquía sale de tres tonos de oscuro (`#111318` de fondo, `#1b2029` de panel, `#272e3a` elevado) y de bordes `#3b4655`, no de sombras. El verde `#55d68b` marca lo que se puede accionar, y se usa poco.

El tono es cercano y de juego, en español: frases directas, con alguna referencia al mundo de Minecraft, pero sin perder claridad. Un estado se explica con punto, color y texto a la vez.

Lo que no debe parecer: un panel de hosting genérico, con tarjetas idénticas, gradientes y métricas decorativas sin función.

**Key Characteristics:**
- Plano por defecto: jerarquía por capas tonales.
- Verde de acción escaso por pantalla.
- Estados siempre visibles: punto, color y texto.
- Radios medios (8 px) y bordes visibles: firme, no blando.
- Movimiento corto (120–300 ms) y solo para responder a una acción.

## Colors

Paleta oscura como tema principal, con un tema claro para quien la prefiera. Los valores del tema claro viven en `.impeccable/design.json` (`light`).

### Primary
- **Verde de acción** (#55d68b): botón principal, enlace activo, selección de navegación. Una acción principal por pantalla como máximo. Hover en `#6ce09b`.
- **Tinta sobre verde** (#04160d): texto sobre el botón verde.

### Secondary
- **Violeta de mods** (#a78bfa): loaders, categorías y todo lo relacionado con mods y configuración.

### Tertiary
- **Cian de estado** (#42c6d9): servidor arrancando e información secundaria.
- **Ámbar de aviso** (#f0b85a): avisos que requieren atención (mods desactualizados, cliente antiguo).

### Neutral
- **Fondo de cabina** (#111318): fondo general.
- **Panel de trabajo** (#1b2029): tarjetas, barra lateral, campos.
- **Superficie elevada** (#272e3a): botones secundarios, chips, iconos de servidor, diálogos.
- **Borde de consola** (#3b4655): divisores y bordes de todo.
- **Texto principal** (#eef2f6) y **texto secundario** (#98a3b3).
- **Fondo de consola** (#0c0f14): solo el log del servidor.
- **Gris desconectado** (#87909d): servidor parado.

### Error
- **Rojo de error** (#f16b72): errores, acciones destructivas, servidor en fallo.

### Marca
- **Degradado de marca** (`linear-gradient(120deg, #59f8b8, #9a80f3)`, menta a violeta): tomado del logo MODNEX. Solo en acentos: titular de la landing, barras de las etiquetas, progreso del demo, indicador del servidor activo, borde superior del login y del cierre de la landing. Nunca como fondo de texto de cuerpo ni de botones.
- **Menta de marca** (#59f8b8) y **violeta de marca** (#9a80f3): los colores exactos del logo. El verde de acción de la especificación (#55d68b) queda como primario de interfaz.

### Named Rules
**The One Action Rule.** El verde de acción aparece en una sola acción principal por pantalla. Su rareza es lo que la hace clara.

## Typography

**Display, body y label:** Inter, con `system-ui` y la pila del sistema como respaldo.
**Mono:** `ui-monospace` para la consola y los valores técnicos.

**Character:** Inter neutral y legible, con un único peso de títulos (600–650). No hay una segunda fuente de display: la jerarquía sale del tamaño y del peso.

### Hierarchy
- **Headline** (650, 24px, 1.2): título de la pantalla; en la landing crece a `clamp(2.4rem, 5.2vw, 4rem)`.
- **Title** (600, 17px, 1.2): título de cada bloque de panel.
- **Subsection** (600, 14px): encabezados de grupo dentro de un bloque (`h3`).
- **Body** (400, 15px, 1.5): texto de la interfaz. Las descripciones de mods usan 0.98rem, 1.7 de interlineado y 92ch como máximo.
- **Label** (600, 12–13px): chips, estados y metadatos.
- **Mono** (400, 12.5px, 1.5): consola y valores técnicos.

### Named Rules
**The Plain Weight Rule.** Solo dos pesos en la interfaz: 400 para leer, 600 para señalar. Los títulos no pasan de 650.

## Layout

El panel usa una barra lateral fija de 268 px a la izquierda y un área principal con padding de 28×36 px, máximo de 1040 px. La ficha de mod ocupa todo el ancho disponible con una columna lateral de 340 px. Por debajo de 820 px la barra lateral pasa arriba y la columna se apila.

La landing usa un contenedor de 1240 px con 32 px de margen lateral y secciones separadas por 96 px. Por debajo de 900 px el hero pasa a una columna.

Espaciado: los valores observados son 4, 8, 10, 12, 14 y 24 px. No hay una escala formal; `spacing` en el frontmatter recoge los pasos más usados.

## Elevation & Depth

El sistema es plano. Las superficies no tienen sombra en reposo: la jerarquía sale de `#111318`, `#1b2029` y `#272e3a`, y de bordes `#3b4655`.

Hay dos excepciones que se deben conocer, porque son deriva respecto a la regla:
- la vista previa de la landing (`.mock`) tiene una sombra grande en reposo;
- las tarjetas de la landing se elevan y se sombrean al pasar el cursor.

Ninguna de las dos aparece en el panel de trabajo.

### Shadow Vocabulary
- **Diálogo** (`box-shadow: 0 24px 60px -30px rgb(0 0 0 / 0.6)`): diálogos y la vista previa de la landing.
- **Hover de tarjeta de landing** (`box-shadow: 0 14px 30px -18px rgb(0 0 0 / 0.7)`): solo al pasar el cursor, con `translateY(-3px)`.

### Named Rules
**The Flat-At-Rest Rule.** Las superficies no tienen sombra en reposo. Una sombra aparece solo como respuesta a un estado: hover, foco o diálogo.

## Shapes

Radios medios y consistentes: 8 px en controles (botones, campos, navegación), 10 px en paneles y listas, 12 px en diálogos y tarjetas de la landing, 99 px en chips y píldoras. Los iconos de servidor son cuadrados con radio 6–16 px según el tamaño. El punto de estado es un círculo de 9 px.

Los bordes son visibles (1 px `#3b4655`) y no se sustituyen por sombras. El foco es un contorno de 2 px en verde de acción, con 2 px de separación.

## Components

Cada componente tiene carácter propio: firme, directo y sin adornos.

### Buttons
- **Shape:** radio 8 px; padding 7×14 px; texto 14px en peso 600.
- **Primary:** fondo `#55d68b`, texto `#04160d`. Hover a `#6ce09b`. Activo con `scale(0.98)`.
- **Secondary:** fondo `#272e3a`, borde `#3b4655`, texto `#eef2f6`. Hover cambia el borde a verde.
- **Danger:** fondo `#272e3a`, texto y borde `#f16b72`. Se desactiva hasta que se cumple la confirmación (escribir el nombre del servidor).
- **Focus:** contorno de 2 px verde, separación de 2 px.

### Chips
- **Style:** fondo `#272e3a`, borde `#3b4655`, texto `#98a3b3`, pastilla de 99 px, texto 12px en peso 600.
- **State:** los chips de origen (Modrinth, CurseForge) y de loader (violeta) usan texto y borde del color de su grupo.

### Cards / Containers
- **Corner Style:** 10 px en paneles y listas; 12 px en tarjetas de la landing.
- **Background:** `#1b2029` sobre el fondo `#111318`.
- **Shadow Strategy:** plano en reposo (ver Elevation).
- **Border:** 1 px `#3b4655`.
- **Internal Padding:** 14×16 px en paneles; 24 px en tarjetas de la landing.

### Inputs / Fields
- **Style:** fondo `#1b2029`, borde `#3b4655`, radio 8 px, padding 8×10 px.
- **Focus:** contorno de 2 px verde.
- **Disabled:** opacidad 0.5 y cursor no permitido.

### Navigation
- **Style:** barra lateral de 268 px, fondo `#1b2029`, texto 15px.
- **Default:** fondo transparente. **Hover:** fondo `#272e3a`. **Active:** fondo `#1b2029` con una barra interior verde de 3 px.
- **Mobile:** la barra pasa arriba y sus elementos se desplazan en horizontal.

### Estado del servidor (LED)
Punto de 9 px con un significado fijo:
- **En marcha:** verde `#55d68b`, pulso lento de 2.6 s.
- **Arrancando:** cian `#42c6d9`, pulso de 1.8 s.
- **Error:** rojo `#f16b72`, un solo destello al fallar.
- **Parado:** gris `#87909d`, fijo.

El estado siempre va acompañado de texto ("En marcha", "Parado").

## Do's and Don'ts

### Do:
- **Do** usar el verde de acción en una sola acción principal por pantalla.
- **Do** mostrar el estado con punto, color y texto a la vez.
- **Do** separar lo destructivo: rojo, confirmación escrita y desactivado hasta cumplirla.
- **Do** usar el violeta para mods, loaders y configuración, y el cian para información de estado.

### Don't:
- **Don't** poner sombras en reposo en el panel de trabajo.
- **Don't** usar gradientes ni tarjetas idénticas de métricas decorativas.
- **Don't** usar el cian de estado y el verde de acción en la misma acción.
- **Don't** mezclar más de tres radios distintos en una misma pantalla.
- **Don't** usar Silkscreen ni otra fuente pixel en la interfaz: la declaración existe en el CSS pero está anulada y no se usa.
- **Don't** adornar la marca MODNEX: el logo se usa tal cual, sobre fondo oscuro.
- **Don't** usar el degradado de marca en botones, en texto de cuerpo ni sobre fondos claros.
