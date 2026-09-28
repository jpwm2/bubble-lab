#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.runtime.checkpoint_runtime import (
    authoritative_runtime_digest,
    authoritative_runtime_state,
)
from bubblelab.runtime.session_control import RuntimeSession, SessionState
from bubblelab.solvers.transient.checkpoint import canonical_bytes


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def _advance_steps(session: RuntimeSession, count: int) -> None:
    if count < 0:
        raise ValueError("step count must be non-negative")
    if session.state in {SessionState.CREATED, SessionState.RUNNING}:
        session.pause()
    if session.state != SessionState.PAUSED:
        raise RuntimeError(
            f"cannot advance authoritative session from state {session.state.value}"
        )
    for _ in range(count):
        session.step()


def _restore_worker(argv: list[str]) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--steps-after", required=True, type=int)
    parser.add_argument("--state-output", required=True)
    parser.add_argument("--process-output", required=True)
    args = parser.parse_args(argv)

    session = RuntimeSession.from_checkpoint(args.checkpoint)
    if not session.capabilities["persistent_checkpoint_restart"]:
        raise RuntimeError("restored RuntimeSession did not advertise checkpoint/restart")
    if not session.command_history or session.command_history[-1]["command"] != "RESTORE_CHECKPOINT":
        raise RuntimeError("restored RuntimeSession did not record restart provenance")

    _advance_steps(session, args.steps_after)
    state = authoritative_runtime_state(session)
    _write_json(Path(args.state_output), state)
    _write_json(
        Path(args.process_output),
        {
            "pid": os.getpid(),
            "checkpoint": str(Path(args.checkpoint).resolve()),
            "steps_after": args.steps_after,
            "final_digest": authoritative_runtime_digest(session),
            "restore_record": session.command_history[-(args.steps_after + 1)],
        },
    )


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--restore-worker":
        _restore_worker(sys.argv[2:])
        return

    parser = argparse.ArgumentParser(
        description=(
            "Qualify RuntimeSession checkpoint/save plus fresh-process restore against "
            "an uninterrupted authoritative transient session."
        )
    )
    parser.add_argument("scenario")
    parser.add_argument("--output", required=True)
    parser.add_argument("--steps-before", type=int, default=3)
    parser.add_argument("--steps-after", type=int, default=2)
    parser.add_argument("--assert-exact", action="store_true")
    args = parser.parse_args()

    if args.steps_before < 0 or args.steps_after < 0:
        raise ValueError("step counts must be non-negative")

    scenario_path = Path(args.scenario)
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    output = Path(args.output)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    uninterrupted = RuntimeSession(scenario, "transient")
    _advance_steps(uninterrupted, args.steps_before + args.steps_after)
    uninterrupted_state = authoritative_runtime_state(uninterrupted)
    uninterrupted_digest = authoritative_runtime_digest(uninterrupted)
    _write_json(output / "uninterrupted-state.json", uninterrupted_state)

    partial = RuntimeSession(scenario, "transient")
    if not partial.capabilities["persistent_checkpoint_restart"]:
        raise RuntimeError("transient RuntimeSession did not advertise checkpoint/restart")
    _advance_steps(partial, args.steps_before)
    checkpoint_path = output / "checkpoint.json"
    save_record = partial.save_checkpoint(checkpoint_path)
    if save_record["result"] != "ACCEPTED" or not save_record["emitted_checkpoint_ids"]:
        raise RuntimeError("RuntimeSession checkpoint save was not accepted")
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))

    restarted_state_path = output / "restarted-state.json"
    process_path = output / "restart-process.json"
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--restore-worker",
        "--checkpoint",
        str(checkpoint_path.resolve()),
        "--steps-after",
        str(args.steps_after),
        "--state-output",
        str(restarted_state_path.resolve()),
        "--process-output",
        str(process_path.resolve()),
    ]
    child = subprocess.run(
        command,
        cwd=str(ROOT),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    process = json.loads(process_path.read_text(encoding="utf-8"))
    restart_pid = int(process["pid"])
    if restart_pid == os.getpid():
        raise RuntimeError("checkpoint restore qualification did not execute in a fresh process")

    restarted_state = json.loads(restarted_state_path.read_text(encoding="utf-8"))
    normalized_uninterrupted = json.loads(canonical_bytes(uninterrupted_state))
    states_exact = normalized_uninterrupted == restarted_state
    digests_exact = uninterrupted_digest == process["final_digest"]
    checkpoint_state = checkpoint["checkpoint_state"]
    summary = {
        "scenario": str(scenario_path),
        "steps_before": args.steps_before,
        "steps_after": args.steps_after,
        "parent_pid": os.getpid(),
        "restart_pid": restart_pid,
        "fresh_process_restart": True,
        "persistent_checkpoint_restart": partial.capabilities[
            "persistent_checkpoint_restart"
        ],
        "checkpoint_frame_id": checkpoint["frame_id"],
        "checkpoint_time_s": checkpoint["simulation_time_s"],
        "same_build_only": checkpoint_state["same_build_only"],
        "runtime_checkpoint_version": checkpoint_state["runtime_checkpoint_version"],
        "continuation_format_version": checkpoint_state[
            "continuation_format_version"
        ],
        "source_scenario_sha256": checkpoint_state["source_scenario"]["sha256"],
        "continuation_sha256": checkpoint_state["integrity"]["continuation_sha256"],
        "save_record": save_record,
        "restore_record": process["restore_record"],
        "uninterrupted_digest": uninterrupted_digest,
        "restarted_digest": process["final_digest"],
        "states_exact": states_exact,
        "digests_exact": digests_exact,
        "child_stdout": child.stdout,
        "child_stderr": child.stderr,
    }
    _write_json(output / "summary.json", summary)
    print(json.dumps(summary, sort_keys=True))

    if args.assert_exact and not (states_exact and digests_exact):
        raise SystemExit("fresh-process RuntimeSession checkpoint continuation was not exact")


if __name__ == "__main__":
    main()
