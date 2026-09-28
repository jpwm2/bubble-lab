from __future__ import annotations

import unittest

from bubblelab.validation.completion.wave19_audit import build_audit, integrity_issues, render_markdown


class Wave19CompletionAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.audit = build_audit(assert_honest=True)
        self.rows = {row["requirement_id"]: row for row in self.audit["rows"]}

    def test_wave19_counts_and_single_status_promotion(self) -> None:
        summary = self.audit["summary"]
        self.assertEqual(summary["previous_status_counts"]["SATISFIED"], 29)
        self.assertEqual(summary["previous_status_counts"]["PARTIAL"], 9)
        self.assertEqual(summary["previous_status_counts"]["UNVERIFIED"], 1)
        self.assertEqual(summary["status_counts"]["SATISFIED"], 30)
        self.assertEqual(summary["status_counts"]["PARTIAL"], 8)
        self.assertEqual(summary["status_counts"]["UNVERIFIED"], 1)
        changes = summary["status_changes"]
        self.assertEqual([item["requirement_id"] for item in changes], ["R13"])
        self.assertEqual(changes[0]["from"], "PARTIAL")
        self.assertEqual(changes[0]["to"], "SATISFIED")
        self.assertIn("tasks/bubble-manybubble-gas-diffusion-network/deliverable.json", changes[0]["evidence_added"])

    def test_r13_consumes_fixed_topology_manybubble_gas_network(self) -> None:
        row = self.rows["R13"]
        self.assertEqual(row["status"], "SATISFIED")
        self.assertEqual(row["features"]["supported_manybubble_pressure_driven_gas_network"], "MODELED")
        self.assertEqual(row["features"]["network_pressure_amount_volume_feedback"], "MODELED")
        self.assertEqual(row["features"]["deterministic_conservative_network_runtime"], "RESOLVED")
        self.assertEqual(row["features"]["gas_transfer_enable_disable"], "RESOLVED")

    def test_multigap_global_cfd_is_consumed_without_universal_overclaim(self) -> None:
        self.assertEqual(self.rows["R11"]["features"]["bounded_three_bubble_two_gap_global_cfd"], "MODELED")
        r38 = self.rows["R38"]["features"]
        self.assertEqual(r38["bounded_three_bubble_two_gap_global_cfd"], "MODELED")
        self.assertEqual(r38["global_full_domain_multiregion_cfd"], "NOT_IMPLEMENTED")
        self.assertEqual(r38["arbitrary_multigap_manybubble_t1_cfd"], "NOT_IMPLEMENTED")
        self.assertEqual(r38["t1_through_global_cfd"], "NOT_IMPLEMENTED")
        self.assertEqual(r38["overlapping_immersed_supports"], "NOT_IMPLEMENTED")

    def test_direct_3d_t1_is_consumed_without_continuum_or_general_overclaim(self) -> None:
        self.assertEqual(self.rows["R9"]["features"]["bounded_direct_geometry_3d_t1_hydrodynamics"], "MODELED")
        r38 = self.rows["R38"]["features"]
        self.assertEqual(r38["bounded_direct_geometry_3d_t1_hydrodynamics"], "MODELED")
        self.assertEqual(r38["general_3d_t1"], "NOT_IMPLEMENTED")
        self.assertEqual(r38["unrestricted_topology_changing_gas_diffusion"], "NOT_IMPLEMENTED")

    def test_remaining_requirements_and_final_acceptance_are_honest(self) -> None:
        self.assertEqual(
            self.audit["summary"]["incomplete_requirement_ids"],
            ["R1", "R10", "R11", "R20", "R28", "R30", "R35", "R38", "R39"],
        )
        self.assertEqual(self.rows["R28"]["status"], "UNVERIFIED")
        self.assertEqual(self.rows["R38"]["status"], "PARTIAL")
        self.assertFalse(self.audit["summary"]["final_acceptance_ready"])

    def test_wave19_report_and_honesty_contract(self) -> None:
        self.assertEqual(self.audit["baseline"], "post-wave-19 accepted main")
        self.assertEqual(integrity_issues(assert_honest=True), [])
        report = render_markdown(self.audit)
        self.assertIn("Post-Wave-17", report)
        self.assertIn("Post-Wave-19", report)
        self.assertIn("**R13**: PARTIAL -> SATISFIED", report)
        self.assertIn("physical iPhone Safari", report)


if __name__ == "__main__":
    unittest.main()
