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

from bubblelab.runtime.topology_gas_transport_runtime import run_frames


DEFAULT_SCENARIO = ROOT / "bubblelab/scenarios/runtime/topology-gas-t1.scenario.json"


def _by_id(frame: dict) -> dict[str, dict]:
    return {item["id"]: item for item in frame["bubbles"]}


def _assert_run(scenario: dict, frames: list[dict]) -> dict:
    if len(frames) <= scenario["user_editable"]["topology_gas_transport"]["t1_frame_index"]:
        raise AssertionError("runtime assertion requires frames through the configured T1 event")
    first = frames[0]
    last = frames[-1]
    event_frames = [frame for frame in frames if frame["diagnostics"]["event_performed"]]
    assert event_frames, "configured T1 event never occurred"
    event_frame = event_frames[0]
    event = event_frame["topology_event"]
    assert event is not None

    initial = _by_id(first)
    final = _by_id(last)
    assert tuple(initial) == tuple(final), "gas region identity changed"
    assert len(initial) >= 4, "bounded T1 gas runtime requires four stable regions"
    assert first["diagnostics"]["topology_revision"] == 0
    assert event_frame["diagnostics"]["topology_revision"] == 1
    assert last["diagnostics"]["topology_revision"] == 1
    assert event["gas_state_unchanged_during_surgery"]
    assert event["gas_amount_relative_drift"] <= 1.0e-12

    retired = set(event["retired_film_ids"])
    created = set(event["created_film_ids"])
    assert not retired.intersection(last["diagnostics"]["edge_ids"])
    assert created.issubset(set(last["diagnostics"]["edge_ids"]))
    assert last["diagnostics"]["max_simultaneous_active_edges"] >= 2
    assert last["diagnostics"]["total_amount_relative_drift_from_initial"] <= 1.0e-12
    assert last["diagnostics"]["worst_transport_step_relative_drift"] <= 1.0e-12
    assert last["diagnostics"]["worst_edge_antisymmetry_residual_mol"] <= 1.0e-30
    created_film = next(item for item in last["film_regions"] if item["id"] in created)
    assert created_film["cumulative_transfer_a_to_b_mol"] != 0.0

    repeat = run_frames(copy.deepcopy(scenario), frame_count=len(frames))
    assert json.dumps(frames, sort_keys=True) == json.dumps(
        repeat, sort_keys=True
    ), "topology-changing runtime replay is not deterministic"

    disabled = copy.deepcopy(scenario)
    disabled["user_editable"]["topology_gas_transport"]["enabled"] = False
    disabled_frames = run_frames(disabled, frame_count=len(frames))
    disabled_initial = _by_id(disabled_frames[0])
    disabled_final = _by_id(disabled_frames[-1])
    for region_id in disabled_initial:
        assert disabled_initial[region_id]["amount_mol"] == disabled_final[region_id]["amount_mol"]
        assert disabled_initial[region_id]["volume_m3"] == disabled_final[region_id]["volume_m3"]
        assert disabled_initial[region_id]["pressure_pa"] == disabled_final[region_id]["pressure_pa"]
    assert disabled_frames[-1]["diagnostics"]["topology_revision"] == 1
    assert disabled_frames[-1]["diagnostics"]["max_simultaneous_active_edges"] == 0

    return {
        "passed": True,
        "frame_count": len(frames),
        "region_count": len(initial),
        "pre_edge_ids": first["diagnostics"]["edge_ids"],
        "post_edge_ids": last["diagnostics"]["edge_ids"],
        "retired_film_ids": event["retired_film_ids"],
        "created_film_ids": event["created_film_ids"],
        "total_amount_relative_drift": last["diagnostics"][
            "total_amount_relative_drift_from_initial"
        ],
        "max_simultaneous_active_edges": last["diagnostics"][
            "max_simultaneous_active_edges"
        ],
        "created_edge_cumulative_transfer_mol": created_film[
            "cumulative_transfer_a_to_b_mol"
        ],
        "deterministic_repeat": True,
        "disabled_transfer_stationary": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument("--frames", type=int, default=7)
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
