#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.runtime.session_control import create_session


def _load_commands(path: str | Path) -> list[object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("commands"), list):
        return payload["commands"]
    raise ValueError("command file must be an array or an object with a commands array")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario")
    parser.add_argument("--commands", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--backend",
        choices=["equilibrium", "transient", "thinfilm", "thinfilm-events"],
    )
    args = parser.parse_args()

    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    session = create_session(scenario, args.backend)
    for command in _load_commands(args.commands):
        session.execute(command)
    replay = session.export_bundle(args.output)
    print(
        json.dumps(
            {
                "output": args.output,
                "backend": session.backend,
                "state": session.state.value,
                "physical_time_s": session.physical_time_s,
                "frames": len(replay["frames"]),
                "commands": len(session.command_history),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
