from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from bubblelab.runtime.topology_gas_transport_runtime import (
    TopologyGasTransportRuntimeConfigurationError,
    run_frames,
)


SCENARIO = (
    Path(__file__).resolve().parents[2]
    / "scenarios/runtime/topology-gas-t1.scenario.json"
)


class TopologyGasTransportRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = json.loads(SCENARIO.read_text())

    def test_runtime_transfers_before_switch_and_continues_afterward(self) -> None:
        frames = run_frames(self.scenario, frame_count=7)
        first = frames[0]
        event_frame = frames[3]
        last = frames[-1]
        initial = {item["id"]: item for item in first["bubbles"]}
        final = {item["id"]: item for item in last["bubbles"]}
        self.assertEqual(tuple(initial), tuple(final))
        self.assertGreaterEqual(len(initial), 4)
        self.assertEqual(first["diagnostics"]["topology_revision"], 0)
        self.assertEqual(event_frame["diagnostics"]["topology_revision"], 1)
        self.assertEqual(last["diagnostics"]["topology_revision"], 1)
        event = event_frame["topology_event"]
        self.assertIsNotNone(event)
        assert event is not None
        self.assertTrue(event["gas_state_unchanged_during_surgery"])
        self.assertLessEqual(event["gas_amount_relative_drift"], 1.0e-12)
        retired = set(event["retired_film_ids"])
        created = set(event["created_film_ids"])
        self.assertFalse(retired.intersection(last["diagnostics"]["edge_ids"]))
        self.assertTrue(created.issubset(set(last["diagnostics"]["edge_ids"])))
        self.assertGreaterEqual(last["diagnostics"]["max_simultaneous_active_edges"], 2)
        self.assertLessEqual(
            last["diagnostics"]["total_amount_relative_drift_from_initial"],
            1.0e-12,
        )
        created_film = next(
            item for item in last["film_regions"] if item["id"] in created
        )
        self.assertNotEqual(created_film["cumulative_transfer_a_to_b_mol"], 0.0)

    def test_deterministic_replay_is_exact(self) -> None:
        first = run_frames(copy.deepcopy(self.scenario), frame_count=7)
        second = run_frames(copy.deepcopy(self.scenario), frame_count=7)
        self.assertEqual(
            json.dumps(first, sort_keys=True),
            json.dumps(second, sort_keys=True),
        )

    def test_disable_stops_transport_but_not_supported_topology_event(self) -> None:
        scenario = copy.deepcopy(self.scenario)
        scenario["user_editable"]["topology_gas_transport"]["enabled"] = False
        frames = run_frames(scenario, frame_count=7)
        initial = {item["id"]: item for item in frames[0]["bubbles"]}
        final = {item["id"]: item for item in frames[-1]["bubbles"]}
        for region_id in initial:
            self.assertEqual(initial[region_id]["amount_mol"], final[region_id]["amount_mol"])
            self.assertEqual(initial[region_id]["volume_m3"], final[region_id]["volume_m3"])
            self.assertEqual(initial[region_id]["pressure_pa"], final[region_id]["pressure_pa"])
        self.assertEqual(frames[-1]["diagnostics"]["max_simultaneous_active_edges"], 0)
        self.assertEqual(frames[-1]["diagnostics"]["topology_revision"], 1)
        self.assertTrue(frames[-1]["diagnostics"]["event_performed"])

    def test_unbounded_topology_features_are_rejected(self) -> None:
        for feature in ("rupture", "coalescence", "vanishing_region_remap"):
            scenario = copy.deepcopy(self.scenario)
            scenario["requested_solver"]["features"][feature] = True
            with self.subTest(feature=feature):
                with self.assertRaises(TopologyGasTransportRuntimeConfigurationError):
                    run_frames(scenario, frame_count=2)


if __name__ == "__main__":
    unittest.main()
