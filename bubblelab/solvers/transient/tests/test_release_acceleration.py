from __future__ import annotations

import math
import unittest

from bubblelab.solvers.transient.amr import AMRConfig, AdaptiveEulerianGasGrid
from bubblelab.solvers.transient.geometry import FilmFront, icosphere
from bubblelab.solvers.transient.grid import EulerianGasGrid, GridConfig
from bubblelab.solvers.transient.release_acceleration import (
    AccelerationPolicy,
    AcceleratedTransientSoapFilmSolver,
    ReleaseAdaptiveEulerianGasGrid,
    classify_regions_ray_exact,
)
from bubblelab.solvers.transient.solver import (
    TimeStepPolicy,
    TransientConfig,
    TransientSoapFilmSolver,
    _solid_angle_contains,
)


def _rotate(front: FilmFront) -> FilmFront:
    axis = (1.0, 2.0, 3.0)
    n = math.sqrt(sum(x * x for x in axis))
    ax = tuple(x / n for x in axis)
    angle = 0.431
    c = math.cos(angle)
    s = math.sin(angle)
    ux, uy, uz = ax

    def apply(p):
        x, y, z = p
        dot = ux * x + uy * y + uz * z
        cross = (uy * z - uz * y, uz * x - ux * z, ux * y - uy * x)
        return (
            x * c + cross[0] * s + ux * dot * (1.0 - c),
            y * c + cross[1] * s + uy * dot * (1.0 - c),
            z * c + cross[2] * s + uz * dot * (1.0 - c),
        )

    return FilmFront(
        bubble_id=front.bubble_id,
        mesh_id=front.mesh_id,
        film_id=front.film_id,
        vertices=[apply(p) for p in front.vertices],
        faces=list(front.faces),
        surface_tension_n_m=front.surface_tension_n_m,
    )


