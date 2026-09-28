from __future__ import annotations

from dataclasses import replace
import unittest

from bubblelab.solvers.equilibrium.network import FilmNetwork
from bubblelab.solvers.transient.network import NetworkStepperSettings, TransientNetworkState, advance
from bubblelab.solvers.transient.network.t1 import (
    T1TransactionError,
    build_supported_pre_t1_network,
    build_supported_pre_t1_state,
    combine_disjoint_networks,
    detect_t1_eligibility,
    internal_adjacency_pairs,
    perform_t1_transaction,
)
from bubblelab.solvers.transient.network.t1.benchmarks import (
    conservation_benchmark,
    refinement_benchmark,
    switch_benchmark,
)


class ProductionT1EligibilityTests(unittest.TestCase):
    def test_geometry_and_incidence_identify_supported_neighborhood(self) -> None:
        state = build_supported_pre_t1_state(resolution_m=0.12, id_prefix="qualified:")
        result = detect_t1_eligibility(state)
        self.assertTrue(result.eligible, result.reason)
        self.assertIsNotNone(result.neighborhood)
        assert result.neighborhood is not None
        self.assertEqual(("qualified:A", "qualified:B"), result.neighborhood.old_adjacent_regions)
        self.assertEqual(("qualified:C", "qualified:D"), result.neighborhood.opposite_regions)
        self.assertEqual(("qualified:film:AB:central",), result.candidate_film_ids)
        self.assertLess(result.collapsing_length_m, result.threshold_m)

    def test_coarse_outer_geometry_rejects_explicitly(self) -> None:
        result = detect_t1_eligibility(build_supported_pre_t1_state(resolution_m=0.8))
        self.assertFalse(result.eligible)
        self.assertIn("under-resolved", result.reason)

    def test_ambiguous_simultaneous_collapses_reject(self) -> None:
        first = build_supported_pre_t1_network(resolution_m=0.12)
        second = build_supported_pre_t1_network(
            resolution_m=0.12,
            id_prefix="second:",
            origin_xy=(3.0, 0.0),
        )
        combined = TransientNetworkState.from_network(combine_disjoint_networks(first, second))
        result = detect_t1_eligibility(combined)
        self.assertFalse(result.eligible)
        self.assertEqual("ambiguous simultaneous collapses", result.reason)
        self.assertEqual(2, len(result.candidate_film_ids))

    def test_nonplanar_general_3d_geometry_rejects(self) -> None:
        network = build_supported_pre_t1_network(resolution_m=0.12)
        patches = []
        for patch in network.patches:
            if patch.id != "film:AC":
                patches.append(patch)
                continue
            vertices = list(patch.mesh.vertices)
            x, y, z = vertices[-1]
            vertices[-1] = (x + 0.025, y + 0.025, z)
            patches.append(replace(patch, mesh=patch.mesh.with_vertices(vertices)))
        distorted = FilmNetwork(network.regions, tuple(patches), network.junctions)
        distorted.validate()
        result = detect_t1_eligibility(TransientNetworkState.from_network(distorted))
        self.assertFalse(result.eligible)
        self.assertIn("unsupported T1 candidate", result.reason)


class ProductionT1TransactionTests(unittest.TestCase):
    def test_switch_changes_real_neighbor_graph_and_geometry(self) -> None:
        state = build_supported_pre_t1_state(resolution_m=0.12)
        result = perform_t1_transaction(state)
        before_pairs = set(internal_adjacency_pairs(result.before))
        after_pairs = set(internal_adjacency_pairs(result.after))
        self.assertIn(("A", "B"), before_pairs)
        self.assertNotIn(("A", "B"), after_pairs)
        self.assertNotIn(("C", "D"), before_pairs)
        self.assertIn(("C", "D"), after_pairs)
        created = next(
            patch for patch in result.after.to_network().patches
            if patch.id == result.lineage.created_film_ids[0]
        )
        self.assertGreater(created.mesh.area(), 0.0)
        result.after.to_network().validate()

    def test_region_identity_and_lineage_are_stable(self) -> None:
        result = perform_t1_transaction(build_supported_pre_t1_state(resolution_m=0.12))
        self.assertEqual(result.before.topology.region_ids, result.after.topology.region_ids)
        self.assertEqual(("film:AB:central",), result.lineage.retired_film_ids)
        self.assertEqual(1, len(result.lineage.created_film_ids))
        self.assertEqual(2, len(result.lineage.retired_junction_ids))
        self.assertEqual(2, len(result.lineage.created_junction_ids))
        self.assertEqual(("A", "B", "C", "D"), result.lineage.preserved_region_ids)
        self.assertTrue({"film:AC", "film:BC", "film:AD", "film:BD"}.issubset(result.lineage.preserved_film_ids))

    def test_closed_region_volumes_meet_production_tolerance(self) -> None:
        result = perform_t1_transaction(build_supported_pre_t1_state(resolution_m=0.12))
        self.assertLessEqual(max(error for _, error in result.volume_errors_after), 2.0e-10)
        before_targets = tuple((region.id, region.target_volume_m3) for region in result.before.to_network().regions)
        after_targets = tuple((region.id, region.target_volume_m3) for region in result.after.to_network().regions)
        self.assertEqual(before_targets, after_targets)

    def test_event_is_instantaneous_and_seed_requires_relaxation(self) -> None:
        state = replace(
            build_supported_pre_t1_state(resolution_m=0.12),
            time_s=1.25,
            step_index=42,
        )
        result = perform_t1_transaction(state)
        self.assertEqual(1.25, result.after.time_s)
        self.assertEqual(42, result.after.step_index)
        self.assertTrue(result.seed_requires_relaxation)

    def test_deterministic_replay_matches_topology_and_positions(self) -> None:
        first = perform_t1_transaction(build_supported_pre_t1_state(resolution_m=0.12))
        second = perform_t1_transaction(build_supported_pre_t1_state(resolution_m=0.12))
        self.assertEqual(first.after.topology_signature(), second.after.topology_signature())
        self.assertEqual(first.after.positions, second.after.positions)
        self.assertEqual(first.lineage, second.lineage)

    def test_post_event_seed_can_enter_transient_relaxation(self) -> None:
        result = perform_t1_transaction(build_supported_pre_t1_state(resolution_m=0.12))
        advanced, diagnostic = advance(
            result.after,
            settings=NetworkStepperSettings(
                dt_s=1.0e-6,
                mobility_m_per_n_s=1.0e-4,
                volume_relative_tolerance=2.0e-10,
            ),
        )
        self.assertEqual(result.after.step_index + 1, advanced.step_index)
        self.assertLessEqual(max(error for _, error in diagnostic.relative_volume_errors), 2.0e-9)

    def test_ineligible_state_does_not_mutate_through_transaction(self) -> None:
        state = build_supported_pre_t1_state(resolution_m=0.8)
        signature = state.topology_signature()
        with self.assertRaises(T1TransactionError):
            perform_t1_transaction(state)
        self.assertEqual(signature, state.topology_signature())

    def test_acceptance_benchmarks_pass(self) -> None:
        self.assertTrue(switch_benchmark()["pass"])
        self.assertTrue(conservation_benchmark()["pass"])
        self.assertTrue(refinement_benchmark()["pass"])


if __name__ == "__main__":
    unittest.main()
