from __future__ import annotations

import unittest

from bubblelab.solvers.events.fragmentation import (
    ParentState,
    UnsupportedFragmentation,
    diagnose_neck,
    ellipsoid_mesh,
    necked_mesh,
    rotate_mesh,
    split_parent,
)


class FragmentationProductionTests(unittest.TestCase):
    def test_necked_mesh_splits_into_two_closed_children(self) -> None:
        mesh = necked_mesh()
        result = split_parent(ParentState("parent", mesh, mesh.volume(), 2.0e-6), event_time_s=0.01)
        self.assertEqual(result.parent_status, "SPLIT")
        self.assertEqual(result.event_contract()["type"], "SPLIT")
        self.assertEqual(len(result.children), 2)
        for child in result.children:
            self.assertTrue(child.mesh.is_closed_manifold())
            self.assertGreater(child.mesh.volume(), 0.0)
            self.assertEqual(child.lineage, ("parent",))
            self.assertEqual(child.geometry_status, "CUT_CAP_RESTART_REQUIRES_PHYSICAL_RELAXATION")
        self.assertGreaterEqual(result.surgery.negative.inserted_intersection_vertex_count, 12)
        self.assertGreaterEqual(result.surgery.positive.inserted_intersection_vertex_count, 12)

    def test_elongated_unnecked_surface_is_rejected(self) -> None:
        mesh = ellipsoid_mesh()
        diagnostic = diagnose_neck(mesh)
        self.assertFalse(diagnostic.detected)
        with self.assertRaises(UnsupportedFragmentation):
            split_parent(ParentState("ellipsoid", mesh, mesh.volume(), 1.0e-6), event_time_s=0.01)

    def test_conservation_and_deterministic_ids(self) -> None:
        mesh = necked_mesh()
        parent = ParentState(
            "conservative", mesh, 7.125, 2.75e-6,
            velocity_m_s=(0.35, -0.12, 0.08), mass_kg=8.4e-8,
        )
        first = split_parent(parent, event_time_s=0.0125)
        second = split_parent(parent, event_time_s=0.0125)
        self.assertEqual(first, second)
        self.assertLessEqual(float(first.conservation["target_volume_relative_error"] or 0.0), 1.0e-12)
        self.assertLessEqual(float(first.conservation["gas_amount_relative_error"] or 0.0), 1.0e-12)
        self.assertLessEqual(float(first.conservation["linear_momentum_relative_error"] or 0.0), 1.0e-12)
        self.assertLessEqual(float(first.conservation["geometric_volume_relative_error"] or 0.0), 5.0e-11)

    def test_rotation_preserves_classification_and_partition(self) -> None:
        mesh = necked_mesh(axial_segments=24, circum_segments=36)
        rotated = rotate_mesh(mesh, (0.31, 0.77, 0.55), 0.83)
        base = split_parent(ParentState("base", mesh, mesh.volume(), 1.0e-6), event_time_s=0.02)
        turn = split_parent(ParentState("turn", rotated, rotated.volume(), 1.0e-6), event_time_s=0.02)
        base_fraction = sorted(child.represented_volume_m3 / base.surgery.geometric_volume_sum for child in base.children)
        turn_fraction = sorted(child.represented_volume_m3 / turn.surgery.geometric_volume_sum for child in turn.children)
        self.assertLessEqual(max(abs(a - b) for a, b in zip(base_fraction, turn_fraction)), 1.0e-10)
        self.assertEqual(base.event_contract()["type"], "SPLIT")
        self.assertEqual(turn.event_contract()["type"], "SPLIT")

    def test_child_meshes_reuse_parent_geometry_away_from_cut(self) -> None:
        mesh = necked_mesh()
        result = split_parent(ParentState("reuse", mesh, mesh.volume(), None), event_time_s=0.0)
        self.assertGreater(result.surgery.negative.reused_parent_vertex_count, 300)
        self.assertGreater(result.surgery.positive.reused_parent_vertex_count, 300)
        self.assertLess(len(result.children[0].mesh.vertices), len(mesh.vertices) + 100)
        self.assertLess(len(result.children[1].mesh.vertices), len(mesh.vertices) + 100)


if __name__ == "__main__":
    unittest.main()
