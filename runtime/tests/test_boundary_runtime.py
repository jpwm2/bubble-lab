from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from bubblelab.runtime.boundary_runtime import (
    BoundaryRuntimeConfigurationError,
    solid_boundaries_from_scenario,
)
from bubblelab.runtime.bundle import validate_replay_bundle
from bubblelab.runtime.runner import UnsupportedScenarioFeature, run_scenario
from bubblelab.solvers.boundary import AxisAlignedBoxBoundary, PlaneBoundary, SphereBoundary


ROOT = Path(__file__).resolve().parents[3]
SCENARIOS = ROOT / "bubblelab" / "scenarios" / "runtime"


def load(name: str) -> dict:
    return json.loads((SCENARIOS / name).read_text(encoding="utf-8"))


def load_frames(root: str | Path, replay: dict) -> list[dict]:
    base = Path(root)
    return [json.loads((base / ref["path"]).read_text(encoding="utf-8")) for ref in replay["frames"]]


class BoundaryRuntimeTests(unittest.TestCase):
    def test_parser_resolves_plane_sphere_and_aabb_with_wetting(self):
        scenario = load("transient-floor-contact.scenario.json")
        scenario["user_editable"]["solid_boundaries"].append(
            {
                "id": "box-obstacle",
                "type": "AABB",
                "minimum_m": [0.02, -0.01, -0.005],
                "maximum_m": [0.03, 0.01, 0.005],
            }
        )
        scenario["environment"]["boundary_refs"].append("box-obstacle")
        boundaries = solid_boundaries_from_scenario(scenario)
        self.assertEqual([boundary.boundary_id for boundary in boundaries], ["floor", "obstacle-sphere", "box-obstacle"])
        self.assertIsInstance(boundaries[0], PlaneBoundary)
        self.assertIsInstance(boundaries[1], SphereBoundary)
        self.assertIsInstance(boundaries[2], AxisAlignedBoxBoundary)
        self.assertEqual(boundaries[0].wetting.target_contact_angle_deg, 60.0)

    def test_floor_contact_replay_is_deterministic_and_disclosed(self):
        scenario = load("transient-floor-contact.scenario.json")
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            replay_a = run_scenario(scenario, "transient", first, frames=4)
            replay_b = run_scenario(scenario, "transient", second, frames=4)
            validate_replay_bundle(first)
            validate_replay_bundle(second)
            self.assertEqual((Path(first) / "replay.json").read_bytes(), (Path(second) / "replay.json").read_bytes())
            for ref_a, ref_b in zip(replay_a["frames"], replay_b["frames"]):
                self.assertEqual((Path(first) / ref_a["path"]).read_bytes(), (Path(second) / ref_b["path"]).read_bytes())

            frames = load_frames(first, replay_a)
            contacts = [frame["diagnostics"]["solid_boundary_contact"] for frame in frames]
            self.assertTrue(any(entry["contact_vertex_count"] > 0 for entry in contacts))
            self.assertTrue(any("floor" in entry["active_boundary_ids"] for entry in contacts))
            self.assertTrue(all(entry["max_penetration_post_m"] <= 1.0e-12 for entry in contacts))
            self.assertEqual(frames[-1]["environment"]["boundary_refs"], ["floor", "obstacle-sphere"])
            disclosures = frames[-1]["manifest"]["feature_disclosures"]
            self.assertEqual(disclosures["solid_boundary_sdf_geometry"], "RESOLVED")
            self.assertEqual(disclosures["tracked_film_solid_no_penetration"], "RESOLVED")
            self.assertEqual(disclosures["tracked_film_wall_tangential_motion"], "MODELED")
            self.assertEqual(disclosures["film_wall_contact_angle"], "MODELED")
            self.assertEqual(disclosures["bulk_solid_wall_no_slip"], "RESOLVED")
            self.assertEqual(disclosures["bulk_solid_fluid_wall_coupling"], "RESOLVED")
            self.assertEqual(
                contacts[-1]["bulk_eulerian_wall_coupling"],
                "RESOLVED_SDF_CUT_STENCIL_NO_SLIP",
            )
            self.assertTrue(frames[-1]["diagnostics"]["bulk_solid_wall_cfd"]["installed_on_all_levels"])

    def test_legacy_no_boundary_transient_remains_boundary_disabled(self):
        scenario = load("transient-wind.scenario.json")
        self.assertEqual(solid_boundaries_from_scenario(scenario), ())
        with tempfile.TemporaryDirectory() as out:
            replay = run_scenario(scenario, "transient", out, frames=2)
            frame = load_frames(out, replay)[-1]
            self.assertNotIn("boundary_refs", frame["environment"])
            self.assertFalse(frame["diagnostics"]["solid_boundary_contact"]["enabled"])
            self.assertEqual(
                frame["manifest"]["feature_disclosures"]["solid_boundary_sdf_geometry"],
                "NOT_IMPLEMENTED",
            )
            self.assertEqual(
                frame["manifest"]["feature_disclosures"]["bulk_solid_wall_no_slip"],
                "NOT_IMPLEMENTED",
            )
            self.assertNotIn("bulk_solid_wall_cfd", frame["diagnostics"])

    def test_unknown_boundary_reference_and_geometry_are_rejected(self):
        scenario = load("transient-floor-contact.scenario.json")
        bad_ref = copy.deepcopy(scenario)
        bad_ref["environment"]["boundary_refs"] = ["missing"]
        with self.assertRaisesRegex(BoundaryRuntimeConfigurationError, "unknown boundary"):
            solid_boundaries_from_scenario(bad_ref)

        bad_geometry = copy.deepcopy(scenario)
        bad_geometry["user_editable"]["solid_boundaries"][0] = {
            "id": "floor",
            "type": "mesh",
        }
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaisesRegex(UnsupportedScenarioFeature, "unsupported solid boundary geometry"):
                run_scenario(bad_geometry, "transient", out, frames=1)

    def test_resolved_bulk_no_slip_request_runs(self):
        scenario = load("transient-floor-contact.scenario.json")
        scenario["requested_solver"]["features"]["bulk_solid_wall_no_slip"] = True
        with tempfile.TemporaryDirectory() as out:
            replay = run_scenario(scenario, "transient", out, frames=1)
            frame = load_frames(out, replay)[0]
            self.assertTrue(replay["run_settings"]["bulk_solid_wall_no_slip_requested"])
            self.assertEqual(
                frame["manifest"]["feature_disclosures"]["bulk_solid_wall_no_slip"],
                "RESOLVED",
            )
            self.assertTrue(frame["diagnostics"]["bulk_solid_wall_cfd"]["installed_on_all_levels"])


if __name__ == "__main__":
    unittest.main()
