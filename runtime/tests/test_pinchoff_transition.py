from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from bubblelab.runtime.tools.run_pinchoff_transition import assert_transition, run_transition

SCENARIO = ROOT / "bubblelab" / "scenarios" / "runtime" / "pinchoff-necked.scenario.json"


class PinchOffTransitionTests(unittest.TestCase):
    def test_dynamic_pinchoff_hands_exact_children_to_transient_restart(self) -> None:
        scenario = json.loads(SCENARIO.read_text(encoding="utf-8"))
        payload = run_transition(scenario)
        assert_transition(payload)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["supported_class"], "SINGLE_SMOOTH_AXISYMMETRIC_NECK")
        self.assertEqual(payload["postfragmentation_handoff"]["front_count"], 2)
        self.assertTrue(payload["postfragmentation_handoff"]["exact_child_mesh_seed"])
        self.assertEqual(
            payload["fragmentation"]["fidelity_boundary"]["singular_pinch_off_cfd"],
            "MODELED_SUPPORTED_AXISYMMETRIC_SLENDER_NECK",
        )
        self.assertEqual(payload["fragmentation"]["fidelity_boundary"]["retracting_liquid_rim"], "NOT_RESOLVED")
        self.assertEqual(payload["fragmentation"]["fidelity_boundary"]["droplet_spray"], "NOT_RESOLVED")


if __name__ == "__main__":
    unittest.main()
