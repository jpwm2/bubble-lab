from __future__ import annotations

import unittest

from bubblelab.validation.completion.wave23_audit import build_audit, integrity_issues, render_markdown


class Wave23CompletionAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.audit = build_audit(assert_honest=True)
        self.rows = {row["requirement_id"]: row for row in self.audit["rows"]}

    def test_wave23_counts_are_unchanged_from_wave21(self) -> None:
        summary = self.audit["summary"]
        for counts in (summary["previous_status_counts"], summary["status_counts"]):
            self.assertEqual(counts["SATISFIED"], 30)
            self.assertEqual(counts["PARTIAL"], 8)
            self.assertEqual(counts["UNVERIFIED"], 1)
            self.assertEqual(counts["DEFERRED"], 0)
            self.assertEqual(counts["NOT_IMPLEMENTED"], 0)
        self.assertEqual(summary["status_changes"], [])

    def test_asymmetric_multimode_breakup_is_bounded(self) -> None:
        r16 = self.rows["R16"]["features"]
        self.assertEqual(r16["bounded_asymmetric_multimode_rim_breakup"], "MODELED")
        self.assertEqual(r16["state_derived_multimode_droplet_handoff"], "RESOLVED")
        r38 = self.rows["R38"]["features"]
        self.assertEqual(r38["bounded_asymmetric_multimode_rim_breakup"], "MODELED")
        self.assertEqual(r38["retracting_rim_ligament_droplet_spray"], "NOT_IMPLEMENTED")
        self.assertEqual(r38["unrestricted_3d_multineck_pinchoff"], "NOT_IMPLEMENTED")

    def test_plateau_border_hydrodynamics_is_reduced_order(self) -> None:
        for requirement_id in ("R9", "R10", "R11", "R38"):
            self.assertEqual(
                self.rows[requirement_id]["features"]["bounded_dynamic_plateau_border_hydrodynamics"],
                "MODELED",
            )
        self.assertEqual(self.rows["R38"]["features"]["general_3d_t1"], "NOT_IMPLEMENTED")

    def test_strong_t1_global_cfd_is_bounded(self) -> None:
        for requirement_id in ("R10", "R11", "R20", "R38"):
            self.assertEqual(
                self.rows[requirement_id]["features"]["bounded_strongly_coupled_t1_global_cfd"],
                "MODELED",
            )
        self.assertEqual(self.rows["R11"]["features"]["bounded_causal_cfd_t1_timing_feedback"], "MODELED")
        self.assertEqual(self.rows["R38"]["features"]["t1_through_global_cfd"], "NOT_IMPLEMENTED")
        self.assertEqual(self.rows["R38"]["features"]["global_full_domain_multiregion_cfd"], "NOT_IMPLEMENTED")

    def test_remaining_requirements_and_final_acceptance_are_honest(self) -> None:
        self.assertEqual(
            self.audit["summary"]["incomplete_requirement_ids"],
            ["R1", "R10", "R11", "R20", "R28", "R30", "R35", "R38", "R39"],
        )
        self.assertEqual(self.rows["R28"]["status"], "UNVERIFIED")
        self.assertEqual(self.rows["R38"]["status"], "PARTIAL")
        self.assertFalse(self.audit["summary"]["final_acceptance_ready"])

    def test_wave23_report_and_honesty_contract(self) -> None:
        self.assertEqual(self.audit["baseline"], "post-wave-23 accepted main")
        self.assertEqual(integrity_issues(assert_honest=True), [])
        report = render_markdown(self.audit)
        self.assertIn("Post-Wave-21", report)
        self.assertIn("Post-Wave-23", report)
        self.assertIn("- None.", report)
        self.assertIn("physical iPhone Safari", report)


if __name__ == "__main__":
    unittest.main()
