from __future__ import annotations

import math
import unittest
from unittest.mock import patch

from bubblelab.solvers.equilibrium.network import FilmNetwork, FilmPatch
from bubblelab.solvers.transient.network.core import TransientNetworkState
from bubblelab.solvers.transient.network.t1 import build_supported_pre_t1_state
from bubblelab.solvers.transient.network.t1_3d import detect_t1_3d_eligibility
from bubblelab.solvers.transient.network.t1_hydrodynamics import (
    DirectT1Settings,
    build_direct_3d_t1_state,
    detect_direct_t1_eligibility,
    forecast_direct_t1,
    perform_direct_t1_transaction,
)


def _rotate(point: tuple[float, float, float]) -> tuple[float, float, float]:
    ax = 0.37
    az = -0.61
    x, y, z = point
    cy, sy = math.cos(ax), math.sin(ax)
    y1, z1 = cy * y - sy * z, sy * y + cy * z
    cz, sz = math.cos(az), math.sin(az)
    return (cz * x - sz * y1, sz * x + cz * y1, z1)


def _direct_state(**kwargs: object) -> TransientNetworkState:
    return build_direct_3d_t1_state(
        amplitude_m_inv=0.8,
        y_saturation_m=0.04,
        **kwargs,
    )


def _rotated_state(state: TransientNetworkState) -> TransientNetworkState:
    network = state.to_network()
    patches = tuple(
        FilmPatch(
            id=patch.id,
            mesh=patch.mesh.with_vertices(_rotate(vertex) for vertex in patch.mesh.vertices),
            adjacent=patch.adjacent,
            sheet_tension_n_m=patch.sheet_tension_n_m,
            fixed_vertex_indices=patch.fixed_vertex_indices,
            contributes_to_volume=patch.contributes_to_volume,
        )
        for patch in network.patches
    )
    return TransientNetworkState.from_network(FilmNetwork(network.regions, patches, network.junctions))


class DirectT1HydrodynamicsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = DirectT1Settings(
            plateau_border_core_radius_m=0.010,
            hydrodynamic_segments=24,
        )

    def test_two_non_bilinear_fixtures_are_directly_eligible(self) -> None:
        for mode in ("twisted-saturation", "saddle-saturation"):
            with self.subTest(mode=mode):
                state = _direct_state(mode=mode)
                eligibility = detect_direct_t1_eligibility(state, self.settings)
                self.assertTrue(eligibility.eligible, eligibility.reason)
                self.assertGreater(eligibility.max_nonplanarity_m, 0.0)
                self.assertGreater(eligibility.junction_tangent_spread, 0.0)
                self.assertFalse(detect_t1_3d_eligibility(state).eligible)

    def test_legacy_decision_route_can_be_disabled(self) -> None:
        state = _direct_state()
        with patch(
            "bubblelab.solvers.transient.network.t1_3d.detect_t1_3d_eligibility",
            side_effect=AssertionError("legacy detector must not be called"),
        ), patch(
            "bubblelab.solvers.transient.network.t1_3d.perform_t1_3d_transaction",
            side_effect=AssertionError("legacy transaction must not be called"),
        ):
            result = perform_direct_t1_transaction(state, self.settings)
        self.assertGreater(result.forecast.event_time_s, 0.0)

    def test_force_balance_predicts_positive_finite_event_time(self) -> None:
        state = _direct_state()
        eligibility, forecast = forecast_direct_t1(state, self.settings)
        self.assertTrue(eligibility.eligible)
        self.assertTrue(math.isfinite(forecast.event_time_s))
        self.assertGreater(forecast.event_time_s, 0.0)
        self.assertGreater(forecast.minimum_force_n, self.settings.minimum_driving_force_n)
        self.assertLess(forecast.local_energy_event_j, forecast.local_energy_initial_j)

    def test_transaction_changes_adjacency_and_incidence(self) -> None:
        state = _direct_state()
        result = perform_direct_t1_transaction(state, self.settings)
        neighborhood = result.eligibility.neighborhood
        self.assertIsNotNone(neighborhood)
        assert neighborhood is not None
        old_pair = tuple(sorted(neighborhood.old_adjacent_regions))
        new_pair = tuple(sorted(neighborhood.opposite_regions))
        self.assertIn(old_pair, result.adjacency_before)
        self.assertNotIn(old_pair, result.adjacency_after)
        self.assertNotIn(new_pair, result.adjacency_before)
        self.assertIn(new_pair, result.adjacency_after)
        network = result.after.to_network()
        created = result.lineage.created_film_ids[0]
        touching = [junction for junction in network.junctions if created in junction.incident_film_ids]
        self.assertEqual(len(touching), 2)
        self.assertEqual(set(result.lineage.created_junction_ids), {junction.id for junction in touching})

    def test_stable_gas_identity_and_volume_conservation(self) -> None:
        state = _direct_state()
        result = perform_direct_t1_transaction(state, self.settings)
        self.assertEqual(
            tuple(region.id for region in result.before.to_network().regions),
            tuple(region.id for region in result.after.to_network().regions),
        )
        self.assertLessEqual(max(error for _, error in result.volume_errors_after), 1.0e-12)

    def test_deterministic_replay_is_exact(self) -> None:
        state = _direct_state(mode="saddle-saturation")
        first = perform_direct_t1_transaction(state, self.settings)
        second = perform_direct_t1_transaction(state, self.settings)
        self.assertEqual(first.forecast, second.forecast)
        self.assertEqual(first.lineage, second.lineage)
        self.assertEqual(first.after, second.after)

    def test_rotation_invariance_of_event_time_and_topology(self) -> None:
        state = _direct_state()
        rotated = _rotated_state(state)
        first = perform_direct_t1_transaction(state, self.settings)
        second = perform_direct_t1_transaction(rotated, self.settings)
        self.assertAlmostEqual(first.forecast.event_time_s, second.forecast.event_time_s, places=10)
        self.assertEqual(first.adjacency_after, second.adjacency_after)
        self.assertAlmostEqual(first.forecast.initial_force_n, second.forecast.initial_force_n, places=10)

    def test_extruded_legacy_fixture_is_outside_claimed_class(self) -> None:
        state = build_supported_pre_t1_state(resolution_m=0.10, collapse_fraction=0.50)
        eligibility = detect_direct_t1_eligibility(state, self.settings)
        self.assertFalse(eligibility.eligible)


if __name__ == "__main__":
    unittest.main()
