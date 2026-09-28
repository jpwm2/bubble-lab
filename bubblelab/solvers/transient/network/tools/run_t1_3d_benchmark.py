#!/usr/bin/env python3
"""Run one bounded genuine-3D production T1 acceptance benchmark."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bubblelab.solvers.transient.network.t1_3d import run_t1_3d_benchmark


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("name", choices=("switch", "conservation", "refinement"))
    parser.add_argument("--assert", dest="assert_pass", action="store_true")
    args = parser.parse_args()
    result = run_t1_3d_benchmark(args.name)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if args.assert_pass and not bool(result.get("pass")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
