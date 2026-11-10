"""Servidor HTTP del panel: cabeceras de seguridad, sesión y enrutado de la API."""

import ipaddress
import json
import re
import urllib.request
from http.server import BaseHTTPRequestHandler

from modnex import plugins
from modnex.infra import db
from modnex.services import extras
from modnex.services import modpacks
from modnex.services import release
from modnex.services import templates
from modnex.services.addons import _invalidate_installed, install, server_loader
from modnex.services.catalog import KINDS, category_tags, compat_for, mod_files, search
from modnex.services.client import build_client, client_plan
from modnex.config import STATIC, load_config
from modnex.services.creation import create_modpack_server, create_server
from modnex.services.datapacks import datapacks_dir, delete_datapack, finish_datapack, list_datapacks
from modnex.services.deps import install_many, resolve_deps
from modnex.services.detail import mod_detail
from modnex.services.identify import identify_mods, update_mod
from modnex.services.mods import delete_mod, installed_index, toggle_mod
from modnex.services.players import player_action, players_info
from modnex.services.properties import properties_view, set_properties
from modnex.services.resourcepacks import delete_local_pack, finish_pack_upload, get_resourcepack, list_local_packs, packs_dir, set_resourcepack, use_local_pack
from modnex.services.servers import delete_server, live_metrics, read_log, send_command, server_path, set_memory, start, stop, visible_servers


COOKIE = "mgr_session"


ASSETS = {"style.css": "text/css; charset=utf-8", "app.js": "text/javascript; charset=utf-8",
          "icons.js": "text/javascript; charset=utf-8", "theme.js": "text/javascript; charset=utf-8",
          "fonts/Inter.ttf": "font/ttf",
          "brand/modnex-mark.png": "image/png", "brand/modnex-logo.png": "image/png",
          **{f"brand/servers/{n}.png": "image/png" for n in db.ICONS}}


