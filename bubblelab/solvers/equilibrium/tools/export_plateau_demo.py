#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.solvers.equilibrium.plateau_benchmarks import plateau_three_result  # noqa: E402
from bubblelab.solvers.equilibrium.plateau_export import canonical_plateau_frame  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a solved three-film Plateau-junction FRAME")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    frame = canonical_plateau_frame(plateau_three_result())
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(frame, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
