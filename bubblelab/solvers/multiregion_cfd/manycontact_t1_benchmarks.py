"""Acceptance evidence for the bounded many-contact T1/global-CFD foundation."""
from __future__ import annotations

from dataclasses import replace
import json
from typing import Any

from bubblelab.solvers.transient.network.t1_hydrodynamics import (
    build_direct_3d_t1_state,
    detect_direct_t1_eligibility,
)

from .manycontact_t1 import (
    ManyContactT1GlobalCFDSettings,
    ManyContactT1GlobalTransitionResult,
    run_manycontact_t1_global_cfd_transition,
)
from .manycontact_t1_fixtures import build_supported_manycontact_t1_solver
from .t1 import T1GlobalCFDSettings
from .t1_strong import StrongT1GlobalCFDSettings


MASS_BALANCE_LIMIT = 0.20
TRACTION_MISMATCH_LIMIT = 0.20
VOLUME_ERROR_LIMIT = 1.0e-12
PARTITION_ERROR_LIMIT = 1.0e-14
MINIMUM_EVENT_TIME_SHIFT_FRACTION = 0.05
MINIMUM_NON_EVENT_CAUSALITY_FRACTION = 0.02
SYMMETRY_RELATIVE_LIMIT = 1.0e-11
REFINEMENT_RELATIVE_SPAN_LIMIT = 0.25
CONVERGED_FIELD_PSEUDO_STEPS = 20


def _settings(
    *,
    pseudo_steps: int = CONVERGED_FIELD_PSEUDO_STEPS,
) -> ManyContactT1GlobalCFDSettings:
    base = T1GlobalCFDSettings()
    base = replace(
        base,
        field=replace(base.field, pseudo_steps=pseudo_steps),
        pre_event_drift_speed_m_s=0.0,
        maximum_aggregate_traction_mismatch=TRACTION_MISMATCH_LIMIT,
    )
    strong = StrongT1GlobalCFDSettings(
        base=base,
        feedback_iterations=4,
        feedback_relaxation=0.65,
        maximum_feedback_relative_residual=5.0e-3,
    )
    return ManyContactT1GlobalCFDSettings(
        strong=strong,
        minimum_support_regions=5,
        non_event_relative_speed_m_s=0.0005,
        minimum_non_event_causality_fraction=(
            MINIMUM_NON_EVENT_CAUSALITY_FRACTION
        ),
    )


def _case(
    *,
    cells: int = 10,
    pseudo_steps: int = CONVERGED_FIELD_PSEUDO_STEPS,
    axis_cycle: int = 0,
    reverse_front_order: bool = False,
) -> ManyContactT1GlobalTransitionResult:
    settings = _settings(pseudo_steps=pseudo_steps)
    state = build_direct_3d_t1_state(
        mode="saddle-saturation",
        amplitude_m_inv=0.8,
        y_saturation_m=0.04,
        sheet_tension_n_m=0.03,
    )
    eligibility = detect_direct_t1_eligibility(
        state, settings.strong.base.direct
    )
    if not eligibility.eligible or eligibility.neighborhood is None:
        raise AssertionError(
            "many-contact fixture is not directly T1 eligible: "
            f"{eligibility.reason}"
        )
    topology_ids = tuple(
        region.id for region in state.to_network().regions
    )
    support_ids = tuple(sorted((*topology_ids, "E")))
    front_order = (
        tuple(reversed(support_ids))
        if reverse_front_order
        else support_ids
    )
    solver = build_supported_manycontact_t1_solver(
        region_ids=topology_ids,
        old_pair=eligibility.neighborhood.old_adjacent_regions,
        extra_region_id="E",
        cells=cells,
        extent_m=0.010,
        radius_m=0.00105,
        old_pair_gap_m=0.00028,
        transverse_offset_m=0.00275,
        transverse_z_offset_m=0.00160,
        non_event_gap_m=0.00018,
        non_event_lateral_offset_m=0.00025,
        exterior_density_kg_m3=970.0,
        exterior_viscosity_pa_s=50.0,
        interior_density_kg_m3=1.204,
        interior_viscosity_pa_s=1.825e-5,
        pressure_iterations=120,
        pressure_tolerance_s_inv=2.0e-6,
        subdivisions=2,
        front_order=front_order,
        axis_cycle=axis_cycle,
    )
    event_pair = tuple(
        sorted(eligibility.neighborhood.old_adjacent_regions)
    )
    non_event_pair = (event_pair[0], "E")
    return run_manycontact_t1_global_cfd_transition(
        solver,
        state,
        non_event_pair,
        settings,
    )


