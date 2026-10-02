from __future__ import annotations

import unittest

from bubblelab.validation.completion.audit import build_audit, integrity_issues


class RefreshEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.audit = build_audit(assert_honest=True)
        self.rows = {row["requirement_id"]: row for row in self.audit["rows"]}

    def test_exact_transient_release_is_not_a_blocker(self) -> None:
        for requirement_id in ("R6", "R7", "R18", "R32"):
            self.assertEqual(self.rows[requirement_id]["status"], "SATISFIED")
        self.assertFalse(any("B03/B07/B08/B12" in blocker for blocker in self.audit["summary"]["known_blockers"]))

    def test_webkit_evidence_stops_at_engine_scope(self) -> None:
        features = self.rows["R28"]["features"]
        self.assertEqual(features["webkit_mobile_engine"], "RESOLVED")
        self.assertEqual(features["physical_iphone_safari"], "NOT_IMPLEMENTED")
        self.assertEqual(features["native_hardware_multitouch"], "NOT_IMPLEMENTED")
        self.assertEqual(self.rows["R28"]["status"], "UNVERIFIED")

    def test_wave15_live_editing_and_wall_scope_are_preserved(self) -> None:
        self.assertEqual(self.rows["R4"]["status"], "SATISFIED")
        self.assertEqual(self.rows["R27"]["status"], "SATISFIED")
        self.assertEqual(self.rows["R17"]["status"], "SATISFIED")
        self.assertEqual(self.rows["R38"]["features"]["arbitrary_coupled_topology_live_surgery"], "NOT_IMPLEMENTED")
        self.assertEqual(self.rows["R38"]["features"]["arbitrary_deforming_moving_wall_cfd"], "NOT_IMPLEMENTED")

    def test_wave17_global_cfd_is_consumed_without_universal_overclaim(self) -> None:
        self.assertEqual(
            self.rows["R11"]["features"]["supported_global_two_bubble_single_gap_multiregion_cfd"],
            "MODELED",
        )
        self.assertEqual(
            self.rows["R38"]["features"]["supported_global_two_bubble_single_gap_multiregion_cfd"],
            "MODELED",
        )
        self.assertEqual(self.rows["R38"]["features"]["global_full_domain_multiregion_cfd"], "NOT_IMPLEMENTED")
        self.assertEqual(self.rows["R38"]["features"]["arbitrary_multigap_manybubble_t1_cfd"], "NOT_IMPLEMENTED")

    def test_wave17_bounded_genuine_3d_t1_is_consumed(self) -> None:
        self.assertEqual(self.rows["R9"]["features"]["bounded_genuine_non_coplanar_3d_t1"], "RESOLVED")
        self.assertEqual(self.rows["R38"]["features"]["bounded_genuine_non_coplanar_3d_t1"], "RESOLVED")
        self.assertEqual(self.rows["R38"]["features"]["general_3d_t1"], "NOT_IMPLEMENTED")

    def test_wave17_pinchoff_closes_r16_without_rim_spray_overclaim(self) -> None:
        self.assertEqual(self.rows["R16"]["status"], "SATISFIED")
        self.assertEqual(self.rows["R16"]["features"]["supported_axisymmetric_slender_neck_pinchoff"], "MODELED")
        self.assertEqual(self.rows["R16"]["features"]["deterministic_pinchoff_fragmentation_restart"], "RESOLVED")
        self.assertEqual(self.rows["R38"]["features"]["retracting_rim_ligament_droplet_spray"], "NOT_IMPLEMENTED")
        self.assertEqual(self.rows["R38"]["features"]["unrestricted_3d_multineck_pinchoff"], "NOT_IMPLEMENTED")

    def test_residual_limits_are_explicit(self) -> None:
        r38 = self.rows["R38"]["features"]
        for name in (
            "physical_iphone_safari",
            "native_hardware_multitouch",
            "global_full_domain_multiregion_cfd",
            "arbitrary_multigap_manybubble_t1_cfd",
            "general_3d_t1",
            "retracting_rim_ligament_droplet_spray",
            "unrestricted_3d_multineck_pinchoff",
            "arbitrary_deforming_moving_wall_cfd",
            "arbitrary_coupled_topology_live_surgery",
        ):
            self.assertEqual(r38[name], "NOT_IMPLEMENTED")
        self.assertFalse(self.audit["summary"]["final_acceptance_ready"])

    def test_honesty_evidence_contract_is_clean(self) -> None:
        self.assertEqual(integrity_issues(assert_honest=True), [])

    def test_completion_audit_is_product_owned(self) -> None:
        self.assertEqual(self.audit["source_requirements"], "bubblelab/docs/PRODUCT_REQUIREMENTS.md")
        removed_prefixes = ("tasks/", "orchestra/", "agent/")
        for row in self.audit["rows"]:
            for evidence in row["evidence"]:
                self.assertFalse(str(evidence).startswith(removed_prefixes), evidence)


if __name__ == "__main__":
    unittest.main()
