"""Bounded many-contact T1 transition through one authoritative Eulerian CFD field.

This module embeds the accepted four-region direct-geometry T1 neighborhood in a
larger immersed support system.  Five or more stable closed fronts are advanced
on one Eulerian pressure/velocity field.  The production T1 mobility balance uses
only pressure/viscous traction recovered from that shared field.  A second,
non-event contact remains active while the T1 occurs, and its influence is
measured against an otherwise identical decoupled-contact reference.

The direct topology transaction still owns the local four-region film/junction
surgery.  Extra support regions are hydrodynamic participants, not synthetic
topology nodes.  The same production Eulerian field is continued after the
transaction; no isolated four-region field solve or pair-force superposition is
used.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from bubblelab.solvers.transient.geometry import Vec3, norm
from bubblelab.solvers.transient.grid import EulerianGasGrid
from bubblelab.solvers.transient.network import t1_hydrodynamics as _direct_t1

from . import core as _core
from .t1 import (
    T1GlobalTransitionResult,
    T1SharedFieldResult,
    _add,
    _constraint_partition,
    _hydrodynamic_resistance_on_pair,
    _mul,
    _pair_targets,
    _partitioned_control_surface_tractions,
    _sub,
    _sum_vectors,
)
from .t1_strong import StrongT1GlobalCFDSettings


MODEL_ID = "GLOBAL_3D_MANYCONTACT_T1_PARTITIONED_IMMERSED_CFD"
TRANSITION_MODEL_ID = "GLOBAL_3D_MANYCONTACT_STRONGLY_FIELD_COUPLED_T1_TRANSITION"


@dataclass(frozen=True)
class ManyContactT1GlobalCFDSettings:
    """Numerical and physical controls for the bounded many-contact transition."""

    strong: StrongT1GlobalCFDSettings = StrongT1GlobalCFDSettings()
    minimum_support_regions: int = 5
    non_event_relative_speed_m_s: float = 0.0005
    minimum_non_event_causality_fraction: float = 0.02

    def validate(self) -> None:
        self.strong.validate()
        if self.minimum_support_regions < 5:
            raise ValueError("many-contact T1 requires at least five support regions")
        if self.non_event_relative_speed_m_s <= 0.0:
            raise ValueError("many-contact non-event relative speed must be positive")
        if not 0.0 < self.minimum_non_event_causality_fraction <= 0.20:
            raise ValueError(
                "many-contact causality floor must lie in (0, 0.20]"
            )


@dataclass(frozen=True)
class _FeedbackSolution:
    trial_field: T1SharedFieldResult
    production_field: T1SharedFieldResult
    production_target_speed_m_s: float
    coupled_speed_m_s: float
    hydrodynamic_resistance_n: float
    net_force_n: float
    feedback_relative_residual: float
    event_time_s: float


@dataclass(frozen=True)
class ManyContactT1GlobalTransitionResult:
    """Many-contact evidence wrapped around the conservative T1 transaction."""

    transition: T1GlobalTransitionResult
    trial_field: T1SharedFieldResult
    support_region_ids: tuple[str, ...]
    non_event_contact_pair: tuple[str, str]
    feedback_disabled_event_time_s: float
    feedback_disabled_closing_speed_m_s: float
    production_field_target_closing_speed_m_s: float
    coupled_closing_speed_m_s: float
    feedback_iterations: int
    feedback_relative_residual: float
    event_time_shift_fraction: float
    decoupled_contact_event_time_s: float
    decoupled_contact_resistance_n: float
    non_event_contact_event_time_shift_fraction: float
    non_event_contact_resistance_shift_fraction: float

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
                "pressure/viscous resistance from the one authoritative "
                "many-contact Eulerian field at v)"
            ),
        }
        payload["many_contact"] = {
            "support_region_ids": list(self.support_region_ids),
            "support_region_count": len(self.support_region_ids),
            "non_event_contact_pair": list(self.non_event_contact_pair),
            "simultaneously_active_contact_count": 2,
            "decoupled_contact_event_time_s": float(
                self.decoupled_contact_event_time_s
            ),
            "decoupled_contact_resistance_n": float(
                self.decoupled_contact_resistance_n
            ),
            "non_event_contact_event_time_shift_fraction": float(
                self.non_event_contact_event_time_shift_fraction
            ),
            "non_event_contact_resistance_shift_fraction": float(
                self.non_event_contact_resistance_shift_fraction
            ),
            "coupling": (
                "event and non-event contact velocities are imposed together "
                "before one partitioned immersed forcing update and one pressure "
                "projection per pseudo-step; no pairwise force law is summed"
            ),
        }
        return payload


def _normalize_targets(
    solver: Any,
    target_velocities_world: Mapping[str, Vec3],
) -> dict[str, Vec3]:
    ids = {front.bubble_id for front in solver.fronts}
    if set(target_velocities_world) != ids:
        raise ValueError(
            "many-contact target velocity map must contain exactly all support IDs"
        )
    return {
        key: (float(value[0]), float(value[1]), float(value[2]))
        for key, value in sorted(target_velocities_world.items())
    }


def _validate_manycontact_solver(
    solver: Any,
    cfg: ManyContactT1GlobalCFDSettings,
) -> tuple[EulerianGasGrid, tuple[Any, ...]]:
    cfg.validate()
    if len(solver.fronts) < cfg.minimum_support_regions:
        raise ValueError(
            f"many-contact T1 requires at least {cfg.minimum_support_regions} "
            "closed support fronts"
        )
    if type(solver.grid) is not EulerianGasGrid:
        raise ValueError(
            "many-contact T1 currently requires the base EulerianGasGrid"
        )
    solver._refresh_regions()
    ordered = tuple(sorted(solver.fronts, key=lambda item: item.bubble_id))
    if len({front.bubble_id for front in ordered}) != len(ordered):
        raise ValueError("many-contact T1 requires unique stable support IDs")
    for front in ordered:
        error = _core._front_sphericity_error(front)
        if error > cfg.strong.base.field.maximum_sphericity_error:
            raise ValueError(
                f"front {front.bubble_id!r} exceeds many-contact support "
                f"sphericity limit: {error:.6g}"
            )
    return solver.grid, ordered


def solve_manycontact_shared_field(
    solver: Any,
    target_velocities_world: Mapping[str, Vec3],
    *,
    phase: str,
    settings: ManyContactT1GlobalCFDSettings | None = None,
) -> T1SharedFieldResult:
    """Advance five or more immersed fronts on one partitioned Eulerian field."""

    cfg = settings or ManyContactT1GlobalCFDSettings()
    grid, fronts = _validate_manycontact_solver(solver, cfg)
    base = cfg.strong.base
    targets = _normalize_targets(solver, target_velocities_world)
    mappings, combined, support = _constraint_partition(
        grid, fronts, targets, base
    )

    max_nu = max(
        (
            mu / rho
            for mu, rho in zip(grid.dynamic_viscosity, grid.density)
            if rho > 0.0
        ),
        default=0.0,
    )
    speed_scale = max(
        (norm(value) for value in targets.values()), default=1.0e-12
    )
    if max_nu > 0.0:
        pseudo_dt = base.field.viscous_cfl * grid.h * grid.h / max_nu
    else:
        pseudo_dt = 0.1 * grid.h / max(speed_scale, 1.0e-6)
    pseudo_dt = max(pseudo_dt, 1.0e-8)

    last_reactions = {
        front.bubble_id: (0.0, 0.0, 0.0) for front in fronts
    }
    for _ in range(base.field.pseudo_steps):
        before = (list(grid.u), list(grid.v), list(grid.w))
        fields: list[list[float]] = []
        for axis_index, component in enumerate(before):
            viscous = grid._variable_viscous_term(component, axis_index)
            fields.append(
                [
                    value + pseudo_dt * derivative
                    for value, derivative in zip(component, viscous)
                ]
            )

        reactions = {
            front.bubble_id: (0.0, 0.0, 0.0) for front in fronts
        }
        for q in sorted(combined):
            strength, target, shares = combined[q]
            blend = base.field.constraint_relaxation * strength
            old = (fields[0][q], fields[1][q], fields[2][q])
            new = (
                old[0] + blend * (target[0] - old[0]),
                old[1] + blend * (target[1] - old[1]),
                old[2] + blend * (target[2] - old[2]),
            )
            fields[0][q], fields[1][q], fields[2][q] = new
            scale = grid.density[q] * grid.cell_volume / pseudo_dt
            reaction_total = _mul(_sub(new, old), -scale)
            for bubble_id, weight in shares:
                reactions[bubble_id] = _add(
                    reactions[bubble_id], _mul(reaction_total, weight)
                )

        projected = grid.project(
            (fields[0], fields[1], fields[2]), pseudo_dt
        )
        grid.u, grid.v, grid.w = (
            list(projected[0]),
            list(projected[1]),
            list(projected[2]),
        )
        last_reactions = reactions

    tractions = _partitioned_control_surface_tractions(
        grid, fronts, mappings
    )
    traction_map = {
        item.bubble_id: item.total_force_n for item in tractions
    }
    reaction_map = last_reactions
    front_mismatches: list[tuple[str, float]] = []
    force_scale = max(
        sum(norm(value) for value in traction_map.values())
        / max(len(traction_map), 1),
        sum(norm(value) for value in reaction_map.values())
        / max(len(reaction_map), 1),
        1.0e-30,
    )
    for bubble_id in sorted(traction_map):
        traction = traction_map[bubble_id]
        reaction = reaction_map[bubble_id]
        denominator = max(
            norm(traction),
            norm(reaction),
            0.05 * force_scale,
            1.0e-30,
        )
        front_mismatches.append(
            (
                bubble_id,
                norm(_sub(traction, reaction)) / denominator,
            )
        )

    total_traction = _sum_vectors(tuple(traction_map.values()))
    total_reaction = _sum_vectors(tuple(reaction_map.values()))
    aggregate_mismatch = norm(
        _sub(total_traction, total_reaction)
    ) / max(
        norm(total_traction),
        norm(total_reaction),
        force_scale,
        1.0e-30,
    )
    global_force_imbalance = norm(total_traction) / max(
        sum(norm(value) for value in traction_map.values()), 1.0e-30
    )
    divergence = grid.divergence_linf()
    mass_relative = divergence * grid.h / max(speed_scale, 1.0e-12)
    return T1SharedFieldResult(
        model=MODEL_ID,
        phase=phase,
        target_velocities_world=tuple(sorted(targets.items())),
        pseudo_dt_s=float(pseudo_dt),
        pseudo_steps=base.field.pseudo_steps,
        support=support,
        constraint_cell_counts=tuple(
            sorted(
                (bubble_id, len(mapping))
                for bubble_id, mapping in mappings.items()
            )
        ),
        region_cell_counts=_core._region_counts(grid),
        pressure_linf_pa=max(
            (abs(value) for value in grid.pressure), default=0.0
        ),
        max_speed_m_s=grid.max_speed(),
        divergence_linf_s_inv=divergence,
        mass_balance_relative_residual=mass_relative,
        projection_residual_s_inv=grid.last_projection_residual,
        pressure_iterations=grid.last_projection_iterations,
        tractions=tractions,
        constraint_reaction_forces_n=tuple(
            sorted(reaction_map.items())
        ),
        front_constraint_traction_relative_mismatch=tuple(
            front_mismatches
        ),
        aggregate_constraint_traction_relative_mismatch=aggregate_mismatch,
        global_force_relative_imbalance=global_force_imbalance,
    )


def _combined_contact_targets(
    solver: Any,
    event_pair: tuple[str, str],
    *,
    event_relative_speed_m_s: float,
    event_opening: bool,
    non_event_pair: tuple[str, str],
    non_event_relative_speed_m_s: float,
) -> dict[str, Vec3]:
    event_targets = _pair_targets(
        solver,
        event_pair,
        relative_speed_m_s=event_relative_speed_m_s,
        drift_speed_m_s=0.0,
        opening=event_opening,
    )
    non_event_targets = _pair_targets(
        solver,
        non_event_pair,
        relative_speed_m_s=non_event_relative_speed_m_s,
        drift_speed_m_s=0.0,
        opening=False,
    )
    return {
        bubble_id: _add(
            event_targets[bubble_id], non_event_targets[bubble_id]
        )
        for bubble_id in sorted(event_targets)
    }


def _field_at_speed(
    solver: Any,
    event_pair: tuple[str, str],
    speed_m_s: float,
    non_event_pair: tuple[str, str],
    non_event_speed_m_s: float,
    settings: ManyContactT1GlobalCFDSettings,
    *,
    phase: str,
) -> T1SharedFieldResult:
    targets = _combined_contact_targets(
        solver,
        event_pair,
        event_relative_speed_m_s=speed_m_s,
        event_opening=False,
        non_event_pair=non_event_pair,
        non_event_relative_speed_m_s=non_event_speed_m_s,
    )
    return solve_manycontact_shared_field(
        solver, targets, phase=phase, settings=settings
    )


def _speed_from_field(
    solver: Any,
    event_pair: tuple[str, str],
    field: T1SharedFieldResult,
    capillary_force_n: float,
    settings: ManyContactT1GlobalCFDSettings,
) -> tuple[float, float, float]:
    resistance = _hydrodynamic_resistance_on_pair(
        solver, event_pair, field
    )
    net_force = capillary_force_n - resistance
    base = settings.strong.base
    if net_force <= base.minimum_net_driving_force_n:
        raise ValueError(
            "many-contact field traction stalls the supported T1 collapse: "
            f"net drive {net_force:.6e} N"
        )
    speed = base.event_mobility_m_per_n_s * net_force
    return speed, resistance, net_force


def _feedback_solution(
    solver: Any,
    baseline: object,
    event_pair: tuple[str, str],
    non_event_pair: tuple[str, str],
    non_event_speed_m_s: float,
    capillary_force_n: float,
    travel_m: float,
    free_speed_m_s: float,
    settings: ManyContactT1GlobalCFDSettings,
    *,
    phase_prefix: str,
) -> _FeedbackSolution:
    strong = settings.strong
    _core._restore(solver.grid, baseline)
    trial = _field_at_speed(
        solver,
        event_pair,
        free_speed_m_s,
        non_event_pair,
        non_event_speed_m_s,
        settings,
        phase=f"{phase_prefix}_TRIAL",
    )
    current_speed = free_speed_m_s
    last_field = trial

    for iteration in range(strong.feedback_iterations):
        if iteration > 0:
            _core._restore(solver.grid, baseline)
            last_field = _field_at_speed(
                solver,
                event_pair,
                current_speed,
                non_event_pair,
                non_event_speed_m_s,
                settings,
                phase=f"{phase_prefix}_PICARD",
            )
        proposal_speed, _, _ = _speed_from_field(
            solver,
            event_pair,
            last_field,
            capillary_force_n,
            settings,
        )
        current_speed = (
            (1.0 - strong.feedback_relaxation) * current_speed
            + strong.feedback_relaxation * proposal_speed
        )

    _core._restore(solver.grid, baseline)
    candidate = _field_at_speed(
        solver,
        event_pair,
        current_speed,
        non_event_pair,
        non_event_speed_m_s,
        settings,
        phase=f"{phase_prefix}_CANDIDATE",
    )
    resolved_speed, _, _ = _speed_from_field(
        solver, event_pair, candidate, capillary_force_n, settings
    )

    production_target_speed = resolved_speed
    _core._restore(solver.grid, baseline)
    production_field = _field_at_speed(
        solver,
        event_pair,
        production_target_speed,
        non_event_pair,
        non_event_speed_m_s,
        settings,
        phase=f"{phase_prefix}_PRODUCTION",
    )
    coupled_speed, resistance, net_force = _speed_from_field(
        solver,
        event_pair,
        production_field,
        capillary_force_n,
        settings,
    )
    feedback_residual = abs(
        coupled_speed - production_target_speed
    ) / max(free_speed_m_s, 1.0e-30)
    if feedback_residual > strong.maximum_feedback_relative_residual:
        raise ValueError(
            "many-contact T1 field/mobility feedback failed to converge: "
            f"relative residual {feedback_residual:.6e} exceeds "
            f"{strong.maximum_feedback_relative_residual:.6e}"
        )
    return _FeedbackSolution(
        trial_field=trial,
        production_field=production_field,
        production_target_speed_m_s=production_target_speed,
        coupled_speed_m_s=coupled_speed,
        hydrodynamic_resistance_n=resistance,
        net_force_n=net_force,
        feedback_relative_residual=feedback_residual,
        event_time_s=travel_m / coupled_speed,
    )


def run_manycontact_t1_global_cfd_transition(
    solver: Any,
    topology_state: _direct_t1.TransientNetworkState,
    non_event_contact_pair: tuple[str, str],
    settings: ManyContactT1GlobalCFDSettings | None = None,
) -> ManyContactT1GlobalTransitionResult:
    """Cross one real T1 while another immersed contact stays active."""

    cfg = settings or ManyContactT1GlobalCFDSettings()
    grid, _ = _validate_manycontact_solver(solver, cfg)
    base = cfg.strong.base

    eligibility = _direct_t1.detect_direct_t1_eligibility(
        topology_state, base.direct
    )
    if not eligibility.eligible or eligibility.neighborhood is None:
        raise ValueError(
            f"unsupported direct 3D T1 neighborhood: {eligibility.reason}"
        )
    neighborhood = eligibility.neighborhood
    topology_ids = tuple(
        sorted(region.id for region in topology_state.to_network().regions)
    )
    support_ids = tuple(
        sorted(front.bubble_id for front in solver.fronts)
    )
    if not set(topology_ids).issubset(support_ids):
        raise ValueError(
            "all four T1 gas-region IDs must be present in the support field"
        )
    if len(support_ids) < cfg.minimum_support_regions:
        raise ValueError("many-contact support system is too small")

    non_event_pair = tuple(sorted(non_event_contact_pair))
    if len(set(non_event_pair)) != 2 or not set(non_event_pair).issubset(
        support_ids
    ):
        raise ValueError(
            "non-event contact must contain two distinct support IDs"
        )
    if non_event_pair == tuple(
        sorted(neighborhood.old_adjacent_regions)
    ):
        raise ValueError(
            "non-event contact must differ from the T1 event pair"
        )
    if set(non_event_pair).issubset(topology_ids):
        raise ValueError(
            "non-event contact must include at least one extra support region"
        )

    capillary_force = _direct_t1._direct_gap_capillary_force(
        topology_state.to_network(), neighborhood
    )
    if capillary_force <= base.minimum_net_driving_force_n:
        raise ValueError(
            "direct 3D capillary drive is non-positive for many-contact T1"
        )
    travel = eligibility.initial_gap_m - eligibility.event_gap_m
    if travel <= 0.0:
        raise ValueError(
            "many-contact T1 geometry has no positive pre-event travel"
        )
    free_speed = base.event_mobility_m_per_n_s * capillary_force
    if free_speed <= 0.0:
        raise ValueError("capillary-only T1 closing speed must be positive")
    feedback_disabled_event_time = travel / free_speed

    solver._refresh_regions()
    grid_identity = id(grid)
    baseline = _core._snapshot(grid)

    # The causal reference keeps all five-plus support regions on the same field,
    # but disables only the non-event contact's relative motion.
    decoupled = _feedback_solution(
        solver,
        baseline,
        neighborhood.old_adjacent_regions,
        non_event_pair,
        0.0,
        capillary_force,
        travel,
        free_speed,
        cfg,
        phase_prefix="PRE_T1_MANYCONTACT_DECOUPLED",
    )

    # Re-run from the identical field baseline with the second contact active.
    # The final active production field is intentionally left on the grid.
    active = _feedback_solution(
        solver,
        baseline,
        neighborhood.old_adjacent_regions,
        non_event_pair,
        cfg.non_event_relative_speed_m_s,
        capillary_force,
        travel,
        free_speed,
        cfg,
        phase_prefix="PRE_T1_MANYCONTACT_ACTIVE",
    )

    event_shift = (
        active.event_time_s / feedback_disabled_event_time - 1.0
    )
    contact_time_shift = abs(
        active.event_time_s - decoupled.event_time_s
    ) / max(abs(decoupled.event_time_s), 1.0e-30)
    contact_resistance_shift = abs(
        active.hydrodynamic_resistance_n
        - decoupled.hydrodynamic_resistance_n
    ) / max(
        abs(decoupled.hydrodynamic_resistance_n),
        abs(active.hydrodynamic_resistance_n),
        1.0e-30,
    )

    transaction = _direct_t1.perform_direct_t1_transaction(
        topology_state, base.direct
    )
    after_state = replace(
        transaction.after,
        time_s=topology_state.time_s + active.event_time_s,
    )

    new_pair = tuple(sorted(neighborhood.opposite_regions))
    post_targets = _combined_contact_targets(
        solver,
        new_pair,
        event_relative_speed_m_s=base.post_event_opening_speed_m_s,
        event_opening=True,
        non_event_pair=non_event_pair,
        non_event_relative_speed_m_s=cfg.non_event_relative_speed_m_s,
    )
    # Do not restore the baseline here.  The active production field continues
    # directly across the topology transaction and the non-event contact stays active.
    post_field = solve_manycontact_shared_field(
        solver,
        post_targets,
        phase="POST_T1_MANYCONTACT_ACTIVE",
        settings=cfg,
    )
    authoritative_grid_preserved = id(solver.grid) == grid_identity

    transition = T1GlobalTransitionResult(
        model=TRANSITION_MODEL_ID,
        supported_class=(
            "bounded five-or-more-region many-contact system with one genuine "
            "non-coplanar four-region direct-geometry T1 embedded in one "
            "partitioned immersed Eulerian field while another contact remains active"
        ),
        pre_field=active.production_field,
        post_field=post_field,
        field_event_time_s=active.event_time_s,
        direct_geometry_diagnostic_event_time_s=(
            transaction.forecast.event_time_s
        ),
        initial_gap_m=eligibility.initial_gap_m,
        event_gap_m=eligibility.event_gap_m,
        capillary_driving_force_n=capillary_force,
        field_hydrodynamic_resistance_n=(
            active.hydrodynamic_resistance_n
        ),
        net_field_coupled_driving_force_n=active.net_force_n,
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
    return ManyContactT1GlobalTransitionResult(
        transition=transition,
        trial_field=active.trial_field,
        support_region_ids=support_ids,
        non_event_contact_pair=non_event_pair,
        feedback_disabled_event_time_s=feedback_disabled_event_time,
        feedback_disabled_closing_speed_m_s=free_speed,
        production_field_target_closing_speed_m_s=(
            active.production_target_speed_m_s
        ),
        coupled_closing_speed_m_s=active.coupled_speed_m_s,
        feedback_iterations=cfg.strong.feedback_iterations,
        feedback_relative_residual=active.feedback_relative_residual,
        event_time_shift_fraction=event_shift,
        decoupled_contact_event_time_s=decoupled.event_time_s,
        decoupled_contact_resistance_n=(
            decoupled.hydrodynamic_resistance_n
        ),
        non_event_contact_event_time_shift_fraction=contact_time_shift,
        non_event_contact_resistance_shift_fraction=contact_resistance_shift,
    )
