#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks import neck_detection_benchmark, neck_resolution_benchmark, split_bookkeeping_benchmark


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmark", choices=("neck-detection", "split-bookkeeping", "neck-resolution"))
    parser.add_argument("--assert", dest="assert_result", action="store_true")
    args = parser.parse_args()
    runner = {
        "neck-detection": neck_detection_benchmark,
        "split-bookkeeping": split_bookkeeping_benchmark,
        "neck-resolution": neck_resolution_benchmark,
    }[args.benchmark]
    result = runner(args.assert_result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
