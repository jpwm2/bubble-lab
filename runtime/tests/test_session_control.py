from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from bubblelab.runtime.bundle import validate_replay_bundle
from bubblelab.runtime.session_control import (
    InvalidSessionCommand,
    RuntimeSession,
    SessionState,
    UnsupportedSessionCapability,
)

ROOT = Path(__file__).resolve().parents[3]
SCENARIOS = ROOT / "bubblelab" / "scenarios" / "runtime"


def load_scenario(name: str) -> dict:
    return json.loads((SCENARIOS / name).read_text(encoding="utf-8"))


class RuntimeSessionControlTests(unittest.TestCase):
    def make_transient(self) -> RuntimeSession:
        return RuntimeSession(load_scenario("transient-wind.scenario.json"))

    def test_pause_does_not_advance_physical_time(self):
        session = self.make_transient()
        before = session.physical_time_s
        session.pause()
        self.assertEqual(session.state, SessionState.PAUSED)
        self.assertEqual(session.physical_time_s, before)
        session.pause()
        self.assertEqual(session.physical_time_s, before)

    def test_step_advances_exactly_one_backend_step_and_returns_paused(self):
        session = self.make_transient()
        session.pause()
        before_index = session._solver.step_index
        before_time = session.physical_time_s
        result = session.step()
        self.assertEqual(session._solver.step_index, before_index + 1)
        self.assertGreater(session.physical_time_s, before_time)
        self.assertEqual(session.state, SessionState.PAUSED)
        self.assertEqual(len(result["emitted_frame_ids"]), 1)
        self.assertEqual(session.frames[-1]["simulation_time_s"], session.physical_time_s)

    def test_run_to_time_requires_running_and_lands_on_target(self):
        session = self.make_transient()
        session.pause()
        with self.assertRaises(InvalidSessionCommand):
            session.run_to_time(0.001)
        session.resume()
        result = session.run_to_time(0.001)
        self.assertEqual(session.state, SessionState.PAUSED)
        self.assertAlmostEqual(session.physical_time_s, 0.001, places=15)
        self.assertGreaterEqual(len(result["emitted_frame_ids"]), 1)
        self.assertEqual(result["overshoot_s"], 0.0)

    def test_reset_restores_initial_authoritative_state(self):
        session = self.make_transient()
        initial = copy.deepcopy(session.frames[0])
        session.pause()
        session.step()
        self.assertGreater(session.physical_time_s, 0.0)
        session.reset()
        self.assertEqual(session.state, SessionState.CREATED)
        self.assertEqual(session.physical_time_s, 0.0)
        self.assertEqual(session.current_frame_index, 0)
        self.assertEqual(session.frames, [initial])

    def test_same_commands_reproduce_exact_frames_and_log(self):
        commands = [
            {"command": "PAUSE"},
            {"command": "STEP"},
            {"command": "RESUME"},
            {"command": "RUN_TO_TIME", "target_time_s": 0.001},
        ]
        first = self.make_transient()
        second = self.make_transient()
        for command in commands:
            first.execute(command)
            second.execute(command)
        self.assertEqual(first.frames, second.frames)
        self.assertEqual(first.command_history, second.command_history)
        self.assertEqual(first._solver.replay_signature(), second._solver.replay_signature())

    def test_checkpoint_is_authoritative_and_advertised_for_live_transient(self):
        session = self.make_transient()
        self.assertTrue(session.capabilities["persistent_checkpoint_restart"])
        session.pause()
        result = session.save_checkpoint()
        self.assertEqual(result["result"], "ACCEPTED")
        self.assertEqual(len(result["emitted_checkpoint_ids"]), 1)
        self.assertEqual(len(session.checkpoints), 1)
        self.assertEqual(session.checkpoints[0]["kind"], "CHECKPOINT")
        self.assertTrue(session.checkpoints[0]["checkpoint_state"]["same_build_only"])
        self.assertEqual(session.command_history[-1]["command"], "SAVE_CHECKPOINT")

    def test_equilibrium_exposes_final_state_without_fake_time_stepping(self):
        session = RuntimeSession(load_scenario("equilibrium-single.scenario.json"))
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertFalse(session.capabilities["step"])
        self.assertFalse(session.capabilities["persistent_checkpoint_restart"])
        with self.assertRaises(UnsupportedSessionCapability):
            session.step()

    def test_export_is_a_normal_valid_replay_bundle(self):
        session = self.make_transient()
        session.pause()
        session.step()
        session.save_checkpoint()
        session.resume()
        session.run_to_time(0.001)
        with tempfile.TemporaryDirectory() as tmp:
            replay = session.export_bundle(tmp)
            validated = validate_replay_bundle(tmp)
            self.assertEqual(replay, validated)
            self.assertTrue((Path(tmp) / "commands.json").is_file())
            self.assertTrue((Path(tmp) / "session.json").is_file())
            self.assertEqual(len(replay["checkpoints"]), 1)
            self.assertTrue((Path(tmp) / replay["checkpoints"][0]["path"]).is_file())


if __name__ == "__main__":
    unittest.main()
