"""Actualización segura de mods.

Se prueba en un entorno aislado (copia del servidor sin el mundo) arrancándolo de verdad con las
actualizaciones aplicadas. Si falla, se busca qué actualización lo rompe (primero con lo que dice el
log, y después dividiendo en grupos). Solo se aplican al servidor real las que arrancan bien.
El servidor real debe estar parado durante la prueba: comparte memoria y puertos con el entorno.
"""
import os
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from . import backups, doctor

ALLOWED_HOSTS = {"cdn.modrinth.com"}
JAR_NAME = re.compile(r"[A-Za-z0-9._+\-\[\]() ]{1,200}\.jar")
COPY_DIRS = ("config", "defaultconfigs", "kubejs", "scripts", "global_packs")
COPY_FILES = ("server.properties", "eula.txt", "user_jvm_args.txt", "start.sh", ".manager.json", "ops.json", "whitelist.json")
BOOT_TIMEOUT = 300
MAX_BOOTS = 12
MAX_CANDIDATES = 60
JOBS = {}
_GLOBAL = threading.Lock()   # una prueba a la vez en toda la máquina


class UpdateError(Exception):
    pass


# ---------- candidatos ----------
def candidates(ctx, name):
    v = ctx.server_versions(name)
    rows = ctx.identify_mods(name, v.get("loader") or "neoforge", v.get("minecraft") or "1.21.1")
    existing = {r["file"] for r in rows}
    out = []
    for r in rows:
        if not (r.get("enabled") and r.get("latest") and r.get("update_url") and r.get("update_filename")):
            continue
        u = urlparse(r["update_url"])
        fn = r["update_filename"]
        if u.scheme != "https" or u.hostname not in ALLOWED_HOSTS or not JAR_NAME.fullmatch(fn) or "/" in fn or fn in existing:
            continue
        out.append({"file": r["file"], "name": r.get("name") or r["file"], "installed": r.get("installed"), "latest": r["latest"],
                    "url": r["update_url"], "filename": fn, "sha1": r.get("update_sha1")})
    return out[:MAX_CANDIDATES]


# ---------- búsqueda del culpable (pura, sin E/S) ----------
class Budget(Exception):
    pass


def find_safe(items, test, max_boots=MAX_BOOTS):
    """items: ids de actualizaciones. test(subset) -> (ok, culpables_nombrados_por_el_log).
    Devuelve {safe, bad, conflict, unknown, boots, truncated}.

    Si el conjunto falla y una mitad pasa, el fallo está en la otra: no se gasta un arranque en
    comprobarlo. Con un solo culpable bastan ~log2(n)+2 arranques. Al final se verifica una vez que
    el conjunto seguro arranca junto; si no, hay una interacción y se vuelve a buscar dentro de él."""
    memo, boots, best = {}, [0], [[]]

    def T(subset):
        key = tuple(sorted(subset))
        if key not in memo:
            if boots[0] >= max_boots:
                raise Budget()
            boots[0] += 1
            memo[key] = test(list(subset))
            if memo[key][0] and len(key) > len(best[0]):
                best[0] = list(key)
        return memo[key]

    def solve(S, culprits=None):
        """S falla (ya probado o deducido). Devuelve (seguras, malas, en conflicto)."""
        named = [x for x in S if culprits and x in set(culprits)]
        if named:
            rest = [x for x in S if x not in named]
            if not rest:
                return [], named, []
            ok, c = T(rest)
            if ok:
                return rest, named, []
            s, b, cf = solve(rest, c)
            return s, named + b, cf
        if len(S) == 1:
            return [], list(S), []
        mid = len(S) // 2
        A, B = S[:mid], S[mid:]
        okA, cA = T(A)
        if okA:
            sB, bB, cfB = solve(B)  # el fallo debe estar en B
            if set(sB) == set(B):   # B entera funciona sola: las dos mitades chocan entre sí
                keep, drop = (A, B) if len(A) >= len(B) else (B, A)
                return keep, [], drop
            return A + sB, bB, cfB
        sA, bA, cfA = solve(A, cA)
        okB, cB = T(B)
        if okB:
            return sA + B, bA, cfA
        sB, bB, cfB = solve(B, cB)
        return sA + sB, bA + bB, cfA + cfB

    try:
        ok, c = T(list(items)) if items else (True, [])
        if ok:
            safe, bad, conflict = list(items), [], []
        else:
            safe, bad, conflict = solve(list(items), c)
            for _ in range(3):  # verificación final del conjunto seguro, junto
                if not safe or T(safe)[0]:
                    break
                s2, b2, cf2 = solve(safe, T(safe)[1])
                conflict += [x for x in safe if x not in s2] if not (b2 or cf2) else []
                bad += b2; conflict += cf2; safe = s2
        truncated = False
    except Budget:
        safe, bad, conflict, truncated = best[0], [], [], True
    decided = set(safe) | set(bad) | set(conflict)
    return {"safe": safe, "bad": bad, "conflict": conflict, "unknown": [x for x in items if x not in decided],
            "boots": boots[0], "truncated": truncated}


