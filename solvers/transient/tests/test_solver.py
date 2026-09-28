from __future__ import annotations

import unittest

from bubblelab.solvers.transient import GridConfig, RegionProperties, TimeStepPolicy, TransientConfig, TransientSoapFilmSolver, icosphere
from bubblelab.solvers.transient.geometry import norm, sub


class SolverTests(unittest.TestCase):
    def test_background_wind_advects_front_without_renderer_kinematics(self):
        front = icosphere(radius_m=0.005, subdivisions=1, surface_tension_n_m=0.0)
        initial = front.centroid()
        config = TransientConfig(
            grid=GridConfig(cells=(8, 8, 8), origin_m=(-0.02, -0.02, -0.02), extent_m=(0.04, 0.04, 0.04), background_velocity_m_s=(0.1, 0.0, 0.0)),
            timestep=TimeStepPolicy(max_dt_s=1.0e-4),
        )
        solver = TransientSoapFilmSolver([front], config)
        solver.step(1.0e-4)
        moved = solver.fronts[0].centroid()
        self.assertAlmostEqual(moved[0] - initial[0], 1.0e-5, places=10)
        self.assertAlmostEqual(moved[1] - initial[1], 0.0, places=10)
        self.assertAlmostEqual(moved[2] - initial[2], 0.0, places=10)

    def test_closed_volume_is_conserved_by_front_projection(self):
        front = icosphere(radius_m=0.01, subdivisions=1, surface_tension_n_m=0.05)
        target = front.volume()
        solver = TransientSoapFilmSolver([front], TransientConfig(timestep=TimeStepPolicy(max_dt_s=5.0e-5, capillary_safety=0.05)))
        solver.step()
        self.assertLess(abs(solver.fronts[0].volume() - target) / target, 1.0e-12)
        self.assertLess(solver.history[-1].divergence_linf_s_inv, 1.0e-5)

    def test_replay_is_exact_for_identical_initial_state(self):
        front = icosphere(radius_m=0.008, subdivisions=1, surface_tension_n_m=0.04)
        config = TransientConfig(timestep=TimeStepPolicy(max_dt_s=5.0e-5, capillary_safety=0.05), deterministic_seed=9)
        a = TransientSoapFilmSolver([front], config)
        b = TransientSoapFilmSolver([front], config)
        for _ in range(2):
            a.step()
            b.step()
        self.assertEqual(a.replay_signature(), b.replay_signature())

    def test_gravity_hook_enters_bulk_and_front_motion(self):
        front = icosphere(radius_m=0.005, subdivisions=1, surface_tension_n_m=0.0)
        config = TransientConfig(
            grid=GridConfig(cells=(8, 8, 8), origin_m=(-0.02, -0.02, -0.02), extent_m=(0.04, 0.04, 0.04)),
            gravity_m_s2=(0.0, -1.0, 0.0),
            timestep=TimeStepPolicy(max_dt_s=1.0e-4),
        )
        solver = TransientSoapFilmSolver([front], config)
        before = solver.fronts[0].centroid()
        solver.step(1.0e-4)
        after = solver.fronts[0].centroid()
        self.assertLess(after[1], before[1])

    def test_sharp_pressure_jump_balances_static_sphere(self):
        front = icosphere(radius_m=0.008, subdivisions=2, surface_tension_n_m=0.05)
        config = TransientConfig(
            grid=GridConfig(
                cells=(8, 8, 8),
                origin_m=(-0.02, -0.02, -0.02),
                extent_m=(0.04, 0.04, 0.04),
                pressure_iterations=320,
                pressure_tolerance_s_inv=1.0e-10,
            ),
            timestep=TimeStepPolicy(max_dt_s=2.0e-5, capillary_safety=0.05),
        )
        solver = TransientSoapFilmSolver([front], config)
        diag = solver.step()
        target = solver.target_pressure_jump_pa(front.bubble_id)
        measured = solver.pressure_jump_pa(front.bubble_id)
        self.assertLess(abs(measured - target) / target, 2.0e-5)
        self.assertLess(diag.max_speed_m_s, 1.0e-7)

    def test_density_contrast_produces_upward_buoyancy_for_light_internal_gas(self):
        front = icosphere(radius_m=0.006, subdivisions=1, surface_tension_n_m=0.0)
        config = TransientConfig(
            grid=GridConfig(
                cells=(8, 8, 8),
                origin_m=(-0.02, -0.02, -0.02),
                extent_m=(0.04, 0.04, 0.04),
                pressure_iterations=320,
                pressure_tolerance_s_inv=1.0e-10,
            ),
            gravity_m_s2=(0.0, -9.81, 0.0),
            timestep=TimeStepPolicy(max_dt_s=2.0e-5),
            region_properties={front.bubble_id: RegionProperties(0.60, 1.2e-5)},
        )
        solver = TransientSoapFilmSolver([front], config)
        solver.step(2.0e-5)
        self.assertGreater(solver.bubble_velocity(front.bubble_id)[1], 0.0)


if __name__ == "__main__":
    unittest.main()
