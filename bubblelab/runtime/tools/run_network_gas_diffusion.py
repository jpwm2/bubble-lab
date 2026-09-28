#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.runtime.network_gas_diffusion_runtime import run_frames


DEFAULT_SCENARIO = (
    ROOT / "bubblelab/scenarios/runtime/manybubble-gas-diffusion.scenario.json"
)


def _by_id(frame: dict) -> dict[str, dict]:
    return {bubble["id"]: bubble for bubble in frame["bubbles"]}


def _assert_run(scenario: dict, frames: list[dict]) -> dict:
    first = frames[0]
    last = frames[-1]
    initial = _by_id(first)
    final = _by_id(last)
    smallest_id = min(initial, key=lambda key: initial[key]["volume_m3"])
    largest_id = max(initial, key=lambda key: initial[key]["volume_m3"])

    initial_total = first["diagnostics"]["total_amount_mol"]
    final_total = last["diagnostics"]["total_amount_mol"]
    relative_drift = abs(final_total - initial_total) / initial_total

    assert tuple(initial) == tuple(final), "gas region identity changed"
    assert len(initial) >= 3, "runtime requires at least three gas regions"
    assert len(last["film_regions"]) >= 2, "runtime requires multiple shared films"
    assert last["diagnostics"]["max_simultaneous_active_edges"] >= 2
    assert relative_drift <= 1.0e-12
    assert last["diagnostics"]["worst_total_moles_relative_drift"] <= 1.0e-12
    assert last["diagnostics"]["worst_edge_antisymmetry_residual_mol"] <= 1.0e-30
    assert final[smallest_id]["volume_m3"] < initial[smallest_id]["volume_m3"]
    assert final[largest_id]["volume_m3"] > initial[largest_id]["volume_m3"]
    assert final[smallest_id]["pressure_pa"] > initial[smallest_id]["pressure_pa"]
    assert final[largest_id]["pressure_pa"] < initial[largest_id]["pressure_pa"]

    repeat = run_frames(copy.deepcopy(scenario), frame_count=len(frames))
    assert json.dumps(frames, sort_keys=True) == json.dumps(
        repeat, sort_keys=True
    ), "runtime replay is not deterministic"

    disabled = copy.deepcopy(scenario)
    disabled["user_editable"]["gas_diffusion"]["enabled"] = False
    disabled_frames = run_frames(disabled, frame_count=len(frames))
    disabled_initial = _by_id(disabled_frames[0])
    disabled_final = _by_id(disabled_frames[-1])
    for region_id in disabled_initial:
        assert (
            disabled_initial[region_id]["amount_mol"]
            == disabled_final[region_id]["amount_mol"]
        )
        assert (
            disabled_initial[region_id]["volume_m3"]
            == disabled_final[region_id]["volume_m3"]
        )
    assert disabled_frames[-1]["diagnostics"]["max_simultaneous_active_edges"] == 0

    return {
        "passed": True,
        "frame_count": len(frames),
        "region_count": len(initial),
        "shared_film_edge_count": len(last["film_regions"]),
        "max_simultaneous_active_edges": last["diagnostics"][
            "max_simultaneous_active_edges"
        ],
        "total_moles_relative_drift": relative_drift,
        "worst_total_moles_relative_drift": last["diagnostics"][
            "worst_total_moles_relative_drift"
        ],
        "max_edge_antisymmetry_residual_mol": last["diagnostics"][
            "worst_edge_antisymmetry_residual_mol"
        ],
        "smallest_region_id": smallest_id,
        "smallest_initial_volume_m3": initial[smallest_id]["volume_m3"],
        "smallest_final_volume_m3": final[smallest_id]["volume_m3"],
        "largest_region_id": largest_id,
        "largest_initial_volume_m3": initial[largest_id]["volume_m3"],
        "largest_final_volume_m3": final[largest_id]["volume_m3"],
        "deterministic_repeat": True,
        "disabled_transfer_stationary": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument("--frames", type=int, default=9)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--assert", dest="assert_run", action="store_true")
    args = parser.parse_args()

    scenario = json.loads(args.scenario.read_text())
    frames = run_frames(scenario, frame_count=args.frames)
    result = {
        "scenario": scenario["name"],
        "summary": _assert_run(scenario, frames) if args.assert_run else {},
        "frames": frames,
    }
    payload = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
