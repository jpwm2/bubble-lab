"""Global 3D two-bubble pre-contact CFD coupling on the authoritative Eulerian grid.

This module is deliberately narrow.  It supports one separated pair of closed,
quasi-spherical tracked fronts.  Their triangulated surface samples impose a
regularized direct-forcing no-slip constraint on the same EulerianGasGrid used by
TransientSoapFilmSolver.  Viscous relaxation and the grid's variable-density
pressure projection produce the velocity/pressure field.  Production feedback is
computed only from numerical pressure plus viscous traction integrated over the
tracked surfaces; no Taylor/Reynolds force law appears in this path.

The implementation is a foundation, not a claim of arbitrary multi-gap/T1,
compressible, turbulent, thermal, rarefied, or general full-domain multiphase CFD.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from bubblelab.solvers.contact_lubrication import GapGeometry, measure_axis_gap_geometry
from bubblelab.solvers.transient.geometry import FilmFront, Vec3, cross, dot, norm, sub
from bubblelab.solvers.transient.grid import EulerianGasGrid


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a: Vec3, s: float) -> Vec3:
    return (a[0] * s, a[1] * s, a[2] * s)


def _neg(a: Vec3) -> Vec3:
    return (-a[0], -a[1], -a[2])


@dataclass(frozen=True)
class MultiregionCFDSettings:
    """Numerical limits for the supported global two-bubble immersed solve."""

    pseudo_steps: int = 5
    viscous_cfl: float = 0.08
    constraint_relaxation: float = 0.85
    minimum_gap_cells: float = 1.25
    traction_offset_cells: float = 0.80
    gradient_step_cells: float = 0.50
    maximum_sphericity_error: float = 0.12
    minimum_constraint_cells_per_front: int = 8

    def validate(self) -> None:
        if self.pseudo_steps < 2:
            raise ValueError("global CFD requires at least two pseudo-time relaxation steps")
        if not (0.0 < self.viscous_cfl <= 0.15):
            raise ValueError("viscous_cfl must lie in (0, 0.15]")
        if not (0.0 < self.constraint_relaxation <= 1.0):
            raise ValueError("constraint_relaxation must lie in (0, 1]")
        if self.minimum_gap_cells <= 0.0:
            raise ValueError("minimum_gap_cells must be positive")
        if self.traction_offset_cells <= 0.0:
            raise ValueError("traction_offset_cells must be positive")
        if self.gradient_step_cells <= 0.0:
            raise ValueError("gradient_step_cells must be positive")
        if not (0.0 < self.maximum_sphericity_error < 1.0):
            raise ValueError("maximum_sphericity_error must lie in (0, 1)")
        if self.minimum_constraint_cells_per_front < 4:
            raise ValueError("minimum_constraint_cells_per_front must be at least four")


@dataclass(frozen=True)
class SurfaceTraction:
    bubble_id: str
    pressure_force_n: Vec3
    viscous_force_n: Vec3
    total_force_n: Vec3

    def as_dict(self) -> dict[str, object]:
        return {
            "bubble_id": self.bubble_id,
            "pressure_force_n": [float(x) for x in self.pressure_force_n],
            "viscous_force_n": [float(x) for x in self.viscous_force_n],
            "total_force_n": [float(x) for x in self.total_force_n],
        }


@dataclass(frozen=True)
class GlobalFieldResult:
    """One resolved field solve at a prescribed pair closing speed."""

    model: str
    geometry: GapGeometry
    closing_speed_m_s: float
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
    tractions: tuple[SurfaceTraction, SurfaceTraction]
    resisting_force_n: float
    pressure_resisting_force_n: float
    viscous_resisting_force_n: float
    pair_force_relative_imbalance: float
    constraint_traction_relative_mismatch: float
    constraint_reaction_forces_n: tuple[tuple[str, Vec3], ...]
    centerline_pressure_samples: tuple[tuple[float, float], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "geometry": {
                "parent_ids": list(self.geometry.parent_ids),
                "anchor_vertex_indices": list(self.geometry.anchor_vertex_indices),
                "normal_a_to_b": [float(x) for x in self.geometry.normal_a_to_b],
                "gap_m": float(self.geometry.gap_m),
                "effective_radius_m": float(self.geometry.effective_radius_m),
                "mesh_resolution_m": float(self.geometry.mesh_resolution_m),
                "source": self.geometry.geometry_source,
            },
            "closing_speed_m_s": float(self.closing_speed_m_s),
            "grid": {
                "pseudo_dt_s": float(self.pseudo_dt_s),
                "pseudo_steps": int(self.pseudo_steps),
                "constraint_cell_counts": {key: int(value) for key, value in self.constraint_cell_counts},
                "region_cell_counts": {key: int(value) for key, value in self.region_cell_counts},
            },
            "field": {
                "pressure_linf_pa": float(self.pressure_linf_pa),
                "max_speed_m_s": float(self.max_speed_m_s),
                "divergence_linf_s_inv": float(self.divergence_linf_s_inv),
                "mass_balance_relative_residual": float(self.mass_balance_relative_residual),
                "projection_residual_s_inv": float(self.projection_residual_s_inv),
                "pressure_iterations": int(self.pressure_iterations),
                "surface_velocity_relative_error": float(self.surface_velocity_relative_error),
                "velocity_fixed_point_relative_residual": float(self.velocity_fixed_point_relative_residual),
                "centerline_pressure_samples": [
                    {"fraction": float(fraction), "pressure_pa": float(pressure)}
                    for fraction, pressure in self.centerline_pressure_samples
                ],
            },
            "traction": {
                "surfaces": [traction.as_dict() for traction in self.tractions],
                "resisting_force_n": float(self.resisting_force_n),
                "pressure_resisting_force_n": float(self.pressure_resisting_force_n),
                "viscous_resisting_force_n": float(self.viscous_resisting_force_n),
                "pair_force_relative_imbalance": float(self.pair_force_relative_imbalance),
                "constraint_traction_relative_mismatch": float(self.constraint_traction_relative_mismatch),
                "constraint_reaction_forces_n": {
                    key: [float(x) for x in value] for key, value in self.constraint_reaction_forces_n
                },
            },
        }


@dataclass(frozen=True)
class GlobalCoupledResponse:
    """Overdamped pair response whose added resistance is field-derived."""

    free_closing_speed_m_s: float
    coupled_closing_speed_m_s: float
    correction_speed_m_s: float
    outer_resistance_n_s_m: float
    resolved_cfd_resistance_n_s_m: float
    trial_field: GlobalFieldResult
    production_field: GlobalFieldResult
    model: str = "GLOBAL_3D_TWO_BUBBLE_IMMERSED_MULTI_REGION_CFD"

    def as_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "free_closing_speed_m_s": float(self.free_closing_speed_m_s),
            "coupled_closing_speed_m_s": float(self.coupled_closing_speed_m_s),
            "correction_speed_m_s": float(self.correction_speed_m_s),
            "outer_resistance_n_s_m": float(self.outer_resistance_n_s_m),
            "resolved_cfd_resistance_n_s_m": float(self.resolved_cfd_resistance_n_s_m),
            "trial_field": self.trial_field.as_dict(),
            "production_field": self.production_field.as_dict(),
        }


@dataclass
class _GridSnapshot:
    u: list[float]
    v: list[float]
    w: list[float]
    pressure: list[float]
    last_projection_iterations: int
    last_projection_residual: float


def _snapshot(grid: EulerianGasGrid) -> _GridSnapshot:
    return _GridSnapshot(
        list(grid.u), list(grid.v), list(grid.w), list(grid.pressure),
        int(grid.last_projection_iterations), float(grid.last_projection_residual),
    )


def _restore(grid: EulerianGasGrid, snapshot: _GridSnapshot) -> None:
    grid.u = list(snapshot.u)
    grid.v = list(snapshot.v)
    grid.w = list(snapshot.w)
    grid.pressure = list(snapshot.pressure)
    grid.last_projection_iterations = snapshot.last_projection_iterations
    grid.last_projection_residual = snapshot.last_projection_residual


def _front_sphericity_error(front: FilmFront) -> float:
    center = front.centroid()
    radii = [norm(sub(vertex, center)) for vertex in front.vertices]
    mean_radius = sum(radii) / len(radii)
    if mean_radius <= 0.0:
        return float("inf")
    return max(abs(radius - mean_radius) for radius in radii) / mean_radius


def _ordered_fronts(fronts: Sequence[FilmFront], geometry: GapGeometry) -> tuple[FilmFront, FilmFront]:
    by_id = {front.bubble_id: front for front in fronts}
    return by_id[geometry.parent_ids[0]], by_id[geometry.parent_ids[1]]


def _validate_supported_class(
    solver: Any,
    settings: MultiregionCFDSettings,
    *,
    refresh_regions: bool,
) -> tuple[EulerianGasGrid, tuple[FilmFront, FilmFront], GapGeometry]:
    settings.validate()
    if len(solver.fronts) != 2:
        raise ValueError("global multi-region CFD currently supports exactly two fronts")
    grid = solver.grid
    if type(grid) is not EulerianGasGrid:
        raise ValueError("global multi-region CFD foundation currently requires the base EulerianGasGrid")
    if refresh_regions:
        solver._refresh_regions()
    geometry = measure_axis_gap_geometry(solver.fronts[0], solver.fronts[1])
    if geometry.gap_m <= 0.0:
        raise ValueError("global multi-region CFD requires separated fronts")
    if geometry.gap_m / grid.h < settings.minimum_gap_cells:
        raise ValueError(
            "gap is below the declared globally resolved support limit: "
            f"{geometry.gap_m / grid.h:.6g} cells"
        )
    ordered = _ordered_fronts(solver.fronts, geometry)
    for front in ordered:
        error = _front_sphericity_error(front)
        if error > settings.maximum_sphericity_error:
            raise ValueError(
                f"front {front.bubble_id!r} exceeds quasi-spherical support limit: {error:.6g}"
            )
    return grid, ordered, geometry


def _surface_samples(front: FilmFront) -> Iterable[Vec3]:
    for vertex in front.vertices:
        yield vertex
    for i, j, k in front.faces:
        a, b, c = front.vertices[i], front.vertices[j], front.vertices[k]
        yield (
            (a[0] + b[0] + c[0]) / 3.0,
            (a[1] + b[1] + c[1]) / 3.0,
            (a[2] + b[2] + c[2]) / 3.0,
        )


def _constraint_map(
    grid: EulerianGasGrid,
    front: FilmFront,
    target_world_velocity: Vec3,
) -> dict[int, tuple[float, Vec3]]:
    bg = grid.config.background_velocity_m_s
    target = (
        target_world_velocity[0] - bg[0],
        target_world_velocity[1] - bg[1],
        target_world_velocity[2] - bg[2],
    )
    weights: dict[int, float] = {}
    accum: dict[int, list[float]] = {}
    for point in _surface_samples(front):
        for q, weight in grid._weights(point):
            weights[q] = weights.get(q, 0.0) + weight
            dest = accum.setdefault(q, [0.0, 0.0, 0.0])
            dest[0] += weight * target[0]
            dest[1] += weight * target[1]
            dest[2] += weight * target[2]
    result: dict[int, tuple[float, Vec3]] = {}
    for q, total in weights.items():
        if total <= 0.0:
            continue
        value = accum[q]
        result[q] = (
            min(1.0, total),
            (value[0] / total, value[1] / total, value[2] / total),
        )
    return result


def _sample_scalar(grid: EulerianGasGrid, field: Sequence[float], point: Vec3) -> float:
    return sum(weight * field[q] for q, weight in grid._weights(point))


def _velocity_gradient(
    grid: EulerianGasGrid,
    point: Vec3,
    step_m: float,
) -> tuple[tuple[float, float, float], ...]:
    columns: list[Vec3] = []
    for axis in range(3):
        delta = [0.0, 0.0, 0.0]
        delta[axis] = step_m
        plus = grid.sample_dynamic_velocity(
            (point[0] + delta[0], point[1] + delta[1], point[2] + delta[2])
        )
        minus = grid.sample_dynamic_velocity(
            (point[0] - delta[0], point[1] - delta[1], point[2] - delta[2])
        )
        inv = 0.5 / step_m
        columns.append(
            (
                (plus[0] - minus[0]) * inv,
                (plus[1] - minus[1]) * inv,
                (plus[2] - minus[2]) * inv,
            )
        )
    return (
        (columns[0][0], columns[1][0], columns[2][0]),
        (columns[0][1], columns[1][1], columns[2][1]),
        (columns[0][2], columns[1][2], columns[2][2]),
    )


def _surface_traction(
    grid: EulerianGasGrid,
    front: FilmFront,
    settings: MultiregionCFDSettings,
) -> SurfaceTraction:
    pressure_force = (0.0, 0.0, 0.0)
    viscous_force = (0.0, 0.0, 0.0)
    offset = settings.traction_offset_cells * grid.h
    gradient_step = settings.gradient_step_cells * grid.h
    for i, j, k in front.faces:
        a, b, c = front.vertices[i], front.vertices[j], front.vertices[k]
        raw = cross(sub(b, a), sub(c, a))
        raw_norm = norm(raw)
        if raw_norm <= 0.0:
            continue
        normal = _mul(raw, 1.0 / raw_norm)
        area = 0.5 * raw_norm
        center = (
            (a[0] + b[0] + c[0]) / 3.0,
            (a[1] + b[1] + c[1]) / 3.0,
            (a[2] + b[2] + c[2]) / 3.0,
        )
        sample = _add(center, _mul(normal, offset))
        pressure = _sample_scalar(grid, grid.pressure, sample)
        viscosity = _sample_scalar(grid, grid.dynamic_viscosity, sample)
        grad = _velocity_gradient(grid, sample, gradient_step)
        pressure_traction = _mul(normal, -pressure)
        viscous_traction = [0.0, 0.0, 0.0]
        for row in range(3):
            value = 0.0
            for col in range(3):
                value += viscosity * (grad[row][col] + grad[col][row]) * normal[col]
            viscous_traction[row] = value
        pressure_force = _add(pressure_force, _mul(pressure_traction, area))
        viscous_force = _add(
            viscous_force,
            (
                viscous_traction[0] * area,
                viscous_traction[1] * area,
                viscous_traction[2] * area,
            ),
        )
    return SurfaceTraction(
        bubble_id=front.bubble_id,
        pressure_force_n=pressure_force,
        viscous_force_n=viscous_force,
        total_force_n=_add(pressure_force, viscous_force),
    )


def _axis_resistance(first: Vec3, second: Vec3, axis_a_to_b: Vec3) -> float:
    return 0.5 * max(0.0, -dot(first, axis_a_to_b) + dot(second, axis_a_to_b))


def _region_counts(grid: EulerianGasGrid) -> tuple[tuple[str, int], ...]:
    counts: dict[str, int] = {}
    for label in grid.region_labels:
        counts[label] = counts.get(label, 0) + 1
    return tuple(sorted(counts.items()))


def _centerline_pressure(
    grid: EulerianGasGrid,
    fronts: tuple[FilmFront, FilmFront],
    geometry: GapGeometry,
    count: int = 9,
) -> tuple[tuple[float, float], ...]:
    a, b = fronts
    pa = a.vertices[geometry.anchor_vertex_indices[0]]
    pb = b.vertices[geometry.anchor_vertex_indices[1]]
    samples: list[tuple[float, float]] = []
    for index in range(count):
        fraction = index / (count - 1)
        point = (
            pa[0] + fraction * (pb[0] - pa[0]),
            pa[1] + fraction * (pb[1] - pa[1]),
            pa[2] + fraction * (pb[2] - pa[2]),
        )
        samples.append((fraction, _sample_scalar(grid, grid.pressure, point)))
    return tuple(samples)


def _max_surface_velocity_error(
    grid: EulerianGasGrid,
    targets_world: Mapping[str, Vec3],
    fronts: Sequence[FilmFront],
    speed_scale: float,
) -> float:
    by_id = {front.bubble_id: front for front in fronts}
    maximum = 0.0
    for bubble_id, target in targets_world.items():
        front = by_id[bubble_id]
        for point in _surface_samples(front):
            sampled = grid.sample_velocity(point)
            error = norm((sampled[0] - target[0], sampled[1] - target[1], sampled[2] - target[2]))
            maximum = max(maximum, error)
    return maximum / max(speed_scale, 1.0e-12)


def _relax_global_field(
    grid: EulerianGasGrid,
    fronts: tuple[FilmFront, FilmFront],
    geometry: GapGeometry,
    closing_speed_m_s: float,
    settings: MultiregionCFDSettings,
) -> tuple[float, float, tuple[tuple[str, int], ...], tuple[tuple[str, Vec3], ...]]:
    axis = geometry.normal_a_to_b
    targets_world = {
        fronts[0].bubble_id: _mul(axis, 0.5 * closing_speed_m_s),
        fronts[1].bubble_id: _mul(axis, -0.5 * closing_speed_m_s),
    }
    constraints = {
        front.bubble_id: _constraint_map(grid, front, targets_world[front.bubble_id])
        for front in fronts
    }
    for bubble_id, mapping in constraints.items():
        if len(mapping) < settings.minimum_constraint_cells_per_front:
            raise ValueError(f"front {bubble_id!r} couples to only {len(mapping)} Eulerian cells")

    max_nu = max(
        (mu / rho for mu, rho in zip(grid.dynamic_viscosity, grid.density) if rho > 0.0),
        default=0.0,
    )
    if max_nu > 0.0:
        pseudo_dt = settings.viscous_cfl * grid.h * grid.h / max_nu
    else:
        pseudo_dt = 0.1 * grid.h / max(closing_speed_m_s, 1.0e-6)
    pseudo_dt = max(pseudo_dt, 1.0e-8)

    fixed_point_residual = 0.0
    last_reactions = {
        fronts[0].bubble_id: (0.0, 0.0, 0.0),
        fronts[1].bubble_id: (0.0, 0.0, 0.0),
    }
    for _ in range(settings.pseudo_steps):
        before = (list(grid.u), list(grid.v), list(grid.w))
        fields: list[list[float]] = []
        for axis_index, component in enumerate(before):
            viscous = grid._variable_viscous_term(component, axis_index)
            fields.append([value + pseudo_dt * derivative for value, derivative in zip(component, viscous)])

        reactions: dict[str, Vec3] = {}
        for front in fronts:
            bubble_id = front.bubble_id
            reaction_fluid = (0.0, 0.0, 0.0)
            for q, (strength, target) in constraints[bubble_id].items():
                blend = settings.constraint_relaxation * strength
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
            reactions[bubble_id] = _neg(reaction_fluid)

        projected = grid.project((fields[0], fields[1], fields[2]), pseudo_dt)
        grid.u, grid.v, grid.w = (list(projected[0]), list(projected[1]), list(projected[2]))
        scale = max(closing_speed_m_s, 1.0e-12)
        fixed_point_residual = max(
            (
                abs(grid.u[q] - before[0][q])
                + abs(grid.v[q] - before[1][q])
                + abs(grid.w[q] - before[2][q])
            ) / scale
            for q in range(len(grid.u))
        )
        last_reactions = reactions

    counts = tuple(sorted((bubble_id, len(mapping)) for bubble_id, mapping in constraints.items()))
    return pseudo_dt, fixed_point_residual, counts, tuple(sorted(last_reactions.items()))


def _solve_current_geometry(
    grid: EulerianGasGrid,
    fronts: tuple[FilmFront, FilmFront],
    geometry: GapGeometry,
    closing_speed_m_s: float,
    settings: MultiregionCFDSettings,
) -> GlobalFieldResult:
    if closing_speed_m_s < 0.0:
        raise ValueError("closing speed must be non-negative")
    pseudo_dt, fixed_point, constraint_counts, reactions = _relax_global_field(
        grid, fronts, geometry, closing_speed_m_s, settings
    )
    tractions = (_surface_traction(grid, fronts[0], settings), _surface_traction(grid, fronts[1], settings))
    axis = geometry.normal_a_to_b
    resisting = _axis_resistance(tractions[0].total_force_n, tractions[1].total_force_n, axis)
    pressure_resisting = _axis_resistance(
        tractions[0].pressure_force_n, tractions[1].pressure_force_n, axis
    )
    viscous_resisting = 0.5 * (
        -dot(tractions[0].viscous_force_n, axis) + dot(tractions[1].viscous_force_n, axis)
    )
    pair_sum = _add(tractions[0].total_force_n, tractions[1].total_force_n)
    pair_imbalance = norm(pair_sum) / max(
        norm(tractions[0].total_force_n) + norm(tractions[1].total_force_n), 1.0e-30
    )
    reaction_map = dict(reactions)
    reaction_resisting = _axis_resistance(
        reaction_map[fronts[0].bubble_id], reaction_map[fronts[1].bubble_id], axis
    )
    mismatch = abs(reaction_resisting - resisting) / max(reaction_resisting, resisting, 1.0e-30)
    div = grid.divergence_linf()
    mass_relative = div * grid.h / max(closing_speed_m_s, 1.0e-12)
    targets_world = {
        fronts[0].bubble_id: _mul(axis, 0.5 * closing_speed_m_s),
        fronts[1].bubble_id: _mul(axis, -0.5 * closing_speed_m_s),
    }
    return GlobalFieldResult(
        model="GLOBAL_3D_TWO_BUBBLE_IMMERSED_MULTI_REGION_CFD",
        geometry=geometry,
        closing_speed_m_s=float(closing_speed_m_s),
        pseudo_dt_s=float(pseudo_dt),
        pseudo_steps=settings.pseudo_steps,
        constraint_cell_counts=constraint_counts,
        region_cell_counts=_region_counts(grid),
        pressure_linf_pa=max((abs(value) for value in grid.pressure), default=0.0),
        max_speed_m_s=grid.max_speed(),
        divergence_linf_s_inv=div,
        mass_balance_relative_residual=mass_relative,
        projection_residual_s_inv=grid.last_projection_residual,
        pressure_iterations=grid.last_projection_iterations,
        surface_velocity_relative_error=_max_surface_velocity_error(
            grid, targets_world, fronts, max(closing_speed_m_s, 1.0e-12)
        ),
        velocity_fixed_point_relative_residual=fixed_point,
        tractions=tractions,
        resisting_force_n=resisting,
        pressure_resisting_force_n=pressure_resisting,
        viscous_resisting_force_n=viscous_resisting,
        pair_force_relative_imbalance=pair_imbalance,
        constraint_traction_relative_mismatch=mismatch,
        constraint_reaction_forces_n=reactions,
        centerline_pressure_samples=_centerline_pressure(grid, fronts, geometry),
    )


def solve_global_precontact_field(
    solver: Any,
    closing_speed_m_s: float,
    settings: MultiregionCFDSettings | None = None,
) -> GlobalFieldResult:
    """Solve one global field directly on the authoritative transient grid."""
    cfg = settings or MultiregionCFDSettings()
    grid, fronts, geometry = _validate_supported_class(solver, cfg, refresh_regions=True)
    return _solve_current_geometry(grid, fronts, geometry, float(closing_speed_m_s), cfg)


def coupled_global_response(
    solver: Any,
    free_closing_speed_m_s: float,
    outer_resistance_n_s_m: float,
    settings: MultiregionCFDSettings | None = None,
) -> GlobalCoupledResponse:
    """Measure field resistance then retain the production field at coupled speed."""
    cfg = settings or MultiregionCFDSettings()
    free_speed = float(free_closing_speed_m_s)
    if free_speed < 0.0:
        raise ValueError("free closing speed must be non-negative")
    if outer_resistance_n_s_m <= 0.0:
        raise ValueError("outer resistance must be positive")
    grid, fronts, geometry = _validate_supported_class(solver, cfg, refresh_regions=True)
    baseline = _snapshot(grid)
    trial = _solve_current_geometry(grid, fronts, geometry, free_speed, cfg)
    if free_speed <= 1.0e-15:
        resistance = 0.0
        coupled = 0.0
    else:
        resistance = trial.resisting_force_n / free_speed
        coupled = free_speed * outer_resistance_n_s_m / (
            outer_resistance_n_s_m + max(resistance, 0.0)
        )
    _restore(grid, baseline)
    production = _solve_current_geometry(grid, fronts, geometry, coupled, cfg)
    return GlobalCoupledResponse(
        free_closing_speed_m_s=free_speed,
        coupled_closing_speed_m_s=coupled,
        correction_speed_m_s=max(0.0, free_speed - coupled),
        outer_resistance_n_s_m=float(outer_resistance_n_s_m),
        resolved_cfd_resistance_n_s_m=float(max(resistance, 0.0)),
        trial_field=trial,
        production_field=production,
    )
