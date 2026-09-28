import unittest
from bubblelab.solvers.singular_breakup.transactions import child_lineage, conservative_split


class ConservativeTransactionTests(unittest.TestCase):
    def test_split_is_conservative(self):
        split = conservative_split(2.0e-8, 4.5e-10)
        self.assertLessEqual(split.relative_error, 1e-15)
        self.assertAlmostEqual(split.parent_after_m3 + split.detached_m3, split.parent_before_m3)

    def test_lineage_is_stable(self):
        self.assertEqual(
            child_lineage("liquid-root", 2, 0),
            "liquid-root/detach-002/piece-00",
        )


if __name__ == "__main__":
    unittest.main()
