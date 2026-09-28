from __future__ import annotations

import unittest

from bubblelab.solvers.thinfilm.benchmarks import (
    gravity_drainage_benchmark,
    inclined_patch,
    surfactant_conservation_benchmark,
    uniform_film_benchmark,
)
from bubblelab.solvers.thinfilm.surface import (
    SurfaceTransportParameters,
    SurfaceTransportState,
)


class SurfaceTransportTests(unittest.TestCase):
    def test_uniform_film_is_stationary_and_conservative(self):
        result = uniform_film_benchmark()
        self.assertTrue(result["passed"])
        self.assertLessEqual(result["liquid_relative_drift"], 1.0e-14)

    def test_gravity_drainage_moves_liquid_downhill_and_is_first_order(self):
        result = gravity_drainage_benchmark()
        self.assertTrue(result["passed"])
        self.assertGreaterEqual(result["observed_time_order"], 0.95)

    def test_surfacant_diffusion_conserves_and_marangoni_points_to_high_sigma(self):
        result = surfactant_conservation_benchmark()
        self.assertTrue(result["passed"])
        self.assertGreater(result["marangoni_alignment"], 0.0)

    def test_positivity_uses_substeps_instead_of_large_negative_clamp(self):
        state = SurfaceTransportState(
            inclined_patch(),
            [1.0e-7, 2.0e-5],
            [0.0, 0.0],
            parameters=SurfaceTransportParameters(
                gravity_m_s2=(0.0, 0.0, 0.0),
                disjoining_coefficient_pa_m3=1.0e-22,
                surface_elasticity_n_m_per_mol_m2=0.0,
            ),
        )
        diag = state.advance(0.01)
        self.assertGreaterEqual(min(state.thickness_m), 0.0)
        self.assertEqual(diag.roundoff_corrections, 0)
        self.assertLessEqual(diag.liquid_relative_drift, 1.0e-12)


if __name__ == "__main__":
    unittest.main()
