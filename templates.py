"""Plantillas para crear servidores: Vanilla, Fabric, NeoForge, Forge y Paper.

Cada plantilla sabe qué versiones ofrece, cómo descargar o instalar su servidor y qué tipo de
contenido admite: mods (NeoForge, Forge, Fabric), plugins (Paper) o nada (Vanilla).
Las descargas van a fuentes oficiales y se comprueban con su hash cuando la API lo da.
"""
import hashlib
import json
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

UA = "modnex-server-manager/1.0 (local)"
RUNTIME_JAVA = Path("/home/luky/servers/.runtime/java21/bin/java")
MAX_DOWNLOAD = 1024 * 1024 * 1024
MC_RE = re.compile(r"\d+\.\d+(\.\d+)?")

TEMPLATES = {
    "vanilla": {"label": "Vanilla", "kind": "none", "loader": None,
                "desc": "El servidor oficial de Mojang. Sin mods ni plugins; admite datapacks."},
    "fabric": {"label": "Fabric", "kind": "mod", "loader": "fabric",
               "desc": "Mods ligeros y actualizados rápido. Compatible con Sodium, Lithium y similares."},
    "neoforge": {"label": "NeoForge", "kind": "mod", "loader": "neoforge",
                 "desc": "Mods grandes de contenido, como Cobblemon, Create o AE2."},
    "forge": {"label": "Forge", "kind": "mod", "loader": "forge",
              "desc": "El loader clásico, con el catálogo de mods más antiguo."},
    "paper": {"label": "Paper", "kind": "plugin", "loader": "paper",
              "desc": "Servidor optimizado para plugins de Bukkit y Spigot. Sin mods de cliente."},
}


# Preset de rendimiento: mods que se instalan por defecto y que solo corren en el servidor.
# Cada uno se investigó en Modrinth: qué hace, en qué lados corre y si tiene versión para 1.21.1.
PERF_PRESETS = {
    "neoforge": [
        ("ferrite-core", "FerriteCore", "Reduce el uso de memoria de modelos y estados de bloques."),
        ("lithium", "Lithium", "Optimiza la lógica del juego: ticks, mobs, IA, caminos y redstone."),
        ("modernfix", "ModernFix", "Arranque más rápido y menos memoria; corrige fallos conocidos."),
        ("c2me-neoforge", "C2ME", "Carga y generación de chunks en varios hilos."),
        ("krypton-fnp", "Krypton", "Optimiza la pila de red para reducir latencia y tráfico."),
        ("alternate-current", "Alternate Current", "Redstone más eficiente sin cambiar su comportamiento."),
        ("noisiumforked", "Noisium", "Acelera la generación del terreno."),
    ],
    "fabric": [
        ("ferrite-core", "FerriteCore", "Reduce el uso de memoria de modelos y estados de bloques."),
        ("lithium", "Lithium", "Optimiza la lógica del juego: ticks, mobs, IA, caminos y redstone."),
        ("modernfix", "ModernFix", "Arranque más rápido y menos memoria; corrige fallos conocidos."),
        ("c2me-fabric", "C2ME", "Carga y generación de chunks en varios hilos."),
        ("krypton", "Krypton", "Optimiza la pila de red para reducir latencia y tráfico."),
        ("vmp-fabric", "Very Many Players", "Pensado para servidores con muchos jugadores a la vez."),
        ("alternate-current", "Alternate Current", "Redstone más eficiente sin cambiar su comportamiento."),
        ("noisiumforked", "Noisium", "Acelera la generación del terreno."),
        ("scalablelux", "ScalableLux", "Cálculo de iluminación más rápido (basado en Starlight)."),
    ],
    "forge": [
        ("krypton-fnp", "Krypton", "Optimiza la pila de red para reducir latencia y tráfico."),
    ],
}


def perf_list(template):
    """Mods del preset de rendimiento para una plantilla (vacío si no hay ninguno para ella)."""
    return [{"slug": a, "title": b, "desc": c} for a, b, c in PERF_PRESETS.get(template, [])]


