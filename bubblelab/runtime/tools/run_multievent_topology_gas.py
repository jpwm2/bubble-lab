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

from bubblelab.runtime.multievent_topology_gas_runtime import run_frames

DEFAULT_SCENARIO = ROOT / "bubblelab/scenarios/runtime/multievent-topology-gas.scenario.json"


def _by_id(frame: dict) -> dict[str, dict]:
    return {item["id"]: item for item in frame["bubbles"]}


def _assert_run(scenario: dict, frames: list[dict]) -> dict:
    if len(frames) < 7:
        raise AssertionError("runtime assertion requires enough frames to cross all transactions")
    first = frames[0]
    last = frames[-1]
    events = last["topology_events"]
    event_types = [event["type"] for event in events]
    assert event_types[:4] == ["T1"] * 4
    assert event_types[-2:] == ["RUPTURE", "COALESCENCE"]
    assert last["diagnostics"]["transaction_count"] == 5
    assert last["diagnostics"]["topology_event_count"] == 6
    assert last["diagnostics"]["topology_revision"] == 6
    assert len(first["bubbles"]) == 10
    assert len(last["bubbles"]) == 9
    for reason in first["diagnostics"]["initial_blocked_t1_reasons"].values():
        assert "adjacency already exists" in reason
    assert "does not exist before event 4" in first["diagnostics"]["initial_rupture_block_reason"]

    t1_events = events[:4]
    for index, event in enumerate(t1_events, 1):
        assert event["unaffected_state_exact"]
        assert event["gas_amount_relative_drift"] <= 1.0e-12
        assert event["topology_revision_before"] == index - 1
        assert event["topology_revision_after"] == index
    fourth_created = t1_events[-1]["created_film_ids"][0]
    assert fourth_created in events[-2]["retired_film_ids"]
    assert events[-1]["lineage"] == ["G", "H"]
    assert events[-1]["unaffected_state_exact"]
    assert events[-1]["gas_amount_relative_drift"] <= 1.0e-12

    assert last["diagnostics"]["total_amount_relative_drift_from_initial"] <= 1.0e-12
    assert last["diagnostics"]["worst_transport_step_relative_drift"] <= 1.0e-12
    assert last["diagnostics"]["worst_edge_antisymmetry_residual_mol"] <= 1.0e-30
    assert last["diagnostics"]["max_simultaneous_active_edges"] >= 2
    final_edges = set(last["diagnostics"]["edge_ids"])
    assert fourth_created not in final_edges
    transfer_history = last["diagnostics"]["edge_transfer_history_mol"]
    for event in t1_events:
        created = event["created_film_ids"][0]
        assert transfer_history[created] != 0.0

    repeat = run_frames(copy.deepcopy(scenario), frame_count=len(frames))
    assert json.dumps(frames, sort_keys=True) == json.dumps(repeat, sort_keys=True)

    disabled = copy.deepcopy(scenario)
    disabled["user_editable"]["multievent_topology_gas"]["enabled"] = False
    disabled_frames = run_frames(disabled, frame_count=len(frames))
    disabled_first = _by_id(disabled_frames[0])
    disabled_last = _by_id(disabled_frames[-1])
    for region_id, region in disabled_first.items():
        if region_id in ("G", "H"):
            continue
        assert disabled_last[region_id]["amount_mol"] == region["amount_mol"]
        assert disabled_last[region_id]["volume_m3"] == region["volume_m3"]
    coalescence = disabled_frames[-1]["topology_events"][-1]
    child = disabled_last[coalescence["child_region_id"]]
    expected_gh = disabled_first["G"]["amount_mol"] + disabled_first["H"]["amount_mol"]
    assert child["amount_mol"] == expected_gh
    assert disabled_frames[-1]["diagnostics"]["max_simultaneous_active_edges"] == 0
    assert disabled_frames[-1]["diagnostics"]["topology_revision"] == 6

    return {
        "passed": True,
        "frame_count": len(frames),
        "initial_region_count": len(first["bubbles"]),
        "final_region_count": len(last["bubbles"]),
        "transaction_count": last["diagnostics"]["transaction_count"],
        "event_types": event_types,
        "event_ids": [event["event_id"] for event in events],
        "fourth_t1_created_and_ruptured_film": fourth_created,
        "coalescence_lineage": events[-1]["lineage"],
        "total_amount_relative_drift": last["diagnostics"]["total_amount_relative_drift_from_initial"],
        "max_simultaneous_active_edges": last["diagnostics"]["max_simultaneous_active_edges"],
        "deterministic_repeat": True,
        "disabled_transport_stationary": True
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument("--frames", type=int, default=8)
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
