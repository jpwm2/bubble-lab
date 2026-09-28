from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from bubblelab.runtime import run_scenario


ROOT = Path(__file__).resolve().parents[2]
SCENARIO = ROOT / "scenarios" / "runtime" / "two-bubble-coalescence-relaxation.scenario.json"
PHASE = "POST_EVENT_TRANSIENT_RELAXATION"
UNIT_FRAMES = 8


def _scenario() -> dict:
    return json.loads(SCENARIO.read_text(encoding="utf-8"))


def _frames(root: Path, replay: dict) -> list[dict]:
    return [
        json.loads((root / item["path"]).read_text(encoding="utf-8"))
        for item in replay["frames"]
    ]


class PostCoalescenceRelaxationTests(unittest.TestCase):
    def test_restart_mesh_is_handed_to_transient_solver_then_evolves(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            replay = run_scenario(_scenario(), "thinfilm-events", root, UNIT_FRAMES)
            frames = _frames(root, replay)

        self.assertEqual(len(frames), UNIT_FRAMES)
        event = next(
            frame for frame in frames
            if frame.get("event_runtime", {}).get("phase") == "EVENT"
        )
        post = [
            frame for frame in frames
            if frame.get("event_runtime", {}).get("phase") == PHASE
        ]
        self.assertGreaterEqual(len(post), 3)
        restart = next(
            mesh for mesh in event["surface_meshes"]
            if mesh.get("restart_geometry") is not None
        )
        seed = post[0]["surface_meshes"][0]
        self.assertEqual(restart["restart_geometry"]["kind"], "VOLUME_MATCHED_OCTAHEDRON")
        self.assertEqual(seed["vertices"], restart["vertices"])
        self.assertEqual(seed["faces"], restart["faces"])
        self.assertEqual(seed["vertex_count"], 6)
        self.assertEqual(seed["face_count"], 8)
        self.assertTrue(post[0]["diagnostics"]["post_event_relaxation"]["seed_geometry_preserved"])

        seed_signature = (
            seed["vertex_count"],
            seed["face_count"],
            tuple(seed["vertices"]["values"]),
            tuple(seed["faces"]["values"]),
        )
        later_signatures = []
        for frame in post[1:]:
            mesh = frame["surface_meshes"][0]
            later_signatures.append((
                mesh["vertex_count"],
                mesh["face_count"],
                tuple(mesh["vertices"]["values"]),
                tuple(mesh["faces"]["values"]),
            ))
        self.assertTrue(any(signature != seed_signature for signature in later_signatures))
        self.assertTrue(all(
            frame["event_runtime"]["physical_advancement_after_event"]
            for frame in post[1:]
        ))
        self.assertEqual(replay["backend"]["post_event_continuation"], PHASE)

    def test_lineage_history_volume_and_relaxation_diagnostics_persist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            replay = run_scenario(_scenario(), "thinfilm-events", root, UNIT_FRAMES)
            frames = _frames(root, replay)

        event = next(
            frame for frame in frames
            if frame.get("event_runtime", {}).get("phase") == "EVENT"
        )
        post = [
            frame for frame in frames
            if frame.get("event_runtime", {}).get("phase") == PHASE
        ]
        coalescence = next(item for item in event["topology"]["events"] if item["type"] == "COALESCENCE")
        child_id, parents = next(iter(coalescence["lineage"].items()))
        event_history = event["topology"]["events"]
        event_ids = [item["id"] for item in event_history]

        for frame in post:
            self.assertEqual(frame["topology"]["events"], event_history)
            self.assertEqual(frame["event_runtime"]["event_ids"], event_ids)
            self.assertEqual(frame["event_runtime"]["child_bubble_id"], child_id)
            self.assertEqual(frame["event_runtime"]["parent_lineage"], parents)
            child = next(bubble for bubble in frame["bubbles"] if bubble["id"] == child_id)
            self.assertEqual(child["lineage"], parents)
            self.assertEqual(child["status"], "ALIVE")
            metrics = frame["diagnostics"]["post_event_relaxation"]
            self.assertLessEqual(metrics["volume_relative_error"], 5.0e-10)
            self.assertIn("surface_energy_j", metrics)
            self.assertIn("bulk_kinetic_energy_j", metrics)
            self.assertIn("capillary_excess_ratio_to_seed", metrics)
        self.assertEqual(post[0]["diagnostics"]["post_event_relaxation"]["capillary_excess_ratio_to_seed"], 1.0)
        self.assertEqual(replay["event_runtime"]["post_event_frame_count"], len(post))

    def test_repeat_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_root = Path(first)
            second_root = Path(second)
            first_replay = run_scenario(_scenario(), "thinfilm-events", first_root, UNIT_FRAMES)
            second_replay = run_scenario(_scenario(), "thinfilm-events", second_root, UNIT_FRAMES)
            self.assertEqual(
                (first_root / "replay.json").read_bytes(),
                (second_root / "replay.json").read_bytes(),
            )
            self.assertEqual(
                [(first_root / item["path"]).read_bytes() for item in first_replay["frames"]],
                [(second_root / item["path"]).read_bytes() for item in second_replay["frames"]],
            )


if __name__ == "__main__":
    unittest.main()
