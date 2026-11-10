"""Circuit breaker del cliente HTTP: se abre tras fallos seguidos, falla al instante y se recupera con una prueba."""
import sys, threading, unittest, urllib.error
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modnex.infra import net
from modnex.infra.breaker import CircuitBreaker, ProviderUnavailable, breaker_for


class Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t


class BreakerTests(unittest.TestCase):
    def setUp(self): self.clock = Clock(); self.b = CircuitBreaker(threshold=3, cooldown=30, clock=self.clock)

    def test_cerrado_deja_pasar_y_los_exitos_reinician_la_cuenta(self):
        self.b.failure(); self.b.failure(); self.b.success(); self.b.failure(); self.b.failure()
        self.assertEqual(self.b.state, "closed"); self.assertTrue(self.b.allow())

    def test_se_abre_tras_el_umbral_y_falla_al_instante(self):
        for _ in range(3): self.b.failure()
        self.assertEqual(self.b.state, "open"); self.assertFalse(self.b.allow())

    def test_pasado_el_enfriamiento_deja_pasar_una_sola_prueba(self):
        for _ in range(3): self.b.failure()
        self.clock.t = 31
        self.assertEqual(self.b.state, "half-open")
        self.assertTrue(self.b.allow()); self.assertFalse(self.b.allow(), "solo un intento de prueba a la vez")

    def test_la_prueba_con_exito_cierra(self):
        for _ in range(3): self.b.failure()
        self.clock.t = 31; self.b.allow(); self.b.success()
        self.assertEqual(self.b.state, "closed"); self.assertTrue(self.b.allow())

    def test_la_prueba_fallida_reinicia_el_enfriamiento(self):
        for _ in range(3): self.b.failure()
        self.clock.t = 31; self.b.allow(); self.b.failure()
        self.assertEqual(self.b.state, "open"); self.clock.t = 50
        self.assertFalse(self.b.allow(), "faltan 11 s desde la prueba fallida")
        self.clock.t = 62; self.assertTrue(self.b.allow())


class NetTests(unittest.TestCase):
    def setUp(self):
        from modnex.infra import breaker
        breaker._BREAKERS.clear(); self.url = "https://api.ejemplo.test/v1/x"

    def fail_with(self, exc, times):
        calls = []
        def call():
            calls.append(1); raise exc
        for _ in range(times):
            with self.assertRaises(type(exc)): net.guarded(self.url, call)
        return calls

    def test_errores_de_red_abren_el_breaker_y_dejan_de_llamar(self):
        calls = self.fail_with(urllib.error.URLError("sin red"), 5)
        self.assertEqual(len(calls), 5)
        with self.assertRaises(ProviderUnavailable) as cm: net.guarded(self.url, lambda: calls.append(1))
        self.assertEqual(len(calls), 5, "con el breaker abierto no se toca la red")
        self.assertEqual(cm.exception.http_status, 503); self.assertIsInstance(cm.exception, OSError)

    def test_5xx_y_429_cuentan_pero_404_no(self):
        self.fail_with(urllib.error.HTTPError(self.url, 404, "n", {}, None), 8)
        self.assertEqual(breaker_for("api.ejemplo.test").state, "closed")
        self.fail_with(urllib.error.HTTPError(self.url, 503, "n", {}, None), 5)
        self.assertEqual(breaker_for("api.ejemplo.test").state, "open")

    def test_un_host_caido_no_bloquea_a_otro(self):
        self.fail_with(OSError("x"), 5)
        self.assertEqual(net.guarded("https://otro.ejemplo.test/a", lambda: "ok"), "ok")

    def test_http_json_pasa_por_el_breaker(self):
        class R:
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def read(s): return b'{"a": 1}'
        with mock.patch.object(net.urllib.request, "urlopen", lambda *a, **k: R()):
            self.assertEqual(net.http_json(self.url), {"a": 1})
        with mock.patch.object(net.urllib.request, "urlopen", side_effect=urllib.error.URLError("x")):
            for _ in range(5):
                with self.assertRaises(urllib.error.URLError): net.http_json(self.url)
            with self.assertRaises(ProviderUnavailable): net.http_json(self.url)

    def test_sha1_distinto_no_cuenta_como_fallo_del_proveedor(self):
        import tempfile
        class R:
            headers = {"Content-Length": "3"}; n = 0
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def read(s, k):
                s.n += 1; return b"abc" if s.n == 1 else b""
        with tempfile.TemporaryDirectory() as d, mock.patch.object(net.urllib.request, "urlopen", lambda *a, **k: R()):
            for _ in range(6):
                with self.assertRaises(ValueError): net._download(self.url, Path(d) / "f.part", "0" * 40)
        self.assertEqual(breaker_for("api.ejemplo.test").state, "closed")

    def test_hilos_a_la_vez_no_rompen_la_cuenta(self):
        b = CircuitBreaker(threshold=50, cooldown=1)
        ts = [threading.Thread(target=lambda: [b.failure() for _ in range(10)]) for _ in range(5)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(b.failures, 50); self.assertEqual(b.state, "open")


if __name__ == "__main__":
    unittest.main()
