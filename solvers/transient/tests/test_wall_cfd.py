from __future__ import annotations

import math
import unittest

from bubblelab.solvers.boundary import PlaneBoundary
from bubblelab.solvers.transient.amr import AMRConfig, AdaptiveEulerianGasGrid
from bubblelab.solvers.transient.geometry import icosphere
from bubblelab.solvers.transient.grid import EulerianGasGrid, GridConfig, RegionProperties
from bubblelab.solvers.transient.solver import TransientConfig, TransientSoapFilmSolver


def channel_grid(n: int = 8, top_speed: float = 0.0, nu: float = 0.1) -> EulerianGasGrid:
    h = 1.0 / n
    grid = EulerianGasGrid(
        GridConfig(
            cells=(4, n + 2, 4),
            origin_m=(-2.0 * h, -h, -2.0 * h),
            extent_m=(4.0 * h, (n + 2) * h, 4.0 * h),
            density_kg_m3=1.0,
            dynamic_viscosity_pa_s=nu,
            pressure_iterations=500,
            pressure_tolerance_s_inv=1.0e-10,
        )
    )
    grid.configure_solid_walls(
        (
            PlaneBoundary(
                boundary_id="bottom",
                point_m=(0.0, 0.0, 0.0),
                normal_outward=(0.0, 1.0, 0.0),
            ),
            PlaneBoundary(
                boundary_id="top",
                wall_velocity_m_s=(top_speed, 0.0, 0.0),
                point_m=(0.0, 1.0, 0.0),
                normal_outward=(0.0, -1.0, 0.0),
            ),
        )
    )
    return grid


class ResolvedWallCFDTests(unittest.TestCase):
    def test_stationary_wall_viscous_term_constrains_tangential_components(self):
        grid = channel_grid()
        wall = grid.resolved_walls
        self.assertIsNotNone(wall)
        assert wall is not None
        for q in wall.fluid_indices:
            grid.u[q] = 1.0
            grid.w[q] = -0.5
        grid.apply_solid_wall_constraints()
        du = grid._variable_viscous_term(grid.u, 0)
        dw = grid._variable_viscous_term(grid.w, 2)
        near_bottom = min(
            wall.fluid_indices,
            key=lambda q: grid.cell_center(*grid._ijk(q))[1],
        )
        self.assertLess(du[near_bottom], 0.0)
        self.assertGreater(dw[near_bottom], 0.0)

    def test_moving_wall_couette_profile_is_preserved(self):
        grid = channel_grid(n=16, top_speed=1.0)
        wall = grid.resolved_walls
        assert wall is not None
        for q in wall.fluid_indices:
            y = grid.cell_center(*grid._ijk(q))[1]
            grid.u[q] = y
        grid.apply_solid_wall_constraints()
        dt = 0.05 * grid.h * grid.h / grid.config.dynamic_viscosity_pa_s
        zero = [0.0] * len(grid.u)
        grid.advance(dt, (zero, zero, zero), (0.0, 0.0, 0.0))
        for q in wall.fluid_indices:
            y = grid.cell_center(*grid._ijk(q))[1]
            self.assertAlmostEqual(grid.u[q], y, places=12)
        self.assertLess(grid.divergence_linf(), 1.0e-9)

    def test_poiseuille_balance_uses_wall_dirichlet_viscosity(self):
        nu = 0.1
        acceleration = 0.25
        grid = channel_grid(n=16, nu=nu)
        wall = grid.resolved_walls
        assert wall is not None
        analytic = lambda y: acceleration * y * (1.0 - y) / (2.0 * nu)
        for q in wall.fluid_indices:
            y = grid.cell_center(*grid._ijk(q))[1]
            grid.u[q] = analytic(y)
        grid.apply_solid_wall_constraints()
        viscous = grid._variable_viscous_term(grid.u, 0)
        for q in wall.fluid_indices:
            self.assertAlmostEqual(viscous[q], -acceleration, places=11)

    def test_wall_aware_projection_removes_fluid_divergence(self):
        grid = channel_grid()
        wall = grid.resolved_walls
        assert wall is not None
        for q in wall.fluid_indices:
            x, y, z = grid.cell_center(*grid._ijk(q))
            grid.u[q] = math.sin(2.0 * math.pi * x) + 0.2 * y
            grid.v[q] = 0.3 * math.sin(math.pi * y)
            grid.w[q] = 0.1 * math.cos(2.0 * math.pi * z)
        grid.apply_solid_wall_constraints()
        before = grid.divergence_linf()
        grid.u, grid.v, grid.w = grid.project((grid.u, grid.v, grid.w), 0.01)
        self.assertGreater(before, 1.0)
        self.assertLess(grid.divergence_linf(), 1.0e-8)

    def test_region_specific_properties_remain_active_with_wall_stencil(self):
        grid = channel_grid()
        wall = grid.resolved_walls
        assert wall is not None
        labels = ["EXTERIOR"] * len(grid.u)
        for q in wall.fluid_indices[::2]:
            labels[q] = "bubble"
        grid.configure_regions(labels, {"bubble": RegionProperties(0.8, 0.05)})
        grid.configure_solid_walls(wall.boundaries)
        self.assertIn(0.8, grid.density)
        self.assertIn(0.05, grid.dynamic_viscosity)
        self.assertTrue(all(math.isfinite(x) for x in grid._variable_viscous_term(grid.u, 0)))

    def test_solver_installs_walls_on_uniform_and_amr_levels(self):
        h = 0.125
        grid_config = GridConfig(
            cells=(8, 10, 8),
            origin_m=(-0.5, -h, -0.5),
            extent_m=(1.0, 1.25, 1.0),
            density_kg_m3=1.0,
            dynamic_viscosity_pa_s=0.01,
        )
        walls = (
            PlaneBoundary(
                boundary_id="bottom",
                point_m=(0.0, 0.0, 0.0),
                normal_outward=(0.0, 1.0, 0.0),
            ),
            PlaneBoundary(
                boundary_id="top",
                point_m=(0.0, 1.0, 0.0),
                normal_outward=(0.0, -1.0, 0.0),
            ),
        )
        front = icosphere(
            radius_m=0.15,
            center_m=(0.0, 0.5, 0.0),
            subdivisions=1,
            bubble_id="bubble",
            surface_tension_n_m=0.02,
        )
        solver = TransientSoapFilmSolver(
            [front], TransientConfig(grid=grid_config, solid_boundaries=walls)
        )
        self.assertIsNotNone(solver.grid.resolved_walls)

        amr_solver = TransientSoapFilmSolver(
            [front],
            TransientConfig(
                grid=grid_config,
                amr=AMRConfig(enabled=True, max_levels=1),
                solid_boundaries=walls,
            ),
        )
        self.assertIsInstance(amr_solver.grid, AdaptiveEulerianGasGrid)
        self.assertTrue(
            all(grid.resolved_walls is not None for grid in amr_solver.grid.level_grids())
        )


if __name__ == "__main__":
    unittest.main()
