from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from bubblelab.runtime import UnsupportedScenarioFeature, run_scenario


ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "scenarios" / "runtime"


def _load(name: str) -> dict:
    return json.loads((SCENARIOS / name).read_text(encoding="utf-8"))


def _frames(root: Path, replay: dict) -> list[dict]:
    return [json.loads((root / item["path"]).read_text(encoding="utf-8")) for item in replay["frames"]]


def _unique_events(frames: list[dict]) -> list[dict]:
    seen = set()
    output = []
    for frame in frames:
        for event in frame["topology"]["events"]:
            if event["id"] not in seen:
                seen.add(event["id"])
                output.append(event)
    return output


class EventRuntimeTests(unittest.TestCase):
    def test_threshold_rupture_coalescence_replay(self) -> None:
        scenario = _load("two-bubble-rupture.scenario.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            replay = run_scenario(scenario, "thinfilm-events", root, 10)
            frames = _frames(root, replay)
        phases = [(frame.get("event_runtime") or {}).get("phase") for frame in frames]
        self.assertEqual(phases[-3:], ["PRE_EVENT", "EVENT", "POST_EVENT"])
        events = _unique_events(frames)
        self.assertEqual([event["type"] for event in events], ["RUPTURE", "COALESCENCE"])
        rupture, coalescence = events
        self.assertEqual(rupture["criterion"], "THICKNESS_DWELL")
        self.assertEqual(rupture["provenance"]["source"], "SOLVER")
        self.assertEqual(rupture["time_s"], coalescence["time_s"])
        self.assertEqual(len(coalescence["lineage"]), 1)
        conservation = coalescence["conservation"]
        self.assertLessEqual(conservation["gas_amount_relative_error"], 1.0e-12)
        self.assertLessEqual(conservation["target_volume_relative_error"], 1.0e-12)
        self.assertLessEqual(conservation["restart_geometry_volume_relative_error"], 1.0e-12)
        self.assertTrue(conservation["requires_post_event_relaxation"])
        post = frames[-1]
        self.assertEqual(post["manifest"]["feature_disclosures"]["post_event_cfd_relaxation"], "NOT_IMPLEMENTED")
        self.assertTrue(post["event_runtime"]["requires_post_event_relaxation"])

    def test_user_trigger_has_distinct_provenance(self) -> None:
        scenario = _load("user-burst.scenario.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            replay = run_scenario(scenario, "thinfilm-events", root, 6)
            events = _unique_events(_frames(root, replay))
        rupture = next(event for event in events if event["type"] == "RUPTURE")
        self.assertEqual(rupture["criterion"], "USER_TRIGGER")
        self.assertEqual(rupture["provenance"]["source"], "USER")
        self.assertIsNone(rupture.get("threshold_m"))

    def test_repeat_is_byte_identical(self) -> None:
        scenario = _load("two-bubble-rupture.scenario.json")
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_root, second_root = Path(first), Path(second)
            first_replay = run_scenario(scenario, "thinfilm-events", first_root, 10)
            second_replay = run_scenario(scenario, "thinfilm-events", second_root, 10)
            self.assertEqual((first_root / "replay.json").read_bytes(), (second_root / "replay.json").read_bytes())
            self.assertEqual(
                [(first_root / item["path"]).read_bytes() for item in first_replay["frames"]],
                [(second_root / item["path"]).read_bytes() for item in second_replay["frames"]],
            )

    def test_rejects_event_modes_not_owned_by_accepted_engine(self) -> None:
        scenario = _load("two-bubble-rupture.scenario.json")
        disabled_coalescence = copy.deepcopy(scenario)
        disabled_coalescence["user_editable"]["events"]["coalesce_on_shared_film_rupture"] = False
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(UnsupportedScenarioFeature, "coalesce_on_shared_film_rupture"):
                run_scenario(disabled_coalescence, "thinfilm-events", directory, 4)
        stochastic = copy.deepcopy(scenario)
        stochastic["user_editable"]["events"]["stochastic_nucleation_enabled"] = True
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(UnsupportedScenarioFeature, "unsupported event runtime setting"):
                run_scenario(stochastic, "thinfilm-events", directory, 4)


if __name__ == "__main__":
    unittest.main()