def _front_mismatch(field: Any) -> float:
    return max(
        (
            value
            for _, value
            in field.front_constraint_traction_relative_mismatch
        ),
        default=0.0,
    )


def _phase_conservative(field: Any) -> bool:
    return (
        field.mass_balance_relative_residual < MASS_BALANCE_LIMIT
        and field.aggregate_constraint_traction_relative_mismatch
        <= TRACTION_MISMATCH_LIMIT
        and _front_mismatch(field) <= TRACTION_MISMATCH_LIMIT
    )


def _relative_error(first: float, second: float) -> float:
    return abs(first - second) / max(
        abs(first), abs(second), 1.0e-30
    )


def _relative_span(values: list[float]) -> float:
    return (max(values) - min(values)) / max(
        max(abs(value) for value in values), 1.0e-30
    )


def _finish(
    payload: dict[str, Any],
    assertions: bool,
) -> dict[str, Any]:
    if assertions and not payload["passed"]:
        raise AssertionError(json.dumps(payload, sort_keys=True))
    return payload


def norm_sq(value: tuple[float, float, float]) -> float:
    return (
        value[0] * value[0]
        + value[1] * value[1]
        + value[2] * value[2]
    )


def feedback(assertions: bool) -> dict[str, Any]:
    result = _case()
    transition = result.transition
    many = result.as_dict()["many_contact"]
    pre_targets = dict(transition.pre_field.target_velocities_world)
    non_event_pair = result.non_event_contact_pair
    non_event_active = all(
        norm_sq(pre_targets[bubble_id]) > 0.0
        for bubble_id in non_event_pair
    )
    row = {
        "support_region_ids": list(result.support_region_ids),
        "support_region_count": len(result.support_region_ids),
        "non_event_contact_pair": list(non_event_pair),
        "simultaneously_active_contact_count": (
            many["simultaneously_active_contact_count"]
        ),
        "feedback_disabled_event_time_s": (
            result.feedback_disabled_event_time_s
        ),
        "field_coupled_event_time_s": transition.field_event_time_s,
        "event_time_shift_fraction": result.event_time_shift_fraction,
        "feedback_relative_residual": result.feedback_relative_residual,
        "field_hydrodynamic_resistance_n": (
            transition.field_hydrodynamic_resistance_n
        ),
        "net_field_coupled_driving_force_n": (
            transition.net_field_coupled_driving_force_n
        ),
        "overlap_cell_count": transition.pre_field.support.overlap_cell_count,
        "maximum_overlap_multiplicity": (
            transition.pre_field.support.maximum_overlap_multiplicity
        ),
        "maximum_partition_sum_error": (
            transition.pre_field.support.maximum_partition_sum_error
        ),
        "non_event_targets_nonzero": non_event_active,
        "authoritative_grid_preserved": (
            transition.authoritative_grid_preserved
        ),
    }
    passed = (
        row["support_region_count"] >= 5
        and row["simultaneously_active_contact_count"] >= 2
        and row["event_time_shift_fraction"]
        >= MINIMUM_EVENT_TIME_SHIFT_FRACTION
        and row["field_coupled_event_time_s"]
        > row["feedback_disabled_event_time_s"]
        and row["feedback_relative_residual"]
        <= _settings().strong.maximum_feedback_relative_residual
        and row["field_hydrodynamic_resistance_n"] > 0.0
        and row["net_field_coupled_driving_force_n"] > 0.0
        and row["overlap_cell_count"] > 0
        and row["maximum_overlap_multiplicity"] >= 2
        and row["maximum_partition_sum_error"] <= PARTITION_ERROR_LIMIT
        and row["non_event_targets_nonzero"]
        and row["authoritative_grid_preserved"]
        and transition.adjacency_before != transition.adjacency_after
        and len(transition.retired_film_ids) == 1
        and len(transition.created_film_ids) == 1
        and len(transition.retired_junction_ids) == 2
        and len(transition.created_junction_ids) == 2
    )
    return _finish(
        {
            "benchmark": "manycontact-t1-feedback",
            "model": transition.model,
            "physical_regime": {
                "sheet_tension_n_m": 0.03,
                "exterior_density_kg_m3": 970.0,
                "exterior_dynamic_viscosity_pa_s": 50.0,
                "interior_density_kg_m3": 1.204,
                "interior_dynamic_viscosity_pa_s": 1.825e-5,
                "coupling": (
                    "one partitioned immersed Eulerian field; resolved "
                    "pressure/viscous traction only"
                ),
            },
            "minimum_event_time_shift_fraction": (
                MINIMUM_EVENT_TIME_SHIFT_FRACTION
            ),
            "result": row,
            "passed": passed,
        },
        assertions,
    )


