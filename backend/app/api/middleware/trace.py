"""
Middleware de trazabilidad y correlación de solicitudes (OBS-01).
Inyecta identificadores de correlación (X-Request-ID) y medición de latencia (X-Execution-Time-Ms).
Mantiene un ContextVar accesible en cualquier capa de la aplicación sin acoplamiento.
"""
from contextvars import ContextVar
import time
from typing import Callable
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# ContextVar global para correlación de logs, manejadores de error y telemetría
request_id_ctx: ContextVar[str] = ContextVar("request_id_ctx", default="")


def get_current_request_id() -> str:
    """Obtiene el identificador de solicitud del contexto asíncrono actual."""
    return request_id_ctx.get()


class RequestTraceMiddleware(BaseHTTPMiddleware):
    """
    Middleware ASGI que propaga o genera el identificador X-Request-ID,
    mide la latencia de ejecución en milisegundos y expone los encabezados correspondientes.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 1. Capturar encabezado entrante o generar UUIDv4 trazable
        incoming_id = request.headers.get("X-Request-ID")
        req_id = incoming_id.strip() if incoming_id and incoming_id.strip() else str(uuid.uuid4())

        # 2. Registrar en ContextVar y en request.state
        token = request_id_ctx.set(req_id)
        request.state.request_id = req_id

        # 3. Medir tiempo de ejecución
        start_time = time.perf_counter()
        try:
            response = await call_next(request)
            execution_time_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            response.headers["X-Request-ID"] = req_id
            response.headers["X-Execution-Time-Ms"] = str(execution_time_ms)
            return response
        finally:
            request_id_ctx.reset(token)

