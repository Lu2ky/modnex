"""Filtro de mods de cliente basado en el arranque real del servidor.

Cuando un servidor cae al arrancar, la traza suele nombrar el mod culpable:
- NeoForge: "Attempted to load class X for invalid dist DEDICATED_SERVER" y el
  frame TRANSFORMER/<modid>@... o el nombre del handler de mixin.
- Java: "Module M not found, required by P" (un mod trae un módulo que el
  servidor no tiene, p. ej. LWJGL del cliente).

Este módulo identifica el jar de ese mod y lo mueve a .removed-client-mods/mods/.
Nunca borra: la cuarentena se puede revertir moviendo el jar de vuelta.
"""
import re
import shutil
import zipfile
from pathlib import Path

QUARANTINE = ".removed-client-mods"

_DIST_ERR = re.compile(r"invalid dist DEDICATED_SERVER")
_MODULE_ERR = re.compile(r"Module ([\w.]+) not found, required by ([\w.]+)")
_FRAME_MOD = re.compile(r"TRANSFORMER/([a-z0-9_\-.]+)@")
_HANDLER = re.compile(r"handler\$[^\s(]+")
_MODID = re.compile(r'modId\s*=\s*"([^"]+)"')
_FABRIC_ID = re.compile(r'"id"\s*:\s*"([^"]+)"')
CORE = {"minecraft", "neoforge", "fml_loader", "modlauncher", "bootstraplauncher",
        "securejarhandler", "forge", "fml", "javafmlmod", "java"}


def clean(text):
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def modid_map(mods_dir):
    """modId -> nombre del jar, leyendo neoforge.mods.toml / mods.toml / fabric.mod.json."""
    out = {}
    for jar in sorted(Path(mods_dir).glob("*.jar")):
        try:
            with zipfile.ZipFile(jar) as z:
                names = z.namelist()
                for meta in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml"):
                    if meta in names:
                        m = _MODID.search(z.read(meta).decode("utf-8", "ignore"))
                        if m:
                            out.setdefault(m.group(1), jar.name)
                if "fabric.mod.json" in names:
                    m = _FABRIC_ID.search(z.read("fabric.mod.json").decode("utf-8", "ignore"))
                    if m:
                        out.setdefault(m.group(1), jar.name)
        except (zipfile.BadZipFile, OSError):
            continue
    return out


def jars_with_package(mods_dir, pkg_path):
    """Jars de mods que contienen (directa o anidada) la ruta de un paquete, p. ej. org/lwjgl/tinyexr/."""
    hits = []
    for jar in sorted(Path(mods_dir).glob("*.jar")):
        try:
            with zipfile.ZipFile(jar) as z:
                if any(pkg_path in n for n in z.namelist()):
                    hits.append(jar.name)
        except (zipfile.BadZipFile, OSError):
            continue
    return hits


_FATAL = re.compile(r"Caused by: java\.lang\.RuntimeException: Attempted to load class")


def _culprit_mods(text, mids):
    """Mods de la traza fatal (ventana alrededor de la excepción que lleva el error de dist)."""
    lines = text.splitlines()
    hits = [i for i, l in enumerate(lines) if _FATAL.search(l)]
    idx = hits[-1] if hits else None  # la excepción fatal es la última que se imprime
    if idx is None:
        return set()
    window = "\n".join(lines[max(0, idx - 80): idx + 40])
    names = set()
    for h in _HANDLER.finditer(window):
        for mid in mids:
            if mid not in CORE and f"${mid}$" in h.group(0) + "$":
                names.add(mid)
    for m in _FRAME_MOD.finditer(window):
        mid = m.group(1)
        if mid not in CORE and mid in mids:
            names.add(mid)
    return names


def diagnose(log_text, mods_dir):
    """Devuelve (candidatos, ambiguo). candidatos = [(jar, motivo)]. Solo se actúa si hay un único candidato."""
    text = clean(log_text)
    found = []
    mids = modid_map(mods_dir) if _DIST_ERR.search(text) else {}
    if mids:
        for mid in sorted(_culprit_mods(text, mids)):
            found.append((mids[mid], f"carga clases de cliente en servidor (modid {mid})"))
    for m in _MODULE_ERR.finditer(text):
        required = m.group(1)
        pkg = required.replace(".", "/") + "/"
        for jar in jars_with_package(mods_dir, pkg):
            found.append((jar, f"necesita el módulo {required}, que solo existe en el cliente"))
    seen, out = set(), []
    for jar, why in found:
        if jar not in seen:
            seen.add(jar)
            out.append((jar, why))
    return out, len(out) > 1


def quarantine(server_dir, jar_name):
    """Mueve mods/<jar> a .removed-client-mods/mods/<jar>. Devuelve la ruta destino o None."""
    src = Path(server_dir) / "mods" / jar_name
    if not src.exists():
        return None
    dst = Path(server_dir) / QUARANTINE / "mods" / jar_name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return dst
