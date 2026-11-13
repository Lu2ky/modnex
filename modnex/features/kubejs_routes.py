"""KubeJS: recetas visuales, editor de scripts y diagnóstico. Solo en servidores con KubeJS instalado."""
from . import kubejs, kubejs_ae2, kubejs_check, kubejs_create, kubejs_history, kubejs_loot, kubejs_rules
from .guard import _guard


def _need(ctx, name):
    if not kubejs.installed(ctx, name):
        raise ValueError("KubeJS no está instalado en este servidor")


def ctx_addons(ctx, name):
    from ..services import servers
    return servers.addons_of(ctx.server_path(name))


def _snap(ctx, user, name, label):
    """Guarda una versión antes de cambiar nada. Si falla (disco lleno...) no impide guardar: solo se pierde el deshacer de ese cambio."""
    try:
        kubejs_history.snapshot(ctx, name, label, (user or {}).get("username", ""))
    except OSError:
        pass


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
        _snap(ctx, user, name, "Antes de guardar recetas")
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
        _snap(ctx, user, name, "Antes de cambiar las recetas quitadas")
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
        _snap(ctx, user, name, "Antes de borrar una receta")
        if b.get("store") == "create":
            kubejs_create.delete(ctx, name, slug)
            ctx.audit(user, name, "receta de Create borrada", slug)
            return 200, kubejs_create.load(ctx, name)
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
        _snap(ctx, user, name, "Antes de guardar reglas")
        rules = kubejs_rules.save(ctx, name, b.get("rules"))
        ctx.audit(user, name, "reglas de KubeJS guardadas", f"{len(rules)} reglas")
        out = kubejs_rules.load(ctx, name)
        out["morejs"] = "morejs" in ctx_addons(ctx, name)
        return 200, out

    @api.route("GET", "kubejs_gui")
    @_guard
    def r_gui(ctx, user, name, q, b):
        _need(ctx, name)
        return 200, {"textures": kubejs.gui_textures(ctx, name), "vanilla": kubejs.vanilla_status(ctx, name)}

    @api.route("GET", "kubejs_blocks")
    @_guard
    def r_blocks(ctx, user, name, q, b):
        _need(ctx, name)
        ids = [i for i in str((q or {}).get("ids", "")).split(",") if i][:60]
        models, textures = kubejs.block_models(ctx, name, ids)
        return 200, {"models": models, "textures": textures}

    @api.route("GET", "kubejs_create")
    @_guard
    def r_create(ctx, user, name, q, b):
        _need(ctx, name)
        out = kubejs_create.load(ctx, name)
        out["installed"] = "create" in ctx_addons(ctx, name)
        return 200, out

    @api.route("POST", "kubejs_create_save")
    @_guard
    def r_create_save(ctx, user, name, q, b):
        _need(ctx, name)
        _snap(ctx, user, name, "Antes de guardar recetas de Create")
        recipes = kubejs_create.save(ctx, name, b.get("recipes"))
        ctx.audit(user, name, "recetas de Create guardadas", f"{len(recipes)} recetas")
        out = kubejs_create.load(ctx, name)
        out["installed"] = "create" in ctx_addons(ctx, name)
        return 200, out

    @api.route("GET", "kubejs_fluids")
    @_guard
    def r_fluids(ctx, user, name, q, b):
        _need(ctx, name)
        return 200, {"fluids": kubejs.fluids(ctx, name)}

    @api.route("GET", "kubejs_loot")
    @_guard
    def r_loot(ctx, user, name, q, b):
        _need(ctx, name)
        return 200, kubejs_loot.load(ctx, name)

    @api.route("GET", "kubejs_loot_targets")
    @_guard
    def r_loot_targets(ctx, user, name, q, b):
        _need(ctx, name)
        q = q or {}
        return 200, {"targets": kubejs_loot.targets(ctx, name, str(q.get("kind", "block")), str(q.get("q", "")))}

    @api.route("GET", "kubejs_loot_current")
    @_guard
    def r_loot_current(ctx, user, name, q, b):
        _need(ctx, name)
        q = q or {}
        kind = str(q.get("kind", "block"))
        if kind not in kubejs_loot.KINDS:
            raise ValueError("tipo no válido")
        return 200, kubejs_loot.current(ctx, name, kind, str(q.get("target", "")))

    @api.route("POST", "kubejs_loot_save")
    @_guard
    def r_loot_save(ctx, user, name, q, b):
        _need(ctx, name)
        _snap(ctx, user, name, "Antes de guardar tablas de botín")
        rules = kubejs_loot.save(ctx, name, b.get("rules"))
        ctx.audit(user, name, "tablas de botín de KubeJS guardadas", f"{len(rules)} reglas")
        return 200, kubejs_loot.load(ctx, name)
    @api.route("POST", "kubejs_test")
    @_guard
    def r_test(ctx, user, name, q, b):
        _need(ctx, name)
        out = kubejs_check.run(ctx, name)
        ctx.audit(user, name, "scripts de KubeJS probados con /reload", "sin errores" if out["ok"] else f"{len(out['problems'])} problemas")
        return 200, out

    @api.route("GET", "kubejs_history")
    @_guard
    def r_history(ctx, user, name, q, b):
        _need(ctx, name)
        return 200, {"versions": kubejs_history.versions(ctx, name)}

    @api.route("POST", "kubejs_history_restore")
    @_guard
    def r_history_restore(ctx, user, name, q, b):
        _need(ctx, name)
        out = kubejs_history.restore(ctx, name, b.get("id"), (user or {}).get("username", ""))
        ctx.audit(user, name, "versión anterior de KubeJS restaurada", f"{out['restored']} ({out['files']} archivos)")
        return 200, {**out, "versions": kubejs_history.versions(ctx, name)}

    @api.route("GET", "kubejs_appeng")
    @_guard
    def r_ae2(ctx, user, name, q, b):
        _need(ctx, name)
        return 200, kubejs_ae2.load(ctx, name)

    @api.route("POST", "kubejs_appeng_save")
    @_guard
    def r_ae2_save(ctx, user, name, q, b):
        _need(ctx, name)
        _snap(ctx, user, name, "Antes de guardar recetas de AE2")
        recipes = kubejs_ae2.save(ctx, name, b.get("recipes"))
        ctx.audit(user, name, "recetas de AE2 guardadas con KubeJS", f"{len(recipes)} recetas")
        return 200, kubejs_ae2.load(ctx, name)