def install_perf(template, mc, dest):
    """Descarga el preset de rendimiento desde Modrinth para la versión del servidor.
    Devuelve un informe por mod; un fallo no detiene la creación del servidor."""
    loader = loader_of(template)
    report = []
    if not loader or template not in PERF_PRESETS:
        return report
    folder = Path(dest) / folder_for(template)
    folder.mkdir(exist_ok=True)
    for slug, title, _ in PERF_PRESETS[template]:
        try:
            proj = _get_json(f"https://api.modrinth.com/v2/project/{urllib.parse.quote(slug)}")
            vs = _get_json("https://api.modrinth.com/v2/project/" + urllib.parse.quote(slug) + "/version?" + urllib.parse.urlencode(
                {"loaders": json.dumps([loader]), "game_versions": json.dumps([mc])}))
        except Exception as e:  # noqa: BLE001 - el informe lo muestra; no se aborta la creación
            report.append({"slug": slug, "title": title, "status": "error", "note": f"No se pudo consultar: {e}"})
            continue
        if not vs:
            report.append({"slug": slug, "title": title, "status": "unavailable",
                           "note": f"Sin versión para Minecraft {mc} y {loader}"})
            continue
        v = vs[0]
        f = next((x for x in v["files"] if x.get("primary")), v["files"][0])
        fname = f["filename"]
        if not re.fullmatch(r"[A-Za-z0-9._+\-\[\]() ]+\.jar", fname) or fname != Path(fname).name:
            report.append({"slug": slug, "title": title, "status": "error", "note": "nombre de archivo no válido"})
            continue
        try:
            _download(f["url"], folder / fname, sha1=f["hashes"].get("sha1"))
        except Exception as e:  # noqa: BLE001
            report.append({"slug": slug, "title": title, "status": "error", "note": str(e)})
            continue
        report.append({"slug": slug, "title": proj.get("title", title), "status": "ok",
                       "version": v["version_number"], "filename": fname})
    return report


def template_info(name):
    return TEMPLATES.get(name)


def loader_of(template):
    return TEMPLATES[template]["loader"] if template in TEMPLATES else None


def kind_of(template):
    return TEMPLATES[template]["kind"] if template in TEMPLATES else "mod"


def folder_for(template):
    """Carpeta donde viven los jars que se añaden: plugins para Paper, mods para el resto."""
    return "plugins" if template == "paper" else "mods"


# ---------- HTTP ----------

def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _get_json(url):
    return json.loads(_get(url, timeout=30))


def _download(url, dest, sha1=None, sha256=None):
    """Descarga con límite de tamaño y comprobación de hash. Borra el archivo si algo falla."""
    h1, h2 = (hashlib.sha1() if sha1 else None), (hashlib.sha256() if sha256 else None)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as fh:
            total = 0
            while chunk := r.read(1 << 16):
                total += len(chunk)
                if total > MAX_DOWNLOAD:
                    raise ValueError("la descarga supera el límite de 1 GB")
                fh.write(chunk)
                if h1: h1.update(chunk)
                if h2: h2.update(chunk)
        if sha1 and h1.hexdigest() != sha1:
            raise ValueError("el SHA-1 de la descarga no coincide")
        if sha256 and h2.hexdigest() != sha256:
            raise ValueError("el SHA-256 de la descarga no coincide")
    except BaseException:
        Path(dest).unlink(missing_ok=True)
        raise


# ---------- versiones disponibles ----------

_CACHE = {}
_CACHE_LOCK = threading.Lock()


def _cached(key, fn, ttl=900):
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    value = fn()
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), value)
    return value


def _mojang_releases():
    m = _get_json("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")
    return [v["id"] for v in m["versions"] if v["type"] == "release"]


def _fabric_games():
    return [g["version"] for g in _get_json("https://meta.fabricmc.net/v2/versions/game") if g.get("stable")]


def _neoforge_maven():
    root = ET.fromstring(_get("https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"))
    return [v.text for v in root.iter("version")]


def _forge_maven():
    root = ET.fromstring(_get("https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"))
    return [v.text for v in root.iter("version")]


def _paper_versions():
    data = _get_json("https://fill.papermc.io/v3/projects/paper")
    out = []
    for group in data.get("versions", {}).values():
        out.extend(group)
    return [v for v in out if MC_RE.fullmatch(v)]


def versions(template):
    """Versiones de Minecraft que ofrece una plantilla, de la más nueva a la más antigua."""
    if template not in TEMPLATES:
        raise ValueError("plantilla no válida")
    if template == "vanilla":
        return _cached("vanilla", _mojang_releases)
    if template == "fabric":
        return _cached("fabric", _fabric_games)
    if template == "paper":
        return _cached("paper", _paper_versions)
    if template == "neoforge":
        # NeoForge usa 21.1.x para Minecraft 1.21.1 (los dos primeros números son el MC sin el 1).
        def names():
            mc = {}
            for v in _cached("neoforge-maven", _neoforge_maven, ttl=1800):
                if v.startswith(("0.", "snapshot")) or "beta" in v:
                    continue
                parts = v.split(".")
                if len(parts) < 3 or not parts[0].isdigit():
                    continue
                key = _nf_to_mc(v)
                mc.setdefault(key, []).append(v)
            return mc
        mc = _cached("neoforge-map", names, ttl=1800)
        return sorted(mc.keys(), key=_mc_key, reverse=True)
    if template == "forge":
        def names():
            mc = {}
            for v in _cached("forge-maven", _forge_maven, ttl=1800):
                if "-" in v:
                    m, _, _ = v.partition("-")
                    mc.setdefault(m, []).append(v)
            return mc
        mc = _cached("forge-map", names, ttl=1800)
        return sorted(mc.keys(), key=_mc_key, reverse=True)
    raise ValueError("plantilla no válida")


