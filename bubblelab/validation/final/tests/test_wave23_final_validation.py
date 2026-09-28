from __future__ import annotations

import unittest

from bubblelab.validation.final.wave23_suite import (
    CLAIM_BOUNDARIES,
    CURRENT_PROBES,
    HISTORICAL_EVIDENCE,
    SMALLEST_BLOCKING_GAPS,
    build_final_validation,
    honesty_issues,
    render_markdown,
)


class Wave23FinalValidationTests(unittest.TestCase):
    def test_wave23_domains_are_currently_exercised(self) -> None:
        coverage = " ".join(str(item["coverage"]) for item in CURRENT_PROBES)
        self.assertIn("asymmetric single-hole reduced rim", coverage)
        self.assertIn("dynamic reduced-order Plateau-border", coverage)
        self.assertIn("strongly coupled four-region T1", coverage)

    def test_wave23_accepted_evidence_is_explicit(self) -> None:
        names = {item["name"] for item in HISTORICAL_EVIDENCE}
        self.assertIn("wave23-asymmetric-multimode-rim-breakup", names)
        self.assertIn("wave23-dynamic-plateau-border-t1", names)
        self.assertIn("wave23-strong-t1-global-cfd", names)

    def test_static_assembly_reports_unchanged_counts_without_final_acceptance(self) -> None:
        result = build_final_validation(execute=False, assert_honest=True)
        self.assertEqual(result["baseline"], "post-wave-23 accepted main")
        self.assertEqual(result["qualification_status"], "NOT_RUN")
        self.assertFalse(result["summary"]["validation_passed"])
        self.assertFalse(result["summary"]["final_acceptance_ready"])
        self.assertEqual(honesty_issues(), [])
        completion = result["completion_audit_summary"]
        for counts in (completion["previous_status_counts"], completion["status_counts"]):
            self.assertEqual(counts["SATISFIED"], 30)
            self.assertEqual(counts["PARTIAL"], 8)
            self.assertEqual(counts["UNVERIFIED"], 1)
            self.assertEqual(counts["DEFERRED"], 0)
            self.assertEqual(counts["NOT_IMPLEMENTED"], 0)
        self.assertEqual(completion["status_changes"], [])
        report = render_markdown(result)
        self.assertIn("Post-Wave-21 SATISFIED/PARTIAL/UNVERIFIED: 30/8/1", report)
        self.assertIn("Post-Wave-23 SATISFIED/PARTIAL/UNVERIFIED: 30/8/1", report)
        self.assertIn("Status changes: none", report)

    def test_claim_boundaries_preserve_wave23_supported_classes(self) -> None:
        text = " ".join(CLAIM_BOUNDARIES)
        self.assertIn("simultaneous modes 7 and 10", text)
        self.assertIn("reduced-order local two-control-volume", text)
        self.assertIn("measured >=5% timing feedback", text)
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
        self.assertIn("arbitrary-contact universal multiphase", text)
        self.assertIn("Physical iPhone Safari", text)
        self.assertIn("GPU/thermal", text)


if __name__ == "__main__":
    unittest.main()
