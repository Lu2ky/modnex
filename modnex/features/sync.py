"""Sincronización de clientes con AutoModpack (LGPL-3.0, mod aparte; no se incluye su código).

Se prueba primero en una copia aislada del servidor (sin el mundo) para ver qué publicaría a los
clientes. Instalarlo en el servidor real exige haber pasado esa prueba, el servidor parado y una copia
de seguridad previa. Las pruebas funcionan con el servidor real en marcha porque se limita la memoria
del entorno y se baja su prioridad de CPU; aun así puede notarse un instante de carga.
"""
import json
import re
import shutil
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import backups, safeupdate as su

API = "https://api.modrinth.com/v2/project/automodpack/version"
CDN = "cdn.modrinth.com"
SAFE_TOKEN = re.compile(r"[A-Za-z0-9._\-]{1,40}")
TEST_XMX_MB = 4096
JOBS = {}
# AutoModpack 4.x escribe «Certificate fingerprint: …» y 5.x «AutoModpack host certificate fingerprint: …»
FP_RE = re.compile(r"certificate fingerprint:\s*([0-9a-f]{64})", re.I)
CONFIG_KEYS = ("modpackHost", "autoExcludeServerSideMods", "requireAutoModpackOnClient", "bindPort", "syncedFiles", "allowEditsInFiles")


class SyncError(Exception):
    pass


def _paths(ctx, name):
    base = Path(ctx.config().get("sandbox_dir") or (Path(ctx.here) / "sandbox"))
    return base, base / "cache" / name


def resolve_version(ctx, name, fetch=None):
    """Última versión estable para el cargador y la versión de Minecraft del servidor."""
    v = ctx.server_versions(name)
    loader, mc = str(v.get("loader") or ""), str(v.get("minecraft") or "")
    if not (SAFE_TOKEN.fullmatch(loader) and SAFE_TOKEN.fullmatch(mc)):
        raise SyncError("no se pudo determinar el cargador y la versión de Minecraft del servidor")
    q = urllib.parse.urlencode({"loaders": json.dumps([loader.lower()]), "game_versions": json.dumps([mc])})
    if fetch:
        rows = fetch(q)
    else:
        req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": "Modnex"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                rows = json.loads(r.read())
        except OSError as e:
            raise SyncError(f"no se pudo consultar Modrinth: {e}")
    stable = [x for x in rows if x.get("version_type") == "release"]
    if not stable:
        raise SyncError(f"AutoModpack no tiene una versión estable para {loader} {mc}")
    best = max(stable, key=lambda x: x.get("date_published", ""))
    f = next((x for x in best["files"] if x.get("primary")), best["files"][0])
    u = urllib.parse.urlparse(f["url"])
    if u.scheme != "https" or u.hostname != CDN or not su.JAR_NAME.fullmatch(f["filename"]):
        raise SyncError("Modrinth devolvió una descarga no válida")
    return {"version": best["version_number"], "url": f["url"], "filename": f["filename"], "sha1": (f.get("hashes") or {}).get("sha1")}


def installed(ctx, name):
    mods = Path(ctx.server_path(name)) / "mods"
    return sorted(p.name for p in mods.glob("*.jar") if p.name.lower().startswith("automodpack"))


def real_fingerprint(ctx, name):
    """Huella del certificado del servidor REAL, si ya arrancó con AutoModpack."""
    d = Path(ctx.server_path(name))
    for p in (d / "logs" / "latest.log", d / "manager-console.log"):
        try:
            hits = FP_RE.findall(p.read_text(errors="ignore")[-400_000:])
        except OSError:
            continue
        if hits:
            return hits[-1]
    return None


def summarize(sb, server_mods):
    """Qué publicaría AutoModpack, leído de lo que generó en el entorno aislado."""
    sbp = Path(sb)
    out = {"published": [], "excluded": [], "config": {}, "host_on_game_port": None}
    try:
        content = json.loads((sbp / "automodpack" / "host-modpack" / "automodpack-content.json").read_text())
        files = [x["file"] for x in content.get("list", []) if isinstance(x, dict) and "file" in x]
        out["published"] = sorted(Path(x).name for x in files if x.startswith("/mods/"))
        out["other_files"] = len([x for x in files if not x.startswith("/mods/")])
    except (OSError, ValueError):
        pass
    out["excluded"] = sorted(n for n in server_mods if n not in set(out["published"]) and not n.lower().startswith("automodpack"))
    try:
        cfg = json.loads((sbp / "automodpack" / "automodpack-server.json").read_text())
        out["config"] = {k: cfg[k] for k in CONFIG_KEYS if k in cfg}
        out["host_on_game_port"] = cfg.get("bindPort", -1) == -1
    except (OSError, ValueError):
        pass
    return out


def start_test(ctx, name, runner=None, fetch=None):
    if JOBS.get(name, {}).get("state") == "running":
        raise SyncError("ya hay una prueba en curso")
    if not su._GLOBAL.acquire(blocking=False):
        raise SyncError("ya hay otra prueba en curso en este equipo")
    JOBS[name] = {"state": "running", "step": "Consultando Modrinth…", "started": int(time.time())}
    threading.Thread(target=_work, args=(ctx, name, runner or (lambda c, sb, t: su.boot(c, sb, t, nice=True)), fetch), daemon=True).start()


