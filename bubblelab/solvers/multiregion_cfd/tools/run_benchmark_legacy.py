#!/usr/bin/env python3
"""Deterministic evidence probes for global immersed multi-region CFD paths."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.solvers.multiregion_cfd import (
    MultigapCFDSettings,
    MultiregionCFDSettings,
    build_supported_three_bubble_solver,
    build_supported_two_bubble_solver,
    coupled_global_response,
    coupled_multigap_response,
    solve_global_precontact_field,
    solve_multigap_precontact_field,
)
from bubblelab.solvers.multiregion_cfd.t1_benchmarks import (
    conservation as t1_conservation,
    overlap_support as t1_overlap_support,
    refinement as t1_refinement,
    symmetry as t1_symmetry,
    transition as t1_transition,
)


MAX_CONSTRAINT_TRACTION_RELATIVE_MISMATCH = 0.20
MULTIGAP_FREE_VELOCITIES = {
    "bubble-a": (0.028, 0.0, 0.0),
    "bubble-b": (0.002, 0.0, 0.0),
    "bubble-c": (-0.030, 0.0, 0.0),
}


def _settings(pseudo_steps: int = 16) -> MultiregionCFDSettings:
    return MultiregionCFDSettings(
        pseudo_steps=pseudo_steps,
        viscous_cfl=0.08,
        constraint_relaxation=0.85,
        minimum_gap_cells=1.2,
        traction_offset_cells=0.8,
        gradient_step_cells=0.5,
        maximum_sphericity_error=0.12,
        minimum_constraint_cells_per_front=8,
    )


def _multigap_settings(
    pseudo_steps: int = 10,
    feedback_iterations: int = 4,
) -> MultigapCFDSettings:
    return MultigapCFDSettings(
        field=MultiregionCFDSettings(
            pseudo_steps=pseudo_steps,
            viscous_cfl=0.08,
            constraint_relaxation=0.85,
            minimum_gap_cells=1.5,
            traction_offset_cells=0.8,
            gradient_step_cells=0.5,
            maximum_sphericity_error=0.12,
            minimum_constraint_cells_per_front=8,
        ),
        feedback_iterations=feedback_iterations,
        feedback_relaxation=0.30,
    )


def _solve(cells: int):
    solver = build_supported_two_bubble_solver(
        cells=cells,
        extent_m=0.024,
        radius_m=0.003,
        gap_m=0.005,
        subdivisions=1,
        pressure_iterations=100,
        pressure_tolerance_s_inv=3.0e-6,
    )
    return solve_global_precontact_field(solver, 0.05, _settings())


def _solve_multigap(cells: int, *, pseudo_steps: int = 10):
    solver = build_supported_three_bubble_solver(
        cells=cells,
        extent_m=0.030,
        radius_m=0.0022,
        left_gap_m=0.0064,
        right_gap_m=0.0060,
        subdivisions=1,
        pressure_iterations=100,
        pressure_tolerance_s_inv=3.0e-6,
    )
    return solve_multigap_precontact_field(
        solver,
        MULTIGAP_FREE_VELOCITIES,
        _multigap_settings(pseudo_steps=pseudo_steps),
    )


def _strictly_decreasing(values: list[float]) -> bool:
    return bool(values) and values[-1] > 0.0 and all(
        first > second for first, second in zip(values, values[1:])
    )


def _relative_l2(values: list[float], reference: list[float]) -> float:
    scale = math.sqrt(sum(value * value for value in reference))
    scale = max(scale, 1.0e-30)
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(values, reference))) / scale


def refinement(assertions: bool) -> dict[str, object]:
    levels = [10, 12, 14]
    results = [_solve(level) for level in levels]
    reference = results[-1]
    ref_profile = [value for _, value in reference.centerline_pressure_samples]
    pressure_scale = max(max(abs(value) for value in ref_profile), 1.0e-30)
    force_scale = max(reference.resisting_force_n, 1.0e-30)
    rows = []
    for cells, result in zip(levels, results):
        profile = [value for _, value in result.centerline_pressure_samples]
        profile_error = math.sqrt(
            sum((a - b) ** 2 for a, b in zip(profile, ref_profile)) / len(profile)
        ) / pressure_scale
        force_error = abs(result.resisting_force_n - reference.resisting_force_n) / force_scale
        rows.append(
            {
                "cells_per_axis": cells,
                "cell_size_m": 0.024 / cells,
                "gap_cells": result.geometry.gap_m / (0.024 / cells),
                "constraint_cells_total": sum(
                    count for _, count in result.constraint_cell_counts
                ),
                "resisting_force_n": result.resisting_force_n,
                "pressure_linf_pa": result.pressure_linf_pa,
                "centerline_pressure_relative_l2_error_vs_finest": profile_error,
                "traction_relative_error_vs_finest": force_error,
                "mass_balance_relative_residual": result.mass_balance_relative_residual,
                "constraint_traction_relative_mismatch": (
                    result.constraint_traction_relative_mismatch
                ),
                "velocity_fixed_point_relative_residual": (
                    result.velocity_fixed_point_relative_residual
                ),
            }
        )
    profile_errors = [
        row["centerline_pressure_relative_l2_error_vs_finest"] for row in rows[:-1]
    ]
    force_errors = [row["traction_relative_error_vs_finest"] for row in rows[:-1]]
    pressure_monotone = _strictly_decreasing(profile_errors)
    traction_monotone = _strictly_decreasing(force_errors)
    passed = (
        pressure_monotone
        and traction_monotone
        and min(row["gap_cells"] for row in rows) > 2.0
        and max(row["constraint_traction_relative_mismatch"] for row in rows)
        <= MAX_CONSTRAINT_TRACTION_RELATIVE_MISMATCH
        and rows[-1]["mass_balance_relative_residual"] < 0.2
    )
    payload = {
        "benchmark": "global-multiregion-spatial-refinement",
        "model": reference.model,
        "refinement_regime": "gap resolved by more than two Eulerian cells",
        "levels": rows,
        "monotone_centerline_pressure_refinement": pressure_monotone,
        "monotone_traction_refinement": traction_monotone,
        "constraint_traction_relative_mismatch_limit": (
            MAX_CONSTRAINT_TRACTION_RELATIVE_MISMATCH
        ),
        "passed": passed,
    }
    if assertions and not passed:
        raise AssertionError(json.dumps(payload, sort_keys=True))
    return payload


def conservation(assertions: bool) -> dict[str, object]:
    result = _solve(12)
    payload = {
        "benchmark": "global-multiregion-mass-momentum-balance",
        "model": result.model,
        "mass_balance_relative_residual": result.mass_balance_relative_residual,
        "pair_force_relative_imbalance": result.pair_force_relative_imbalance,
        "constraint_traction_relative_mismatch": result.constraint_traction_relative_mismatch,
        "constraint_traction_relative_mismatch_limit": MAX_CONSTRAINT_TRACTION_RELATIVE_MISMATCH,
        "pressure_resisting_force_n": result.pressure_resisting_force_n,
        "viscous_resisting_force_n": result.viscous_resisting_force_n,
        "total_resisting_force_n": result.resisting_force_n,
        "region_cell_counts": dict(result.region_cell_counts),
        "projection_residual_s_inv": result.projection_residual_s_inv,
        "velocity_fixed_point_relative_residual": (
            result.velocity_fixed_point_relative_residual
        ),
        "surface_velocity_relative_error": result.surface_velocity_relative_error,
    }
    passed = (
        result.mass_balance_relative_residual < 0.2
        and result.pair_force_relative_imbalance < 0.45
        and result.constraint_traction_relative_mismatch
        <= MAX_CONSTRAINT_TRACTION_RELATIVE_MISMATCH
        and result.resisting_force_n > 0.0
        and result.pressure_linf_pa > 0.0
        and all(
            dict(result.region_cell_counts).get(name, 0) > 0
            for name in ("EXTERIOR", "bubble-a", "bubble-b")
        )
    )
    payload["passed"] = passed
    if assertions and not passed:
        raise AssertionError(json.dumps(payload, sort_keys=True))
    return payload


def feedback(assertions: bool) -> dict[str, object]:
    solver = build_supported_two_bubble_solver(
        cells=12,
        extent_m=0.024,
        radius_m=0.003,
        gap_m=0.005,
        subdivisions=1,
        pressure_iterations=100,
        pressure_tolerance_s_inv=3.0e-6,
    )
    response = coupled_global_response(
        solver,
        free_closing_speed_m_s=0.05,
        outer_resistance_n_s_m=1.5e-6,
        settings=_settings(),
    )
    slowdown = 1.0 - response.coupled_closing_speed_m_s / response.free_closing_speed_m_s
    payload = {
        "benchmark": "global-multiregion-front-feedback",
        "model": response.model,
        "free_closing_speed_m_s": response.free_closing_speed_m_s,
        "coupled_closing_speed_m_s": response.coupled_closing_speed_m_s,
        "slowdown_fraction": slowdown,
        "field_derived_resistance_n_s_m": response.resolved_cfd_resistance_n_s_m,
        "production_resisting_force_n": response.production_field.resisting_force_n,
        "production_pressure_linf_pa": response.production_field.pressure_linf_pa,
        "production_mass_balance_relative_residual": response.production_field.mass_balance_relative_residual,
        "production_constraint_traction_relative_mismatch": (
            response.production_field.constraint_traction_relative_mismatch
        ),
    }
    passed = (
        slowdown > 0.01
        and response.resolved_cfd_resistance_n_s_m > 0.0
        and response.production_field.resisting_force_n > 0.0
        and response.production_field.pressure_linf_pa > 0.0
        and response.production_field.mass_balance_relative_residual < 0.2
        and response.production_field.constraint_traction_relative_mismatch
        <= MAX_CONSTRAINT_TRACTION_RELATIVE_MISMATCH
    )
    payload["passed"] = passed
    if assertions and not passed:
        raise AssertionError(json.dumps(payload, sort_keys=True))
    return payload


def multigap_refinement(assertions: bool) -> dict[str, object]:
    levels = [13, 15, 17]
    results = [_solve_multigap(level, pseudo_steps=10) for level in levels]
    reference = results[-1]
    ref_pressure = [
        value
        for _, samples in reference.gap_pressure_samples
        for _, value in samples
    ]
    ref_traction = [
        component
        for traction in reference.tractions
        for component in traction.total_force_n
    ]
    rows = []
    for cells, result in zip(levels, results):
        pressure = [
            value
            for _, samples in result.gap_pressure_samples
            for _, value in samples
        ]
        traction = [
            component
            for item in result.tractions
            for component in item.total_force_n
        ]
        rows.append(
            {
                "cells_per_axis": cells,
                "cell_size_m": 0.030 / cells,
                "minimum_gap_cells": min(
                    gap.gap_m / (0.030 / cells) for gap in result.gaps
                ),
                "pressure_relative_l2_error_vs_finest": _relative_l2(
                    pressure, ref_pressure
                ),
                "traction_relative_l2_error_vs_finest": _relative_l2(
                    traction, ref_traction
                ),
                "mass_balance_relative_residual": result.mass_balance_relative_residual,
                "max_constraint_traction_relative_mismatch": (
                    result.max_constraint_traction_relative_mismatch
                ),
                "global_force_relative_imbalance": result.global_force_relative_imbalance,
            }
        )
    pressure_errors = [
        row["pressure_relative_l2_error_vs_finest"] for row in rows[:-1]
    ]
    traction_errors = [
        row["traction_relative_l2_error_vs_finest"] for row in rows[:-1]
    ]
    pressure_monotone = _strictly_decreasing(pressure_errors)
    traction_monotone = _strictly_decreasing(traction_errors)
    passed = (
        pressure_monotone
        and traction_monotone
        and min(row["minimum_gap_cells"] for row in rows) > 2.0
        and max(row["max_constraint_traction_relative_mismatch"] for row in rows)
        <= MAX_CONSTRAINT_TRACTION_RELATIVE_MISMATCH
        and rows[-1]["mass_balance_relative_residual"] < 0.2
    )
    payload = {
        "benchmark": "multigap-manybubble-spatial-refinement",
        "model": reference.model,
        "supported_regime": (
            "three collinear quasi-spherical fronts with both pre-contact gaps "
            "resolved by more than two Eulerian cells"
        ),
        "levels": rows,
        "monotone_pressure_refinement": pressure_monotone,
        "monotone_traction_refinement": traction_monotone,
        "constraint_traction_relative_mismatch_limit": (
            MAX_CONSTRAINT_TRACTION_RELATIVE_MISMATCH
        ),
        "passed": passed,
    }
    if assertions and not passed:
        raise AssertionError(json.dumps(payload, sort_keys=True))
    return payload


def multigap_conservation(assertions: bool) -> dict[str, object]:
    result = _solve_multigap(15, pseudo_steps=12)
    counts = dict(result.region_cell_counts)
    payload = {
        "benchmark": "multigap-manybubble-mass-momentum-balance",
        "model": result.model,
        "tracked_front_count": len(result.tractions),
        "active_gap_count": len(result.gaps),
        "mass_balance_relative_residual": result.mass_balance_relative_residual,
        "global_force_relative_imbalance": result.global_force_relative_imbalance,
        "front_constraint_traction_relative_mismatch": dict(
            result.front_constraint_traction_relative_mismatch
        ),
        "max_constraint_traction_relative_mismatch": (
            result.max_constraint_traction_relative_mismatch
        ),
        "constraint_traction_relative_mismatch_limit": (
            MAX_CONSTRAINT_TRACTION_RELATIVE_MISMATCH
        ),
        "region_cell_counts": counts,
        "front_tractions": [traction.as_dict() for traction in result.tractions],
        "constraint_reaction_forces_n": {
            key: list(value) for key, value in result.constraint_reaction_forces_n
        },
    }
    passed = (
        len(result.tractions) == 3
        and len(result.gaps) == 2
        and result.pressure_linf_pa > 0.0
        and result.mass_balance_relative_residual < 0.2
        and result.global_force_relative_imbalance < 0.30
        and result.max_constraint_traction_relative_mismatch
        <= MAX_CONSTRAINT_TRACTION_RELATIVE_MISMATCH
        and all(
            counts.get(name, 0) > 0
            for name in ("EXTERIOR", "bubble-a", "bubble-b", "bubble-c")
        )
    )
    payload["passed"] = passed
    if assertions and not passed:
        raise AssertionError(json.dumps(payload, sort_keys=True))
    return payload


def multigap_feedback(assertions: bool) -> dict[str, object]:
    solver = build_supported_three_bubble_solver(
        cells=13,
        extent_m=0.030,
        radius_m=0.0022,
        left_gap_m=0.0064,
        right_gap_m=0.0060,
        subdivisions=1,
        pressure_iterations=100,
        pressure_tolerance_s_inv=3.0e-6,
    )
    response = coupled_multigap_response(
        solver,
        MULTIGAP_FREE_VELOCITIES,
        outer_resistance_n_s_m=8.0e-6,
        settings=_multigap_settings(pseudo_steps=10, feedback_iterations=4),
    )
    coupled = dict(response.coupled_velocities_world)
    free = dict(response.free_velocities_world)
    changes = {
        bubble_id: abs(coupled[bubble_id][0] - free[bubble_id][0])
        / max(abs(free[bubble_id][0]), 0.01)
        for bubble_id in free
    }
    free_closures = (
        free["bubble-a"][0] - free["bubble-b"][0],
        free["bubble-b"][0] - free["bubble-c"][0],
    )
    coupled_closures = (
        coupled["bubble-a"][0] - coupled["bubble-b"][0],
        coupled["bubble-b"][0] - coupled["bubble-c"][0],
    )
    closure_changes = [
        abs(after - before) / max(abs(before), 1.0e-12)
        for before, after in zip(free_closures, coupled_closures)
    ]
    changed_fronts = sum(value > 0.01 for value in changes.values())
    payload = {
        "benchmark": "multigap-manybubble-multifront-feedback",
        "model": response.model,
        "free_velocities_world_m_s": {key: list(value) for key, value in free.items()},
        "coupled_velocities_world_m_s": {
            key: list(value) for key, value in coupled.items()
        },
        "front_velocity_change_fraction": changes,
        "changed_front_count": changed_fronts,
        "free_gap_closing_speeds_m_s": list(free_closures),
        "coupled_gap_closing_speeds_m_s": list(coupled_closures),
        "gap_closing_speed_change_fraction": closure_changes,
        "feedback_relative_residual": response.feedback_relative_residual,
        "production_mass_balance_relative_residual": (
            response.production_field.mass_balance_relative_residual
        ),
        "production_max_constraint_traction_relative_mismatch": (
            response.production_field.max_constraint_traction_relative_mismatch
        ),
        "production_pressure_linf_pa": response.production_field.pressure_linf_pa,
    }
    passed = (
        changed_fronts >= 2
        and max(closure_changes) > 0.01
        and response.production_field.pressure_linf_pa > 0.0
        and response.production_field.mass_balance_relative_residual < 0.2
        and response.production_field.max_constraint_traction_relative_mismatch
        <= MAX_CONSTRAINT_TRACTION_RELATIVE_MISMATCH
    )
    payload["passed"] = passed
    if assertions and not passed:
        raise AssertionError(json.dumps(payload, sort_keys=True))
    return payload


def multigap_symmetry(assertions: bool) -> dict[str, object]:
    settings = _multigap_settings(pseudo_steps=8)
    first = solve_multigap_precontact_field(
        build_supported_three_bubble_solver(
            cells=13,
            extent_m=0.030,
            radius_m=0.0022,
            left_gap_m=0.0064,
            right_gap_m=0.0060,
            subdivisions=1,
            pressure_iterations=90,
            front_order=("bubble-a", "bubble-b", "bubble-c"),
        ),
        MULTIGAP_FREE_VELOCITIES,
        settings,
    ).as_dict()
    second = solve_multigap_precontact_field(
        build_supported_three_bubble_solver(
            cells=13,
            extent_m=0.030,
            radius_m=0.0022,
            left_gap_m=0.0064,
            right_gap_m=0.0060,
            subdivisions=1,
            pressure_iterations=90,
            front_order=("bubble-c", "bubble-a", "bubble-b"),
        ),
        MULTIGAP_FREE_VELOCITIES,
        settings,
    ).as_dict()
    identical = first == second
    payload = {
        "benchmark": "multigap-manybubble-container-permutation-symmetry",
        "model": first["model"],
        "permuted_front_container_order": ["bubble-c", "bubble-a", "bubble-b"],
        "physical_solution_exactly_identical": identical,
        "passed": identical,
    }
    if assertions and not identical:
        raise AssertionError(json.dumps(payload, sort_keys=True))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=(
            "refinement",
            "conservation",
            "feedback",
            "multigap-refinement",
            "multigap-conservation",
            "multigap-feedback",
            "multigap-symmetry",
            "t1-overlap-support",
            "t1-transition",
            "t1-conservation",
            "t1-refinement",
            "t1-symmetry",
        ),
    )
    parser.add_argument("--assert", dest="assertions", action="store_true")
    args = parser.parse_args()
    function = {
        "refinement": refinement,
        "conservation": conservation,
        "feedback": feedback,
        "multigap-refinement": multigap_refinement,
        "multigap-conservation": multigap_conservation,
        "multigap-feedback": multigap_feedback,
        "multigap-symmetry": multigap_symmetry,
        "t1-overlap-support": t1_overlap_support,
        "t1-transition": t1_transition,
        "t1-conservation": t1_conservation,
        "t1-refinement": t1_refinement,
        "t1-symmetry": t1_symmetry,
    }[args.mode]
    print(json.dumps(function(args.assertions), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
