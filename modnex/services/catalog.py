"""Catálogo de mods y plugins: búsqueda con páginas y etiquetas (Modrinth y CurseForge) y compatibilidad con el servidor."""

import json
import re
import time
import urllib.request

from modnex.services import templates
from modnex.services.addons import server_template_of
from modnex.config import CF_LOADER_TYPE, load_cf_key
from modnex.infra.net import http_json


KINDS = {
    "mod": {"perm": "mods", "cf_class": 6, "mr_type": "mod"},
    "plugin": {"perm": "mods", "cf_class": 5, "mr_type": "plugin"},
    "datapack": {"perm": "datapacks", "cf_class": 6945, "mr_type": "datapack"},
    "resourcepack": {"perm": "textures", "cf_class": 12, "mr_type": "resourcepack"},
}


MR_SORTS = {"relevance", "downloads", "updated", "newest"}


CF_SORTS = {"relevance": 2, "downloads": 6, "updated": 3, "newest": 11}


# Modrinth declara por separado el lado cliente y el lado servidor (required / optional / unsupported).
# "server" = mods que tienen sentido en un servidor: lo exigen, o lo admiten sin exigir cliente
# (así se excluyen mods de cliente que solo "toleran" el servidor, como un minimapa).
SIDE_FILTERS = {
    "server": '(server_side = "required") OR (server_side = "optional" AND client_side != "required")',
    "required": 'server_side = "required"',
}


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _match_score(query, item):
    """0 = nombre exacto, 1 = empieza por, 2 = contiene, 3 = no coincide por nombre."""
    q, n, sl = _norm(query), _norm(item["name"]), _norm(item["slug"])
    if n == q or sl == q:
        return 0
    if n.startswith(q) or sl.startswith(q):
        return 1
    return 2 if (q in n or q in sl) else 3


def _cf_client_only(mod, version):
    """CurseForge etiqueta los archivos con 'Client' y/o 'Server'. Solo es seguro descartar los que
    son únicamente de cliente (p. ej. Sodium); los que no traen etiqueta se mantienen."""
    files = [f for f in mod.get("latestFiles", []) if version in f.get("gameVersions", [])] or mod.get("latestFiles", [])
    return bool(files) and all("Client" in f.get("gameVersions", []) and "Server" not in f.get("gameVersions", [])
                               for f in files)


def compat_for(server, kind):
    """Loader y tipo real que puede usar un servidor. Un Paper recibe plugins; uno Vanilla, nada."""
    if not server or kind in ("datapack", "resourcepack"):  # datapacks y texturas valen en cualquier servidor
        return None, kind
    tpl = server_template_of(server)
    if templates.kind_of(tpl) == "none":
        raise ValueError("este servidor es Vanilla: no admite mods ni plugins (usa datapacks)")
    if templates.kind_of(tpl) == "plugin":
        if kind == "mod":
            kind = "plugin"
        if kind != "plugin":
            raise ValueError("este servidor usa plugins de Paper, no mods")
    elif kind == "plugin":
        raise ValueError("este servidor usa mods, no plugins")
    return templates.loader_of(tpl), kind


PER_PAGE = 24


MAX_PAGE = 50


TAG_RE = re.compile(r"[a-z0-9][a-z0-9\-]{0,29}")


TAG_LABELS = {"adventure": "Aventura", "cursed": "Maldito", "decoration": "Decoración", "economy": "Economía", "equipment": "Equipamiento",
              "food": "Comida", "game-mechanics": "Mecánicas", "library": "Librería", "magic": "Magia", "management": "Administración",
              "minigame": "Minijuego", "mobs": "Criaturas", "optimization": "Optimización", "social": "Social", "storage": "Almacenamiento",
              "technology": "Tecnología", "transportation": "Transporte", "utility": "Utilidad", "worldgen": "Generación de mundo",
              "combat": "Combate", "themed": "Temático", "tweaks": "Ajustes", "realistic": "Realista", "simplistic": "Sencillo",
              "modded": "Para mods", "vanilla-like": "Estilo vainilla", "challenging": "Desafiante", "kitchen-sink": "De todo",
              "lightweight": "Ligero", "multiplayer": "Multijugador", "quests": "Misiones", "exploration": "Exploración",
              "fantasy": "Fantasía", "survival": "Supervivencia", "technology-fallback": "Tecnología", "chat": "Chat", "mechanics": "Mecánicas",
              "world-management": "Gestión del mundo", "gameplay": "Jugabilidad", "worldgen-fallback": "Mundo", "transport": "Transporte"}


_TAG_CACHE = {"at": 0, "rows": []}


def category_tags(kind):
    """Etiquetas de Modrinth para un tipo de contenido: [{name, label}]. Se cachean 6 h; si Modrinth falla, lista vacía."""
    if time.time() - _TAG_CACHE["at"] > 6 * 3600 or not _TAG_CACHE["rows"]:
        try:
            _TAG_CACHE["rows"] = http_json("https://api.modrinth.com/v2/tag/category")
            _TAG_CACHE["at"] = time.time()
        except Exception:  # noqa: BLE001 - sin etiquetas el filtro simplemente no se ofrece
            return []
    want = KINDS[kind]["mr_type"]
    out = []
    for r in _TAG_CACHE["rows"]:
        if r.get("project_type") == want and r.get("header") == "categories" and TAG_RE.fullmatch(str(r.get("name", ""))):
            out.append({"name": r["name"], "label": TAG_LABELS.get(r["name"], r["name"].replace("-", " ").capitalize())})
    return sorted(out, key=lambda t: t["label"].lower())


