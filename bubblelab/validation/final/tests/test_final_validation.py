from __future__ import annotations

import unittest

from bubblelab.validation.final.suite import (
    CLAIM_BOUNDARIES,
    CURRENT_PROBES,
    HISTORICAL_EVIDENCE,
    SMALLEST_BLOCKING_GAPS,
    build_final_validation,
    honesty_issues,
    render_markdown,
)


class FinalValidationTests(unittest.TestCase):
    def test_required_domains_are_represented(self) -> None:
        coverage = " ".join(str(item["coverage"]) for item in CURRENT_PROBES)
        for phrase in (
            "equilibrium",
            "sharp-interface",
            "shared-film",
            "Plateau",
            "contact",
            "finite-thickness",
            "rupture/coalescence",
            "production split",
            "production T1",
            "session transport",
            "live bubble add/delete/move/resize/velocity",
            "resolved bulk no-slip wall CFD",
            "pre-contact thin-gap CFD",
            "global-domain 3D two-bubble/single-gap multi-region CFD",
            "bounded genuinely non-coplanar 3D T1",
            "single smooth axisymmetric slender-neck pinch-off",
        ):
            self.assertIn(phrase, coverage)

    def test_heavy_accepted_evidence_is_explicitly_historical(self) -> None:
        names = {item["name"] for item in HISTORICAL_EVIDENCE}
        for name in (
            "exact-transient-release",
            "mobile-webkit-engine",
            "checkpoint-restart",
            "wave15-live-runtime-editing",
            "wave15-noslip-wall-runtime",
            "wave15-precontact-thin-gap-cfd",
            "wave17-global-multiregion-cfd",
            "wave17-bounded-genuine-3d-t1",
            "wave17-axisymmetric-pinchoff",
        ):
            self.assertIn(name, names)

    def test_claim_boundaries_include_required_limits(self) -> None:
        text = " ".join(CLAIM_BOUNDARIES)
        for phrase in (
            "high-accuracy rupture-time",
            "mathematically bounded bilinear-shear subclass",
            "arbitrary admissible 3D T1",
            "global-domain two-bubble/single-gap class",
            "arbitrary simultaneous multi-gap/many-bubble/T1 CFD",
            "one smooth axisymmetric slender neck",
            "retracting rims, ligaments, droplets/spray",
            "arbitrary multi-neck",
            "fixed SDF geometry",
            "arbitrary/deforming moving-wall CFD",
            "physical iPhone Safari",
            "arbitrary surgery through existing shared-film/network/T1/thin-film/event states",
        ):
            self.assertIn(phrase, text)

    def test_static_assembly_is_honest_and_not_finally_accepted(self) -> None:
        result = build_final_validation(execute=False, assert_honest=True)
        self.assertEqual(result["baseline"], "post-wave-17 accepted main")
        self.assertEqual(result["qualification_status"], "NOT_RUN")
        self.assertFalse(result["summary"]["validation_passed"])
        self.assertFalse(result["summary"]["final_acceptance_ready"])
        self.assertEqual(honesty_issues(), [])
        self.assertEqual(result["completion_audit_summary"]["previous_status_counts"]["SATISFIED"], 28)
        self.assertEqual(result["completion_audit_summary"]["previous_status_counts"]["PARTIAL"], 10)
        self.assertEqual(result["completion_audit_summary"]["previous_status_counts"]["UNVERIFIED"], 1)
        self.assertEqual(result["completion_audit_summary"]["status_counts"]["SATISFIED"], 29)
        self.assertEqual(result["completion_audit_summary"]["status_counts"]["PARTIAL"], 9)
        self.assertEqual(result["completion_audit_summary"]["status_counts"]["UNVERIFIED"], 1)
        report = render_markdown(result)
        self.assertIn("Smallest blocking gaps", report)
        self.assertIn("Claim boundaries retained", report)
        self.assertIn("Status changes: R16", report)

    def test_smallest_blockers_are_priority_ordered_and_keep_device_gap(self) -> None:
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
        self.assertIn("arbitrary simultaneous multi-gap/many-bubble/T1 CFD", text)
        self.assertIn("unrestricted admissible 3D T1", text)
        self.assertIn("retracting-rim/ligament/droplet-spray", text)
        self.assertIn("cross-version checkpoint portability", text)
        self.assertIn("Physical iPhone Safari", text)
        self.assertIn("GPU/thermal", text)
        self.assertNotIn("global full-domain multi-region CFD/simultaneous multi-gap coupling", text)
        self.assertNotIn("general 3D T1, and singular pinch-off", text)


if __name__ == "__main__":
    unittest.main()
