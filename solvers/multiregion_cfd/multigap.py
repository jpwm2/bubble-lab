"""Bounded three-bubble/two-gap global immersed multi-region CFD foundation.

This module extends the accepted two-bubble global Eulerian path without changing
that API.  The supported class is deliberately narrow: three separated,
quasi-spherical fronts arranged as a collinear chain with two simultaneously
resolved pre-contact gaps.  All three immersed constraints are applied to one
Eulerian velocity field before one pressure projection per pseudo-step.  Pressure
and viscous traction are recovered from disjoint closed finite-volume control
volumes for every front and feed an overdamped many-front mobility iteration.

No pairwise CFD solve, pair-force superposition, Taylor/Reynolds production law,
T1 topology change, turbulence, compressibility, thermal or rarefied-gas model is
used here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from bubblelab.solvers.contact_lubrication import GapGeometry, measure_axis_gap_geometry
from bubblelab.solvers.transient.geometry import FilmFront, Vec3, norm
from bubblelab.solvers.transient.grid import EulerianGasGrid

from . import core as _core
from .core import MultiregionCFDSettings, SurfaceTraction


MODEL_ID = "GLOBAL_3D_THREE_BUBBLE_TWO_GAP_IMMERSED_MULTI_REGION_CFD"


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a: Vec3, scale: float) -> Vec3:
    return (a[0] * scale, a[1] * scale, a[2] * scale)


def _geometry_dict(geometry: GapGeometry) -> dict[str, object]:
    return {
        "parent_ids": list(geometry.parent_ids),
        "anchor_vertex_indices": list(geometry.anchor_vertex_indices),
        "normal_a_to_b": [float(x) for x in geometry.normal_a_to_b],
        "gap_m": float(geometry.gap_m),
        "effective_radius_m": float(geometry.effective_radius_m),
        "mesh_resolution_m": float(geometry.mesh_resolution_m),
        "source": geometry.geometry_source,
    }


@dataclass(frozen=True)
class MultigapCFDSettings:
    field: MultiregionCFDSettings = MultiregionCFDSettings()
    feedback_iterations: int = 4
    feedback_relaxation: float = 0.35
    maximum_axis_offset_over_radius: float = 0.08

    def validate(self) -> None:
        self.field.validate()
        if self.feedback_iterations < 1:
            raise ValueError("multigap feedback_iterations must be at least one")
        if not (0.0 < self.feedback_relaxation <= 1.0):
            raise ValueError("multigap feedback_relaxation must lie in (0, 1]")
        if not (0.0 <= self.maximum_axis_offset_over_radius < 0.5):
            raise ValueError("maximum_axis_offset_over_radius must lie in [0, 0.5)")


@dataclass(frozen=True)
class ManyBubbleFieldResult:
    model: str
    gaps: tuple[GapGeometry, GapGeometry]
    target_velocities_world: tuple[tuple[str, Vec3], ...]
    pseudo_dt_s: float
    pseudo_steps: int
    constraint_cell_counts: tuple[tuple[str, int], ...]
    region_cell_counts: tuple[tuple[str, int], ...]
    pressure_linf_pa: float
    max_speed_m_s: float
    divergence_linf_s_inv: float
    mass_balance_relative_residual: float
    projection_residual_s_inv: float
    pressure_iterations: int
    surface_velocity_relative_error: float
    velocity_fixed_point_relative_residual: float
    tractions: tuple[SurfaceTraction, ...]
    constraint_reaction_forces_n: tuple[tuple[str, Vec3], ...]
    front_constraint_traction_relative_mismatch: tuple[tuple[str, float], ...]
    max_constraint_traction_relative_mismatch: float
    global_force_relative_imbalance: float
    gap_pressure_samples: tuple[tuple[tuple[str, str], tuple[tuple[float, float], ...]], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "gaps": [_geometry_dict(gap) for gap in self.gaps],
            "target_velocities_world_m_s": {
                bubble_id: [float(x) for x in velocity]
                for bubble_id, velocity in self.target_velocities_world
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
            "field": {
                "pressure_linf_pa": float(self.pressure_linf_pa),
                "max_speed_m_s": float(self.max_speed_m_s),
                "divergence_linf_s_inv": float(self.divergence_linf_s_inv),
                "mass_balance_relative_residual": float(self.mass_balance_relative_residual),
                "projection_residual_s_inv": float(self.projection_residual_s_inv),
                "pressure_iterations": int(self.pressure_iterations),
                "surface_velocity_relative_error": float(self.surface_velocity_relative_error),
                "velocity_fixed_point_relative_residual": float(
                    self.velocity_fixed_point_relative_residual
                ),
                "gap_pressure_samples": [
                    {
                        "parent_ids": list(parent_ids),
                        "samples": [
                            {"fraction": float(fraction), "pressure_pa": float(value)}
                            for fraction, value in samples
                        ],
                    }
                    for parent_ids, samples in self.gap_pressure_samples
                ],
            },
            "traction": {
                "surfaces": [traction.as_dict() for traction in self.tractions],
                "constraint_reaction_forces_n": {
                    key: [float(x) for x in value]
                    for key, value in self.constraint_reaction_forces_n
                },
                "front_constraint_traction_relative_mismatch": {
                    key: float(value)
                    for key, value in self.front_constraint_traction_relative_mismatch
                },
                "max_constraint_traction_relative_mismatch": float(
                    self.max_constraint_traction_relative_mismatch
                ),
                "global_force_relative_imbalance": float(
                    self.global_force_relative_imbalance
                ),
            },
        }


@dataclass(frozen=True)
class ManyBubbleCoupledResponse:
    model: str
    free_velocities_world: tuple[tuple[str, Vec3], ...]
    coupled_velocities_world: tuple[tuple[str, Vec3], ...]
    outer_resistance_n_s_m: float
    feedback_iterations: int
    feedback_relative_residual: float
    trial_field: ManyBubbleFieldResult
    production_field: ManyBubbleFieldResult

    def as_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "free_velocities_world_m_s": {
                key: [float(x) for x in value] for key, value in self.free_velocities_world
            },
            "coupled_velocities_world_m_s": {
                key: [float(x) for x in value]
                for key, value in self.coupled_velocities_world
            },
            "outer_resistance_n_s_m": float(self.outer_resistance_n_s_m),
            "feedback_iterations": int(self.feedback_iterations),
            "feedback_relative_residual": float(self.feedback_relative_residual),
            "trial_field": self.trial_field.as_dict(),
            "production_field": self.production_field.as_dict(),
        }


def _ordered_chain(fronts: Sequence[FilmFront]) -> tuple[FilmFront, FilmFront, FilmFront]:
    if len(fronts) != 3:
        raise ValueError("multigap global CFD supports exactly three tracked fronts")
    ordered = tuple(sorted(fronts, key=lambda front: (front.centroid()[0], front.bubble_id)))
    return ordered[0], ordered[1], ordered[2]


def _chain_gaps(
    fronts: tuple[FilmFront, FilmFront, FilmFront],
) -> tuple[GapGeometry, GapGeometry]:
    return (
        measure_axis_gap_geometry(fronts[0], fronts[1]),
        measure_axis_gap_geometry(fronts[1], fronts[2]),
    )


def _mean_radius(front: FilmFront) -> float:
    center = front.centroid()
    radii = [norm(_sub(vertex, center)) for vertex in front.vertices]
    return sum(radii) / max(len(radii), 1)


def _validate_supported_chain(
    solver: Any,
    settings: MultigapCFDSettings,
    *,
    refresh_regions: bool,
) -> tuple[EulerianGasGrid, tuple[FilmFront, FilmFront, FilmFront], tuple[GapGeometry, GapGeometry]]:
    settings.validate()
    fronts = _ordered_chain(solver.fronts)
    grid = solver.grid
    if type(grid) is not EulerianGasGrid:
        raise ValueError("multigap global CFD currently requires the base EulerianGasGrid")
    if refresh_regions:
        solver._refresh_regions()

    centers = [front.centroid() for front in fronts]
    reference_radius = max(min(_mean_radius(front) for front in fronts), 1.0e-30)
    transverse_span = max(
        max(abs(center[1]) for center in centers),
        max(abs(center[2]) for center in centers),
    )
    if transverse_span / reference_radius > settings.maximum_axis_offset_over_radius:
        raise ValueError("multigap supported class requires a collinear x-axis bubble chain")

    gaps = _chain_gaps(fronts)
    for geometry in gaps:
        if geometry.gap_m <= 0.0:
            raise ValueError("multigap global CFD requires separated adjacent fronts")
        if geometry.gap_m / grid.h < settings.field.minimum_gap_cells:
            raise ValueError(
                "multigap gap is below the declared globally resolved support limit: "
                f"{geometry.gap_m / grid.h:.6g} cells"
            )
    for front in fronts:
        error = _core._front_sphericity_error(front)
        if error > settings.field.maximum_sphericity_error:
            raise ValueError(
                f"front {front.bubble_id!r} exceeds quasi-spherical support limit: {error:.6g}"
            )
    return grid, fronts, gaps


def _normalize_velocity_map(
    fronts: Sequence[FilmFront],
    velocities: Mapping[str, Vec3],
) -> dict[str, Vec3]:
    expected = {front.bubble_id for front in fronts}
    if set(velocities) != expected:
        raise ValueError(
            "multigap target velocities must contain exactly the supported bubble ids"
        )
    normalized: dict[str, Vec3] = {}
    for bubble_id in sorted(expected):
        raw = velocities[bubble_id]
        value = (float(raw[0]), float(raw[1]), float(raw[2]))
        transverse = max(abs(value[1]), abs(value[2]))
        if transverse > 1.0e-12 * max(1.0, abs(value[0])):
            raise ValueError("multigap supported class currently permits axial velocities only")
        normalized[bubble_id] = value
    return normalized


def _constraint_maps(
    grid: EulerianGasGrid,
    fronts: Sequence[FilmFront],
    targets_world: Mapping[str, Vec3],
    settings: MultigapCFDSettings,
) -> dict[str, dict[int, tuple[float, Vec3]]]:
    mappings = {
        front.bubble_id: _core._constraint_map(
            grid, front, targets_world[front.bubble_id]
        )
        for front in fronts
    }
    occupied: dict[int, str] = {}
    for bubble_id in sorted(mappings):
        mapping = mappings[bubble_id]
        if len(mapping) < settings.field.minimum_constraint_cells_per_front:
            raise ValueError(
                f"front {bubble_id!r} couples to only {len(mapping)} Eulerian cells"
            )
        for q in mapping:
            previous = occupied.get(q)
            if previous is not None:
                raise ValueError(
                    "multigap immersed forcing supports overlap between "
                    f"{previous!r} and {bubble_id!r}; hand off before shared support"
                )
            occupied[q] = bubble_id
    return mappings


def _relax_manyfront_field(
    grid: EulerianGasGrid,
    fronts: tuple[FilmFront, FilmFront, FilmFront],
    targets_world: Mapping[str, Vec3],
    settings: MultigapCFDSettings,
) -> tuple[float, float, tuple[tuple[str, int], ...], tuple[tuple[str, Vec3], ...]]:
    constraints = _constraint_maps(grid, fronts, targets_world, settings)
    max_nu = max(
        (mu / rho for mu, rho in zip(grid.dynamic_viscosity, grid.density) if rho > 0.0),
        default=0.0,
    )
    speed_scale = max(
        (norm(value) for value in targets_world.values()),
        default=1.0e-12,
    )
    if max_nu > 0.0:
        pseudo_dt = settings.field.viscous_cfl * grid.h * grid.h / max_nu
    else:
        pseudo_dt = 0.1 * grid.h / max(speed_scale, 1.0e-6)
    pseudo_dt = max(pseudo_dt, 1.0e-8)

    fixed_point_residual = 0.0
    last_reactions = {front.bubble_id: (0.0, 0.0, 0.0) for front in fronts}
    for _ in range(settings.field.pseudo_steps):
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

        reactions: dict[str, Vec3] = {}
        for front in fronts:
            bubble_id = front.bubble_id
            reaction_fluid = (0.0, 0.0, 0.0)
            for q, (strength, target) in constraints[bubble_id].items():
                blend = settings.field.constraint_relaxation * strength
                old = (fields[0][q], fields[1][q], fields[2][q])
                new = (
                    old[0] + blend * (target[0] - old[0]),
                    old[1] + blend * (target[1] - old[1]),
                    old[2] + blend * (target[2] - old[2]),
                )
                fields[0][q], fields[1][q], fields[2][q] = new
                scale = grid.density[q] * grid.cell_volume / pseudo_dt
                reaction_fluid = _add(
                    reaction_fluid,
                    (
                        scale * (new[0] - old[0]),
                        scale * (new[1] - old[1]),
                        scale * (new[2] - old[2]),
                    ),
                )
            reactions[bubble_id] = _mul(reaction_fluid, -1.0)

        projected = grid.project((fields[0], fields[1], fields[2]), pseudo_dt)
        grid.u, grid.v, grid.w = (
            list(projected[0]),
            list(projected[1]),
            list(projected[2]),
        )
        fixed_point_residual = max(
            (
                abs(grid.u[q] - before[0][q])
                + abs(grid.v[q] - before[1][q])
                + abs(grid.w[q] - before[2][q])
            )
            / max(speed_scale, 1.0e-12)
            for q in range(len(grid.u))
        )
        last_reactions = reactions

    counts = tuple(
        sorted((bubble_id, len(mapping)) for bubble_id, mapping in constraints.items())
    )
    return (
        pseudo_dt,
        fixed_point_residual,
        counts,
        tuple(sorted(last_reactions.items())),
    )


def _control_volume_cells(grid: EulerianGasGrid, front: FilmFront) -> set[int]:
    support = set(_core._constraint_map(grid, front, (0.0, 0.0, 0.0)))
    interior = {
        q for q, label in enumerate(grid.region_labels) if label == front.bubble_id
    }
    return support | interior


def _discrete_control_surface_tractions(
    grid: EulerianGasGrid,
    fronts: Sequence[FilmFront],
) -> tuple[SurfaceTraction, ...]:
    masks = {front.bubble_id: _control_volume_cells(grid, front) for front in fronts}
    ids = sorted(masks)
    for index, first in enumerate(ids):
        for second in ids[index + 1 :]:
            overlap = masks[first] & masks[second]
            if overlap:
                raise ValueError(
                    "multigap closed traction control volumes overlap between "
                    f"{first!r} and {second!r} in {len(overlap)} cells"
                )

    viscous_acceleration = tuple(
        grid._variable_viscous_term(field, axis)
        for axis, field in enumerate((grid.u, grid.v, grid.w))
    )
    pressure_mobility_gradient = grid._mobility_gradient(grid.pressure)
    volume = grid.cell_volume
    result: list[SurfaceTraction] = []
    for front in fronts:
        mask = masks[front.bubble_id]
        pressure_force = tuple(
            sum(
                -grid.density[q] * pressure_mobility_gradient[axis][q] * volume
                for q in mask
            )
            for axis in range(3)
        )
        viscous_force = tuple(
            sum(
                grid.density[q] * viscous_acceleration[axis][q] * volume
                for q in mask
            )
            for axis in range(3)
        )
        result.append(
            SurfaceTraction(
                bubble_id=front.bubble_id,
                pressure_force_n=pressure_force,
                viscous_force_n=viscous_force,
                total_force_n=_add(pressure_force, viscous_force),
            )
        )
    return tuple(result)


def _gap_samples(
    grid: EulerianGasGrid,
    fronts: tuple[FilmFront, FilmFront, FilmFront],
    gaps: tuple[GapGeometry, GapGeometry],
) -> tuple[tuple[tuple[str, str], tuple[tuple[float, float], ...]], ...]:
    return (
        (
            gaps[0].parent_ids,
            _core._centerline_pressure(grid, (fronts[0], fronts[1]), gaps[0]),
        ),
        (
            gaps[1].parent_ids,
            _core._centerline_pressure(grid, (fronts[1], fronts[2]), gaps[1]),
        ),
    )


def _solve_current_chain(
    grid: EulerianGasGrid,
    fronts: tuple[FilmFront, FilmFront, FilmFront],
    gaps: tuple[GapGeometry, GapGeometry],
    targets_world: Mapping[str, Vec3],
    settings: MultigapCFDSettings,
) -> ManyBubbleFieldResult:
    pseudo_dt, fixed_point, counts, reactions = _relax_manyfront_field(
        grid, fronts, targets_world, settings
    )
    tractions = _discrete_control_surface_tractions(grid, fronts)
    reaction_map = dict(reactions)
    traction_map = {traction.bubble_id: traction.total_force_n for traction in tractions}
    force_scale = max(
        sum(norm(value) for value in traction_map.values()) / len(tractions),
        sum(norm(value) for value in reaction_map.values()) / len(tractions),
        1.0e-30,
    )
    mismatches: list[tuple[str, float]] = []
    for bubble_id in sorted(traction_map):
        traction = traction_map[bubble_id]
        reaction = reaction_map[bubble_id]
        denominator = max(norm(traction), norm(reaction), 0.05 * force_scale, 1.0e-30)
        mismatches.append(
            (bubble_id, norm(_sub(traction, reaction)) / denominator)
        )
    total_force = (0.0, 0.0, 0.0)
    for value in traction_map.values():
        total_force = _add(total_force, value)
    global_force_imbalance = norm(total_force) / max(
        sum(norm(value) for value in traction_map.values()), 1.0e-30
    )
    speed_scale = max(
        (norm(value) for value in targets_world.values()),
        default=1.0e-12,
    )
    div = grid.divergence_linf()
    mass_relative = div * grid.h / max(speed_scale, 1.0e-12)
    return ManyBubbleFieldResult(
        model=MODEL_ID,
        gaps=gaps,
        target_velocities_world=tuple(sorted(targets_world.items())),
        pseudo_dt_s=float(pseudo_dt),
        pseudo_steps=settings.field.pseudo_steps,
        constraint_cell_counts=counts,
        region_cell_counts=_core._region_counts(grid),
        pressure_linf_pa=max((abs(value) for value in grid.pressure), default=0.0),
        max_speed_m_s=grid.max_speed(),
        divergence_linf_s_inv=div,
        mass_balance_relative_residual=mass_relative,
        projection_residual_s_inv=grid.last_projection_residual,
        pressure_iterations=grid.last_projection_iterations,
        surface_velocity_relative_error=_core._max_surface_velocity_error(
            grid, targets_world, fronts, max(speed_scale, 1.0e-12)
        ),
        velocity_fixed_point_relative_residual=fixed_point,
        tractions=tractions,
        constraint_reaction_forces_n=reactions,
        front_constraint_traction_relative_mismatch=tuple(mismatches),
        max_constraint_traction_relative_mismatch=max(
            (value for _, value in mismatches), default=0.0
        ),
        global_force_relative_imbalance=global_force_imbalance,
        gap_pressure_samples=_gap_samples(grid, fronts, gaps),
    )


def solve_multigap_precontact_field(
    solver: Any,
    target_velocities_world: Mapping[str, Vec3],
    settings: MultigapCFDSettings | None = None,
) -> ManyBubbleFieldResult:
    """Solve all three front constraints in one authoritative Eulerian field."""
    cfg = settings or MultigapCFDSettings()
    grid, fronts, gaps = _validate_supported_chain(solver, cfg, refresh_regions=True)
    targets = _normalize_velocity_map(fronts, target_velocities_world)
    return _solve_current_chain(grid, fronts, gaps, targets, cfg)


def coupled_multigap_response(
    solver: Any,
    free_velocities_world: Mapping[str, Vec3],
    outer_resistance_n_s_m: float,
    settings: MultigapCFDSettings | None = None,
) -> ManyBubbleCoupledResponse:
    """Solve the many-front overdamped mobility balance using global field traction.

    The external mobility model is zeta*(v-v_free)=F_hydro(v).  Each Picard
    evaluation solves all fronts simultaneously on the same Eulerian grid; no
    pairwise resistance curve is evaluated or superposed.
    """
    cfg = settings or MultigapCFDSettings()
    if outer_resistance_n_s_m <= 0.0:
        raise ValueError("outer_resistance_n_s_m must be positive")
    grid, fronts, gaps = _validate_supported_chain(solver, cfg, refresh_regions=True)
    free = _normalize_velocity_map(fronts, free_velocities_world)
    baseline = _core._snapshot(grid)

    _core._restore(grid, baseline)
    trial = _solve_current_chain(grid, fronts, gaps, free, cfg)
    current = dict(free)
    residual = 0.0
    last_field = trial
    speed_scale = max((abs(value[0]) for value in free.values()), default=1.0e-12)
    for iteration in range(cfg.feedback_iterations):
        if iteration > 0:
            _core._restore(grid, baseline)
            last_field = _solve_current_chain(grid, fronts, gaps, current, cfg)
        traction_map = {
            traction.bubble_id: traction.total_force_n
            for traction in last_field.tractions
        }
        updated: dict[str, Vec3] = {}
        residual = 0.0
        for bubble_id in sorted(current):
            proposal_x = free[bubble_id][0] + traction_map[bubble_id][0] / outer_resistance_n_s_m
            next_x = (
                (1.0 - cfg.feedback_relaxation) * current[bubble_id][0]
                + cfg.feedback_relaxation * proposal_x
            )
            updated[bubble_id] = (next_x, 0.0, 0.0)
            residual = max(
                residual,
                abs(next_x - current[bubble_id][0]) / max(speed_scale, 1.0e-12),
            )
        current = updated

    _core._restore(grid, baseline)
    production = _solve_current_chain(grid, fronts, gaps, current, cfg)
    return ManyBubbleCoupledResponse(
        model="GLOBAL_3D_THREE_BUBBLE_TWO_GAP_FIELD_COUPLED_MOBILITY",
        free_velocities_world=tuple(sorted(free.items())),
        coupled_velocities_world=tuple(sorted(current.items())),
        outer_resistance_n_s_m=float(outer_resistance_n_s_m),
        feedback_iterations=cfg.feedback_iterations,
        feedback_relative_residual=float(residual),
        trial_field=trial,
        production_field=production,
    )
