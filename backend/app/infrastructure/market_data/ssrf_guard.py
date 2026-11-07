"""
Guardián de seguridad anti-SSRF (Server-Side Request Forgery) (Módulo 6 - Fase 2).
Valida esquemas, hostnames y rangos de direcciones IP para prevenir ataques SSRF hacia
redes internas, localhost, link-local y servicios de metadatos de nube (AWS/GCP/Azure).
"""

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlsplit

from app.domain.services.market_connector import SecuritySSRFViolationError

# Redes IPv4 e IPv6 estrictamente prohibidas para salida HTTP
BLOCKED_NETWORKS = [
    # IPv4 loopback, privadas y reservadas
    ipaddress.ip_network("0.0.0.0/8"),  # Red local actual / difusión
    ipaddress.ip_network("10.0.0.0/8"),  # RFC 1918 privada
    ipaddress.ip_network("100.64.0.0/10"),  # RFC 6598 Carrier Grade NAT
    ipaddress.ip_network("127.0.0.0/8"),  # Loopback localhost
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local / Cloud Metadata (169.254.169.254)
    ipaddress.ip_network("172.16.0.0/12"),  # RFC 1918 privada
    ipaddress.ip_network("192.168.0.0/16"),  # RFC 1918 privada
    ipaddress.ip_network("224.0.0.0/4"),  # Multicast
    ipaddress.ip_network("240.0.0.0/4"),  # Reservada / experimental
    # IPv6 loopback, únicas locales y link-local
    ipaddress.ip_network("::/128"),  # No especificada
    ipaddress.ip_network("::1/128"),  # Loopback IPv6
    ipaddress.ip_network("fc00::/7"),  # Unique Local Address (ULA)
    ipaddress.ip_network("fe80::/10"),  # Link-local IPv6
]

LOCAL_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "127.0.0.1",
    "::1",
    "0.0.0.0",  # noqa: S104  # blocklist entry, not a bind address
}


def _default_dns_resolver(hostname: str) -> list[str]:
    """Resolución DNS estándar utilizando socket.getaddrinfo."""
    try:
        addr_info = socket.getaddrinfo(hostname, None)
        # Extraer las IPs únicas resueltas
        ips = list({sockaddr[0] for _, _, _, _, sockaddr in addr_info})
        if not ips:
            raise SecuritySSRFViolationError(
                f"No fue posible resolver la dirección para el host '{hostname}'."
            )
        return ips
    except socket.gaierror as e:
        raise SecuritySSRFViolationError(
            f"Fallo en la resolución DNS para el host '{hostname}': {e}"
        ) from e
    except Exception as e:
        raise SecuritySSRFViolationError(f"Error inesperado al resolver '{hostname}': {e}") from e


def validate_ip_address(ip_str: str) -> None:
    """
    Verifica si una dirección IP pertenece a algún rango prohibido o reservado.
    Lanza SecuritySSRFViolationError si la IP no es pública y segura.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError as e:
        raise SecuritySSRFViolationError(f"Dirección IP inválida '{ip_str}': {e}") from e

    # Verificación contra redes explícitas
    for blocked_net in BLOCKED_NETWORKS:
        if ip.version == blocked_net.version and ip in blocked_net:
            raise SecuritySSRFViolationError(
                f"Violación de seguridad SSRF: la dirección IP '{ip_str}' pertenece "
                f"al rango restringido/privado {blocked_net}."
            )

    # Verificación complementaria por propiedades estándar
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_unspecified
        or ip.is_reserved
        or ip.is_multicast
    ):
        raise SecuritySSRFViolationError(
            f"Violación de seguridad SSRF: la dirección IP '{ip_str}' está clasificada "
            f"como privada o no enrutable públicamente."
        )


def validate_url_against_ssrf(
    url: str,
    dns_resolver: Callable[[str], list[str]] | None = None,
) -> str:
    """
    Valida rigurosamente una URL para mitigar ataques de Server-Side Request Forgery (SSRF).

    Reglas de validación:
    ---------------------
    1. Esquema estricto: Únicamente 'http' o 'https'.
    2. Hostname no vacío ni perteneciente a nombres locales estándar.
    3. Resolución y comprobación de IPs: Ninguna IP resuelta puede pertenecer a rangos
       privados (RFC 1918), loopback, link-local (metadatos de nube) o reservados.

    Parámetros:
    -----------
    url: Dirección URL completa a validar.
    dns_resolver: Función opcional para inyectar resolución de nombres (ideal para pruebas sin red).

    Retorna:
    --------
    str: La URL validada si cumple con todas las políticas de seguridad.

    Lanza:
    ------
    SecuritySSRFViolationError: Si la URL o alguno de sus destinos IP es sospechoso o prohibido.
    """
    if not url or not isinstance(url, str):
        raise SecuritySSRFViolationError("La URL no puede ser nula ni vacía.")

    parsed = urlsplit(url)

    # 1. Esquema
    if parsed.scheme.lower() not in ("http", "https"):
        raise SecuritySSRFViolationError(
            f"Esquema no autorizado '{parsed.scheme}'. Solo se permiten protocolos http o https."
        )

    # 2. Hostname
    hostname = parsed.hostname
    if not hostname:
        raise SecuritySSRFViolationError("La URL provista no contiene un hostname válido.")

    hostname_lower = hostname.strip().lower()
    if (
        hostname_lower in LOCAL_HOSTNAMES
        or hostname_lower.endswith(".local")
        or hostname_lower.endswith(".internal")
    ):
        raise SecuritySSRFViolationError(
            f"Acceso prohibido a host o dominio interno/local: '{hostname}'."
        )

    # 3. Detección de IP literal vs Nombre de dominio
    try:
        # Si hostname es una IP literal válida, la validamos directamente sin DNS
        ipaddress.ip_address(hostname_lower)
        validate_ip_address(hostname_lower)
        return url
    except ValueError:
        # No es IP literal, es un nombre de dominio
        pass

    # 4. Resolución de nombres
    resolver = dns_resolver or _default_dns_resolver
    resolved_ips = resolver(hostname_lower)

    if not resolved_ips:
        raise SecuritySSRFViolationError(
            f"El hostname '{hostname}' no resolvió a ninguna dirección IP."
        )

    # Validar cada una de las IPs resueltas
    for ip_candidate in resolved_ips:
        validate_ip_address(ip_candidate)

    return url