def search(source, q, loader, version, kind="mod", sort="auto", side="server", page=1, tags=(), paged=False):
    """Busca contenido. Con `paged` devuelve {items, total, page, pages, per_page}; si no, solo la lista (la usan los plugins)."""
    page = max(1, min(int(page or 1), MAX_PAGE))
    tags = [t for t in dict.fromkeys(tags or ()) if TAG_RE.fullmatch(t)][:6]
    res = _search(source, q, loader, version, kind, sort, side, page, tags)
    if not paged:
        return res["items"]
    total = max(res["total"], len(res["items"]))
    return {"items": res["items"], "total": total, "page": page, "per_page": PER_PAGE, "pages": max(1, -(-total // PER_PAGE))}


def _search(source, q, loader, version, kind, sort, side, page, tags):
    if kind not in KINDS:
        raise ValueError("tipo de contenido no válido")
    if kind == "mod" and loader not in CF_LOADER_TYPE:
        raise ValueError("loader no válido")
    q = (q or "").strip()
    if sort == "auto":  # lo más descargado al abrir; relevancia cuando se busca algo concreto
        sort = "relevance" if q else "downloads"
    if source == "modrinth":
        facets = [[f"project_type:{KINDS[kind]['mr_type']}"], [f"versions:{version}"]]
        params = {"query": q, "limit": PER_PAGE, "offset": (page - 1) * PER_PAGE, "index": sort if sort in MR_SORTS else "downloads"}
        facets.extend([f"categories:{t}"] for t in tags)   # cada etiqueta restringe más (Y, no O)
        if kind == "mod":
            facets.append([f"categories:{loader}"])
            if side in SIDE_FILTERS:
                params["filters"] = SIDE_FILTERS[side]
        elif kind == "plugin":
            facets.append(["categories:paper"])
        params["facets"] = json.dumps(facets)
        d = http_json("https://api.modrinth.com/v2/search?" + urllib.parse.urlencode(params))
        items = [{"source": "modrinth", "id": h["project_id"], "slug": h["slug"], "name": h["title"],
                  "summary": h["description"], "downloads": h["downloads"], "icon": h.get("icon_url")}
                 for h in d["hits"]]
        if q:
            items.sort(key=lambda it: _match_score(q, it))  # estable: conserva el orden de Modrinth
        return {"items": items, "total": int(d.get("total_hits", len(items)))}
    if source == "curseforge":
        key = load_cf_key()
        if not key:
            raise RuntimeError("falta la API key de CurseForge (config.json o CURSEFORGE_API_KEY)")
        params = {"gameId": 432, "classId": KINDS[kind]["cf_class"], "gameVersion": version, "pageSize": PER_PAGE,
                  "index": (page - 1) * PER_PAGE, "sortField": CF_SORTS.get(sort, 6), "sortOrder": "desc"}
        if q:
            params["searchFilter"] = q
        if kind == "mod":
            params["modLoaderType"] = CF_LOADER_TYPE[loader]
        resp = http_json("https://api.curseforge.com/v1/mods/search?" + urllib.parse.urlencode(params),
                         headers={"x-api-key": key})
        data = resp["data"]
        total = int((resp.get("pagination") or {}).get("totalCount", len(data)))
        if kind == "mod" and side in SIDE_FILTERS:
            data = [m for m in data if not _cf_client_only(m, version)]
        items = [{"source": "curseforge", "id": str(m["id"]), "slug": m["slug"], "name": m["name"],
                  "summary": m["summary"], "downloads": m["downloadCount"],
                  "icon": (m.get("logo") or {}).get("url")} for m in data]
        if q:
            # La búsqueda de CurseForge es difusa: se reordena por coincidencia de nombre y se
            # descartan los resultados que no mencionan la búsqueda en nombre ni identificador.
            items.sort(key=lambda it: _match_score(q, it))  # estable: conserva el orden por popularidad
            good = [it for it in items if _match_score(q, it) < 3]
            items = good if len(good) >= 3 else items
        return {"items": items[:PER_PAGE], "total": total}
    raise ValueError("fuente no válida")


def mod_files(source, project, slug, loader, version, kind="mod"):
    if kind not in KINDS:
        raise ValueError("tipo de contenido no válido")
    if source == "modrinth":
        loaders = [loader] if kind == "mod" else (["datapack"] if kind == "datapack" else
                  (["paper", "spigot", "bukkit", "purpur"] if kind == "plugin" else ["minecraft"]))
        q = urllib.parse.urlencode({"loaders": json.dumps(loaders), "game_versions": json.dumps([version])})
        vs = http_json(f"https://api.modrinth.com/v2/project/{urllib.parse.quote(project)}/version?{q}")
        out = []
        for v in vs[:10]:
            f = next((x for x in v["files"] if x.get("primary")), v["files"][0])
            out.append({"id": v["id"], "version": v["version_number"], "filename": f["filename"], "url": f["url"],
                        "sha1": f["hashes"].get("sha1"), "date": v["date_published"][:10], "page": None})
        return out
    if source == "curseforge":
        key = load_cf_key()
        if not key:
            raise RuntimeError("falta la API key de CurseForge")
        params = {"gameVersion": version}
        if kind == "mod":
            params["modLoaderType"] = CF_LOADER_TYPE[loader]
        d = http_json(f"https://api.curseforge.com/v1/mods/{int(project)}/files?" + urllib.parse.urlencode(params),
                      headers={"x-api-key": key})
        out = []
        for f in d["data"][:10]:
            sha1 = next((h["value"] for h in f.get("hashes", []) if h["algo"] == 1), None)
            out.append({"id": str(f["id"]), "version": f["displayName"], "filename": f["fileName"], "url": f.get("downloadUrl"),
                        "sha1": sha1, "date": f["fileDate"][:10],
                        "page": f"https://www.curseforge.com/minecraft/mc-mods/{slug}/files/{f['id']}"})
        return out
    raise ValueError("fuente no válida")
