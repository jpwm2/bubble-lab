from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from bubblelab.runtime.bundle import validate_replay_bundle
from bubblelab.runtime.contact_thinfilm_event_runtime import (
    BACKEND_IDENTITY,
    ContactThinFilmEventConfigurationError,
    run_contact_thinfilm_event_frames,
    run_contact_thinfilm_event_scenario,
)

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "scenarios" / "runtime"


def _load(name: str) -> dict:
    return json.loads((SCENARIOS / name).read_text(encoding="utf-8"))


def _rows(ref: dict) -> list[list[float]]:
    rows, width = int(ref["shape"][0]), int(ref["shape"][1])
    values = ref["values"]
    if len(values) == rows and values and isinstance(values[0], list):
        return [list(row) for row in values]
    return [list(values[index * width:(index + 1) * width]) for index in range(rows)]


def _shared(frame: dict) -> tuple[dict, dict]:
    film = next(item for item in frame["film_regions"] if item["kind"] == "SHARED")
    mesh = next(item for item in frame["surface_meshes"] if item["id"] == film["mesh_id"])
    return mesh, film


def _events(frames: list[dict]) -> list[dict]:
    seen, output = set(), []
    for frame in frames:
        for event in frame["topology"]["events"]:
            if event["id"] not in seen:
                seen.add(event["id"])
                output.append(event)
    return output


class ContactThinFilmEventRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.drainage_scenario = _load("contact-thinfilm-event-drainage.scenario.json")
        cls.drainage_frames, cls.drainage_meta = run_contact_thinfilm_event_frames(
            cls.drainage_scenario,
            contact_frames=12,
            thinfilm_frames=8,
        )
        cls.rupture_scenario = _load("contact-thinfilm-event-rupture.scenario.json")
        cls.rupture_frames, cls.rupture_meta = run_contact_thinfilm_event_frames(
            cls.rupture_scenario,
            contact_frames=12,
            thinfilm_frames=8,
        )

    def test_exact_contact_geometry_and_ids_seed_thinfilm(self) -> None:
        frames = self.drainage_frames
        self.assertEqual(frames[0]["simulation_time_s"], 0.0)
        contact_event = next(
            event for event in frames[0]["topology"]["events"]
            if event.get("transition_kind") == "CONTACT_FORMATION"
        )
        self.assertEqual(contact_event["time_s"], 0.0)
        self.assertGreater(contact_event["provenance"]["source_contact_simulation_time_s"], 0.0)

        source_mesh, source_film = _shared(frames[0])
        thinfilm_mesh, thinfilm_film = _shared(frames[1])
        self.assertEqual(source_film["id"], thinfilm_film["id"])
        self.assertEqual(source_mesh["id"], thinfilm_mesh["id"])
        self.assertEqual(_rows(source_mesh["vertices"]), _rows(thinfilm_mesh["vertices"]))
        self.assertEqual(_rows(source_mesh["faces"]), _rows(thinfilm_mesh["faces"]))
        self.assertEqual(
            frames[0]["diagnostics"]["contact_thinfilm_event_runtime"]["shared_film_geometry_digest"],
            frames[1]["diagnostics"]["contact_thinfilm_event_runtime"]["shared_film_geometry_digest"],
        )
        self.assertEqual(
            [bubble["id"] for bubble in frames[1]["bubbles"]],
            ["bubble-a", "bubble-b"],
        )

    def test_accepted_transport_evolves_and_conserves(self) -> None:
        thinfilm = [
            frame["diagnostics"]["thinfilm"]
            for frame in self.drainage_frames[1:]
            if "thinfilm" in frame.get("diagnostics", {})
        ]
        minima = [float(item["min_thickness_m"]) for item in thinfilm]
        self.assertGreater(len(minima), 1)
        self.assertLess(min(minima[1:]), minima[0])
        gas_amounts = [item["gas_amounts_mol"] for item in thinfilm if "gas_amounts_mol" in item]
        self.assertGreater(len(gas_amounts), 1)
        self.assertNotEqual(gas_amounts[0], gas_amounts[-1])
        for item in thinfilm:
            if "gas_total_relative_drift" in item:
                self.assertLessEqual(float(item["gas_total_relative_drift"]), 1.0e-12)
            step = item.get("surface_step")
            if step:
                self.assertLessEqual(float(step["liquid_relative_drift"]), 1.0e-12)
                self.assertLessEqual(float(step["surfactant_relative_drift"]), 1.0e-12)
        self.assertEqual(self.drainage_meta["identity"], BACKEND_IDENTITY)
        self.assertTrue(self.drainage_meta["drainage_enabled"])
        self.assertTrue(self.drainage_meta["gas_diffusion_enabled"])

    def test_physical_threshold_reaches_accepted_rupture_and_coalescence(self) -> None:
        events = _events(self.rupture_frames)
        event_types = [event["type"] for event in events]
        self.assertIn("FILM_FORMED", event_types)
        self.assertIn("RUPTURE", event_types)
        self.assertIn("COALESCENCE", event_types)
        rupture = next(event for event in events if event["type"] == "RUPTURE")
        coalescence = next(event for event in events if event["type"] == "COALESCENCE")
        self.assertEqual(rupture["provenance"]["source"], "SOLVER")
        self.assertIn(rupture["criterion"], ("THICKNESS_THRESHOLD", "THICKNESS_DWELL"))
        localization = rupture["provenance"]["event_time_localization"]
        self.assertLess(localization["thickness_end_m"], localization["thickness_start_m"])
        self.assertEqual(rupture["time_s"], coalescence["time_s"])
        self.assertEqual(coalescence["bubble_ids_before"], ["bubble-a", "bubble-b"])
        self.assertEqual(len(coalescence["bubble_ids_after"]), 1)
        conservation = coalescence["conservation"]
        self.assertLessEqual(conservation["gas_amount_relative_error"], 1.0e-12)
        self.assertLessEqual(conservation["target_volume_relative_error"], 1.0e-12)
        self.assertLessEqual(conservation["restart_geometry_volume_relative_error"], 1.0e-12)

    def test_rejects_hidden_initialization_and_writes_valid_deterministic_bundle(self) -> None:
        missing = copy.deepcopy(self.drainage_scenario)
        del missing["user_editable"]["thinfilm"]["initial_thickness_m"]
        with self.assertRaisesRegex(ContactThinFilmEventConfigurationError, "initial_thickness_m"):
            run_contact_thinfilm_event_frames(missing, contact_frames=12, thinfilm_frames=2)

        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_replay = run_contact_thinfilm_event_scenario(
                self.drainage_scenario, first, contact_frames=12, thinfilm_frames=4
            )
            second_replay = run_contact_thinfilm_event_scenario(
                self.drainage_scenario, second, contact_frames=12, thinfilm_frames=4
            )
            self.assertEqual(validate_replay_bundle(first), first_replay)
            self.assertEqual(validate_replay_bundle(second), second_replay)
            self.assertEqual(
                (Path(first) / "replay.json").read_bytes(),
                (Path(second) / "replay.json").read_bytes(),
            )
            for left, right in zip(first_replay["frames"], second_replay["frames"]):
                self.assertEqual(
                    (Path(first) / left["path"]).read_bytes(),
                    (Path(second) / right["path"]).read_bytes(),
                )


if __name__ == "__main__":
    unittest.main()
