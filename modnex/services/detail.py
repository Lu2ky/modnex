"""Ficha de un mod (descripción, versiones, enlaces) a partir del proveedor."""

import json
import urllib.request

from modnex.services.catalog import mod_files
from modnex.config import load_cf_key
from modnex.services.markdown import _body_to_html, _safe_href, sanitize_html
from modnex.infra.net import http_json, mr_get


def _mr_members(pid):
    return [m["user"]["username"] for m in mr_get(f"/project/{urllib.parse.quote(pid)}/members") if m.get("user")]


def mod_detail(source, ident, loader="neoforge", version="1.21.1"):
    if source == "modrinth":
        pid = urllib.parse.quote(str(ident), safe="")
        p = mr_get(f"/project/{pid}")
        try:
            authors = _mr_members(pid)
        except (urllib.error.URLError, KeyError):
            authors = []
        vs = mr_get(f"/project/{pid}/version?" + urllib.parse.urlencode({
            "loaders": json.dumps([loader]), "game_versions": json.dumps([version])}))
        return {
            "source": "modrinth", "id": p["id"], "slug": p["slug"], "name": p["title"], "summary": p["description"],
            "icon": p.get("icon_url"), "downloads": p.get("downloads", 0), "followers": p.get("followers", 0),
            "published": p.get("published"), "updated": p.get("updated"),
            "license": (p.get("license") or {}).get("id"), "categories": p.get("categories", []),
            "client": p.get("client_side"), "server": p.get("server_side"),
            "loaders": p.get("loaders", []), "game_versions": (p.get("game_versions") or [])[-8:],
            "authors": authors,
            "links": {"source": _safe_href(p.get("source_url")), "issues": _safe_href(p.get("issues_url")),
                      "wiki": _safe_href(p.get("wiki_url")), "discord": _safe_href(p.get("discord_url")),
                      "page": f"https://modrinth.com/mod/{p['slug']}"},
            "gallery": [{"url": g["url"], "title": g.get("title") or ""} for g in p.get("gallery", [])[:12]
                        if _safe_href(g.get("url"))],
            "body_html": _body_to_html(p.get("body") or ""),
            "files": mod_files("modrinth", p["id"], p["slug"], loader, version, "mod")[:8],
        }
    if source == "curseforge":
        key = load_cf_key()
        if not key:
            raise RuntimeError("falta la API key de CurseForge")
        hdr = {"x-api-key": key}
        m = http_json(f"https://api.curseforge.com/v1/mods/{int(ident)}", headers=hdr)["data"]
        try:
            desc = http_json(f"https://api.curseforge.com/v1/mods/{int(ident)}/description", headers=hdr)["data"]
        except urllib.error.URLError:
            desc = ""
        links = m.get("links") or {}
        cats = [c["name"] for c in m.get("categories", [])]
        return {
            "source": "curseforge", "id": str(m["id"]), "slug": m["slug"], "name": m["name"], "summary": m["summary"],
            "icon": (m.get("logo") or {}).get("url"), "downloads": m.get("downloadCount", 0), "followers": None,
            "published": m.get("dateCreated"), "updated": m.get("dateModified"), "license": None, "categories": cats,
            "client": None, "server": None, "loaders": [], "game_versions": [],
            "authors": [a["name"] for a in m.get("authors", [])],
            "links": {"source": _safe_href(links.get("sourceUrl")), "issues": _safe_href(links.get("issuesUrl")),
                      "wiki": _safe_href(links.get("wikiUrl")), "discord": None,
                      "page": _safe_href(links.get("websiteUrl")) or f"https://www.curseforge.com/minecraft/mc-mods/{m['slug']}"},
            "gallery": [{"url": s["url"], "title": s.get("title") or ""} for s in m.get("screenshots", [])[:12]
                        if _safe_href(s.get("url"))],
            "body_html": sanitize_html(desc),
            "files": mod_files("curseforge", str(m["id"]), m["slug"], loader, version, "mod")[:8],
        }
    raise ValueError("fuente no válida")
