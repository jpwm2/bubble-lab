#!/usr/bin/env python3
"""Acceptance benchmarks for the bounded dynamic Plateau-border foundation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from bubblelab.solvers.plateau_border import (
    PlateauBorderModel,
    PlateauBorderSettings,
    conforming_subdivide_state,
    evolve_and_switch,
)
from bubblelab.solvers.transient.network.t1_hydrodynamics import build_direct_3d_t1_state


def _state(surface_tension_n_m: float = 1.0):
    return build_direct_3d_t1_state(
        amplitude_m_inv=0.8,
        y_saturation_m=0.04,
        sheet_tension_n_m=surface_tension_n_m,
    )


def force_balance(assert_mode: bool) -> dict[str, float | bool]:
    model = PlateauBorderModel(_state())
    evolution = model.evolve_to_event()
    max_residual = max(abs(sample.forces.force_balance_residual_n) for sample in evolution.samples)
    minimum_sheet = min(sample.forces.sheet_traction_n for sample in evolution.samples)
    minimum_border_capillary = min(sample.forces.border_capillary_force_n for sample in evolution.samples)
    minimum_capillary = min(sample.forces.capillary_force_n for sample in evolution.samples)
    maximum_pressure = max(sample.forces.pressure_force_n for sample in evolution.samples)
    result = {
        "event_time_s": evolution.event_time_s,
        "minimum_sheet_traction_n": minimum_sheet,
        "minimum_border_capillary_force_n": minimum_border_capillary,
        "minimum_capillary_force_n": minimum_capillary,
        "maximum_pressure_force_n": maximum_pressure,
        "maximum_force_balance_residual_n": max_residual,
    }
    if assert_mode:
        assert evolution.event_time_s > 0.0
        assert minimum_sheet > 0.0
        assert minimum_border_capillary > 0.0
        assert minimum_capillary > 0.0
        assert max_residual <= 1.0e-10
    return result


def conservation(assert_mode: bool) -> dict[str, float]:
    evolution = PlateauBorderModel(_state()).evolve_to_event()
    result = {
        "initial_liquid_volume_m3": evolution.initial_liquid_volume_m3,
        "final_liquid_volume_m3": evolution.final_liquid_volume_m3,
        "maximum_liquid_relative_error": evolution.maximum_liquid_relative_error,
    }
    if assert_mode:
        assert evolution.maximum_liquid_relative_error <= 1.0e-12
        assert abs(evolution.initial_liquid_volume_m3 - evolution.final_liquid_volume_m3) <= 1.0e-16
    return result


def constitutive_response(assert_mode: bool) -> dict[str, float]:
    low_gamma = PlateauBorderModel(
        _state(0.8),
        PlateauBorderSettings(surface_tension_n_m=0.8),
    ).evolve_to_event()
    high_gamma = PlateauBorderModel(
        _state(1.2),
        PlateauBorderSettings(surface_tension_n_m=1.2),
    ).evolve_to_event()
    low_mu = PlateauBorderModel(
        _state(),
        PlateauBorderSettings(liquid_viscosity_pa_s=0.08),
    ).evolve_to_event()
    high_mu = PlateauBorderModel(
        _state(),
        PlateauBorderSettings(liquid_viscosity_pa_s=0.18),
    ).evolve_to_event()
    result = {
        "low_surface_tension_event_time_s": low_gamma.event_time_s,
        "high_surface_tension_event_time_s": high_gamma.event_time_s,
        "low_viscosity_event_time_s": low_mu.event_time_s,
        "high_viscosity_event_time_s": high_mu.event_time_s,
    }
    if assert_mode:
        assert high_gamma.event_time_s < low_gamma.event_time_s
        assert high_mu.event_time_s > low_mu.event_time_s
    return result


def refinement(assert_mode: bool) -> dict[str, float]:
    times = {}
    for dt in (8.0e-4, 4.0e-4, 2.0e-4):
        evolution = PlateauBorderModel(
            _state(),
            PlateauBorderSettings(time_step_s=dt),
        ).evolve_to_event()
        times[dt] = evolution.event_time_s
    coarse_mid = abs(times[8.0e-4] - times[4.0e-4])
    mid_fine = abs(times[4.0e-4] - times[2.0e-4])
    relative_fine = mid_fine / times[2.0e-4]

    base_state = _state()
    refined_state = conforming_subdivide_state(base_state)
    base_time = PlateauBorderModel(base_state).evolve_to_event().event_time_s
    refined_time = PlateauBorderModel(refined_state).evolve_to_event().event_time_s
    mesh_relative = abs(base_time - refined_time) / refined_time
    result = {
        "dt_8e-4_event_time_s": times[8.0e-4],
        "dt_4e-4_event_time_s": times[4.0e-4],
        "dt_2e-4_event_time_s": times[2.0e-4],
        "coarse_mid_delta_s": coarse_mid,
        "mid_fine_delta_s": mid_fine,
        "mid_fine_relative": relative_fine,
        "mesh_base_event_time_s": base_time,
        "mesh_refined_event_time_s": refined_time,
        "mesh_relative": mesh_relative,
    }
    if assert_mode:
        assert relative_fine < 0.03
        assert mesh_relative < 1.0e-9
    return result


def t1_coupling(assert_mode: bool) -> dict[str, object]:
    state = _state()
    model = PlateauBorderModel(state)
    result = evolve_and_switch(state)
    old_pair = tuple(sorted(model.neighborhood.old_adjacent_regions))
    new_pair = tuple(sorted(model.neighborhood.opposite_regions))
    payload = {
        "event_time_s": result.evolution.event_time_s,
        "event_gap_m": result.evolution.event_gap_m,
        "old_pair": old_pair,
        "new_pair": new_pair,
        "adjacency_before": result.adjacency_before,
        "adjacency_after": result.adjacency_after,
        "maximum_gas_volume_error": max(error for _, error in result.volume_errors_after),
    }
    if assert_mode:
        assert old_pair in result.adjacency_before
        assert old_pair not in result.adjacency_after
        assert new_pair not in result.adjacency_before
        assert new_pair in result.adjacency_after
        assert abs(
            result.after.time_s - state.time_s - result.evolution.event_time_s
        ) <= 1.0e-12
        assert payload["maximum_gas_volume_error"] <= 1.0e-12
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "benchmark",
        choices=(
            "force-balance",
            "conservation",
            "constitutive-response",
            "refinement",
            "t1-coupling",
        ),
    )
    parser.add_argument("--assert", dest="assert_mode", action="store_true")
    args = parser.parse_args()
    runners = {
        "force-balance": force_balance,
        "conservation": conservation,
        "constitutive-response": constitutive_response,
        "refinement": refinement,
        "t1-coupling": t1_coupling,
    }
    print(json.dumps(runners[args.benchmark](args.assert_mode), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
