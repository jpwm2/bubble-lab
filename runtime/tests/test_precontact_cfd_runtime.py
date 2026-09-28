from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from bubblelab.runtime.precontact_cfd_runtime import run_precontact_cfd_transition


SCENARIO = (
    Path(__file__).resolve().parents[2]
    / "scenarios"
    / "runtime"
    / "precontact-cfd-two-bubble.scenario.json"
)


def _contact_event(
    frames: list[dict[str, object]],
) -> tuple[dict[str, object], dict[str, object]]:
    matches: list[tuple[dict[str, object], dict[str, object]]] = []
    for frame in frames:
        topology = frame.get("topology") or {}
        if not isinstance(topology, dict):
            continue
        for event in topology.get("events", []):
            if (
                isinstance(event, dict)
                and event.get("transition_kind") == "CONTACT_FORMATION"
            ):
                matches.append((frame, event))
    if len(matches) != 1:
        raise AssertionError(
            f"expected one CONTACT_FORMATION, got {len(matches)}"
        )
    return matches[0]


class PrecontactCFDRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scenario = json.loads(SCENARIO.read_text(encoding="utf-8"))
        cls.cfd_frames, cls.cfd_meta = run_precontact_cfd_transition(
            cls.scenario,
            12,
        )
        disabled = copy.deepcopy(cls.scenario)
        contact = disabled["user_editable"]["contact_runtime"]
        contact["precontact_cfd"]["enabled"] = False
        contact["lubrication"]["enabled"] = False
        cls.disabled_frames, cls.disabled_meta = run_precontact_cfd_transition(
            disabled,
            12,
        )

    def test_resolved_numerical_traction_changes_authoritative_contact_timing(self) -> None:
        model = self.cfd_meta["pre_contact_cfd"]
        self.assertEqual(model["status"], "SUPPORTED_CLASS_RESOLVED")
        self.assertGreater(model["activation_count"], 0)
        self.assertGreater(model["max_center_pressure_pa"], 0.0)
        self.assertGreater(model["max_cfd_traction_force_n"], 0.0)
        self.assertLess(
            model["max_local_mass_balance_relative_residual"],
            1.0e-10,
        )
        self.assertLessEqual(model["max_wall_slip_m_s"], 1.0e-15)
        self.assertLessEqual(
            model["max_closed_bubble_volume_relative_change"],
            5.0e-12,
        )
        self.assertGreater(
            self.cfd_meta["contact_event_time_s"],
            self.disabled_meta["contact_event_time_s"],
        )
        self.assertIn("validation-only", model["production_traction_source"])

    def test_active_step_contains_solved_pressure_and_velocity_evidence(self) -> None:
        active = []
        for frame in self.cfd_frames:
            diagnostics = frame.get("diagnostics", {}).get("pre_contact_cfd")
            if not diagnostics or not diagnostics.get("step"):
                continue
            step = diagnostics["step"]
            if step["response"]["active"]:
                active.append(step)
        self.assertTrue(active)
        sample = active[-1]
        field = sample["response"]["field"]
        self.assertIsNotNone(field)
        self.assertIn("triangulated", sample["geometry"]["source"])
        self.assertGreater(sample["separation_correction_m"], 0.0)
        self.assertGreater(field["center_pressure_pa"], 0.0)
        self.assertGreater(field["max_radial_velocity_m_s"], 0.0)
        self.assertGreater(field["max_wall_shear_pa"], 0.0)
        self.assertEqual(field["max_wall_slip_m_s"], 0.0)
        self.assertLess(field["mass_balance_relative_residual"], 1.0e-10)
        self.assertGreater(len(field["pressure_profile_samples"]), 3)
        self.assertGreater(len(field["radial_velocity_profile_samples"]), 2)
        self.assertAlmostEqual(
            field["outer_radial_outflow_m3_s"],
            field["swept_gap_volume_rate_m3_s"],
            delta=1.0e-10
            * max(field["swept_gap_volume_rate_m3_s"], 1.0e-300),
        )

    def test_contact_handoff_keeps_global_claim_boundary_explicit(self) -> None:
        frame, event = _contact_event(self.cfd_frames)
        shared = [
            item
            for item in frame["film_regions"]
            if item.get("kind") == "SHARED"
        ]
        self.assertEqual(len(shared), 1)
        self.assertEqual(len(frame["junctions"]), 1)
        self.assertEqual(
            event["provenance"]["pre_contact_cfd_status"],
            "SUPPORTED_CLASS_RESOLVED",
        )
        self.assertGreater(
            event["provenance"]["pre_contact_cfd_history_steps"],
            0,
        )
        disclosures = frame["manifest"]["feature_disclosures"]
        self.assertEqual(
            disclosures["pre_contact_local_gap_resolved_cfd"],
            "MODELED",
        )
        self.assertEqual(
            disclosures["fully_coupled_multi_region_eulerian_cfd"],
            "NOT_IMPLEMENTED",
        )
        self.assertEqual(
            frame["manifest"]["provenance"][
                "pre_contact_cfd_global_multiregion_status"
            ],
            "NOT_IMPLEMENTED",
        )
        self.assertIn(
            "global full-domain multi-region Eulerian/Navier-Stokes gap coupling",
            self.cfd_meta["unsupported"],
        )
        self.assertEqual(
            self.cfd_meta["contact_surgery"],
            "bubblelab.solvers.transient.contact.form_contact",
        )


if __name__ == "__main__":
    unittest.main()
