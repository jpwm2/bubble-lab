#!/usr/bin/env python3
"""Run objective transient-foundation and solid-boundary benchmarks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.solvers.transient.benchmarks import BENCHMARKS as TRANSIENT_BENCHMARKS
from bubblelab.solvers.boundary.benchmarks import BENCHMARKS as BOUNDARY_BENCHMARKS

BENCHMARKS = {**TRANSIENT_BENCHMARKS, **BOUNDARY_BENCHMARKS}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmark", choices=sorted(BENCHMARKS))
    parser.add_argument("--assert", dest="assert_pass", action="store_true")
    args = parser.parse_args()
    result = BENCHMARKS[args.benchmark]()
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.assert_pass and not result["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
