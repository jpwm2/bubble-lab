from __future__ import annotations

import unittest

from bubblelab.solvers.thinfilm.benchmarks import remesh_transfer_benchmark


class RemeshTransferTests(unittest.TestCase):
    def test_b14_style_conservative_transfer(self):
        result = remesh_transfer_benchmark()
        self.assertTrue(result["passed"])
        self.assertLessEqual(result["liquid_relative_error"], 1.0e-10)
        self.assertLessEqual(result["surfactant_relative_error"], 1.0e-10)
        self.assertTrue(result["region_identity_preserved"])


if __name__ == "__main__":
    unittest.main()
