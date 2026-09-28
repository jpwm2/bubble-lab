from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))

from bubblelab.solvers.events.pinchoff.benchmarks import (
    assert_benchmark,
    conservation_benchmark,
    neck_benchmark,
    refinement_benchmark,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run supported axisymmetric pinch-off evidence")
    parser.add_argument("benchmark", choices=("neck", "refinement", "conservation"))
    parser.add_argument("--assert", dest="assert_result", action="store_true")
    args = parser.parse_args()
    runners = {
        "neck": neck_benchmark,
        "refinement": refinement_benchmark,
        "conservation": conservation_benchmark,
    }
    payload = runners[args.benchmark]()
    if args.assert_result:
        assert_benchmark(args.benchmark, payload)
    print(json.dumps(payload, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
