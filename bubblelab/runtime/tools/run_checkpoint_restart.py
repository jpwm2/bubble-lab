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
    restore_session_from_file,
    write_checkpoint,
)
from bubblelab.runtime.session_control import SessionState, create_session
from bubblelab.solvers.transient.checkpoint import canonical_bytes


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def _advance_steps(session, count: int) -> None:
    if count < 0:
        raise ValueError("step count must be non-negative")
    if session.state == SessionState.CREATED:
        session.pause()
    elif session.state == SessionState.RUNNING:
        session.pause()
    if session.state != SessionState.PAUSED:
        raise RuntimeError(f"cannot advance restored session from state {session.state.value}")
    for _ in range(count):
        session.step()


def _resume_worker(argv: list[str]) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--steps-after", required=True, type=int)
    parser.add_argument("--state-output", required=True)
    parser.add_argument("--process-output", required=True)
    args = parser.parse_args(argv)

    session = restore_session_from_file(args.checkpoint)
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
        },
    )


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--resume-worker":
        _resume_worker(sys.argv[2:])
        return

    parser = argparse.ArgumentParser()
    parser.add_argument("scenario")
    parser.add_argument("--steps-before", type=int, required=True)
    parser.add_argument("--steps-after", type=int, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if args.steps_before < 0 or args.steps_after < 0:
        raise ValueError("step counts must be non-negative")

    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    output = Path(args.output)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    uninterrupted = create_session(scenario, "transient")
    _advance_steps(uninterrupted, args.steps_before + args.steps_after)
    uninterrupted_state = authoritative_runtime_state(uninterrupted)
    _write_json(output / "uninterrupted-state.json", uninterrupted_state)

    partial = create_session(scenario, "transient")
    _advance_steps(partial, args.steps_before)
    checkpoint_path = output / "checkpoint.json"
    checkpoint = write_checkpoint(partial, checkpoint_path)

    restarted_state_path = output / "restarted-state.json"
    process_path = output / "restart-process.json"
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--resume-worker",
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
    if int(process["pid"]) == os.getpid():
        raise RuntimeError("restart qualification did not execute in a fresh process")

    restarted_state = json.loads(restarted_state_path.read_text(encoding="utf-8"))
    summary = {
        "scenario": str(Path(args.scenario)),
        "steps_before": args.steps_before,
        "steps_after": args.steps_after,
        "parent_pid": os.getpid(),
        "restart_pid": int(process["pid"]),
        "fresh_process_restart": True,
        "checkpoint_frame_id": checkpoint["frame_id"],
        "checkpoint_time_s": checkpoint["simulation_time_s"],
        "uninterrupted_digest": authoritative_runtime_digest(uninterrupted),
        "restarted_digest": process["final_digest"],
        "states_exact": uninterrupted_state == restarted_state,
        "child_stdout": child.stdout,
        "child_stderr": child.stderr,
    }
    _write_json(output / "summary.json", summary)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
