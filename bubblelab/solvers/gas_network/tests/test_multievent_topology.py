from __future__ import annotations

import unittest

from bubblelab.solvers.gas_network.multievent_topology import (
    supported_multievent_topology_gas_state,
)
from bubblelab.solvers.gas_network.multievent_topology_benchmarks import (
    multievent_topology_dependence_benchmark,
    multievent_topology_replay_benchmark,
    multievent_topology_sequence_benchmark,
)


class MultiEventTopologyGasTests(unittest.TestCase):
    def test_causal_four_t1_chain_and_rupture_coalescence(self) -> None:
        state = supported_multievent_topology_gas_state()
        self.assertEqual(len(state.gas_state.regions), 10)
        for number in range(1, 5):
            self.assertTrue(state.event_eligibility(number).eligible)
            event = state.perform_next_t1()
            self.assertEqual(event.topology_revision_after, number)
            self.assertLessEqual(event.total_relative_drift, 1.0e-12)
        eligibility = state.rupture_coalescence_eligibility()
        self.assertTrue(eligibility.eligible)
        event = state.perform_rupture_coalescence()
        self.assertEqual(event.event_types, ("RUPTURE", "COALESCENCE"))
        self.assertEqual(event.lineage, ("G", "H"))
        self.assertEqual(len(state.gas_state.regions), 9)
        self.assertLessEqual(event.total_relative_drift, 1.0e-12)
        self.assertTrue(event.unaffected_state_exact)

    def test_acceptance_benchmarks(self) -> None:
        self.assertTrue(multievent_topology_sequence_benchmark()["passed"])
        self.assertTrue(multievent_topology_dependence_benchmark()["passed"])

    def test_exact_replay(self) -> None:
        self.assertTrue(multievent_topology_replay_benchmark()["passed"])


if __name__ == "__main__":
    unittest.main()
