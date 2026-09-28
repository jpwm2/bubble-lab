#!/usr/bin/env python3
"""CLI for deterministic T1 research benchmarks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.research.t1.benchmarks import run_named


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmark", choices=("eligibility", "neighbor-switch", "refinement"))
    parser.add_argument("--assert", dest="assert_pass", action="store_true")
    args = parser.parse_args()
    result = run_named(args.benchmark)
    print(json.dumps(result, indent=2, sort_keys=True, default=list))
    if args.assert_pass and not result["pass"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
