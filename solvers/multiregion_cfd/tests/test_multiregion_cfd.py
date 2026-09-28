from __future__ import annotations

import unittest

from bubblelab.solvers.multiregion_cfd import (
    MultiregionCFDSettings,
    build_supported_two_bubble_solver,
    coupled_global_response,
    solve_global_precontact_field,
)


class MultiregionCFDTests(unittest.TestCase):
    def settings(self) -> MultiregionCFDSettings:
        return MultiregionCFDSettings(
            pseudo_steps=3,
            viscous_cfl=0.08,
            constraint_relaxation=0.85,
            minimum_gap_cells=1.2,
            traction_offset_cells=0.8,
            gradient_step_cells=0.5,
            maximum_sphericity_error=0.12,
            minimum_constraint_cells_per_front=8,
        )

    def solver(self):
        return build_supported_two_bubble_solver(
            cells=10,
            extent_m=0.024,
            radius_m=0.003,
            gap_m=0.005,
            subdivisions=1,
            pressure_iterations=80,
            pressure_tolerance_s_inv=5.0e-6,
        )

    def test_global_field_is_spatial_and_multiregion(self) -> None:
        result = solve_global_precontact_field(
            self.solver(),
            0.05,
            self.settings(),
        )
        counts = dict(result.region_cell_counts)
        self.assertGreater(counts.get("EXTERIOR", 0), 0)
        self.assertGreater(counts.get("bubble-a", 0), 0)
        self.assertGreater(counts.get("bubble-b", 0), 0)
        self.assertGreater(result.pressure_linf_pa, 0.0)
        self.assertGreater(result.resisting_force_n, 0.0)
        self.assertGreater(len(result.centerline_pressure_samples), 4)
        self.assertLess(result.mass_balance_relative_residual, 0.25)

    def test_field_traction_reduces_authoritative_pair_speed(self) -> None:
        response = coupled_global_response(
            self.solver(),
            free_closing_speed_m_s=0.05,
            outer_resistance_n_s_m=1.5e-6,
            settings=self.settings(),
        )
        self.assertGreater(response.resolved_cfd_resistance_n_s_m, 0.0)
        self.assertGreater(response.free_closing_speed_m_s, response.coupled_closing_speed_m_s)
        self.assertGreater(response.production_field.pressure_linf_pa, 0.0)
        self.assertGreater(response.production_field.resisting_force_n, 0.0)

    def test_same_build_replay_is_exact(self) -> None:
        first = coupled_global_response(
            self.solver(),
            0.04,
            1.5e-6,
            self.settings(),
        ).as_dict()
        second = coupled_global_response(
            self.solver(),
            0.04,
            1.5e-6,
            self.settings(),
        ).as_dict()
        self.assertEqual(first, second)

    def test_underresolved_gap_is_rejected(self) -> None:
        solver = build_supported_two_bubble_solver(
            cells=10,
            extent_m=0.024,
            radius_m=0.003,
            gap_m=0.001,
            subdivisions=1,
            pressure_iterations=60,
        )
        with self.assertRaisesRegex(ValueError, "resolved support limit"):
            solve_global_precontact_field(
                solver,
                0.04,
                MultiregionCFDSettings(
                    pseudo_steps=2,
                    minimum_gap_cells=1.1,
                ),
            )


if __name__ == "__main__":
    unittest.main()
