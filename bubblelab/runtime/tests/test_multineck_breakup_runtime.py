import json
from pathlib import Path
import unittest

from bubblelab.runtime.multineck_breakup_runtime import run_multineck_breakup_runtime


REPO = Path(__file__).resolve().parents[3]
SCENARIO = REPO / "bubblelab/scenarios/runtime/multineck-breakup-3d.scenario.json"


class MultiNeckBreakupRuntimeTests(unittest.TestCase):
    def test_runtime_exposes_3d_interaction_detachments_and_continuation(self):
        scenario = json.loads(SCENARIO.read_text(encoding="utf-8"))
        report = run_multineck_breakup_runtime(scenario)
        self.assertEqual(report["status"], "PASS")
        self.assertGreater(report["geometry"]["noncoplanarity"], 0.15)
        self.assertGreaterEqual(len(report["event_sequence"]), 2)
        self.assertGreaterEqual(report["interaction"]["max_relative_event_time_shift"], 0.02)
        self.assertLessEqual(report["budgets"]["liquid_volume_relative_error"], 1e-12)
        self.assertTrue(report["continuation"]["surviving_necks_continue_after_each_event"])
        ids = [fragment["id"] for fragment in report["fragments"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_runtime_is_deterministic(self):
        scenario = json.loads(SCENARIO.read_text(encoding="utf-8"))
        first = run_multineck_breakup_runtime(scenario)
        second = run_multineck_breakup_runtime(scenario)
        self.assertEqual(first["solver_digest"], second["solver_digest"])
        self.assertEqual(first["event_sequence"], second["event_sequence"])


if __name__ == "__main__":
    unittest.main()
