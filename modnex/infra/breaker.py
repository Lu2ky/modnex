"""Circuit breaker: si un proveedor externo falla varias veces seguidas, las llamadas siguientes fallan al instante
(sin esperar al tiempo máximo de la red) durante un rato, y después se deja pasar una de prueba.

Sin esto, una caída de Modrinth hace que cada petición del panel espere 20 segundos y se acumulen hilos esperando.
Estados: cerrado (todo pasa), abierto (falla al instante) y medio abierto (pasa un único intento de prueba).
"""
import threading
import time


class ProviderUnavailable(OSError):
    """El proveedor no responde y el breaker está abierto. Es un OSError para que quien ya trata los fallos de red
    de forma elegante (usar una caché, mostrar una lista vacía) siga funcionando; el panel recibe un 503."""
    http_status = 503


class CircuitBreaker:
    def __init__(self, threshold=5, cooldown=30.0, clock=time.monotonic):
        self.threshold, self.cooldown, self.clock = threshold, cooldown, clock
        self.failures = 0
        self.opened_at = None      # momento en que se abrió; None = cerrado
        self.probing = False       # ya hay un intento de prueba en vuelo
        self._lock = threading.Lock()

    @property
    def state(self):
        with self._lock:
            if self.opened_at is None:
                return "closed"
            return "half-open" if self.clock() - self.opened_at >= self.cooldown else "open"

    def allow(self):
        """True si la llamada puede hacerse. Tras el enfriamiento solo se permite una a la vez."""
        with self._lock:
            if self.opened_at is None:
                return True
            if self.clock() - self.opened_at >= self.cooldown and not self.probing:
                self.probing = True
                return True
            return False

    def success(self):
        with self._lock:
            self.failures, self.opened_at, self.probing = 0, None, False

    def failure(self):
        with self._lock:
            self.failures += 1
            self.probing = False
            if self.opened_at is not None or self.failures >= self.threshold:
                self.opened_at = self.clock()       # una prueba fallida reinicia el enfriamiento


_BREAKERS = {}
_GUARD = threading.Lock()


def breaker_for(host):
    """Un breaker por proveedor (host): que se caiga uno no bloquea a los demás."""
    with _GUARD:
        return _BREAKERS.setdefault(host, CircuitBreaker())
