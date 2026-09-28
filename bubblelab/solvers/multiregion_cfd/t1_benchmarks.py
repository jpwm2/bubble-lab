"""Deterministic acceptance evidence for the bounded T1/global-CFD foundation."""
from __future__ import annotations

from dataclasses import replace
import json
from typing import Any

from bubblelab.solvers.transient.network.t1_hydrodynamics import (
    build_direct_3d_t1_state,
    detect_direct_t1_eligibility,
)

from .t1 import T1GlobalCFDSettings, T1GlobalTransitionResult, run_t1_global_cfd_transition
from .t1_fixtures import build_supported_four_region_t1_solver


MASS_BALANCE_LIMIT = 0.20
TRACTION_MISMATCH_LIMIT = 0.20
VOLUME_ERROR_LIMIT = 1.0e-12
PARTITION_ERROR_LIMIT = 1.0e-14
REFINEMENT_EVENT_SPAN_LIMIT = 1.0e-6
REFINEMENT_TRACTION_SPAN_LIMIT = 0.10
SYMMETRY_RELATIVE_LIMIT = 1.0e-12


def _settings() -> T1GlobalCFDSettings:
    base = T1GlobalCFDSettings()
    return replace(
        base,
        field=replace(base.field, pseudo_steps=24),
        maximum_aggregate_traction_mismatch=TRACTION_MISMATCH_LIMIT,
    )


def _case(
    cells: int = 12,
    *,
    axis_cycle: int = 0,
    reverse_front_order: bool = False,
) -> T1GlobalTransitionResult:
    state = build_direct_3d_t1_state(
        amplitude_m_inv=0.8,
        y_saturation_m=0.04,
    )
    settings = _settings()
    eligibility = detect_direct_t1_eligibility(state, settings.direct)
    if not eligibility.eligible or eligibility.neighborhood is None:
        raise AssertionError(f"canonical direct-T1 fixture is not eligible: {eligibility.reason}")
    region_ids = tuple(region.id for region in state.to_network().regions)
    front_order = tuple(reversed(region_ids)) if reverse_front_order else region_ids
    solver = build_supported_four_region_t1_solver(
        region_ids=region_ids,
        old_pair=eligibility.neighborhood.old_adjacent_regions,
        cells=cells,
        extent_m=0.010,
        front_order=front_order,
        axis_cycle=axis_cycle,
    )
    return run_t1_global_cfd_transition(solver, state, settings)


def _front_mismatch(result: Any) -> float:
    return max(
        (value for _, value in result.front_constraint_traction_relative_mismatch),
        default=0.0,
    )


def _phase_conservative(field: Any) -> bool:
    return (
        field.mass_balance_relative_residual < MASS_BALANCE_LIMIT
        and field.aggregate_constraint_traction_relative_mismatch <= TRACTION_MISMATCH_LIMIT
        and _front_mismatch(field) <= TRACTION_MISMATCH_LIMIT
    )


def _relative_error(first: float, second: float) -> float:
    return abs(first - second) / max(abs(first), abs(second), 1.0e-30)


def _relative_span(values: list[float]) -> float:
    scale = max(max(abs(value) for value in values), 1.0e-30)
    return (max(values) - min(values)) / scale


def _finish(payload: dict[str, Any], assertions: bool) -> dict[str, Any]:
    if assertions and not payload["passed"]:
        raise AssertionError(json.dumps(payload, sort_keys=True))
    return payload


def overlap_support(assertions: bool) -> dict[str, Any]:
    result = _case()
    support = result.pre_field.support
    payload = {
        "benchmark": "t1-overlap-support",
        "model": result.model,
        "shared_field_model": result.pre_field.model,
        "overlap_cell_count": support.overlap_cell_count,
        "maximum_overlap_multiplicity": support.maximum_overlap_multiplicity,
        "overlap_fraction": support.overlap_fraction,
        "maximum_target_spread_m_s": support.maximum_target_spread_m_s,
        "maximum_partition_sum_error": support.maximum_partition_sum_error,
        "partition_error_limit": PARTITION_ERROR_LIMIT,
        "pressure_linf_pa": result.pre_field.pressure_linf_pa,
        "authoritative_grid_preserved": result.authoritative_grid_preserved,
        "treatment": support.as_dict()["treatment"],
    }
    payload["passed"] = (
        support.overlap_cell_count > 0
        and support.maximum_overlap_multiplicity >= 2
        and support.maximum_target_spread_m_s > 0.0
        and support.maximum_partition_sum_error <= PARTITION_ERROR_LIMIT
        and result.pre_field.pressure_linf_pa > 0.0
        and result.authoritative_grid_preserved
    )
    return _finish(payload, assertions)


