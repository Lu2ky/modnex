"""Vigila logs/latest.log de los servidores en marcha y avisa de entradas y salidas de jugadores."""
import os
import threading
import time
from pathlib import Path

from . import notify, stats

_started = False


def read_new(path, state):
    """Líneas completas nuevas desde la última lectura. `state` guarda {ino, pos}.
    La primera vez no repite el historial: empieza al final del archivo."""
    try:
        st = os.stat(path)
    except OSError:
        state.clear()
        return []
    if not state:
        state.update(ino=st.st_ino, pos=st.st_size)
        return []
    if state["ino"] != st.st_ino or st.st_size < state["pos"]:  # archivo rotado o recortado
        state.update(ino=st.st_ino, pos=0)
    if st.st_size == state["pos"]:
        return []
    with open(path, "rb") as f:
        f.seek(state["pos"])
        data = f.read(min(st.st_size - state["pos"], 1 << 20))
    cut = data.rfind(b"\n")
    if cut < 0:
        return []  # línea a medias: se lee en la próxima vuelta
    state["pos"] += cut + 1
    return data[:cut].decode("utf-8", "ignore").split("\n")


def player_events(lines):
    out = []
    for line in lines:
        m = stats.LINE.match(line.rstrip("\r"))
        if not m:
            continue
        e = stats.EVENT.fullmatch(m.group(7).strip())
        if e:
            out.append(("join" if e.group(2) == "joined" else "leave", e.group(1)))
    return out


def tick(ctx, states):
    live = set()
    for s in ctx.list_servers():
        name = s["name"]
        if not s["status"]["running"]:
            states.pop(name, None)
            continue
        live.add(name)
        path = Path(ctx.server_path(name)) / "logs" / "latest.log"
        for kind, who in player_events(read_new(path, states.setdefault(name, {}))):
            text = f"{who} entró a «{name}»" if kind == "join" else f"{who} salió de «{name}»"
            notify.send(ctx, name, "players", text)
    for gone in set(states) - live:
        states.pop(gone, None)


def start(ctx):
    global _started
    if _started:
        return
    _started = True
    states = {}

    def loop():
        while True:
            try:
                tick(ctx, states)
            except Exception:
                pass
            time.sleep(3)
    threading.Thread(target=loop, daemon=True).start()