# ---------- entorno aislado ----------
def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _xmx_mb(args_text):
    m = re.search(r"-Xmx(\d+)([GgMm])", args_text or "")
    if not m:
        return 2048
    return int(m.group(1)) * (1024 if m.group(2).lower() == "g" else 1)


def mem_available_mb():
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except OSError:
        pass
    return 0


def make_sandbox(ctx, name, base):
    src = Path(ctx.server_path(name))
    sb = Path(base) / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"
    sb.mkdir(parents=True)
    for d in COPY_DIRS:
        if (src / d).is_dir():
            shutil.copytree(src / d, sb / d, symlinks=False, ignore_dangling_symlinks=True)
    if (src / "libraries").is_dir():
        (sb / "libraries").symlink_to((src / "libraries").resolve())
    for f in COPY_FILES:
        if (src / f).is_file():
            shutil.copy2(src / f, sb / f)
    props = (sb / "server.properties").read_text() if (sb / "server.properties").exists() else ""
    kv = {}
    for line in props.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition("=")
            kv[k.strip()] = v
    kv.update({"server-port": str(_free_port()), "level-name": "sandbox-world", "enable-rcon": "false", "enable-query": "false",
               "motd": "Modnex: prueba de actualización"})
    (sb / "server.properties").write_text("\n".join(f"{k}={v}" for k, v in kv.items()) + "\n")
    (sb / "mods").mkdir()
    return sb


def build_mods(src_mods, sb, replace, cache):
    """Rellena sandbox/mods con enlaces: los originales, salvo los reemplazados por su versión nueva."""
    mods = Path(sb) / "mods"
    for f in list(mods.iterdir()):
        f.unlink()
    for f in sorted(Path(src_mods).glob("*.jar")):
        if f.name in replace:
            (mods / replace[f.name]).symlink_to(Path(cache) / replace[f.name])
        else:
            (mods / f.name).symlink_to(f.resolve())