def _work(ctx, name, runner, fetch):
    job = JOBS[name]
    sb = None
    try:
        ver = resolve_version(ctx, name, fetch)
        job["version"] = ver["version"]
        need = TEST_XMX_MB + 1024
        free = su.mem_available_mb()
        if free and free < need:
            raise SyncError(f"no hay memoria libre suficiente para la prueba (hacen falta ~{need} MB, hay {free} MB)")
        base, cache = _paths(ctx, name)
        cache.mkdir(parents=True, exist_ok=True)
        jar = cache / ver["filename"]
        job["step"] = "Descargando AutoModpack…"
        ctx.download(ver["url"], jar, sha1=ver["sha1"])
        job["step"] = "Preparando un entorno aislado…"
        src = Path(ctx.server_path(name))
        sb = su.make_sandbox(ctx, name, base)
        su.build_mods(src / "mods", sb, {}, cache)
        for old in installed(ctx, name):          # si ya estaba instalado, se usa la versión que se prueba
            (sb / "mods" / old).unlink(missing_ok=True)
        (sb / "mods" / ver["filename"]).symlink_to(jar.resolve())
        args = sb / "user_jvm_args.txt"
        text = args.read_text() if args.exists() else ""
        if re.search(r"-Xmx\d+[GgMm]", text):
            text = re.sub(r"-Xmx(\d+)([GgMm])", lambda m: f"-Xmx{min(su._xmx_mb(m.group(0)), TEST_XMX_MB)}M", text)
        else:
            text += f"\n-Xmx{TEST_XMX_MB}M\n"
        args.write_text(text)
        job["step"] = "Arrancando una copia del servidor con AutoModpack…"
        r = runner(ctx, sb, su.BOOT_TIMEOUT)
        if not r["ok"]:
            f = (r.get("findings") or [{}])[0]
            job.update(state="done", step="", ok=False, version=ver["version"], seconds=r.get("seconds"),
                       reason=(f.get("title", "") + (": " + f["detail"] if f.get("detail") else "")) or r.get("why") or "el servidor no arrancó",
                       finished=int(time.time()))
            return
        log = (sb / "manager-console.log")
        fp = FP_RE.findall(log.read_text(errors="ignore")) if log.exists() else []
        summ = summarize(sb, [p.name for p in (src / "mods").glob("*.jar")])
        job.update(state="done", step="", ok=True, version=ver["version"], seconds=r.get("seconds"), test_fingerprint=fp[-1] if fp else None,
                   finished=int(time.time()), **summ)
        job["_tested"] = ver
    except Exception as e:
        job.update(state="error", step="", error=str(e))
    finally:
        su._GLOBAL.release()
        if sb:
            shutil.rmtree(sb, ignore_errors=True)


def public(ctx, name):
    job = {k: v for k, v in (JOBS.get(name) or {"state": "none"}).items() if not k.startswith("_")}
    inst = installed(ctx, name)
    return {**job, "installed": inst, "fingerprint": real_fingerprint(ctx, name) if inst else None, "running": bool(ctx.status(name)["running"])}


def install(ctx, name):
    job = JOBS.get(name) or {}
    ver = job.get("_tested")
    if job.get("state") != "done" or not job.get("ok") or not ver:
        raise SyncError("primero hay que pasar la prueba con éxito")
    if ctx.status(name)["running"]:
        raise SyncError("para el servidor antes de instalarlo")
    if installed(ctx, name):
        raise SyncError("ya está instalado")
    _, cache = _paths(ctx, name)
    jar = cache / ver["filename"]
    if not jar.is_file():
        raise SyncError("falta el archivo descargado; repite la prueba")
    safety = backups.create(ctx, name, label="Antes de instalar la sincronización", kind="pre-update")
    mods = Path(ctx.server_path(name)) / "mods"
    tmp = mods / (ver["filename"] + ".part")
    shutil.copy2(jar, tmp)
    tmp.rename(mods / ver["filename"])
    return {"installed": ver["filename"], "backup": safety["id"]}


def install_in_staging(ctx, staging_name, fetch=None):
    """Pone AutoModpack en el servidor de pruebas (nunca en el real). Debe estar parado."""
    if ctx.status(staging_name)["running"]:
        raise SyncError("para el servidor de pruebas antes de instalar el mod")
    if installed(ctx, staging_name):
        raise SyncError("ya está instalado en el servidor de pruebas")
    ver = resolve_version(ctx, staging_name, fetch)
    _, cache = _paths(ctx, staging_name)
    cache.mkdir(parents=True, exist_ok=True)
    jar = cache / ver["filename"]
    ctx.download(ver["url"], jar, sha1=ver["sha1"])
    mods = Path(ctx.server_path(staging_name)) / "mods"
    tmp = mods / (ver["filename"] + ".part")
    shutil.copy2(jar, tmp)
    tmp.rename(mods / ver["filename"])
    return {"installed": ver["filename"], "version": ver["version"]}
