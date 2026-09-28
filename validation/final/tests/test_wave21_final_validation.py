from __future__ import annotations

import unittest

from bubblelab.validation.final.wave21_suite import (
    CLAIM_BOUNDARIES,
    CURRENT_PROBES,
    HISTORICAL_EVIDENCE,
    SMALLEST_BLOCKING_GAPS,
    build_final_validation,
    honesty_issues,
    render_markdown,
)


class Wave21FinalValidationTests(unittest.TestCase):
    def test_wave21_domains_are_currently_exercised(self) -> None:
        coverage = " ".join(str(item["coverage"]) for item in CURRENT_PROBES)
        self.assertIn("gas transport through one real four-region T1", coverage)
        self.assertIn("four-region T1 through one authoritative Eulerian field", coverage)
        self.assertIn("circular-hole rim retraction", coverage)

    def test_wave21_accepted_evidence_is_explicit(self) -> None:
        names = {item["name"] for item in HISTORICAL_EVIDENCE}
        self.assertIn("wave21-topology-changing-gas-transport", names)
        self.assertIn("wave21-t1-through-global-cfd", names)
        self.assertIn("wave21-rim-ligament-droplet", names)

    def test_static_assembly_reports_unchanged_counts_without_final_acceptance(self) -> None:
        result = build_final_validation(execute=False, assert_honest=True)
        self.assertEqual(result["baseline"], "post-wave-21 accepted main")
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
        self.assertIn("Post-Wave-19 SATISFIED/PARTIAL/UNVERIFIED: 30/8/1", report)
        self.assertIn("Post-Wave-21 SATISFIED/PARTIAL/UNVERIFIED: 30/8/1", report)
        self.assertIn("Status changes: none", report)

    def test_claim_boundaries_preserve_wave21_supported_classes(self) -> None:
        text = " ".join(CLAIM_BOUNDARIES)
        self.assertIn("isolated four-region", text)
        self.assertIn("partition-of-unity overlap treatment", text)
        self.assertIn("circular thin-film hole", text)
        self.assertIn("broad spray distributions", text)
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
        self.assertIn("unrestricted repeated topology-changing gas-film coupling", text)
        self.assertIn("arbitrary-contact/singular-border global CFD", text)
        self.assertIn("Physical iPhone Safari", text)
        self.assertIn("GPU/thermal", text)


if __name__ == "__main__":
    unittest.main()
