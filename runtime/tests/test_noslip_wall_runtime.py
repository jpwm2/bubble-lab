from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from bubblelab.runtime.bundle import validate_replay_bundle
from bubblelab.runtime.runner import UnsupportedScenarioFeature, run_scenario


ROOT = Path(__file__).resolve().parents[3]
SCENARIO = ROOT / "bubblelab" / "scenarios" / "runtime" / "transient-noslip-moving-floor.scenario.json"


def load_scenario() -> dict:
    return json.loads(SCENARIO.read_text(encoding="utf-8"))


def load_frames(root: str | Path, replay: dict) -> list[dict]:
    base = Path(root)
    return [json.loads((base / ref["path"]).read_text(encoding="utf-8")) for ref in replay["frames"]]


class NoSlipWallRuntimeTests(unittest.TestCase):
    def test_explicit_feature_runs_and_exports_authoritative_wall_diagnostics(self):
        scenario = load_scenario()
        with tempfile.TemporaryDirectory() as out:
            replay = run_scenario(scenario, "transient", out, frames=3)
            validate_replay_bundle(out)
            frames = load_frames(out, replay)

            self.assertTrue(replay["run_settings"]["bulk_solid_wall_no_slip_requested"])
            self.assertIn("bulk_wall_cfd", replay["backend"])
            self.assertEqual(
                replay["provenance"]["bulk_solid_wall_cfd"]["measurement_source"],
                "authoritative Eulerian velocity state",
            )

            initial = frames[0]["diagnostics"]["bulk_solid_wall_cfd"]
            final = frames[-1]["diagnostics"]["bulk_solid_wall_cfd"]
            self.assertEqual(initial["wall_field"], "ResolvedNoSlipWallField")
            self.assertTrue(initial["installed_on_all_levels"])
            self.assertGreater(initial["solid_cell_count"], 0)
            self.assertGreater(initial["cut_face_count"], 0)
            self.assertGreater(initial["tangential_reconstruction_sample_count"], 0)
            self.assertGreater(initial["max_wall_tangential_reconstruction_error_m_s"], 0.05)
            self.assertLessEqual(final["max_wall_normal_velocity_error_m_s"], 1.0e-12)
            self.assertLessEqual(final["max_solid_storage_velocity_error_m_s"], 1.0e-12)
            self.assertEqual(replay["backend"]["bulk_wall_cfd"], final)

            for frame in frames:
                disclosures = frame["manifest"]["feature_disclosures"]
                self.assertEqual(disclosures["bulk_solid_wall_no_slip"], "RESOLVED")
                self.assertEqual(disclosures["bulk_solid_fluid_wall_coupling"], "RESOLVED")
                self.assertEqual(
                    frame["diagnostics"]["solid_boundary_contact"]["bulk_eulerian_wall_coupling"],
                    "RESOLVED_SDF_CUT_STENCIL_NO_SLIP",
                )

    def test_explicit_noslip_requires_boundary_refs(self):
        scenario = load_scenario()
        scenario["environment"]["boundary_refs"] = []
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaisesRegex(
                UnsupportedScenarioFeature,
                "bulk_solid_wall_no_slip requires environment.boundary_refs",
            ):
                run_scenario(scenario, "transient", out, frames=1)

    def test_legacy_alias_is_not_promoted_to_supported_contract(self):
        scenario = load_scenario()
        scenario["requested_solver"]["features"]["bulk_solid_wall_no_slip"] = False
        scenario["requested_solver"]["features"]["bulk_no_slip"] = True
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaisesRegex(UnsupportedScenarioFeature, "unsupported bulk-wall feature alias"):
                run_scenario(scenario, "transient", out, frames=1)

    def test_deterministic_replay_includes_identical_wall_measurements(self):
        scenario = load_scenario()
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            replay_a = run_scenario(copy.deepcopy(scenario), "transient", first, frames=2)
            replay_b = run_scenario(copy.deepcopy(scenario), "transient", second, frames=2)
            self.assertEqual((Path(first) / "replay.json").read_bytes(), (Path(second) / "replay.json").read_bytes())
            self.assertEqual(replay_a["backend"]["bulk_wall_cfd"], replay_b["backend"]["bulk_wall_cfd"])


if __name__ == "__main__":
    unittest.main()
