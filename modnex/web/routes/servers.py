"""Servidores: la lista y todas las acciones sobre uno concreto (`/api/servers/<nombre>/<acción>`).

Cada acción declara el permiso que exige; los plugins pueden añadir las suyas y se consultan primero.
"""
from modnex import plugins
from modnex.infra import db
from modnex.services import release
from modnex.services.addons import MAX_MOD_UPLOAD, _invalidate_installed, addons_dir, finish_mod_upload, safe_jar_name
from modnex.services.catalog import compat_for
from modnex.services.client import build_client, client_plan
from modnex.services.datapacks import datapacks_dir, delete_datapack, finish_datapack, list_datapacks
from modnex.services.identify import identify_mods, update_mod
from modnex.services.autofilter import modid_map
from modnex.services.incontrol_rules import read_rules, save_rules
from modnex.services.mods import delete_mod, installed_index, toggle_mod
from modnex.services.modconfig import mods_with_config, read_config, save_config, set_auto
from modnex.services.players import player_action, players_info
from modnex.services.properties import properties_view, set_properties
from modnex.services.resourcepacks import (delete_local_pack, finish_pack_upload, get_resourcepack, list_local_packs, packs_dir,
                                           set_resourcepack, use_local_pack)
from modnex.services.servers import (delete_server, live_metrics, read_log, send_command, server_path, set_memory, start, stop,
                                     visible_servers)
from modnex.web.router import PASS, SERVER_ACTIONS, Reply, route, server_action

MAX_DATAPACK = 256 * 1024 * 1024
MAX_RELEASE = 2 * 1024 * 1024 * 1024


@route("GET", r"/api/servers")
def server_list(req):
    return visible_servers(req.user)


@route("*", r"/api/servers/([^/]+)/([a-z_]+)")
def server_dispatch(req):
    name, action = req.m.groups()
    pr = plugins.dispatch(req.method, req.user, name, action, req.q, req.body)
    if pr is not None:
        return Reply(pr[0], pr[1])
    spec = SERVER_ACTIONS.get((req.method, action))
    if req.method == "GET":
        if not spec:
            return PASS
        _check(req, name, spec)
        return spec.fn(req, name)
    if req.method == "POST":
        b = None if spec and spec.raw else req.body()    # igual que antes: el cuerpo se lee antes de comprobar permisos
        if not spec:
            return Reply(404, {"error": "acción desconocida"})
        _check(req, name, spec)
        out = spec.fn(req, name) if spec.raw else spec.fn(req, name, b)
        return {"ok": True} if out is None else out
    return PASS


def _check(req, name, spec):
    if spec.perm is None:
        req.need_admin()
    else:
        req.need(name, spec.perm)


# ---- lecturas ----

@server_action("GET", "metrics", perm="*")
def metrics(req, name):
    return live_metrics(name)


@server_action("GET", "installed", perm="mods")
def installed(req, name):
    return installed_index(name, req.q.get("loader", "neoforge"), req.q.get("version", "1.21.1"))


@server_action("GET", "log", perm="logs")
def log(req, name):
    return {"log": read_log(name, int(req.q.get("lines", 200)))}


@server_action("GET", "mods", perm="mods")
def mods(req, name):
    return identify_mods(name, req.q.get("loader", "neoforge"), req.q.get("version", "1.21.1"))


@server_action("GET", "datapacks", perm="datapacks")
def datapacks(req, name):
    return list_datapacks(name)


@server_action("GET", "releases")
def releases(req, name):
    return release.list_releases(name)


@server_action("GET", "properties")
def properties(req, name):
    server_path(name)
    return properties_view(name)


@server_action("GET", "client_plan")
def plan(req, name):
    return client_plan(name)


@server_action("GET", "resourcepack", perm="textures")
def resourcepack(req, name):
    return {"current": get_resourcepack(name), "local": list_local_packs(name)}


