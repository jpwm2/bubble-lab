from __future__ import annotations

import unittest

from bubblelab.solvers.multiregion_cfd import (
    MultigapCFDSettings,
    MultiregionCFDSettings,
    build_supported_three_bubble_solver,
    coupled_multigap_response,
    solve_multigap_precontact_field,
)


FREE_VELOCITIES = {
    "bubble-a": (0.028, 0.0, 0.0),
    "bubble-b": (0.002, 0.0, 0.0),
    "bubble-c": (-0.030, 0.0, 0.0),
}


class MultigapManyBubbleCFDTests(unittest.TestCase):
    def settings(self, pseudo_steps: int = 3) -> MultigapCFDSettings:
        return MultigapCFDSettings(
            field=MultiregionCFDSettings(
                pseudo_steps=pseudo_steps,
                viscous_cfl=0.08,
                constraint_relaxation=0.85,
                minimum_gap_cells=1.5,
                traction_offset_cells=0.8,
                gradient_step_cells=0.5,
                maximum_sphericity_error=0.12,
                minimum_constraint_cells_per_front=8,
            ),
            feedback_iterations=2,
            feedback_relaxation=0.30,
        )

    def solver(self, *, order=("bubble-a", "bubble-b", "bubble-c")):
        return build_supported_three_bubble_solver(
            cells=13,
            extent_m=0.030,
            radius_m=0.0022,
            left_gap_m=0.0064,
            right_gap_m=0.0060,
            subdivisions=1,
            pressure_iterations=70,
            pressure_tolerance_s_inv=6.0e-6,
            front_order=order,
        )

    def test_one_field_contains_three_regions_two_gaps_and_three_tractions(self) -> None:
        result = solve_multigap_precontact_field(
            self.solver(), FREE_VELOCITIES, self.settings()
        )
        counts = dict(result.region_cell_counts)
        self.assertEqual(len(result.gaps), 2)
        self.assertEqual(len(result.tractions), 3)
        self.assertEqual(len(result.constraint_cell_counts), 3)
        self.assertGreater(result.pressure_linf_pa, 0.0)
        self.assertGreater(result.max_speed_m_s, 0.0)
        self.assertGreater(len(result.gap_pressure_samples), 1)
        for name in ("EXTERIOR", "bubble-a", "bubble-b", "bubble-c"):
            self.assertGreater(counts.get(name, 0), 0)

    def test_global_field_feedback_changes_multiple_front_velocities(self) -> None:
        response = coupled_multigap_response(
            self.solver(),
            FREE_VELOCITIES,
            outer_resistance_n_s_m=8.0e-6,
            settings=self.settings(),
        )
        coupled = dict(response.coupled_velocities_world)
        changed = [
            bubble_id
            for bubble_id, free in FREE_VELOCITIES.items()
            if abs(coupled[bubble_id][0] - free[0]) > 1.0e-6
        ]
        self.assertGreaterEqual(len(changed), 2)
        self.assertEqual(len(response.production_field.tractions), 3)
        self.assertGreater(response.production_field.pressure_linf_pa, 0.0)

    def test_front_container_permutation_does_not_change_physics(self) -> None:
        first = solve_multigap_precontact_field(
            self.solver(order=("bubble-a", "bubble-b", "bubble-c")),
            FREE_VELOCITIES,
            self.settings(),
        ).as_dict()
        second = solve_multigap_precontact_field(
            self.solver(order=("bubble-c", "bubble-a", "bubble-b")),
            FREE_VELOCITIES,
            self.settings(),
        ).as_dict()
        self.assertEqual(first, second)

    def test_underresolved_any_gap_is_rejected(self) -> None:
        solver = build_supported_three_bubble_solver(
            cells=10,
            extent_m=0.030,
            radius_m=0.0022,
            left_gap_m=0.0064,
            right_gap_m=0.0030,
            subdivisions=1,
            pressure_iterations=50,
        )
        with self.assertRaisesRegex(ValueError, "resolved support limit"):
            solve_multigap_precontact_field(
                solver,
                FREE_VELOCITIES,
                MultigapCFDSettings(
                    field=MultiregionCFDSettings(
                        pseudo_steps=2,
                        minimum_gap_cells=1.5,
                    ),
                    feedback_iterations=1,
                ),
            )


if __name__ == "__main__":
    unittest.main()
