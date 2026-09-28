"""Deterministic front-tracked film sheet + sharp two-region Eulerian gas solver."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

from ..boundary import (
    BoundarySet,
    SolidBoundary,
    combine_contact_reports,
    constrain_velocity,
    enforce_front_contact,
)
from .geometry import FilmFront, Vec3, add, cross, dot, norm, sub
from .grid import EulerianGasGrid, GridConfig, RegionProperties
from .amr import AMRConfig, AdaptiveEulerianGasGrid
from .remeshing import ConservativeArealField, FrontRemesher, RemeshConfig


@dataclass(frozen=True)
class TimeStepPolicy:
    max_dt_s: float = 5.0e-4
    advective_cfl: float = 0.45
    viscous_safety: float = 0.20
    capillary_safety: float = 0.20
    min_dt_s: float = 1.0e-8


@dataclass(frozen=True)
class TransientConfig:
    grid: GridConfig = field(default_factory=GridConfig)
    amr: AMRConfig = field(default_factory=AMRConfig)
    gravity_m_s2: Vec3 = (0.0, 0.0, 0.0)
    timestep: TimeStepPolicy = field(default_factory=TimeStepPolicy)
    deterministic_seed: int = 0
    preserve_closed_bubble_volume: bool = True
    region_properties: dict[str, RegionProperties] = field(default_factory=dict)
    sharp_pressure_jump: bool = True
    remeshing: RemeshConfig = field(default_factory=RemeshConfig)
    solid_boundaries: tuple[SolidBoundary, ...] = ()
    boundary_tolerance_m: float = 1.0e-9
    boundary_projection_iterations: int = 4

    def __post_init__(self) -> None:
        if self.boundary_tolerance_m < 0.0:
            raise ValueError("boundary tolerance must be non-negative")
        if self.boundary_projection_iterations < 1:
            raise ValueError("boundary projection iterations must be at least one")
        BoundarySet(self.solid_boundaries)


@dataclass
class StepDiagnostics:
    step_index: int
    simulation_time_s: float
    timestep_s: float
    divergence_linf_s_inv: float
    projection_residual_s_inv: float
    pressure_iterations: int
    max_speed_m_s: float
    max_relative_volume_error_pre_projection: float
    max_relative_volume_error: float
    surface_energy_j: float
    bulk_kinetic_energy_j: float
    capillary_force_l1_n: float
    net_capillary_force_n: Vec3
    max_pressure_jump_relative_error: float
    remesh_operation_count: int = 0
    remesh_max_relative_volume_change: float = 0.0
    remesh_max_field_conservation_error: float = 0.0
    remesh_reports: tuple[dict[str, object], ...] = ()
    boundary_contact_vertex_count: int = 0
    boundary_contact_face_count: int = 0
    boundary_max_penetration_pre_m: float = 0.0
    boundary_max_penetration_post_m: float = 0.0
    boundary_position_correction_l1_m: float = 0.0
    boundary_velocity_correction_proxy_l1_m_s: float = 0.0
    boundary_ids: tuple[str, ...] = ()
    boundary_reports: tuple[dict[str, object], ...] = ()

    def scalar_dict(self) -> dict[str, float]:
        return {
            "divergence_linf_s_inv": self.divergence_linf_s_inv,
            "projection_residual_s_inv": self.projection_residual_s_inv,
            "max_speed_m_s": self.max_speed_m_s,
            "surface_energy_j": self.surface_energy_j,
            "bulk_kinetic_energy_j": self.bulk_kinetic_energy_j,
            "capillary_force_l1_n": self.capillary_force_l1_n,
            "max_pressure_jump_relative_error": self.max_pressure_jump_relative_error,
            "remesh_operation_count": float(self.remesh_operation_count),
            "remesh_max_relative_volume_change": self.remesh_max_relative_volume_change,
            "remesh_max_field_conservation_error": self.remesh_max_field_conservation_error,
            "boundary_contact_vertex_count": float(self.boundary_contact_vertex_count),
            "boundary_contact_face_count": float(self.boundary_contact_face_count),
            "boundary_max_penetration_pre_m": self.boundary_max_penetration_pre_m,
            "boundary_max_penetration_post_m": self.boundary_max_penetration_post_m,
            "boundary_position_correction_l1_m": self.boundary_position_correction_l1_m,
            "boundary_velocity_correction_proxy_l1_m_s": self.boundary_velocity_correction_proxy_l1_m_s,
        }


def _solid_angle_contains(front: FilmFront, point: Vec3) -> bool:
    """Classify a point by oriented solid angle of the closed triangle front."""
    total = 0.0
    scale = max(front.equivalent_radius(), 1.0)
    eps = 1.0e-14 * scale
    px, py, pz = point
    for i, j, k in front.faces:
        va = front.vertices[i]
        vb = front.vertices[j]
        vc = front.vertices[k]
        a = (va[0] - px, va[1] - py, va[2] - pz)
        b = (vb[0] - px, vb[1] - py, vb[2] - pz)
        c = (vc[0] - px, vc[1] - py, vc[2] - pz)
        la, lb, lc = norm(a), norm(b), norm(c)
        if min(la, lb, lc) <= eps:
            return True
        numerator = dot(a, cross(b, c))
        denominator = (
            la * lb * lc
            + dot(a, b) * lc
            + dot(b, c) * la
            + dot(c, a) * lb
        )
        total += 2.0 * math.atan2(numerator, denominator)
    return abs(total) > 2.0 * math.pi


def _front_bounds(front: FilmFront) -> tuple[Vec3, Vec3]:
    return (
        (
            min(v[0] for v in front.vertices),
            min(v[1] for v in front.vertices),
            min(v[2] for v in front.vertices),
        ),
        (
            max(v[0] for v in front.vertices),
            max(v[1] for v in front.vertices),
            max(v[2] for v in front.vertices),
        ),
    )


def _mean_discrete_curvature_1_m(front: FilmFront) -> float:
    """Area-weighted |kappa| from the same discrete area variation as capillarity."""
    vectors = front.normal_curvature_vectors()
    dual = [0.0] * len(front.vertices)
    for i, j, k in front.faces:
        a, b, c = front.vertices[i], front.vertices[j], front.vertices[k]
        area = 0.5 * norm(cross(sub(b, a), sub(c, a)))
        share = area / 3.0
        dual[i] += share
        dual[j] += share
        dual[k] += share
    total_area = sum(dual)
    if total_area <= 0.0:
        raise ValueError("film front has zero area")
    return sum(area * norm(kappa) for area, kappa in zip(dual, vectors)) / total_area


class TransientSoapFilmSolver:
    """Sharp/jump-aware front-tracked reference backend.

    Solid boundaries retain the accepted tracked-film no-penetration/free-slip
    contact model and additionally cut the Eulerian bulk-flow stencil with a
    resolved SDF no-slip condition. Declared wall velocity is imposed on every
    velocity component in the viscous wall treatment while pressure projection
    preserves wall-normal velocity.
    """

    VERSION = "0.6.0-bulk-noslip-wall-cfd"

    def __init__(self, fronts: list[FilmFront], config: TransientConfig | None = None):
        if not fronts:
            raise ValueError("at least one film front is required")
        self.config = config or TransientConfig()
        self.fronts = [front.clone() for front in fronts]
        ids = [f.bubble_id for f in self.fronts]
        if len(ids) != len(set(ids)):
            raise ValueError("bubble IDs must be unique")
        unknown = set(self.config.region_properties) - set(ids)
        if unknown:
            raise ValueError(f"region properties reference unknown bubbles: {sorted(unknown)}")
        self.boundaries = BoundarySet(self.config.solid_boundaries)
        self.grid = (
            AdaptiveEulerianGasGrid(self.config.grid, self.config.amr)
            if self.config.amr.enabled
            else EulerianGasGrid(self.config.grid)
        )
        self.time_s = 0.0
        self.step_index = 0
        self.history: list[StepDiagnostics] = []
        self._bubble_velocities = {f.bubble_id: (0.0, 0.0, 0.0) for f in self.fronts}
        self._pressure_jumps_pa: dict[str, float] = {}
        self._remesher = FrontRemesher(self.config.remeshing)
        self.surface_fields: dict[str, dict[str, ConservativeArealField]] = {
            f.bubble_id: {} for f in self.fronts
        }
        self._refresh_regions()

    def clone_initial(self) -> "TransientSoapFilmSolver":
        clone = TransientSoapFilmSolver([front.clone() for front in self.fronts], self.config)
        clone.surface_fields = {
            bubble_id: {name: field.clone() for name, field in fields.items()}
            for bubble_id, fields in self.surface_fields.items()
        }
        return clone

    def attach_surface_field(
        self,
        bubble_id: str,
        name: str,
        density: float,
    ) -> ConservativeArealField:
        """Attach a generic areal scalar for conservative mesh-transfer testing."""
        if not name:
            raise ValueError("surface field name must be non-empty")
        try:
            front = next(front for front in self.fronts if front.bubble_id == bubble_id)
        except StopIteration as exc:
            raise ValueError(f"unknown bubble id {bubble_id!r}") from exc
        if name in self.surface_fields[bubble_id]:
            raise ValueError(f"surface field {name!r} already exists on {bubble_id!r}")
        field_value = ConservativeArealField.from_density(front, name, density)
        self.surface_fields[bubble_id][name] = field_value
        return field_value

    def _should_remesh(self, front: FilmFront) -> bool:
        config = self.config.remeshing
        if config.mode == "disabled":
            return False
        if config.mode == "interval":
            return (self.step_index + 1) % config.interval_steps == 0
        local_h = self.grid.finest.h if isinstance(self.grid, AdaptiveEulerianGasGrid) else self.grid.h
        return self._remesher.needs_remesh(front, local_h)

    def _remesh_fronts(self) -> tuple[dict[str, object], ...]:
        reports: list[dict[str, object]] = []
        local_h = self.grid.finest.h if isinstance(self.grid, AdaptiveEulerianGasGrid) else self.grid.h
        for front in self.fronts:
            if not self._should_remesh(front):
                continue
            report = self._remesher.remesh(
                front,
                self.surface_fields[front.bubble_id],
                local_eulerian_cell_size_m=local_h,
                force=self.config.remeshing.mode == "interval",
            )
            reports.append({"bubble_id": front.bubble_id, **report.as_dict()})
        return tuple(reports)

    def _region_properties(self) -> dict[str, RegionProperties]:
        exterior = RegionProperties(
            self.config.grid.density_kg_m3,
            self.config.grid.dynamic_viscosity_pa_s,
        )
        return {
            front.bubble_id: self.config.region_properties.get(front.bubble_id, exterior)
            for front in self.fronts
        }

    def _refresh_regions(self) -> None:
        if isinstance(self.grid, AdaptiveEulerianGasGrid):
            self.grid.regrid(self.fronts)
            grids = self.grid.level_grids()
        else:
            grids = [self.grid]

        jumps = {}
        for front in self.fronts:
            curvature = _mean_discrete_curvature_1_m(front)
            jumps[front.bubble_id] = front.surface_tension_n_m * curvature
        self._pressure_jumps_pa = jumps
        bounded = [(front, _front_bounds(front)) for front in self.fronts]
        properties = self._region_properties()

        for gas_grid in grids:
            labels = ["EXTERIOR"] * (gas_grid.nx * gas_grid.ny * gas_grid.nz)
            for q in range(len(labels)):
                p = gas_grid.cell_center(*gas_grid._ijk(q))
                for front, (lo, hi) in bounded:
                    if not (
                        lo[0] <= p[0] <= hi[0]
                        and lo[1] <= p[1] <= hi[1]
                        and lo[2] <= p[2] <= hi[2]
                    ):
                        continue
                    if _solid_angle_contains(front, p):
                        labels[q] = front.bubble_id
                        break
            gas_grid.configure_regions(
                labels,
                properties,
                jumps if self.config.sharp_pressure_jump else {},
            )
            gas_grid.configure_solid_walls(self.boundaries)

    def _has_density_contrast(self) -> bool:
        rho_ext = self.config.grid.density_kg_m3
        return any(
            abs(props.density_kg_m3 - rho_ext) > 1.0e-14 * max(rho_ext, props.density_kg_m3)
            for props in self._region_properties().values()
        )

    def _capillary_timescale_dt(self) -> float:
        sigma = max((f.surface_tension_n_m for f in self.fronts), default=0.0)
        if sigma <= 0.0:
            return float("inf")
        rho = (
            self.grid.minimum_density()
            if isinstance(self.grid, AdaptiveEulerianGasGrid)
            else min(self.grid.density)
        )
        h = self.grid.h
        return self.config.timestep.capillary_safety * math.sqrt(rho * h ** 3 / sigma)

    def select_timestep(self, remaining_s: float | None = None) -> float:
        policy = self.config.timestep
        speed = self.grid.max_speed()
        advective = float("inf") if speed <= 1e-15 else policy.advective_cfl * self.grid.h / speed
        max_nu = (
            self.grid.maximum_kinematic_viscosity()
            if isinstance(self.grid, AdaptiveEulerianGasGrid)
            else max(
                (mu / rho for mu, rho in zip(self.grid.dynamic_viscosity, self.grid.density)),
                default=0.0,
            )
        )
        viscous = float("inf") if max_nu <= 0.0 else policy.viscous_safety * self.grid.h ** 2 / max_nu
        capillary = self._capillary_timescale_dt()
        dt = min(policy.max_dt_s, advective, viscous, capillary)
        if remaining_s is not None:
            dt = min(dt, remaining_s)
        if dt < policy.min_dt_s:
            raise RuntimeError(f"stable timestep {dt:g}s is below configured minimum")
        return dt

    def _capillary_force_diagnostics(self):
        n = self.grid.nx * self.grid.ny * self.grid.nz
        total = ([0.0] * n, [0.0] * n, [0.0] * n)
        capillary_l1 = 0.0
        net = (0.0, 0.0, 0.0)
        for front in self.fronts:
            forces = front.capillary_vertex_forces()
            capillary_l1 += sum(norm(force) for force in forces)
            net = add(net, (
                sum(force[0] for force in forces),
                sum(force[1] for force in forces),
                sum(force[2] for force in forces),
            ))
            if not self.config.sharp_pressure_jump:
                spread = self.grid.spread_vertex_forces(front.vertices, forces)
                for axis in range(3):
                    dest = total[axis]
                    src = spread[axis]
                    for q in range(n):
                        dest[q] += src[q]
        return total, capillary_l1, net

    def surface_energy(self) -> float:
        return sum(f.surface_tension_n_m * f.area() for f in self.fronts)

    def volume_errors(self) -> dict[str, float]:
        return {
            f.bubble_id: abs(f.volume() - float(f.target_volume_m3)) / float(f.target_volume_m3)
            for f in self.fronts
        }

    def pressure_jump_pa(self, bubble_id: str) -> float:
        if isinstance(self.grid, AdaptiveEulerianGasGrid):
            return self.grid.pressure_jump(bubble_id, physical=False)
        return self.grid.mean_pressure(bubble_id, physical=False) - self.grid.mean_pressure("EXTERIOR", physical=False)

    def target_pressure_jump_pa(self, bubble_id: str) -> float:
        return self._pressure_jumps_pa[bubble_id]

    def _max_pressure_jump_relative_error(self) -> float:
        errors = []
        for front in self.fronts:
            target = self.target_pressure_jump_pa(front.bubble_id)
            if abs(target) <= 1.0e-30:
                continue
            measured = self.pressure_jump_pa(front.bubble_id)
            errors.append(abs(measured - target) / abs(target))
        return max(errors, default=0.0)

    def _contact_report(self, front: FilmFront, dt_s: float, *, apply_wetting: bool) -> dict[str, object]:
        return enforce_front_contact(
            front,
            self.boundaries,
            self.config.boundary_tolerance_m,
            dt_s,
            apply_wetting=apply_wetting,
        )

    def step(self, dt_s: float | None = None) -> StepDiagnostics:
        self._refresh_regions()
        dt = self.select_timestep() if dt_s is None else dt_s
        if dt <= 0.0:
            raise ValueError("dt must be positive")
        stable = self.select_timestep()
        if dt > stable * (1.0 + 1e-12):
            raise ValueError(f"requested dt={dt:g}s exceeds stability policy {stable:g}s")

        diffuse_capillary, capillary_l1, net_force = self._capillary_force_diagnostics()
        hydro_ref = self.config.grid.density_kg_m3 if self._has_density_contrast() else None
        self.grid.advance(
            dt,
            diffuse_capillary,
            self.config.gravity_m_s2,
            hydrostatic_reference_density_kg_m3=hydro_ref,
        )
        grids = self.grid.level_grids() if isinstance(self.grid, AdaptiveEulerianGasGrid) else [self.grid]
        for gas_grid in grids:
            gas_grid.apply_solid_wall_constraints()

        pressure_jump_error = self._max_pressure_jump_relative_error()
        pre_projection_error = 0.0
        old_centroids = {f.bubble_id: f.centroid() for f in self.fronts}
        contact_passes: dict[str, list[dict[str, object]]] = {
            front.bubble_id: [] for front in self.fronts
        }

        def tracked_velocity(point: Vec3) -> Vec3:
            raw = self.grid.sample_velocity(point)
            if not self.boundaries:
                return raw
            corrected, _ = constrain_velocity(
                point,
                raw,
                self.boundaries,
                dt,
                self.config.boundary_tolerance_m,
            )
            return corrected

        for front in self.fronts:
            front.advect(tracked_velocity, dt)
            if self.boundaries:
                contact_passes[front.bubble_id].append(self._contact_report(front, dt, apply_wetting=True))

        remesh_reports = self._remesh_fronts()
        remesh_operation_count = sum(
            sum(int(value) for value in report["operations"].values())
            for report in remesh_reports
        )
        remesh_volume_error = max(
            (float(report["volume_relative_change_pre_projection"]) for report in remesh_reports),
            default=0.0,
        )
        remesh_field_error = max(
            (float(report["field_conservation_relative_error"]) for report in remesh_reports),
            default=0.0,
        )

        iterations = self.config.boundary_projection_iterations if self.boundaries else 1
        for _ in range(iterations):
            for front in self.fronts:
                if self.config.preserve_closed_bubble_volume:
                    pre_projection_error = max(pre_projection_error, front.project_volume())
            if self.boundaries:
                for front in self.fronts:
                    contact_passes[front.bubble_id].append(self._contact_report(front, dt, apply_wetting=False))

        self.time_s += dt
        self.step_index += 1
        for front in self.fronts:
            old = old_centroids[front.bubble_id]
            new = front.centroid()
            self._bubble_velocities[front.bubble_id] = (
                (new[0] - old[0]) / dt,
                (new[1] - old[1]) / dt,
                (new[2] - old[2]) / dt,
            )
        post = max(self.volume_errors().values(), default=0.0)

        combined_reports: list[dict[str, object]] = []
        for front in self.fronts:
            passes = contact_passes[front.bubble_id]
            if passes:
                combined_reports.append(combine_contact_reports(*passes))
        boundary_ids = tuple(sorted({
            str(boundary_id)
            for report in combined_reports
            for boundary_id in report.get("boundary_ids", [])
        }))

        diag = StepDiagnostics(
            step_index=self.step_index,
            simulation_time_s=self.time_s,
            timestep_s=dt,
            divergence_linf_s_inv=self.grid.divergence_linf(),
            projection_residual_s_inv=self.grid.last_projection_residual,
            pressure_iterations=self.grid.last_projection_iterations,
            max_speed_m_s=self.grid.max_speed(),
            max_relative_volume_error_pre_projection=pre_projection_error,
            max_relative_volume_error=post,
            surface_energy_j=self.surface_energy(),
            bulk_kinetic_energy_j=self.grid.kinetic_energy(),
            capillary_force_l1_n=capillary_l1,
            net_capillary_force_n=net_force,
            max_pressure_jump_relative_error=pressure_jump_error,
            remesh_operation_count=remesh_operation_count,
            remesh_max_relative_volume_change=remesh_volume_error,
            remesh_max_field_conservation_error=remesh_field_error,
            remesh_reports=remesh_reports,
            boundary_contact_vertex_count=sum(int(report.get("contact_vertex_count", 0)) for report in combined_reports),
            boundary_contact_face_count=sum(int(report.get("contact_face_count", 0)) for report in combined_reports),
            boundary_max_penetration_pre_m=max(
                (float(report.get("max_penetration_pre_m", 0.0)) for report in combined_reports),
                default=0.0,
            ),
            boundary_max_penetration_post_m=max(
                (float(report.get("max_penetration_post_m", 0.0)) for report in combined_reports),
                default=0.0,
            ),
            boundary_position_correction_l1_m=sum(
                float(report.get("position_correction_l1_m", 0.0)) for report in combined_reports
            ),
            boundary_velocity_correction_proxy_l1_m_s=sum(
                float(report.get("velocity_correction_proxy_l1_m_s", 0.0)) for report in combined_reports
            ),
            boundary_ids=boundary_ids,
            boundary_reports=tuple(combined_reports),
        )
        self.history.append(diag)
        self._refresh_regions()
        return diag

    def run_to_time(self, target_time_s: float) -> list[StepDiagnostics]:
        if target_time_s < self.time_s:
            raise ValueError("target time is before current solver time")
        generated: list[StepDiagnostics] = []
        while self.time_s + 1e-15 < target_time_s:
            remaining = target_time_s - self.time_s
            dt = self.select_timestep(remaining)
            generated.append(self.step(dt))
        return generated

    def bubble_velocity(self, bubble_id: str) -> Vec3:
        return self._bubble_velocities[bubble_id]

    def replay_signature(self) -> tuple[Any, ...]:
        """Canonical scalar/geometry signature for deterministic same-build replay."""
        front_data = []
        for f in self.fronts:
            front_data.append((
                f.bubble_id,
                tuple(tuple(float(x) for x in v) for v in f.vertices),
                tuple(f.faces),
                f.volume(),
                f.area(),
            ))
        diag_data = tuple(
            (
                d.step_index, d.simulation_time_s, d.timestep_s,
                d.divergence_linf_s_inv, d.projection_residual_s_inv,
                d.max_speed_m_s, d.max_relative_volume_error,
                d.surface_energy_j, d.bulk_kinetic_energy_j,
                d.max_pressure_jump_relative_error,
                d.remesh_operation_count,
                d.remesh_max_relative_volume_change,
                d.remesh_max_field_conservation_error,
                d.remesh_reports,
                d.boundary_contact_vertex_count,
                d.boundary_contact_face_count,
                d.boundary_max_penetration_pre_m,
                d.boundary_max_penetration_post_m,
                d.boundary_position_correction_l1_m,
                d.boundary_velocity_correction_proxy_l1_m_s,
                d.boundary_ids,
                d.boundary_reports,
            )
            for d in self.history
        )
        grid_state = (
            self.grid.state_signature()
            if isinstance(self.grid, AdaptiveEulerianGasGrid)
            else tuple(self.grid.region_labels)
        )
        return (
            self.time_s,
            tuple(front_data),
            tuple(
                (
                    bubble_id,
                    tuple(
                        (name, tuple(field.face_amounts))
                        for name, field in sorted(fields.items())
                    ),
                )
                for bubble_id, fields in sorted(self.surface_fields.items())
            ),
            diag_data,
            grid_state,
            tuple(sorted(self._pressure_jumps_pa.items())),
            tuple(
                (
                    boundary.boundary_id,
                    boundary.boundary_type,
                    boundary.wall_velocity_m_s,
                    boundary.wetting.target_contact_angle_deg,
                    boundary.wetting.relaxation,
                    boundary.wetting.iterations,
                    boundary.wetting.contact_band_m,
                )
                for boundary in self.boundaries
            ),
        )
