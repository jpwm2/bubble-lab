from __future__ import annotations

from dataclasses import replace
import unittest

from bubblelab.solvers.events.fragmentation import NeckCriteria, diagnose_neck, necked_mesh
from bubblelab.solvers.events.pinchoff import PinchOffConfig, deform_x_axisymmetric_mesh, evolve_neck


class PinchOffSolverTests(unittest.TestCase):
    def test_neck_evolves_in_time_and_conserves_volume(self) -> None:
        result = evolve_neck()
        self.assertEqual(result.stop_reason, "RESOLUTION_LIMIT_REACHED")
        self.assertLess(result.final_minimum_radius_m, 0.40 * result.initial_minimum_radius_m)
        self.assertGreater(result.pinch_time_s, result.last_resolved_time_s)
        self.assertLess(result.terminal_fit_slope_m_s, 0.0)
        self.assertGreater(max(sample.maximum_axial_speed_m_s for sample in result.samples), 0.1)
        self.assertLessEqual(result.volume_relative_error, 2.0e-12)

    def test_repeat_is_bitwise_deterministic_at_result_level(self) -> None:
        first = evolve_neck()
        second = evolve_neck()
        self.assertEqual(first.solver_digest, second.solver_digest)
        self.assertEqual(first.pinch_time_s, second.pinch_time_s)
        self.assertEqual(first.final_radius_m, second.final_radius_m)
        self.assertEqual(first.final_axial_velocity_m_s, second.final_axial_velocity_m_s)

    def test_refinement_reduces_time_and_trajectory_changes(self) -> None:
        base = PinchOffConfig()
        runs = [evolve_neck(replace(base, cell_count=count)) for count in (33, 49, 65)]
        time_changes = (
            abs(runs[0].pinch_time_s - runs[1].pinch_time_s),
            abs(runs[1].pinch_time_s - runs[2].pinch_time_s),
        )
        self.assertLess(time_changes[1], time_changes[0])
        self.assertLess(time_changes[1], 0.10)
        probe = 0.50
        radii = [min(run.samples, key=lambda sample: abs(sample.time_s - probe)).minimum_radius_m for run in runs]
        self.assertLess(abs(radii[1] - radii[2]), abs(radii[0] - radii[1]))

    def test_evolved_parent_mesh_remains_split_eligible(self) -> None:
        config = PinchOffConfig()
        result = evolve_neck(config)
        parent = necked_mesh(
            half_length=config.parent_half_length_m,
            minor_radius=config.base_radius_m,
            neck_depth=config.neck_depth,
            neck_width=config.neck_width_m,
            asymmetry=0.0,
            axial_segments=64,
            circum_segments=72,
        )
        projection = deform_x_axisymmetric_mesh(parent, result, patch_half_length_m=config.patch_half_length_m)
        self.assertTrue(projection.mesh.is_closed_manifold())
        self.assertLessEqual(projection.corrected_volume_relative_error, 2.0e-12)
        diagnostic = diagnose_neck(projection.mesh, NeckCriteria())
        self.assertTrue(diagnostic.detected)
        self.assertTrue(diagnostic.eligible, diagnostic.rejection_reason)
        self.assertIsNotNone(diagnostic.neck_radius)
        self.assertGreater(float(diagnostic.radius_to_spacing or 0.0), 0.70)


if __name__ == "__main__":
    unittest.main()