def causality(assertions: bool) -> dict[str, Any]:
    result = _case()
    transition = result.transition
    time_shift = result.non_event_contact_event_time_shift_fraction
    resistance_shift = (
        result.non_event_contact_resistance_shift_fraction
    )
    passed = (
        max(time_shift, resistance_shift)
        >= MINIMUM_NON_EVENT_CAUSALITY_FRACTION
        and transition.field_hydrodynamic_resistance_n > 0.0
        and result.decoupled_contact_resistance_n > 0.0
        and len(result.support_region_ids) >= 5
    )
    return _finish(
        {
            "benchmark": "manycontact-t1-causality",
            "comparison": (
                "same five-region geometry and same Eulerian solver; only the "
                "non-event contact relative motion is decoupled"
            ),
            "active_contact_event_time_s": transition.field_event_time_s,
            "decoupled_contact_event_time_s": (
                result.decoupled_contact_event_time_s
            ),
            "active_contact_resistance_n": (
                transition.field_hydrodynamic_resistance_n
            ),
            "decoupled_contact_resistance_n": (
                result.decoupled_contact_resistance_n
            ),
            "event_time_shift_fraction": time_shift,
            "resistance_shift_fraction": resistance_shift,
            "minimum_causality_fraction": (
                MINIMUM_NON_EVENT_CAUSALITY_FRACTION
            ),
            "passed": passed,
        },
        assertions,
    )


def conservation(assertions: bool) -> dict[str, Any]:
    result = _case()
    transition = result.transition
    volume_error = max(
        (value for _, value in transition.volume_errors_after),
        default=0.0,
    )
    pre = transition.pre_field
    post = transition.post_field
    row = {
        "support_region_ids": list(result.support_region_ids),
        "pre_mass_balance_relative_residual": (
            pre.mass_balance_relative_residual
        ),
        "post_mass_balance_relative_residual": (
            post.mass_balance_relative_residual
        ),
        "pre_aggregate_constraint_traction_relative_mismatch": (
            pre.aggregate_constraint_traction_relative_mismatch
        ),
        "post_aggregate_constraint_traction_relative_mismatch": (
            post.aggregate_constraint_traction_relative_mismatch
        ),
        "pre_max_front_constraint_traction_relative_mismatch": (
            _front_mismatch(pre)
        ),
        "post_max_front_constraint_traction_relative_mismatch": (
            _front_mismatch(post)
        ),
        "maximum_closed_topology_region_volume_relative_error": (
            volume_error
        ),
        "preserved_topology_region_ids": list(
            transition.preserved_region_ids
        ),
        "authoritative_grid_preserved": (
            transition.authoritative_grid_preserved
        ),
    }
    passed = (
        _phase_conservative(pre)
        and _phase_conservative(post)
        and volume_error <= VOLUME_ERROR_LIMIT
        and len(transition.preserved_region_ids) == 4
        and len(result.support_region_ids) >= 5
        and transition.authoritative_grid_preserved
    )
    row["passed"] = passed
    return _finish(
        {
            "benchmark": "manycontact-t1-conservation",
            "mass_balance_limit": MASS_BALANCE_LIMIT,
            "traction_mismatch_limit": TRACTION_MISMATCH_LIMIT,
            "volume_error_limit": VOLUME_ERROR_LIMIT,
            "result": row,
            "passed": passed,
        },
        assertions,
    )


