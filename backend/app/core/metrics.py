"""
Telemetry and RED Metrics (Rate, Errors, Duration) Engine for InvestAI.
Provides centralized Prometheus instrumentation, cardinality defense, and async middleware.
"""

from __future__ import annotations

import logging
import time

from fastapi import Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.routing import Match

logger = logging.getLogger("investai.metrics")

# Optimized geometric buckets for HTTP duration (in seconds)
HTTP_DURATION_BUCKETS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)

# Buckets for scheduler job duration (in seconds)
SCHEDULER_DURATION_BUCKETS: tuple[float, ...] = (
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
)

# Buckets for quantitative solver latency (in seconds, capturing sub-millisecond to multi-second)
QUANT_SOLVER_DURATION_BUCKETS: tuple[float, ...] = (
    0.0005,
    0.001,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
)

# Buckets for solver iteration count
QUANT_SOLVER_ITERATION_BUCKETS: tuple[float, ...] = (
    5.0,
    10.0,
    25.0,
    50.0,
    100.0,
    250.0,
    500.0,
    1000.0,
)

# Canonical catalog of fallback reasons preventing cardinality explosion
KNOWN_FALLBACK_REASONS: frozenset[str] = frozenset(
    {
        "max_iter_exceeded",
        "non_positive_definite",
        "singular_matrix",
        "tolerance_not_reached",
        "numerical_instability",
    }
)

# Canonical catalog of market data cache tiers
KNOWN_CACHE_TIERS: frozenset[str] = frozenset(
    {
        "memory",
        "redis",
    }
)


def normalize_route_path(request: Request) -> str:
    """
    Extracts the canonical route template (e.g., '/api/v1/portfolios/{portfolio_id}')
    to prevent Prometheus label cardinality explosion.
    Returns 'unmatched_route' if no registered route matches the request.
    """
    try:
        # Priority 1: Check if scope already resolved the route
        route = request.scope.get("route")
        if route is not None and hasattr(route, "path"):
            return str(route.path)

        # Priority 2: Iterate registered app routes against request scope
        app = getattr(request, "app", None)
        if app is not None and hasattr(app, "routes"):
            # First pass: check for exact match (path and method)
            for r in app.routes:
                try:
                    match, _ = r.matches(request.scope)
                    if match == Match.FULL and hasattr(r, "path"):
                        return str(r.path)
                except Exception:  # noqa: S112  # unmatched route must not break normalization
                    continue

            # Second pass: check for partial match (path matches, method differs e.g. 405)
            for r in app.routes:
                try:
                    match, _ = r.matches(request.scope)
                    if match == Match.PARTIAL and hasattr(r, "path"):
                        return str(r.path)
                except Exception:  # noqa: S112  # unmatched route must not break normalization
                    continue
    except Exception as exc:
        logger.debug("Error while normalizing route path: %s", exc)

    return "unmatched_route"


