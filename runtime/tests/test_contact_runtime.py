from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from bubblelab.runtime.bundle import validate_replay_bundle
from bubblelab.runtime.contact_runtime import (
    BACKEND_ID,
    ContactRuntimeConfigurationError,
    run_contact_transition,
)
from bubblelab.runtime.runner import run_scenario

ROOT = Path(__file__).resolve().parents[3]
SCENARIO = ROOT / "bubblelab" / "scenarios" / "runtime" / "contact-transition-two-bubble.scenario.json"


def load_scenario() -> dict:
    return json.loads(SCENARIO.read_text(encoding="utf-8"))


class ContactRuntimeTests(unittest.TestCase):
    def test_transition_forms_once_and_handoffs_shared_dofs(self) -> None:
        frames, metadata = run_contact_transition(load_scenario(), 12)
        self.assertEqual(metadata["identity"], BACKEND_ID)
        self.assertEqual(metadata["contact_events"], 1)
        self.assertFalse(
            frames[0]["diagnostics"]["contact_transition"]["observation"]["contact"]
        )

        events = [
            (index, event)
            for index, frame in enumerate(frames)
            for event in frame["topology"]["events"]
            if event.get("transition_kind") == "CONTACT_FORMATION"
        ]
        self.assertEqual(len(events), 1)
        transition_index, event = events[0]
        self.assertGreater(transition_index, 0)
        self.assertEqual(event["type"], "FILM_FORMED")
        self.assertEqual(event["bubble_ids_before"], ["bubble-a", "bubble-b"])
        self.assertEqual(event["bubble_ids_after"], ["bubble-a", "bubble-b"])
        self.assertEqual(
            event["trigger"]["geometry_source"],
            "authoritative triangulated tracked fronts",
        )

        transition = frames[transition_index]
        self.assertEqual(
            transition["diagnostics"]["contact_transition"]["post_contact_network_steps"],
            0,
        )
        self.assertEqual(
            transition["diagnostics"]["contact_transition"]["first_post_transition_geometry"],
            "exact form_contact surgery output before network advance",
        )
        self.assertEqual(
            len([item for item in transition["film_regions"] if item["kind"] == "SHARED"]),
            1,
        )
        self.assertEqual(len(transition["junctions"]), 1)
        self.assertGreater(transition["diagnostics"]["shared_dof_count"], 0)

        for frame in frames:
            self.assertEqual([item["id"] for item in frame["bubbles"]], ["bubble-a", "bubble-b"])
        for frame in frames[transition_index:]:
            self.assertEqual(
                len([item for item in frame["film_regions"] if item["kind"] == "SHARED"]),
                1,
            )
            self.assertEqual(len(frame["junctions"]), 1)
            self.assertGreater(frame["diagnostics"]["shared_dof_count"], 0)

    def test_runner_writes_contract_valid_bundle(self) -> None:
        scenario = load_scenario()
        with tempfile.TemporaryDirectory() as out:
            replay = run_scenario(scenario, "contact-transition", out, frames=12)
            validated = validate_replay_bundle(out)
            self.assertEqual(validated, replay)
            self.assertEqual(replay["backend"]["identity"], BACKEND_ID)
            self.assertEqual(len(replay["frames"]), 12)

    def test_rejects_more_than_two_bubbles(self) -> None:
        scenario = copy.deepcopy(load_scenario())
        extra = copy.deepcopy(scenario["initial_bubbles"][1])
        extra["id"] = "bubble-c"
        extra["centroid_m"] = [0.02, 0.0, 0.0]
        scenario["initial_bubbles"].append(extra)
        with self.assertRaisesRegex(ContactRuntimeConfigurationError, "exactly two"):
            run_contact_transition(scenario, 4)

    def test_deterministic_repeat(self) -> None:
        scenario = load_scenario()
        frames_a, metadata_a = run_contact_transition(copy.deepcopy(scenario), 6)
        frames_b, metadata_b = run_contact_transition(copy.deepcopy(scenario), 6)
        canonical = lambda value: json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        self.assertEqual(canonical(frames_a), canonical(frames_b))
        self.assertEqual(canonical(metadata_a), canonical(metadata_b))


if __name__ == "__main__":
    unittest.main()
