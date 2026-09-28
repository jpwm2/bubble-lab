from __future__ import annotations

import unittest

from bubblelab.solvers.contact_lubrication import GapGeometry
from bubblelab.solvers.precontact_cfd import (
    PrecontactCFDSettings,
    coupled_cfd_response,
    solve_thin_gap_field,
    taylor_reference_force_n,
)


def _geometry(gap_m: float = 2.0e-4) -> GapGeometry:
    return GapGeometry(
        parent_ids=("bubble-a", "bubble-b"),
        anchor_vertex_indices=(0, 0),
        normal_a_to_b=(0.0, 0.0, 1.0),
        gap_m=gap_m,
        local_radius_a_m=1.0e-2,
        local_radius_b_m=1.0e-2,
        effective_radius_m=5.0e-3,
        local_curvature_a_1_m=200.0,
        local_curvature_b_1_m=200.0,
        mesh_resolution_m=5.0e-4,
        geometry_source="manufactured triangulated local geometry",
    )


class PrecontactCFDTests(unittest.TestCase):
    def test_discretized_pressure_velocity_field_enforces_no_slip_and_mass_balance(self) -> None:
        geometry = _geometry()
        settings = PrecontactCFDSettings(radial_cells=48, gap_cells=16)
        field = solve_thin_gap_field(geometry, 0.12, 1.825e-5, settings)
        self.assertEqual(len(field.pressure_pa), settings.radial_cells)
        self.assertEqual(
            len(field.radial_velocity_faces_m_s), settings.radial_cells + 1
        )
        self.assertTrue(all(value >= 0.0 for value in field.pressure_pa))
        self.assertGreater(field.center_pressure_pa, 0.0)
        self.assertGreater(field.pressure_force_n, 0.0)
        self.assertGreater(field.max_radial_velocity_m_s, 0.0)
        self.assertGreater(field.max_wall_shear_pa, 0.0)
        self.assertEqual(field.max_wall_slip_m_s, 0.0)
        self.assertLess(field.mass_balance_relative_residual, 1.0e-11)
        self.assertLess(field.max_pressure_equation_residual_m3_s, 1.0e-15)
        self.assertAlmostEqual(
            field.lower_wall_normal_velocity_m_s, 0.06, places=14
        )
        self.assertAlmostEqual(
            field.upper_wall_normal_velocity_m_s, -0.06, places=14
        )

    def test_refinement_converges_toward_taylor_thin_gap_reference(self) -> None:
        geometry = _geometry()
        reference = taylor_reference_force_n(
            5.0e-3, 2.0e-4, 0.12, 1.825e-5
        )
        errors = []
        for radial_cells, gap_cells in ((12, 8), (24, 12), (48, 16), (96, 32)):
            field = solve_thin_gap_field(
                geometry,
                0.12,
                1.825e-5,
                PrecontactCFDSettings(
                    radial_cells=radial_cells,
                    gap_cells=gap_cells,
                ),
            )
            errors.append(abs(field.pressure_force_n - reference) / reference)
        self.assertTrue(
            all(later < earlier for earlier, later in zip(errors, errors[1:]))
        )
        self.assertLess(errors[-1], 0.003)

    def test_coupled_feedback_uses_numerically_integrated_traction(self) -> None:
        geometry = _geometry()
        settings = PrecontactCFDSettings(
            onset_gap_over_effective_radius=1.0,
            radial_cells=48,
            gap_cells=16,
        )
        response = coupled_cfd_response(
            geometry, 0.18, 1.825e-5, settings
        )
        self.assertTrue(response.active)
        self.assertIsNotNone(response.field)
        assert response.field is not None
        self.assertLess(
            response.coupled_closing_speed_m_s,
            response.free_closing_speed_m_s,
        )
        self.assertGreater(response.correction_speed_m_s, 0.0)
        self.assertGreater(response.cfd_resistance_n_s_m, 0.0)
        self.assertAlmostEqual(
            response.force_n, response.field.pressure_force_n, places=18
        )
        self.assertAlmostEqual(
            response.cfd_resistance_n_s_m,
            response.field.pressure_force_n
            / response.coupled_closing_speed_m_s,
            delta=0.02 * response.cfd_resistance_n_s_m,
        )
        self.assertNotIn("TAYLOR", response.model)

    def test_inactive_gap_does_not_construct_a_synthetic_field(self) -> None:
        geometry = _geometry(gap_m=4.0e-3)
        response = coupled_cfd_response(
            geometry,
            0.1,
            1.825e-5,
            PrecontactCFDSettings(onset_gap_over_effective_radius=0.5),
        )
        self.assertFalse(response.active)
        self.assertIsNone(response.field)
        self.assertEqual(response.force_n, 0.0)
        self.assertEqual(
            response.coupled_closing_speed_m_s,
            response.free_closing_speed_m_s,
        )


if __name__ == "__main__":
    unittest.main()
