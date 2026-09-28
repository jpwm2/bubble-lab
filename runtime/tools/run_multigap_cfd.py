#!/usr/bin/env python3
"""End-to-end evidence probe for the bounded three-bubble/two-gap CFD runtime."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.runtime.multigap_cfd_runtime import (
    load_scenario,
    replay_signature,
    run_multigap_cfd,
)


DEFAULT_SCENARIO = (
    ROOT / "bubblelab" / "scenarios" / "runtime" / "multigap-three-bubble.scenario.json"
)
MAX_CONSTRAINT_TRACTION_RELATIVE_MISMATCH = 0.20


def run(assertions: bool) -> dict[str, object]:
    scenario = load_scenario(DEFAULT_SCENARIO)
    enabled = run_multigap_cfd(scenario, global_enabled=True)
    repeat = run_multigap_cfd(scenario, global_enabled=True)
    control = run_multigap_cfd(scenario, global_enabled=False)
    enabled_summary = enabled["summary"]
    control_summary = control["summary"]
    replay_exact = replay_signature(enabled) == replay_signature(repeat)
    enabled_time = float(enabled_summary["resolved_handoff_time_s"])
    control_time = float(control_summary["resolved_handoff_time_s"])
    timing_change = abs(enabled_time - control_time) / max(abs(control_time), 1.0e-12)
    frames = enabled["frames"]
    all_two_gap = bool(frames) and all(
        frame["simultaneously_active_gap_count"] == 2 for frame in frames
    )
    shared_field = bool(frames) and all(
        frame["global_grid_shared_state"] for frame in frames
    )
    payload = {
        "benchmark": "multigap-manybubble-runtime-e2e",
        "model_id": enabled["manifest"]["model_id"],
        "global_activation_count": enabled_summary["global_activation_count"],
        "frame_count": len(frames),
        "simultaneous_two_gap_every_frame": all_two_gap,
        "one_authoritative_global_grid_every_frame": shared_field,
        "changed_front_ids": enabled_summary["changed_front_ids"],
        "changed_front_count": enabled_summary["changed_front_count"],
        "enabled_handoff_time_s": enabled_time,
        "control_handoff_time_s": control_time,
        "handoff_timing_change_fraction": timing_change,
        "enabled_handoff_pair_ids": enabled_summary["resolved_handoff_pair_ids"],
        "control_handoff_pair_ids": control_summary["resolved_handoff_pair_ids"],
        "max_mass_balance_relative_residual": enabled_summary[
            "max_mass_balance_relative_residual"
        ],
        "max_constraint_traction_relative_mismatch": enabled_summary[
            "max_constraint_traction_relative_mismatch"
        ],
        "max_global_force_relative_imbalance": enabled_summary[
            "max_global_force_relative_imbalance"
        ],
        "max_closed_bubble_volume_relative_error": enabled_summary[
            "max_closed_bubble_volume_relative_error"
        ],
        "deterministic_replay_exact": replay_exact,
        "pairwise_force_superposition": enabled["manifest"]["feature_disclosures"][
            "pairwise_force_superposition"
        ],
    }
    passed = (
        enabled_summary["global_activation_count"] > 0
        and all_two_gap
        and shared_field
        and enabled_summary["changed_front_count"] >= 2
        and timing_change > 0.01
        and enabled_summary["max_mass_balance_relative_residual"] < 0.2
        and enabled_summary["max_constraint_traction_relative_mismatch"]
        <= MAX_CONSTRAINT_TRACTION_RELATIVE_MISMATCH
        and enabled_summary["max_closed_bubble_volume_relative_error"] < 1.0e-12
        and replay_exact
        and payload["pairwise_force_superposition"] == "NOT_USED"
    )
    payload["passed"] = passed
    if assertions and not passed:
        raise AssertionError(json.dumps(payload, sort_keys=True))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assert", dest="assertions", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.assertions), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
