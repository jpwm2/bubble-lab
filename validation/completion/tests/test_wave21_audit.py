from __future__ import annotations

import unittest

from bubblelab.validation.completion.wave21_audit import build_audit, integrity_issues, render_markdown


class Wave21CompletionAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.audit = build_audit(assert_honest=True)
        self.rows = {row["requirement_id"]: row for row in self.audit["rows"]}

    def test_wave21_counts_are_unchanged_from_wave19(self) -> None:
        summary = self.audit["summary"]
        for counts in (summary["previous_status_counts"], summary["status_counts"]):
            self.assertEqual(counts["SATISFIED"], 30)
            self.assertEqual(counts["PARTIAL"], 8)
            self.assertEqual(counts["UNVERIFIED"], 1)
            self.assertEqual(counts["DEFERRED"], 0)
            self.assertEqual(counts["NOT_IMPLEMENTED"], 0)
        self.assertEqual(summary["status_changes"], [])

    def test_topology_changing_gas_transport_is_bounded(self) -> None:
        r13 = self.rows["R13"]["features"]
        self.assertEqual(r13["bounded_topology_changing_gas_transport"], "MODELED")
        self.assertEqual(r13["t1_gas_state_preservation"], "RESOLVED")
        r38 = self.rows["R38"]["features"]
        self.assertEqual(r38["bounded_topology_changing_gas_transport"], "MODELED")
        self.assertEqual(r38["unrestricted_topology_changing_gas_diffusion"], "NOT_IMPLEMENTED")

    def test_t1_global_cfd_is_consumed_without_general_overclaim(self) -> None:
        r11 = self.rows["R11"]["features"]
        self.assertEqual(r11["bounded_t1_through_global_cfd"], "MODELED")
        self.assertEqual(r11["bounded_overlapping_immersed_supports"], "MODELED")
        r38 = self.rows["R38"]["features"]
        self.assertEqual(r38["bounded_t1_through_global_cfd"], "MODELED")
        self.assertEqual(r38["bounded_overlapping_immersed_supports"], "MODELED")
        self.assertEqual(r38["t1_through_global_cfd"], "NOT_IMPLEMENTED")
        self.assertEqual(r38["overlapping_immersed_supports"], "NOT_IMPLEMENTED")

    def test_rim_breakup_is_consumed_without_spray_overclaim(self) -> None:
        r16 = self.rows["R16"]["features"]
        self.assertEqual(r16["bounded_retracting_rim_ligament_droplet_detachment"], "MODELED")
        self.assertEqual(r16["deterministic_rim_breakup_runtime_handoff"], "RESOLVED")
        r38 = self.rows["R38"]["features"]
        self.assertEqual(r38["bounded_retracting_rim_ligament_droplet_detachment"], "MODELED")
        self.assertEqual(r38["retracting_rim_ligament_droplet_spray"], "NOT_IMPLEMENTED")
        self.assertEqual(r38["unrestricted_3d_multineck_pinchoff"], "NOT_IMPLEMENTED")

    def test_remaining_requirements_and_final_acceptance_are_honest(self) -> None:
        self.assertEqual(
            self.audit["summary"]["incomplete_requirement_ids"],
            ["R1", "R10", "R11", "R20", "R28", "R30", "R35", "R38", "R39"],
        )
        self.assertEqual(self.rows["R28"]["status"], "UNVERIFIED")
        self.assertEqual(self.rows["R38"]["status"], "PARTIAL")
        self.assertFalse(self.audit["summary"]["final_acceptance_ready"])

    def test_wave21_report_and_honesty_contract(self) -> None:
        self.assertEqual(self.audit["baseline"], "post-wave-21 accepted main")
        self.assertEqual(integrity_issues(assert_honest=True), [])
        report = render_markdown(self.audit)
        self.assertIn("Post-Wave-19", report)
        self.assertIn("Post-Wave-21", report)
        self.assertIn("- None.", report)
        self.assertIn("physical iPhone Safari", report)


if __name__ == "__main__":
    unittest.main()
