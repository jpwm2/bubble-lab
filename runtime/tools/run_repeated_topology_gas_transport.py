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

from bubblelab.runtime.repeated_topology_gas_transport_runtime import run_frames


DEFAULT_SCENARIO = ROOT / "bubblelab/scenarios/runtime/repeated-topology-gas-t1.scenario.json"


def _by_id(frame: dict) -> dict[str, dict]:
    return {item["id"]: item for item in frame["bubbles"]}


def _assert_run(scenario: dict, frames: list[dict]) -> dict:
    event_frames = scenario["user_editable"]["repeated_topology_gas_transport"]["t1_frame_indices"]
    if len(frames) <= max(event_frames):
        raise AssertionError("runtime assertion requires frames through both configured T1 events")
    first = frames[0]
    last = frames[-1]
    events = last["topology_events"]
    assert len(events) == 2, "exactly two production T1 events must occur"
    first_event, second_event = events
    assert [event["event_id"] for event in events] == ["t1:000001", "t1:000002"]
    assert first_event["retired_film_ids"] != second_event["retired_film_ids"]
    assert first_event["created_film_ids"] != second_event["created_film_ids"]
    assert first_event["adjacency_after"] == second_event["adjacency_before"]
    assert first_event["topology_revision_after"] == 1
    assert second_event["topology_revision_before"] == 1
    assert second_event["topology_revision_after"] == 2
    for event in events:
        assert event["gas_state_unchanged_during_surgery"]
        assert event["gas_amount_relative_drift"] <= 1.0e-12

    initial = _by_id(first)
    final = _by_id(last)
    assert len(initial) == 6, "qualified repeated runtime requires six stable gas regions"
    assert tuple(initial) == tuple(final), "stable gas-region identity changed"
    assert first["diagnostics"]["second_event_blocked_before_first"]
    assert "adjacency already exists" in first["diagnostics"]["second_event_initial_block_reason"]
    assert last["diagnostics"]["topology_revision"] == 2
    assert last["diagnostics"]["event_count"] == 2
    assert last["diagnostics"]["max_simultaneous_active_edges"] >= 2
    assert last["diagnostics"]["total_amount_relative_drift_from_initial"] <= 1.0e-12
    assert last["diagnostics"]["worst_transport_step_relative_drift"] <= 1.0e-12
    assert last["diagnostics"]["worst_edge_antisymmetry_residual_mol"] <= 1.0e-30

    transfer_history = last["diagnostics"]["edge_transfer_history_mol"]
    first_created = first_event["created_film_ids"][0]
    second_created = second_event["created_film_ids"][0]
    assert transfer_history[first_created] != 0.0
    assert transfer_history[second_created] != 0.0
    assert first_created in last["diagnostics"]["edge_ids"]
    assert second_created in last["diagnostics"]["edge_ids"]

    repeat = run_frames(copy.deepcopy(scenario), frame_count=len(frames))
    assert json.dumps(frames, sort_keys=True) == json.dumps(
        repeat, sort_keys=True
    ), "repeated topology runtime replay is not deterministic"

    disabled = copy.deepcopy(scenario)
    disabled["user_editable"]["repeated_topology_gas_transport"]["enabled"] = False
    disabled_frames = run_frames(disabled, frame_count=len(frames))
    disabled_initial = _by_id(disabled_frames[0])
    disabled_final = _by_id(disabled_frames[-1])
    for region_id in disabled_initial:
        assert disabled_initial[region_id]["amount_mol"] == disabled_final[region_id]["amount_mol"]
        assert disabled_initial[region_id]["volume_m3"] == disabled_final[region_id]["volume_m3"]
        assert disabled_initial[region_id]["pressure_pa"] == disabled_final[region_id]["pressure_pa"]
    assert disabled_frames[-1]["diagnostics"]["topology_revision"] == 2
    assert disabled_frames[-1]["diagnostics"]["event_count"] == 2
    assert disabled_frames[-1]["diagnostics"]["max_simultaneous_active_edges"] == 0

    return {
        "passed": True,
        "frame_count": len(frames),
        "region_count": len(initial),
        "event_ids": [event["event_id"] for event in events],
        "distinct_retired_films": [event["retired_film_ids"] for event in events],
        "second_event_blocked_before_first": True,
        "first_created_film_id": first_created,
        "second_created_film_id": second_created,
        "first_created_transfer_mol": transfer_history[first_created],
        "second_created_transfer_mol": transfer_history[second_created],
        "total_amount_relative_drift": last["diagnostics"]["total_amount_relative_drift_from_initial"],
        "max_simultaneous_active_edges": last["diagnostics"]["max_simultaneous_active_edges"],
        "deterministic_repeat": True,
        "disabled_transfer_stationary": True
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
