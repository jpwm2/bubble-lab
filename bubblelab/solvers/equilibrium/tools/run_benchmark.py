#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.solvers.equilibrium.benchmarks import (  # noqa: E402
    assert_convergence,
    assert_sphere,
    sphere_case,
    sphere_convergence,
)
from bubblelab.solvers.equilibrium.shared_benchmarks import (  # noqa: E402
    assert_b04,
    assert_b05,
    b04_equal_pressure_flatness,
    b05_unequal_pressure_curvature,
)
from bubblelab.solvers.equilibrium.plateau_benchmarks import (  # noqa: E402
    assert_plateau_convergence,
    assert_plateau_three,
    plateau_convergence,
    plateau_three,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Bubble Lab equilibrium benchmarks")
    parser.add_argument(
        "benchmark",
        choices=(
            "sphere",
            "sphere-convergence",
            "two-bubble-equal",
            "two-bubble-unequal",
            "plateau-three",
            "plateau-convergence",
        ),
    )
    parser.add_argument("--assert", dest="assert_metrics", action="store_true")
    args = parser.parse_args()

    if args.benchmark == "sphere":
        metrics = sphere_case()
        if args.assert_metrics:
            assert_sphere(metrics)
    elif args.benchmark == "sphere-convergence":
        metrics = sphere_convergence()
        if args.assert_metrics:
            assert_convergence(metrics)
    elif args.benchmark == "two-bubble-equal":
        metrics = b04_equal_pressure_flatness()
        if args.assert_metrics:
            assert_b04(metrics)
    elif args.benchmark == "two-bubble-unequal":
        metrics = b05_unequal_pressure_curvature()
        if args.assert_metrics:
            assert_b05(metrics)
    elif args.benchmark == "plateau-three":
        metrics = plateau_three()
        if args.assert_metrics:
            assert_plateau_three(metrics)
    else:
        metrics = plateau_convergence()
        if args.assert_metrics:
            assert_plateau_convergence(metrics)

    print(json.dumps(metrics, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
