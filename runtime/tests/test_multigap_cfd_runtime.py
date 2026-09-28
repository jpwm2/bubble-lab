from __future__ import annotations

from copy import deepcopy
import unittest

from bubblelab.runtime.multigap_cfd_runtime import (
    load_scenario,
    replay_signature,
    run_multigap_cfd,
)


SCENARIO = "bubblelab/scenarios/runtime/multigap-three-bubble.scenario.json"


class MultigapCFDRuntimeTests(unittest.TestCase):
    def fast_scenario(self):
        scenario = deepcopy(load_scenario(SCENARIO))
        scenario["domain"]["cells"] = 13
        scenario["domain"]["pressure_iterations"] = 60
        scenario["coupling"]["nominal_dt_s"] = 0.02
        scenario["coupling"]["handoff_gap_cells"] = 1.8
        scenario["coupling"]["max_steps"] = 12
        scenario["coupling"]["global_field"]["pseudo_steps"] = 2
        scenario["coupling"]["global_field"]["feedback_iterations"] = 1
        return scenario

    def test_runtime_uses_one_global_field_for_two_simultaneous_gaps(self) -> None:
        result = run_multigap_cfd(self.fast_scenario(), global_enabled=True)
        self.assertGreater(result["summary"]["global_activation_count"], 0)
        self.assertGreaterEqual(result["summary"]["changed_front_count"], 2)
        self.assertTrue(result["frames"])
        self.assertTrue(
            all(frame["simultaneously_active_gap_count"] == 2 for frame in result["frames"])
        )
        self.assertTrue(
            all(frame["global_grid_shared_state"] for frame in result["frames"])
        )
        self.assertEqual(
            result["manifest"]["feature_disclosures"]["pairwise_force_superposition"],
            "NOT_USED",
        )

    def test_runtime_replay_is_exact(self) -> None:
        scenario = self.fast_scenario()
        first = run_multigap_cfd(scenario, global_enabled=True)
        second = run_multigap_cfd(scenario, global_enabled=True)
        self.assertEqual(replay_signature(first), replay_signature(second))

    def test_global_field_changes_resolved_handoff_timing(self) -> None:
        scenario = self.fast_scenario()
        enabled = run_multigap_cfd(scenario, global_enabled=True)
        control = run_multigap_cfd(scenario, global_enabled=False)
        enabled_time = enabled["summary"]["resolved_handoff_time_s"]
        control_time = control["summary"]["resolved_handoff_time_s"]
        self.assertGreater(
            abs(enabled_time - control_time) / max(abs(control_time), 1.0e-12),
            0.005,
        )


if __name__ == "__main__":
    unittest.main()
