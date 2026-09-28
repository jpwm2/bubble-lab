#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.solvers.gas_network.benchmarks import BENCHMARKS
from bubblelab.solvers.gas_network.multievent_topology_benchmarks import (
    MULTIEVENT_TOPOLOGY_BENCHMARKS,
)
from bubblelab.solvers.gas_network.repeated_topology_benchmarks import (
    REPEATED_TOPOLOGY_BENCHMARKS,
)
from bubblelab.solvers.gas_network.topology_benchmarks import TOPOLOGY_BENCHMARKS


ALL_BENCHMARKS = {
    **BENCHMARKS,
    **TOPOLOGY_BENCHMARKS,
    **REPEATED_TOPOLOGY_BENCHMARKS,
    **MULTIEVENT_TOPOLOGY_BENCHMARKS,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmark", choices=sorted(ALL_BENCHMARKS))
    parser.add_argument("--assert", dest="assert_pass", action="store_true")
    args = parser.parse_args()
    result = ALL_BENCHMARKS[args.benchmark]()
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.assert_pass and not result["passed"]:
        raise SystemExit(f"{args.benchmark} benchmark failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
