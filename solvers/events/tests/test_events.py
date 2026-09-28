from __future__ import annotations

import json
import math
import unittest

from bubblelab.solvers.events.benchmarks import _demo_state, event_replay_benchmark
from bubblelab.solvers.events.criteria import RuptureConfig, RuptureHooks, RuptureObservation, RuptureTracker
from bubblelab.solvers.events.engine import TopologyEventEngine
from bubblelab.solvers.events.model import EventState, SharedFilmState
from bubblelab.solvers.events.export import canonical_demo_frame


class RuptureCriteriaTests(unittest.TestCase):
    def test_threshold_crossing_is_localized_inside_step(self) -> None:
        tracker = RuptureTracker(RuptureConfig(thickness_threshold_m=100.0e-9))
        self.assertIsNone(tracker.observe(RuptureObservation(0.0, 150.0e-9)))
        decision = tracker.observe(RuptureObservation(0.05, 70.0e-9))
        self.assertIsNotNone(decision)
        self.assertEqual(decision.criterion, "THICKNESS_THRESHOLD")
        self.assertAlmostEqual(decision.rupture_time_s, 0.03125, places=14)
        self.assertGreater(decision.rupture_time_s, 0.0)
        self.assertLess(decision.rupture_time_s, 0.05)

    def test_dwell_time_is_continuous_below_threshold(self) -> None:
        tracker = RuptureTracker(
            RuptureConfig(thickness_threshold_m=100.0e-9, dwell_time_s=0.02)
        )
        self.assertIsNone(tracker.observe(RuptureObservation(0.0, 120.0e-9)))
        self.assertIsNone(tracker.observe(RuptureObservation(0.02, 80.0e-9)))
        decision = tracker.observe(RuptureObservation(0.04, 70.0e-9))
        self.assertIsNotNone(decision)
        self.assertAlmostEqual(decision.rupture_time_s, 0.03, places=14)
        self.assertEqual(decision.criterion, "THICKNESS_DWELL")

    def test_user_trigger_is_deterministic(self) -> None:
        tracker = RuptureTracker(RuptureConfig(thickness_threshold_m=10.0e-9))
        decision = tracker.observe(
            RuptureObservation(1.25, 1.0e-6, user_trigger=True, user_detail="operator")
        )
        self.assertEqual(decision.criterion, "USER_TRIGGER")
        self.assertEqual(decision.rupture_time_s, 1.25)

    def test_stochastic_hook_is_inert_by_default(self) -> None:
        calls = []

        def hook(observation: RuptureObservation, seed: int) -> bool:
            calls.append((observation.time_s, seed))
            return True

        tracker = RuptureTracker(
            RuptureConfig(thickness_threshold_m=10.0e-9),
            hooks=RuptureHooks(stochastic_nucleation=hook),
            seed=7,
            film_id="f",
        )
        self.assertIsNone(tracker.observe(RuptureObservation(0.0, 1.0e-6)))
        self.assertEqual(calls, [])


class CoalescenceTests(unittest.TestCase):
    def test_shared_film_rupture_and_coalescence_are_distinct_events(self) -> None:
        state = _demo_state()
        engine = TopologyEventEngine(
            RuptureConfig(thickness_threshold_m=100.0e-9), seed=state.seed
        )
        transition = engine.trigger_user_rupture(state, "shared-ab", time_s=0.2)
        self.assertEqual(
            [event.type for event in transition.emitted_events],
            ["RUPTURE", "COALESCENCE"],
        )
        self.assertEqual(
            transition.emitted_events[0].time_s,
            transition.emitted_events[1].time_s,
        )
        self.assertNotIn("shared-ab", transition.state.active_films)
        self.assertEqual(
            transition.state.retired_films["shared-ab"].status,
            "RUPTURED",
        )

    def test_gas_volume_momentum_lineage_and_restart_geometry_are_conservative(self) -> None:
        state = _demo_state()
        a = state.bubbles["bubble-a"]
        b = state.bubbles["bubble-b"]
        engine = TopologyEventEngine(
            RuptureConfig(thickness_threshold_m=100.0e-9), seed=state.seed
        )
        final = engine.trigger_user_rupture(state, "shared-ab", time_s=0.2).state
        child = next(item for item in final.bubbles.values() if item.status == "ALIVE")
        self.assertEqual(child.lineage, ("bubble-a", "bubble-b"))
        self.assertEqual(final.bubbles["bubble-a"].status, "MERGED")
        self.assertEqual(final.bubbles["bubble-b"].status, "MERGED")
        self.assertEqual(
            child.gas_amount_mol,
            math.fsum((a.gas_amount_mol, b.gas_amount_mol)),
        )
        self.assertEqual(child.volume_m3, math.fsum((a.volume_m3, b.volume_m3)))
        before_momentum = tuple(
            a.mass_kg * a.velocity_m_s[i] + b.mass_kg * b.velocity_m_s[i]
            for i in range(3)
        )
        after_momentum = tuple(
            child.mass_kg * child.velocity_m_s[i]
            for i in range(3)
        )
        for before, after in zip(before_momentum, after_momentum):
            self.assertAlmostEqual(before, after, places=18)
        self.assertLessEqual(
            child.restart_geometry.volume_relative_error(),
            1.0e-12,
        )

    def test_surviving_parent_films_are_rewired_to_child(self) -> None:
        state = _demo_state()
        outer_a = SharedFilmState(
            id="outer-a",
            adjacent=("bubble-a", "EXTERIOR"),
            min_thickness_m=500.0e-9,
            mean_thickness_m=500.0e-9,
            area_m2=2.0e-4,
            surface_tension_n_m=0.050,
        )
        state = EventState(
            bubbles=state.bubbles,
            active_films={**state.active_films, outer_a.id: outer_a},
            retired_films=state.retired_films,
            seed=state.seed,
        )
        engine = TopologyEventEngine(
            RuptureConfig(thickness_threshold_m=100.0e-9), seed=state.seed
        )
        final = engine.trigger_user_rupture(state, "shared-ab", time_s=0.2).state
        child = next(item for item in final.bubbles.values() if item.status == "ALIVE")
        self.assertEqual(
            final.active_films["outer-a"].adjacent,
            (child.id, "EXTERIOR"),
        )

    def test_replay_is_exact(self) -> None:
        result = event_replay_benchmark(assert_pass=True)
        self.assertTrue(result["identical"])


class ExportTests(unittest.TestCase):
    def test_export_contains_explicit_event_history_and_retired_parents(self) -> None:
        frame = canonical_demo_frame()
        self.assertEqual(frame["contract_version"], "1.0.0")
        self.assertEqual(
            [event["type"] for event in frame["topology"]["events"]],
            ["RUPTURE", "COALESCENCE"],
        )
        statuses = {bubble["id"]: bubble["status"] for bubble in frame["bubbles"]}
        self.assertEqual(statuses["bubble-a"], "MERGED")
        self.assertEqual(statuses["bubble-b"], "MERGED")
        self.assertEqual(sum(status == "ALIVE" for status in statuses.values()), 1)
        event_json = json.dumps(frame["topology"]["events"], sort_keys=True)
        self.assertIn("pre_event_state_ref", event_json)
        self.assertIn("lineage", event_json)
        self.assertIn("gas_amount_relative_error", event_json)


if __name__ == "__main__":
    unittest.main()
