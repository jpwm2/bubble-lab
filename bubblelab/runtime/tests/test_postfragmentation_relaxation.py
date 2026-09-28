from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bubblelab" / "python"))

from bubblelab_contract import assert_valid
from bubblelab.runtime.postfragmentation_relaxation import (
    PHASE,
    run_postfragmentation_frames,
    run_postfragmentation_scenario,
)

SCENARIO = ROOT / "bubblelab" / "scenarios" / "runtime" / "postfragmentation-necked.scenario.json"


def _mesh_by_owner(frame: dict) -> dict[str, dict]:
    return {str(mesh["owner_bubble_ids"][0]): mesh for mesh in frame["surface_meshes"]}


class PostFragmentationRelaxationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = json.loads(SCENARIO.read_text(encoding="utf-8"))

    def test_contract_lineage_and_exact_restart_mesh(self) -> None:
        assert_valid(self.scenario)
        frames, backend = run_postfragmentation_frames(self.scenario, frames=5)
        self.assertEqual(backend["identity"], "fragmentation-to-transient-relaxation")
        self.assertEqual(len(frames), 5)
        for frame in frames:
            assert_valid(frame)

        split = frames[1]
        restart = frames[2]
        event = split["topology"]["events"][0]
        self.assertEqual(event["type"], "SPLIT")
        self.assertEqual(restart["postfragmentation_runtime"]["phase"], PHASE)
        self.assertEqual(restart["postfragmentation_runtime"]["child_bubble_ids"], event["bubble_ids_after"])
        self.assertEqual(restart["postfragmentation_runtime"]["parent_bubble_id"], event["bubble_ids_before"][0])
        self.assertTrue(restart["diagnostics"]["postfragmentation_relaxation"]["seed_geometry_preserved"])
        self.assertTrue(restart["diagnostics"]["postfragmentation_relaxation"]["restart_mesh_authoritative"])

        split_meshes = _mesh_by_owner(split)
        restart_meshes = _mesh_by_owner(restart)
        self.assertEqual(set(split_meshes), set(restart_meshes))
        for child_id in event["bubble_ids_after"]:
            self.assertEqual(
                restart_meshes[child_id]["vertices"]["values"],
                split_meshes[child_id]["vertices"]["values"],
            )
            self.assertEqual(
                restart_meshes[child_id]["faces"]["values"],
                split_meshes[child_id]["faces"]["values"],
            )
            bubble = next(item for item in restart["bubbles"] if item["id"] == child_id)
            self.assertEqual(bubble["lineage"], event["lineage"][child_id])

    def test_physical_advancement_preserves_supported_child_invariants(self) -> None:
        frames, _ = run_postfragmentation_frames(self.scenario, frames=6)
        split_time = frames[1]["simulation_time_s"]
        self.assertEqual(frames[2]["simulation_time_s"], split_time)
        self.assertTrue(all(frames[index]["simulation_time_s"] > split_time for index in range(3, len(frames))))

        final = frames[-1]
        relaxation = final["diagnostics"]["postfragmentation_relaxation"]
        self.assertGreater(relaxation["solver_step_index"], 0)
        self.assertTrue(final["postfragmentation_runtime"]["physical_advancement_after_split"])
        self.assertTrue(relaxation["all_children_closed_oriented_manifold"])
        self.assertLessEqual(relaxation["max_child_volume_relative_error"], 1.0e-10)
        self.assertEqual(len(relaxation["children"]), 2)
        self.assertEqual(len(final["surface_meshes"]), 2)
        self.assertEqual(len(final["film_regions"]), 2)
        self.assertEqual(len(final["topology"]["events"]), 1)
        self.assertEqual(final["topology"]["events"][0]["type"], "SPLIT")

        disclosures = final["manifest"]["feature_disclosures"]
        self.assertEqual(disclosures["fragmentation_topology_surgery"], "MODELED")
        self.assertEqual(disclosures["post_split_physical_relaxation"], "MODELED")
        self.assertEqual(disclosures["singular_pinch_off_cfd"], "NOT_IMPLEMENTED")
        self.assertEqual(disclosures["retracting_liquid_rim"], "NOT_IMPLEMENTED")
        self.assertEqual(disclosures["droplet_spray"], "NOT_IMPLEMENTED")

    def test_deterministic_repeat(self) -> None:
        frames_a, backend_a = run_postfragmentation_frames(self.scenario, frames=5)
        frames_b, backend_b = run_postfragmentation_frames(self.scenario, frames=5)
        self.assertEqual(backend_a, backend_b)
        self.assertEqual(frames_a, frames_b)

    def test_replay_bundle_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            replay_a = run_postfragmentation_scenario(self.scenario, a, frames=5)
            replay_b = run_postfragmentation_scenario(self.scenario, b, frames=5)
            self.assertEqual(replay_a, replay_b)
            for rel in ("replay.json", "frames/000000.json", "frames/000001.json", "frames/000002.json", "frames/000004.json"):
                self.assertEqual((Path(a) / rel).read_bytes(), (Path(b) / rel).read_bytes())


if __name__ == "__main__":
    unittest.main()
