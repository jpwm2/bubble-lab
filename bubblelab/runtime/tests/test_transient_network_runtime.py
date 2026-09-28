from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from bubblelab.runtime.bundle import validate_replay_bundle
from bubblelab.runtime.runner import UnsupportedScenarioFeature, run_scenario

ROOT = Path(__file__).resolve().parents[3]
SCENARIOS = ROOT / "bubblelab" / "scenarios" / "runtime"


def load(name: str) -> dict:
    return json.loads((SCENARIOS / name).read_text(encoding="utf-8"))


def read_frames(bundle: str, replay: dict) -> list[dict]:
    root = Path(bundle)
    return [
        json.loads((root / item["path"]).read_text(encoding="utf-8"))
        for item in replay["frames"]
    ]


def mesh_vertices(frame: dict, mesh_id: str) -> list[list[float]]:
    mesh = next(item for item in frame["surface_meshes"] if item["id"] == mesh_id)
    return mesh["vertices"]["values"]


class TransientNetworkRuntimeTests(unittest.TestCase):
    def test_shared_film_evolves_deterministically_with_stable_identity(self):
        scenario = load("transient-network-shared-film.scenario.json")
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            replay_a = run_scenario(scenario, "transient-network", a, frames=4)
            replay_b = run_scenario(scenario, "transient-network", b, frames=4)
            validate_replay_bundle(a)
            validate_replay_bundle(b)
            self.assertEqual(
                (Path(a) / "replay.json").read_bytes(),
                (Path(b) / "replay.json").read_bytes(),
            )
            frames_a = read_frames(a, replay_a)
            frames_b = read_frames(b, replay_b)
            self.assertEqual(frames_a, frames_b)

            self.assertEqual(replay_a["backend"]["identity"], "bubblelab-transient-network")
            self.assertIn("reduced-order", replay_a["backend"]["model_class"])
            self.assertFalse(replay_a["backend"]["fully_coupled_multi_region_eulerian_cfd"])
            self.assertEqual(len(frames_a), 4)
            for actual, expected in zip(
                [frame["simulation_time_s"] for frame in frames_a],
                [0.0, 0.0002, 0.0004, 0.0006],
            ):
                self.assertAlmostEqual(actual, expected, places=15)

            expected_regions = ["bubble-a", "bubble-b"]
            expected_films = ["outer-a", "outer-b", "shared-ab"]
            energies = []
            for frame in frames_a:
                self.assertEqual([item["id"] for item in frame["bubbles"]], expected_regions)
                self.assertEqual([item["id"] for item in frame["film_regions"]], expected_films)
                self.assertEqual(frame["junctions"], [])
                self.assertEqual(frame["diagnostics"]["region_ids"], expected_regions)
                self.assertEqual(frame["diagnostics"]["film_ids"], expected_films)
                self.assertLessEqual(frame["diagnostics"]["max_relative_volume_error"], 5.0e-8)
                energies.append(frame["diagnostics"]["surface_energy_j"])
                shared = next(item for item in frame["film_regions"] if item["id"] == "shared-ab")
                self.assertEqual(shared["adjacent"], ["bubble-a", "bubble-b"])
                mesh = next(item for item in frame["surface_meshes"] if item["id"] == shared["mesh_id"])
                self.assertEqual(mesh["geometry_role"], "SHARED_FILM")
                self.assertGreater(mesh["vertex_count"], 0)
            for before, after in zip(energies, energies[1:]):
                self.assertLessEqual(after, before + 2.0e-12 * max(abs(before), 1.0))

    def test_plateau_frames_preserve_shared_dofs_and_junction(self):
        scenario = load("transient-network-plateau.scenario.json")
        with tempfile.TemporaryDirectory() as out:
            replay = run_scenario(scenario, "transient-network", out, frames=4)
            validate_replay_bundle(out)
            frames = read_frames(out, replay)
            self.assertGreater(replay["backend"]["shared_dof_count"], 0)
            for frame in frames:
                self.assertEqual(frame["diagnostics"]["junction_ids"], ["plateau-junction-0"])
                self.assertGreater(frame["diagnostics"]["shared_dof_count"], 0)
                self.assertLessEqual(frame["diagnostics"]["max_relative_volume_error"], 5.0e-8)
                self.assertLessEqual(frame["diagnostics"]["junction_force_residual"], 5.0e-2)
                self.assertEqual(len(frame["junctions"]), 1)
                junction = frame["junctions"][0]
                self.assertEqual(junction["id"], "plateau-junction-0")
                self.assertEqual(
                    junction["incident_film_ids"],
                    ["film-ab", "film-bc", "film-ca"],
                )
                self.assertGreater(len(junction["geometry"]["values"]), 0)
                self.assertEqual(
                    junction["measurement_provenance"]["geometry_source"],
                    "authoritative transient shared-DOF network",
                )

    def test_forcing_changes_authoritative_geometry(self):
        scenario = load("transient-network-forced.scenario.json")
        with tempfile.TemporaryDirectory() as out:
            replay = run_scenario(scenario, "transient-network", out, frames=6)
            validate_replay_bundle(out)
            frames = read_frames(out, replay)
            first = mesh_vertices(frames[0], "mesh-shared-ab")
            last = mesh_vertices(frames[-1], "mesh-shared-ab")
            delta = max(
                sum((a - b) ** 2 for a, b in zip(before, after)) ** 0.5
                for before, after in zip(first, last)
            )
            self.assertGreater(delta, 1.0e-10)
            self.assertGreater(
                max(frame["diagnostics"]["max_displacement_m"] for frame in frames[1:]),
                0.0,
            )
            self.assertLessEqual(
                max(frame["diagnostics"]["max_relative_volume_error"] for frame in frames),
                5.0e-8,
            )

    def test_rejects_mismatched_film_adjacency(self):
        scenario = load("transient-network-shared-film.scenario.json")
        scenario["initial_film_regions"][2]["adjacent"] = ["bubble-b", "bubble-a"]
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaisesRegex(UnsupportedScenarioFeature, "adjacency/order"):
                run_scenario(scenario, "transient-network", out, frames=2)

    def test_rejects_topology_change_feature(self):
        scenario = copy.deepcopy(load("transient-network-shared-film.scenario.json"))
        scenario["requested_solver"]["features"]["coalescence"] = True
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaisesRegex(UnsupportedScenarioFeature, "coalescence"):
                run_scenario(scenario, "transient-network", out, frames=2)


if __name__ == "__main__":
    unittest.main()
