"""
Pruebas unitarias para el Middleware de Trazabilidad y Correlación (OBS-01).
Valida ContextVar, aislamiento entre tareas asíncronas y resolución de request_id.
"""

import asyncio
import unittest

from app.api.middleware.trace import get_current_request_id, request_id_ctx


class TestTraceMiddlewareUnit(unittest.TestCase):
    def test_default_request_id_is_empty(self):
        """Valida que fuera del contexto de una solicitud, get_current_request_id() retorne cadena vacía."""
        self.assertEqual(get_current_request_id(), "")

    def test_context_var_set_and_reset(self):
        """Valida que request_id_ctx pueda establecerse y restaurarse correctamente."""
        token = request_id_ctx.set("req-test-123")
        self.assertEqual(get_current_request_id(), "req-test-123")
        request_id_ctx.reset(token)
        self.assertEqual(get_current_request_id(), "")

    def test_async_task_context_isolation(self):
        """Valida que el ContextVar no se contamine entre corrutinas concurrentes."""

        async def task_worker(task_id: str):
            token = request_id_ctx.set(task_id)
            await asyncio.sleep(0.01)
            observed = get_current_request_id()
            request_id_ctx.reset(token)
            return observed

        async def main():
            results = await asyncio.gather(
                task_worker("task-alpha"),
                task_worker("task-beta"),
                task_worker("task-gamma"),
            )
            return results

        results = asyncio.run(main())
        self.assertEqual(results, ["task-alpha", "task-beta", "task-gamma"])
        self.assertEqual(get_current_request_id(), "")


if __name__ == "__main__":
    unittest.main()
