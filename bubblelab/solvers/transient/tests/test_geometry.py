from __future__ import annotations

import math
import unittest

from bubblelab.solvers.transient.geometry import icosphere, norm


class FilmFrontTests(unittest.TestCase):
    def test_icosphere_is_closed_outward_and_refines_geometry(self):
        coarse = icosphere(radius_m=0.01, subdivisions=0)
        fine = icosphere(radius_m=0.01, subdivisions=2)
        exact_v = 4.0 * math.pi * 0.01 ** 3 / 3.0
        exact_a = 4.0 * math.pi * 0.01 ** 2
        self.assertGreater(coarse.signed_volume(), 0.0)
        self.assertGreater(fine.signed_volume(), 0.0)
        self.assertLess(abs(fine.volume() - exact_v), abs(coarse.volume() - exact_v))
        self.assertLess(abs(fine.area() - exact_a), abs(coarse.area() - exact_a))

    def test_capillary_area_gradient_has_near_zero_net_force(self):
        front = icosphere(radius_m=0.01, subdivisions=2, surface_tension_n_m=0.05)
        forces = front.capillary_vertex_forces()
        net = tuple(sum(f[a] for f in forces) for a in range(3))
        self.assertLess(norm(net), 1.0e-14)
        self.assertGreater(sum(norm(f) for f in forces), 0.0)

    def test_volume_projection_restores_target(self):
        front = icosphere(radius_m=0.01, subdivisions=1)
        target = front.volume()
        front.vertices = [(1.01 * x, y, z) for x, y, z in front.vertices]
        pre = front.project_volume()
        self.assertGreater(pre, 1.0e-4)
        self.assertLess(abs(front.volume() - target) / target, 1.0e-12)


if __name__ == "__main__":
    unittest.main()
