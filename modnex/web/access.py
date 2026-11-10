"""Política de acceso: de dónde llega cada petición y si un administrador puede usar el panel desde ahí.

Es un mixin del manejador HTTP. Las cabeceras de un túnel (Cf-Connecting-Ip, X-Forwarded-For) solo se creen si la
conexión llega desde esta misma máquina, porque el túnel conecta por loopback; desde la red local se ignoran para
que nadie pueda falsificarlas.
"""
import ipaddress
import urllib.parse

from modnex.config import load_config


class AccessPolicy:
    PRIVATE_SUFFIXES = (".local", ".lan", ".home", ".internal", ".localdomain", ".home.arpa")

    def _peer_loopback(self):
        return self.client_address[0] in ("127.0.0.1", "::1")

    def _client_ip(self):
        """IP real del cliente (ver la nota del módulo sobre las cabeceras de túnel)."""
        if self._peer_loopback():
            for h in ("Cf-Connecting-Ip", "X-Forwarded-For"):
                v = (self.headers.get(h) or "").split(",")[0].strip()
                if v:
                    return v[:64]
        return self.client_address[0]

    def _via_tunnel(self):
        return self._peer_loopback() and bool(self.headers.get("Cf-Connecting-Ip") or self.headers.get("X-Forwarded-For"))

    @staticmethod
    def _is_local_ip(value):
        """Local = no enrutable por internet (loopback, red local, ZeroTier, Tailscale, enlace local)."""
        try:
            ip = ipaddress.ip_address(str(value).strip())
        except ValueError:
            return False
        ip = getattr(ip, "ipv4_mapped", None) or ip
        return not ip.is_global

    def _host_is_public_name(self):
        """True si el Host de la petición es un nombre de dominio público (p. ej. el de un túnel)."""
        h = (self.headers.get("Host") or "").strip().lower()
        if h.startswith("["):
            return False                      # IPv6 literal
        h = h.rsplit(":", 1)[0] if h.count(":") == 1 else h
        try:
            ipaddress.ip_address(h)
            return False                      # IP literal: se juzga por la IP
        except ValueError:
            pass
        return "." in h and not h.endswith(self.PRIVATE_SUFFIXES)

    def _remote_origin(self):
        """True si la petición llega desde fuera de este equipo y de la red local.
        Se considera remota si pasa por un túnel (cabeceras de reenvío desde loopback), si la conexión viene
        de una IP enrutable, o si llega por loopback pero con un nombre de dominio público en `Host`."""
        if self._via_tunnel():
            return True
        peer = self.client_address[0]
        if not self._is_local_ip(peer):
            return True
        return self._peer_loopback() and self._host_is_public_name()

    def _admin_remote_blocked(self, user):
        """Los administradores solo entran desde el equipo o la red local, salvo `admin_remote: true` en config.json."""
        return bool(user and user.get("is_admin") and self._remote_origin() and load_config().get("admin_remote") is not True)

    def _https(self):
        return self._peer_loopback() and (self.headers.get("X-Forwarded-Proto") or "").lower() == "https"

    def _same_origin(self):
        origin = self.headers.get("Origin")
        return origin is None or urllib.parse.urlparse(origin).netloc == self.headers.get("Host", "")
