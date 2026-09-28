from __future__ import annotations

import copy
import unittest

from bubblelab.solvers.gas_network import (
    TopologyChangeRequired,
    advance_gas_network,
)
from bubblelab.solvers.gas_network.benchmarks import three_bubble_chain


class GasNetworkTests(unittest.TestCase):
    def test_multi_edge_step_is_conservative_and_coupled(self) -> None:
        state = three_bubble_chain()
        initial_total = state.total_amount_mol()
        before = {
            region.id: (region.volume_m3, region.pressure_pa())
            for region in state.regions
        }
        diag = advance_gas_network(state, 0.025)
        after = {
            region.id: (region.volume_m3, region.pressure_pa())
            for region in state.regions
        }
        self.assertGreaterEqual(diag.max_simultaneous_active_edges, 2)
        self.assertLessEqual(diag.total_relative_drift, 1.0e-12)
        self.assertEqual(diag.max_edge_antisymmetry_residual_mol, 0.0)
        self.assertAlmostEqual(state.total_amount_mol(), initial_total, delta=1.0e-21)
        self.assertLess(after["small"][0], before["small"][0])
        self.assertGreater(after["large"][0], before["large"][0])
        self.assertGreater(after["small"][1], before["small"][1])
        self.assertLess(after["large"][1], before["large"][1])
        self.assertEqual(diag.region_ids_before, diag.region_ids_after)
        self.assertEqual(diag.edge_ids_before, diag.edge_ids_after)

    def test_edge_order_does_not_make_transport_sequential(self) -> None:
        first = three_bubble_chain()
        second = copy.deepcopy(first)
        second.edges = tuple(reversed(second.edges))
        advance_gas_network(first, 0.025)
        advance_gas_network(second, 0.025)
        by_id_first = first.region_by_id()
        by_id_second = second.region_by_id()
        for region_id in first.region_ids():
            self.assertEqual(
                by_id_first[region_id].amount_mol,
                by_id_second[region_id].amount_mol,
            )
            self.assertEqual(
                by_id_first[region_id].volume_m3,
                by_id_second[region_id].volume_m3,
            )

    def test_disabled_control_leaves_amount_and_geometry_unchanged(self) -> None:
        state = three_bubble_chain(enabled=False)
        before = [
            (r.id, r.amount_mol, r.volume_m3, r.pressure_pa())
            for r in state.regions
        ]
        diag = advance_gas_network(state, 1.0)
        after = [
            (r.id, r.amount_mol, r.volume_m3, r.pressure_pa())
            for r in state.regions
        ]
        self.assertEqual(before, after)
        self.assertFalse(diag.enabled)
        self.assertEqual(diag.substeps, 0)
        self.assertEqual(diag.max_simultaneous_active_edges, 0)

    def test_inconsistent_constitutive_state_is_rejected(self) -> None:
        state = three_bubble_chain()
        state.regions[0].volume_m3 *= 1.01
        with self.assertRaises(ValueError):
            advance_gas_network(state, 0.025)

    def test_vanished_region_requires_topology_change(self) -> None:
        state = three_bubble_chain()
        state.regions[0].amount_mol = 0.0
        with self.assertRaises(TopologyChangeRequired):
            advance_gas_network(state, 0.025)


if __name__ == "__main__":
    unittest.main()
