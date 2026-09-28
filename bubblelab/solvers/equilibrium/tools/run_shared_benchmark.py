#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.solvers.equilibrium.shared_benchmarks import (  # noqa: E402
    assert_b04,
    assert_b05,
    b04_equal_pressure_flatness,
    b05_unequal_pressure_curvature,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run shared-film equilibrium benchmarks")
    parser.add_argument("benchmark", choices=("b04", "b05"))
    parser.add_argument("--assert", dest="assert_metrics", action="store_true")
    args = parser.parse_args()

    if args.benchmark == "b04":
        metrics = b04_equal_pressure_flatness()
        if args.assert_metrics:
            assert_b04(metrics)
    else:
        metrics = b05_unequal_pressure_curvature()
        if args.assert_metrics:
            assert_b05(metrics)

    print(json.dumps(metrics, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
