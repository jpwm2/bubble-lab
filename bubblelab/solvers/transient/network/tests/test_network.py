from __future__ import annotations

import unittest

from bubblelab.solvers.equilibrium.plateau import reference_plateau_network
from bubblelab.solvers.equilibrium.shared_geometry import reference_two_bubble_network
from bubblelab.solvers.transient.network import (
    ConstantForcing,
    NetworkStepperSettings,
    NetworkTopology,
    TransientNetworkState,
    advance,
    run_steps,
)


class NetworkTopologyTests(unittest.TestCase):
    def test_shared_film_is_single_first_class_patch(self) -> None:
        network = reference_two_bubble_network(
            radius_a_m=8.0e-3,
            radius_b_m=8.0e-3,
            contact_radius_m=3.0e-3,
            sheet_tension_n_m=0.05,
            outer_rings=3,
            shared_rings=3,
            azimuth_segments=12,
        )
        state = TransientNetworkState.from_network(network)
        shared = [patch for patch in state.to_network().patches if patch.id == "shared-ab"]
        self.assertEqual(len(shared), 1)
        self.assertEqual(shared[0].adjacent, ("bubble-a", "bubble-b"))
        self.assertEqual(state.topology.region_ids, ("bubble-a", "bubble-b"))

    def test_plateau_members_collapse_to_authoritative_shared_dofs(self) -> None:
        network = reference_plateau_network(
            longitudinal_segments=6,
            junction_offset_m=(0.0, 0.0),
            twist_rad=0.0,
        )
        topology = NetworkTopology.from_network(network)
        state = TransientNetworkState.from_network(network)
        junction = network.junctions[0]
        count = len(junction.vertex_indices_by_film[0])
        self.assertEqual(state.shared_dof_count(), count)
        for sample in range(count):
            indices = [
                topology.member_to_dof[(film_id, vertex_indices[sample])]
                for film_id, vertex_indices in zip(
                    junction.incident_film_ids,
                    junction.vertex_indices_by_film,
                )
            ]
            self.assertEqual(len(set(indices)), 1)

    def test_topology_identity_is_deterministic(self) -> None:
        network = reference_plateau_network(
            longitudinal_segments=6,
            junction_offset_m=(0.0, 0.0),
            twist_rad=0.0,
        )
        a = TransientNetworkState.from_network(network)
        b = TransientNetworkState.from_network(network)
        self.assertEqual(a.topology_signature(), b.topology_signature())
        self.assertEqual(a.positions, b.positions)


class NetworkIntegratorTests(unittest.TestCase):
    def _two_bubble(self) -> TransientNetworkState:
        network = reference_two_bubble_network(
            radius_a_m=8.0e-3,
            radius_b_m=8.0e-3,
            contact_radius_m=3.0e-3,
            sheet_tension_n_m=0.05,
            outer_rings=3,
            shared_rings=3,
            azimuth_segments=12,
        )
        return TransientNetworkState.from_network(network)

    def test_nonzero_timestep_preserves_ids_and_volumes(self) -> None:
        state = self._two_bubble()
        settings = NetworkStepperSettings(
            dt_s=1.0e-4,
            mobility_m_per_n_s=5.0e-3,
            volume_relative_tolerance=5.0e-9,
        )
        advanced, diag = advance(state, settings=settings)
        self.assertEqual(advanced.step_index, 1)
        self.assertGreater(advanced.time_s, 0.0)
        self.assertEqual(state.topology_signature(), advanced.topology_signature())
        self.assertLessEqual(max(error for _, error in diag.relative_volume_errors), 2.0e-7)

    def test_zero_forcing_is_dissipative(self) -> None:
        state = self._two_bubble()
        settings = NetworkStepperSettings(dt_s=1.0e-4, mobility_m_per_n_s=5.0e-3)
        before = state.to_network().surface_energy_j()
        advanced, diag = advance(state, settings=settings)
        self.assertLessEqual(
            diag.surface_energy_j,
            before + 2.0e-12 * max(abs(before), 1.0),
        )
        self.assertEqual(state.topology_signature(), advanced.topology_signature())

    def test_forcing_moves_real_geometry_not_metadata(self) -> None:
        state = self._two_bubble()
        forcing = ConstantForcing(velocity_m_s=(0.0, 1.0e-4, 0.0))
        settings = NetworkStepperSettings(dt_s=2.0e-4, mobility_m_per_n_s=5.0e-3)
        advanced, _ = run_steps(state, 2, settings=settings, forcing=forcing)
        self.assertNotEqual(advanced.positions, state.positions)
        self.assertEqual(state.topology_signature(), advanced.topology_signature())

    def test_replay_is_bitwise_deterministic(self) -> None:
        state = self._two_bubble()
        settings = NetworkStepperSettings(dt_s=1.0e-4, mobility_m_per_n_s=5.0e-3)
        forcing = ConstantForcing(velocity_m_s=(2.0e-5, -1.0e-5, 0.0))
        a, ah = run_steps(state, 3, settings=settings, forcing=forcing)
        b, bh = run_steps(state, 3, settings=settings, forcing=forcing)
        self.assertEqual(a.positions, b.positions)
        self.assertEqual(a.pressures_pa, b.pressures_pa)
        self.assertEqual(ah, bh)


if __name__ == "__main__":
    unittest.main()
