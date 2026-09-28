from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from bubblelab.runtime.checkpoint_runtime import (
    CheckpointRuntimeError,
    authoritative_runtime_state,
    checkpoint_document,
    restore_session,
)
from bubblelab.runtime.session_control import create_session
from bubblelab.solvers.transient.checkpoint import canonical_bytes


BUBBLELAB = Path(__file__).resolve().parents[2]


def _scenario(name: str):
    return json.loads(
        (BUBBLELAB / "scenarios" / "runtime" / name).read_text(encoding="utf-8")
    )


def _advance(session, count: int) -> None:
    session.pause()
    for _ in range(count):
        session.step()


class RuntimeCheckpointRestartTests(unittest.TestCase):
    def test_transient_checkpoint_restart_matches_uninterrupted_state(self):
        scenario = _scenario("checkpoint-transient.scenario.json")

        uninterrupted = create_session(scenario, "transient")
        _advance(uninterrupted, 5)

        partial = create_session(scenario, "transient")
        _advance(partial, 3)
        document = checkpoint_document(partial)
        self.assertEqual(document["kind"], "CHECKPOINT")
        self.assertTrue(document["checkpoint_state"]["same_build_only"])
        self.assertEqual(
            document["checkpoint_state"]["source_scenario"]["sha256"],
            partial.source_scenario_sha256,
        )

        restored = restore_session(json.loads(canonical_bytes(document)))
        for _ in range(2):
            restored.step()

        self.assertEqual(
            canonical_bytes(authoritative_runtime_state(uninterrupted)),
            canonical_bytes(authoritative_runtime_state(restored)),
        )

    def test_corrupt_continuation_digest_is_rejected(self):
        scenario = _scenario("checkpoint-transient.scenario.json")
        session = create_session(scenario, "transient")
        _advance(session, 1)
        document = checkpoint_document(session)
        corrupt = copy.deepcopy(document)
        corrupt["checkpoint_state"]["continuation"]["solver"]["step_index"] += 1
        with self.assertRaisesRegex(CheckpointRuntimeError, "integrity digest"):
            restore_session(corrupt)

    def test_thinfilm_restart_preserves_fields_amounts_and_continuation(self):
        scenario = _scenario("checkpoint-thinfilm.scenario.json")
        original = create_session(scenario, "transient")
        _advance(original, 2)
        document = checkpoint_document(original)
        restored = restore_session(json.loads(canonical_bytes(document)))

        before = authoritative_runtime_state(original)
        after = authoritative_runtime_state(restored)
        self.assertEqual(canonical_bytes(before), canonical_bytes(after))
        self.assertIsNotNone(after["thinfilm"])
        self.assertIn("liquid_amount_m3", after["thinfilm"])
        self.assertIn("surfactant_amount_mol", after["thinfilm"])

        original.step()
        restored.step()
        self.assertEqual(
            canonical_bytes(authoritative_runtime_state(original)),
            canonical_bytes(authoritative_runtime_state(restored)),
        )


if __name__ == "__main__":
    unittest.main()
