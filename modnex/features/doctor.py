"""Diagnóstico de arranques y caídas: lee logs y reportes de crash y explica la causa.

`analyze` es una función pura sobre texto (fácil de probar); `diagnose` lee los archivos del servidor.
Cada hallazgo: {id, severity: error|warn|info, title, detail, fix, mods?}.
"""
import re
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;]*m")
MAX_READ = 600_000


def clean(t):
    return ANSI.sub("", t)


def _f(fid, sev, title, detail, fix, **extra):
    return {"id": fid, "severity": sev, "title": title, "detail": detail, "fix": fix, **extra}


def analyze(text, mods_dir=None):
    t = clean(text)
    out = []

    m = re.search(r"requires javaVersion (\d+)[^\n]*?but ([\d.]+) is available", t)
    if m:
        out.append(_f("java", "error", "Versión de Java incorrecta",
                      f"Un mod pide Java {m.group(1)} y el servidor se ejecuta con Java {m.group(2)}.",
                      f"Arranca con Java {m.group(1)}. El gestor usa .runtime/java21 si existe; compruébalo."))

    if "invalid dist DEDICATED_SERVER" in t or re.search(r"Module [\w.]+ not found, required by", t):
        culprits = []
        if mods_dir:
            try:
                import autofilter  # núcleo del gestor
                culprits, _ = autofilter.diagnose(t, mods_dir)
            except Exception:
                culprits = []
        if culprits:
            names = [c[0] for c in culprits]
            out.append(_f("client_mod", "error", "Hay un mod de cliente en el servidor",
                          "; ".join(f"{j}: {why}" for j, why in culprits),
                          "Quita ese mod del servidor (el gestor lo mueve a cuarentena al arrancar).", mods=names))
        else:
            out.append(_f("client_mod", "error", "Hay un mod de cliente en el servidor",
                          "El servidor intentó cargar clases que solo existen en el cliente, pero no pude identificar el mod.",
                          "Revisa los mods de solo cliente (minimapas, shaders, mejoras de interfaz) y quítalos del servidor."))

    if re.search(r"java\.lang\.OutOfMemoryError|GC overhead limit", t):
        out.append(_f("oom", "error", "Sin memoria",
                      "Java se quedó sin memoria.", "Sube la memoria máxima (Xmx) en Ajustes y reinicia."))

    if re.search(r"Address already in use|FAILED TO BIND TO PORT", t):
        out.append(_f("port", "error", "El puerto está ocupado",
                      "Otro proceso usa el puerto del servidor.",
                      "Cierra el otro servidor o cambia server-port en Propiedades."))

    if re.search(r"You need to agree to the EULA", t):
        out.append(_f("eula", "error", "Falta aceptar la EULA",
                      "Minecraft no arranca hasta aceptarla.", "Acepta la EULA al crear el servidor, o pon eula=true en eula.txt."))

    deps = re.findall(r"Mod ID: '([^']+)', Requested by: '([^']+)', Expected range: '([^']+)', Actual version: '([^']+)'", t)
    if deps:
        lines = [f"{req} necesita {mid} {rng} (hay {act})" for mid, req, rng, act in deps]
        out.append(_f("deps", "error", "Faltan dependencias de mods", "; ".join(lines[:8]),
                      "Instala las dependencias que faltan, o la versión que piden.",
                      mods=sorted({mid for mid, _, _, _ in deps})))

    dup = re.search(r"Found duplicate mods?[:\s]+([^\n]+)", t)
    if dup:
        out.append(_f("dup", "error", "Mods duplicados", dup.group(1)[:200], "Deja una sola copia de cada mod en la carpeta mods/."))

    mix = sorted(set(re.findall(r"Mixin apply failed [^\n]*? from mod ([\w\-]+)", t)))
    if mix:
        out.append(_f("mixin", "error", "Un mod falla al modificar el juego (mixin)", ", ".join(mix),
                      "Suele ser un conflicto entre mods o una versión incompatible: actualiza o quita ese mod.", mods=mix))

    lag = len(re.findall(r"Can't keep up!", t))
    if lag >= 5:
        out.append(_f("lag", "warn", "El servidor va con retraso", f"Aparece «Can't keep up» {lag} veces.",
                      "Prueba a bajar la distancia de simulación, asignar más memoria o quitar mods pesados."))

    if not out and re.search(r"Mod loading has failed|Failed to start the minecraft server", t):
        out.append(_f("generic", "error", "El servidor no pudo arrancar",
                      "Hay un fallo de carga sin una causa que reconozca.", "Abre el reporte de crash más reciente en crash-reports/."))

    if not out and re.search(r"Done \(", t):
        out.append(_f("ok", "info", "Sin problemas detectados", "El último arranque llegó a «Done».", ""))
    return out


def _last_run(text):
    """Texto de la última ejecución (desde el último arranque de ModLauncher)."""
    idx = [m.start() for m in re.finditer(r"ModLauncher [\d.]+\+main\.\w+ starting", clean(text))]
    t = clean(text)
    return t[idx[-1]:] if idx else t


def diagnose(ctx, name):
    p = Path(ctx.server_path(name))
    parts = []
    log = p / "manager-console.log"
    if log.exists():
        with open(log, "rb") as f:
            f.seek(max(0, log.stat().st_size - MAX_READ))
            parts.append(_last_run(f.read().decode("utf-8", "ignore")))
    crashes = sorted((p / "crash-reports").glob("crash-*.txt"), key=lambda x: x.stat().st_mtime) if (p / "crash-reports").is_dir() else []
    last_crash = crashes[-1] if crashes else None
    if last_crash and log.exists() and last_crash.stat().st_mtime >= log.stat().st_mtime - 3600:
        parts.append(last_crash.read_text(errors="ignore")[:MAX_READ])
    findings = analyze("\n".join(parts), p / "mods")
    return {"findings": findings, "crash_report": last_crash.name if last_crash else None,
            "running": bool(ctx.status(name)["running"])}
