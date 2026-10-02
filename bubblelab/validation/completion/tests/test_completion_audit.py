from __future__ import annotations

import json
import unittest

from bubblelab.validation.completion.audit import (
    FEATURE_VOCABULARY,
    ROOT,
    STATUS_VOCABULARY,
    build_audit,
    integrity_issues,
    render_markdown,
)


class CompletionAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.audit = build_audit(assert_honest=True)
        self.rows = {row["requirement_id"]: row for row in self.audit["rows"]}

    def test_audits_every_requirement_in_order(self) -> None:
        expected = [f"R{i}" for i in range(1, 40)]
        self.assertEqual([row["requirement_id"] for row in self.audit["rows"]], expected)
        self.assertEqual(self.audit["summary"]["requirement_count"], 39)
        self.assertEqual(self.audit["summary"]["previous_status_counts"]["SATISFIED"], 28)
        self.assertEqual(self.audit["summary"]["previous_status_counts"]["PARTIAL"], 10)
        self.assertEqual(self.audit["summary"]["previous_status_counts"]["UNVERIFIED"], 1)
        self.assertEqual(self.audit["summary"]["status_counts"]["SATISFIED"], 29)
        self.assertEqual(self.audit["summary"]["status_counts"]["PARTIAL"], 9)
        self.assertEqual(self.audit["summary"]["status_counts"]["UNVERIFIED"], 1)

    def test_status_changes_are_exactly_wave17_closure(self) -> None:
        changes = self.audit["summary"]["status_changes"]
        self.assertEqual([item["requirement_id"] for item in changes], ["R16"])
        self.assertEqual(changes[0]["from"], "PARTIAL")
        self.assertEqual(changes[0]["to"], "SATISFIED")
        self.assertIn("bubblelab/validation/completion/evidence/historical-deliveries/bubble-singular-breakup-cfd-foundation.json", changes[0]["evidence_added"])

    def test_all_evidence_paths_exist(self) -> None:
        for row in self.audit["rows"]:
            self.assertTrue(row["evidence"], row["requirement_id"])
            for evidence in row["evidence"]:
                self.assertTrue((ROOT / evidence).is_file(), f"{row['requirement_id']}: {evidence}")

    def test_vocabularies_are_closed(self) -> None:
        self.assertEqual(tuple(self.audit["status_vocabulary"]), STATUS_VOCABULARY)
        self.assertEqual(tuple(self.audit["feature_vocabulary"]), FEATURE_VOCABULARY)
        for row in self.audit["rows"]:
            self.assertIn(row["status"], STATUS_VOCABULARY)
            for classification in row["features"].values():
                self.assertIn(classification, FEATURE_VOCABULARY)

    def test_existing_integrated_evidence_is_preserved(self) -> None:
        self.assertEqual(self.rows["R8"]["status"], "SATISFIED")
        self.assertEqual(self.rows["R9"]["status"], "SATISFIED")
        self.assertEqual(self.rows["R14"]["status"], "SATISFIED")
        self.assertEqual(self.rows["R15"]["status"], "SATISFIED")
        self.assertEqual(self.rows["R19"]["status"], "SATISFIED")
        self.assertEqual(self.rows["R4"]["status"], "SATISFIED")
        self.assertEqual(self.rows["R17"]["status"], "SATISFIED")
        self.assertEqual(self.rows["R27"]["status"], "SATISFIED")

    def test_wave17_global_cfd_is_supported_not_universal(self) -> None:
        self.assertEqual(
            self.rows["R11"]["features"]["supported_global_two_bubble_single_gap_multiregion_cfd"],
            "MODELED",
        )
        self.assertEqual(self.rows["R11"]["features"]["arbitrary_multigap_manybubble_t1_cfd"], "NOT_IMPLEMENTED")
        self.assertEqual(
            self.rows["R38"]["features"]["supported_global_two_bubble_single_gap_multiregion_cfd"],
            "MODELED",
        )
        self.assertEqual(self.rows["R38"]["features"]["global_full_domain_multiregion_cfd"], "NOT_IMPLEMENTED")

    def test_wave17_genuine_3d_t1_is_bounded(self) -> None:
        self.assertEqual(self.rows["R9"]["features"]["bounded_genuine_non_coplanar_3d_t1"], "RESOLVED")
        self.assertEqual(self.rows["R38"]["features"]["bounded_genuine_non_coplanar_3d_t1"], "RESOLVED")
        self.assertEqual(self.rows["R38"]["features"]["general_3d_t1"], "NOT_IMPLEMENTED")

    def test_wave17_pinchoff_closes_r16_baseline(self) -> None:
        self.assertEqual(self.rows["R16"]["status"], "SATISFIED")
        self.assertEqual(self.rows["R16"]["features"]["production_fragmentation"], "RESOLVED")
        self.assertEqual(self.rows["R16"]["features"]["supported_axisymmetric_slender_neck_pinchoff"], "MODELED")
        self.assertEqual(self.rows["R16"]["features"]["deterministic_pinchoff_fragmentation_restart"], "RESOLVED")
        self.assertEqual(self.rows["R38"]["features"]["retracting_rim_ligament_droplet_spray"], "NOT_IMPLEMENTED")
        self.assertEqual(self.rows["R38"]["features"]["unrestricted_3d_multineck_pinchoff"], "NOT_IMPLEMENTED")

    def test_webkit_engine_is_resolved_without_hardware_overclaim(self) -> None:
        self.assertEqual(self.rows["R28"]["status"], "UNVERIFIED")
        self.assertEqual(self.rows["R28"]["features"]["webkit_mobile_engine"], "RESOLVED")
        self.assertEqual(self.rows["R28"]["features"]["physical_iphone_safari"], "NOT_IMPLEMENTED")
        self.assertEqual(self.rows["R28"]["features"]["native_hardware_multitouch"], "NOT_IMPLEMENTED")

    def test_checkpoint_evidence_preserves_scope(self) -> None:
        self.assertEqual(self.rows["R30"]["features"]["same_build_checkpoint_restart"], "RESOLVED")
        self.assertEqual(self.rows["R30"]["features"]["cross_version_checkpoint_portability"], "NOT_IMPLEMENTED")
        self.assertEqual(self.rows["R31"]["features"]["fresh_process_checkpoint_exact_continuation"], "RESOLVED")

    def test_final_integration_consumes_wave17_evidence_and_preserves_limits(self) -> None:
        r38 = self.rows["R38"]
        for name in (
            "multi_bubble_canonical_runtime",
            "contact_thinfilm_event_chain",
            "browser_live_solver_transport",
            "production_fragmentation",
            "supported_t1_transaction",
            "arbitrary_live_runtime_creation",
            "live_runtime_bubble_editing",
            "resolved_no_slip_wall_cfd",
            "bounded_genuine_non_coplanar_3d_t1",
            "deterministic_pinchoff_fragmentation_restart",
        ):
            self.assertEqual(r38["features"][name], "RESOLVED")
        self.assertEqual(r38["features"]["supported_global_two_bubble_single_gap_multiregion_cfd"], "MODELED")
        self.assertEqual(r38["features"]["supported_axisymmetric_slender_neck_pinchoff"], "MODELED")
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
            self.assertEqual(r38["features"][name], "NOT_IMPLEMENTED")
        self.assertEqual(r38["status"], "PARTIAL")

    def test_every_incomplete_row_has_gap_and_closure(self) -> None:
        incomplete = []
        for row in self.audit["rows"]:
            if row["status"] != "SATISFIED":
                incomplete.append(row["requirement_id"])
                self.assertTrue(row["gap"].strip())
                self.assertTrue(row["closure"].strip())
        self.assertEqual(
            incomplete,
            ["R1", "R10", "R11", "R13", "R20", "R28", "R30", "R35", "R38", "R39"],
        )
        self.assertEqual(incomplete, self.audit["summary"]["incomplete_requirement_ids"])
        self.assertFalse(self.audit["summary"]["final_acceptance_ready"])
        self.assertIn("R28", self.audit["summary"]["final_acceptance_reason"])

    def test_build_and_report_are_deterministic(self) -> None:
        first = build_audit(assert_honest=True)
        second = build_audit(assert_honest=True)
        self.assertEqual(
            json.dumps(first, sort_keys=True, ensure_ascii=False, allow_nan=False),
            json.dumps(second, sort_keys=True, ensure_ascii=False, allow_nan=False),
        )
        self.assertEqual(render_markdown(first), render_markdown(second))

    def test_report_replaces_stale_wave15_blockers(self) -> None:
        report = render_markdown(self.audit)
        blockers = report.split("## Known blockers", 1)[1].split("## Requirement matrix", 1)[0]
        self.assertIn("physical iPhone Safari/device-GPU/native hardware multi-touch qualification", blockers)
        self.assertIn("arbitrary simultaneous multi-gap/many-bubble/T1 CFD", blockers)
        self.assertIn("unrestricted arbitrary-admissible 3D T1", blockers)
        self.assertIn("retracting-rim/ligament/droplet-spray", blockers)
        self.assertNotIn("global full-domain multi-region CFD and simultaneous multi-gap coupling beyond the supported local isolated thin-gap foundation", blockers)
        status_changes = report.split("## Status changes", 1)[1].split("## Known blockers", 1)[0]
        self.assertIn("R16", status_changes)
        self.assertNotIn("R4", status_changes)
        self.assertNotIn("R17", status_changes)
        self.assertNotIn("R27", status_changes)

    def test_honesty_validator_is_clean(self) -> None:
        self.assertEqual(integrity_issues(assert_honest=True), [])


if __name__ == "__main__":
    unittest.main()
