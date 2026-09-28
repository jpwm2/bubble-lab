from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from bubblelab.runtime.contact_lubrication_runtime import (
    run_contact_lubrication_transition,
)


SCENARIO = (
    Path(__file__).resolve().parents[2]
    / "scenarios"
    / "runtime"
    / "contact-lubrication-two-bubble.scenario.json"
)


def _contact_event(frames: list[dict[str, object]]) -> tuple[dict[str, object], dict[str, object]]:
    matches: list[tuple[dict[str, object], dict[str, object]]] = []
    for frame in frames:
        topology = frame.get("topology") or {}
        if not isinstance(topology, dict):
            continue
        for event in topology.get("events", []):
            if isinstance(event, dict) and event.get("transition_kind") == "CONTACT_FORMATION":
                matches.append((frame, event))
    if len(matches) != 1:
        raise AssertionError(f"expected one CONTACT_FORMATION, got {len(matches)}")
    return matches[0]


class ContactLubricationRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scenario = json.loads(SCENARIO.read_text(encoding="utf-8"))
        cls.enabled_frames, cls.enabled_meta = run_contact_lubrication_transition(
            cls.scenario,
            12,
        )
        disabled = copy.deepcopy(cls.scenario)
        disabled["user_editable"]["contact_runtime"]["lubrication"]["enabled"] = False
        cls.disabled_frames, cls.disabled_meta = run_contact_lubrication_transition(
            disabled,
            12,
        )

    def test_pressure_feedback_changes_authoritative_contact_timing(self) -> None:
        model = self.enabled_meta["pre_contact_lubrication"]
        self.assertEqual(model["status"], "MODELED")
        self.assertGreater(model["activation_count"], 0)
        self.assertGreater(model["max_center_pressure_pa"], 0.0)
        self.assertGreater(model["max_lubrication_force_n"], 0.0)
        self.assertLessEqual(model["max_closed_bubble_volume_relative_change"], 5.0e-12)
        self.assertGreater(
            self.enabled_meta["contact_event_time_s"],
            self.disabled_meta["contact_event_time_s"],
        )

    def test_contact_handoff_preserves_accepted_topology_and_provenance(self) -> None:
        frame, event = _contact_event(self.enabled_frames)
        shared = [
            item
            for item in frame["film_regions"]
            if item.get("kind") == "SHARED"
        ]
        self.assertEqual(len(shared), 1)
        self.assertEqual(len(frame["junctions"]), 1)
        self.assertEqual(
            event["provenance"]["pre_contact_lubrication_status"],
            "MODELED",
        )
        self.assertGreater(
            event["provenance"]["lubrication_history_steps"],
            0,
        )
        disclosures = frame["manifest"]["feature_disclosures"]
        self.assertEqual(disclosures["pre_contact_lubrication_drainage"], "MODELED")
        self.assertEqual(
            disclosures["pre_contact_lubrication_pressure_feedback"],
            "MODELED",
        )
        self.assertEqual(
            disclosures["fully_coupled_multi_region_eulerian_cfd"],
            "NOT_IMPLEMENTED",
        )
        self.assertEqual(
            self.enabled_meta["contact_surgery"],
            "bubblelab.solvers.transient.contact.form_contact",
        )
        self.assertEqual(
            self.enabled_meta["post_contact_solver"],
            "bubblelab.solvers.transient.network.core.advance",
        )

    def test_precontact_step_reports_actual_mesh_geometry_and_conservation(self) -> None:
        active = []
        for frame in self.enabled_frames:
            diagnostics = frame.get("diagnostics", {}).get("pre_contact_lubrication")
            if not diagnostics or not diagnostics.get("step"):
                continue
            step = diagnostics["step"]
            if step["response"]["active"]:
                active.append(step)
        self.assertTrue(active)
        sample = active[-1]
        self.assertIn("triangulated", sample["geometry"]["source"])
        self.assertGreater(sample["geometry"]["effective_radius_m"], 0.0)
        self.assertGreater(sample["model_gap_m"], 0.0)
        self.assertGreater(sample["separation_correction_m"], 0.0)
        self.assertLessEqual(
            sample["conservation"]["max_closed_bubble_volume_relative_change"],
            5.0e-12,
        )
        self.assertEqual(
            sample["conservation"]["gap_continuity_residual_m3_s"],
            0.0,
        )


if __name__ == "__main__":
    unittest.main()
