from __future__ import annotations

import unittest

from bubblelab.solvers.transient.contact import (
    ContactFormationError,
    form_contact,
    observe_contact,
)
from bubblelab.solvers.transient.geometry import FilmFront, icosphere


def pair(*, subdivisions: int = 2, gap_m: float = 8.0e-4) -> tuple[FilmFront, FilmFront]:
    radius = 1.0e-2
    half_distance = radius + 0.5 * gap_m
    a = icosphere(
        radius_m=radius,
        center_m=(-half_distance, 0.0, 0.0),
        subdivisions=subdivisions,
        bubble_id="bubble-a",
        surface_tension_n_m=0.05,
    )
    b = icosphere(
        radius_m=radius,
        center_m=(half_distance, 0.0, 0.0),
        subdivisions=subdivisions,
        bubble_id="bubble-b",
        surface_tension_n_m=0.05,
    )
    return a, b


class ContactFormationTests(unittest.TestCase):
    def test_separated_then_contact(self) -> None:
        far_a, far_b = pair(gap_m=5.0e-3)
        far = observe_contact(far_a, far_b)
        self.assertFalse(far.contact)
        near_a, near_b = pair(gap_m=7.5e-4)
        near = observe_contact(near_a, near_b)
        self.assertTrue(near.contact)
        self.assertLessEqual(near.separation_metric_m, near.threshold_m)
        self.assertGreater(near.threshold_m, 0.0)
        self.assertEqual(near.parent_ids, ("bubble-a", "bubble-b"))

    def test_contact_creates_one_shared_film_and_shared_ring_dofs(self) -> None:
        a, b = pair()
        result = form_contact(a, b)
        self.assertEqual(tuple(region.id for region in result.network.regions), ("bubble-a", "bubble-b"))
        shared = [
            patch
            for patch in result.network.patches
            if patch.adjacent == ("bubble-a", "bubble-b")
        ]
        self.assertEqual(len(shared), 1)
        self.assertEqual(len(result.network.junctions), 1)
        self.assertEqual(result.state.shared_dof_count(), len(result.contact_ring_points_m))
        self.assertGreaterEqual(len(result.contact_ring_points_m), 5)
        result.network.validate()

    def test_prescribed_volumes_are_projected_without_identity_change(self) -> None:
        a, b = pair()
        targets = {a.bubble_id: a.target_volume_m3, b.bubble_id: b.target_volume_m3}
        result = form_contact(a, b)
        self.assertLessEqual(
            max(error for _, error in result.raw_relative_volume_errors),
            result.local_volume_budget_fraction,
        )
        self.assertLess(
            max(error for _, error in result.projected_relative_volume_errors),
            3.0e-9,
        )
        self.assertEqual(
            {region.id: region.target_volume_m3 for region in result.network.regions},
            targets,
        )

    def test_input_order_is_deterministic(self) -> None:
        a, b = pair()
        forward = form_contact(a, b)
        reverse = form_contact(b, a)
        self.assertEqual(forward.signature(), reverse.signature())

    def test_threshold_refines_with_surface_resolution(self) -> None:
        observations = []
        for subdivisions in (1, 2, 3):
            a, b = pair(subdivisions=subdivisions, gap_m=6.0e-3)
            observations.append(observe_contact(a, b))
        thresholds = [item.threshold_m for item in observations]
        self.assertGreater(thresholds[0], thresholds[1])
        self.assertGreater(thresholds[1], thresholds[2])
        ratios = [thresholds[i + 1] / thresholds[i] for i in range(2)]
        self.assertTrue(all(0.35 < ratio < 0.75 for ratio in ratios))

    def test_large_interpenetration_is_rejected(self) -> None:
        a, b = pair(gap_m=-3.0e-3)
        with self.assertRaises(ContactFormationError):
            observe_contact(a, b)


if __name__ == "__main__":
    unittest.main()
