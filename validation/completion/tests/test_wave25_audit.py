from __future__ import annotations

import unittest

from bubblelab.validation.completion.wave25_audit import build_audit, integrity_issues, render_markdown


class Wave25CompletionAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.audit = build_audit(assert_honest=True)
        self.rows = {row["requirement_id"]: row for row in self.audit["rows"]}

    def test_wave25_counts_are_unchanged_from_wave23(self) -> None:
        summary = self.audit["summary"]
        for counts in (summary["previous_status_counts"], summary["status_counts"]):
            self.assertEqual(counts["SATISFIED"], 30)
            self.assertEqual(counts["PARTIAL"], 8)
            self.assertEqual(counts["UNVERIFIED"], 1)
            self.assertEqual(counts["DEFERRED"], 0)
            self.assertEqual(counts["NOT_IMPLEMENTED"], 0)
        self.assertEqual(summary["status_changes"], [])

    def test_repeated_t1_gas_transport_is_bounded(self) -> None:
        self.assertEqual(self.rows["R13"]["features"]["bounded_repeated_t1_gas_transport"], "MODELED")
        self.assertEqual(self.rows["R12"]["features"]["repeated_t1_stable_gas_identity"], "RESOLVED")
        self.assertEqual(self.rows["R13"]["features"]["repeated_post_topology_transport_rebuild"], "RESOLVED")
        self.assertEqual(self.rows["R38"]["features"]["unrestricted_topology_changing_gas_diffusion"], "NOT_IMPLEMENTED")

    def test_interacting_multihole_breakup_is_bounded(self) -> None:
        self.assertEqual(self.rows["R16"]["features"]["bounded_interacting_multihole_breakup"], "MODELED")
        self.assertEqual(self.rows["R16"]["features"]["state_derived_interacting_multihole_fragments"], "RESOLVED")
        self.assertEqual(self.rows["R38"]["features"]["unrestricted_3d_multineck_pinchoff"], "NOT_IMPLEMENTED")
        self.assertEqual(self.rows["R38"]["features"]["retracting_rim_ligament_droplet_spray"], "NOT_IMPLEMENTED")

    def test_manycontact_t1_global_cfd_is_bounded(self) -> None:
        for requirement_id in ("R10", "R11", "R20", "R38"):
            self.assertEqual(self.rows[requirement_id]["features"]["bounded_manycontact_t1_global_cfd"], "MODELED")
        self.assertEqual(self.rows["R11"]["features"]["bounded_non_event_contact_causality"], "MODELED")
        self.assertEqual(self.rows["R20"]["features"]["manycontact_refinement_feedback_gates"], "RESOLVED")
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

    def test_wave25_report_and_honesty_contract(self) -> None:
        self.assertEqual(self.audit["baseline"], "post-wave-25 accepted main")
        self.assertEqual(integrity_issues(assert_honest=True), [])
        report = render_markdown(self.audit)
        self.assertIn("Post-Wave-23", report)
        self.assertIn("Post-Wave-25", report)
        self.assertIn("- None.", report)
        self.assertIn("physical iPhone Safari", report)


if __name__ == "__main__":
    unittest.main()
