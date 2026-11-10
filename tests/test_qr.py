import re, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.features import qr

try:
    import zxingcpp
    from PIL import Image
except ImportError:
    zxingcpp = None

URI = "otpauth://totp/Modnex:ana?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP&issuer=Modnex&algorithm=SHA1&digits=6&period=30"


def render(m, scale=8, border=4):
    n = len(m); img = Image.new("L", ((n + 2 * border) * scale,) * 2, 255); px = img.load()
    for y, row in enumerate(m):
        for x, c in enumerate(row):
            if c:
                for dy in range(scale):
                    for dx in range(scale): px[(x + border) * scale + dx, (y + border) * scale + dy] = 0
    return img


class EstructuraTests(unittest.TestCase):
    def test_tamano_segun_longitud(self):
        self.assertEqual(len(qr.matrix("a")), 21); self.assertEqual(len(qr.matrix("a" * 15)), 25); self.assertEqual(len(qr.matrix("a" * 213)), 57)

    def test_finders_y_temporizacion(self):
        m = qr.matrix(URI); n = len(m)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
            self.assertTrue(m[cy][cx]); self.assertFalse(m[cy][cx + 2] if cx + 2 < n else False)
            self.assertTrue(m[cy - 3][cx - 3 if cx - 3 >= 0 else cx + 3])
        self.assertTrue(all(m[6][i] == (i % 2 == 0) for i in range(8, n - 8)))

    def test_modulo_oscuro_y_determinista(self):
        m = qr.matrix(URI); self.assertTrue(m[len(m) - 8][8]); self.assertEqual(m, qr.matrix(URI))

    def test_reed_solomon_sin_errores(self):
        data = list(range(1, 17)); ec = qr._rs_remainder(data, 10); word = data + ec
        for i in range(10):   # el polinomio completo se anula en las raíces del generador
            acc = 0
            for c in word: acc = qr._gmul(acc, qr._EXP[i]) ^ c
            self.assertEqual(acc, 0, i)

    def test_demasiado_largo_y_texto_unicode(self):
        with self.assertRaises(qr.QRError): qr.matrix("x" * 300)
        self.assertTrue(qr.matrix("ñandú ✓"))

    def test_svg_valido_y_sin_estilos_en_linea(self):
        s = qr.svg(URI)
        self.assertTrue(s.startswith("<svg") and s.endswith("</svg>")); self.assertNotIn("style=", s); self.assertNotIn("<script", s)
        n = len(qr.matrix(URI)) + 8
        self.assertIn(f'viewBox="0 0 {n} {n}"', s); self.assertEqual(len(re.findall(r"<path", s)), 1); self.assertLess(len(s), 9000)


@unittest.skipUnless(zxingcpp, "sin decodificador (zxing-cpp) no se comprueba la lectura")
class LecturaTests(unittest.TestCase):
    def test_se_lee_con_todas_las_mascaras_y_longitudes(self):
        import random; random.seed(3)
        for n in (1, 14, 15, 42, 43, 84, 85, 122, 123, 152, 153, 213):
            text = "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789:/?&=._-") for _ in range(n))
            for mask in list(range(8)) + [None]:
                r = zxingcpp.read_barcodes(render(qr.matrix(text, mask)))
                self.assertTrue(r and r[0].text == text, (n, mask))

    def test_el_enlace_otpauth_se_lee(self):
        r = zxingcpp.read_barcodes(render(qr.matrix(URI))); self.assertEqual(r[0].text, URI)


if __name__ == "__main__":
    unittest.main()
