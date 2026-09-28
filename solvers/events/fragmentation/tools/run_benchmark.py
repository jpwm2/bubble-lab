#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))

from bubblelab.solvers.events.fragmentation.benchmarks import conservation_benchmark, neck_split_benchmark, refinement_benchmark


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmark", choices=("neck-split", "conservation", "refinement"))
    parser.add_argument("--assert", dest="assert_result", action="store_true")
    args = parser.parse_args()
    runner = {
        "neck-split": neck_split_benchmark,
        "conservation": conservation_benchmark,
        "refinement": refinement_benchmark,
    }[args.benchmark]
    print(json.dumps(runner(args.assert_result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
