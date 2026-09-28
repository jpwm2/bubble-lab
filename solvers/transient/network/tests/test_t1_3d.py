from __future__ import annotations

import unittest

from bubblelab.solvers.transient.network.t1 import detect_t1_eligibility
from bubblelab.solvers.transient.network.t1_3d import (
    T13DSettings,
    build_supported_pre_t1_3d_state,
    continue_t1_3d,
    detect_t1_3d_eligibility,
    genuine_3d_metrics,
    perform_t1_3d_transaction,
    run_t1_3d_benchmark,
)


class General3DT1FoundationTests(unittest.TestCase):
    def test_supported_geometry_is_genuinely_3d(self) -> None:
        cfg = T13DSettings()
        state = build_supported_pre_t1_3d_state(shear_m_inv=cfg.shear_m_inv)
        eligibility = detect_t1_3d_eligibility(state, cfg)
        metrics = genuine_3d_metrics(state.to_network())

        self.assertTrue(eligibility.eligible, eligibility.reason)
        self.assertFalse(detect_t1_eligibility(state).eligible)
        self.assertGreaterEqual(
            metrics["max_patch_nonplanarity_m"],
            eligibility.required_nonplanarity_m,
        )
        self.assertGreaterEqual(
            metrics["junction_direction_spread"],
            cfg.minimum_junction_direction_spread,
        )

    def test_switch_changes_adjacency_and_junction_incidence(self) -> None:
        cfg = T13DSettings()
        state = build_supported_pre_t1_3d_state(shear_m_inv=cfg.shear_m_inv)
        result = perform_t1_3d_transaction(state, cfg)
        neighborhood = result.eligibility.base.neighborhood
        self.assertIsNotNone(neighborhood)
        assert neighborhood is not None

        old_pair = tuple(sorted(neighborhood.old_adjacent_regions))
        new_pair = tuple(sorted(neighborhood.opposite_regions))
        self.assertIn(old_pair, result.adjacency_before)
        self.assertNotIn(old_pair, result.adjacency_after)
        self.assertNotIn(new_pair, result.adjacency_before)
        self.assertIn(new_pair, result.adjacency_after)

        after = result.after.to_network()
        junctions = {junction.id: junction for junction in after.junctions}
        created_film = result.lineage.created_film_ids[0]
        for junction_id in result.lineage.created_junction_ids:
            self.assertIn(junction_id, junctions)
            self.assertIn(created_film, junctions[junction_id].incident_film_ids)
        for junction_id in result.lineage.retired_junction_ids:
            self.assertNotIn(junction_id, junctions)

    def test_conservation_identity_and_replay_are_deterministic(self) -> None:
        cfg = T13DSettings()
        state = build_supported_pre_t1_3d_state(shear_m_inv=cfg.shear_m_inv)
        first = perform_t1_3d_transaction(state, cfg)
        second = perform_t1_3d_transaction(state, cfg)

        before_ids = tuple(region.id for region in first.before.to_network().regions)
        after_ids = tuple(region.id for region in first.after.to_network().regions)
        self.assertEqual(before_ids, after_ids)
        self.assertEqual(before_ids, first.lineage.preserved_region_ids)
        self.assertLessEqual(
            max(value for _, value in first.volume_errors_after),
            cfg.base.volume_relative_tolerance,
        )
        self.assertEqual(first.lineage, second.lineage)
        self.assertEqual(first.after.topology_signature(), second.after.topology_signature())
        self.assertEqual(first.after.positions, second.after.positions)

    def test_post_event_transient_continuation_preserves_new_topology(self) -> None:
        cfg = T13DSettings()
        state = build_supported_pre_t1_3d_state(shear_m_inv=cfg.shear_m_inv)
        result = perform_t1_3d_transaction(state, cfg)
        continued, history = continue_t1_3d(result, steps=2)

        self.assertEqual(2, len(history))
        self.assertEqual(result.after.step_index + 2, continued.step_index)
        self.assertGreater(continued.time_s, result.after.time_s)
        self.assertEqual(result.after.topology_signature(), continued.topology_signature())
        self.assertGreater(continued.shared_dof_count(), 0)

    def test_refinement_geometry_residual_converges(self) -> None:
        result = run_t1_3d_benchmark("refinement")
        self.assertTrue(result["pass"], result)
        self.assertTrue(result["before_residual_strictly_decreases"])
        self.assertTrue(result["after_residual_strictly_decreases"])
        self.assertTrue(result["topology_invariant_under_refinement"])

    def test_zero_shear_cannot_be_claimed_as_3d(self) -> None:
        with self.assertRaises(ValueError):
            T13DSettings(shear_m_inv=0.0).validate()


if __name__ == "__main__":
    unittest.main()