def boot(ctx, sb, timeout=BOOT_TIMEOUT, nice=False):
    """Arranca el entorno. Devuelve {ok, seconds, findings, tail}."""
    env = dict(os.environ, JAVA_BIN=ctx.java_bin())
    logp = Path(sb) / "manager-console.log"
    t0 = time.time()
    with open(logp, "wb") as lf:
        proc = subprocess.Popen((["nice", "-n", "19"] if nice else []) + ["bash", "start.sh"], cwd=sb, env=env, stdin=subprocess.PIPE, stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
    ok, why = False, ""
    while True:
        time.sleep(0.4)
        txt = doctor.clean(logp.read_text(errors="ignore")[-300_000:])
        if "Done (" in txt:
            ok = True
            break
        if proc.poll() is not None:
            why = "el servidor se cerró antes de terminar de arrancar"
            break
        if time.time() - t0 > timeout:
            why = "no terminó de arrancar a tiempo"
            break
    try:
        if ok and proc.poll() is None:
            proc.stdin.write(b"stop\n"); proc.stdin.flush()
            try:
                proc.wait(60)
            except subprocess.TimeoutExpired:
                pass
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(10)
    except (OSError, ProcessLookupError):
        pass
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
    txt = doctor.clean(logp.read_text(errors="ignore")[-300_000:])
    findings = [] if ok else doctor.analyze(txt, Path(sb) / "mods")
    return {"ok": ok, "seconds": round(time.time() - t0, 1), "why": why, "findings": findings, "tail": txt[-1500:]}


# ---------- trabajo completo ----------
def start_job(ctx, name, runner=None):
    """Lanza la prueba en segundo plano. `runner(ctx, sb, timeout)` sustituye a boot() en las pruebas."""
    if JOBS.get(name, {}).get("state") == "running":
        raise UpdateError("ya hay una prueba en curso para este servidor")
    if ctx.status(name)["running"]:
        raise UpdateError("para el servidor antes de probar: la prueba usa su memoria y sus puertos")
    if not _GLOBAL.acquire(blocking=False):
        raise UpdateError("ya hay otra prueba de actualización en curso en este equipo")
    JOBS[name] = {"state": "running", "step": "Buscando actualizaciones…", "boots": 0, "started": int(time.time())}
    threading.Thread(target=_work, args=(ctx, name, runner or boot), daemon=True).start()


def _work(ctx, name, runner):
    job = JOBS[name]
    sb = None
    try:
        cands = candidates(ctx, name)
        job["candidates"] = [{k: c[k] for k in ("file", "name", "installed", "latest")} for c in cands]
        if not cands:
            job.update(state="done", step="", safe=[], bad=[], conflict=[], unknown=[], note="No hay actualizaciones disponibles.")
            return
        src = Path(ctx.server_path(name))
        args = (src / "user_jvm_args.txt").read_text() if (src / "user_jvm_args.txt").exists() else ""
        need = _xmx_mb(args) + 1024
        if mem_available_mb() and mem_available_mb() < need:
            raise UpdateError(f"no hay memoria libre suficiente para la prueba (hacen falta ~{need} MB, hay {mem_available_mb()} MB)")
        base = Path(ctx.config().get("sandbox_dir") or (Path(ctx.here) / "sandbox"))
        job["step"] = "Descargando las versiones nuevas…"
        cache = base / "cache" / name
        cache.mkdir(parents=True, exist_ok=True)
        by_file = {c["file"]: c for c in cands}
        for c in cands:
            ctx.download(c["url"], cache / c["filename"], sha1=c.get("sha1"))
        sb = make_sandbox(ctx, name, base)
        details = {}

        def test(subset):
            job["step"] = f"Probando {len(subset)} actualización(es) en un entorno aislado…"
            build_mods(src / "mods", sb, {f: by_file[f]["filename"] for f in subset}, cache)
            r = runner(ctx, sb, BOOT_TIMEOUT)
            job["boots"] = job.get("boots", 0) + 1
            culprits = []
            if not r["ok"]:
                for fnd in r.get("findings", []):
                    for j in fnd.get("mods", []) or []:
                        new_to_old = {by_file[f]["filename"]: f for f in subset}
                        if j in new_to_old:
                            culprits.append(new_to_old[j])
                for f in culprits:
                    details[f] = [r]
                if len(subset) == 1:
                    details[subset[0]] = [r]
            return r["ok"], culprits

        res = find_safe(list(by_file), test)
        bad = []
        for f in res["bad"] + res["conflict"]:
            last = (details.get(f) or [{}])[-1]
            fnd = last.get("findings") or []
            bad.append({"file": f, "name": by_file[f]["name"], "installed": by_file[f]["installed"], "latest": by_file[f]["latest"],
                        "kind": "conflict" if f in res["conflict"] else "bad",
                        "reason": (fnd[0]["title"] + ": " + fnd[0]["detail"]) if fnd else (last.get("why") or "no arranca con esta actualización")})
        job.update(state="done", step="", safe=[{k: by_file[f][k] for k in ("file", "name", "installed", "latest")} for f in res["safe"]],
                   bad=bad, unknown=[by_file[f]["name"] for f in res["unknown"]], boots=res["boots"], truncated=res["truncated"],
                   finished=int(time.time()))
        job["_plan"] = {f: by_file[f] for f in res["safe"]}
    except Exception as e:
        job.update(state="error", step="", error=str(e))
    finally:
        _GLOBAL.release()
        if sb:
            shutil.rmtree(sb, ignore_errors=True)


def public(job):
    return {k: v for k, v in (job or {}).items() if not k.startswith("_")}


# ---------- aplicar ----------
def apply(ctx, name, files):
    job = JOBS.get(name) or {}
    plan = job.get("_plan")
    if job.get("state") != "done" or plan is None:
        raise UpdateError("primero hay que probar las actualizaciones")
    if ctx.status(name)["running"]:
        raise UpdateError("para el servidor antes de aplicar las actualizaciones")
    chosen = [f for f in files if f in plan]
    if not chosen or len(chosen) != len(set(files)):
        raise UpdateError("solo se pueden aplicar actualizaciones que pasaron la prueba")
    safety = backups.create(ctx, name, label="Antes de actualizar mods", kind="pre-update")
    mods = Path(ctx.server_path(name)) / "mods"
    cache = Path(ctx.config().get("sandbox_dir") or (Path(ctx.here) / "sandbox")) / "cache" / name
    done = []
    for f in chosen:
        c = plan[f]
        new, old = mods / c["filename"], mods / f
        if not old.is_file():
            continue
        tmp = mods / (c["filename"] + ".part")
        if (cache / c["filename"]).is_file():
            shutil.copy2(cache / c["filename"], tmp)
        else:
            ctx.download(c["url"], tmp, sha1=c.get("sha1"))
        tmp.rename(new)
        old.unlink()
        done.append(f)
    JOBS[name]["_plan"] = {k: v for k, v in plan.items() if k not in done}
    return {"applied": done, "backup": safety["id"]}
