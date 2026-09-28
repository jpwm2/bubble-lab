from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks import neck_detection_benchmark, neck_resolution_benchmark, split_bookkeeping_benchmark
from geometry import ellipsoid_mesh, necked_mesh
from neck import diagnose_neck


class FragmentationResearchTests(unittest.TestCase):
    def test_necked_shape_is_detected_and_ellipsoid_is_rejected(self) -> None:
        necked = diagnose_neck(necked_mesh(axial_segments=18, circum_segments=28))
        ellipsoid = diagnose_neck(ellipsoid_mesh(axial_segments=18, circum_segments=28))
        self.assertTrue(necked.detected)
        self.assertTrue(necked.topologically_separable)
        self.assertFalse(ellipsoid.detected)

    def test_neck_benchmark(self) -> None:
        result = neck_detection_benchmark(assert_result=True)
        self.assertGreater(result["prominence_ratio"], 1.3)

    def test_split_bookkeeping_is_conservative_and_deterministic(self) -> None:
        result = split_bookkeeping_benchmark(assert_result=True)
        self.assertTrue(result["deterministic_replay"])
        self.assertIsNone(result["surface_energy_change"])

    def test_resolution_study(self) -> None:
        result = neck_resolution_benchmark(assert_result=True)
        self.assertEqual(len(result["levels"]), 3)


if __name__ == "__main__":
    unittest.main()
