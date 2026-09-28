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
from bubblelab.runtime.fragmentation_runtime import run_fragmentation_frames, run_fragmentation_scenario

SCENARIO = ROOT / "bubblelab" / "scenarios" / "runtime" / "fragmentation-necked.scenario.json"


class FragmentationRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = json.loads(SCENARIO.read_text(encoding="utf-8"))

    def test_scenario_and_exported_frames_are_contract_v1_valid(self) -> None:
        assert_valid(self.scenario)
        frames, backend = run_fragmentation_frames(self.scenario)
        self.assertEqual(backend["identity"], "fragmentation-topology")
        self.assertEqual(len(frames), 2)
        for frame in frames:
            assert_valid(frame)

    def test_post_frame_contains_explicit_split_lineage_and_restart_meshes(self) -> None:
        frames, _ = run_fragmentation_frames(self.scenario)
        pre, post = frames
        self.assertEqual(pre["fragmentation_runtime"]["phase"], "PRE_SPLIT")
        self.assertEqual(post["fragmentation_runtime"]["phase"], "POST_SPLIT_RESTART")
        self.assertEqual(len(post["topology"]["events"]), 1)
        event = post["topology"]["events"][0]
        self.assertEqual(event["type"], "SPLIT")
        self.assertEqual(event["bubble_ids_before"], ["necked-parent-1"])
        self.assertEqual(len(event["bubble_ids_after"]), 2)
        self.assertEqual(set(event["lineage"]), set(event["bubble_ids_after"]))
        statuses = {bubble["id"]: bubble["status"] for bubble in post["bubbles"]}
        self.assertEqual(statuses["necked-parent-1"], "SPLIT")
        self.assertTrue(all(statuses[child] == "ALIVE" for child in event["bubble_ids_after"]))
        self.assertEqual(len(post["surface_meshes"]), 2)
        self.assertTrue(all(mesh["closed_manifold"] for mesh in post["surface_meshes"]))
        self.assertTrue(all("derived_from_parent_mesh_digest" in mesh for mesh in post["surface_meshes"]))

    def test_export_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            replay_a = run_fragmentation_scenario(self.scenario, a)
            replay_b = run_fragmentation_scenario(self.scenario, b)
            self.assertEqual(replay_a, replay_b)
            for rel in ("replay.json", "frames/000000.json", "frames/000001.json"):
                self.assertEqual((Path(a) / rel).read_bytes(), (Path(b) / rel).read_bytes())

    def test_conservation_and_fidelity_boundary_are_explicit(self) -> None:
        frames, backend = run_fragmentation_frames(self.scenario)
        conservation = backend["conservation"]
        self.assertLessEqual(float(conservation["gas_amount_relative_error"] or 0.0), 1.0e-12)
        self.assertLessEqual(float(conservation["target_volume_relative_error"] or 0.0), 1.0e-12)
        self.assertLessEqual(float(conservation["geometric_volume_relative_error"] or 0.0), 5.0e-11)
        disclosures = frames[-1]["manifest"]["feature_disclosures"]
        self.assertEqual(disclosures["fragmentation_topology_surgery"], "MODELED")
        self.assertEqual(disclosures["singular_pinch_off_cfd"], "NOT_IMPLEMENTED")
        self.assertEqual(disclosures["post_split_physical_relaxation"], "NOT_IMPLEMENTED")
        self.assertTrue(frames[-1]["diagnostics"]["mesh_quality"]["restart_geometry_requires_relaxation"])


if __name__ == "__main__":
    unittest.main()
