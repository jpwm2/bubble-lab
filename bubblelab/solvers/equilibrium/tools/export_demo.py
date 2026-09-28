#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.solvers.equilibrium.export import canonical_frame  # noqa: E402
from bubblelab.solvers.equilibrium.solver import solve_prescribed_volume  # noqa: E402
from bubblelab.solvers.equilibrium.sphere import icosphere, sphere_volume  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a canonical equilibrium demo frame")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    radius_m = 0.01
    tension = 0.05
    target = sphere_volume(radius_m)
    result = solve_prescribed_volume(icosphere(4, radius_m), target, tension)
    frame = canonical_frame(result, target_volume_m3=target, sheet_tension_n_m=tension)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(frame, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
