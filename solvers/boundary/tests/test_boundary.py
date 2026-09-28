from __future__ import annotations

import unittest

from bubblelab.solvers.boundary import (
    AxisAlignedBoxBoundary,
    BoundarySet,
    PlaneBoundary,
    SphereBoundary,
    WettingParameters,
    constrain_velocity,
    enforce_front_contact,
)
from bubblelab.solvers.transient.geometry import icosphere


class SdfBoundaryTests(unittest.TestCase):
    def test_plane_sign_projection_and_normal(self):
        floor = PlaneBoundary("floor", point_m=(0.0, 0.0, 0.0), normal_outward=(0.0, 2.0, 0.0))
        self.assertAlmostEqual(floor.signed_distance((1.0, 0.25, -2.0)), 0.25)
        self.assertAlmostEqual(floor.signed_distance((1.0, -0.25, -2.0)), -0.25)
        self.assertEqual(floor.outward_normal((0.0, 0.0, 0.0)), (0.0, 1.0, 0.0))
        self.assertEqual(floor.closest_point((1.0, -0.25, -2.0)), (1.0, 0.0, -2.0))

    def test_sphere_and_box_signs(self):
        sphere = SphereBoundary("sphere", center_m=(0.0, 0.0, 0.0), radius_m=2.0)
        self.assertAlmostEqual(sphere.signed_distance((3.0, 0.0, 0.0)), 1.0)
        self.assertAlmostEqual(sphere.signed_distance((1.0, 0.0, 0.0)), -1.0)
        box = AxisAlignedBoxBoundary("box", minimum_m=(-1.0, -2.0, -3.0), maximum_m=(1.0, 2.0, 3.0))
        self.assertLess(box.signed_distance((0.0, 0.0, 0.0)), 0.0)
        self.assertAlmostEqual(box.signed_distance((2.0, 0.0, 0.0)), 1.0)
        self.assertEqual(box.closest_point((0.0, 0.0, 0.0)), (-1.0, 0.0, 0.0))

    def test_boundary_set_tie_breaks_by_stable_id(self):
        a = PlaneBoundary("a", point_m=(0.0, 0.0, 0.0), normal_outward=(0.0, 1.0, 0.0))
        b = PlaneBoundary("b", point_m=(0.0, 0.0, 0.0), normal_outward=(0.0, 1.0, 0.0))
        boundary_set = BoundarySet((b, a))
        self.assertEqual([boundary.boundary_id for boundary in boundary_set], ["a", "b"])
        self.assertEqual(boundary_set.nearest((0.0, 1.0, 0.0)).boundary_id, "a")


class ContactTests(unittest.TestCase):
    def test_velocity_removes_only_inward_normal_component(self):
        floor = PlaneBoundary("floor", point_m=(0.0, 0.0, 0.0), normal_outward=(0.0, 1.0, 0.0))
        velocity, correction = constrain_velocity((0.0, 1.0e-5, 0.0), (2.0, -1.0, 3.0), (floor,), 1.0e-3, 0.0)
        self.assertAlmostEqual(velocity[0], 2.0)
        self.assertAlmostEqual(velocity[1], 0.0)
        self.assertAlmostEqual(velocity[2], 3.0)
        self.assertAlmostEqual(correction, 1.0)

    def test_front_contact_is_local_and_nonpenetrating(self):
        front = icosphere(radius_m=0.006, center_m=(0.0, 0.0045, 0.0), subdivisions=1)
        floor = PlaneBoundary(
            "floor",
            point_m=(0.0, 0.0, 0.0),
            normal_outward=(0.0, 1.0, 0.0),
            wetting=WettingParameters(target_contact_angle_deg=60.0, contact_band_m=0.01),
        )
        report = enforce_front_contact(front, (floor,), 1.0e-8, 1.0e-4)
        self.assertGreater(report["contact_vertex_count"], 0)
        self.assertLess(report["contact_vertex_count"], len(front.vertices))
        self.assertGreater(report["position_correction_l1_m"], 0.0)
        self.assertGreaterEqual(min(floor.signed_distance(v) for v in front.vertices), -1.0e-8)
        entry = report["boundaries"][0]
        self.assertEqual(entry["bulk_eulerian_wall_coupling"], "NOT_IMPLEMENTED_PERIODIC_GRID")
        self.assertEqual(entry["tracked_front_tangential_condition"], "FREE_SLIP")


if __name__ == "__main__":
    unittest.main()
