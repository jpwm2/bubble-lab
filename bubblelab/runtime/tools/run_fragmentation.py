#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from bubblelab.runtime.fragmentation_runtime import run_fragmentation_scenario


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    replay = run_fragmentation_scenario(scenario, args.output)
    print(json.dumps(replay, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
