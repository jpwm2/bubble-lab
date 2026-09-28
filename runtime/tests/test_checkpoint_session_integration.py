from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from bubblelab.runtime.bundle import validate_replay_bundle
from bubblelab.runtime.checkpoint_runtime import authoritative_runtime_state
from bubblelab.runtime.session_control import RuntimeSession, SessionState
from bubblelab.solvers.transient.checkpoint import canonical_bytes


BUBBLELAB = Path(__file__).resolve().parents[2]
ROOT = BUBBLELAB.parent
SCENARIOS = BUBBLELAB / "scenarios" / "runtime"
TOOL = BUBBLELAB / "runtime" / "tools" / "run_checkpoint_session.py"


def _scenario(name: str = "checkpoint-transient.scenario.json") -> dict:
    return json.loads((SCENARIOS / name).read_text(encoding="utf-8"))


def _advance(session: RuntimeSession, count: int) -> None:
    if session.state in {SessionState.CREATED, SessionState.RUNNING}:
        session.pause()
    for _ in range(count):
        session.step()


class RuntimeSessionCheckpointIntegrationTests(unittest.TestCase):
    def test_live_transient_advertises_and_saves_canonical_checkpoint(self):
        session = RuntimeSession(_scenario(), "transient")
        self.assertTrue(session.capabilities["persistent_checkpoint_restart"])
        _advance(session, 2)

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "checkpoint.json"
            result = session.save_checkpoint(target)
            document = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(result["result"], "ACCEPTED")
        self.assertEqual(result["emitted_checkpoint_ids"], [document["frame_id"]])
        self.assertEqual(document["kind"], "CHECKPOINT")
        self.assertTrue(document["checkpoint_state"]["same_build_only"])
        self.assertEqual(
            document["checkpoint_state"]["source_scenario"]["sha256"],
            session.source_scenario_sha256,
        )
        self.assertEqual(canonical_bytes(session.checkpoints[0]), canonical_bytes(document))
        self.assertEqual(session.command_history[-1]["command"], "SAVE_CHECKPOINT")

    def test_session_restore_continues_exactly_and_records_provenance(self):
        scenario = _scenario()
        uninterrupted = RuntimeSession(scenario, "transient")
        _advance(uninterrupted, 5)

        partial = RuntimeSession(scenario, "transient")
        _advance(partial, 3)
        partial.save_checkpoint()
        document = partial.checkpoints[-1]

        restored = RuntimeSession.from_checkpoint(document)
        restore_record = restored.command_history[-1]
        self.assertEqual(restore_record["command"], "RESTORE_CHECKPOINT")
        self.assertEqual(restore_record["result"], "ACCEPTED")
        self.assertEqual(
            restore_record["requested"]["continuation_sha256"],
            document["checkpoint_state"]["integrity"]["continuation_sha256"],
        )
        self.assertTrue(restored.capabilities["persistent_checkpoint_restart"])
        _advance(restored, 2)

        self.assertEqual(
            canonical_bytes(authoritative_runtime_state(uninterrupted)),
            canonical_bytes(authoritative_runtime_state(restored)),
        )

    def test_export_bundle_carries_checkpoint_file_and_provenance(self):
        session = RuntimeSession(_scenario(), "transient")
        _advance(session, 1)
        session.save_checkpoint()

        with tempfile.TemporaryDirectory() as tmp:
            replay = session.export_bundle(tmp)
            validated = validate_replay_bundle(tmp)
            metadata = json.loads(
                (Path(tmp) / "session.json").read_text(encoding="utf-8")
            )
            checkpoint_ref = replay["checkpoints"][0]
            checkpoint = json.loads(
                (Path(tmp) / checkpoint_ref["path"]).read_text(encoding="utf-8")
            )

        self.assertEqual(replay, validated)
        self.assertEqual(len(replay["checkpoints"]), 1)
        self.assertEqual(replay["fidelity"]["checkpoint_continuation"], "SAME_BUILD_EXACT")
        self.assertTrue(metadata["capabilities"]["persistent_checkpoint_restart"])
        self.assertEqual(metadata["checkpoint_count"], 1)
        self.assertEqual(metadata["checkpoints"][0]["frame_id"], checkpoint["frame_id"])
        self.assertTrue(metadata["checkpoints"][0]["same_build_only"])
        self.assertEqual(
            metadata["checkpoints"][0]["integrity"]["continuation_sha256"],
            checkpoint["checkpoint_state"]["integrity"]["continuation_sha256"],
        )

    def test_cli_uses_fresh_process_and_asserts_exact_session_continuation(self):
        with tempfile.TemporaryDirectory() as tmp:
            command = [
                sys.executable,
                str(TOOL),
                str(SCENARIOS / "checkpoint-transient.scenario.json"),
                "--output",
                tmp,
                "--assert-exact",
            ]
            completed = subprocess.run(
                command,
                cwd=ROOT,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            summary = json.loads(completed.stdout.strip().splitlines()[-1])

        self.assertTrue(summary["fresh_process_restart"])
        self.assertNotEqual(summary["parent_pid"], summary["restart_pid"])
        self.assertTrue(summary["persistent_checkpoint_restart"])
        self.assertTrue(summary["same_build_only"])
        self.assertTrue(summary["states_exact"])
        self.assertTrue(summary["digests_exact"])
        self.assertEqual(summary["save_record"]["command"], "SAVE_CHECKPOINT")
        self.assertEqual(summary["restore_record"]["command"], "RESTORE_CHECKPOINT")


if __name__ == "__main__":
    unittest.main()