def transition(assertions: bool) -> dict[str, Any]:
    result = _case()
    payload = {
        "benchmark": "t1-transition",
        "model": result.model,
        "field_event_time_s": result.field_event_time_s,
        "standalone_direct_diagnostic_event_time_s": result.direct_geometry_diagnostic_event_time_s,
        "capillary_driving_force_n": result.capillary_driving_force_n,
        "field_hydrodynamic_resistance_n": result.field_hydrodynamic_resistance_n,
        "net_field_coupled_driving_force_n": result.net_field_coupled_driving_force_n,
        "adjacency_before": [list(pair) for pair in result.adjacency_before],
        "adjacency_after": [list(pair) for pair in result.adjacency_after],
        "retired_film_ids": list(result.retired_film_ids),
        "created_film_ids": list(result.created_film_ids),
        "retired_junction_ids": list(result.retired_junction_ids),
        "created_junction_ids": list(result.created_junction_ids),
        "preserved_region_ids": list(result.preserved_region_ids),
        "post_t1_pressure_linf_pa": result.post_field.pressure_linf_pa,
        "authoritative_grid_preserved": result.authoritative_grid_preserved,
        "production_event_source": (
            "resolved direct-3D capillary drive minus traction from the shared Eulerian field"
        ),
    }
    payload["passed"] = (
        result.field_event_time_s > 0.0
        and result.field_hydrodynamic_resistance_n > 0.0
        and result.net_field_coupled_driving_force_n > 0.0
        and result.adjacency_before != result.adjacency_after
        and len(result.retired_film_ids) == 1
        and len(result.created_film_ids) == 1
        and len(result.retired_junction_ids) == 2
        and len(result.created_junction_ids) == 2
        and len(result.preserved_region_ids) == 4
        and result.post_field.pressure_linf_pa > 0.0
        and result.authoritative_grid_preserved
        and abs(
            result.topology_state_after.time_s - result.field_event_time_s
        ) <= 1.0e-13
    )
    return _finish(payload, assertions)


def conservation(assertions: bool) -> dict[str, Any]:
    result = _case()
    volume_error = max((value for _, value in result.volume_errors_after), default=0.0)
    payload = {
        "benchmark": "t1-conservation",
        "model": result.model,
        "pre_mass_balance_relative_residual": result.pre_field.mass_balance_relative_residual,
        "post_mass_balance_relative_residual": result.post_field.mass_balance_relative_residual,
        "pre_aggregate_constraint_traction_relative_mismatch": (
            result.pre_field.aggregate_constraint_traction_relative_mismatch
        ),
        "post_aggregate_constraint_traction_relative_mismatch": (
            result.post_field.aggregate_constraint_traction_relative_mismatch
        ),
        "pre_max_front_constraint_traction_relative_mismatch": _front_mismatch(result.pre_field),
        "post_max_front_constraint_traction_relative_mismatch": _front_mismatch(result.post_field),
        "maximum_closed_region_volume_relative_error": volume_error,
        "mass_balance_limit": MASS_BALANCE_LIMIT,
        "traction_mismatch_limit": TRACTION_MISMATCH_LIMIT,
        "volume_error_limit": VOLUME_ERROR_LIMIT,
        "preserved_region_ids": list(result.preserved_region_ids),
    }
    payload["passed"] = (
        _phase_conservative(result.pre_field)
        and _phase_conservative(result.post_field)
        and volume_error <= VOLUME_ERROR_LIMIT
        and len(result.preserved_region_ids) == 4
    )
    return _finish(payload, assertions)


