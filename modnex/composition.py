"""Raíz de composición: construye lo que los plugins reciben (`ctx`) y arranca el servidor HTTP."""

import os
import signal
import sys
from http.server import ThreadingHTTPServer

from modnex import plugins
from modnex.infra import db
from modnex.services import extras
from modnex.services import modpacks
from modnex.services import templates
from modnex.services.catalog import compat_for, search
from modnex.services.client import server_versions
from modnex.config import HERE, PORT, SERVERS_DIR, ensure_config, load_config
from modnex.services.identify import identify_mods
from modnex.services.servers import list_servers, read_log, send_command, server_path, start, status, stop
from modnex.web.server import Handler


def plugin_ctx():
    """Lo que el núcleo ofrece a un plugin: lo justo para actuar sobre servidores y datos propios."""
    import types
    ctx = types.SimpleNamespace(
        here=HERE, servers_dir=SERVERS_DIR, server_path=server_path, status=status, start=start, stop=stop,
        send_command=send_command, read_log=read_log, audit=db.audit, can=db.can, db_run=db.run,
        db_connect=db._connect, config=load_config, list_servers=list_servers,
        search=search, compat_for=compat_for, server_versions=server_versions, user_perms=db.user_perms,
        identify_mods=identify_mods, java_bin=templates._java, download=modpacks._download, port=PORT)
    ctx.install_modrinth = lambda name, slug, loaders=None, prefix=None: extras.install_modrinth(ctx, name, slug, loaders, prefix)
    return ctx


def main():
    cfg = ensure_config()
    SERVERS_DIR.mkdir(parents=True, exist_ok=True)
    templates.RUNTIME_JAVA = SERVERS_DIR / ".runtime" / "java21" / "bin" / "java"
    db.init()
    ctx = plugin_ctx()
    Handler.ctx = ctx
    plugins.load(ctx, cfg)
    if db.bootstrap_admin(cfg["access_token"]):
        print("Usuario inicial 'admin' creado: su contraseña es el access_token de config.json. "
              "Cámbiala desde el panel.", flush=True)
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))  # deja que atexit cierre el túnel
    bind = os.environ.get("MANAGER_BIND") or cfg.get("bind", "0.0.0.0")
    srv = ThreadingHTTPServer((bind, PORT), Handler)
    print(f"Gestor en http://{bind}:{PORT}  (servidores en {SERVERS_DIR})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
