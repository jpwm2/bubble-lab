from __future__ import annotations

import unittest

from bubblelab.solvers.gas_network.repeated_topology import (
    supported_repeated_t1_gas_transport_state,
)
from bubblelab.solvers.gas_network.repeated_topology_benchmarks import (
    repeated_post_event_transfer_benchmark,
    repeated_t1_switch_benchmark,
    repeated_topology_conservation_benchmark,
    repeated_topology_replay_benchmark,
    second_event_dependence_benchmark,
)


class RepeatedTopologyGasTransportTests(unittest.TestCase):
    def test_second_distinct_t1_is_enabled_only_by_first_canonical_switch(self) -> None:
        state = supported_repeated_t1_gas_transport_state()
        initial_ids = state.gas_state.region_ids()
        blocked = state.event_eligibility(2)
        self.assertFalse(blocked.eligible)
        self.assertIn("adjacency already exists", blocked.reason)
        first = state.perform_t1()
        enabled = state.event_eligibility(2)
        self.assertTrue(enabled.eligible)
        state.advance(0.05)
        second = state.perform_t1()
        self.assertNotEqual(first.retired_film_ids, second.retired_film_ids)
        self.assertNotEqual(first.created_film_ids, second.created_film_ids)
        self.assertEqual(first.adjacency_after, second.adjacency_before)
        self.assertEqual(first.event_id, "t1:000001")
        self.assertEqual(second.event_id, "t1:000002")
        self.assertEqual(len(initial_ids), 6)
        self.assertEqual(state.gas_state.topology_revision, 2)
        self.assertEqual(initial_ids, state.gas_state.region_ids())

    def test_repeated_acceptance_benchmarks(self) -> None:
        for benchmark in (
            repeated_t1_switch_benchmark,
            repeated_topology_conservation_benchmark,
            second_event_dependence_benchmark,
            repeated_post_event_transfer_benchmark,
            repeated_topology_replay_benchmark,
        ):
            with self.subTest(benchmark=benchmark.__name__):
                self.assertTrue(benchmark()["passed"])


if __name__ == "__main__":
    unittest.main()
