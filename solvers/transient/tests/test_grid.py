from __future__ import annotations

import math
import unittest

from bubblelab.solvers.transient.geometry import icosphere, norm
from bubblelab.solvers.transient.grid import EulerianGasGrid, GridConfig, RegionProperties


class EulerianGridTests(unittest.TestCase):
    def setUp(self):
        self.grid = EulerianGasGrid(GridConfig(cells=(8, 8, 8), origin_m=(-0.5, -0.5, -0.5), extent_m=(1.0, 1.0, 1.0), pressure_iterations=160, pressure_tolerance_s_inv=1e-10))

    def test_cloud_in_cell_spread_conserves_integrated_force(self):
        front = icosphere(radius_m=0.2, subdivisions=1, surface_tension_n_m=0.05)
        forces = front.capillary_vertex_forces()
        spread = self.grid.spread_vertex_forces(front.vertices, forces)
        total_front = tuple(sum(f[a] for f in forces) for a in range(3))
        total_grid = self.grid.total_integrated_force(spread)
        for a, b in zip(total_front, total_grid):
            self.assertAlmostEqual(a, b, places=13)

    def test_projection_reduces_divergence(self):
        for q in range(len(self.grid.u)):
            i, j, k = self.grid._ijk(q)
            x, y, z = self.grid.cell_center(i, j, k)
            self.grid.u[q] = math.sin(2.0 * math.pi * x)
            self.grid.v[q] = 0.3 * math.sin(2.0 * math.pi * y)
            self.grid.w[q] = -0.2 * math.cos(2.0 * math.pi * z)
        before = self.grid.divergence_linf()
        fields = self.grid.project((self.grid.u, self.grid.v, self.grid.w), 0.01)
        self.grid.u, self.grid.v, self.grid.w = fields
        after = self.grid.divergence_linf()
        self.assertGreater(before, 1.0)
        self.assertLess(after, 1.0e-9)

    def test_uniform_background_wind_is_interpolated_exactly(self):
        grid = EulerianGasGrid(GridConfig(background_velocity_m_s=(0.2, -0.1, 0.05)))
        self.assertEqual(grid.sample_velocity((0.001, -0.002, 0.003)), (0.2, -0.1, 0.05))

    def test_region_properties_populate_density_viscosity_and_jump_potential(self):
        labels = ["bubble-1" if q % 2 == 0 else "EXTERIOR" for q in range(len(self.grid.u))]
        self.grid.configure_regions(
            labels,
            {"bubble-1": RegionProperties(0.8, 1.0e-5)},
            {"bubble-1": 12.5},
        )
        self.assertEqual(min(self.grid.density), 0.8)
        self.assertEqual(max(self.grid.density), self.grid.config.density_kg_m3)
        self.assertEqual(min(self.grid.dynamic_viscosity), 1.0e-5)
        self.assertIn(12.5, self.grid.capillary_pressure_potential)
        self.assertIn(0.0, self.grid.capillary_pressure_potential)


if __name__ == "__main__":
    unittest.main()
