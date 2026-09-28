from __future__ import annotations

import unittest

from bubblelab.solvers.thinfilm.benchmarks import gas_diffusion_pair_benchmark
from bubblelab.solvers.thinfilm.gas import GasRegionState, GasTransferPair


class GasTransferTests(unittest.TestCase):
    def test_pairwise_transfer_is_equal_opposite_and_pressure_driven(self):
        a = GasRegionState("a", 1.0e-6, 1.0e-5)
        b = GasRegionState("b", 2.0e-6, 1.0e-5)
        pair = GasTransferPair(
            "a",
            "b",
            1.0e-4,
            1.0e-6,
            permeability_mol_m_per_m2_s_pa=1.0e-12,
        )
        initial = a.amount_mol + b.amount_mol
        diag = pair.advance(a, b, 0.1)
        self.assertGreater(diag.amount_transferred_a_to_b_mol, 0.0)
        self.assertLessEqual(diag.total_relative_drift, 1.0e-15)
        self.assertAlmostEqual(a.amount_mol + b.amount_mol, initial, places=18)

    def test_b15_style_temporal_convergence(self):
        result = gas_diffusion_pair_benchmark()
        self.assertTrue(result["passed"])
        self.assertGreaterEqual(result["observed_time_order"], 0.95)
        self.assertLessEqual(result["gas_total_relative_drift"], 1.0e-10)


if __name__ == "__main__":
    unittest.main()
