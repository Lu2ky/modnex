"""Diagnóstico de los registros y crashes."""
from . import doctor
from .guard import _guard


def register(api):
    ctx = api.ctx

    @api.route("GET", "doctor")
    @_guard
    def r_doctor(ctx, user, name, q, b):
        return 200, doctor.diagnose(ctx, name)
