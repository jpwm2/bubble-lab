from __future__ import annotations

import copy
import unittest

from bubblelab.runtime.multiregion_cfd_runtime import (
    replay_signature,
    run_multiregion_precontact_cfd,
)


def _scenario() -> dict:
    return {
        "domain": {
            "cells": 10,
            "extent_m": 0.024,
            "pressure_iterations": 70,
            "pressure_tolerance_s_inv": 6.0e-6,
        },
        "bubbles": {
            "radius_m": 0.003,
            "initial_gap_m": 0.0055,
            "subdivisions": 1,
        },
        "materials": {
            "exterior": {
                "density_kg_m3": 1.204,
                "dynamic_viscosity_pa_s": 1.825e-5,
            },
            "interior": {
                "density_kg_m3": 1.05,
                "dynamic_viscosity_pa_s": 1.65e-5,
            },
        },
        "coupling": {
            "global_enabled": True,
            "free_closing_speed_m_s": 0.05,
            "outer_resistance_n_s_m": 1.5e-6,
            "nominal_dt_s": 0.03,
            "global_handoff_gap_cells": 1.5,
            "contact_gap_m": 2.0e-4,
            "max_steps": 24,
            "global_field": {
                "pseudo_steps": 2,
                "viscous_cfl": 0.08,
                "constraint_relaxation": 0.85,
                "minimum_gap_cells": 1.2,
                "traction_offset_cells": 0.8,
                "gradient_step_cells": 0.5,
                "maximum_sphericity_error": 0.12,
                "minimum_constraint_cells_per_front": 8,
            },
            "local_handoff": {
                "minimum_gap_m": 1.0e-7,
                "radial_cells": 16,
                "gap_cells": 6,
                "radial_extent_over_sqrt_2rh": 40.0,
                "radial_stretch": 4.0,
            },
        },
    }


class MultiregionCFDRuntimeTests(unittest.TestCase):
    def test_global_field_delays_same_local_handoff_contact(self) -> None:
        scenario = _scenario()
        coupled = run_multiregion_precontact_cfd(
            copy.deepcopy(scenario),
            global_enabled=True,
        )
        control = run_multiregion_precontact_cfd(
            copy.deepcopy(scenario),
            global_enabled=False,
        )
        self.assertGreater(coupled["summary"]["global_activation_count"], 0)
        self.assertGreater(coupled["summary"]["local_handoff_activation_count"], 0)
        self.assertGreater(
            coupled["summary"]["contact_time_s"],
            control["summary"]["contact_time_s"],
        )
        self.assertLess(
            coupled["summary"]["max_closed_bubble_volume_relative_error"],
            1.0e-11,
        )
        self.assertEqual(
            coupled["manifest"]["feature_disclosures"][
                "general_simultaneous_multigap_cfd"
            ],
            "NOT_IMPLEMENTED",
        )

    def test_runtime_replay_is_exact(self) -> None:
        first = run_multiregion_precontact_cfd(_scenario(), global_enabled=True)
        second = run_multiregion_precontact_cfd(_scenario(), global_enabled=True)
        self.assertEqual(replay_signature(first), replay_signature(second))


if __name__ == "__main__":
    unittest.main()
