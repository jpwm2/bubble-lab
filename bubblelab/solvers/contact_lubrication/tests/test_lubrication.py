from __future__ import annotations

import math
import unittest

from bubblelab.solvers.contact_lubrication import (
    GapGeometry,
    LubricationSettings,
    apply_pair_translation,
    coupled_response,
    measure_axis_gap_geometry,
    reynolds_sphere_pressure_pa,
    taylor_lubrication_force_n,
)
from bubblelab.solvers.transient.geometry import icosphere, norm, sub


class LubricationModelTests(unittest.TestCase):
    def test_reynolds_center_pressure_and_taylor_force(self) -> None:
        radius = 5.0e-3
        gap = 2.0e-4
        speed = 0.12
        viscosity = 1.825e-5
        expected_pressure = 3.0 * viscosity * speed * radius / gap**2
        expected_force = 6.0 * math.pi * viscosity * radius**2 * speed / gap
        self.assertAlmostEqual(
            reynolds_sphere_pressure_pa(radius, gap, speed, viscosity),
            expected_pressure,
            places=14,
        )
        self.assertAlmostEqual(
            taylor_lubrication_force_n(radius, gap, speed, viscosity),
            expected_force,
            places=14,
        )
        off_axis = reynolds_sphere_pressure_pa(
            radius, gap, speed, viscosity, radial_position_m=1.0e-3
        )
        self.assertGreater(expected_pressure, off_axis)
        self.assertGreater(off_axis, 0.0)

    def test_overdamped_resistance_matching_changes_approach_speed(self) -> None:
        radius = 5.0e-3
        gap = 1.0e-3
        geometry = GapGeometry(
            parent_ids=("a", "b"),
            anchor_vertex_indices=(0, 0),
            normal_a_to_b=(0.0, 0.0, 1.0),
            gap_m=gap,
            local_radius_a_m=1.0e-2,
            local_radius_b_m=1.0e-2,
            effective_radius_m=radius,
            local_curvature_a_1_m=200.0,
            local_curvature_b_1_m=200.0,
            mesh_resolution_m=1.0e-3,
            geometry_source="manufactured",
        )
        free_speed = 0.18
        response = coupled_response(
            geometry,
            free_speed,
            1.825e-5,
            LubricationSettings(onset_gap_over_effective_radius=1.0),
        )
        expected = free_speed / (1.0 + radius / gap)
        self.assertTrue(response.active)
        self.assertAlmostEqual(response.coupled_closing_speed_m_s, expected, places=14)
        self.assertGreater(response.force_n, 0.0)
        self.assertGreater(response.center_pressure_pa, 0.0)
        self.assertGreater(response.radial_drainage_rate_m3_s, 0.0)
        self.assertAlmostEqual(
            response.free_closing_speed_m_s,
            response.coupled_closing_speed_m_s + response.correction_speed_m_s,
            places=14,
        )

    def test_gap_geometry_is_measured_from_tracked_mesh(self) -> None:
        first = icosphere(
            radius_m=0.01,
            center_m=(0.0, 0.0, -0.011),
            subdivisions=2,
            bubble_id="bubble-a",
            surface_tension_n_m=0.05,
        )
        second = icosphere(
            radius_m=0.01,
            center_m=(0.0, 0.0, 0.011),
            subdivisions=2,
            bubble_id="bubble-b",
            surface_tension_n_m=0.05,
        )
        geometry = measure_axis_gap_geometry(first, second)
        self.assertEqual(geometry.parent_ids, ("bubble-a", "bubble-b"))
        self.assertGreater(geometry.gap_m, 0.0)
        self.assertGreater(geometry.effective_radius_m, 0.0)
        self.assertGreater(geometry.local_curvature_a_1_m, 0.0)
        self.assertGreater(geometry.local_curvature_b_1_m, 0.0)
        self.assertIn("triangulated", geometry.geometry_source)

    def test_equal_opposite_feedback_preserves_closed_gas_volume(self) -> None:
        first = icosphere(
            radius_m=0.01,
            center_m=(0.0, 0.0, -0.011),
            subdivisions=1,
            bubble_id="bubble-a",
            surface_tension_n_m=0.05,
        )
        second = icosphere(
            radius_m=0.01,
            center_m=(0.0, 0.0, 0.011),
            subdivisions=1,
            bubble_id="bubble-b",
            surface_tension_n_m=0.05,
        )
        geometry = measure_axis_gap_geometry(first, second)
        before_distance = norm(sub(second.centroid(), first.centroid()))
        before_volumes = (first.volume(), second.volume())
        errors = apply_pair_translation(
            [first, second], geometry, separation_correction_m=2.5e-4
        )
        after_distance = norm(sub(second.centroid(), first.centroid()))
        self.assertAlmostEqual(after_distance - before_distance, 2.5e-4, places=12)
        self.assertLessEqual(max(errors.values()), 5.0e-12)
        self.assertAlmostEqual(first.volume(), before_volumes[0], places=15)
        self.assertAlmostEqual(second.volume(), before_volumes[1], places=15)


if __name__ == "__main__":
    unittest.main()
