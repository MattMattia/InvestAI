"""
Unit Test Suite for InvestAI Specialized Quantitative Telemetry & Cache Metrics.
Certified under Module 8.3 (Phase 2) - Chapter 8.
"""

from __future__ import annotations

import concurrent.futures
import unittest

import pytest
from app.core.metrics import (
    InvestAIMetrics,
    record_cache_hit,
    record_cache_miss,
    record_solver_fallback,
    record_solver_run,
)
from prometheus_client import CollectorRegistry


@pytest.mark.unit
class TestQuantMetrics(unittest.TestCase):
    """
    Test suite certifying quantitative solver telemetry (SLSQP vs Spinu),
    fallback reason cardinality sanitization, cache hits/misses, and thread safety.
    """

    def test_record_solver_run_increments_duration_and_handles_optional_iterations(self) -> None:
        """
        Verifies that solver latency is recorded in the histogram and that iterations=None
        does not record false observations, whereas iterations=45 records into bucket 50.
        """
        custom_registry = CollectorRegistry()
        metrics = InvestAIMetrics(registry=custom_registry)

        # 1. Run with iterations=None
        metrics.record_solver_run(
            solver_name="SLSQP",
            objective="MIN_VARIANCE",
            duration_seconds=0.015,
            iterations=None,
        )

        dur_count = custom_registry.get_sample_value(
            "quant_solver_duration_seconds_count",
            {"solver_name": "SLSQP", "objective": "MIN_VARIANCE"},
        )
        self.assertEqual(dur_count, 1.0)

        iter_count = custom_registry.get_sample_value(
            "quant_solver_iterations_count",
            {"solver_name": "SLSQP"},
        )
        self.assertIsNone(iter_count)

        # 2. Run with iterations=45
        metrics.record_solver_run(
            solver_name="SLSQP",
            objective="SHARPE_RATIO",
            duration_seconds=0.035,
            iterations=45,
        )

        dur_count2 = custom_registry.get_sample_value(
            "quant_solver_duration_seconds_count",
            {"solver_name": "SLSQP", "objective": "SHARPE_RATIO"},
        )
        self.assertEqual(dur_count2, 1.0)

        iter_count2 = custom_registry.get_sample_value(
            "quant_solver_iterations_count",
            {"solver_name": "SLSQP"},
        )
        self.assertEqual(iter_count2, 1.0)

        # Bucket 50 should include 45
        bucket_50 = custom_registry.get_sample_value(
            "quant_solver_iterations_bucket",
            {"solver_name": "SLSQP", "le": "50.0"},
        )
        self.assertEqual(bucket_50, 1.0)

        # Bucket 25 should NOT include 45
        bucket_25 = custom_registry.get_sample_value(
            "quant_solver_iterations_bucket",
            {"solver_name": "SLSQP", "le": "25.0"},
        )
        self.assertEqual(bucket_25, 0.0)

        # Test module-level wrapper delegation
        record_solver_run("DefaultSLSQP", "MIN_VAR", 0.01, iterations=20)

    def test_record_solver_fallback_sanitizes_reason_cardinality(self) -> None:
        """
        Verifies that known fallback reasons are recorded verbatim while arbitrary error
        messages are mapped to 'other' to prevent Prometheus cardinality explosion.
        """
        custom_registry = CollectorRegistry()
        metrics = InvestAIMetrics(registry=custom_registry)

        # 1. Known reasons
        metrics.record_solver_fallback("Spinu", "SLSQP", "singular_matrix")
        metrics.record_solver_fallback("Spinu", "SLSQP", "max_iter_exceeded")

        # 2. Arbitrary strings and unexpected reasons
        metrics.record_solver_fallback("Spinu", "SLSQP", "Error 503: condition number high")
        metrics.record_solver_fallback("SLSQP", "EqualWeight", "Unrecognized solver crash!")

        # Certify singular_matrix label
        val_sm = custom_registry.get_sample_value(
            "quant_solver_fallbacks_total",
            {"from_solver": "Spinu", "to_solver": "SLSQP", "reason": "singular_matrix"},
        )
        self.assertEqual(val_sm, 1.0)

        # Certify max_iter_exceeded label
        val_iter = custom_registry.get_sample_value(
            "quant_solver_fallbacks_total",
            {"from_solver": "Spinu", "to_solver": "SLSQP", "reason": "max_iter_exceeded"},
        )
        self.assertEqual(val_iter, 1.0)

        # Certify normalized 'other' labels
        val_other1 = custom_registry.get_sample_value(
            "quant_solver_fallbacks_total",
            {"from_solver": "Spinu", "to_solver": "SLSQP", "reason": "other"},
        )
        self.assertEqual(val_other1, 1.0)

        val_other2 = custom_registry.get_sample_value(
            "quant_solver_fallbacks_total",
            {"from_solver": "SLSQP", "to_solver": "EqualWeight", "reason": "other"},
        )
        self.assertEqual(val_other2, 1.0)

        # Test module-level wrapper delegation
        record_solver_fallback("Spinu", "SLSQP", "numerical_instability")

    def test_cache_hits_and_misses_normalization_and_recording(self) -> None:
        """
        Verifies recorded hits and misses across memory and redis tiers, and ensures
        unknown tiers are cleanly normalized to 'other'.
        """
        custom_registry = CollectorRegistry()
        metrics = InvestAIMetrics(registry=custom_registry)

        # Record hits
        metrics.record_cache_hit("memory")
        metrics.record_cache_hit("redis")
        metrics.record_cache_hit("unknown_distributed_cache")

        # Record misses
        metrics.record_cache_miss("memory")
        metrics.record_cache_miss("redis")
        metrics.record_cache_miss("ephemeral_l1")

        # Certify hit tiers
        self.assertEqual(
            custom_registry.get_sample_value(
                "market_data_cache_hits_total", {"cache_tier": "memory"}
            ),
            1.0,
        )
        self.assertEqual(
            custom_registry.get_sample_value(
                "market_data_cache_hits_total", {"cache_tier": "redis"}
            ),
            1.0,
        )
        self.assertEqual(
            custom_registry.get_sample_value(
                "market_data_cache_hits_total", {"cache_tier": "other"}
            ),
            1.0,
        )

        # Certify miss tiers
        self.assertEqual(
            custom_registry.get_sample_value(
                "market_data_cache_misses_total", {"cache_tier": "memory"}
            ),
            1.0,
        )
        self.assertEqual(
            custom_registry.get_sample_value(
                "market_data_cache_misses_total", {"cache_tier": "redis"}
            ),
            1.0,
        )
        self.assertEqual(
            custom_registry.get_sample_value(
                "market_data_cache_misses_total", {"cache_tier": "other"}
            ),
            1.0,
        )

        # Test module-level wrappers delegation
        record_cache_hit("memory")
        record_cache_miss("redis")

    def test_quant_metrics_rendered_in_prometheus_scrape_output(self) -> None:
        """
        Generates Prometheus scrape payload and certifies proper # HELP and # TYPE headers
        for all specialized quantitative metrics and cache counters.
        """
        custom_registry = CollectorRegistry()
        metrics = InvestAIMetrics(registry=custom_registry)

        metrics.record_solver_run("SLSQP", "RISK_PARITY", 0.02, iterations=12)
        metrics.record_solver_fallback("Spinu", "SLSQP", "numerical_instability")
        metrics.record_cache_hit("redis")
        metrics.record_cache_miss("redis")

        payload, _ = metrics.generate_metrics_payload()
        text = payload.decode("utf-8")

        self.assertIn("# HELP quant_solver_duration_seconds", text)
        self.assertIn("# TYPE quant_solver_duration_seconds histogram", text)

        self.assertIn("# HELP quant_solver_fallbacks_total", text)
        self.assertIn("# TYPE quant_solver_fallbacks_total counter", text)

        self.assertIn("# HELP quant_solver_iterations", text)
        self.assertIn("# TYPE quant_solver_iterations histogram", text)

        self.assertIn("# HELP market_data_cache_hits_total", text)
        self.assertIn("# TYPE market_data_cache_hits_total counter", text)

        self.assertIn("# HELP market_data_cache_misses_total", text)
        self.assertIn("# TYPE market_data_cache_misses_total counter", text)

    def test_solver_duration_buckets_capture_submillisecond_and_multisecond_runs(self) -> None:
        """
        Verifies that submillisecond solver runs (0.0008s) fall into bucket 0.001
        and multisecond runs (1.5s) fall into bucket 2.5 without histogram distortion.
        """
        custom_registry = CollectorRegistry()
        metrics = InvestAIMetrics(registry=custom_registry)

        # Fast submillisecond solver execution: 0.0008s (800 microseconds)
        metrics.record_solver_run("SpinuFast", "MIN_VARIANCE", 0.0008)

        # Slow multisecond quadratic optimization: 1.5s
        metrics.record_solver_run("SLSQPSlow", "MAX_DIVERSIFICATION", 1.5)

        # For 0.0008s:
        # Bucket 0.0005 should be 0.0
        # Bucket 0.001 should be 1.0
        b_0005 = custom_registry.get_sample_value(
            "quant_solver_duration_seconds_bucket",
            {"solver_name": "SpinuFast", "objective": "MIN_VARIANCE", "le": "0.0005"},
        )
        self.assertEqual(b_0005, 0.0)

        b_001 = custom_registry.get_sample_value(
            "quant_solver_duration_seconds_bucket",
            {"solver_name": "SpinuFast", "objective": "MIN_VARIANCE", "le": "0.001"},
        )
        self.assertEqual(b_001, 1.0)

        # For 1.5s:
        # Bucket 1.0 should be 0.0
        # Bucket 2.5 should be 1.0
        b_10 = custom_registry.get_sample_value(
            "quant_solver_duration_seconds_bucket",
            {"solver_name": "SLSQPSlow", "objective": "MAX_DIVERSIFICATION", "le": "1.0"},
        )
        self.assertEqual(b_10, 0.0)

        b_25 = custom_registry.get_sample_value(
            "quant_solver_duration_seconds_bucket",
            {"solver_name": "SLSQPSlow", "objective": "MAX_DIVERSIFICATION", "le": "2.5"},
        )
        self.assertEqual(b_25, 1.0)

    def test_quant_metrics_thread_safety_under_concurrent_solvers(self) -> None:
        """
        Simulates massive concurrent writes from multiple solver worker threads using
        ThreadPoolExecutor and certifies consistent and race-free final metrics.
        """
        custom_registry = CollectorRegistry()
        metrics = InvestAIMetrics(registry=custom_registry)

        num_threads = 8
        runs_per_thread = 40

        def solver_worker() -> None:
            for _ in range(runs_per_thread):
                metrics.record_solver_run("SLSQP_Concurrent", "MIN_VAR", 0.002, iterations=10)
                metrics.record_solver_fallback(
                    "Spinu_Concurrent", "SLSQP_Concurrent", "singular_matrix"
                )
                metrics.record_cache_hit("redis")
                metrics.record_cache_miss("memory")

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(solver_worker) for _ in range(num_threads)]
            for f in concurrent.futures.as_completed(futures):
                f.result()

        expected_count = float(num_threads * runs_per_thread)

        # Certify solver duration observations
        runs_val = custom_registry.get_sample_value(
            "quant_solver_duration_seconds_count",
            {"solver_name": "SLSQP_Concurrent", "objective": "MIN_VAR"},
        )
        self.assertEqual(runs_val, expected_count)

        # Certify iterations observations
        iter_val = custom_registry.get_sample_value(
            "quant_solver_iterations_count",
            {"solver_name": "SLSQP_Concurrent"},
        )
        self.assertEqual(iter_val, expected_count)

        # Certify fallbacks
        fallback_val = custom_registry.get_sample_value(
            "quant_solver_fallbacks_total",
            {
                "from_solver": "Spinu_Concurrent",
                "to_solver": "SLSQP_Concurrent",
                "reason": "singular_matrix",
            },
        )
        self.assertEqual(fallback_val, expected_count)

        # Certify cache hits
        hits_val = custom_registry.get_sample_value(
            "market_data_cache_hits_total",
            {"cache_tier": "redis"},
        )
        self.assertEqual(hits_val, expected_count)

        # Certify cache misses
        misses_val = custom_registry.get_sample_value(
            "market_data_cache_misses_total",
            {"cache_tier": "memory"},
        )
        self.assertEqual(misses_val, expected_count)