class InvestAIMetrics:
    """
    Centralized Prometheus metrics registry and collector for InvestAI.
    Tracks RED HTTP metrics (Rate, Errors, Duration) and business/scheduler execution telemetry.
    """

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry: CollectorRegistry = (
            registry if registry is not None else CollectorRegistry(auto_describe=True)
        )

        # RED Metrics: Rate & Status
        self.http_requests_total: Counter = Counter(
            name="http_requests_total",
            documentation="Total count of HTTP requests processed by method, path template and status code.",
            labelnames=["method", "path", "status_code"],
            registry=self.registry,
        )

        # RED Metrics: Duration (Latency)
        self.http_request_duration_seconds: Histogram = Histogram(
            name="http_request_duration_seconds",
            documentation="Histogram of HTTP request processing duration in seconds.",
            labelnames=["method", "path"],
            buckets=HTTP_DURATION_BUCKETS,
            registry=self.registry,
        )

        # RED Metrics: Errors (Unhandled exceptions)
        self.http_requests_exceptions_total: Counter = Counter(
            name="http_requests_exceptions_total",
            documentation="Total count of unhandled exceptions raised during HTTP request processing.",
            labelnames=["method", "path", "exception_type"],
            registry=self.registry,
        )

        # Business & Scheduler Telemetry
        self.scheduler_jobs_total: Counter = Counter(
            name="scheduler_jobs_total",
            documentation="Total count of market scheduler job executions by status and trigger type.",
            labelnames=["status", "trigger_type"],
            registry=self.registry,
        )

        self.scheduler_duration_seconds: Histogram = Histogram(
            name="scheduler_duration_seconds",
            documentation="Histogram of market scheduler job execution duration in seconds.",
            labelnames=["status"],
            buckets=SCHEDULER_DURATION_BUCKETS,
            registry=self.registry,
        )

        self.scheduler_portfolios_processed_total: Counter = Counter(
            name="scheduler_portfolios_processed_total",
            documentation="Total count of portfolios processed during close jobs by outcome status.",
            labelnames=["status"],
            registry=self.registry,
        )

        self.scheduler_orders_generated_total: Counter = Counter(
            name="scheduler_orders_generated_total",
            documentation="Total count of rebalance FSM orders generated during market close jobs.",
            registry=self.registry,
        )

        # Specialized Quantitative Telemetry (Módulo 8.3 - Fase 2)
        self.quant_solver_duration_seconds: Histogram = Histogram(
            name="quant_solver_duration_seconds",
            documentation="Histogram of quantitative optimization solver duration in seconds.",
            labelnames=["solver_name", "objective"],
            buckets=QUANT_SOLVER_DURATION_BUCKETS,
            registry=self.registry,
        )

        self.quant_solver_fallbacks_total: Counter = Counter(
            name="quant_solver_fallbacks_total",
            documentation="Total count of quantitative solver fallbacks and algorithmic commutations.",
            labelnames=["from_solver", "to_solver", "reason"],
            registry=self.registry,
        )

        self.quant_solver_iterations: Histogram = Histogram(
            name="quant_solver_iterations",
            documentation="Histogram of quantitative optimization solver iteration counts.",
            labelnames=["solver_name"],
            buckets=QUANT_SOLVER_ITERATION_BUCKETS,
            registry=self.registry,
        )

        self.market_data_cache_hits_total: Counter = Counter(
            name="market_data_cache_hits_total",
            documentation="Total count of market data quote and bar cache hits by tier.",
            labelnames=["cache_tier"],
            registry=self.registry,
        )

        self.market_data_cache_misses_total: Counter = Counter(
            name="market_data_cache_misses_total",
            documentation="Total count of market data quote and bar cache misses by tier.",
            labelnames=["cache_tier"],
            registry=self.registry,
        )

    def record_http_request(
        self,
        method: str,
        path: str,
        status_code: int | str,
        duration_seconds: float,
    ) -> None:
        """Records an HTTP request completion with latency and status code."""
        norm_method = (method or "UNKNOWN").upper()
        norm_path = path or "unmatched_route"
        norm_status = str(status_code)

        self.http_requests_total.labels(
            method=norm_method,
            path=norm_path,
            status_code=norm_status,
        ).inc()

        self.http_request_duration_seconds.labels(
            method=norm_method,
            path=norm_path,
        ).observe(max(0.0, float(duration_seconds)))

    def record_http_exception(
        self,
        method: str,
        path: str,
        exception_type: str,
    ) -> None:
        """Records an unhandled HTTP exception."""
        norm_method = (method or "UNKNOWN").upper()
        norm_path = path or "unmatched_route"
        self.http_requests_exceptions_total.labels(
            method=norm_method,
            path=norm_path,
            exception_type=exception_type,
        ).inc()

    def record_scheduler_job(
        self,
        status: str,
        trigger_type: str,
        duration_seconds: float,
    ) -> None:
        """Records a market close scheduler job execution."""
        self.scheduler_jobs_total.labels(
            status=status,
            trigger_type=trigger_type,
        ).inc()
        self.scheduler_duration_seconds.labels(
            status=status,
        ).observe(max(0.0, float(duration_seconds)))

    def record_scheduler_portfolios(
        self,
        status: str,
        count: int = 1,
    ) -> None:
        """Records processed portfolios count by outcome status."""
        if count > 0:
            self.scheduler_portfolios_processed_total.labels(
                status=status,
            ).inc(count)

    def record_scheduler_orders_generated(self, count: int = 1) -> None:
        """Records the number of rebalance FSM tickets generated."""
        if count > 0:
            self.scheduler_orders_generated_total.inc(count)

    def record_solver_run(
        self,
        solver_name: str,
        objective: str,
        duration_seconds: float,
        iterations: int | None = None,
    ) -> None:
        """
        Records a quantitative optimization solver run latency and optional iteration count.
        """
        dur = max(0.0, float(duration_seconds))
        self.quant_solver_duration_seconds.labels(
            solver_name=solver_name,
            objective=objective,
        ).observe(dur)

        if iterations is not None and iterations >= 0:
            self.quant_solver_iterations.labels(
                solver_name=solver_name,
            ).observe(float(iterations))

    def record_solver_fallback(
        self,
        from_solver: str,
        to_solver: str,
        reason: str,
    ) -> None:
        """
        Records a solver fallback or algorithmic commutation event.
        Sanitizes reason against KNOWN_FALLBACK_REASONS to block cardinality explosion.
        """
        clean_reason = (reason or "").strip().lower()
        norm_reason = clean_reason if clean_reason in KNOWN_FALLBACK_REASONS else "other"
        self.quant_solver_fallbacks_total.labels(
            from_solver=from_solver,
            to_solver=to_solver,
            reason=norm_reason,
        ).inc()

    def record_cache_hit(self, cache_tier: str = "redis") -> None:
        """
        Records a market data quote/bar cache hit.
        Sanitizes cache_tier against KNOWN_CACHE_TIERS ('memory', 'redis') or defaults to 'other'.
        """
        tier = (cache_tier or "").strip().lower()
        norm_tier = tier if tier in KNOWN_CACHE_TIERS else "other"
        self.market_data_cache_hits_total.labels(cache_tier=norm_tier).inc()

    def record_cache_miss(self, cache_tier: str = "redis") -> None:
        """
        Records a market data quote/bar cache miss.
        Sanitizes cache_tier against KNOWN_CACHE_TIERS ('memory', 'redis') or defaults to 'other'.
        """
        tier = (cache_tier or "").strip().lower()
        norm_tier = tier if tier in KNOWN_CACHE_TIERS else "other"
        self.market_data_cache_misses_total.labels(cache_tier=norm_tier).inc()

    def generate_metrics_payload(self) -> tuple[bytes, str]:
        """Serializes current registry metrics into Prometheus exposition format."""
        return generate_latest(self.registry), CONTENT_TYPE_LATEST


