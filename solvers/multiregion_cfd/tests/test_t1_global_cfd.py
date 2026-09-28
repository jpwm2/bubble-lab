from __future__ import annotations

import unittest

from bubblelab.solvers.multiregion_cfd import (
    T1GlobalCFDSettings,
    build_supported_four_region_t1_solver,
    run_t1_global_cfd_transition,
)
from bubblelab.solvers.transient.network.t1_hydrodynamics import (
    build_direct_3d_t1_state,
    detect_direct_t1_eligibility,
)


def _direct_state():
    return build_direct_3d_t1_state(
        amplitude_m_inv=0.8,
        y_saturation_m=0.04,
    )


class T1GlobalCFDTests(unittest.TestCase):
    def _case(self, *, cells: int = 12, front_order=None, axis_cycle: int = 0):
        state = _direct_state()
        eligibility = detect_direct_t1_eligibility(state)
        self.assertTrue(eligibility.eligible, eligibility.reason)
        self.assertIsNotNone(eligibility.neighborhood)
        neighborhood = eligibility.neighborhood
        assert neighborhood is not None
        region_ids = tuple(region.id for region in state.to_network().regions)
        solver = build_supported_four_region_t1_solver(
            region_ids=region_ids,
            old_pair=neighborhood.old_adjacent_regions,
            cells=cells,
            front_order=front_order,
            axis_cycle=axis_cycle,
        )
        result = run_t1_global_cfd_transition(
            solver,
            state,
            T1GlobalCFDSettings(),
        )
        return solver, state, result

    def test_overlap_is_partitioned_inside_one_shared_field(self) -> None:
        _, _, result = self._case()
        support = result.pre_field.support
        self.assertGreater(support.overlap_cell_count, 0)
        self.assertGreaterEqual(support.maximum_overlap_multiplicity, 2)
        self.assertGreater(support.overlap_fraction, 0.0)
        self.assertLessEqual(support.maximum_partition_sum_error, 1.0e-14)
        self.assertEqual(len(result.pre_field.constraint_cell_counts), 4)
        self.assertGreater(result.pre_field.pressure_linf_pa, 0.0)

    def test_transition_changes_real_adjacency_and_preserves_gas_ids(self) -> None:
        _, state, result = self._case()
        before = set(result.adjacency_before)
        after = set(result.adjacency_after)
        self.assertNotEqual(before, after)
        self.assertEqual(len(result.retired_film_ids), 1)
        self.assertEqual(len(result.created_film_ids), 1)
        self.assertEqual(len(result.retired_junction_ids), 2)
        self.assertEqual(len(result.created_junction_ids), 2)
        expected_ids = tuple(region.id for region in state.to_network().regions)
        self.assertEqual(result.preserved_region_ids, expected_ids)
        self.assertLessEqual(max(dict(result.volume_errors_after).values()), 1.0e-12)

    def test_field_traction_drives_event_time_and_post_t1_continues_same_grid(self) -> None:
        _, state, result = self._case()
        self.assertGreater(result.field_event_time_s, 0.0)
        self.assertGreater(result.capillary_driving_force_n, 0.0)
        self.assertGreaterEqual(result.field_hydrodynamic_resistance_n, 0.0)
        self.assertGreater(result.net_field_coupled_driving_force_n, 0.0)
        self.assertAlmostEqual(
            result.topology_state_after.time_s,
            state.time_s + result.field_event_time_s,
            places=13,
        )
        self.assertTrue(result.authoritative_grid_preserved)
        self.assertEqual(result.pre_field.model, result.post_field.model)
        self.assertGreater(result.post_field.pressure_linf_pa, 0.0)

    def test_container_permutation_is_deterministic(self) -> None:
        state = _direct_state()
        eligibility = detect_direct_t1_eligibility(state)
        assert eligibility.neighborhood is not None
        ids = tuple(region.id for region in state.to_network().regions)
        _, _, first = self._case(front_order=ids)
        _, _, second = self._case(front_order=tuple(reversed(ids)))
        self.assertEqual(first.as_dict(), second.as_dict())


if __name__ == "__main__":
    unittest.main()
