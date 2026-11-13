"""KubeJS: recetas visuales, editor de scripts y diagnóstico. Solo en servidores con KubeJS instalado."""
from . import kubejs, kubejs_rules
from .guard import _guard


def _need(ctx, name):
    if not kubejs.installed(ctx, name):
        raise ValueError("KubeJS no está instalado en este servidor")


def ctx_addons(ctx, name):
    from ..services import servers
    return servers.addons_of(ctx.server_path(name))


def register(api):
    @api.route("GET", "kubejs_state")
    @_guard
    def r_state(ctx, user, name, q, b):
        _need(ctx, name)
        return 200, kubejs.load(ctx, name)

    @api.route("GET", "kubejs_items")
    @_guard
    def r_items(ctx, user, name, q, b):
        _need(ctx, name)
        try:
            limit = int((q or {}).get("limit", kubejs.MAX_RESULTS))
        except (TypeError, ValueError):
            limit = kubejs.MAX_RESULTS
        return 200, {"items": kubejs.search(ctx, name, str((q or {}).get("q", "")), limit)}

    @api.route("POST", "kubejs_save")
    @_guard
    def r_save(ctx, user, name, q, b):
        _need(ctx, name)
        recipes = kubejs.save(ctx, name, b.get("recipes"))
        ctx.audit(user, name, "recetas de KubeJS guardadas", f"{len(recipes)} recetas")
        return 200, kubejs.load(ctx, name)

    @api.route("GET", "kubejs_scripts")
    @_guard
    def r_scripts(ctx, user, name, q, b):
        return 200, {"scripts": kubejs.scripts(ctx, name)}

    @api.route("GET", "kubejs_script")
    @_guard
    def r_script(ctx, user, name, q, b):
        return 200, kubejs.read_script(ctx, name, str((q or {}).get("path", "")))

    @api.route("POST", "kubejs_script_save")
    @_guard
    def r_script_save(ctx, user, name, q, b):
        out = kubejs.save_script(ctx, name, str(b.get("path") or ""), b.get("text"))
        ctx.audit(user, name, "script de KubeJS guardado", out["path"])
        return 200, out

    @api.route("POST", "kubejs_script_new")
    @_guard
    def r_script_new(ctx, user, name, q, b):
        rel = kubejs.new_script_path(str(b.get("folder") or ""), str(b.get("filename") or ""))
        out = kubejs.save_script(ctx, name, rel, str(b.get("text") or "// Nuevo script de KubeJS\n"), create=True)
        ctx.audit(user, name, "script de KubeJS creado", out["path"])
        return 200, out

    @api.route("POST", "kubejs_script_delete")
    @_guard
    def r_script_delete(ctx, user, name, q, b):
        rel = str(b.get("path") or "")
        kubejs.delete_script(ctx, name, rel)
        ctx.audit(user, name, "script de KubeJS borrado", rel)
        return 200, {"ok": True}

    @api.route("GET", "kubejs_diag")
    @_guard
    def r_diag(ctx, user, name, q, b):
        return 200, kubejs.diagnostics(ctx, name)

    @api.route("GET", "kubejs_recipes_for")
    @_guard
    def r_recipes_for(ctx, user, name, q, b):
        _need(ctx, name)
        return 200, kubejs.recipes_for(ctx, name, str((q or {}).get("item", "")))

    @api.route("POST", "kubejs_removals_save")
    @_guard
    def r_removals_save(ctx, user, name, q, b):
        _need(ctx, name)
        removals = kubejs.save_removals(ctx, name, b.get("removals"))
        ctx.audit(user, name, "recetas quitadas con KubeJS", f"{len(removals)} eliminaciones")
        return 200, kubejs.load(ctx, name)

    @api.route("POST", "kubejs_vanilla_fetch")
    @_guard
    def r_vanilla_fetch(ctx, user, name, q, b):
        _need(ctx, name)
        out = kubejs.fetch_vanilla(ctx, name)
        ctx.audit(user, name, "cliente de Minecraft descargado para texturas", str(out.get("version")))
        return 200, out

    @api.route("POST", "kubejs_recipe_delete")
    @_guard
    def r_recipe_delete(ctx, user, name, q, b):
        _need(ctx, name)
        slug = str(b.get("slug") or "")
        kubejs.delete_recipe(ctx, name, slug)
        ctx.audit(user, name, "receta del panel borrada", slug)
        return 200, kubejs.load(ctx, name)

    @api.route("GET", "kubejs_rules")
    @_guard
    def r_rules(ctx, user, name, q, b):
        _need(ctx, name)
        out = kubejs_rules.load(ctx, name)
        out["morejs"] = "morejs" in ctx_addons(ctx, name)
        return 200, out

    @api.route("POST", "kubejs_rules_save")
    @_guard
    def r_rules_save(ctx, user, name, q, b):
        _need(ctx, name)
        rules = kubejs_rules.save(ctx, name, b.get("rules"))
        ctx.audit(user, name, "reglas de KubeJS guardadas", f"{len(rules)} reglas")
        out = kubejs_rules.load(ctx, name)
        out["morejs"] = "morejs" in ctx_addons(ctx, name)
        return 200, out
