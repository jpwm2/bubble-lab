from __future__ import annotations

import json
from pathlib import Path
import unittest

from bubblelab.runtime.t1_global_cfd_runtime import T1GlobalCFDRuntime


ROOT = Path(__file__).resolve().parents[2]
SCENARIO = ROOT / "scenarios/runtime/t1-global-cfd.scenario.json"


class T1GlobalCFDRuntimeTests(unittest.TestCase):
    def _run(self):
        scenario = json.loads(SCENARIO.read_text(encoding="utf-8"))
        return T1GlobalCFDRuntime.from_scenario(scenario).run()

    def test_runtime_crosses_real_t1_and_continues_authoritative_field(self) -> None:
        payload = self._run()
        self.assertEqual(payload["status"], "SUPPORTED_CLASS_RESOLVED")
        self.assertEqual([frame["phase"] for frame in payload["frames"]], [
            "PRE_T1", "T1_EVENT", "POST_T1"
        ])
        transition = payload["transition"]
        self.assertTrue(transition["authoritative_grid_preserved"])
        self.assertGreater(
            transition["pre_field"]["shared_support"]["overlap_cell_count"], 0
        )
        self.assertNotEqual(
            transition["topology"]["adjacency_before"],
            transition["topology"]["adjacency_after"],
        )
        self.assertEqual(len(transition["topology"]["retired_film_ids"]), 1)
        self.assertEqual(len(transition["topology"]["created_film_ids"]), 1)
        self.assertGreater(transition["post_field"]["field"]["pressure_linf_pa"], 0.0)

    def test_runtime_replay_is_exact(self) -> None:
        self.assertEqual(self._run(), self._run())


if __name__ == "__main__":
    unittest.main()
