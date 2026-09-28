#!/usr/bin/env python3
"""Run the dynamic Plateau-border T1 transition and transient continuation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from bubblelab.runtime.plateau_border_t1_runtime import run_plateau_border_t1_runtime
from bubblelab.solvers.plateau_border import SUPPORTED_CLASS, PlateauBorderSettings
from bubblelab.solvers.transient.network.core import NetworkStepperSettings
from bubblelab.solvers.transient.network.t1_hydrodynamics import build_direct_3d_t1_state


def _default_scenario_path() -> Path:
    return Path(__file__).resolve().parents[2] / "scenarios" / "runtime" / "plateau-border-t1.scenario.json"


def run(path: Path) -> dict[str, object]:
    scenario = json.loads(path.read_text(encoding="utf-8"))
    if str(scenario["supported_class"]) != SUPPORTED_CLASS:
        raise ValueError(
            "scenario supported_class does not match Plateau-border implementation: "
            f"{scenario['supported_class']!r} != {SUPPORTED_CLASS!r}"
        )
    fixture = scenario["fixture"]
    liquid = scenario["liquid_border"]
    continuation = scenario["continuation"]
    state = build_direct_3d_t1_state(
        resolution_m=float(fixture["resolution_m"]),
        initial_gap_m=float(fixture["initial_gap_m"]),
        half_extent_m=float(fixture["half_extent_m"]),
        depth_m=float(fixture["depth_m"]),
        sheet_tension_n_m=float(fixture["sheet_tension_n_m"]),
        mode=str(fixture["mode"]),
        amplitude_m_inv=float(fixture["amplitude_m_inv"]),
        y_saturation_m=float(fixture["y_saturation_m"]),
    )
    settings = PlateauBorderSettings(
        surface_tension_n_m=float(liquid["surface_tension_n_m"]),
        liquid_viscosity_pa_s=float(liquid["liquid_viscosity_pa_s"]),
        core_radius_m=float(liquid["core_radius_m"]),
        total_liquid_volume_m3=float(liquid["total_liquid_volume_m3"]),
        initial_core_volume_fraction=float(liquid["initial_core_volume_fraction"]),
        redistribution_length_m=float(liquid["redistribution_length_m"]),
        redistribution_radius_m=float(liquid["redistribution_radius_m"]),
        time_step_s=float(liquid["time_step_s"]),
        maximum_time_s=float(liquid["maximum_time_s"]),
        post_event_seed_factor=float(liquid["post_event_seed_factor"]),
    )
    stepper = NetworkStepperSettings(
        dt_s=float(continuation["dt_s"]),
        mobility_m_per_n_s=float(continuation["mobility_m_per_n_s"]),
        volume_relative_tolerance=float(continuation["volume_relative_tolerance"]),
    )
    result = run_plateau_border_t1_runtime(
        state,
        event_settings=settings,
        stepper_settings=stepper,
        continuation_steps=int(continuation["steps"]),
    )
    event = result.event
    return {
        "scenario": scenario["name"],
        "supported_class": event.supported_class,
        "event_time_s": event.evolution.event_time_s,
        "event_gap_m": event.evolution.event_gap_m,
        "event_id": event.lineage.event_id,
        "created_film_ids": list(event.lineage.created_film_ids),
        "created_junction_ids": list(event.lineage.created_junction_ids),
        "adjacency_before": [list(value) for value in event.adjacency_before],
        "adjacency_after": [list(value) for value in event.adjacency_after],
        "max_liquid_volume_error": event.evolution.maximum_liquid_relative_error,
        "max_event_gas_volume_error": max(error for _, error in event.volume_errors_after),
        "continued_steps": len(result.diagnostics),
        "continued_time_s": result.continued.time_s,
        "continued_step_index": result.continued.step_index,
        "max_continued_volume_error": max(
            error
            for diagnostics in result.diagnostics
            for _, error in diagnostics.relative_volume_errors
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", type=Path, default=_default_scenario_path())
    parser.add_argument("--assert", dest="assert_result", action="store_true")
    args = parser.parse_args()
    result = run(args.scenario)
    if args.assert_result:
        assert result["supported_class"] == SUPPORTED_CLASS
        assert result["event_time_s"] > 0.0
        assert result["max_liquid_volume_error"] <= 1.0e-12
        assert result["max_event_gas_volume_error"] <= 1.0e-12
        assert result["continued_steps"] >= 1
        assert result["continued_step_index"] >= result["continued_steps"]
        assert result["max_continued_volume_error"] <= 2.0e-10
        assert result["created_film_ids"] and len(result["created_junction_ids"]) == 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
