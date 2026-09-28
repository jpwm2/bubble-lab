#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.solvers.events.benchmarks import (  # noqa: E402
    coalescence_conservation_benchmark,
    event_replay_benchmark,
    rupture_convergence_benchmark,
    rupture_threshold_benchmark,
)

BENCHMARKS = {
    "rupture-threshold": rupture_threshold_benchmark,
    "coalescence-conservation": coalescence_conservation_benchmark,
    "rupture-convergence": rupture_convergence_benchmark,
    "event-replay": event_replay_benchmark,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic bubble topology-event benchmarks")
    parser.add_argument("benchmark", choices=sorted(BENCHMARKS))
    parser.add_argument("--assert", dest="assert_pass", action="store_true")
    args = parser.parse_args()
    result = BENCHMARKS[args.benchmark](assert_pass=args.assert_pass)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
