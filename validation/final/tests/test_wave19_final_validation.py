from __future__ import annotations

import unittest

from bubblelab.validation.final.wave19_suite import (
    CLAIM_BOUNDARIES,
    CURRENT_PROBES,
    HISTORICAL_EVIDENCE,
    SMALLEST_BLOCKING_GAPS,
    build_final_validation,
    honesty_issues,
    render_markdown,
)


class Wave19FinalValidationTests(unittest.TestCase):
    def test_wave19_domains_are_currently_exercised(self) -> None:
        coverage = " ".join(str(item["coverage"]) for item in CURRENT_PROBES)
        self.assertIn("fixed-topology many-bubble pressure-driven gas diffusion", coverage)
        self.assertIn("three-bubble/two-simultaneous-gap global CFD", coverage)
        self.assertIn("direct-geometry genuinely non-coplanar 3D T1 hydrodynamics", coverage)

    def test_wave19_accepted_evidence_is_explicit(self) -> None:
        names = {item["name"] for item in HISTORICAL_EVIDENCE}
        self.assertIn("wave19-manybubble-gas-diffusion-network", names)
        self.assertIn("wave19-multigap-manybubble-cfd", names)
        self.assertIn("wave19-direct-3d-t1-hydrodynamics", names)

    def test_static_assembly_reports_wave19_counts_without_final_acceptance(self) -> None:
        result = build_final_validation(execute=False, assert_honest=True)
        self.assertEqual(result["baseline"], "post-wave-19 accepted main")
        self.assertEqual(result["qualification_status"], "NOT_RUN")
        self.assertFalse(result["summary"]["validation_passed"])
        self.assertFalse(result["summary"]["final_acceptance_ready"])
        self.assertEqual(honesty_issues(), [])
        completion = result["completion_audit_summary"]
        self.assertEqual(completion["previous_status_counts"]["SATISFIED"], 29)
        self.assertEqual(completion["previous_status_counts"]["PARTIAL"], 9)
        self.assertEqual(completion["previous_status_counts"]["UNVERIFIED"], 1)
        self.assertEqual(completion["status_counts"]["SATISFIED"], 30)
        self.assertEqual(completion["status_counts"]["PARTIAL"], 8)
        self.assertEqual(completion["status_counts"]["UNVERIFIED"], 1)
        self.assertEqual([item["requirement_id"] for item in completion["status_changes"]], ["R13"])
        report = render_markdown(result)
        self.assertIn("Post-Wave-17 SATISFIED/PARTIAL/UNVERIFIED: 29/9/1", report)
        self.assertIn("Post-Wave-19 SATISFIED/PARTIAL/UNVERIFIED: 30/8/1", report)
        self.assertIn("Status changes: R13", report)

    def test_claim_boundaries_preserve_wave19_supported_classes(self) -> None:
        text = " ".join(CLAIM_BOUNDARIES)
        self.assertIn("fixed-topology shared-film network", text)
        self.assertIn("three separated quasi-spherical tracked bubbles", text)
        self.assertIn("overlapping immersed supports", text)
        self.assertIn("direct-geometry 3D T1", text)
        self.assertIn("conforming subdivision", text)
        self.assertIn("physical iPhone Safari", text)

    def test_remaining_blockers_are_priority_ordered(self) -> None:
        self.assertEqual(
            [item["priority"] for item in SMALLEST_BLOCKING_GAPS],
            [
                "physical validity",
                "numerical stability",
                "state/conservation/reproducibility",
                "runtime control",
                "visualization",
                "performance",
            ],
        )
        text = " ".join(item["gap"] for item in SMALLEST_BLOCKING_GAPS)
        self.assertIn("T1-through-global-CFD", text)
        self.assertIn("unrestricted topology-changing gas transport", text)
        self.assertIn("Physical iPhone Safari", text)
        self.assertIn("GPU/thermal", text)


if __name__ == "__main__":
    unittest.main()
