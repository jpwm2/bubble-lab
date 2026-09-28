from __future__ import annotations

import json
from pathlib import Path
import unittest

from bubblelab.runtime.repeated_topology_gas_transport_runtime import (
    RepeatedTopologyGasTransportRuntimeConfigurationError,
    run_frames,
)


ROOT = Path(__file__).resolve().parents[3]
SCENARIO = ROOT / "bubblelab/scenarios/runtime/repeated-topology-gas-t1.scenario.json"


class RepeatedTopologyGasTransportRuntimeTests(unittest.TestCase):
    def scenario(self) -> dict:
        return json.loads(SCENARIO.read_text())

    def test_two_distinct_events_share_one_dependent_canonical_history(self) -> None:
        frames = run_frames(self.scenario(), frame_count=7)
        events = frames[-1]["topology_events"]
        self.assertEqual(len(events), 2)
        self.assertEqual([event["event_id"] for event in events], ["t1:000001", "t1:000002"])
        self.assertNotEqual(events[0]["retired_film_ids"], events[1]["retired_film_ids"])
        self.assertNotEqual(events[0]["created_film_ids"], events[1]["created_film_ids"])
        self.assertEqual(events[0]["adjacency_after"], events[1]["adjacency_before"])
        self.assertTrue(frames[0]["diagnostics"]["second_event_blocked_before_first"])
        self.assertIn(
            "adjacency already exists",
            frames[0]["diagnostics"]["second_event_initial_block_reason"],
        )
        self.assertEqual(len(frames[0]["diagnostics"]["region_ids"]), 6)
        self.assertEqual(frames[-1]["diagnostics"]["topology_revision"], 2)
        self.assertEqual(frames[0]["diagnostics"]["region_ids"], frames[-1]["diagnostics"]["region_ids"])

    def test_each_created_film_carries_nonzero_transport(self) -> None:
        frames = run_frames(self.scenario(), frame_count=7)
        events = frames[-1]["topology_events"]
        history = frames[-1]["diagnostics"]["edge_transfer_history_mol"]
        for event in events:
            created = event["created_film_ids"][0]
            self.assertNotEqual(history[created], 0.0)
            self.assertIn(created, frames[-1]["diagnostics"]["edge_ids"])
        self.assertLessEqual(
            frames[-1]["diagnostics"]["total_amount_relative_drift_from_initial"],
            1.0e-12,
        )

    def test_rejects_non_increasing_event_frames(self) -> None:
        scenario = self.scenario()
        scenario["user_editable"]["repeated_topology_gas_transport"]["t1_frame_indices"] = [4, 2]
        with self.assertRaises(RepeatedTopologyGasTransportRuntimeConfigurationError):
            run_frames(scenario, frame_count=7)


if __name__ == "__main__":
    unittest.main()
