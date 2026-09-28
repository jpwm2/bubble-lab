from __future__ import annotations

import unittest

from bubblelab.solvers.transient import (
    AMRConfig,
    AdaptiveEulerianGasGrid,
    GridConfig,
    TransientConfig,
    TransientSoapFilmSolver,
    icosphere,
)


class AdaptiveGridTests(unittest.TestCase):
    def _solver(self, levels: int = 2) -> TransientSoapFilmSolver:
        front = icosphere(radius_m=0.008, subdivisions=1, surface_tension_n_m=0.05)
        config = TransientConfig(
            grid=GridConfig(
                cells=(8, 8, 8),
                origin_m=(-0.02, -0.02, -0.02),
                extent_m=(0.04, 0.04, 0.04),
            ),
            amr=AMRConfig(enabled=True, max_levels=levels, front_band_cells=0.90),
        )
        return TransientSoapFilmSolver([front], config)

    def test_layout_is_deterministic_and_retains_coarse_far_field(self):
        a = self._solver()
        b = self._solver()
        self.assertIsInstance(a.grid, AdaptiveEulerianGasGrid)
        self.assertEqual(a.grid.hierarchy_signature(), b.grid.hierarchy_signature())
        counts = a.grid.active_cell_counts_by_level()
        self.assertGreaterEqual(len(a.grid.levels), 2)
        self.assertGreater(counts["0"], 0)
        self.assertGreater(counts[str(len(a.grid.levels) - 1)], 0)
        self.assertLess(a.grid.finest.h, a.grid.base.h)

    def test_constant_velocity_survives_prolong_restrict_cycle(self):
        solver = self._solver()
        grid = solver.grid
        self.assertIsInstance(grid, AdaptiveEulerianGasGrid)
        constants = (0.125, -0.25, 0.5)
        grid.base.u = [constants[0]] * len(grid.base.u)
        grid.base.v = [constants[1]] * len(grid.base.v)
        grid.base.w = [constants[2]] * len(grid.base.w)
        grid.prolong_all()
        grid.restrict_all()
        grid.prolong_all()
        for level in grid.levels:
            for expected, field in zip(constants, (level.grid.u, level.grid.v, level.grid.w)):
                self.assertLess(max(abs(value - expected) for value in field), 1.0e-14)

    def test_sampling_selects_finest_covering_level(self):
        solver = self._solver(levels=1)
        grid = solver.grid
        self.assertIsInstance(grid, AdaptiveEulerianGasGrid)
        self.assertGreaterEqual(len(grid.levels), 2)
        fine = grid.finest
        fine.u = [0.75] * len(fine.u)
        fine.v = [0.0] * len(fine.v)
        fine.w = [0.0] * len(fine.w)
        grid.base.u = [0.0] * len(grid.base.u)
        p = fine.cell_center(fine.nx // 2, fine.ny // 2, fine.nz // 2)
        self.assertAlmostEqual(grid.sample_dynamic_velocity(p)[0], 0.75, places=12)


if __name__ == "__main__":
    unittest.main()
