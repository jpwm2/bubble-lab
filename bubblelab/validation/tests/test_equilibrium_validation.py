from __future__ import annotations

import copy
import unittest

from bubblelab.validation.equilibrium_suite import (
    canonical_hash,
    gate_ge,
    gate_le,
    gate_true,
    gate_zero,
)
from bubblelab.validation.tools.compare_validation_runs import compare_results, first_difference
from bubblelab.validation.tools.render_validation_report import render_report


class GateTests(unittest.TestCase):
    def test_numeric_gates(self) -> None:
        self.assertTrue(gate_le("x", 0.1, 0.2, "spec")["passed"])
        self.assertFalse(gate_le("x", 0.3, 0.2, "spec")["passed"])
        self.assertTrue(gate_ge("p", 1.7, 1.7, "spec")["passed"])
        self.assertFalse(gate_ge("p", 1.2, 1.3, "spec")["passed"])

    def test_boolean_and_zero_gates(self) -> None:
        self.assertTrue(gate_true("ok", True, "spec")["passed"])
        self.assertFalse(gate_true("ok", False, "spec")["passed"])
        self.assertTrue(gate_zero("count", 0, "spec")["passed"])
        self.assertFalse(gate_zero("count", 1, "spec")["passed"])

    def test_canonical_hash_is_key_order_independent(self) -> None:
        left = {"b": [2, 3], "a": 1}
        right = {"a": 1, "b": [2, 3]}
        self.assertEqual(canonical_hash(left), canonical_hash(right))


class ComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sample = {
            "summary": {"passed": True},
            "replay_payload_sha256": "a" * 64,
            "benchmarks": [{"id": "B01", "passed": True}],
        }

    def test_exact_comparison_passes(self) -> None:
        comparison = compare_results(self.sample, copy.deepcopy(self.sample))
        self.assertTrue(comparison["same"])
        self.assertIsNone(comparison["difference"])

    def test_difference_reports_path(self) -> None:
        changed = copy.deepcopy(self.sample)
        changed["benchmarks"][0]["passed"] = False
        difference = first_difference(self.sample, changed)
        self.assertIsNotNone(difference)
        self.assertIn("$.benchmarks[0].passed", difference or "")


class ReportTests(unittest.TestCase):
    def test_report_states_equilibrium_only_scope_and_gates(self) -> None:
        result = {
            "summary": {"passed": True},
            "replay_payload_sha256": "b" * 64,
            "provenance": {
                "backend": "test-backend",
                "fidelity_tier": "HIGH_FIDELITY",
                "active_feature_classification": ["equilibrium"],
                "adapter_source_sha256": {"sphere": "c" * 64},
                "seed": None,
                "thread_process_count": {"threads": 1, "processes": 1},
                "bulk_grid_resolution": None,
                "timestep": None,
            },
            "benchmarks": [
                {
                    "id": "B01",
                    "title": "Sphere geometry",
                    "requirements": ["R7", "R32"],
                    "setup": {"geometry": "sphere"},
                    "resolution": {"eta_s": 0.02},
                    "metrics": {"error": 0.001},
                    "gates": [
                        {
                            "metric": "error",
                            "value": 0.001,
                            "relation": "<=",
                            "threshold": 0.002,
                            "passed": True,
                            "source": "spec",
                        }
                    ],
                    "passed": True,
                    "termination": {"reason": "converged"},
                    "convergence": None,
                    "limitations": [],
                }
            ],
            "limitations": ["equilibrium only"],
        }
        report = render_report(result)
        self.assertIn("validates equilibrium physics only", report)
        self.assertIn("B01", report)
        self.assertIn("0.002", report)


if __name__ == "__main__":
    unittest.main()
