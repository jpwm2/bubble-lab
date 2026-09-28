from __future__ import annotations
import json
from pathlib import Path
import unittest
from bubblelab.runtime.rim_breakup_runtime import run_rim_breakup_runtime

ROOT = Path(__file__).resolve().parents[3]
SCENARIO = ROOT / "bubblelab" / "scenarios" / "runtime" / "rim-breakup.scenario.json"


class RimBreakupRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenario = json.loads(SCENARIO.read_text(encoding="utf-8"))
        cls.payload = run_rim_breakup_runtime(cls.scenario)

    def test_evolved_state_handoff(self):
        self.assertEqual(self.payload["status"], "PASS")
        self.assertTrue(self.payload["continuation"]["exact_evolved_velocity_seed"])
        self.assertGreater(len(self.payload["droplets"]), 1)
        self.assertLessEqual(self.payload["budgets"]["liquid_volume_relative_error"], 1e-12)

    def test_deterministic_runtime(self):
        repeat = run_rim_breakup_runtime(self.scenario)
        self.assertEqual(self.payload["solver_digest"], repeat["solver_digest"])
        self.assertEqual(self.payload["droplets"], repeat["droplets"])

    def test_claim_boundary(self):
        self.assertEqual(self.payload["claim_boundary"]["turbulent_atomization"], "UNSUPPORTED")
        self.assertEqual(self.payload["provenance"]["supported_class"], "ONE_CIRCULAR_THIN_FILM_HOLE_ONE_AZIMUTHAL_MODE")


if __name__ == "__main__":
    unittest.main()
