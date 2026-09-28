from __future__ import annotations

import unittest

from bubblelab.solvers.equilibrium.network import project_region_volumes
from bubblelab.solvers.equilibrium.shared_benchmarks import (
    assert_b04,
    assert_b05,
    b04_equal_pressure_flatness,
    b05_unequal_pressure_curvature,
    unequal_pressure_result,
)
from bubblelab.solvers.equilibrium.shared_export import canonical_shared_film_frame
from bubblelab.solvers.equilibrium.shared_geometry import perturb_shared_film, reference_two_bubble_network


class SharedFilmTopologyTests(unittest.TestCase):
    def test_shared_patch_is_single_and_enters_region_volumes_with_opposite_sign(self) -> None:
        reference = reference_two_bubble_network(
            radius_a_m=0.012,
            radius_b_m=0.012,
            contact_radius_m=0.006,
            sheet_tension_n_m=0.05,
            outer_rings=6,
            shared_rings=6,
            azimuth_segments=24,
        )
        shared = [patch for patch in reference.patches if patch.id == "shared-ab"]
        self.assertEqual(len(shared), 1)
        self.assertEqual(shared[0].adjacent, ("bubble-a", "bubble-b"))

        moved = perturb_shared_film(reference, 2.0e-6)
        delta_a = moved.region_volume("bubble-a") - reference.region_volume("bubble-a")
        delta_b = moved.region_volume("bubble-b") - reference.region_volume("bubble-b")
        self.assertNotEqual(delta_a, 0.0)
        self.assertAlmostEqual(delta_a, -delta_b, delta=1.0e-18)

    def test_coupled_projection_hits_both_targets_without_moving_contact_ring(self) -> None:
        reference = reference_two_bubble_network(
            radius_a_m=0.010,
            radius_b_m=0.014,
            contact_radius_m=0.006,
            sheet_tension_n_m=0.05,
            outer_rings=6,
            shared_rings=6,
            azimuth_segments=24,
        )
        perturbed = perturb_shared_film(reference, 1.0e-5)
        projected = project_region_volumes(perturbed, relative_tolerance=1.0e-11)
        for region in projected.regions:
            error = abs(projected.region_volume(region.id) - region.target_volume_m3) / region.target_volume_m3
            self.assertLessEqual(error, 1.0e-10)

        before = next(patch for patch in perturbed.patches if patch.id == "shared-ab")
        after = next(patch for patch in projected.patches if patch.id == "shared-ab")
        for index in before.fixed_vertex_indices:
            self.assertEqual(before.mesh.vertices[index], after.mesh.vertices[index])


class SharedFilmBenchmarkTests(unittest.TestCase):
    def test_b04_equal_pressure_flatness(self) -> None:
        metrics = b04_equal_pressure_flatness()
        assert_b04(metrics)

    def test_b05_unequal_pressure_curvature(self) -> None:
        metrics = b05_unequal_pressure_curvature()
        assert_b05(metrics)


class SharedFilmExportTests(unittest.TestCase):
    def test_canonical_export_contains_one_shared_film_and_no_fake_junction(self) -> None:
        frame = canonical_shared_film_frame(unequal_pressure_result())
        self.assertEqual(frame["contract_version"], "1.0.0")
        self.assertEqual(frame["kind"], "FRAME")
        self.assertEqual(len(frame["bubbles"]), 2)
        shared_regions = [film for film in frame["film_regions"] if film["kind"] == "SHARED"]
        self.assertEqual(len(shared_regions), 1)
        self.assertEqual(shared_regions[0]["adjacent"], ["bubble-a", "bubble-b"])
        self.assertEqual(frame["junctions"], [])
        self.assertEqual(frame["manifest"]["feature_disclosures"]["shared_films"], "RESOLVED")
        self.assertEqual(frame["manifest"]["feature_disclosures"]["plateau_junctions"], "NOT_IMPLEMENTED")
        self.assertTrue(any(mesh["geometry_role"] == "SHARED_FILM" for mesh in frame["surface_meshes"]))


if __name__ == "__main__":
    unittest.main()