def _mc_key(v):
    return tuple(int(x) for x in v.split(".") if x.isdigit())


# ---------- instalación ----------

def _java():
    return str(RUNTIME_JAVA) if RUNTIME_JAVA.exists() else "java"


def _run_installer(dest, jar_url, version_label, expect):
    """Descarga un instalador de NeoForge/Forge y lo ejecuta con --installServer."""
    inst = dest / "installer.jar"
    _download(jar_url, inst)
    try:
        r = subprocess.run([_java(), "-jar", str(inst), "--installServer", str(dest)],
                           cwd=dest, capture_output=True, text=True, timeout=1500)
        if r.returncode != 0 or not expect(dest):
            tail = (r.stdout + r.stderr).strip().splitlines()[-6:]
            raise RuntimeError(f"el instalador de {version_label} falló: " + " | ".join(tail))
    finally:
        inst.unlink(missing_ok=True)
        for log in dest.glob("*.jar.log"):
            log.unlink(missing_ok=True)


def install(template, mc, dest, loader_version=None):
    """Deja en dest el servidor listo para arrancar. Devuelve el script de arranque (lo escribe el llamante)."""
    if template == "vanilla":
        m = _get_json("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")
        url = next(v["url"] for v in m["versions"] if v["id"] == mc)
        info = _get_json(url)["downloads"]["server"]
        _download(info["url"], dest / "server.jar", sha1=info["sha1"])
        return {"jar": "server.jar"}
    if template == "paper":
        b = _get_json(f"https://fill.papermc.io/v3/projects/paper/versions/{mc}/builds/latest")
        d = b["downloads"]["server:default"]
        _download(d["url"], dest / "server.jar", sha256=d["checksums"]["sha256"])
        return {"jar": "server.jar"}
    if template == "fabric":
        loaders = _get_json("https://meta.fabricmc.net/v2/versions/loader")
        ld = loader_version or next(x["version"] for x in loaders if x.get("stable"))
        inst = _get_json("https://meta.fabricmc.net/v2/versions/installer")
        ins = next(x["version"] for x in inst if x.get("stable"))
        _download(f"https://meta.fabricmc.net/v2/versions/loader/{urllib.parse.quote(mc)}/{ld}/{ins}/server/jar",
                  dest / "server.jar")
        return {"jar": "server.jar", "loader_version": ld}
    if template == "neoforge":
        v = loader_version
        if not v:
            cands = [x for x in _cached("neoforge-maven", _neoforge_maven, ttl=1800)
                     if x.startswith(_nf_prefix(mc)) and "beta" not in x]
            if not cands:
                raise ValueError(f"NeoForge no tiene versión para Minecraft {mc}")
            v = cands[-1]
        url = f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{v}/neoforge-{v}-installer.jar"
        _run_installer(dest, url, f"NeoForge {v}",
                       lambda d: any((d / "libraries" / "net" / "neoforged" / "neoforge").glob("*/unix_args.txt")))
        return {"args": "neoforge", "loader_version": v}
    if template == "forge":
        if not loader_version:
            cands = [x for x in _cached("forge-maven", _forge_maven, ttl=1800) if x.startswith(mc + "-")]
            if not cands:
                raise ValueError(f"Forge no tiene versión para Minecraft {mc}")
            loader_version = cands[-1]
        v = loader_version
        url = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{v}/forge-{v}-installer.jar"
        _run_installer(dest, url, f"Forge {v}",
                       lambda d: any((d / "libraries" / "net" / "minecraftforge" / "forge").glob("*/unix_args.txt")))
        return {"args": "forge", "loader_version": v}
    raise ValueError("plantilla no válida")


def _nf_to_mc(v):
    """Versión de NeoForge (21.1.265) a versión de Minecraft (1.21.1). Desde Minecraft 26 no hay «1.»."""
    p = v.split(".")
    if int(p[0]) >= 26:
        return f"{p[0]}.{p[1]}" if p[1] != "0" else p[0]
    return f"1.{p[0]}.{p[1]}" if p[1] != "0" else f"1.{p[0]}"


def _nf_prefix(mc):
    """Prefijo de versiones de NeoForge para una versión de Minecraft: 1.21.1 -> '21.1.', 26.3 -> '26.3.'."""
    parts = mc.split(".")
    if parts[0] == "1":
        return f"{parts[1]}.{parts[2] if len(parts) > 2 else '0'}."
    return f"{parts[0]}.{parts[1] if len(parts) > 1 else '0'}."