CSP = ("default-src 'self'; img-src 'self' data: https:; style-src 'self'; script-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


MAX_DATAPACK = 256 * 1024 * 1024


MAX_RELEASE = 2 * 1024 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    ctx = None   # lo fija la raíz de composición: lo que los servicios necesitan de fuera (plugins)
    server_version = "CobblemonManager/2.0"

    def log_message(self, *args):
        pass

    # --- utilidades ---
    def _send(self, code, payload, ctype="application/json; charset=utf-8", headers=None):
        data = json.dumps(payload).encode() if ctype.startswith("application/json") else payload
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy", CSP)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 1_000_000:
            raise ValueError("cuerpo demasiado grande")
        return json.loads(self.rfile.read(n) or b"{}")

    def _peer_loopback(self):
        return self.client_address[0] in ("127.0.0.1", "::1")

    def _client_ip(self):
        """IP real del cliente. Las cabeceras de un túnel solo se creen si la conexión llega desde esta
        misma máquina (el túnel conecta por loopback); desde la red local se ignoran, así no se pueden falsificar."""
        if self._peer_loopback():
            for h in ("Cf-Connecting-Ip", "X-Forwarded-For"):
                v = (self.headers.get(h) or "").split(",")[0].strip()
                if v:
                    return v[:64]
        return self.client_address[0]

    def _via_tunnel(self):
        return self._peer_loopback() and bool(self.headers.get("Cf-Connecting-Ip") or self.headers.get("X-Forwarded-For"))

    PRIVATE_SUFFIXES = (".local", ".lan", ".home", ".internal", ".localdomain", ".home.arpa")

    @staticmethod
    def _is_local_ip(value):
        """Local = no enrutable por internet (loopback, red local, ZeroTier, Tailscale, enlace local)."""
        try:
            ip = ipaddress.ip_address(str(value).strip())
        except ValueError:
            return False
        ip = getattr(ip, "ipv4_mapped", None) or ip
        return not ip.is_global

    def _host_is_public_name(self):
        """True si el Host de la petición es un nombre de dominio público (p. ej. el de un túnel)."""
        h = (self.headers.get("Host") or "").strip().lower()
        if h.startswith("["):
            return False                      # IPv6 literal
        h = h.rsplit(":", 1)[0] if h.count(":") == 1 else h
        try:
            ipaddress.ip_address(h)
            return False                      # IP literal: se juzga por la IP
        except ValueError:
            pass
        return "." in h and not h.endswith(self.PRIVATE_SUFFIXES)

    def _remote_origin(self):
        """True si la petición llega desde fuera de este equipo y de la red local.
        Se considera remota si pasa por un túnel (cabeceras de reenvío desde loopback), si la conexión viene
        de una IP enrutable, o si llega por loopback pero con un nombre de dominio público en `Host`."""
        if self._via_tunnel():
            return True
        peer = self.client_address[0]
        if not self._is_local_ip(peer):
            return True
        return self._peer_loopback() and self._host_is_public_name()

    def _admin_remote_blocked(self, user):
        """Los administradores solo entran desde el equipo o la red local, salvo `admin_remote: true` en config.json."""
        return bool(user and user.get("is_admin") and self._remote_origin() and load_config().get("admin_remote") is not True)

    def _https(self):
        return self._peer_loopback() and (self.headers.get("X-Forwarded-Proto") or "").lower() == "https"

    def _same_origin(self):
        origin = self.headers.get("Origin")
        return origin is None or urllib.parse.urlparse(origin).netloc == self.headers.get("Host", "")

    def _cookie(self):
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return urllib.parse.unquote(v)
        return None

    def _cookie_header(self, token, max_age):
        secure = "; Secure" if self._https() else ""
        return {"Set-Cookie": f"{COOKIE}={urllib.parse.quote(token)}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}{secure}"}

    def _serve_pack(self, token, fname):
        row = db.pack_lookup(token, fname)
        f = packs_dir(row["server_name"]) / row["filename"] if row else None
        if not row or not f.is_file():
            return self._send(404, {"error": "no encontrado"})
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(f.stat().st_size))
        self.send_header("Content-Disposition", f'attachment; filename="{row["filename"]}"')
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            with open(f, "rb") as fh:
                while chunk := fh.read(1 << 20):
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _save_upload(self, dest_dir, limit, namer=release.safe_zip_name):
        fname = namer(self.headers.get("X-Filename", ""))
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > limit:
            raise ValueError(f"tamaño no válido (máximo {limit // (1 << 20)} MB)")
        tmp = dest_dir / (fname + ".part")
        remaining = n
        with open(tmp, "wb") as fh:
            while remaining > 0:
                chunk = self.rfile.read(min(1 << 20, remaining))
                if not chunk:
                    break
                fh.write(chunk)
                remaining -= len(chunk)
        if remaining:
            tmp.unlink(missing_ok=True)
            raise ValueError("subida incompleta")
        return tmp, fname

    @staticmethod
    def _need(user, server, perm):
        if not db.can(user, server, perm):
            raise PermissionError("no tienes permiso para esto")

    @staticmethod
    def _need_admin(user):
        if not user["is_admin"]:
            raise PermissionError("solo administradores")

    # --- enrutado ---
    def _route(self, method):
        if not self._same_origin():
            return self._send(403, {"error": "origen no permitido"})
        u = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        path = u.path
        try:
            if method == "GET" and path == "/":
                # La landing pública es un sitio estático aparte (carpeta landing/). El gestor solo sirve el panel.
                return self._send(302, b"", "text/plain; charset=utf-8", headers={"Location": "/app"})
            if method == "GET" and path in ("/app", "/app/"):
                return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            m = re.fullmatch(r"/assets/([A-Za-z0-9_./-]+)", path)
            if method == "GET" and m and m.group(1) in ASSETS:
                return self._send(200, (STATIC / m.group(1)).read_bytes(), ASSETS[m.group(1)])

            mpl = re.fullmatch(r"/plugin/([A-Za-z0-9_.-]{1,60})", path)
            if method == "GET" and mpl:
                a = plugins.asset(mpl.group(1))
                if not a or not a[0].is_file():
                    return self._send(404, {"error": "no encontrado"})
                return self._send(200, a[0].read_bytes(), a[1])

            mp = re.fullmatch(r"/packs/([A-Za-z0-9_-]{10,40})/([^/]+)", path)
            if method == "GET" and mp:
                return self._serve_pack(mp.group(1), urllib.parse.unquote(mp.group(2)))

            if method == "POST" and path == "/api/login":
                b = self._body()
                try:
                    user = db.authenticate(b.get("username", ""), b.get("password", ""), self._client_ip())
                except PermissionError as e:
                    return self._send(429, {"error": str(e)})
                if not user:
                    return self._send(401, {"error": "usuario o contraseña incorrectos"})
                if self._admin_remote_blocked(user):
                    # Misma respuesta que una contraseña errónea: desde fuera no se revela que la cuenta existe ni que es admin.
                    db.register_fail(self._client_ip())
                    db.audit(user, None, "acceso de administrador bloqueado", f"desde fuera de la red local ({self._client_ip()})")
                    return self._send(401, {"error": "usuario o contraseña incorrectos"})
                sf = plugins.second_factor(user, b, self._via_tunnel(), self._client_ip())
                if sf:
                    if len(sf) > 2 and sf[2]:
                        db.register_fail(self._client_ip())
                    return self._send(sf[0], sf[1])
                token = db.create_session(user["id"])
                db.audit(user, None, "login")
                return self._send(200, {"user": user}, headers=self._cookie_header(token, db.SESSION_TTL))
            if method == "POST" and path == "/api/logout":
                db.delete_session(self._cookie())
                return self._send(200, {"ok": True}, headers=self._cookie_header("", 0))

            user = db.user_for_token(self._cookie())
            if path.startswith("/api/") and not user:
                return self._send(401, {"error": "no autorizado"})
            if self._admin_remote_blocked(user):  # una sesión de administrador no sirve desde fuera, aunque se robe la cookie
                return self._send(403, {"error": "los administradores solo pueden usar el panel desde este equipo o la red local"})

            if method == "GET" and path == "/api/me":
                return self._send(200, {"user": user, "icons": db.ICONS})
            if method == "POST" and path == "/api/me/password":
                b = self._body()
                if not db.verify_password(user["id"], b.get("old", "")):
                    return self._send(400, {"error": "la contraseña actual no es correcta"})
                db.update_user(user["id"], password=b.get("new", ""))
                token = db.create_session(user["id"])  # update_user cerró las sesiones
                db.audit(user, None, "cambio de contraseña")
                return self._send(200, {"ok": True}, headers=self._cookie_header(token, db.SESSION_TTL))
            if method == "GET" and path == "/api/servers":
                return self._send(200, visible_servers(user))

            # búsqueda e instalación de mods
            if method == "GET" and path in ("/api/search", "/api/files"):
                kind = q.get("kind", "mod")
                if kind not in KINDS:
                    raise ValueError("tipo de contenido no válido")
                if not db.can_any(user, KINDS[kind]["perm"]):
                    raise PermissionError("no tienes permiso para buscar este contenido")
                loader, version = q.get("loader", "neoforge"), q.get("version", "1.21.1")
                sv = q.get("server")
                if sv:
                    self._need(user, sv, KINDS[kind]["perm"])
                    loader, kind = compat_for(sv, kind)
                    kind = kind if kind in KINDS else "mod"
                if path == "/api/search":
                    paged = "page" in q
                    res = search(q.get("source", "modrinth"), q.get("q", ""), loader, version, kind, q.get("sort", "auto"), q.get("side", "server"),
                                 int(q.get("page", 1) or 1), [t for t in q.get("tags", "").split(",") if t], paged)
                    return self._send(200, res)
                return self._send(200, mod_files(q["source"], q["project"], q.get("slug", ""), loader, version, kind))
            if method == "GET" and path == "/api/tags":
                kind = q.get("kind", "mod")
                if kind not in KINDS:
                    raise ValueError("tipo de contenido no válido")
                if not db.can_any(user, KINDS[kind]["perm"]):
                    raise PermissionError("no tienes permiso para este contenido")
                return self._send(200, category_tags(kind))
            if method == "GET" and path == "/api/templates":
                return self._send(200, [{"id": k, "label": v["label"], "kind": v["kind"], "desc": v["desc"], "loader": v["loader"],
                                         "perf": templates.perf_list(k)} for k, v in templates.TEMPLATES.items()])
            if method == "GET" and path == "/api/extras":
                return self._send(200, extras.listing())
            if method == "GET" and path == "/api/templates/versions":
                self._need_admin(user)
                return self._send(200, {"versions": templates.versions(q.get("template", ""))})
            if method == "GET" and path.startswith("/api/jobs/"):
                self._need_admin(user)
                st = templates.job_status(path.rsplit("/", 1)[1])
                if not st:
                    raise FileNotFoundError("trabajo no encontrado")
                return self._send(200, st)
            if method == "GET" and path == "/api/modpacks/search":
                self._need_admin(user)
                return self._send(200, modpacks.search(q.get("source", "modrinth"), q.get("q", ""), q.get("mc", "1.21.1")))
            if method == "GET" and path == "/api/modpacks/versions":
                self._need_admin(user)
                return self._send(200, modpacks.versions(q.get("source", "modrinth"), q["project"], q.get("mc", "1.21.1")))
            if method == "POST" and path == "/api/servers/create_modpack":
                self._need_admin(user)
                return self._send(200, {"job": create_modpack_server(user, self._body(), self.ctx)})
            if method == "POST" and path == "/api/servers/create":
                self._need_admin(user)
                return self._send(200, {"job": create_server(user, self._body(), self.ctx)})
            if method == "GET" and path == "/api/mod":
                if not db.can_any(user, "mods"):
                    raise PermissionError("no tienes permiso para ver fichas de mods")
                return self._send(200, mod_detail(q.get("source", "modrinth"), q["id"],
                                                  q.get("loader", "neoforge"), q.get("version", "1.21.1")))
            if method == "GET" and path == "/api/deps":
                self._need(user, q["server"], "mods")
                compat_for(q["server"], "mod")
                return self._send(200, resolve_deps(q["server"], q["source"], q["project"], q["vid"],
                                                    server_loader(q["server"]) or q.get("loader", "neoforge"),
                                                    q.get("version", "1.21.1")))
            if method == "POST" and path == "/api/install_many":
                b = self._body()
                self._need(user, b["server"], "mods")
                compat_for(b["server"], "mod")
                res = install_many(b["server"], b.get("items"))
                db.audit(user, b["server"], "instalar mods con dependencias", ", ".join(r["file"] for r in res if r["ok"])[:250])
                return self._send(200, {"results": res})
            if method == "POST" and path == "/api/install":
                b = self._body()
                kind = b.get("kind", "mod")
                if kind not in ("mod", "plugin", "datapack"):
                    raise ValueError("tipo no instalable")
                self._need(user, b["server"], KINDS[kind]["perm"])
                compat_for(b["server"], kind)  # lanza error si el tipo no encaja con el servidor
                fname = install(b["server"], b["url"], b["filename"], b.get("sha1"), kind)
                db.audit(user, b["server"], f"instalar {'datapack' if kind == 'datapack' else 'mod'}", fname)
                return self._send(200, {"installed": fname})

            # administración
            if path == "/api/users" or path.startswith("/api/users/") or path in ("/api/audit", "/api/share", "/api/share_stop"):
                self._need_admin(user)
                if method == "GET" and path == "/api/users":
                    return self._send(200, db.list_users())
                if method == "POST" and path == "/api/users":
                    b = self._body()
                    uid = db.create_user(b.get("username", ""), b.get("password", ""), bool(b.get("is_admin")))
                    db.audit(user, None, "crear usuario", b.get("username"))
                    return self._send(200, {"id": uid})
                mu = re.fullmatch(r"/api/users/(\d+)/(update|delete|permissions)", path)
                if method == "POST" and mu:
                    uid, action = int(mu.group(1)), mu.group(2)
                    b = self._body()
                    target = db.get_user(uid)
                    if not target:
                        raise FileNotFoundError("usuario no encontrado")
                    if action == "update":
                        db.update_user(uid, password=b.get("password"), is_admin=b.get("is_admin"), active=b.get("active"))
                        db.audit(user, None, "editar usuario", target["username"])
                    elif action == "delete":
                        if uid == user["id"]:
                            raise ValueError("no puedes borrar tu propia cuenta")
                        db.delete_user(uid)
                        db.audit(user, None, "borrar usuario", target["username"])
                    elif "permissions" in b:  # guardado explícito de todos los permisos del usuario
                        perms = b["permissions"]
                        if not isinstance(perms, dict):
                            raise ValueError("permisos no válidos")
                        clean = {}
                        for srv, p in perms.items():
                            server_path(srv)
                            clean[srv] = {k: bool(p.get(k)) for k in db.PERMS}
                        db.set_all_permissions(uid, clean)
                        db.audit(user, None, "permisos", f"{target['username']}: " + ", ".join(
                            f"{s}[{'/'.join(k for k in db.PERMS if p[k]) or '-'}]" for s, p in clean.items()))
                    else:
                        server_path(b["server"])
                        db.set_permissions(uid, b["server"], {k: bool(b.get(k)) for k in db.PERMS})
                        db.audit(user, b["server"], "permisos", f"{target['username']}: {b}")
                    return self._send(200, {"ok": True})
                if method == "GET" and path == "/api/audit":
                    return self._send(200, db.recent_audit(int(q.get("limit", 100))))
                if method == "GET" and path == "/api/share":
                    return self._send(200, release.status())
                if method == "POST" and path == "/api/share_stop":
                    release.stop_share()
                    db.audit(user, None, "detener descarga pública")
                    return self._send(200, {"ok": True})

            if method == "GET" and path == "/api/plugins":
                return self._send(200, plugins.info())
            mg = re.fullmatch(r"/api/features/([a-z0-9_]+)", path)
            if mg:
                gr = plugins.dispatch_global(method, user, mg.group(1), q, self._body)
                if gr is not None:
                    return self._send(gr[0], gr[1])

            # acciones por servidor
            ms = re.fullmatch(r"/api/servers/([^/]+)/([a-z_]+)", path)
            if ms:
                name, action = ms.groups()
                pr = plugins.dispatch(method, user, name, action, q, self._body)
                if pr is not None:
                    return self._send(pr[0], pr[1])
                if method == "GET":
                    if action == "metrics":
                        if not any(db.can(user, name, perm) for perm in db.PERMS):
                            raise PermissionError("no tienes permiso para esto")
                        return self._send(200, live_metrics(name))
                    if action == "installed":
                        self._need(user, name, "mods")
                        return self._send(200, installed_index(name, q.get("loader", "neoforge"), q.get("version", "1.21.1")))
                    if action == "log":
                        self._need(user, name, "logs")
                        return self._send(200, {"log": read_log(name, int(q.get("lines", 200)))})
                    if action == "mods":
                        self._need(user, name, "mods")
                        return self._send(200, identify_mods(name, q.get("loader", "neoforge"), q.get("version", "1.21.1")))
                    if action == "datapacks":
                        self._need(user, name, "datapacks")
                        return self._send(200, list_datapacks(name))
                    if action == "releases":
                        self._need_admin(user)
                        return self._send(200, release.list_releases(name))
                    if action == "properties":
                        self._need_admin(user)
                        server_path(name)
                        return self._send(200, properties_view(name))
                    if action == "client_plan":
                        self._need_admin(user)
                        return self._send(200, client_plan(name))
                    if action == "resourcepack":
                        self._need(user, name, "textures")
                        return self._send(200, {"current": get_resourcepack(name), "local": list_local_packs(name)})
                    if action == "players":
                        self._need(user, name, "players")
                        return self._send(200, players_info(name))
                if method == "POST":
                    # subidas en bruto (no JSON)
                    if action == "datapack_upload":
                        self._need(user, name, "datapacks")
                        tmp, fname = self._save_upload(datapacks_dir(name, create=True), MAX_DATAPACK)
                        finish_datapack(name, tmp, fname)
                        db.audit(user, name, "subir datapack", fname)
                        return self._send(200, {"uploaded": fname})
                    if action == "resourcepack_upload":
                        self._need(user, name, "textures")
                        tmp, fname = self._save_upload(packs_dir(name), MAX_DATAPACK)
                        finish_pack_upload(name, tmp, fname)
                        db.audit(user, name, "subir pack de texturas", fname)
                        return self._send(200, {"uploaded": fname})
                    if action == "release_upload":
                        self._need_admin(user)
                        tmp, fname = self._save_upload(release.release_dir(name), MAX_RELEASE, release.safe_release_name)
                        release.finish_upload(name, tmp, fname)
                        db.audit(user, name, "subir release", fname)
                        return self._send(200, {"uploaded": fname})
                    b = self._body()
                    if action in ("command", "memory", "meta", "release_delete", "release_share", "client_build",
                                  "properties", "delete"):
                        self._need_admin(user)
                    if action in ("start", "stop"):
                        self._need(user, name, "control")
                    if action == "start":
                        start(name)
                        db.audit(user, name, "arrancar")
                    elif action == "stop":
                        stop(name)
                        db.audit(user, name, "parar")
                    elif action == "command":
                        send_command(name, b.get("cmd", ""))
                        db.audit(user, name, "comando", b.get("cmd"))
                    elif action == "memory":
                        set_memory(name, b["xmx"], b["xms"])
                        db.audit(user, name, "memoria", f"{b['xmx']}/{b['xms']}")
                    elif action == "meta":
                        server_path(name)
                        db.set_server_meta(name, b.get("display_name"), b.get("icon"))
                    elif action == "mod_toggle":
                        self._need(user, name, "mods")
                        new = toggle_mod(name, b["file"])
                        _invalidate_installed(name)
                        db.audit(user, name, "activar/desactivar mod", new)
                        return self._send(200, {"file": new})
                    elif action == "mod_delete":
                        self._need(user, name, "mods")
                        delete_mod(name, b["file"])
                        _invalidate_installed(name)
                        db.audit(user, name, "borrar mod", b["file"])
                    elif action == "mod_update":
                        self._need(user, name, "mods")
                        new = update_mod(name, b["file"], b.get("loader", "neoforge"), b.get("version", "1.21.1"))
                        _invalidate_installed(name)
                        db.audit(user, name, "actualizar mod", new)
                        return self._send(200, {"installed": new})
                    elif action == "datapack_delete":
                        self._need(user, name, "datapacks")
                        delete_datapack(name, b["file"])
                        db.audit(user, name, "borrar datapack", b["file"])
                    elif action == "resourcepack_set":
                        self._need(user, name, "textures")
                        set_resourcepack(name, b.get("url"), b.get("sha1"), bool(b.get("required")), b.get("prompt"))
                        db.audit(user, name, "texturas del servidor", (b.get("url") or "(quitado)")[:120])
                    elif action == "resourcepack_use":
                        self._need(user, name, "textures")
                        use_local_pack(name, b["file"], b.get("base_url"), bool(b.get("required")), b.get("prompt"))
                        db.audit(user, name, "texturas del servidor (local)", b["file"])
                    elif action == "resourcepack_delete":
                        self._need(user, name, "textures")
                        delete_local_pack(name, b["file"])
                        db.audit(user, name, "borrar pack de texturas", b["file"])
                    elif action == "player":
                        self._need(user, name, "players")
                        cmd = player_action(name, b.get("action"), b.get("player"), b.get("text", ""))
                        db.audit(user, name, f"jugador: {b.get('action')}", cmd[:150])
                    elif action == "properties":
                        clean = set_properties(name, b.get("values"))
                        db.audit(user, name, "propiedades del servidor", ", ".join(sorted(clean)))
                        return self._send(200, {"ok": True, "values": properties_view(name)["values"]})
                    elif action == "delete":
                        if b.get("confirm") != name:
                            raise ValueError("escribe el nombre exacto del servidor para confirmar el borrado")
                        delete_server(name)
                        db.audit(user, None, "borrar servidor", name)
                    elif action == "client_build":
                        res = build_client(name, b.get("files"), b.get("format"), b.get("version"),
                                           bool(b.get("include_config")), b.get("pack_name"), user["username"], bool(b.get("reference_cf")),
                                           bool(b.get("presets")))
                        db.audit(user, name, "generar cliente", f"{res['file']} · {res['mods']} mods")
                        return self._send(200, res)
                    elif action == "release_delete":
                        release.delete_release(name, b["file"])
                        db.audit(user, name, "borrar release", b["file"])
                    elif action == "release_share":
                        server_path(name)
                        st = release.start_share(name, b["file"], b.get("minutes", release.DEFAULT_MINUTES))
                        db.audit(user, name, "publicar release", f"{b['file']} · {b.get('minutes', release.DEFAULT_MINUTES)} min")
                        return self._send(200, st)
                    else:
                        return self._send(404, {"error": "acción desconocida"})
                    return self._send(200, {"ok": True})
            return self._send(404, {"error": "no encontrado"})
        except PermissionError as e:
            return self._send(403, {"error": str(e)})
        except (ValueError, KeyError) as e:
            return self._send(400, {"error": str(e)})
        except (FileNotFoundError, LookupError) as e:
            return self._send(404, {"error": str(e)})
        except RuntimeError as e:
            return self._send(409, {"error": str(e)})
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return self._send(404, {"error": "no existe en el proveedor"})
            return self._send(502, {"error": f"el proveedor respondió {e.code}"})
        except Exception as e:  # noqa: BLE001 - se devuelve al cliente para depurar
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")
