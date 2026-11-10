"""Descubrir mods en el núcleo: páginas, etiquetas, compatibilidad y el índice de lo instalado."""
import json, os, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock
CORE = Path(__file__).resolve().parent.parent
_tmp = tempfile.mkdtemp(prefix="modnex-discover-")
os.environ.setdefault("MANAGER_DB", str(Path(_tmp) / "db.db")); os.environ.setdefault("SERVERS_DIR", _tmp)
sys.path.insert(0, str(CORE))
from modnex.services import addons, catalog, mods

HIT = lambda i: {"project_id": f"P{i}", "slug": f"mod-{i}", "title": f"Mod {i}", "description": "d", "downloads": 10 - i, "icon_url": None}


class BusquedaTests(unittest.TestCase):
    def run_search(self, **kw):
        calls = []
        def fake(url, headers=None):
            calls.append(url); return {"hits": [HIT(i) for i in range(24)], "total_hits": 130}
        with mock.patch.object(catalog, "http_json", fake):
            r = catalog.search("modrinth", "", "neoforge", "1.21.1", **kw)
        return r, calls[0]

    def test_sin_paged_devuelve_la_lista_como_antes(self):
        r, _ = self.run_search(); self.assertIsInstance(r, list); self.assertEqual(len(r), 24)

    def test_paged_calcula_paginas_y_offset(self):
        r, url = self.run_search(page=3, paged=True)
        self.assertEqual((r["page"], r["pages"], r["total"], r["per_page"]), (3, 6, 130, 24)); self.assertIn("offset=48", url); self.assertIn("limit=24", url)

    def test_pagina_se_acota(self):
        for bad, want in ((0, 1), (-4, 1), (9999, catalog.MAX_PAGE), (None, 1)):
            r, url = self.run_search(page=bad, paged=True); self.assertEqual(r["page"], want, bad)

    def test_etiquetas_se_suman_como_Y_y_se_validan(self):
        r, url = self.run_search(tags=["magic", "worldgen"], paged=True)
        facets = json.loads(__import__("urllib.parse").parse.parse_qs(__import__("urllib.parse").parse.urlparse(url).query)["facets"][0])
        self.assertIn(["categories:magic"], facets); self.assertIn(["categories:worldgen"], facets)

    def test_etiquetas_hostiles_se_descartan(self):
        r, url = self.run_search(tags=['a"],["project_type:mod', "../x", "UPPER", "x" * 40, "", "ok-tag"], paged=True)
        q = __import__("urllib.parse").parse.parse_qs(__import__("urllib.parse").parse.urlparse(url).query)["facets"][0]
        self.assertIn("categories:ok-tag", q); self.assertNotIn("UPPER", q); self.assertNotIn("../x", q); self.assertEqual(q.count("categories:"), 2, "loader + ok-tag")

    def test_maximo_de_etiquetas(self):
        r, url = self.run_search(tags=[f"t{i}" for i in range(20)], paged=True)
        q = __import__("urllib.parse").parse.parse_qs(__import__("urllib.parse").parse.urlparse(url).query)["facets"][0]
        self.assertEqual(q.count("categories:t"), 6)

    def test_total_nunca_menor_que_lo_mostrado(self):
        with mock.patch.object(catalog, "http_json", lambda url, headers=None: {"hits": [HIT(i) for i in range(5)], "total_hits": 0}):
            r = catalog.search("modrinth", "", "neoforge", "1.21.1", paged=True)
        self.assertEqual((r["total"], r["pages"]), (5, 1))

    def test_curseforge_pagina_con_index(self):
        seen = []
        def fake(url, headers=None):
            seen.append(url); return {"data": [{"id": i, "slug": f"s{i}", "name": f"M{i}", "summary": "", "downloadCount": 1, "latestFiles": []} for i in range(24)], "pagination": {"totalCount": 100}}
        with mock.patch.object(catalog, "http_json", fake), mock.patch.object(catalog, "load_cf_key", lambda: "k"):
            r = catalog.search("curseforge", "", "neoforge", "1.21.1", page=2, paged=True)
        self.assertIn("index=24", seen[0]); self.assertEqual((r["pages"], r["total"]), (5, 100))


