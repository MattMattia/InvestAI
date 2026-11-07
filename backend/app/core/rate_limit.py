"""
Motor de Rate Limiting Defensivo en Memoria por Ventana Deslizante (Módulo 5.4 - Fase 2).
Mitiga ataques de fuerza bruta, credential stuffing y password spraying en los endpoints de autenticación,
garantizando seguridad multihilo (threading.Lock) e higiene de memoria acotada anti-DoS.
"""

import threading
import time
from math import ceil

__all__ = [
    "SlidingWindowRateLimiter",
    "auth_rate_limiter",
]


class SlidingWindowRateLimiter:
    """
    Limitador de tasa basado en algoritmo de ventana deslizante (Sliding Window Log) en memoria.
    Thread-safe mediante `threading.Lock` para operar de forma determinista tanto en el
    event loop asíncrono como bajo clientes de prueba síncronos/multihilo.
    """

    def __init__(self, max_tracked_keys: int = 10_000) -> None:
        self._storage: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._max_tracked_keys: int = max_tracked_keys

    def is_rate_limited(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> tuple[bool, int, int]:
        """
        Evalúa si `key` ha excedido `max_requests` dentro de los últimos `window_seconds`.

        Retorna una tupla `(is_limited, retry_after, remaining)`:
        - `is_limited`: True si la solicitud debe ser bloqueada (HTTP 429), False si se permite.
        - `retry_after`: Segundos enteros (>= 1) hasta que se libere cupo cuando `is_limited` es True; 0 en caso contrario.
        - `remaining`: Solicitudes restantes disponibles en la ventana actual.
        """
        now = time.time()
        cutoff = now - window_seconds

        with self._lock:
            existing_timestamps = self._storage.get(key, [])
            valid_timestamps = [ts for ts in existing_timestamps if ts > cutoff]

            if not valid_timestamps:
                if key in self._storage:
                    del self._storage[key]
            else:
                self._storage[key] = valid_timestamps

            if len(valid_timestamps) >= max_requests:
                oldest = valid_timestamps[0] if valid_timestamps else now
                retry_after = max(1, int(ceil(window_seconds - (now - oldest))))
                return (True, retry_after, 0)

            if len(self._storage) >= self._max_tracked_keys and key not in self._storage:
                oldest_key = next(iter(self._storage))
                del self._storage[oldest_key]

            valid_timestamps.append(now)
            self._storage[key] = valid_timestamps
            remaining = max(0, max_requests - len(valid_timestamps))
            return (False, 0, remaining)

    def reset(self) -> None:
        """Limpia la totalidad del estado en memoria de manera thread-safe."""
        with self._lock:
            self._storage.clear()


# Instancia singleton global para protección de endpoints de identidad (/api/v1/auth/*)
auth_rate_limiter = SlidingWindowRateLimiter()
