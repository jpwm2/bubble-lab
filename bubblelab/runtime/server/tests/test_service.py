from __future__ import annotations

import json
import unittest
from pathlib import Path

from bubblelab.runtime.server.service import LiveSessionService, LiveSessionTransportError

ROOT = Path(__file__).resolve().parents[4]
SCENARIO = ROOT / "bubblelab" / "scenarios" / "runtime" / "transient-wind.scenario.json"


def load_scenario() -> dict:
    return json.loads(SCENARIO.read_text(encoding="utf-8"))


class LiveSessionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = LiveSessionService()
        self.created = self.service.create_session(load_scenario())
        self.session_id = self.created["session_id"]

    def test_create_and_read_expose_authoritative_initial_frame(self):
        self.assertEqual(self.created["snapshot"]["state"], "CREATED")
        self.assertEqual(self.created["snapshot"]["physical_time_s"], 0.0)
        self.assertEqual(self.created["snapshot"]["frame_index"], 0)
        self.assertEqual(self.created["latest_frame"]["kind"], "FRAME")
        self.assertEqual(
            self.created["latest_frame"]["simulation_time_s"],
            self.created["snapshot"]["physical_time_s"],
        )
        fetched = self.service.get_session(self.session_id)
        self.assertEqual(fetched, self.created)

    def test_pause_step_resume_run_to_time_are_backend_authoritative(self):
        paused = self.service.execute_command(self.session_id, {"command": "PAUSE"})
        self.assertEqual(paused["snapshot"]["state"], "PAUSED")
        self.assertEqual(paused["snapshot"]["physical_time_s"], 0.0)
        stepped = self.service.execute_command(self.session_id, {"command": "STEP"})
        self.assertEqual(stepped["snapshot"]["state"], "PAUSED")
        self.assertEqual(stepped["snapshot"]["frame_index"], 1)
        self.assertGreater(stepped["snapshot"]["physical_time_s"], 0.0)
        self.assertEqual(len(stepped["command_result"]["emitted_frame_ids"]), 1)
        resumed = self.service.execute_command(self.session_id, {"command": "RESUME"})
        self.assertEqual(resumed["snapshot"]["state"], "RUNNING")
        target = max(0.001, resumed["snapshot"]["physical_time_s"] + 0.0001)
        advanced = self.service.execute_command(
            self.session_id,
            {"command": "RUN_TO_TIME", "target_time_s": target},
        )
        self.assertEqual(advanced["snapshot"]["state"], "PAUSED")
        self.assertAlmostEqual(advanced["snapshot"]["physical_time_s"], target, places=15)
        self.assertEqual(
            advanced["latest_frame"]["simulation_time_s"],
            advanced["snapshot"]["physical_time_s"],
        )

    def test_rejected_command_returns_rejected_authoritative_history(self):
        with self.assertRaises(LiveSessionTransportError) as caught:
            self.service.execute_command(self.session_id, {"command": "STEP"})
        error = caught.exception
        self.assertEqual(error.code, "invalid_command")
        self.assertEqual(error.status, 409)
        self.assertIsNotNone(error.session_payload)
        self.assertEqual(error.session_payload["command_result"]["result"], "REJECTED")
        self.assertEqual(error.session_payload["snapshot"]["state"], "CREATED")
        self.assertEqual(error.session_payload["snapshot"]["physical_time_s"], 0.0)

    def test_checkpoint_is_in_memory_and_browser_path_is_forbidden(self):
        saved = self.service.save_checkpoint(self.session_id)
        self.assertEqual(saved["checkpoint"]["kind"], "CHECKPOINT")
        self.assertTrue(saved["checkpoint_provenance"]["same_build_only"])
        self.assertEqual(saved["snapshot"]["checkpoint_count"], 1)
        checkpoint_id = saved["checkpoint"]["frame_id"]
        fetched = self.service.get_checkpoint(self.session_id, checkpoint_id)
        self.assertEqual(fetched["checkpoint"], saved["checkpoint"])
        with self.assertRaises(LiveSessionTransportError) as caught:
            self.service.execute_command(
                self.session_id,
                {"command": "SAVE_CHECKPOINT", "path": "../../outside.json"},
            )
        self.assertEqual(caught.exception.code, "filesystem_path_forbidden")
        self.assertEqual(self.service.get_session(self.session_id)["snapshot"]["checkpoint_count"], 1)

    def test_reset_and_close(self):
        self.service.execute_command(self.session_id, {"command": "PAUSE"})
        self.service.execute_command(self.session_id, {"command": "STEP"})
        reset = self.service.execute_command(self.session_id, {"command": "RESET"})
        self.assertEqual(reset["snapshot"]["state"], "CREATED")
        self.assertEqual(reset["snapshot"]["physical_time_s"], 0.0)
        self.assertEqual(reset["snapshot"]["frame_index"], 0)
        closed = self.service.close_session(self.session_id)
        self.assertTrue(closed["closed"])
        with self.assertRaises(LiveSessionTransportError) as caught:
            self.service.get_session(self.session_id)
        self.assertEqual(caught.exception.status, 404)

    def test_backend_selection_is_allowlisted(self):
        scenario = load_scenario()
        scenario["requested_solver"]["backend"] = "python.module:arbitrary"
        with self.assertRaises(LiveSessionTransportError) as caught:
            LiveSessionService().create_session(scenario)
        self.assertEqual(caught.exception.code, "unsupported_backend")


if __name__ == "__main__":
    unittest.main()
