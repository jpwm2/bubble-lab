from __future__ import annotations

import json
import unittest
from pathlib import Path

from bubblelab.runtime.session_control import InvalidSessionCommand, RuntimeSession, SessionState

ROOT = Path(__file__).resolve().parents[3]
SCENARIOS = ROOT / "bubblelab" / "scenarios" / "runtime"


def load_scenario(name: str) -> dict:
    return json.loads((SCENARIOS / name).read_text(encoding="utf-8"))


def bubble(frame: dict, bubble_id: str) -> dict:
    return next(item for item in frame["bubbles"] if item["id"] == bubble_id)


class LiveRuntimeEditingTests(unittest.TestCase):
    def make_session(self) -> RuntimeSession:
        session = RuntimeSession(load_scenario("transient-wind.scenario.json"))
        self.assertTrue(session.capabilities["paused_state_edit"])
        return session

    def add_second(self, session: RuntimeSession) -> None:
        session.execute(
            {
                "command": "ADD_BUBBLE",
                "bubble_id": "bubble-2",
                "centroid_m": [0.018, 0.0, 0.0],
                "equivalent_radius_m": 0.004,
                "velocity_m_s": [0.0, 0.0, 0.0],
                "surface_tension_n_m": 0.05,
            }
        )

    def test_edit_requires_paused_and_rejection_is_atomic(self):
        session = self.make_session()
        before_signature = session._solver.replay_signature()
        before_frame_count = len(session.frames)
        before_time = session.physical_time_s
        with self.assertRaises(InvalidSessionCommand):
            session.execute(
                {
                    "command": "MOVE_BUBBLE",
                    "bubble_id": "bubble-1",
                    "centroid_m": [-0.005, 0.0, 0.0],
                }
            )
        self.assertEqual(session.state, SessionState.CREATED)
        self.assertEqual(session.physical_time_s, before_time)
        self.assertEqual(len(session.frames), before_frame_count)
        self.assertEqual(session._solver.replay_signature(), before_signature)
        self.assertEqual(session.command_history[-1]["result"], "REJECTED")

    def test_add_move_resize_velocity_and_step_continue_from_edited_state(self):
        session = self.make_session()
        session.pause()
        edit_time = session.physical_time_s
        self.add_second(session)
        self.assertEqual(session.physical_time_s, edit_time)
        self.assertEqual([front.bubble_id for front in session._solver.fronts], ["bubble-1", "bubble-2"])

        session.execute(
            {
                "command": "MOVE_BUBBLE",
                "bubble_id": "bubble-1",
                "centroid_m": [-0.005, 0.0, 0.0],
            }
        )
        moved = bubble(session.frames[-1], "bubble-1")
        for actual, expected in zip(moved["centroid_m"], [-0.005, 0.0, 0.0]):
            self.assertAlmostEqual(actual, expected, places=12)

        session.execute(
            {
                "command": "RESIZE_BUBBLE",
                "bubble_id": "bubble-2",
                "equivalent_radius_m": 0.005,
            }
        )
        resized = bubble(session.frames[-1], "bubble-2")
        self.assertAlmostEqual(resized["equivalent_radius_m"], 0.005, places=12)

        session.execute(
            {
                "command": "SET_BUBBLE_VELOCITY",
                "bubble_id": "bubble-1",
                "velocity_m_s": [0.02, 0.0, 0.0],
            }
        )
        velocity_frame = session.frames[-1]
        self.assertEqual(bubble(velocity_frame, "bubble-1")["velocity_m_s"], [0.02, 0.0, 0.0])
        before_step_centroid = tuple(bubble(velocity_frame, "bubble-1")["centroid_m"])
        self.assertEqual(session.physical_time_s, edit_time)

        result = session.step()
        self.assertEqual(result["result"], "ACCEPTED")
        self.assertGreater(session.physical_time_s, edit_time)
        after_step = session.frames[-1]
        self.assertEqual({item["id"] for item in after_step["bubbles"]}, {"bubble-1", "bubble-2"})
        self.assertNotEqual(tuple(bubble(after_step, "bubble-1")["centroid_m"]), before_step_centroid)
        self.assertEqual(session.state, SessionState.PAUSED)

    def test_delete_preserves_survivor_identity_and_final_delete_is_rejected(self):
        session = self.make_session()
        session.pause()
        self.add_second(session)
        session.execute({"command": "DELETE_BUBBLE", "bubble_id": "bubble-2"})
        self.assertEqual([front.bubble_id for front in session._solver.fronts], ["bubble-1"])
        self.assertEqual([item["id"] for item in session.frames[-1]["bubbles"]], ["bubble-1"])
        with self.assertRaises(InvalidSessionCommand):
            session.execute({"command": "DELETE_BUBBLE", "bubble_id": "bubble-1"})
        self.assertEqual([front.bubble_id for front in session._solver.fronts], ["bubble-1"])

    def test_overlap_rejection_does_not_mutate_solver_geometry(self):
        session = self.make_session()
        session.pause()
        before = session._solver.replay_signature()
        before_time = session.physical_time_s
        with self.assertRaises(InvalidSessionCommand):
            session.execute(
                {
                    "command": "ADD_BUBBLE",
                    "bubble_id": "overlap",
                    "centroid_m": [0.005, 0.0, 0.0],
                    "equivalent_radius_m": 0.004,
                    "velocity_m_s": [0.0, 0.0, 0.0],
                    "surface_tension_n_m": 0.05,
                }
            )
        self.assertEqual(session.physical_time_s, before_time)
        self.assertEqual(session._solver.replay_signature(), before)
        self.assertEqual([front.bubble_id for front in session._solver.fronts], ["bubble-1"])

    def test_unresolvable_resize_rolls_back_authoritative_solver_state(self):
        session = self.make_session()
        session.pause()
        self.add_second(session)
        before = session._solver.replay_signature()
        before_frames = len(session.frames)
        before_time = session.physical_time_s
        with self.assertRaises(InvalidSessionCommand):
            session.execute(
                {
                    "command": "RESIZE_BUBBLE",
                    "bubble_id": "bubble-2",
                    "equivalent_radius_m": 0.0001,
                }
            )
        self.assertEqual(session._solver.replay_signature(), before)
        self.assertEqual(len(session.frames), before_frames)
        self.assertEqual(session.physical_time_s, before_time)
        self.assertEqual(session.command_history[-1]["result"], "REJECTED")

    def test_checkpoint_roundtrip_preserves_live_edits(self):
        session = self.make_session()
        session.pause()
        self.add_second(session)
        session.execute(
            {
                "command": "MOVE_BUBBLE",
                "bubble_id": "bubble-1",
                "centroid_m": [-0.005, 0.0, 0.0],
            }
        )
        session.execute(
            {
                "command": "SET_BUBBLE_VELOCITY",
                "bubble_id": "bubble-2",
                "velocity_m_s": [-0.01, 0.0, 0.0],
            }
        )
        session.save_checkpoint()
        checkpoint = session.checkpoints[-1]
        restored = RuntimeSession.from_checkpoint(checkpoint)
        self.assertEqual(restored.state, SessionState.PAUSED)
        self.assertEqual(restored.physical_time_s, session.physical_time_s)
        self.assertEqual(restored._solver.replay_signature(), session._solver.replay_signature())
        self.assertEqual([front.bubble_id for front in restored._solver.fronts], ["bubble-1", "bubble-2"])
        restored.step()
        self.assertGreater(restored.physical_time_s, session.physical_time_s)

    def test_same_edit_sequence_is_deterministic(self):
        def run() -> RuntimeSession:
            session = self.make_session()
            session.pause()
            self.add_second(session)
            session.execute(
                {
                    "command": "MOVE_BUBBLE",
                    "bubble_id": "bubble-1",
                    "centroid_m": [-0.005, 0.0, 0.0],
                }
            )
            session.execute(
                {
                    "command": "SET_BUBBLE_VELOCITY",
                    "bubble_id": "bubble-2",
                    "velocity_m_s": [-0.01, 0.0, 0.0],
                }
            )
            session.step()
            return session

        first = run()
        second = run()
        self.assertEqual(first.frames, second.frames)
        self.assertEqual(first.command_history, second.command_history)
        self.assertEqual(first._solver.replay_signature(), second._solver.replay_signature())


if __name__ == "__main__":
    unittest.main()
