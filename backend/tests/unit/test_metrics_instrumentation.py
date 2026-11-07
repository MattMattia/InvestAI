"""
Unit Test Suite for InvestAI Telemetry, RED Metrics and Cardinality Defense.
Certified under Module 8.3 (Phase 1) - Chapter 8.
"""

from __future__ import annotations

import asyncio
import unittest

import pytest
from app.core.metrics import (
    HTTP_DURATION_BUCKETS,
    InvestAIMetrics,
    MetricsMiddleware,
    normalize_route_path,
)
from app.main import app
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from prometheus_client import CollectorRegistry


@pytest.mark.unit
class TestMetricsInstrumentation(unittest.IsolatedAsyncioTestCase):
    """
    Test suite certifying Prometheus RED metrics (Rate, Errors, Duration),
    cardinality defense, async middleware, and scheduler metrics.
    """

    async def test_normalize_route_path_extracts_template_and_blocks_cardinality(self) -> None:
        """
        Verifies that dynamic path variables are normalized to canonical route templates
        and that unmatched/nonexistent routes return 'unmatched_route' to defend against cardinality explosion.
        """
        test_app = FastAPI()

        @test_app.get("/api/v1/portfolios/{portfolio_id}")
        async def get_portfolio(portfolio_id: str) -> dict:
            return {"portfolio_id": portfolio_id}

        @test_app.post("/api/v1/orders")
        async def create_order() -> dict:
            return {"status": "created"}

        # 1. Dynamic portfolio ID in path template
        scope_dynamic = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/portfolios/123e4567-e89b-12d3-a456-426614174000",
            "headers": [],
            "app": test_app,
        }
        req_dynamic = Request(scope_dynamic)
        normalized_dynamic = normalize_route_path(req_dynamic)
        self.assertEqual(normalized_dynamic, "/api/v1/portfolios/{portfolio_id}")

        # 2. Unmatched route (nonexistent URL)
        scope_404 = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/nonexistent/random/123",
            "headers": [],
            "app": test_app,
        }
        req_404 = Request(scope_404)
        normalized_404 = normalize_route_path(req_404)
        self.assertEqual(normalized_404, "unmatched_route")

        # 3. Pre-resolved route in scope (fast-path inspection)
        class DummyRoute:
            path = "/api/v1/custom-resource/{item_id}"

        scope_preresolved = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/custom-resource/999",
            "route": DummyRoute(),
            "app": test_app,
        }
        req_preresolved = Request(scope_preresolved)
        self.assertEqual(
            normalize_route_path(req_preresolved),
            "/api/v1/custom-resource/{item_id}",
        )

    async def test_metrics_middleware_records_http_rate_duration_and_status(self) -> None:
        """
        Simulates successful HTTP requests and verifies exact increment of http_requests_total
        with corresponding method, path, and status code, and latency recorded in histogram.
        """
        custom_registry = CollectorRegistry()
        metrics = InvestAIMetrics(registry=custom_registry)

        test_app = FastAPI()
        test_app.add_middleware(MetricsMiddleware, metrics=metrics)

        @test_app.get("/api/v1/test-rate")
        async def sample_get() -> dict:
            return {"status": "ok"}

        @test_app.post("/api/v1/test-rate")
        async def sample_post() -> JSONResponse:
            return JSONResponse(status_code=201, content={"created": True})

        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://testserver"
        ) as client:
            r1 = await client.get("/api/v1/test-rate")
            self.assertEqual(r1.status_code, 200)

            r2 = await client.post("/api/v1/test-rate")
            self.assertEqual(r2.status_code, 201)

        # Verify rate counter increments
        get_val = custom_registry.get_sample_value(
            "http_requests_total",
            {"method": "GET", "path": "/api/v1/test-rate", "status_code": "200"},
        )
        self.assertEqual(get_val, 1.0)

        post_val = custom_registry.get_sample_value(
            "http_requests_total",
            {"method": "POST", "path": "/api/v1/test-rate", "status_code": "201"},
        )
        self.assertEqual(post_val, 1.0)

        # Verify duration histogram observation
        duration_count = custom_registry.get_sample_value(
            "http_request_duration_seconds_count",
            {"method": "GET", "path": "/api/v1/test-rate"},
        )
        self.assertEqual(duration_count, 1.0)

    async def test_metrics_middleware_records_exceptions_counter(self) -> None:
        """
        Simulates an unhandled exception escaping through middleware and verifies
        increment of http_requests_exceptions_total with the exact exception type name.
        """
        custom_registry = CollectorRegistry()
        metrics = InvestAIMetrics(registry=custom_registry)
        middleware = MetricsMiddleware(app=None, metrics=metrics)

        async def faulty_call_next(req: Request) -> Response:
            raise RuntimeError("Database connection suddenly dropped")

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/simulate-crash",
            "headers": [],
        }
        request = Request(scope)

        with self.assertRaises(RuntimeError) as ctx:
            await middleware.dispatch(request, faulty_call_next)

        self.assertIn("Database connection suddenly dropped", str(ctx.exception))

        exc_count = custom_registry.get_sample_value(
            "http_requests_exceptions_total",
            {
                "method": "POST",
                "path": "unmatched_route",
                "exception_type": "RuntimeError",
            },
        )
        self.assertEqual(exc_count, 1.0)

    async def test_metrics_endpoint_returns_prometheus_format_and_content_type(self) -> None:
        """
        Executes GET /metrics against the application and verifies HTTP 200,
        content-type 'text/plain; version=0.0.4; charset=utf-8', and inclusion of core metrics.
        """
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.get("/metrics")
            self.assertEqual(resp.status_code, 200)

            # Content-type header check (canonical prometheus_client.CONTENT_TYPE_LATEST)
            content_type = resp.headers.get("content-type", "")
            self.assertIn("text/plain", content_type)
            self.assertTrue("version=0.0.4" in content_type or "version=1.0.0" in content_type)
            self.assertIn("charset=utf-8", content_type)

            body = resp.text
            self.assertIn("# HELP http_requests_total", body)
            self.assertIn("# TYPE http_requests_total counter", body)
            self.assertIn("# HELP http_request_duration_seconds", body)
            self.assertIn("# TYPE http_request_duration_seconds histogram", body)
            self.assertIn("# HELP http_requests_exceptions_total", body)
            self.assertIn("# HELP scheduler_jobs_total", body)
            self.assertIn("# HELP scheduler_duration_seconds", body)
            self.assertIn("# HELP scheduler_portfolios_processed_total", body)
            self.assertIn("# HELP scheduler_orders_generated_total", body)

    async def test_scheduler_metrics_record_successful_and_failed_job_runs(self) -> None:
        """
        Invokes scheduler metric recording helper methods and certifies accurate
        increments for job status, execution duration, processed portfolios and order tickets.
        """
        custom_registry = CollectorRegistry()
        metrics = InvestAIMetrics(registry=custom_registry)

        # 1. Record completed job and failed job
        metrics.record_scheduler_job(
            status="COMPLETED",
            trigger_type="AUTOMATIC_SCHEDULE",
            duration_seconds=1.25,
        )
        metrics.record_scheduler_job(
            status="FAILED",
            trigger_type="MANUAL_OVERRIDE",
            duration_seconds=0.45,
        )

        # 2. Record portfolios processed
        metrics.record_scheduler_portfolios(status="SUCCESS", count=5)
        metrics.record_scheduler_portfolios(status="FAILED", count=1)
        metrics.record_scheduler_portfolios(status="SKIPPED", count=2)

        # 3. Record generated FSM orders
        metrics.record_scheduler_orders_generated(count=9)

        # Certify job counters
        completed_val = custom_registry.get_sample_value(
            "scheduler_jobs_total",
            {"status": "COMPLETED", "trigger_type": "AUTOMATIC_SCHEDULE"},
        )
        self.assertEqual(completed_val, 1.0)

        failed_val = custom_registry.get_sample_value(
            "scheduler_jobs_total",
            {"status": "FAILED", "trigger_type": "MANUAL_OVERRIDE"},
        )
        self.assertEqual(failed_val, 1.0)

        # Certify job duration histogram observations
        completed_dur_count = custom_registry.get_sample_value(
            "scheduler_duration_seconds_count",
            {"status": "COMPLETED"},
        )
        self.assertEqual(completed_dur_count, 1.0)

        # Certify portfolios processed
        success_ports = custom_registry.get_sample_value(
            "scheduler_portfolios_processed_total",
            {"status": "SUCCESS"},
        )
        self.assertEqual(success_ports, 5.0)

        failed_ports = custom_registry.get_sample_value(
            "scheduler_portfolios_processed_total",
            {"status": "FAILED"},
        )
        self.assertEqual(failed_ports, 1.0)

        skipped_ports = custom_registry.get_sample_value(
            "scheduler_portfolios_processed_total",
            {"status": "SKIPPED"},
        )
        self.assertEqual(skipped_ports, 2.0)

        # Certify orders generated
        orders_val = custom_registry.get_sample_value("scheduler_orders_generated_total")
        self.assertEqual(orders_val, 9.0)

    async def test_histogram_buckets_distribution_and_monotonicity(self) -> None:
        """
        Verifies that duration histogram buckets strictly adhere to the stipulated
        geometric progression and maintain cumulative count monotonicity after observations.
        """
        custom_registry = CollectorRegistry()
        metrics = InvestAIMetrics(registry=custom_registry)

        # 1. Bucket sequence strictly matches stipulated geometric scale
        expected_buckets = HTTP_DURATION_BUCKETS
        histogram_buckets = [
            b for b in metrics.http_request_duration_seconds._upper_bounds if b != float("inf")
        ]
        self.assertEqual(tuple(histogram_buckets), expected_buckets)

        for i in range(len(expected_buckets) - 1):
            self.assertLess(expected_buckets[i], expected_buckets[i + 1])
            self.assertGreater(expected_buckets[i], 0.0)

        # 2. Record diverse durations spanning multiple buckets
        durations = [0.003, 0.007, 0.02, 0.04, 0.09, 0.22, 0.45, 0.85, 2.1, 4.5, 9.0, 15.0]
        for dur in durations:
            metrics.record_http_request(
                method="GET",
                path="/api/v1/latency-test",
                status_code=200,
                duration_seconds=dur,
            )

        # 3. Check cumulative monotonicity across all bucket samples
        bucket_samples = []
        for metric_family in metrics.http_request_duration_seconds.collect():
            for sample in metric_family.samples:
                if (
                    sample.name == "http_request_duration_seconds_bucket"
                    and sample.labels.get("path") == "/api/v1/latency-test"
                ):
                    bucket_samples.append(sample.value)

        self.assertGreater(len(bucket_samples), 0)
        # Check monotonic non-decreasing order: sample[i] <= sample[i+1]
        for i in range(len(bucket_samples) - 1):
            self.assertLessEqual(bucket_samples[i], bucket_samples[i + 1])

        # Final +Inf bucket must equal total observed samples
        self.assertEqual(bucket_samples[-1], float(len(durations)))

    async def test_metrics_registry_thread_safety_under_concurrent_updates(self) -> None:
        """
        Subjects the metrics collector to highly concurrent async tasks (via asyncio.gather)
        and verifies consistency and exactness of final aggregated counters.
        """
        custom_registry = CollectorRegistry()
        metrics = InvestAIMetrics(registry=custom_registry)

        num_workers = 12
        increments_per_worker = 25

        async def concurrent_worker() -> None:
            for _ in range(increments_per_worker):
                metrics.record_http_request(
                    method="POST",
                    path="/api/v1/concurrent-load",
                    status_code=200,
                    duration_seconds=0.012,
                )
                metrics.record_scheduler_orders_generated(count=2)
                await asyncio.sleep(0.0005)

        workers = [concurrent_worker() for _ in range(num_workers)]
        await asyncio.gather(*workers)

        expected_http_count = float(num_workers * increments_per_worker)
        expected_orders_count = float(num_workers * increments_per_worker * 2)

        actual_http = custom_registry.get_sample_value(
            "http_requests_total",
            {"method": "POST", "path": "/api/v1/concurrent-load", "status_code": "200"},
        )
        self.assertEqual(actual_http, expected_http_count)

        actual_orders = custom_registry.get_sample_value("scheduler_orders_generated_total")
        self.assertEqual(actual_orders, expected_orders_count)
