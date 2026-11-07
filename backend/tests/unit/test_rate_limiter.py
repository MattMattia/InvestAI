"""
Pruebas unitarias herméticas para el motor de Rate Limiting en memoria (Módulo 5.4 - Fase 2).
Valida el algoritmo de ventana deslizante (SlidingWindowRateLimiter), cálculo de retry_after,
expiración temporal, higiene de claves huérfanas, cota máxima de memoria (_max_tracked_keys),
reset de estado y seguridad multihilo con ThreadPoolExecutor.
"""

import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from app.core.rate_limit import SlidingWindowRateLimiter


@pytest.mark.unit
class TestSlidingWindowRateLimiter(unittest.TestCase):
    """Suite unitaria para SlidingWindowRateLimiter."""

    def setUp(self) -> None:
        self.limiter = SlidingWindowRateLimiter()

    def test_sliding_window_allows_up_to_max_and_blocks_next(self) -> None:
        """
        Verifica que se permitan peticiones hasta max_requests con decremento exacto
        de remaining, y que la siguiente sea bloqueada retornando (True, retry_after, 0).
        """
        key = "login:account:127.0.0.1:user@investai.com"
        max_req = 3
        window = 60

        is_lim_1, retry_1, rem_1 = self.limiter.is_rate_limited(key, max_req, window)
        self.assertFalse(is_lim_1)
        self.assertEqual(retry_1, 0)
        self.assertEqual(rem_1, 2)

        is_lim_2, retry_2, rem_2 = self.limiter.is_rate_limited(key, max_req, window)
        self.assertFalse(is_lim_2)
        self.assertEqual(retry_2, 0)
        self.assertEqual(rem_2, 1)

        is_lim_3, retry_3, rem_3 = self.limiter.is_rate_limited(key, max_req, window)
        self.assertFalse(is_lim_3)
        self.assertEqual(retry_3, 0)
        self.assertEqual(rem_3, 0)

        # 4ta petición excede el límite
        is_lim_4, retry_4, rem_4 = self.limiter.is_rate_limited(key, max_req, window)
        self.assertTrue(is_lim_4)
        self.assertGreater(retry_4, 0)
        self.assertEqual(rem_4, 0)

    def test_retry_after_calculation_coherence(self) -> None:
        """
        Verifica que retry_after sea estrictamente > 0 y coherente con el tiempo
        restante de la ventana deslizante respecto a la marca más antigua.
        """
        key = "login:ip:10.0.0.5"
        with patch("app.core.rate_limit.time.time") as mock_time:
            mock_time.return_value = 1000.0
            self.limiter.is_rate_limited(key, max_requests=2, window_seconds=60)

            mock_time.return_value = 1015.0
            self.limiter.is_rate_limited(key, max_requests=2, window_seconds=60)

            # A los 1025.3s (han pasado 25.3s desde la marca más antigua en 1000.0):
            # restan 60 - 25.3 = 34.7s -> ceil(34.7) = 35s
            mock_time.return_value = 1025.3
            is_limited, retry_after, remaining = self.limiter.is_rate_limited(
                key, max_requests=2, window_seconds=60
            )
            self.assertTrue(is_limited)
            self.assertEqual(retry_after, 35)
            self.assertEqual(remaining, 0)

    def test_window_expiration_discards_old_timestamps(self) -> None:
        """
        Verifica que las marcas fuera de la ventana temporal se descarten y permitan
        nuevas peticiones una vez transcurrido window_seconds.
        """
        key = "register:ip:192.168.1.10"
        with patch("app.core.rate_limit.time.time") as mock_time:
            mock_time.return_value = 5000.0
            self.limiter.is_rate_limited(key, max_requests=2, window_seconds=30)
            self.limiter.is_rate_limited(key, max_requests=2, window_seconds=30)

            # En t=5010 sigue bloqueado
            mock_time.return_value = 5010.0
            is_lim_mid, _, _ = self.limiter.is_rate_limited(key, max_requests=2, window_seconds=30)
            self.assertTrue(is_lim_mid)

            # En t=5030.1 las marcas en 5000.0 han expirado -> se permite nueva petición
            mock_time.return_value = 5030.1
            is_lim_after, retry_after, rem_after = self.limiter.is_rate_limited(
                key, max_requests=2, window_seconds=30
            )
            self.assertFalse(is_lim_after)
            self.assertEqual(retry_after, 0)
            self.assertEqual(rem_after, 1)

    def test_memory_hygiene_removes_orphan_keys(self) -> None:
        """
        Verifica que las claves cuyas marcas han expirado por completo se eliminen
        del diccionario interno _storage para evitar fugas de memoria.
        """
        with patch("app.core.rate_limit.time.time") as mock_time:
            mock_time.return_value = 2000.0
            self.limiter.is_rate_limited("orphan:key:1", max_requests=3, window_seconds=10)
            self.assertIn("orphan:key:1", self.limiter._storage)

            # Avanzar más allá de la ventana (t=2015.0)
            mock_time.return_value = 2015.0
            # Consultar con max_requests=0 sobre la misma clave tras expirar:
            # la lista filtrada queda vacía y la clave se elimina de _storage
            is_lim, _, _ = self.limiter.is_rate_limited(
                "orphan:key:1", max_requests=0, window_seconds=10
            )
            self.assertTrue(is_lim)
            self.assertNotIn("orphan:key:1", self.limiter._storage)

    def test_max_tracked_keys_evicts_oldest_key(self) -> None:
        """
        Verifica la cota máxima anti-DoS (_max_tracked_keys): al superar la capacidad,
        se desaloja determinísticamente la clave más antigua.
        """
        bounded_limiter = SlidingWindowRateLimiter(max_tracked_keys=3)

        bounded_limiter.is_rate_limited("key_1", max_requests=5, window_seconds=60)
        bounded_limiter.is_rate_limited("key_2", max_requests=5, window_seconds=60)
        bounded_limiter.is_rate_limited("key_3", max_requests=5, window_seconds=60)
        self.assertEqual(len(bounded_limiter._storage), 3)

        # Insertar una 4ta clave distinta debe desalojar 'key_1'
        bounded_limiter.is_rate_limited("key_4", max_requests=5, window_seconds=60)
        self.assertEqual(len(bounded_limiter._storage), 3)
        self.assertNotIn("key_1", bounded_limiter._storage)
        self.assertIn("key_2", bounded_limiter._storage)
        self.assertIn("key_3", bounded_limiter._storage)
        self.assertIn("key_4", bounded_limiter._storage)

    def test_reset_clears_all_records(self) -> None:
        """Verifica que reset() vacíe por completo el almacenamiento interno."""
        self.limiter.is_rate_limited("k1", max_requests=5, window_seconds=60)
        self.limiter.is_rate_limited("k2", max_requests=5, window_seconds=60)
        self.assertEqual(len(self.limiter._storage), 2)

        self.limiter.reset()
        self.assertEqual(len(self.limiter._storage), 0)

    def test_thread_safety_under_concurrent_access(self) -> None:
        """
        Verifica concurrencia segura ante múltiples hilos simultáneos usando ThreadPoolExecutor:
        de 50 intentos concurrentes sobre una clave con límite 10, exactamente 10 deben
        permitirse y 40 deben ser bloqueados.
        """
        key = "concurrent:login:ip:127.0.0.1"
        max_requests = 10
        total_attempts = 50

        def _attempt(_: int) -> bool:
            is_limited, _, _ = self.limiter.is_rate_limited(
                key, max_requests=max_requests, window_seconds=60
            )
            return is_limited

        with ThreadPoolExecutor(max_workers=16) as executor:
            results = list(executor.map(_attempt, range(total_attempts)))

        allowed_count = sum(1 for r in results if not r)
        blocked_count = sum(1 for r in results if r)

        self.assertEqual(allowed_count, max_requests)
        self.assertEqual(blocked_count, total_attempts - max_requests)
        self.assertEqual(len(self.limiter._storage[key]), max_requests)

    def test_cross_window_isolation_does_not_evict_longer_window_keys(self) -> None:
        """
        Verifica aislamiento entre claves con ventanas distintas (ej. register=300s vs login=60s):
        una consulta con window_seconds=60 no debe purgar prematuramente marcas de una clave con
        window_seconds=300 que tengan 90s de antigüedad (AUD-C5-01).
        """
        reg_key = "register:ip:10.0.0.1"
        login_key = "login:ip:10.0.0.2"
        with patch("app.core.rate_limit.time.time") as mock_time:
            mock_time.return_value = 1000.0
            # Agotar límite de registro (3 peticiones en ventana de 300s)
            for _ in range(3):
                is_lim, _, _ = self.limiter.is_rate_limited(
                    reg_key, max_requests=3, window_seconds=300
                )
                self.assertFalse(is_lim)

            # Avanzar 90s (t=1090.0): aún restan 210s de bloqueo para reg_key (ventana de 300s),
            # pero supera la ventana de 60s de login_key
            mock_time.return_value = 1090.0
            self.limiter.is_rate_limited(login_key, max_requests=20, window_seconds=60)

            # reg_key debe permanecer bloqueada en t=1090.0 con retry_after == 210s
            is_reg_limited, retry_after, remaining = self.limiter.is_rate_limited(
                reg_key, max_requests=3, window_seconds=300
            )
            self.assertTrue(is_reg_limited)
            self.assertEqual(retry_after, 210)
            self.assertEqual(remaining, 0)


if __name__ == "__main__":
    unittest.main()
