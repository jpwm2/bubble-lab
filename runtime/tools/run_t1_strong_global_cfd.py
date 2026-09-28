#!/usr/bin/env python3
"""Run the bounded strongly coupled T1/global-CFD scenario and emit JSON evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.runtime.t1_strong_global_cfd_runtime import T1StrongGlobalCFDRuntime


DEFAULT_SCENARIO = ROOT / "bubblelab/scenarios/runtime/t1-strong-global-cfd.scenario.json"


def _maximum_front_mismatch(field: dict[str, object]) -> float:
    traction = field["traction"]
    values = traction["front_constraint_traction_relative_mismatch"].values()
    return max(values, default=0.0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument("--assert", dest="assertions", action="store_true")
    args = parser.parse_args()

    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    runtime = T1StrongGlobalCFDRuntime.from_scenario(scenario)
    payload = runtime.run()
    transition = payload["transition"]
    pre = transition["pre_field"]
    post = transition["post_field"]
    topology = transition["topology"]
    strong = transition["strong_coupling"]
    raw = scenario["t1_strong_global_cfd"]
    mismatch_limit = float(raw.get("maximum_aggregate_traction_mismatch", 0.20))
    feedback_limit = float(raw.get("maximum_feedback_relative_residual", 0.005))
    minimum_shift = 0.05
    passed = (
        payload["status"] == "SUPPORTED_CLASS_STRONGLY_COUPLED"
        and transition["authoritative_grid_preserved"]
        and strong["event_time_shift_fraction"] >= minimum_shift
        and strong["feedback_relative_residual"] <= feedback_limit
        and transition["event"]["field_event_time_s"]
        > strong["feedback_disabled_event_time_s"]
        and strong["coupled_closing_speed_m_s"]
        < strong["feedback_disabled_closing_speed_m_s"]
        and transition["event"]["field_hydrodynamic_resistance_n"] > 0.0
        and transition["event"]["net_field_coupled_driving_force_n"] > 0.0
        and pre["shared_support"]["overlap_cell_count"] > 0
        and pre["shared_support"]["maximum_overlap_multiplicity"] >= 2
        and pre["shared_support"]["maximum_partition_sum_error"] <= 1.0e-14
        and topology["adjacency_before"] != topology["adjacency_after"]
        and len(topology["retired_film_ids"]) == 1
        and len(topology["created_film_ids"]) == 1
        and len(topology["retired_junction_ids"]) == 2
        and len(topology["created_junction_ids"]) == 2
        and len(topology["preserved_region_ids"]) == 4
        and max(topology["volume_errors_after"].values(), default=0.0) <= 1.0e-12
        and pre["field"]["pressure_linf_pa"] > 0.0
        and post["field"]["pressure_linf_pa"] > 0.0
        and pre["field"]["mass_balance_relative_residual"] < 0.20
        and post["field"]["mass_balance_relative_residual"] < 0.20
        and pre["traction"]["aggregate_constraint_traction_relative_mismatch"]
        <= mismatch_limit
        and post["traction"]["aggregate_constraint_traction_relative_mismatch"]
        <= mismatch_limit
        and _maximum_front_mismatch(pre) <= mismatch_limit
        and _maximum_front_mismatch(post) <= mismatch_limit
    )
    payload["assertion_limits"] = {
        "minimum_event_time_shift_fraction": minimum_shift,
        "maximum_feedback_relative_residual": feedback_limit,
        "mass_balance_relative_residual": 0.20,
        "aggregate_and_per_front_constraint_traction_relative_mismatch": mismatch_limit,
        "closed_region_volume_relative_error": 1.0e-12,
        "partition_sum_error": 1.0e-14,
    }
    payload["assertion_passed"] = passed
    if args.assertions and not passed:
        raise AssertionError(json.dumps(payload, sort_keys=True))
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
