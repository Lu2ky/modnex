"""Propuestas de mods de los jugadores."""
from . import notify, proposals
from .guard import _guard


def register(api):
    ctx = api.ctx

    @api.route("GET", "proposal_search")
    @_guard(perm="*")
    def r_proposal_search(ctx, user, name, q, b):
        text = (q.get("q") or "").strip()[:80]
        source = q.get("source", "modrinth")
        if source not in proposals.SOURCES:
            raise ValueError("proveedor no válido")
        loader, _kind = ctx.compat_for(name, "mod")
        mc = ctx.server_versions(name).get("minecraft") or "1.21.1"
        try:
            raw = ctx.search(source, text, loader, mc, "mod", "auto", "server")
        except (OSError, RuntimeError) as e:
            return 502, {"error": f"no se pudo buscar en {source}: {e}"}
        return 200, {"results": proposals.search_results(raw)}

    @api.route("GET", "proposals")
    @_guard(perm="*")
    def r_proposals(ctx, user, name, q, b):
        return 200, {"proposals": proposals.list_for(ctx, name), "can_decide": bool(user.get("is_admin")), "me": user["id"]}

    @api.route("POST", "proposal_create")
    @_guard(perm="*")
    def r_proposal_create(ctx, user, name, q, b):
        pid = proposals.create(ctx, name, user, str(b.get("source")), str(b.get("project_id") or ""), str(b.get("title") or ""),
                               slug=str(b.get("slug") or ""), icon=str(b.get("icon") or ""), note=str(b.get("note") or ""))
        ctx.audit(user, name, "propuesta de mod", f"{b.get('title')}")
        notify.send(ctx, name, "proposals", f"{user['username']} propuso «{str(b.get('title'))[:80]}» en «{name}».")
        return 200, {"id": pid}

    @api.route("POST", "proposal_decide")
    @_guard
    def r_proposal_decide(ctx, user, name, q, b):
        status = proposals.decide(ctx, name, user, b.get("id"), str(b.get("decision")), str(b.get("reason") or ""))
        ctx.audit(user, name, "propuesta de mod " + ("aprobada" if status == "approved" else "rechazada"), str(b.get("id")))
        notify.send(ctx, name, "proposals", f"Propuesta en «{name}» {'aprobada' if status == 'approved' else 'rechazada'} por {user['username']}.")
        return 200, {"status": status}

    @api.route("POST", "proposal_withdraw")
    @_guard(perm="*")
    def r_proposal_withdraw(ctx, user, name, q, b):
        proposals.withdraw(ctx, name, user, b.get("id"))
        return 200, {"ok": True}
