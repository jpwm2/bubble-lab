#!/usr/bin/env python3
"""Run exact production-window transient release benchmarks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.solvers.transient.release_benchmarks import BENCHMARKS, PRIOR_COST_REFERENCE


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmark", choices=sorted(BENCHMARKS))
    parser.add_argument("--assert", dest="assert_pass", action="store_true")
    parser.add_argument("--eta-b-max", type=float, default=0.02)
    parser.add_argument("--b02-qualified-surface", action="store_true")
    parser.add_argument("--capillary-times", type=float)
    parser.add_argument("--characteristic-times", type=float)
    args = parser.parse_args()

    kwargs = {
        "eta_b_max": args.eta_b_max,
        "b02_qualified_surface": args.b02_qualified_surface,
    }
    if args.capillary_times is not None:
        kwargs["capillary_times"] = args.capillary_times
    if args.characteristic_times is not None:
        kwargs["characteristic_times"] = args.characteristic_times

    result = BENCHMARKS[args.benchmark](**kwargs)
    result["prior_measured_cost_reference"] = PRIOR_COST_REFERENCE
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.assert_pass and not result["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
