"""Crear servidores nuevos, desde una plantilla o desde un modpack."""

import re

from modnex import plugins
from modnex.infra import db
from modnex.services import extras
from modnex.services import modpacks
from modnex.services import templates
from modnex.config import MEM_RE, NAME_RE, SERVERS_DIR
from modnex.services.servers import used_ports


def create_server(user, b, ctx):
    name = str(b.get("name", "")).strip()
    if not NAME_RE.fullmatch(name) or len(name) > 40:
        raise ValueError("nombre no válido (letras, números, puntos, guiones y guiones bajos; máximo 40)")
    if (SERVERS_DIR / name).exists():
        raise ValueError("ya existe una carpeta con ese nombre")
    template = b.get("template", "")
    if template not in templates.TEMPLATES:
        raise ValueError("plantilla no válida")
    mc = str(b.get("mc", ""))
    if mc not in templates.versions(template):
        raise ValueError(f"{templates.TEMPLATES[template]['label']} no tiene la versión {mc}")
    if b.get("accept_eula") is not True:
        raise ValueError("debes aceptar el EULA de Minecraft para crear el servidor")
    memory = str(b.get("memory") or "4G")
    if not MEM_RE.fullmatch(memory):
        raise ValueError("memoria no válida (ej. 4G o 4096M)")
    used = used_ports()
    if b.get("port") in (None, "", 0):
        port = next(p for p in range(25565, 25700) if p not in used)
    else:
        port = int(b["port"])
        if not 1024 <= port <= 65535:
            raise ValueError("el puerto debe estar entre 1024 y 65535")
        if port in used:
            raise ValueError(f"el puerto {port} ya lo usa otro servidor")
    display = str(b.get("display_name") or "").strip()[:40]
    loader_version = b.get("loader_version") or None
    if loader_version is not None and not re.fullmatch(r"[0-9A-Za-z._+-]{1,40}", str(loader_version)):
        raise ValueError("versión del loader no válida")
    wanted = extras.validate(b.get("extras"), templates.loader_of(template) or template)   # Vanilla no tiene cargador

    def on_done(n):
        db.sync_servers([n])
        db.audit(user, n, "crear servidor", f"{template} {mc}")
        extras.run(ctx, n, wanted, user)
        plugins.emit("server_created", n)

    perf = b.get("perf", True) is not False
    job = templates.start_job(SERVERS_DIR, name, template, mc, memory, port, display,
                              str(loader_version) if loader_version else None, on_done, perf=perf)
    db.audit(user, name, "iniciar creación", f"{template} {mc} · puerto {port} · {memory}")
    return job


def create_modpack_server(user, b, ctx):
    name = str(b.get("name", "")).strip()
    if not NAME_RE.fullmatch(name) or len(name) > 40:
        raise ValueError("nombre no válido (letras, números, puntos, guiones y guiones bajos; máximo 40)")
    if (SERVERS_DIR / name).exists():
        raise ValueError("ya existe una carpeta con ese nombre")
    source = b.get("source", "")
    if source not in ("modrinth", "curseforge"):
        raise ValueError("fuente no válida")
    project = str(b.get("project", ""))
    version_id = str(b.get("version", ""))
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", project) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", version_id):
        raise ValueError("modpack o versión no válidos")
    if b.get("accept_eula") is not True:
        raise ValueError("debes aceptar el EULA de Minecraft para crear el servidor")
    memory = str(b.get("memory") or "6G")
    if not MEM_RE.fullmatch(memory):
        raise ValueError("memoria no válida (ej. 6G o 6144M)")
    used = used_ports()
    if b.get("port") in (None, "", 0):
        port = next(p for p in range(25565, 25700) if p not in used)
    else:
        port = int(b["port"])
        if not 1024 <= port <= 65535:
            raise ValueError("el puerto debe estar entre 1024 y 65535")
        if port in used:
            raise ValueError(f"el puerto {port} ya lo usa otro servidor")
    display = str(b.get("display_name") or "").strip()[:40]
    wanted = extras.validate(b.get("extras"))   # el cargador de un modpack se sabe al instalarlo: si no encaja, se omite

    def on_done(n):
        db.sync_servers([n])
        db.audit(user, n, "crear servidor desde modpack", f"{source}:{project}:{version_id}")
        extras.run(ctx, n, wanted, user)
        plugins.emit("server_created", n)

    job = modpacks.start_job(SERVERS_DIR, name, source, project, version_id, memory, port, display,
                             bool(b.get("include_client", True)), on_done)
    db.audit(user, name, "iniciar creación desde modpack", f"{source}:{project} · puerto {port} · {memory}")
    return job
