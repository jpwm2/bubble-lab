from __future__ import annotations

import copy
import unittest

from bubblelab.solvers.equilibrium.network import EXTERIOR
from bubblelab.solvers.gas_network import shared_film_edges_from_topology
from bubblelab.solvers.gas_network.topology import supported_t1_gas_transport_state


class TopologyGasTransportTests(unittest.TestCase):
    def test_transport_edges_are_derived_from_real_internal_films(self) -> None:
        state = supported_t1_gas_transport_state()
        network = state.topology_state.to_network()
        edges = shared_film_edges_from_topology(
            network,
            film_thickness_m=state.film_thickness_m,
            permeability_mol_m_per_m2_s_pa=state.permeability_mol_m_per_m2_s_pa,
        )
        patches = {patch.id: patch for patch in network.patches}
        self.assertGreaterEqual(len(edges), 2)
        for edge in edges:
            patch = patches[edge.id]
            self.assertNotIn(EXTERIOR, patch.adjacent)
            self.assertEqual((edge.region_a, edge.region_b), patch.adjacent)
            self.assertEqual(edge.shared_area_m2, patch.mesh.area())

    def test_real_t1_rebuilds_graph_without_resetting_gas_state(self) -> None:
        state = supported_t1_gas_transport_state()
        state.advance(0.05)
        before = tuple(
            (region.id, region.amount_mol, region.volume_m3, region.pressure_pa())
            for region in state.gas_state.regions
        )
        event = state.perform_t1()
        after = tuple(
            (region.id, region.amount_mol, region.volume_m3, region.pressure_pa())
            for region in state.gas_state.regions
        )
        self.assertEqual(before, after)
        self.assertEqual(event.total_relative_drift, 0.0)
        self.assertEqual(event.region_ids_before, event.region_ids_after)
        self.assertNotEqual(event.adjacency_before, event.adjacency_after)
        self.assertFalse(set(event.retired_film_ids).intersection(event.edge_ids_after))
        self.assertTrue(set(event.created_film_ids).issubset(set(event.edge_ids_after)))
        self.assertEqual(state.gas_state.topology_revision, 1)

    def test_post_t1_transfer_uses_created_real_film(self) -> None:
        state = supported_t1_gas_transport_state()
        for _ in range(3):
            state.advance(0.05)
        event = state.perform_t1()
        created_id = event.created_film_ids[0]
        edge = next(item for item in state.gas_state.edges if item.id == created_id)
        pressures = {
            region.id: region.pressure_pa() for region in state.gas_state.regions
        }
        pressure_difference = pressures[edge.region_a] - pressures[edge.region_b]
        diag = state.advance(0.05)
        created_diag = next(item for item in diag.edges if item.edge_id == created_id)
        self.assertNotEqual(pressure_difference, 0.0)
        self.assertGreater(
            pressure_difference * created_diag.initial_rate_a_to_b_mol_s,
            0.0,
        )
        self.assertNotEqual(created_diag.integrated_a_to_b_mol, 0.0)
        self.assertFalse(set(event.retired_film_ids).intersection(state.gas_state.edge_ids()))
        self.assertLessEqual(diag.total_relative_drift, 1.0e-12)

    def test_disabled_transport_stays_stationary_through_t1(self) -> None:
        state = supported_t1_gas_transport_state(diffusion_enabled=False)
        before = copy.deepcopy(
            tuple(
                (region.id, region.amount_mol, region.volume_m3, region.pressure_pa())
                for region in state.gas_state.regions
            )
        )
        pre = state.advance(0.25)
        event = state.perform_t1()
        post = state.advance(0.25)
        after = tuple(
            (region.id, region.amount_mol, region.volume_m3, region.pressure_pa())
            for region in state.gas_state.regions
        )
        self.assertEqual(before, after)
        self.assertEqual(pre.substeps, 0)
        self.assertEqual(post.substeps, 0)
        self.assertEqual(event.total_relative_drift, 0.0)
        self.assertNotEqual(event.edge_ids_before, event.edge_ids_after)


if __name__ == "__main__":
    unittest.main()