class EtiquetasTests(unittest.TestCase):
    ROWS = [{"name": "magic", "project_type": "mod", "header": "categories"}, {"name": "forge", "project_type": "mod", "header": "loaders"},
            {"name": "8x-", "project_type": "resourcepack", "header": "resolutions"}, {"name": "combat", "project_type": "resourcepack", "header": "categories"},
            {"name": "bad name!", "project_type": "mod", "header": "categories"}, {"name": "storage", "project_type": "mod", "header": "categories"}]

    def setUp(self): catalog._TAG_CACHE.update(at=0, rows=[])

    def test_filtra_por_tipo_y_cabecera_y_traduce(self):
        with mock.patch.object(catalog, "http_json", lambda url, headers=None: self.ROWS):
            mods = catalog.category_tags("mod"); packs = catalog.category_tags("resourcepack")
        self.assertEqual([t["name"] for t in mods], ["storage", "magic"][::-1] if False else sorted(["magic", "storage"], key=lambda n: catalog.TAG_LABELS[n].lower()))
        self.assertEqual({t["name"]: t["label"] for t in mods}["magic"], "Magia"); self.assertEqual([t["name"] for t in packs], ["combat"])

    def test_si_modrinth_falla_no_hay_etiquetas_ni_error(self):
        def boom(url, headers=None): raise OSError("sin red")
        with mock.patch.object(catalog, "http_json", boom): self.assertEqual(catalog.category_tags("mod"), [])


class InstaladosTests(unittest.TestCase):
    def setUp(self): addons.INSTALLED_CACHE.clear()

    def rows(self):
        return [{"enabled": True, "source": "modrinth", "project_id": "AAA", "slug": "Cobblemon", "installed": "1.8"},
                {"enabled": True, "source": "curseforge", "project_id": "77", "slug": None, "installed": None},
                {"enabled": False, "source": "modrinth", "project_id": "OFF", "slug": "off", "installed": "1"},
                {"enabled": True, "source": None, "project_id": None, "slug": None, "installed": None}]

    def test_indice_con_proyectos_slugs_y_versiones(self):
        with mock.patch.object(mods, "identify_mods", lambda *a: self.rows()):
            idx = mods.installed_index("s")
        self.assertEqual(set(idx["projects"]), {"modrinth:AAA", "slug:cobblemon", "curseforge:77"}, "los desactivados y sin identificar no cuentan")
        self.assertEqual(idx["versions"], {"modrinth:AAA": "1.8"})

    def test_cache_y_invalidacion(self):
        n = []
        def ident(*a): n.append(1); return self.rows()
        with mock.patch.object(mods, "identify_mods", ident):
            mods.installed_index("s"); mods.installed_index("s"); self.assertEqual(len(n), 1, "segunda llamada desde la caché")
            addons._invalidate_installed("s"); mods.installed_index("s"); self.assertEqual(len(n), 2)

    def test_cache_caduca(self):
        n = []
        with mock.patch.object(mods, "identify_mods", lambda *a: n.append(1) or self.rows()):
            mods.installed_index("s"); addons.INSTALLED_CACHE["s"] = (time.time() - addons.INSTALLED_TTL - 1, addons.INSTALLED_CACHE["s"][1]); mods.installed_index("s")
        self.assertEqual(len(n), 2)

    def test_la_cache_es_por_servidor(self):
        with mock.patch.object(mods, "identify_mods", lambda name, *a: [{"enabled": True, "source": "modrinth", "project_id": name, "slug": None, "installed": None}]):
            self.assertEqual(mods.installed_index("a")["projects"], ["modrinth:a"]); self.assertEqual(mods.installed_index("b")["projects"], ["modrinth:b"])


if __name__ == "__main__":
    unittest.main()
