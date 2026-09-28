#!/usr/bin/env python3
"""Export a deterministic canonical contract-v1 demo frame."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CONTRACT_PYTHON = ROOT / "bubblelab" / "python"
if str(CONTRACT_PYTHON) not in sys.path:
    sys.path.insert(0, str(CONTRACT_PYTHON))

from bubblelab.solvers.transient import AMRConfig, GridConfig, TimeStepPolicy, TransientConfig, TransientSoapFilmSolver, frame_dict, icosphere
from bubblelab_contract.validation import assert_valid


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    front = icosphere(radius_m=0.01, subdivisions=1, surface_tension_n_m=0.05)
    config = TransientConfig(
        grid=GridConfig(cells=(8, 8, 8), origin_m=(-0.025, -0.025, -0.025), extent_m=(0.05, 0.05, 0.05)),
        amr=AMRConfig(enabled=True, max_levels=1, front_band_cells=0.90),
        gravity_m_s2=(0.0, -9.81, 0.0),
        timestep=TimeStepPolicy(max_dt_s=1.0e-4),
        deterministic_seed=17,
    )
    solver = TransientSoapFilmSolver([front], config)
    solver.step()
    frame = frame_dict(solver, "transient-demo-000001")
    assert_valid(frame)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(frame, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
