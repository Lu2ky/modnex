"""KubeJS: probar los scripts en el servidor en marcha.

Envía `/reload` a la consola, espera a que KubeJS anuncie el final y lee de los logs qué pasó: cuántas recetas se
añadieron, qué dicen las líneas `[modnex]` de los scripts generados y qué errores o avisos mencionan a Modnex.
Solo funciona si el servidor lo arrancó el gestor (si no, no hay canal de consola y se dice con claridad).
"""
import re
import threading
import time
from pathlib import Path

FINISH = re.compile(r"Reloaded with (no|\d+) KubeJS errors?", re.IGNORECASE)
DONE = re.compile(r"Server resource reload complete")
SUMMARY = re.compile(r"Added (\d+) recipes?, removed (\d+) recipes?, modified (\d+) recipes?, with (\d+) failed recipes?")
LEVEL = re.compile(r"/(WARN|ERROR)\]|\[(WARN|ERROR)\]")
PREFIX = re.compile(r"^\[[^\]]*\] \[[^\]]*\] \[[^\]]*\]: |^\[\d\d:\d\d:\d\d\] \[[A-Z]+\] ")
LOCATION = re.compile(r"^(?:server_scripts|startup_scripts|client_scripts):([^:\s]+)#\d+: ")
ANSI = re.compile(r"\x1b\[[0-9;]*m|§.")
_BUSY = {}
_LOCK = threading.Lock()


def _level(line):
    m = LEVEL.search(line)
    return (m.group(1) or m.group(2)).lower() if m else "info"


def _clean(line):
    """(archivo del script o None, mensaje) sin la hora, el hilo ni el número de línea."""
    text = PREFIX.sub("", ANSI.sub("", line)).strip()
    m = LOCATION.match(text)
    return (m.group(1) if m else None), LOCATION.sub("", text).strip()


def analyze(latest, kjs):
    """Interpreta lo que escribieron latest.log y logs/kubejs/server.log desde que se envió /reload."""
    m = FINISH.search(latest)
    errors = None if not m else (0 if m.group(1).lower() == "no" else int(m.group(1)))
    finished = bool(m or DONE.search(latest))
    recipes = None
    for s in SUMMARY.finditer(kjs):
        recipes = {"added": int(s.group(1)), "removed": int(s.group(2)), "modified": int(s.group(3)), "failed": int(s.group(4))}
    summary, problems, seen = [], [], set()
    for text, from_kjs in ((latest, False), (kjs, True)):
        for line in text.splitlines():
            if not line.strip():
                continue
            level, low = _level(line), line.lower()
            file, msg = _clean(line)
            clean = f"{file}: {msg}" if file else msg
            if not msg or clean in seen:
                continue
            ours = "modnex" in low
            if level == "error" and (ours or from_kjs or "kubejs" in low):
                seen.add(clean); problems.append({"level": "error", "text": clean[:400]})
            elif level == "warn" and ours:
                seen.add(clean); problems.append({"level": "warn", "text": clean[:400]})
            elif level == "info" and "[modnex]" in low and not low.lstrip().startswith("failed"):
                seen.add(clean); summary.append((f"{file}: " if file else "") + msg.split("[modnex]", 1)[-1].strip())
    has_error = any(p["level"] == "error" for p in problems) or bool(errors)
    return {"finished": finished, "kubejs_errors": errors, "recipes": recipes, "summary": summary[:30], "problems": problems[:40],
            "ok": finished and not has_error}


def notes(ctx, name):
    """Lo que /reload NO aplica, según los scripts generados que existan."""
    base = Path(ctx.server_path(name)) / "kubejs"
    out = []
    if (base / "startup_scripts" / "modnex_inicio.js").is_file():
        out.append("Las propiedades de items (pila, rareza…) son de inicio: /reload no las aplica, hay que reiniciar el servidor.")
    if (base / "client_scripts" / "modnex_cliente.js").is_file():
        out.append("Los tooltips y lo oculto en EMI/JEI se aplican en el cliente: cada jugador recarga con F3+T o reinicia su juego.")
    return out


def _size(p):
    try:
        return p.stat().st_size
    except OSError:
        return 0


def _tail(p, start):
    if not p.is_file():
        return ""
    with open(p, "rb") as fh:
        fh.seek(start if _size(p) >= start else 0)   # el log se rotó (reinicio): se lee entero
        return fh.read().decode(errors="replace")


def run(ctx, name, wait=30, poll=0.4):
    st = ctx.status(name)
    if not st["running"]:
        raise ValueError("El servidor está apagado: enciéndelo desde el gestor para probar los scripts.")
    if not st.get("control"):
        raise ValueError("El servidor no lo arrancó el gestor, así que no puedo enviarle /reload. Arráncalo desde el gestor.")
    with _LOCK:
        if _BUSY.get(name):
            raise ValueError("Ya hay una prueba en curso en este servidor.")
        _BUSY[name] = True
    try:
        base = Path(ctx.server_path(name)) / "logs"
        lf, kf = base / "latest.log", base / "kubejs" / "server.log"
        start_l, start_k = _size(lf), _size(kf)
        try:
            ctx.send_command(name, "reload")
        except RuntimeError as e:
            raise ValueError(str(e))
        t0, done_at, latest, kjs = time.time(), None, "", ""
        while time.time() - t0 < wait:
            time.sleep(poll)
            latest, kjs = _tail(lf, start_l), _tail(kf, start_k)
            if FINISH.search(latest) or DONE.search(latest):
                done_at = done_at or time.time()
                if time.time() - done_at >= max(poll * 2, 0.3):   # un momento más: el log de KubeJS se escribe un poco después
                    break
        res = analyze(latest, kjs)
        res.update(seconds=round(time.time() - t0, 1), notes=notes(ctx, name))
        if not res["finished"]:
            res["problems"].insert(0, {"level": "warn", "text": f"No vi el final del reload en {wait} s. Puede que el servidor esté muy cargado o que KubeJS no haya respondido."})
        return res
    finally:
        with _LOCK:
            _BUSY[name] = False
