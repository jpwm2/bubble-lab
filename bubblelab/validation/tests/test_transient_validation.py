from __future__ import annotations

import unittest

from bubblelab.validation.transient_suite import canonical_hash, run_validation
from bubblelab.validation.tools.render_transient_validation_report import render_report


class TransientValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = run_validation()

    def test_suite_passes_all_integration_gates(self) -> None:
        self.assertTrue(self.result["summary"]["passed"])
        self.assertEqual(self.result["summary"]["failed_count"], 0)
        self.assertEqual(self.result["summary"]["passed_count"], self.result["summary"]["record_count"])

    def test_required_matrix_ids_are_mapped(self) -> None:
        covered = set(self.result["summary"]["matrix_ids_covered"])
        self.assertTrue({"B03", "B07", "B08", "B10", "B11", "B12", "B14", "B16"}.issubset(covered))

    def test_b12_is_not_promoted_past_accepted_resolution(self) -> None:
        amr = next(record for record in self.result["records"] if record["gate_id"] == "amr-integration")
        self.assertEqual(amr["classification"], "MODELED")
        self.assertFalse(amr["setup"]["b12_final_qualified"])
        combined = " ".join(amr["limitations"]).lower()
        self.assertIn("final b12", combined)

    def test_boundary_evidence_is_explicitly_modeled_not_no_slip(self) -> None:
        boundary = next(record for record in self.result["records"] if record["gate_id"] == "boundary-contact")
        self.assertEqual(boundary["classification"], "MODELED")
        self.assertIn("no-slip", " ".join(boundary["limitations"]).lower())
        self.assertTrue(boundary["evidence"]["wall_contact"]["passed"])
        self.assertTrue(boundary["evidence"]["contact_angle"]["passed"])

    def test_postcoalescence_preserves_restart_lineage_and_volume_window(self) -> None:
        record = next(record for record in self.result["records"] if record["gate_id"] == "post-coalescence-continuation")
        checks = record["evidence"]["checks"]
        self.assertEqual(record["classification"], "MODELED")
        self.assertTrue(checks["restart_geometry_preserved"])
        self.assertTrue(checks["geometry_evolved_after_seed"])
        self.assertTrue(checks["lineage_preserved"])
        self.assertTrue(checks["event_history_preserved"])
        self.assertLessEqual(checks["max_volume_relative_error"], 5.0e-10)
        self.assertLessEqual(checks["max_export_volume_relative_error"], 5.0e-10)
        self.assertLess(record["setup"]["qualified_time_window_s"][0], record["setup"]["qualified_time_window_s"][1])

    def test_short_static_window_is_reported_without_long_time_claim(self) -> None:
        record = next(record for record in self.result["records"] if record["gate_id"] == "transient-static-foundation")
        window = record["setup"]["short_window"]
        self.assertEqual(window["step_count"], 2)
        self.assertGreater(window["end_time_s"], 0.0)
        self.assertEqual(len(window["timesteps_s"]), 2)
        self.assertIn("10-characteristic-time", " ".join(record["limitations"]))

    def test_payload_hash_is_self_consistent(self) -> None:
        payload = dict(self.result)
        expected = payload.pop("replay_payload_sha256")
        self.assertEqual(expected, canonical_hash(payload))

    def test_report_keeps_classifications_and_limitations(self) -> None:
        report = render_report(self.result)
        self.assertIn("# Integrated Transient Physics Validation Report", report)
        self.assertIn("MODELED", report)
        self.assertIn("NOT_IMPLEMENTED", report)
        self.assertIn("B12", report)
        self.assertIn("post-coalescence-continuation", report)


if __name__ == "__main__":
    unittest.main()
