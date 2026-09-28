"""Strongly field-coupled bounded four-region T1 transition.

This module builds on the accepted partitioned immersed T1/global-CFD path but
closes the remaining feedback loop.  The pre-T1 relative closing speed is not a
prescribed diagnostic speed.  It is solved from the overdamped balance

    v = M * (F_capillary - F_CFD(v)),

where every evaluation of ``F_CFD`` comes from pressure/viscous traction on the
same authoritative Eulerian field object.  Picard evaluations restore a baseline
state of that object rather than creating pairwise or surrogate CFD solves.  A
final production evaluation must satisfy the mobility balance to the configured
relative residual before the real direct-geometry T1 transaction is committed.
The resulting Eulerian field is then continued directly on the post-T1 topology.

The implementation is deliberately bounded to the already accepted isolated
four-region, genuinely non-coplanar T1 class with four closed quasi-spherical
support fronts and partitioned overlapping immersed support.  It is not a claim
of singular Plateau-border CFD or arbitrary-contact multiphase Navier-Stokes.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from bubblelab.solvers.transient.network import t1_hydrodynamics as _direct_t1

from . import core as _core
from .t1 import (
    T1GlobalCFDSettings,
    T1GlobalTransitionResult,
    T1SharedFieldResult,
    _hydrodynamic_resistance_on_pair,
    _pair_targets,
    solve_t1_shared_field,
)


STRONG_TRANSITION_MODEL_ID = "GLOBAL_3D_FOUR_REGION_STRONGLY_FIELD_COUPLED_T1_TRANSITION"


@dataclass(frozen=True)
class StrongT1GlobalCFDSettings:
    """Numerical controls for the bounded strongly coupled T1 mobility solve."""

    base: T1GlobalCFDSettings = T1GlobalCFDSettings()
    feedback_iterations: int = 6
    feedback_relaxation: float = 0.65
    maximum_feedback_relative_residual: float = 5.0e-3

    def validate(self) -> None:
        self.base.validate()
        if self.feedback_iterations < 2:
            raise ValueError("strong T1 feedback requires at least two iterations")
        if not 0.0 < self.feedback_relaxation <= 1.0:
            raise ValueError("strong T1 feedback_relaxation must lie in (0, 1]")
        if not 0.0 < self.maximum_feedback_relative_residual <= 0.05:
            raise ValueError(
                "strong T1 maximum_feedback_relative_residual must lie in (0, 0.05]"
            )


@dataclass(frozen=True)
class StrongT1GlobalTransitionResult:
    """Strong-coupling evidence wrapped around the accepted transition payload."""

    transition: T1GlobalTransitionResult
    trial_field: T1SharedFieldResult
    feedback_disabled_event_time_s: float
    feedback_disabled_closing_speed_m_s: float
    production_field_target_closing_speed_m_s: float
    coupled_closing_speed_m_s: float
    feedback_iterations: int
    feedback_relative_residual: float
    event_time_shift_fraction: float

    def as_dict(self) -> dict[str, object]:
        payload = self.transition.as_dict()
        payload["strong_coupling"] = {
            "feedback_disabled_event_time_s": float(
                self.feedback_disabled_event_time_s
            ),
            "feedback_disabled_closing_speed_m_s": float(
                self.feedback_disabled_closing_speed_m_s
            ),
            "production_field_target_closing_speed_m_s": float(
                self.production_field_target_closing_speed_m_s
            ),
            "coupled_closing_speed_m_s": float(self.coupled_closing_speed_m_s),
            "feedback_iterations": int(self.feedback_iterations),
            "feedback_relative_residual": float(self.feedback_relative_residual),
            "event_time_shift_fraction": float(self.event_time_shift_fraction),
            "trial_field": self.trial_field.as_dict(),
            "balance": (
                "v = event_mobility * (resolved direct-3D capillary drive - "
                "pressure/viscous resistance from the authoritative Eulerian field at v)"
            ),
            "disabled_reference": (
                "same direct 3D geometry and event mobility with Eulerian field feedback disabled"
            ),
        }
        return payload


def _pre_field_at_speed(
    solver: Any,
    old_pair: tuple[str, str],
    relative_speed_m_s: float,
    settings: T1GlobalCFDSettings,
) -> T1SharedFieldResult:
    targets = _pair_targets(
        solver,
        old_pair,
        relative_speed_m_s=relative_speed_m_s,
        drift_speed_m_s=settings.pre_event_drift_speed_m_s,
        opening=False,
    )
    return solve_t1_shared_field(
        solver,
        targets,
        phase="PRE_T1_STRONG_COUPLING",
        settings=settings,
    )


def _speed_from_field(
    solver: Any,
    old_pair: tuple[str, str],
    field: T1SharedFieldResult,
    capillary_force_n: float,
    settings: T1GlobalCFDSettings,
) -> tuple[float, float, float]:
    resistance = _hydrodynamic_resistance_on_pair(solver, old_pair, field)
    net_force = capillary_force_n - resistance
    if net_force <= settings.minimum_net_driving_force_n:
        raise ValueError(
            "shared-field traction stalls the supported strongly coupled T1 collapse: "
            f"net drive {net_force:.6e} N"
        )
    speed = settings.event_mobility_m_per_n_s * net_force
    return speed, resistance, net_force


def run_strongly_coupled_t1_global_cfd_transition(
    solver: Any,
    topology_state: _direct_t1.TransientNetworkState,
    settings: StrongT1GlobalCFDSettings | None = None,
) -> StrongT1GlobalTransitionResult:
    """Solve one bounded T1 with a self-consistent CFD/closing-speed feedback loop."""

    cfg = settings or StrongT1GlobalCFDSettings()
    cfg.validate()
    base = cfg.base

    eligibility = _direct_t1.detect_direct_t1_eligibility(topology_state, base.direct)
    if not eligibility.eligible or eligibility.neighborhood is None:
        raise ValueError(f"unsupported direct 3D T1 neighborhood: {eligibility.reason}")
    neighborhood = eligibility.neighborhood
    gas_ids = tuple(sorted(region.id for region in topology_state.to_network().regions))
    if set(gas_ids) != {front.bubble_id for front in solver.fronts}:
        raise ValueError("closed CFD support fronts must carry exactly the T1 gas-region IDs")

    capillary_force = _direct_t1._direct_gap_capillary_force(
        topology_state.to_network(), neighborhood
    )
    if capillary_force <= base.minimum_net_driving_force_n:
        raise ValueError("direct 3D capillary drive is non-positive for strong T1 coupling")
    travel = eligibility.initial_gap_m - eligibility.event_gap_m
    if travel <= 0.0:
        raise ValueError("T1 geometry has no positive pre-event travel distance")

    free_speed = base.event_mobility_m_per_n_s * capillary_force
    if free_speed <= 0.0:
        raise ValueError("capillary-only T1 closing speed must be positive")
    disabled_event_time = travel / free_speed

    # Region/material labels are part of the physical fixture and remain fixed through
    # the bounded pre-event mobility iteration.  Snapshot only the evolving field.
    solver._refresh_regions()
    grid_identity = id(solver.grid)
    baseline = _core._snapshot(solver.grid)

    _core._restore(solver.grid, baseline)
    trial = _pre_field_at_speed(
        solver, neighborhood.old_adjacent_regions, free_speed, base
    )
    current_speed = free_speed
    last_field = trial

    for iteration in range(cfg.feedback_iterations):
        if iteration > 0:
            _core._restore(solver.grid, baseline)
            last_field = _pre_field_at_speed(
                solver, neighborhood.old_adjacent_regions, current_speed, base
            )
        proposal_speed, _, _ = _speed_from_field(
            solver,
            neighborhood.old_adjacent_regions,
            last_field,
            capillary_force,
            base,
        )
        current_speed = (
            (1.0 - cfg.feedback_relaxation) * current_speed
            + cfg.feedback_relaxation * proposal_speed
        )

    # First production candidate at the relaxed fixed-point estimate.
    _core._restore(solver.grid, baseline)
    candidate_field = _pre_field_at_speed(
        solver, neighborhood.old_adjacent_regions, current_speed, base
    )
    resolved_speed, _, _ = _speed_from_field(
        solver,
        neighborhood.old_adjacent_regions,
        candidate_field,
        capillary_force,
        base,
    )

    # One final field solve at the force-balance proposal makes the reported
    # production field and the event speed mutually consistent to a measurable gate.
    production_target_speed = resolved_speed
    _core._restore(solver.grid, baseline)
    production_field = _pre_field_at_speed(
        solver,
        neighborhood.old_adjacent_regions,
        production_target_speed,
        base,
    )
    coupled_speed, hydro_resistance, net_force = _speed_from_field(
        solver,
        neighborhood.old_adjacent_regions,
        production_field,
        capillary_force,
        base,
    )
    feedback_residual = abs(coupled_speed - production_target_speed) / max(
        free_speed, 1.0e-30
    )
    if feedback_residual > cfg.maximum_feedback_relative_residual:
        raise ValueError(
            "strong T1 field/mobility feedback failed to converge: "
            f"relative residual {feedback_residual:.6e} exceeds "
            f"{cfg.maximum_feedback_relative_residual:.6e}"
        )

    field_event_time = travel / coupled_speed
    shift = field_event_time / disabled_event_time - 1.0

    transaction = _direct_t1.perform_direct_t1_transaction(
        topology_state, base.direct
    )
    after_state = replace(
        transaction.after,
        time_s=topology_state.time_s + field_event_time,
    )
    new_pair = tuple(sorted(neighborhood.opposite_regions))
    post_targets = _pair_targets(
        solver,
        new_pair,
        relative_speed_m_s=base.post_event_opening_speed_m_s,
        drift_speed_m_s=0.0,
        opening=True,
    )
    # Deliberately do not restore the baseline here: the production Eulerian field
    # is the field continued through the topology transaction.
    post_field = solve_t1_shared_field(
        solver,
        post_targets,
        phase="POST_T1_STRONG_COUPLING",
        settings=base,
    )
    authoritative_grid_preserved = id(solver.grid) == grid_identity

    transition = T1GlobalTransitionResult(
        model=STRONG_TRANSITION_MODEL_ID,
        supported_class=(
            "isolated four-region genuinely non-coplanar direct-geometry T1 with "
            "four closed overlapping support fronts on one partitioned immersed "
            "Eulerian field and self-consistent field/mobility feedback"
        ),
        pre_field=production_field,
        post_field=post_field,
        field_event_time_s=field_event_time,
        direct_geometry_diagnostic_event_time_s=transaction.forecast.event_time_s,
        initial_gap_m=eligibility.initial_gap_m,
        event_gap_m=eligibility.event_gap_m,
        capillary_driving_force_n=capillary_force,
        field_hydrodynamic_resistance_n=hydro_resistance,
        net_field_coupled_driving_force_n=net_force,
        adjacency_before=transaction.adjacency_before,
        adjacency_after=transaction.adjacency_after,
        retired_film_ids=transaction.lineage.retired_film_ids,
        created_film_ids=transaction.lineage.created_film_ids,
        retired_junction_ids=transaction.lineage.retired_junction_ids,
        created_junction_ids=transaction.lineage.created_junction_ids,
        preserved_region_ids=transaction.lineage.preserved_region_ids,
        volume_errors_after=transaction.volume_errors_after,
        authoritative_grid_preserved=authoritative_grid_preserved,
        topology_state_after=after_state,
    )
    return StrongT1GlobalTransitionResult(
        transition=transition,
        trial_field=trial,
        feedback_disabled_event_time_s=disabled_event_time,
        feedback_disabled_closing_speed_m_s=free_speed,
        production_field_target_closing_speed_m_s=production_target_speed,
        coupled_closing_speed_m_s=coupled_speed,
        feedback_iterations=cfg.feedback_iterations,
        feedback_relative_residual=feedback_residual,
        event_time_shift_fraction=shift,
    )
