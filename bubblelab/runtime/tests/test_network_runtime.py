from __future__ import annotations

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

from bubblelab.runtime.bundle import validate_replay_bundle
from bubblelab.runtime.runner import UnsupportedScenarioFeature, run_scenario

ROOT = Path(__file__).resolve().parents[3]
SCENARIOS = ROOT / "bubblelab" / "scenarios" / "runtime"


def load(name: str) -> dict:
    return json.loads((SCENARIOS / name).read_text(encoding="utf-8"))


def frame_from(bundle: str, replay: dict) -> dict:
    return json.loads(
        (Path(bundle) / replay["frames"][0]["path"]).read_text(encoding="utf-8")
    )


class NetworkRuntimeTests(unittest.TestCase):
    def test_shared_film_runtime_is_canonical_and_deterministic(self):
        scenario = load("equilibrium-two-shared.scenario.json")
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            replay_a = run_scenario(scenario, "equilibrium", a)
            replay_b = run_scenario(scenario, "equilibrium", b)
            validate_replay_bundle(a)
            validate_replay_bundle(b)
            self.assertEqual(
                (Path(a) / "replay.json").read_bytes(),
                (Path(b) / "replay.json").read_bytes(),
            )
            self.assertEqual(
                (Path(a) / replay_a["frames"][0]["path"]).read_bytes(),
                (Path(b) / replay_b["frames"][0]["path"]).read_bytes(),
            )

            frame = frame_from(a, replay_a)
            self.assertEqual([bubble["id"] for bubble in frame["bubbles"]], ["bubble-a", "bubble-b"])
            self.assertEqual(
                [film["id"] for film in frame["film_regions"]],
                ["outer-a", "outer-b", "shared-ab"],
            )
            shared = [film for film in frame["film_regions"] if film["kind"] == "SHARED"]
            self.assertEqual(len(shared), 1)
            self.assertEqual(shared[0]["adjacent"], ["bubble-a", "bubble-b"])
            mesh = next(
                item for item in frame["surface_meshes"] if item["id"] == shared[0]["mesh_id"]
            )
            self.assertEqual(mesh["geometry_role"], "SHARED_FILM")
            self.assertGreater(mesh["vertex_count"], 0)
            self.assertGreater(mesh["face_count"], 0)
            self.assertNotEqual(frame["bubbles"][0]["pressure_pa"], frame["bubbles"][1]["pressure_pa"])
            self.assertEqual(frame["manifest"]["fidelity_tier"], "HIGH_FIDELITY")
            self.assertEqual(frame["manifest"]["feature_disclosures"]["shared_films"], "RESOLVED")
            self.assertEqual(
                frame["manifest"]["feature_disclosures"]["plateau_junctions"],
                "NOT_IMPLEMENTED",
            )
            diagnostic = frame["diagnostics"]["pressure_curvature"]
            self.assertLessEqual(diagnostic["pressure_curvature_residual"], 1.0e-2)
            self.assertLessEqual(diagnostic["normalized_curvature_error"], 1.0e-2)
            self.assertTrue(diagnostic["sign_consistent"])
            self.assertEqual(replay_a["backend"]["identity"], "bubblelab-equilibrium")
            self.assertEqual(
                replay_a["backend"]["network_initializer"],
                "accepted-b05-unequal-pressure",
            )

    def test_plateau_runtime_is_measured_and_deterministic(self):
        scenario = load("equilibrium-plateau-three.scenario.json")
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            replay_a = run_scenario(scenario, "equilibrium", a)
            replay_b = run_scenario(scenario, "equilibrium", b)
            validate_replay_bundle(a)
            validate_replay_bundle(b)
            self.assertEqual(
                (Path(a) / "replay.json").read_bytes(),
                (Path(b) / "replay.json").read_bytes(),
            )
            self.assertEqual(
                (Path(a) / replay_a["frames"][0]["path"]).read_bytes(),
                (Path(b) / replay_b["frames"][0]["path"]).read_bytes(),
            )

            frame = frame_from(a, replay_a)
            self.assertEqual(
                [bubble["id"] for bubble in frame["bubbles"]],
                ["bubble-a", "bubble-b", "bubble-c"],
            )
            self.assertEqual(len(frame["junctions"]), 1)
            junction = frame["junctions"][0]
            self.assertEqual(junction["id"], "plateau-junction-0")
            self.assertEqual(
                junction["incident_film_ids"],
                ["film-ab", "film-bc", "film-ca"],
            )
            angles = [float(value) for value in junction["measured_angles_deg"]]
            self.assertEqual(len(angles), 3)
            rms = math.sqrt(sum((value - 120.0) ** 2 for value in angles) / len(angles))
            self.assertLessEqual(rms, 1.0)
            self.assertLessEqual(
                junction["measurement_provenance"]["junction_force_residual"],
                5.0e-3,
            )
            self.assertEqual(
                junction["measurement_provenance"]["geometry_source"],
                "solved triangulated film network",
            )
            self.assertEqual(
                frame["manifest"]["feature_disclosures"]["plateau_junctions"],
                "RESOLVED",
            )
            self.assertEqual(
                replay_a["backend"]["network_initializer"],
                "accepted-b06-plateau-three",
            )

    def test_rejects_reversed_shared_adjacency(self):
        scenario = load("equilibrium-two-shared.scenario.json")
        scenario["initial_film_regions"][2]["adjacent"] = ["bubble-b", "bubble-a"]
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaisesRegex(UnsupportedScenarioFeature, "adjacency/order"):
                run_scenario(scenario, "equilibrium", out)

    def test_rejects_duplicate_film_ids(self):
        scenario = load("equilibrium-two-shared.scenario.json")
        scenario["initial_film_regions"][1]["id"] = "outer-a"
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaisesRegex(UnsupportedScenarioFeature, "duplicate film ID"):
                run_scenario(scenario, "equilibrium", out)

    def test_rejects_missing_junction_film_reference(self):
        scenario = load("equilibrium-plateau-three.scenario.json")
        scenario["initial_junctions"][0]["incident_film_ids"][2] = "missing-film"
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaisesRegex(UnsupportedScenarioFeature, "missing film"):
                run_scenario(scenario, "equilibrium", out)

    def test_rejects_unsupported_network_topology(self):
        scenario = load("equilibrium-plateau-three.scenario.json")
        scenario["initial_film_regions"].pop()
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaisesRegex(UnsupportedScenarioFeature, "film IDs/order"):
                run_scenario(scenario, "equilibrium", out)

    def test_rejects_dynamic_transport_claims(self):
        scenario = load("equilibrium-two-shared.scenario.json")
        scenario["requested_solver"]["features"]["gas_diffusion"] = True
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaisesRegex(UnsupportedScenarioFeature, "dynamic transport/contact"):
                run_scenario(scenario, "equilibrium", out)


if __name__ == "__main__":
    unittest.main()