@server_action("GET", "players", perm="players")
def players(req, name):
    return players_info(name)


# ---- subidas en bruto (el cuerpo no es JSON) ----

@server_action("POST", "datapack_upload", perm="datapacks", raw=True)
def datapack_upload(req, name):
    tmp, fname = req.h._save_upload(datapacks_dir(name, create=True), MAX_DATAPACK)
    finish_datapack(name, tmp, fname)
    db.audit(req.user, name, "subir datapack", fname)
    return {"uploaded": fname}


@server_action("POST", "resourcepack_upload", perm="textures", raw=True)
def resourcepack_upload(req, name):
    tmp, fname = req.h._save_upload(packs_dir(name), MAX_DATAPACK)
    finish_pack_upload(name, tmp, fname)
    db.audit(req.user, name, "subir pack de texturas", fname)
    return {"uploaded": fname}


@server_action("POST", "mod_upload", raw=True)    # solo administradores: un .jar es código que corre con los permisos del servidor
def mod_upload(req, name):
    compat_for(name, "mod")        # falla con un mensaje claro si el servidor es Vanilla
    d = addons_dir(name)
    d.mkdir(exist_ok=True)
    tmp, fname = req.h._save_upload(d, MAX_MOD_UPLOAD, safe_jar_name)
    finish_mod_upload(name, tmp, fname)
    db.audit(req.user, name, "subir mod propio", fname)
    return {"uploaded": fname}


@server_action("POST", "release_upload", raw=True)
def release_upload(req, name):
    tmp, fname = req.h._save_upload(release.release_dir(name), MAX_RELEASE, release.safe_release_name)
    release.finish_upload(name, tmp, fname)
    db.audit(req.user, name, "subir release", fname)
    return {"uploaded": fname}


# ---- control del servidor ----

@server_action("POST", "start", perm="control")
def start_server(req, name, b):
    start(name)
    db.audit(req.user, name, "arrancar")


@server_action("POST", "stop", perm="control")
def stop_server(req, name, b):
    stop(name)
    db.audit(req.user, name, "parar")


@server_action("POST", "command")
def command(req, name, b):
    send_command(name, b.get("cmd", ""))
    db.audit(req.user, name, "comando", b.get("cmd"))


@server_action("POST", "memory")
def memory(req, name, b):
    set_memory(name, b["xmx"], b["xms"])
    db.audit(req.user, name, "memoria", f"{b['xmx']}/{b['xms']}")


@server_action("POST", "meta")
def meta(req, name, b):
    server_path(name)
    db.set_server_meta(name, b.get("display_name"), b.get("icon"))


@server_action("POST", "properties")
def save_properties(req, name, b):
    clean = set_properties(name, b.get("values"))
    db.audit(req.user, name, "propiedades del servidor", ", ".join(sorted(clean)))
    return {"ok": True, "values": properties_view(name)["values"]}


@server_action("POST", "delete")
def delete(req, name, b):
    if b.get("confirm") != name:
        raise ValueError("escribe el nombre exacto del servidor para confirmar el borrado")
    delete_server(name)
    db.audit(req.user, None, "borrar servidor", name)


# ---- mods ----

@server_action("GET", "mod_config_prompts", perm="mods")
def mod_config_prompts(req, name):
    """Mods instalados que tienen archivos de configuración: el panel se abre para ellos."""
    jars = modid_map(addons_dir(name))
    return [dict(m, jar=jars.get(m["modid"], "")) for m in mods_with_config(name, jars)]


@server_action("GET", "mod_config_read", perm="mods")
def mod_config_read(req, name):
    return read_config(name, req.q.get("file", ""))


@server_action("GET", "incontrol_rules", perm="mods")
def incontrol_rules_read(req, name):
    return read_rules(name, req.q.get("file", ""))


