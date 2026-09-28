"""Bounded four-region T1 transition through one authoritative Eulerian CFD field.

The direct 3D T1 network owns local adjacency/incidence geometry.  Four closed
support fronts, carrying the same stable gas-region IDs, are coupled to one
Eulerian pressure/velocity field.  When regularized immersed supports overlap,
this module does not disable the safety condition and does not launch pairwise
solves.  Instead it replaces the formerly unsupported regime with a bounded
partition-of-unity constraint treatment: every Eulerian cell is forced once,
using the normalized support weights of all incident fronts, and the resulting
reaction is partitioned back to those fronts with the same weights.

The field-derived front traction modifies the resolved 3D capillary drive used
to predict the supported T1 time.  Only after that field-coupled event criterion
is satisfied is the existing conservative direct-geometry transaction invoked
for the actual film/junction surgery.  Its independent time forecast is retained
as a diagnostic only and is not used as the production event time.  The same
Eulerian grid object is then advanced again with the post-T1 adjacency active.

This is intentionally a narrow foundation, not arbitrary-contact multiphase CFD.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any, Mapping, Sequence

from bubblelab.solvers.transient.geometry import FilmFront, Vec3, norm
from bubblelab.solvers.transient.grid import EulerianGasGrid
from bubblelab.solvers.transient.network import t1_hydrodynamics as _direct_t1
from bubblelab.solvers.transient.network.t1_hydrodynamics import (
    DirectT1Settings,
    TransientNetworkState,
)

from . import core as _core
from .core import MultiregionCFDSettings, SurfaceTraction


MODEL_ID = "GLOBAL_3D_FOUR_REGION_T1_PARTITIONED_IMMERSED_CFD"
TRANSITION_MODEL_ID = "GLOBAL_3D_FOUR_REGION_FIELD_COUPLED_T1_TRANSITION"


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a: Vec3, scale: float) -> Vec3:
    return (a[0] * scale, a[1] * scale, a[2] * scale)


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _unit(a: Vec3) -> Vec3:
    length = norm(a)
    if length <= 1.0e-30:
        raise ValueError("T1 global CFD cannot normalize a zero-length direction")
    return _mul(a, 1.0 / length)


def _sum_vectors(values: Sequence[Vec3]) -> Vec3:
    total = (0.0, 0.0, 0.0)
    for value in values:
        total = _add(total, value)
    return total


@dataclass(frozen=True)
class T1GlobalCFDSettings:
    field: MultiregionCFDSettings = MultiregionCFDSettings(
        pseudo_steps=10,
        viscous_cfl=0.08,
        constraint_relaxation=0.82,
        minimum_gap_cells=0.25,
        traction_offset_cells=0.80,
        gradient_step_cells=0.50,
        maximum_sphericity_error=0.12,
        minimum_constraint_cells_per_front=8,
    )
    direct: DirectT1Settings = DirectT1Settings()
    event_mobility_m_per_n_s: float = 2.0e-2
    pre_event_closing_speed_m_s: float = 0.020
    pre_event_drift_speed_m_s: float = 0.015
    post_event_opening_speed_m_s: float = 0.012
    minimum_net_driving_force_n: float = 1.0e-12
    maximum_aggregate_traction_mismatch: float = 0.20

    def validate(self) -> None:
        self.field.validate()
        self.direct.validate()
        if self.event_mobility_m_per_n_s <= 0.0:
            raise ValueError("T1 field-coupled event mobility must be positive")
        if self.pre_event_closing_speed_m_s <= 0.0:
            raise ValueError("T1 pre-event closing speed must be positive")
        if self.post_event_opening_speed_m_s <= 0.0:
            raise ValueError("T1 post-event opening speed must be positive")
        if self.minimum_net_driving_force_n <= 0.0:
            raise ValueError("T1 minimum net driving force must be positive")
        if not 0.0 < self.maximum_aggregate_traction_mismatch <= 0.20:
            raise ValueError("T1 aggregate traction mismatch gate must lie in (0, 0.20]")


@dataclass(frozen=True)
class SharedSupportDiagnostics:
    total_constraint_cells: int
    overlap_cell_count: int
    maximum_overlap_multiplicity: int
    overlap_fraction: float
    maximum_partition_sum_error: float
    maximum_target_spread_m_s: float

    def as_dict(self) -> dict[str, object]:
        return {
            "total_constraint_cells": int(self.total_constraint_cells),
            "overlap_cell_count": int(self.overlap_cell_count),
            "maximum_overlap_multiplicity": int(self.maximum_overlap_multiplicity),
            "overlap_fraction": float(self.overlap_fraction),
            "maximum_partition_sum_error": float(self.maximum_partition_sum_error),
            "maximum_target_spread_m_s": float(self.maximum_target_spread_m_s),
            "treatment": (
                "single-cell partition-of-unity immersed constraint; one blended "
                "Eulerian forcing update and one pressure projection per pseudo-step"
            ),
        }


@dataclass(frozen=True)
class T1SharedFieldResult:
    model: str
    phase: str
    target_velocities_world: tuple[tuple[str, Vec3], ...]
    pseudo_dt_s: float
    pseudo_steps: int
    support: SharedSupportDiagnostics
    constraint_cell_counts: tuple[tuple[str, int], ...]
    region_cell_counts: tuple[tuple[str, int], ...]
    pressure_linf_pa: float
    max_speed_m_s: float
    divergence_linf_s_inv: float
    mass_balance_relative_residual: float
    projection_residual_s_inv: float
    pressure_iterations: int
    tractions: tuple[SurfaceTraction, ...]
    constraint_reaction_forces_n: tuple[tuple[str, Vec3], ...]
    front_constraint_traction_relative_mismatch: tuple[tuple[str, float], ...]
    aggregate_constraint_traction_relative_mismatch: float
    global_force_relative_imbalance: float

    def as_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "phase": self.phase,
            "target_velocities_world_m_s": {
                key: [float(x) for x in value]
                for key, value in self.target_velocities_world
            },
            "grid": {
                "pseudo_dt_s": float(self.pseudo_dt_s),
                "pseudo_steps": int(self.pseudo_steps),
                "constraint_cell_counts": {
                    key: int(value) for key, value in self.constraint_cell_counts
                },
                "region_cell_counts": {
                    key: int(value) for key, value in self.region_cell_counts
                },
            },
            "shared_support": self.support.as_dict(),
            "field": {
                "pressure_linf_pa": float(self.pressure_linf_pa),
                "max_speed_m_s": float(self.max_speed_m_s),
                "divergence_linf_s_inv": float(self.divergence_linf_s_inv),
                "mass_balance_relative_residual": float(self.mass_balance_relative_residual),
                "projection_residual_s_inv": float(self.projection_residual_s_inv),
                "pressure_iterations": int(self.pressure_iterations),
            },
            "traction": {
                "surfaces": [item.as_dict() for item in self.tractions],
                "constraint_reaction_forces_n": {
                    key: [float(x) for x in value]
                    for key, value in self.constraint_reaction_forces_n
                },
                "front_constraint_traction_relative_mismatch": {
                    key: float(value)
                    for key, value in self.front_constraint_traction_relative_mismatch
                },
                "aggregate_constraint_traction_relative_mismatch": float(
                    self.aggregate_constraint_traction_relative_mismatch
                ),
                "global_force_relative_imbalance": float(
                    self.global_force_relative_imbalance
                ),
            },
        }


@dataclass(frozen=True)
class T1GlobalTransitionResult:
    model: str
    supported_class: str
    pre_field: T1SharedFieldResult
    post_field: T1SharedFieldResult
    field_event_time_s: float
    direct_geometry_diagnostic_event_time_s: float
    initial_gap_m: float
    event_gap_m: float
    capillary_driving_force_n: float
    field_hydrodynamic_resistance_n: float
    net_field_coupled_driving_force_n: float
    adjacency_before: tuple[tuple[str, str], ...]
    adjacency_after: tuple[tuple[str, str], ...]
    retired_film_ids: tuple[str, ...]
    created_film_ids: tuple[str, ...]
    retired_junction_ids: tuple[str, ...]
    created_junction_ids: tuple[str, ...]
    preserved_region_ids: tuple[str, ...]
    volume_errors_after: tuple[tuple[str, float], ...]
    authoritative_grid_preserved: bool
    topology_state_after: TransientNetworkState

    def as_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "supported_class": self.supported_class,
            "event": {
                "field_event_time_s": float(self.field_event_time_s),
                "direct_geometry_diagnostic_event_time_s": float(
                    self.direct_geometry_diagnostic_event_time_s
                ),
                "initial_gap_m": float(self.initial_gap_m),
                "event_gap_m": float(self.event_gap_m),
                "capillary_driving_force_n": float(self.capillary_driving_force_n),
                "field_hydrodynamic_resistance_n": float(
                    self.field_hydrodynamic_resistance_n
                ),
                "net_field_coupled_driving_force_n": float(
                    self.net_field_coupled_driving_force_n
                ),
                "time_source": (
                    "resolved 3D capillary drive minus traction from the shared Eulerian field; "
                    "direct standalone forecast retained only as a diagnostic"
                ),
            },
            "topology": {
                "adjacency_before": [list(pair) for pair in self.adjacency_before],
                "adjacency_after": [list(pair) for pair in self.adjacency_after],
                "retired_film_ids": list(self.retired_film_ids),
                "created_film_ids": list(self.created_film_ids),
                "retired_junction_ids": list(self.retired_junction_ids),
                "created_junction_ids": list(self.created_junction_ids),
                "preserved_region_ids": list(self.preserved_region_ids),
                "volume_errors_after": {
                    key: float(value) for key, value in self.volume_errors_after
                },
            },
            "authoritative_grid_preserved": bool(self.authoritative_grid_preserved),
            "pre_field": self.pre_field.as_dict(),
            "post_field": self.post_field.as_dict(),
        }


def _front_map(fronts: Sequence[FilmFront]) -> dict[str, FilmFront]:
    result = {front.bubble_id: front for front in fronts}
    if len(result) != len(fronts):
        raise ValueError("T1 global CFD requires unique stable front/gas IDs")
    return result


def _normalize_targets(
    fronts: Sequence[FilmFront],
    velocities: Mapping[str, Vec3],
) -> dict[str, Vec3]:
    ids = {front.bubble_id for front in fronts}
    if set(velocities) != ids:
        raise ValueError("T1 target velocity map must contain exactly all four gas IDs")
    return {
        key: (float(value[0]), float(value[1]), float(value[2]))
        for key, value in sorted(velocities.items())
    }


def _validate_solver(solver: Any, cfg: T1GlobalCFDSettings) -> tuple[EulerianGasGrid, tuple[FilmFront, ...]]:
    cfg.validate()
    if len(solver.fronts) != 4:
        raise ValueError("T1 global CFD supports exactly four closed support fronts")
    if type(solver.grid) is not EulerianGasGrid:
        raise ValueError("T1 global CFD currently requires the base EulerianGasGrid")
    solver._refresh_regions()
    ordered = tuple(sorted(solver.fronts, key=lambda item: item.bubble_id))
    for front in ordered:
        error = _core._front_sphericity_error(front)
        if error > cfg.field.maximum_sphericity_error:
            raise ValueError(
                f"front {front.bubble_id!r} exceeds T1 support sphericity limit: {error:.6g}"
            )
    return solver.grid, ordered


def _constraint_partition(
    grid: EulerianGasGrid,
    fronts: Sequence[FilmFront],
    targets: Mapping[str, Vec3],
    cfg: T1GlobalCFDSettings,
) -> tuple[
    dict[str, dict[int, tuple[float, Vec3]]],
    dict[int, tuple[float, Vec3, tuple[tuple[str, float], ...]]],
    SharedSupportDiagnostics,
]:
    mappings = {
        front.bubble_id: _core._constraint_map(grid, front, targets[front.bubble_id])
        for front in fronts
    }
    for bubble_id, mapping in mappings.items():
        if len(mapping) < cfg.field.minimum_constraint_cells_per_front:
            raise ValueError(
                f"front {bubble_id!r} couples to only {len(mapping)} Eulerian cells"
            )

    incident: dict[int, list[tuple[str, float, Vec3]]] = {}
    for bubble_id in sorted(mappings):
        for q, (strength, target) in mappings[bubble_id].items():
            incident.setdefault(q, []).append((bubble_id, float(strength), target))

    combined: dict[int, tuple[float, Vec3, tuple[tuple[str, float], ...]]] = {}
    overlap_count = 0
    max_multiplicity = 1
    max_partition_error = 0.0
    max_target_spread = 0.0
    for q, entries in incident.items():
        total = sum(max(strength, 0.0) for _, strength, _ in entries)
        if total <= 0.0:
            continue
        shares = tuple(
            (bubble_id, max(strength, 0.0) / total)
            for bubble_id, strength, _ in sorted(entries)
        )
        max_partition_error = max(
            max_partition_error,
            abs(sum(weight for _, weight in shares) - 1.0),
        )
        by_id = {bubble_id: target for bubble_id, _, target in entries}
        target = (0.0, 0.0, 0.0)
        for bubble_id, weight in shares:
            target = _add(target, _mul(by_id[bubble_id], weight))
        if len(entries) > 1:
            overlap_count += 1
            max_multiplicity = max(max_multiplicity, len(entries))
            values = [item[2] for item in entries]
            for left_index, left in enumerate(values):
                for right in values[left_index + 1 :]:
                    max_target_spread = max(max_target_spread, norm(_sub(left, right)))
        combined[q] = (min(1.0, total), target, shares)

    support = SharedSupportDiagnostics(
        total_constraint_cells=len(combined),
        overlap_cell_count=overlap_count,
        maximum_overlap_multiplicity=max_multiplicity,
        overlap_fraction=overlap_count / max(len(combined), 1),
        maximum_partition_sum_error=max_partition_error,
        maximum_target_spread_m_s=max_target_spread,
    )
    return mappings, combined, support


def _partitioned_control_surface_tractions(
    grid: EulerianGasGrid,
    fronts: Sequence[FilmFront],
    mappings: Mapping[str, Mapping[int, tuple[float, Vec3]]],
) -> tuple[SurfaceTraction, ...]:
    # Interface cells use the exact same normalized immersed-support shares as
    # constraint forcing. Interior-only cells retain their sharp region-label
    # owner. This removes winner-take-all ownership jumps under grid refinement.
    bubble_ids = tuple(sorted(front.bubble_id for front in fronts))
    all_cells: set[int] = set()
    for bubble_id in bubble_ids:
        all_cells.update(mappings[bubble_id])
    all_cells.update(
        q for q, label in enumerate(grid.region_labels) if label in bubble_ids
    )

    viscous_acceleration = tuple(
        grid._variable_viscous_term(field, axis)
        for axis, field in enumerate((grid.u, grid.v, grid.w))
    )
    pressure_mobility_gradient = grid._mobility_gradient(grid.pressure)
    volume = grid.cell_volume
    pressure_forces = {bubble_id: (0.0, 0.0, 0.0) for bubble_id in bubble_ids}
    viscous_forces = {bubble_id: (0.0, 0.0, 0.0) for bubble_id in bubble_ids}

    for q in sorted(all_cells):
        strengths = {
            bubble_id: max(
                0.0,
                float(
                    mappings[bubble_id].get(
                        q, (0.0, (0.0, 0.0, 0.0))
                    )[0]
                ),
            )
            for bubble_id in bubble_ids
        }
        strengths = {
            bubble_id: strength
            for bubble_id, strength in strengths.items()
            if strength > 0.0
        }
        if strengths:
            total_strength = sum(strengths.values())
            shares = tuple(
                (bubble_id, strengths[bubble_id] / total_strength)
                for bubble_id in sorted(strengths)
            )
        else:
            label = grid.region_labels[q]
            shares = ((label, 1.0),) if label in pressure_forces else ()
        if not shares:
            continue

        pressure_cell = tuple(
            -grid.density[q] * pressure_mobility_gradient[axis][q] * volume
            for axis in range(3)
        )
        viscous_cell = tuple(
            grid.density[q] * viscous_acceleration[axis][q] * volume
            for axis in range(3)
        )
        for bubble_id, weight in shares:
            pressure_forces[bubble_id] = _add(
                pressure_forces[bubble_id], _mul(pressure_cell, weight)
            )
            viscous_forces[bubble_id] = _add(
                viscous_forces[bubble_id], _mul(viscous_cell, weight)
            )

    return tuple(
        SurfaceTraction(
            bubble_id=bubble_id,
            pressure_force_n=pressure_forces[bubble_id],
            viscous_force_n=viscous_forces[bubble_id],
            total_force_n=_add(
                pressure_forces[bubble_id], viscous_forces[bubble_id]
            ),
        )
        for bubble_id in bubble_ids
    )


def solve_t1_shared_field(
    solver: Any,
    target_velocities_world: Mapping[str, Vec3],
    *,
    phase: str,
    settings: T1GlobalCFDSettings | None = None,
) -> T1SharedFieldResult:
    """Advance all four immersed fronts on one Eulerian field, including overlap."""
    cfg = settings or T1GlobalCFDSettings()
    grid, fronts = _validate_solver(solver, cfg)
    targets = _normalize_targets(fronts, target_velocities_world)
    mappings, combined, support = _constraint_partition(grid, fronts, targets, cfg)

    max_nu = max(
        (mu / rho for mu, rho in zip(grid.dynamic_viscosity, grid.density) if rho > 0.0),
        default=0.0,
    )
    speed_scale = max((norm(value) for value in targets.values()), default=1.0e-12)
    if max_nu > 0.0:
        pseudo_dt = cfg.field.viscous_cfl * grid.h * grid.h / max_nu
    else:
        pseudo_dt = 0.1 * grid.h / max(speed_scale, 1.0e-6)
    pseudo_dt = max(pseudo_dt, 1.0e-8)

    last_reactions = {front.bubble_id: (0.0, 0.0, 0.0) for front in fronts}
    for _ in range(cfg.field.pseudo_steps):
        before = (list(grid.u), list(grid.v), list(grid.w))
        fields: list[list[float]] = []
        for axis_index, component in enumerate(before):
            viscous = grid._variable_viscous_term(component, axis_index)
            fields.append([
                value + pseudo_dt * derivative
                for value, derivative in zip(component, viscous)
            ])

        reactions = {front.bubble_id: (0.0, 0.0, 0.0) for front in fronts}
        for q in sorted(combined):
            strength, target, shares = combined[q]
            blend = cfg.field.constraint_relaxation * strength
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

        projected = grid.project((fields[0], fields[1], fields[2]), pseudo_dt)
        grid.u, grid.v, grid.w = (
            list(projected[0]), list(projected[1]), list(projected[2])
        )
        last_reactions = reactions

    tractions = _partitioned_control_surface_tractions(grid, fronts, mappings)
    traction_map = {item.bubble_id: item.total_force_n for item in tractions}
    reaction_map = last_reactions
    front_mismatches: list[tuple[str, float]] = []
    force_scale = max(
        sum(norm(value) for value in traction_map.values()) / max(len(traction_map), 1),
        sum(norm(value) for value in reaction_map.values()) / max(len(reaction_map), 1),
        1.0e-30,
    )
    for bubble_id in sorted(traction_map):
        traction = traction_map[bubble_id]
        reaction = reaction_map[bubble_id]
        denominator = max(norm(traction), norm(reaction), 0.05 * force_scale, 1.0e-30)
        front_mismatches.append(
            (bubble_id, norm(_sub(traction, reaction)) / denominator)
        )

    total_traction = _sum_vectors(tuple(traction_map.values()))
    total_reaction = _sum_vectors(tuple(reaction_map.values()))
    aggregate_mismatch = norm(_sub(total_traction, total_reaction)) / max(
        norm(total_traction), norm(total_reaction), force_scale, 1.0e-30
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
        pseudo_steps=cfg.field.pseudo_steps,
        support=support,
        constraint_cell_counts=tuple(
            sorted((bubble_id, len(mapping)) for bubble_id, mapping in mappings.items())
        ),
        region_cell_counts=_core._region_counts(grid),
        pressure_linf_pa=max((abs(value) for value in grid.pressure), default=0.0),
        max_speed_m_s=grid.max_speed(),
        divergence_linf_s_inv=divergence,
        mass_balance_relative_residual=mass_relative,
        projection_residual_s_inv=grid.last_projection_residual,
        pressure_iterations=grid.last_projection_iterations,
        tractions=tractions,
        constraint_reaction_forces_n=tuple(sorted(reaction_map.items())),
        front_constraint_traction_relative_mismatch=tuple(front_mismatches),
        aggregate_constraint_traction_relative_mismatch=aggregate_mismatch,
        global_force_relative_imbalance=global_force_imbalance,
    )


def _pair_targets(
    solver: Any,
    pair: tuple[str, str],
    *,
    relative_speed_m_s: float,
    drift_speed_m_s: float,
    opening: bool,
) -> dict[str, Vec3]:
    fronts = _front_map(solver.fronts)
    if pair[0] not in fronts or pair[1] not in fronts:
        raise ValueError("T1 topology pair is missing from closed CFD support fronts")
    first = fronts[pair[0]].centroid()
    second = fronts[pair[1]].centroid()
    direction = _unit(_sub(second, first))
    sign = -1.0 if opening else 1.0
    targets = {bubble_id: (0.0, 0.0, 0.0) for bubble_id in fronts}
    targets[pair[0]] = _mul(
        direction, drift_speed_m_s + sign * 0.5 * relative_speed_m_s
    )
    targets[pair[1]] = _mul(
        direction, drift_speed_m_s - sign * 0.5 * relative_speed_m_s
    )
    return targets


def _hydrodynamic_resistance_on_pair(
    solver: Any,
    pair: tuple[str, str],
    field: T1SharedFieldResult,
) -> float:
    fronts = _front_map(solver.fronts)
    direction = _unit(_sub(fronts[pair[1]].centroid(), fronts[pair[0]].centroid()))
    traction = {item.bubble_id: item.total_force_n for item in field.tractions}
    generalized = 0.5 * _dot(
        _sub(traction[pair[1]], traction[pair[0]]), direction
    )
    return max(0.0, generalized)


def run_t1_global_cfd_transition(
    solver: Any,
    topology_state: TransientNetworkState,
    settings: T1GlobalCFDSettings | None = None,
) -> T1GlobalTransitionResult:
    """Cross one real four-region T1 event through the authoritative CFD field."""
    cfg = settings or T1GlobalCFDSettings()
    cfg.validate()
    eligibility = _direct_t1.detect_direct_t1_eligibility(topology_state, cfg.direct)
    if not eligibility.eligible or eligibility.neighborhood is None:
        raise ValueError(f"unsupported direct 3D T1 neighborhood: {eligibility.reason}")
    neighborhood = eligibility.neighborhood
    gas_ids = tuple(sorted(region.id for region in topology_state.to_network().regions))
    if set(gas_ids) != {front.bubble_id for front in solver.fronts}:
        raise ValueError("closed CFD support fronts must carry exactly the T1 gas-region IDs")

    grid_identity = id(solver.grid)
    pre_targets = _pair_targets(
        solver,
        neighborhood.old_adjacent_regions,
        relative_speed_m_s=cfg.pre_event_closing_speed_m_s,
        drift_speed_m_s=cfg.pre_event_drift_speed_m_s,
        opening=False,
    )
    pre_field = solve_t1_shared_field(
        solver, pre_targets, phase="PRE_T1", settings=cfg
    )
    capillary_force = _direct_t1._direct_gap_capillary_force(
        topology_state.to_network(), neighborhood
    )
    hydro_resistance = _hydrodynamic_resistance_on_pair(
        solver, neighborhood.old_adjacent_regions, pre_field
    )
    net_force = capillary_force - hydro_resistance
    if net_force <= cfg.minimum_net_driving_force_n:
        raise ValueError(
            "shared-field traction prevents the supported T1 collapse: "
            f"net drive {net_force:.6e} N"
        )
    travel = eligibility.initial_gap_m - eligibility.event_gap_m
    if travel <= 0.0:
        raise ValueError("T1 geometry has no positive pre-event travel distance")
    field_event_time = travel / (cfg.event_mobility_m_per_n_s * net_force)

    transaction = _direct_t1.perform_direct_t1_transaction(topology_state, cfg.direct)
    after_state = replace(
        transaction.after,
        time_s=topology_state.time_s + field_event_time,
    )
    new_pair = tuple(sorted(neighborhood.opposite_regions))
    post_targets = _pair_targets(
        solver,
        new_pair,
        relative_speed_m_s=cfg.post_event_opening_speed_m_s,
        drift_speed_m_s=0.0,
        opening=True,
    )
    post_field = solve_t1_shared_field(
        solver, post_targets, phase="POST_T1", settings=cfg
    )
    authoritative_grid_preserved = id(solver.grid) == grid_identity
    return T1GlobalTransitionResult(
        model=TRANSITION_MODEL_ID,
        supported_class=(
            "isolated four-region genuinely non-coplanar direct-geometry T1 with "
            "four closed support fronts on one partitioned immersed Eulerian field"
        ),
        pre_field=pre_field,
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
