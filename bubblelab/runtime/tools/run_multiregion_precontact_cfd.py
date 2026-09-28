#!/usr/bin/env python3
"""Run the supported global-to-local two-bubble pre-contact CFD transition."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.runtime.multiregion_cfd_runtime import (
    load_scenario,
    replay_signature,
    run_multiregion_precontact_cfd,
)


MAX_CONSTRAINT_TRACTION_RELATIVE_MISMATCH = 0.20


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario",
        default=str(
            Path(__file__).resolve().parents[2]
            / "scenarios"
            / "runtime"
            / "multiregion-cfd-two-bubble.scenario.json"
        ),
    )
    parser.add_argument("--assert", dest="assertions", action="store_true")
    args = parser.parse_args()
    scenario = load_scenario(args.scenario)
    coupled = run_multiregion_precontact_cfd(scenario, global_enabled=True)
    control = run_multiregion_precontact_cfd(scenario, global_enabled=False)
    replay = run_multiregion_precontact_cfd(scenario, global_enabled=True)

    coupled_summary = coupled["summary"]
    control_summary = control["summary"]
    delay = coupled_summary["contact_time_s"] - control_summary["contact_time_s"]
    replay_exact = replay_signature(coupled) == replay_signature(replay)
    payload = {
        "model": coupled["manifest"]["model_id"],
        "coupled_contact_time_s": coupled_summary["contact_time_s"],
        "global_disabled_contact_time_s": control_summary["contact_time_s"],
        "global_cfd_contact_delay_s": delay,
        "global_activation_count": coupled_summary["global_activation_count"],
        "local_handoff_activation_count": coupled_summary[
            "local_handoff_activation_count"
        ],
        "max_mass_balance_relative_residual": coupled_summary[
            "max_mass_balance_relative_residual"
        ],
        "max_pair_force_relative_imbalance": coupled_summary[
            "max_pair_force_relative_imbalance"
        ],
        "max_constraint_traction_relative_mismatch": coupled_summary[
            "max_constraint_traction_relative_mismatch"
        ],
        "constraint_traction_relative_mismatch_limit": (
            MAX_CONSTRAINT_TRACTION_RELATIVE_MISMATCH
        ),
        "max_closed_bubble_volume_relative_error": coupled_summary[
            "max_closed_bubble_volume_relative_error"
        ],
        "final_gap_m": coupled_summary["final_gap_m"],
        "contact_gap_m": coupled_summary["contact_gap_m"],
        "deterministic_replay_exact": replay_exact,
        "last_global_field": coupled_summary["last_global_field"],
    }
    passed = (
        payload["global_activation_count"] > 0
        and payload["local_handoff_activation_count"] > 0
        and delay > 1.0e-5
        and replay_exact
        and payload["max_mass_balance_relative_residual"] < 0.2
        and payload["max_constraint_traction_relative_mismatch"]
        <= MAX_CONSTRAINT_TRACTION_RELATIVE_MISMATCH
        and payload["max_closed_bubble_volume_relative_error"] < 1.0e-11
        and payload["last_global_field"] is not None
        and payload["last_global_field"]["traction"]["resisting_force_n"] > 0.0
        and payload["last_global_field"]["field"]["pressure_linf_pa"] > 0.0
        and payload["final_gap_m"] <= payload["contact_gap_m"] * (1.0 + 1.0e-8)
    )
    payload["passed"] = passed
    if args.assertions and not passed:
        raise AssertionError(json.dumps(payload, sort_keys=True))
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