class ReleaseAccelerationTests(unittest.TestCase):
    def test_ray_classifier_matches_accepted_solid_angle_predicate(self):
        front = _rotate(icosphere(radius_m=0.008, subdivisions=1))
        grid = EulerianGasGrid(
            GridConfig(
                cells=(10, 10, 10),
                origin_m=(-0.02, -0.02, -0.02),
                extent_m=(0.04, 0.04, 0.04),
            )
        )
        accelerated = classify_regions_ray_exact(grid, [front])
        reference = []
        for q in range(len(accelerated)):
            p = grid.cell_center(*grid._ijk(q))
            reference.append(front.bubble_id if _solid_angle_contains(front, p) else "EXTERIOR")
        self.assertEqual(accelerated, reference)

    def test_triangle_neighborhood_amr_marking_preserves_hierarchy(self):
        front = _rotate(icosphere(radius_m=0.008, subdivisions=1))
        grid_config = GridConfig(
            cells=(6, 6, 6),
            origin_m=(-0.02, -0.02, -0.02),
            extent_m=(0.04, 0.04, 0.04),
        )
        amr = AMRConfig(enabled=True, max_levels=2, front_band_cells=0.90)
        reference = AdaptiveEulerianGasGrid(grid_config, amr)
        accelerated = ReleaseAdaptiveEulerianGasGrid(grid_config, amr)
        reference.regrid([front])
        accelerated.regrid([front])
        self.assertEqual(reference.hierarchy_signature(), accelerated.hierarchy_signature())

    def test_zero_dynamic_step_matches_reference_operator(self):
        front = icosphere(radius_m=0.008, subdivisions=1, surface_tension_n_m=0.05)
        config = TransientConfig(
            grid=GridConfig(
                cells=(8, 8, 8),
                origin_m=(-0.02, -0.02, -0.02),
                extent_m=(0.04, 0.04, 0.04),
                pressure_tolerance_s_inv=1.0e-10,
            ),
            timestep=TimeStepPolicy(max_dt_s=1.0e-5, capillary_safety=0.05),
        )
        reference = TransientSoapFilmSolver([front], config)
        accelerated = AcceleratedTransientSoapFilmSolver([front], config)
        dt = min(reference.select_timestep(), accelerated.select_timestep())
        ref_diag = reference.step(dt)
        acc_diag = accelerated.step(dt)
        radius = front.equivalent_radius()
        max_vertex_error = max(
            math.dist(a, b)
            for a, b in zip(reference.fronts[0].vertices, accelerated.fronts[0].vertices)
        ) / radius
        self.assertLessEqual(max_vertex_error, 2.0e-13)
        self.assertLessEqual(
            abs(reference.pressure_jump_pa(front.bubble_id) - accelerated.pressure_jump_pa(front.bubble_id)),
            2.0e-12,
        )
        self.assertLessEqual(abs(ref_diag.max_speed_m_s - acc_diag.max_speed_m_s), 1.0e-14)
        self.assertLessEqual(abs(ref_diag.max_relative_volume_error - acc_diag.max_relative_volume_error), 2.0e-13)

    def test_static_fixed_point_fast_forward_is_proof_gated(self):
        front = icosphere(radius_m=0.008, subdivisions=0, surface_tension_n_m=0.05)
        config = TransientConfig(
            grid=GridConfig(cells=(8, 8, 8)),
            timestep=TimeStepPolicy(max_dt_s=1.0e-5, capillary_safety=0.05),
        )
        solver = AcceleratedTransientSoapFilmSolver(
            [front], config, AccelerationPolicy(proof_steps=3, operator_tolerance=2.0e-13)
        )
        dt = solver.select_timestep()
        solver.run_to_time(9.0 * dt)
        events = [e for e in solver.acceleration_events if e["mode"] == "exact_fixed_point"]
        self.assertEqual(len(events), 1)
        self.assertGreaterEqual(int(events[0]["physical_steps_elided"]), 1)
        self.assertEqual(solver.step_index, 9)
        self.assertAlmostEqual(solver.time_s, 9.0 * dt, places=15)
        self.assertGreaterEqual(len(solver.history), 3)

    def test_fixed_point_can_be_disabled_for_orientation_runs(self):
        front = _rotate(icosphere(radius_m=0.008, subdivisions=0, surface_tension_n_m=0.05))
        config = TransientConfig(
            grid=GridConfig(cells=(8, 8, 8)),
            timestep=TimeStepPolicy(max_dt_s=1.0e-5, capillary_safety=0.05),
        )
        solver = AcceleratedTransientSoapFilmSolver(
            [front], config, AccelerationPolicy(fixed_point_enabled=False)
        )
        dt = solver.select_timestep()
        solver.run_to_time(5.0 * dt, allow_fixed_point=False)
        self.assertEqual(solver.step_index, 5)
        self.assertEqual(len(solver.history), 5)
        self.assertFalse(any(e["mode"] == "exact_fixed_point" for e in solver.acceleration_events))

    def test_uniform_background_reuses_eulerian_state_without_time_skip(self):
        front = icosphere(radius_m=0.004, subdivisions=0, surface_tension_n_m=0.0)
        velocity = (0.1, 0.0, 0.0)
        config = TransientConfig(
            grid=GridConfig(
                cells=(8, 8, 8),
                origin_m=(-0.02, -0.02, -0.02),
                extent_m=(0.04, 0.04, 0.04),
                dynamic_viscosity_pa_s=0.0,
                background_velocity_m_s=velocity,
            ),
            timestep=TimeStepPolicy(max_dt_s=1.0e-3),
        )
        solver = AcceleratedTransientSoapFilmSolver([front], config)
        initial = solver.fronts[0].centroid()
        dt = solver.select_timestep()
        target = 4.0 * dt
        solver.run_to_time(target)
        final = solver.fronts[0].centroid()
        self.assertAlmostEqual(final[0] - initial[0], velocity[0] * target, places=13)
        self.assertEqual(solver.step_index, 4)
        events = [e for e in solver.acceleration_events if e["mode"] == "exact_uniform_background_eulerian_reuse"]
        self.assertEqual(len(events), 1)
        self.assertEqual(float(events[0]["physical_time_elided_s"]), 0.0)
        self.assertEqual(int(events[0]["physical_steps_executed"]), 4)


if __name__ == "__main__":
    unittest.main()
