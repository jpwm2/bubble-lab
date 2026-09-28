#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.runtime.runner import run_scenario


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the canonical supported two-bubble contact transition."
    )
    parser.add_argument("scenario")
    parser.add_argument("--frames", type=int, default=12)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    replay = run_scenario(
        scenario,
        "contact-transition",
        args.output,
        frames=args.frames,
    )
    print(json.dumps({
        "valid": True,
        "frames": len(replay["frames"]),
        "contact_event_time_s": replay["backend"]["contact_event_time_s"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
