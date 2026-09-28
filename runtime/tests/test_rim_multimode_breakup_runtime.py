from __future__ import annotations
import json
from pathlib import Path
import unittest
from bubblelab.runtime.rim_multimode_breakup_runtime import run_rim_multimode_breakup_runtime

ROOT = Path(__file__).resolve().parents[3]
SCENARIO = ROOT / "bubblelab" / "scenarios" / "runtime" / "rim-multimode-breakup.scenario.json"


class RimMultimodeBreakupRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenario=json.loads(SCENARIO.read_text(encoding="utf-8"))
        cls.payload=run_rim_multimode_breakup_runtime(cls.scenario)

    def test_evolved_multimode_handoff(self):
        self.assertEqual(self.payload["status"], "PASS")
        self.assertGreaterEqual(len(self.payload["rim"]["seed_modes"]), 2)
        self.assertEqual(len(self.payload["droplets"]), len(self.payload["rim"]["evolved_neck_cells"]))
        self.assertNotIn(len(self.payload["droplets"]), self.payload["rim"]["seed_modes"])
        self.assertLessEqual(self.payload["budgets"]["liquid_volume_relative_error"], 1e-12)
        self.assertTrue(self.payload["continuation"]["exact_evolved_velocity_seed"])

    def test_deterministic_runtime(self):
        repeat=run_rim_multimode_breakup_runtime(self.scenario)
        self.assertEqual(self.payload["solver_digest"], repeat["solver_digest"])
        self.assertEqual(self.payload["droplets"], repeat["droplets"])

    def test_claim_boundary(self):
        self.assertEqual(self.payload["supported_class"], "ONE_ASYMMETRIC_THIN_FILM_HOLE_SIMULTANEOUS_MULTIMODE_REDUCED_RIM")
        self.assertEqual(self.payload["claim_boundary"]["turbulent_atomization"], "UNSUPPORTED")
        self.assertEqual(self.payload["claim_boundary"]["unrestricted_3d_multi_hole_interaction"], "UNSUPPORTED")


if __name__ == "__main__": unittest.main()
