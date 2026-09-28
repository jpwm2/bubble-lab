from __future__ import annotations

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


def read_frames(root: str, replay: dict) -> list[dict]:
    return [
        json.loads((Path(root) / ref["path"]).read_text(encoding="utf-8"))
        for ref in replay["frames"]
    ]


class ThinFilmRuntimeTests(unittest.TestCase):
    def test_transient_thinfilm_fields_are_modeled_and_repeat_exactly(self):
        scenario = load("transient-thinfilm.scenario.json")
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            ra = run_scenario(scenario, "transient", a, frames=6)
            rb = run_scenario(scenario, "transient", b, frames=6)
            validate_replay_bundle(a)
            validate_replay_bundle(b)

            self.assertEqual((Path(a) / "replay.json").read_bytes(), (Path(b) / "replay.json").read_bytes())
            self.assertEqual(len(ra["frames"]), 6)
            for left, right in zip(ra["frames"], rb["frames"]):
                self.assertEqual(
                    (Path(a) / left["path"]).read_bytes(),
                    (Path(b) / right["path"]).read_bytes(),
                )

            frames = read_frames(a, ra)
            final = frames[-1]
            mesh = final["surface_meshes"][0]
            self.assertIn("film_thickness_m", mesh["fields"])
            self.assertIn("surfactant_mol_m2", mesh["fields"])
            self.assertIn("surface_tension_n_m", mesh["fields"])
            self.assertEqual(
                final["film_regions"][0]["thickness"]["fidelity"],
                "MODELED",
            )
            disclosures = final["manifest"]["feature_disclosures"]
            self.assertEqual(disclosures["film_thickness"], "MODELED")
            self.assertEqual(disclosures["film_drainage"], "MODELED")
            self.assertEqual(disclosures["surfactant_diffusion"], "MODELED")
            self.assertEqual(disclosures["gas_diffusion"], "NOT_IMPLEMENTED")

            initial_h = frames[0]["surface_meshes"][0]["fields"]["film_thickness_m"]["values"]
            final_h = mesh["fields"]["film_thickness_m"]["values"]
            self.assertNotEqual(initial_h, final_h)
            self.assertGreater(max(final_h) - min(final_h), 0.0)
            thinfilm = final["diagnostics"]["thinfilm"]
            self.assertGreater(thinfilm["liquid_amount_m3"], 0.0)
            self.assertGreater(thinfilm["surfactant_amount_mol"], 0.0)
            self.assertIn("step", thinfilm)
            self.assertIn("geometry_transfer", thinfilm)
            self.assertIn("thinfilm_operator_split", final["manifest"]["provenance"])

    def test_two_bubble_gas_diffusion_conserves_total_and_moves_high_to_low_pressure(self):
        scenario = load("two-bubble-diffusion.scenario.json")
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            ra = run_scenario(scenario, "thinfilm", a, frames=6)
            rb = run_scenario(scenario, "thinfilm", b, frames=6)
            validate_replay_bundle(a)
            validate_replay_bundle(b)
            self.assertEqual((Path(a) / "replay.json").read_bytes(), (Path(b) / "replay.json").read_bytes())
            for left, right in zip(ra["frames"], rb["frames"]):
                self.assertEqual(
                    (Path(a) / left["path"]).read_bytes(),
                    (Path(b) / right["path"]).read_bytes(),
                )

            frames = read_frames(a, ra)
            first = frames[0]
            last = frames[-1]
            first_bubbles = {item["id"]: item for item in first["bubbles"]}
            last_bubbles = {item["id"]: item for item in last["bubbles"]}
            self.assertGreater(
                first_bubbles["bubble-small"]["pressure_pa"],
                first_bubbles["bubble-large"]["pressure_pa"],
            )
            self.assertLess(
                last_bubbles["bubble-small"]["gas_amount_mol"],
                first_bubbles["bubble-small"]["gas_amount_mol"],
            )
            self.assertGreater(
                last_bubbles["bubble-large"]["gas_amount_mol"],
                first_bubbles["bubble-large"]["gas_amount_mol"],
            )
            initial_gap = (
                first_bubbles["bubble-small"]["pressure_pa"]
                - first_bubbles["bubble-large"]["pressure_pa"]
            )
            final_gap = (
                last_bubbles["bubble-small"]["pressure_pa"]
                - last_bubbles["bubble-large"]["pressure_pa"]
            )
            self.assertLess(abs(final_gap), abs(initial_gap))
            diag = last["diagnostics"]["thinfilm"]
            self.assertLessEqual(diag["gas_total_relative_drift"], 1.0e-12)
            self.assertEqual(
                diag["coarsening_direction"],
                {"from": "bubble-small", "to": "bubble-large"},
            )
            self.assertEqual(
                last["manifest"]["feature_disclosures"]["gas_diffusion"],
                "MODELED",
            )
            self.assertEqual(
                last["manifest"]["feature_disclosures"]["geometry_evolution"],
                "NOT_IMPLEMENTED",
            )
            self.assertEqual(
                last["film_regions"][0]["thickness"]["fidelity"],
                "MODELED",
            )

    def test_requested_drainage_without_transport_configuration_fails_explicitly(self):
        scenario = load("transient-wind.scenario.json")
        scenario["requested_solver"]["features"]["drainage"] = True
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaisesRegex(
                UnsupportedScenarioFeature,
                "drainage.*user_editable.thinfilm",
            ):
                run_scenario(scenario, "transient", out, frames=2)

    def test_topology_changing_coalescence_is_rejected_before_runtime(self):
        scenario = load("transient-thinfilm.scenario.json")
        scenario["requested_solver"]["features"]["coalescence"] = True
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaisesRegex(UnsupportedScenarioFeature, "coalescence"):
                run_scenario(scenario, "transient", out, frames=2)

    def test_multi_junction_transport_is_explicitly_unsupported(self):
        scenario = load("two-bubble-diffusion.scenario.json")
        scenario["initial_junctions"] = [
            {
                "id": "junction-1",
                "incident_film_ids": ["film-shared", "film-x", "film-y"],
            }
        ]
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaisesRegex(
                UnsupportedScenarioFeature,
                "multi-junction",
            ):
                run_scenario(scenario, "thinfilm", out, frames=2)


if __name__ == "__main__":
    unittest.main()
