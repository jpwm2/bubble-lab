from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from bubblelab.runtime.network_gas_diffusion_runtime import (
    NetworkGasDiffusionRuntimeConfigurationError,
    run_frames,
)


SCENARIO = (
    Path(__file__).resolve().parents[2]
    / "scenarios/runtime/manybubble-gas-diffusion.scenario.json"
)


class NetworkGasDiffusionRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = json.loads(SCENARIO.read_text())

    def test_runtime_advances_authoritative_multi_edge_network(self) -> None:
        frames = run_frames(self.scenario, frame_count=9)
        first, last = frames[0], frames[-1]
        initial = {item["id"]: item for item in first["bubbles"]}
        final = {item["id"]: item for item in last["bubbles"]}
        self.assertEqual(tuple(initial), tuple(final))
        self.assertGreaterEqual(len(initial), 3)
        self.assertGreaterEqual(len(last["film_regions"]), 2)
        self.assertGreaterEqual(
            last["diagnostics"]["max_simultaneous_active_edges"], 2
        )
        self.assertLessEqual(
            last["diagnostics"]["worst_total_moles_relative_drift"], 1.0e-12
        )
        self.assertEqual(
            last["diagnostics"]["worst_edge_antisymmetry_residual_mol"], 0.0
        )
        self.assertLess(
            final["small"]["volume_m3"], initial["small"]["volume_m3"]
        )
        self.assertGreater(
            final["large"]["volume_m3"], initial["large"]["volume_m3"]
        )
        self.assertGreater(
            final["small"]["pressure_pa"], initial["small"]["pressure_pa"]
        )
        self.assertLess(
            final["large"]["pressure_pa"], initial["large"]["pressure_pa"]
        )

    def test_deterministic_replay(self) -> None:
        first = run_frames(copy.deepcopy(self.scenario), frame_count=7)
        second = run_frames(copy.deepcopy(self.scenario), frame_count=7)
        self.assertEqual(
            json.dumps(first, sort_keys=True),
            json.dumps(second, sort_keys=True),
        )

    def test_user_disable_control_prevents_transfer(self) -> None:
        scenario = copy.deepcopy(self.scenario)
        scenario["user_editable"]["gas_diffusion"]["enabled"] = False
        frames = run_frames(scenario, frame_count=7)
        initial = {item["id"]: item for item in frames[0]["bubbles"]}
        final = {item["id"]: item for item in frames[-1]["bubbles"]}
        for region_id in initial:
            self.assertEqual(
                initial[region_id]["amount_mol"], final[region_id]["amount_mol"]
            )
            self.assertEqual(
                initial[region_id]["volume_m3"], final[region_id]["volume_m3"]
            )
        self.assertEqual(
            frames[-1]["diagnostics"]["max_simultaneous_active_edges"], 0
        )

    def test_topology_changing_features_are_explicitly_rejected(self) -> None:
        for feature in ("dynamic_shared_films", "t1", "rupture", "coalescence"):
            scenario = copy.deepcopy(self.scenario)
            scenario["requested_solver"]["features"][feature] = True
            with self.subTest(feature=feature):
                with self.assertRaises(NetworkGasDiffusionRuntimeConfigurationError):
                    run_frames(scenario, frame_count=2)


if __name__ == "__main__":
    unittest.main()
