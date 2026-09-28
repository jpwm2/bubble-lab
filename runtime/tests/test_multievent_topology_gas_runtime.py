from __future__ import annotations

import json
from pathlib import Path
import unittest

from bubblelab.runtime.multievent_topology_gas_runtime import run_frames

ROOT = Path(__file__).resolve().parents[3]
SCENARIO = ROOT / "bubblelab/scenarios/runtime/multievent-topology-gas.scenario.json"


class MultiEventTopologyGasRuntimeTests(unittest.TestCase):
    def test_runtime_crosses_all_causal_transactions(self) -> None:
        scenario = json.loads(SCENARIO.read_text())
        frames = run_frames(scenario, frame_count=8)
        final = frames[-1]
        self.assertEqual(
            [event["type"] for event in final["topology_events"]],
            ["T1", "T1", "T1", "T1", "RUPTURE", "COALESCENCE"],
        )
        self.assertEqual(final["diagnostics"]["transaction_count"], 5)
        self.assertEqual(final["diagnostics"]["topology_revision"], 6)
        self.assertEqual(len(frames[0]["bubbles"]), 10)
        self.assertEqual(len(final["bubbles"]), 9)
        self.assertLessEqual(
            final["diagnostics"]["total_amount_relative_drift_from_initial"], 1.0e-12
        )

    def test_runtime_replay_is_exact(self) -> None:
        scenario = json.loads(SCENARIO.read_text())
        first = run_frames(scenario, frame_count=8)
        second = run_frames(scenario, frame_count=8)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