# Default singleton metrics instance
default_metrics = InvestAIMetrics()


# Module-level convenience wrappers delegating to default_metrics
def record_solver_run(
    solver_name: str,
    objective: str,
    duration_seconds: float,
    iterations: int | None = None,
) -> None:
    """Convenience wrapper delegating to default_metrics.record_solver_run."""
    default_metrics.record_solver_run(solver_name, objective, duration_seconds, iterations)


def record_solver_fallback(from_solver: str, to_solver: str, reason: str) -> None:
    """Convenience wrapper delegating to default_metrics.record_solver_fallback."""
    default_metrics.record_solver_fallback(from_solver, to_solver, reason)


def record_cache_hit(cache_tier: str = "redis") -> None:
    """Convenience wrapper delegating to default_metrics.record_cache_hit."""
    default_metrics.record_cache_hit(cache_tier)


def record_cache_miss(cache_tier: str = "redis") -> None:
    """Convenience wrapper delegating to default_metrics.record_cache_miss."""
    default_metrics.record_cache_miss(cache_tier)


class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Asynchronous FastAPI middleware collecting RED metrics on every HTTP interaction.
    Guarantees cardinality defense by normalizing path templates and isolating exceptions.
    """

    def __init__(self, app, metrics: InvestAIMetrics | None = None) -> None:
        super().__init__(app)
        self.metrics: InvestAIMetrics = metrics or default_metrics

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        method = request.method
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
            duration = time.perf_counter() - t0
            path = normalize_route_path(request)
            self.metrics.record_http_request(
                method=method,
                path=path,
                status_code=response.status_code,
                duration_seconds=duration,
            )
            return response
        except Exception as exc:
            duration = time.perf_counter() - t0
            path = normalize_route_path(request)
            exception_type = type(exc).__name__
            self.metrics.record_http_exception(
                method=method,
                path=path,
                exception_type=exception_type,
            )
            raise
