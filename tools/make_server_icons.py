"""Genera los iconos de tipo de servidor (static/brand/servers/*.png).

Son dibujos propios y sencillos: un mosaico de color con el monograma del tipo de servidor. No reproducen
ningún logotipo de terceros. Uso:  python3 tools/make_server_icons.py   (necesita Pillow)
"""
import colorsys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent.parent
OUT = HERE / "static" / "brand" / "servers"
FONT = HERE / "landing" / "assets" / "fonts" / "Inter.ttf"
S, SS = 160, 4          # tamaño final y factor de supersampling

# id -> (texto, tono 0-360). Los tonos se reparten para distinguirlos de un vistazo.
ICONS = {
    "vanilla": ("V", 140), "forge": ("F", 18), "neoforge": ("N", 28), "fabric": ("Fa", 40), "quilt": ("Q", 275),
    "paper": ("P", 205), "bukkit": ("B", 50), "spigot": ("S", 32), "purpur": ("Pu", 295), "velocity": ("Ve", 185),
    "sponge": ("Sp", 70), "mohist": ("M", 345), "catserver": ("Ca", 330), "arclight": ("Ar", 235),
    "thermos": ("T", 8), "modded": ("+", 160), "liteloader": ("Li", 215), "custom": ("*", 255),
    "unknown": ("?", 220), "disabled": ("-", 220),
}


def tile(text, hue, grey=False):
    n = S * SS
    sat = 0.04 if grey else 0.62
    top = tuple(round(c * 255) for c in colorsys.hls_to_rgb(hue / 360, 0.52 if not grey else 0.42, sat))
    bot = tuple(round(c * 255) for c in colorsys.hls_to_rgb(((hue + 28) % 360) / 360, 0.34 if not grey else 0.26, sat))
    img = Image.new("RGBA", (n, n))
    px = img.load()
    for y in range(n):
        t = y / (n - 1)
        row = tuple(round(top[i] + (bot[i] - top[i]) * t) for i in range(3)) + (255,)
        for x in range(n):
            px[x, y] = row
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, n - 1, n - 1), radius=n // 5, fill=255)
    img.putalpha(mask)
    over = Image.new("RGBA", (n, n), (0, 0, 0, 0))     # capa aparte: así el filete y el texto se mezclan en vez de sustituir píxeles
    d = ImageDraw.Draw(over)
    inset = n // 14      # filete interior: da relieve sin copiar ningún diseño
    d.rounded_rectangle((inset, inset, n - 1 - inset, n - 1 - inset), radius=n // 6, outline=(255, 255, 255, 70), width=n // 60)
    f = ImageFont.truetype(str(FONT), int(n * (0.5 if len(text) == 1 else 0.4)))
    try:
        f.set_variation_by_name("Bold")
    except Exception:
        pass
    box = d.textbbox((0, 0), text, font=f)
    d.text(((n - (box[2] - box[0])) / 2 - box[0], (n - (box[3] - box[1])) / 2 - box[1]), text, font=f, fill=(255, 255, 255, 245))
    img = Image.alpha_composite(img, over)
    img.putalpha(mask)
    return img.resize((S, S), Image.LANCZOS)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (text, hue) in ICONS.items():
        tile(text, hue, grey=(name == "disabled")).save(OUT / f"{name}.png", optimize=True)
    print(f"{len(ICONS)} iconos en {OUT}")
