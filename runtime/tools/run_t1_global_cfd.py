#!/usr/bin/env python3
"""Run the bounded T1-through-global-CFD runtime scenario and emit JSON evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.runtime.t1_global_cfd_runtime import T1GlobalCFDRuntime


DEFAULT_SCENARIO = ROOT / "bubblelab/scenarios/runtime/t1-global-cfd.scenario.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument("--assert", dest="assertions", action="store_true")
    args = parser.parse_args()

    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    runtime = T1GlobalCFDRuntime.from_scenario(scenario)
    payload = runtime.run()
    transition = payload["transition"]
    pre = transition["pre_field"]
    post = transition["post_field"]
    topology = transition["topology"]
    mismatch_limit = float(
        scenario["t1_global_cfd"].get("maximum_aggregate_traction_mismatch", 0.20)
    )
    passed = (
        payload["status"] == "SUPPORTED_CLASS_RESOLVED"
        and transition["authoritative_grid_preserved"]
        and pre["shared_support"]["overlap_cell_count"] > 0
        and pre["shared_support"]["maximum_overlap_multiplicity"] >= 2
        and pre["shared_support"]["maximum_partition_sum_error"] <= 1.0e-14
        and transition["event"]["field_event_time_s"] > 0.0
        and transition["event"]["net_field_coupled_driving_force_n"] > 0.0
        and topology["adjacency_before"] != topology["adjacency_after"]
        and len(topology["retired_film_ids"]) == 1
        and len(topology["created_film_ids"]) == 1
        and len(topology["retired_junction_ids"]) == 2
        and len(topology["created_junction_ids"]) == 2
        and max(topology["volume_errors_after"].values(), default=0.0) <= 1.0e-12
        and pre["field"]["pressure_linf_pa"] > 0.0
        and post["field"]["pressure_linf_pa"] > 0.0
        and pre["field"]["mass_balance_relative_residual"] < 0.20
        and post["field"]["mass_balance_relative_residual"] < 0.20
        and pre["traction"]["aggregate_constraint_traction_relative_mismatch"]
        <= mismatch_limit
        and post["traction"]["aggregate_constraint_traction_relative_mismatch"]
        <= mismatch_limit
    )
    payload["assertion_limits"] = {
        "mass_balance_relative_residual": 0.20,
        "aggregate_constraint_traction_relative_mismatch": mismatch_limit,
        "closed_region_volume_relative_error": 1.0e-12,
    }
    payload["assertion_passed"] = passed
    if args.assertions and not passed:
        raise AssertionError(json.dumps(payload, sort_keys=True))
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