def refinement(assertions: bool) -> dict[str, Any]:
    levels = (10, 12, 14)
    results = [_case(cells) for cells in levels]
    event_times = [result.field_event_time_s for result in results]
    tractions = [result.field_hydrodynamic_resistance_n for result in results]
    rows = []
    for cells, result in zip(levels, results):
        rows.append({
            "cells_per_axis": cells,
            "cell_size_m": 0.010 / cells,
            "field_event_time_s": result.field_event_time_s,
            "field_hydrodynamic_resistance_n": result.field_hydrodynamic_resistance_n,
            "pre_aggregate_constraint_traction_relative_mismatch": (
                result.pre_field.aggregate_constraint_traction_relative_mismatch
            ),
            "post_aggregate_constraint_traction_relative_mismatch": (
                result.post_field.aggregate_constraint_traction_relative_mismatch
            ),
            "pre_max_front_constraint_traction_relative_mismatch": _front_mismatch(result.pre_field),
            "post_max_front_constraint_traction_relative_mismatch": _front_mismatch(result.post_field),
            "pre_mass_balance_relative_residual": result.pre_field.mass_balance_relative_residual,
            "post_mass_balance_relative_residual": result.post_field.mass_balance_relative_residual,
            "overlap_cell_count": result.pre_field.support.overlap_cell_count,
        })
    event_monotone = all(first > second for first, second in zip(event_times, event_times[1:]))
    traction_monotone = all(first > second for first, second in zip(tractions, tractions[1:]))
    event_span = _relative_span(event_times)
    traction_span = _relative_span(tractions)
    payload = {
        "benchmark": "t1-refinement",
        "model": results[-1].model,
        "levels": rows,
        "monotone_field_event_time_refinement": event_monotone,
        "monotone_field_traction_refinement": traction_monotone,
        "field_event_time_relative_span": event_span,
        "field_traction_relative_span": traction_span,
        "field_event_time_relative_span_limit": REFINEMENT_EVENT_SPAN_LIMIT,
        "field_traction_relative_span_limit": REFINEMENT_TRACTION_SPAN_LIMIT,
    }
    payload["passed"] = (
        event_monotone
        and traction_monotone
        and event_span <= REFINEMENT_EVENT_SPAN_LIMIT
        and traction_span <= REFINEMENT_TRACTION_SPAN_LIMIT
        and all(_phase_conservative(result.pre_field) for result in results)
        and all(_phase_conservative(result.post_field) for result in results)
        and all(result.pre_field.support.overlap_cell_count > 0 for result in results)
    )
    return _finish(payload, assertions)


def symmetry(assertions: bool) -> dict[str, Any]:
    base = _case()
    replay = _case()
    rotated = _case(axis_cycle=1)
    permuted = _case(reverse_front_order=True)
    rotation_event_error = _relative_error(base.field_event_time_s, rotated.field_event_time_s)
    rotation_traction_error = _relative_error(
        base.field_hydrodynamic_resistance_n,
        rotated.field_hydrodynamic_resistance_n,
    )
    rotation_pre_mismatch_error = abs(
        base.pre_field.aggregate_constraint_traction_relative_mismatch
        - rotated.pre_field.aggregate_constraint_traction_relative_mismatch
    )
    rotation_post_mismatch_error = abs(
        base.post_field.aggregate_constraint_traction_relative_mismatch
        - rotated.post_field.aggregate_constraint_traction_relative_mismatch
    )
    replay_exact = base.as_dict() == replay.as_dict()
    permutation_exact = base.as_dict() == permuted.as_dict()
    payload = {
        "benchmark": "t1-symmetry",
        "model": base.model,
        "deterministic_replay_exact": replay_exact,
        "front_container_permutation_exact": permutation_exact,
        "cyclic_axis_rotation_event_relative_error": rotation_event_error,
        "cyclic_axis_rotation_traction_relative_error": rotation_traction_error,
        "cyclic_axis_rotation_pre_mismatch_absolute_error": rotation_pre_mismatch_error,
        "cyclic_axis_rotation_post_mismatch_absolute_error": rotation_post_mismatch_error,
        "symmetry_relative_limit": SYMMETRY_RELATIVE_LIMIT,
        "rotation_overlap_cell_count_equal": (
            base.pre_field.support.overlap_cell_count
            == rotated.pre_field.support.overlap_cell_count
        ),
    }
    payload["passed"] = (
        replay_exact
        and permutation_exact
        and rotation_event_error <= SYMMETRY_RELATIVE_LIMIT
        and rotation_traction_error <= SYMMETRY_RELATIVE_LIMIT
        and rotation_pre_mismatch_error <= SYMMETRY_RELATIVE_LIMIT
        and rotation_post_mismatch_error <= SYMMETRY_RELATIVE_LIMIT
        and payload["rotation_overlap_cell_count_equal"]
    )
    return _finish(payload, assertions)