def refinement(assertions: bool) -> dict[str, Any]:
    levels = (8, 10, 12)
    results = [_case(cells=cells) for cells in levels]
    event_times = [
        result.transition.field_event_time_s for result in results
    ]
    shifts = [
        result.event_time_shift_fraction for result in results
    ]
    resistances = [
        result.transition.field_hydrodynamic_resistance_n
        for result in results
    ]
    causalities = [
        max(
            result.non_event_contact_event_time_shift_fraction,
            result.non_event_contact_resistance_shift_fraction,
        )
        for result in results
    ]
    rows = []
    for cells, result, causality_value in zip(
        levels, results, causalities
    ):
        transition = result.transition
        rows.append(
            {
                "cells_per_axis": cells,
                "cell_size_m": 0.010 / cells,
                "field_event_time_s": transition.field_event_time_s,
                "event_time_shift_fraction": (
                    result.event_time_shift_fraction
                ),
                "non_event_causality_fraction": causality_value,
                "field_hydrodynamic_resistance_n": (
                    transition.field_hydrodynamic_resistance_n
                ),
                "feedback_relative_residual": (
                    result.feedback_relative_residual
                ),
                "pre_mass_balance_relative_residual": (
                    transition.pre_field.mass_balance_relative_residual
                ),
                "post_mass_balance_relative_residual": (
                    transition.post_field.mass_balance_relative_residual
                ),
                "pre_max_front_constraint_traction_relative_mismatch": (
                    _front_mismatch(transition.pre_field)
                ),
                "post_max_front_constraint_traction_relative_mismatch": (
                    _front_mismatch(transition.post_field)
                ),
                "overlap_cell_count": (
                    transition.pre_field.support.overlap_cell_count
                ),
            }
        )
    event_span = _relative_span(event_times)
    shift_span = _relative_span(shifts)
    resistance_span = _relative_span(resistances)
    passed = (
        max(event_span, shift_span, resistance_span)
        <= REFINEMENT_RELATIVE_SPAN_LIMIT
        and all(
            shift >= MINIMUM_EVENT_TIME_SHIFT_FRACTION
            for shift in shifts
        )
        and all(
            causality >= MINIMUM_NON_EVENT_CAUSALITY_FRACTION
            for causality in causalities
        )
        and all(
            _phase_conservative(result.transition.pre_field)
            for result in results
        )
        and all(
            _phase_conservative(result.transition.post_field)
            for result in results
        )
        and all(
            result.transition.pre_field.support.overlap_cell_count > 0
            for result in results
        )
    )
    return _finish(
        {
            "benchmark": "manycontact-t1-refinement",
            "levels": rows,
            "field_event_time_relative_span": event_span,
            "event_time_shift_relative_span": shift_span,
            "field_resistance_relative_span": resistance_span,
            "relative_span_limit": REFINEMENT_RELATIVE_SPAN_LIMIT,
            "minimum_event_time_shift_fraction": (
                MINIMUM_EVENT_TIME_SHIFT_FRACTION
            ),
            "minimum_non_event_causality_fraction": (
                MINIMUM_NON_EVENT_CAUSALITY_FRACTION
            ),
            "passed": passed,
        },
        assertions,
    )


def symmetry(assertions: bool) -> dict[str, Any]:
    base = _case()
    replay = _case()
    rotated = _case(axis_cycle=1)
    permuted = _case(reverse_front_order=True)
    replay_exact = base.as_dict() == replay.as_dict()
    permutation_exact = base.as_dict() == permuted.as_dict()
    event_error = _relative_error(
        base.transition.field_event_time_s,
        rotated.transition.field_event_time_s,
    )
    shift_error = _relative_error(
        base.event_time_shift_fraction,
        rotated.event_time_shift_fraction,
    )
    resistance_error = _relative_error(
        base.transition.field_hydrodynamic_resistance_n,
        rotated.transition.field_hydrodynamic_resistance_n,
    )
    causality_error = _relative_error(
        max(
            base.non_event_contact_event_time_shift_fraction,
            base.non_event_contact_resistance_shift_fraction,
        ),
        max(
            rotated.non_event_contact_event_time_shift_fraction,
            rotated.non_event_contact_resistance_shift_fraction,
        ),
    )
    payload = {
        "benchmark": "manycontact-t1-symmetry",
        "deterministic_replay_exact": replay_exact,
        "front_container_permutation_exact": permutation_exact,
        "cyclic_axis_rotation_event_relative_error": event_error,
        "cyclic_axis_rotation_shift_relative_error": shift_error,
        "cyclic_axis_rotation_resistance_relative_error": (
            resistance_error
        ),
        "cyclic_axis_rotation_causality_relative_error": (
            causality_error
        ),
        "rotation_overlap_cell_count_equal": (
            base.transition.pre_field.support.overlap_cell_count
            == rotated.transition.pre_field.support.overlap_cell_count
        ),
        "symmetry_relative_limit": SYMMETRY_RELATIVE_LIMIT,
    }
    payload["passed"] = (
        replay_exact
        and permutation_exact
        and event_error <= SYMMETRY_RELATIVE_LIMIT
        and shift_error <= SYMMETRY_RELATIVE_LIMIT
        and resistance_error <= SYMMETRY_RELATIVE_LIMIT
        and causality_error <= SYMMETRY_RELATIVE_LIMIT
        and payload["rotation_overlap_cell_count_equal"]
    )
    return _finish(payload, assertions)
