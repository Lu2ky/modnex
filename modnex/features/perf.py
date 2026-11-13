"""Rendimiento: estado de spark, avisos de lag del log y ejecución de sus comandos desde el panel.

spark no tiene API: se le habla por la consola del servidor y se lee su respuesta del log. Eso solo
funciona si el servidor lo arrancó el gestor (si no hay canal de consola, se dice con claridad).
"""
import re
import time
from pathlib import Path

ACTIONS = {
    "tps": "spark tps",
    "health": "spark health",
    "profiler_start": "spark profiler start",
    "profiler_stop": "spark profiler stop",
}
_LAG = re.compile(r"Can't keep up! Is the server overloaded\? Running (\d+)ms or (\d+) ticks behind")
_PREFIX = re.compile(r"^\[[^\]]*\] \[[^\]]*\] \[[^\]]*\]: ")
_ANSI = re.compile(r"\x1b\[[0-9;]*m|§.")
_URL = re.compile(r"https://spark\.lucko\.me/\S+")


def _log(path):
    return Path(path) / "logs" / "latest.log"


def info(ctx, name):
    p = Path(ctx.server_path(name))
    jars = sorted((p / "mods").glob("spark*.jar")) if (p / "mods").is_dir() else []
    bg = None
    cfg = p / "config" / "spark" / "config.json"
    if cfg.is_file():
        m = re.search(r'"backgroundProfiler"\s*:\s*(true|false)', cfg.read_text(errors="replace"))
        bg = (m.group(1) == "true") if m else None
    lag, last = 0, []
    f = _log(p)
    if f.is_file():
        with open(f, errors="replace") as fh:
            for line in fh:
                m = _LAG.search(line)
                if m:
                    lag += 1
                    last = (last + [{"time": line[1:21].strip(), "ms": int(m.group(1)), "ticks": int(m.group(2))}])[-5:]
    st = ctx.status(name)
    return {"installed": bool(jars), "jar": jars[0].name if jars else None, "background": bg,
            "running": bool(st["running"]), "control": bool(st.get("control")),
            "lag_count": lag, "lag_last": last}


def run(ctx, name, action, wait=None):
    if action not in ACTIONS:
        raise ValueError("acción no válida")
    if not info(ctx, name)["installed"]:
        raise ValueError("spark no está instalado en este servidor")
    f = _log(ctx.server_path(name))
    start = f.stat().st_size if f.is_file() else 0
    try:
        ctx.send_command(name, ACTIONS[action])
    except RuntimeError as e:
        raise ValueError(str(e))
    limit = wait if wait is not None else (20 if action == "profiler_stop" else 8)
    text, stable, last_len = "", 0, -1
    t0 = time.time()
    while time.time() - t0 < limit:
        time.sleep(0.5)
        if f.is_file():
            with open(f, "rb") as fh:
                fh.seek(start)
                text = fh.read().decode(errors="replace")
        if text and len(text) == last_len:
            stable += 1
            if stable >= 3 and (action != "profiler_stop" or _URL.search(text)):
                break
        else:
            stable, last_len = 0, len(text)
    lines = [_ANSI.sub("", _PREFIX.sub("", ln)).rstrip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln.strip()]
    url = next((m.group(0) for ln in lines if (m := _URL.search(ln))), None)
    return {"lines": lines[:60], "url": url}
