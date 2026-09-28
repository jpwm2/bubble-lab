#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
from bubblelab.solvers.events.rim_breakup.benchmarks import assert_benchmark as assert_legacy_benchmark, run as run_legacy
from bubblelab.solvers.events.rim_breakup.multihole_benchmarks import assert_benchmark as assert_multihole_benchmark, run as run_multihole

LEGACY = ("retraction","ligament","conservation","refinement","replay","asymmetric-retraction","mode-competition","multimode-conservation","multimode-response","multimode-refinement","multimode-replay")
MULTIHOLE = ("multihole-interaction","multihole-mode-coupling","multihole-conservation","multihole-response","multihole-refinement","multihole-replay")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmark", choices=LEGACY + MULTIHOLE)
    parser.add_argument("--assert", dest="assert_result", action="store_true")
    args = parser.parse_args()
    if args.benchmark in MULTIHOLE:
        payload = run_multihole(args.benchmark)
        if args.assert_result:
            assert_multihole_benchmark(args.benchmark, payload)
    else:
        payload = run_legacy(args.benchmark)
        if args.assert_result:
            assert_legacy_benchmark(args.benchmark, payload)
    print(json.dumps(payload, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