@server_action("POST", "incontrol_rules_save", perm="mods")
def incontrol_rules_write(req, name, b):
    res = save_rules(name, b.get("file", ""), b.get("rules"))
    if res.get("changed"):
        db.audit(req.user, name, "cambiar reglas de InControl", b.get("file", ""))
    return res


@server_action("POST", "mod_config_auto", perm="mods")
def mod_config_auto(req, name, b):
    set_auto(b.get("modid", ""), bool(b.get("on")))
    db.audit(req.user, name, "panel de configuración automático", f"{b.get('modid', '')}={bool(b.get('on'))}")
    return {"ok": True}


@server_action("POST", "mod_config_save", perm="mods")
def mod_config_save(req, name, b):
    res = save_config(name, b.get("file", ""), updates=b.get("updates"), json_text=b.get("json_text"))
    if res.get("changed"):
        db.audit(req.user, name, "cambiar configuración de mod", b.get("file", ""))
    return res

@server_action("POST", "mod_toggle", perm="mods")
def mod_toggle(req, name, b):
    new = toggle_mod(name, b["file"])
    _invalidate_installed(name)
    db.audit(req.user, name, "activar/desactivar mod", new)
    return {"file": new}


@server_action("POST", "mod_delete", perm="mods")
def mod_delete(req, name, b):
    delete_mod(name, b["file"])
    _invalidate_installed(name)
    db.audit(req.user, name, "borrar mod", b["file"])


@server_action("POST", "mod_update", perm="mods")
def mod_update(req, name, b):
    new = update_mod(name, b["file"], b.get("loader", "neoforge"), b.get("version", "1.21.1"))
    _invalidate_installed(name)
    db.audit(req.user, name, "actualizar mod", new)
    return {"installed": new}


# ---- datapacks, texturas y jugadores ----

@server_action("POST", "datapack_delete", perm="datapacks")
def datapack_delete(req, name, b):
    delete_datapack(name, b["file"])
    db.audit(req.user, name, "borrar datapack", b["file"])


@server_action("POST", "resourcepack_set", perm="textures")
def resourcepack_set(req, name, b):
    set_resourcepack(name, b.get("url"), b.get("sha1"), bool(b.get("required")), b.get("prompt"))
    db.audit(req.user, name, "texturas del servidor", (b.get("url") or "(quitado)")[:120])


@server_action("POST", "resourcepack_use", perm="textures")
def resourcepack_use(req, name, b):
    use_local_pack(name, b["file"], b.get("base_url"), bool(b.get("required")), b.get("prompt"))
    db.audit(req.user, name, "texturas del servidor (local)", b["file"])


@server_action("POST", "resourcepack_delete", perm="textures")
def resourcepack_delete(req, name, b):
    delete_local_pack(name, b["file"])
    db.audit(req.user, name, "borrar pack de texturas", b["file"])


@server_action("POST", "player", perm="players")
def player(req, name, b):
    cmd = player_action(name, b.get("action"), b.get("player"), b.get("text", ""))
    db.audit(req.user, name, f"jugador: {b.get('action')}", cmd[:150])


# ---- cliente y releases ----

@server_action("POST", "client_build")
def client_build(req, name, b):
    res = build_client(name, b.get("files"), b.get("format"), b.get("version"), bool(b.get("include_config")), b.get("pack_name"),
                       req.user["username"], bool(b.get("reference_cf")), bool(b.get("presets")))
    db.audit(req.user, name, "generar cliente", f"{res['file']} · {res['mods']} mods")
    return res


@server_action("POST", "release_delete")
def release_delete(req, name, b):
    release.delete_release(name, b["file"])
    db.audit(req.user, name, "borrar release", b["file"])


@server_action("POST", "release_share")
def release_share(req, name, b):
    server_path(name)
    st = release.start_share(name, b["file"], b.get("minutes", release.DEFAULT_MINUTES))
    db.audit(req.user, name, "publicar release", f"{b['file']} · {b.get('minutes', release.DEFAULT_MINUTES)} min")
    return st