def start_script(template, dest, info):
    """Script de arranque con el Java del gestor y los argumentos adecuados para cada plantilla."""
    java = _java()
    if info.get("args") in ("neoforge", "forge"):
        base = Path(dest) / "libraries"
        found = sorted(base.glob("net/neoforged/neoforge/*/unix_args.txt" if info["args"] == "neoforge"
                                 else "net/minecraftforge/forge/*/unix_args.txt"))
        args = "@" + str(found[-1].relative_to(dest)) if found else "@libraries/unix_args.txt"
        cmd = f'exec "$JAVA" @user_jvm_args.txt {args} nogui "$@"'
    else:
        cmd = 'exec "$JAVA" @user_jvm_args.txt -jar server.jar nogui "$@"'
    return f'''#!/usr/bin/env bash
# Arranque generado por el gestor ({template}).
cd "$(dirname "$0")"
JAVA="${{JAVA_BIN:-{java}}}"
{cmd}
'''


def write_properties(dest, port, motd):
    (Path(dest) / "server.properties").write_text(
        "\n".join([
            "enable-jmx-monitoring=false", "level-name=world", "motd=" + motd.replace("\n", " ")[:59],
            "max-players=20", "online-mode=true", f"server-port={port}", "white-list=false",
            "view-distance=10", "simulation-distance=10", "enable-command-block=false", "spawn-protection=16",
            "difficulty=easy", "gamemode=survival", "pvp=true", "allow-flight=false",
        ]) + "\n")


# ---------- trabajos de creación (en segundo plano, con estado consultable) ----------

JOBS = {}
JOBS_LOCK = threading.Lock()
STEPS = ["Preparando la carpeta", "Descargando e instalando el servidor", "Instalando el preset de rendimiento",
         "Escribiendo la configuración", "Listo"]


def _set(job, **kw):
    with JOBS_LOCK:
        JOBS[job].update(kw)


def start_job(servers_dir, name, template, mc, memory, port, display_name, loader_version, on_done, perf=False):
    job = uuid.uuid4().hex[:16]
    with JOBS_LOCK:
        JOBS[job] = {"state": "running", "step": 0, "steps": STEPS, "error": None, "server": name, "perf": []}
    t = threading.Thread(target=_run, args=(job, servers_dir, name, template, mc, memory, port,
                                            display_name, loader_version, on_done, perf), daemon=True)
    t.start()
    return job


def _run(job, servers_dir, name, template, mc, memory, port, display_name, loader_version, on_done, perf=False):
    dest = Path(servers_dir) / name
    try:
        _set(job, step=0)
        dest.mkdir(parents=True, exist_ok=False)
        _set(job, step=1)
        info = install(template, mc, dest, loader_version)
        (dest / "eula.txt").write_text("eula=true\n")
        (dest / "user_jvm_args.txt").write_text(f"-Xmx{memory}\n-Xms{_half(memory)}\n")
        _set(job, step=2)
        if perf and template in PERF_PRESETS:
            _set(job, perf=install_perf(template, mc, dest))
        _set(job, step=3)
        write_properties(dest, port, display_name or name)
        (dest / "start.sh").write_text(start_script(template, dest, info))
        (dest / "start.sh").chmod(0o755)
        if kind_of(template) != "none":
            (dest / folder_for(template)).mkdir(exist_ok=True)
        meta = {"template": template, "mc": mc, "loader": loader_of(template),
                "loader_version": info.get("loader_version"), "created": int(time.time())}
        (dest / ".manager.json").write_text(json.dumps(meta, indent=2) + "\n")
        on_done(name)
        _set(job, step=4, state="done")
    except BaseException as e:  # noqa: BLE001 - el error se muestra al usuario
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        _set(job, state="error", error=f"{type(e).__name__}: {e}")


def _half(mem):
    m = re.fullmatch(r"(\d+)([MG])", mem)
    if not m:
        return "2G"
    n, u = int(m.group(1)), m.group(2)
    return f"{max(1, n // 2)}{u}"


def job_status(job):
    with JOBS_LOCK:
        j = JOBS.get(job)
        return dict(j) if j else None


# ---------- lectura de la plantilla de un servidor existente ----------

def server_template(dest):
    """Plantilla de un servidor: la guardada en .manager.json, o inferida de sus archivos si es anterior."""
    f = Path(dest) / ".manager.json"
    if f.exists():
        try:
            return json.loads(f.read_text()).get("template", "neoforge")
        except (ValueError, OSError):
            pass
    d = Path(dest)
    if list(d.glob("libraries/net/neoforged/neoforge/*")):
        return "neoforge"
    if list(d.glob("libraries/net/minecraftforge/forge/*")):
        return "forge"
    if (d / "plugins").is_dir() and not (d / "mods").is_dir():
        return "paper"
    if (d / "mods").is_dir():
        return "neoforge"  # servidores anteriores al gestor de plantillas: asumimos NeoForge, el caso habitual aquí
    return "vanilla"
