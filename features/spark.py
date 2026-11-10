"""spark (perfilador de rendimiento, GPL-3.0; mod aparte, no se incluye su código).

Aquí solo se ofrece como extra al crear un servidor: el núcleo lo descarga de Modrinth y lo deja en
`mods/`. Paper no lo necesita (lo trae incluido) y Modrinth no publica una versión para él.
"""
LOADERS = {"fabric", "neoforge", "forge"}


def install(ctx, name):
    return ctx.install_modrinth(name, "spark", loaders=LOADERS, prefix="spark")
