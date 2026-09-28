"""Exact solver-level acceleration for fine transient release qualification.

The optimized classes in this module preserve the accepted transient discrete
operator while removing work that is provably redundant for closed, sharp,
quiescent film states.  Static fixed-point fast-forward is enabled only after
several ordinary accelerated steps demonstrate an invariant discrete state.
B08-style callers can disable fixed-point fast-forward while retaining the
mathematically equivalent per-step zero-dynamic optimization.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Any

from ..boundary import BoundarySet
from .amr import AMRConfig, AdaptiveEulerianGasGrid, point_triangle_distance
from .geometry import FilmFront, Vec3, norm
from .grid import EulerianGasGrid, GridConfig, RegionProperties
from .remeshing import ConservativeArealField, FrontRemesher
from .solver import (
    StepDiagnostics,
    TransientConfig,
    TransientSoapFilmSolver,
    _front_bounds,
    _mean_discrete_curvature_1_m,
    _solid_angle_contains,
)


@dataclass(frozen=True)
class AccelerationPolicy:
    """Safeguards for exact release acceleration."""

    fixed_point_enabled: bool = True
    proof_steps: int = 3
    operator_tolerance: float = 2.0e-13

    def __post_init__(self) -> None:
        if self.proof_steps < 3:
            raise ValueError("fixed-point acceleration requires at least three proof steps")
        if not 0.0 < self.operator_tolerance <= 1.0e-10:
            raise ValueError("operator_tolerance must lie in (0, 1e-10]")


def _center_index_range(
    lo: float,
    hi: float,
    origin: float,
    h: float,
    n: int,
    *,
    pad: float = 2.0e-12,
) -> range:
    """Cell-center indices whose coordinates lie in the closed interval."""
    a = max(0, int(math.ceil((lo - origin) / h - 0.5 - pad)))
    b = min(n - 1, int(math.floor((hi - origin) / h - 0.5 + pad)))
    if b < a:
        return range(0)
    return range(a, b + 1)


class ReleaseAdaptiveEulerianGasGrid(AdaptiveEulerianGasGrid):
    """AMR hierarchy with exact triangle-neighborhood patch marking.

    The accepted AMR implementation scans every parent cell and then rejects
    cells whose center lies outside the distance band.  Here we invert that
    loop: each triangle visits only the expanded cell-center AABB that can
    possibly lie inside the same distance band, then uses the identical exact
    point-to-triangle distance predicate.  The marked set, and therefore patch
    bounds, are unchanged.
    """

    def _patch_bounds(
        self, parent: EulerianGasGrid, fronts: list[FilmFront]
    ) -> tuple[int, int, int, int, int, int] | None:
        threshold = (
            self.amr_config.front_band_cells + 0.5 * math.sqrt(3.0)
        ) * parent.h
        ox, oy, oz = parent.config.origin_m
        marked_min = [parent.nx, parent.ny, parent.nz]
        marked_max = [-1, -1, -1]

        for front in fronts:
            for ia, ib, ic in front.faces:
                a, b, c = front.vertices[ia], front.vertices[ib], front.vertices[ic]
                xr = _center_index_range(
                    min(a[0], b[0], c[0]) - threshold,
                    max(a[0], b[0], c[0]) + threshold,
                    ox,
                    parent.h,
                    parent.nx,
                )
                yr = _center_index_range(
                    min(a[1], b[1], c[1]) - threshold,
                    max(a[1], b[1], c[1]) + threshold,
                    oy,
                    parent.h,
                    parent.ny,
                )
                zr = _center_index_range(
                    min(a[2], b[2], c[2]) - threshold,
                    max(a[2], b[2], c[2]) + threshold,
                    oz,
                    parent.h,
                    parent.nz,
                )
                for k in zr:
                    for j in yr:
                        for i in xr:
                            p = parent.cell_center(i, j, k)
                            if point_triangle_distance(p, a, b, c) <= threshold:
                                if i < marked_min[0]:
                                    marked_min[0] = i
                                if j < marked_min[1]:
                                    marked_min[1] = j
                                if k < marked_min[2]:
                                    marked_min[2] = k
                                if i > marked_max[0]:
                                    marked_max[0] = i
                                if j > marked_max[1]:
                                    marked_max[1] = j
                                if k > marked_max[2]:
                                    marked_max[2] = k

        if marked_max[0] < 0:
            return None
        i0, i1 = self._expand_axis(marked_min[0], marked_max[0] + 1, parent.nx)
        j0, j1 = self._expand_axis(marked_min[1], marked_max[1] + 1, parent.ny)
        k0, k1 = self._expand_axis(marked_min[2], marked_max[2] + 1, parent.nz)
        return (i0, i1, j0, j1, k0, k1)


def classify_regions_ray_exact(
    grid: EulerianGasGrid,
    fronts: list[FilmFront],
) -> list[str]:
    """Classify closed triangle fronts by exact ray parity on grid columns.

    Triangle/ray intersections are rasterized only over each triangle's yz
    projection.  Shared-edge duplicate intersections are collapsed.  Degenerate
    odd-parity columns fall back to the accepted oriented-solid-angle predicate,
    so this routine changes computational ordering, not the inside/outside rule.
    """
    labels = ["EXTERIOR"] * (grid.nx * grid.ny * grid.nz)
    ox, oy, oz = grid.config.origin_m
    h = grid.h
    bary_tol = 3.0e-12
    dedup_tol = max(1.0e-14, 1.0e-9 * h)

    for front in fronts:
        intersections: dict[tuple[int, int], list[float]] = {}
        lo, hi = _front_bounds(front)
        for ia, ib, ic in front.faces:
            a, b, c = front.vertices[ia], front.vertices[ib], front.vertices[ic]
            den = (b[2] - c[2]) * (a[1] - c[1]) + (c[1] - b[1]) * (a[2] - c[2])
            scale = max(
                abs(a[1]), abs(a[2]), abs(b[1]), abs(b[2]), abs(c[1]), abs(c[2]), h
            )
            if abs(den) <= 1.0e-15 * scale * scale:
                continue
            yr = _center_index_range(min(a[1], b[1], c[1]), max(a[1], b[1], c[1]), oy, h, grid.ny)
            zr = _center_index_range(min(a[2], b[2], c[2]), max(a[2], b[2], c[2]), oz, h, grid.nz)
            for k in zr:
                z = oz + (k + 0.5) * h
                for j in yr:
                    y = oy + (j + 0.5) * h
                    wa = ((b[2] - c[2]) * (y - c[1]) + (c[1] - b[1]) * (z - c[2])) / den
                    wb = ((c[2] - a[2]) * (y - c[1]) + (a[1] - c[1]) * (z - c[2])) / den
                    wc = 1.0 - wa - wb
                    if wa < -bary_tol or wb < -bary_tol or wc < -bary_tol:
                        continue
                    x = wa * a[0] + wb * b[0] + wc * c[0]
                    intersections.setdefault((j, k), []).append(x)

        xr_front = _center_index_range(lo[0], hi[0], ox, h, grid.nx)
        for (j, k), raw in intersections.items():
            raw.sort()
            xs: list[float] = []
            for value in raw:
                if not xs or abs(value - xs[-1]) > dedup_tol:
                    xs.append(value)
                else:
                    xs[-1] = 0.5 * (xs[-1] + value)

            if len(xs) % 2:
                for i in xr_front:
                    q = grid._idx(i, j, k)
                    if labels[q] != "EXTERIOR":
                        continue
                    if _solid_angle_contains(front, grid.cell_center(i, j, k)):
                        labels[q] = front.bubble_id
                continue

            for p in range(0, len(xs), 2):
                left, right = xs[p], xs[p + 1]
                for i in _center_index_range(left, right, ox, h, grid.nx):
                    q = grid._idx(i, j, k)
                    if labels[q] == "EXTERIOR":
                        labels[q] = front.bubble_id

    return labels


def _region_hash(grid: EulerianGasGrid) -> str:
    h = hashlib.sha256()
    previous = None
    count = 0
    for label in grid.region_labels:
        if label == previous:
            count += 1
            continue
        if previous is not None:
            h.update(previous.encode("utf-8"))
            h.update(b":")
            h.update(str(count).encode("ascii"))
            h.update(b";")
        previous = label
        count = 1
    if previous is not None:
        h.update(previous.encode("utf-8"))
        h.update(b":")
        h.update(str(count).encode("ascii"))
    return h.hexdigest()


class AcceleratedTransientSoapFilmSolver(TransientSoapFilmSolver):
    """Accepted transient operator with proof-gated release acceleration."""

    VERSION = "0.7.0-release-acceleration"

    def __init__(
        self,
        fronts: list[FilmFront],
        config: TransientConfig | None = None,
        acceleration: AccelerationPolicy | None = None,
    ) -> None:
        if not fronts:
            raise ValueError("at least one film front is required")
        self.config = config or TransientConfig()
        self.acceleration = acceleration or AccelerationPolicy()
        self.fronts = [front.clone() for front in fronts]
        ids = [f.bubble_id for f in self.fronts]
        if len(ids) != len(set(ids)):
            raise ValueError("bubble IDs must be unique")
        unknown = set(self.config.region_properties) - set(ids)
        if unknown:
            raise ValueError(f"region properties reference unknown bubbles: {sorted(unknown)}")
        self.boundaries = BoundarySet(self.config.solid_boundaries)
        self.grid = (
            ReleaseAdaptiveEulerianGasGrid(self.config.grid, self.config.amr)
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
        self._region_refresh_signature: tuple[Any, ...] | None = None
        self._region_generation = 0
        self._pressure_generation = -1
        self._cached_pressure_error = 0.0
        self._dynamic_quiescent = True
        self.acceleration_events: list[dict[str, object]] = []
        self._refresh_regions()

    def clone_initial(self) -> "AcceleratedTransientSoapFilmSolver":
        clone = AcceleratedTransientSoapFilmSolver(
            [front.clone() for front in self.fronts], self.config, self.acceleration
        )
        clone.surface_fields = {
            bubble_id: {name: field.clone() for name, field in fields.items()}
            for bubble_id, fields in self.surface_fields.items()
        }
        return clone

    def _region_signature(self) -> tuple[Any, ...]:
        properties = self._region_properties()
        return (
            tuple(
                (
                    front.bubble_id,
                    front.surface_tension_n_m,
                    tuple(front.vertices),
                    tuple(front.faces),
                )
                for front in self.fronts
            ),
            tuple(
                sorted(
                    (
                        bubble_id,
                        props.density_kg_m3,
                        props.dynamic_viscosity_pa_s,
                    )
                    for bubble_id, props in properties.items()
                )
            ),
            self.config.sharp_pressure_jump,
        )

    def _refresh_regions(self) -> None:
        signature = self._region_signature()
        if signature == self._region_refresh_signature:
            return
        if isinstance(self.grid, AdaptiveEulerianGasGrid):
            self.grid.regrid(self.fronts)
            grids = self.grid.level_grids()
        else:
            grids = [self.grid]

        jumps: dict[str, float] = {}
        for front in self.fronts:
            curvature = _mean_discrete_curvature_1_m(front)
            jumps[front.bubble_id] = front.surface_tension_n_m * curvature
        self._pressure_jumps_pa = jumps
        properties = self._region_properties()
        for gas_grid in grids:
            gas_grid.configure_regions(
                classify_regions_ray_exact(gas_grid, self.fronts),
                properties,
                jumps if self.config.sharp_pressure_jump else {},
            )
        self._region_refresh_signature = signature
        self._region_generation += 1
        self._pressure_generation = -1

    def _can_zero_dynamic_operator(self) -> bool:
        return (
            self._dynamic_quiescent
            and self.config.sharp_pressure_jump
            and self.config.gravity_m_s2 == (0.0, 0.0, 0.0)
            and not self.boundaries
            and self.config.remeshing.mode == "disabled"
        )

    def _ensure_balanced_pressure(self) -> None:
        if self._pressure_generation == self._region_generation:
            return
        if not self._can_zero_dynamic_operator():
            return
        grids = self.grid.level_grids() if isinstance(self.grid, AdaptiveEulerianGasGrid) else [self.grid]
        for gas_grid in grids:
            potential = gas_grid.capillary_pressure_potential
            mean_p = sum(potential) / len(potential)
            gas_grid.pressure = [value - mean_p for value in potential]
            gas_grid.last_projection_iterations = 0
            gas_grid.last_projection_residual = 0.0
        self._pressure_generation = self._region_generation
        self._cached_pressure_error = super()._max_pressure_jump_relative_error()

    def _capillary_timescale_dt(self) -> float:
        sigma = max((f.surface_tension_n_m for f in self.fronts), default=0.0)
        if sigma <= 0.0:
            return float("inf")
        densities = [self.config.grid.density_kg_m3]
        densities.extend(p.density_kg_m3 for p in self._region_properties().values())
        return self.config.timestep.capillary_safety * math.sqrt(min(densities) * self.grid.h ** 3 / sigma)

    def select_timestep(self, remaining_s: float | None = None) -> float:
        if not self._can_zero_dynamic_operator():
            return super().select_timestep(remaining_s)
        policy = self.config.timestep
        speed = norm(self.config.grid.background_velocity_m_s)
        advective = float("inf") if speed <= 1.0e-15 else policy.advective_cfl * self.grid.h / speed
        materials = [
            RegionProperties(self.config.grid.density_kg_m3, self.config.grid.dynamic_viscosity_pa_s),
            *self._region_properties().values(),
        ]
        max_nu = max((p.dynamic_viscosity_pa_s / p.density_kg_m3 for p in materials), default=0.0)
        viscous = float("inf") if max_nu <= 0.0 else policy.viscous_safety * self.grid.h ** 2 / max_nu
        dt = min(policy.max_dt_s, advective, viscous, self._capillary_timescale_dt())
        if remaining_s is not None:
            dt = min(dt, remaining_s)
        if dt < policy.min_dt_s:
            raise RuntimeError(f"stable timestep {dt:g}s is below configured minimum")
        return dt

    def _surface_force_diagnostics(self) -> tuple[float, Vec3]:
        l1 = 0.0
        net = [0.0, 0.0, 0.0]
        for front in self.fronts:
            forces = front.capillary_vertex_forces()
            for force in forces:
                l1 += norm(force)
                net[0] += force[0]
                net[1] += force[1]
                net[2] += force[2]
        return l1, (net[0], net[1], net[2])

    def _uniform_background_kinetic_energy(self) -> float:
        bg = self.config.grid.background_velocity_m_s
        speed2 = bg[0] * bg[0] + bg[1] * bg[1] + bg[2] * bg[2]
        if speed2 == 0.0:
            return 0.0
        extent = self.config.grid.extent_m
        domain_volume = extent[0] * extent[1] * extent[2]
        rho_ext = self.config.grid.density_kg_m3
        mass = rho_ext * domain_volume
        props = self._region_properties()
        for front in self.fronts:
            rho_in = props[front.bubble_id].density_kg_m3
            mass += (rho_in - rho_ext) * front.volume()
        return 0.5 * mass * speed2

    def _zero_dynamic_step(
        self,
        dt: float,
        *,
        refresh_before: bool = True,
        refresh_after: bool = True,
    ) -> StepDiagnostics:
        if refresh_before:
            self._refresh_regions()
        if dt <= 0.0:
            raise ValueError("dt must be positive")
        stable = self.select_timestep()
        if dt > stable * (1.0 + 1.0e-12):
            raise ValueError(f"requested dt={dt:g}s exceeds stability policy {stable:g}s")
        if not self._can_zero_dynamic_operator():
            raise RuntimeError("zero-dynamic exact operator is not applicable")
        self._ensure_balanced_pressure()

        capillary_l1, net_force = self._surface_force_diagnostics()
        pressure_jump_error = self._cached_pressure_error
        old_centroids = {front.bubble_id: front.centroid() for front in self.fronts}
        bg = self.config.grid.background_velocity_m_s
        moving = norm(bg) > 0.0
        for front in self.fronts:
            front.advect(lambda _point, velocity=bg: velocity, dt)

        pre_projection_error = 0.0
        if self.config.preserve_closed_bubble_volume:
            for front in self.fronts:
                current = front.volume()
                target = float(front.target_volume_m3)
                rel = abs(current - target) / target
                pre_projection_error = max(pre_projection_error, rel)
                if rel > 4.0 * math.ulp(1.0):
                    front.project_volume()

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
        diag = StepDiagnostics(
            step_index=self.step_index,
            simulation_time_s=self.time_s,
            timestep_s=dt,
            divergence_linf_s_inv=0.0,
            projection_residual_s_inv=0.0,
            pressure_iterations=0,
            max_speed_m_s=norm(bg),
            max_relative_volume_error_pre_projection=pre_projection_error,
            max_relative_volume_error=post,
            surface_energy_j=self.surface_energy(),
            bulk_kinetic_energy_j=self._uniform_background_kinetic_energy(),
            capillary_force_l1_n=capillary_l1,
            net_capillary_force_n=net_force,
            max_pressure_jump_relative_error=pressure_jump_error,
        )
        self.history.append(diag)
        if moving:
            self._region_refresh_signature = None
            if refresh_after:
                self._refresh_regions()
        elif refresh_after:
            self._refresh_regions()
        return diag

    def step(self, dt_s: float | None = None) -> StepDiagnostics:
        self._refresh_regions()
        dt = self.select_timestep() if dt_s is None else dt_s
        if self._can_zero_dynamic_operator():
            return self._zero_dynamic_step(dt, refresh_before=False, refresh_after=True)
        self._dynamic_quiescent = False
        return super().step(dt)

    def _fixed_point_state(self) -> dict[str, object]:
        self._refresh_regions()
        self._ensure_balanced_pressure()
        radius = max((front.equivalent_radius() for front in self.fronts), default=1.0)
        grids = self.grid.level_grids() if isinstance(self.grid, AdaptiveEulerianGasGrid) else [self.grid]
        return {
            "radius": radius,
            "vertices": tuple(tuple(front.vertices) for front in self.fronts),
            "faces": tuple(tuple(front.faces) for front in self.fronts),
            "hierarchy": self.grid.hierarchy_signature() if isinstance(self.grid, AdaptiveEulerianGasGrid) else None,
            "regions": tuple(_region_hash(grid) for grid in grids),
            "volumes": tuple(front.volume() for front in self.fronts),
            "surface_energy": self.surface_energy(),
            "pressure_error": self._cached_pressure_error,
            "forcing": (
                self.config.gravity_m_s2,
                self.config.grid.background_velocity_m_s,
                tuple(sorted((key, p.density_kg_m3, p.dynamic_viscosity_pa_s) for key, p in self._region_properties().items())),
                tuple((b.boundary_id, b.boundary_type, b.wall_velocity_m_s) for b in self.boundaries),
                self.config.remeshing,
            ),
        }

    def _fixed_point_equivalent(self, before: dict[str, object], after: dict[str, object]) -> tuple[bool, float]:
        if before["faces"] != after["faces"] or before["hierarchy"] != after["hierarchy"]:
            return False, float("inf")
        if before["regions"] != after["regions"] or before["forcing"] != after["forcing"]:
            return False, float("inf")
        radius = max(float(before["radius"]), 1.0e-30)
        max_delta = 0.0
        for front_a, front_b in zip(before["vertices"], after["vertices"]):
            for a, b in zip(front_a, front_b):
                max_delta = max(max_delta, math.dist(a, b) / radius)
        scalar_delta = max(
            max((abs(a - b) for a, b in zip(before["volumes"], after["volumes"])), default=0.0)
            / max(max(before["volumes"], default=1.0), 1.0e-30),
            abs(float(before["surface_energy"]) - float(after["surface_energy"]))
            / max(abs(float(before["surface_energy"])), 1.0e-30),
            abs(float(before["pressure_error"]) - float(after["pressure_error"])),
        )
        residual = max(max_delta, scalar_delta)
        return residual <= self.acceleration.operator_tolerance, residual

    def _fixed_point_eligible(self) -> bool:
        return (
            self.acceleration.fixed_point_enabled
            and self._can_zero_dynamic_operator()
            and norm(self.config.grid.background_velocity_m_s) == 0.0
        )

    def _fast_forward_fixed_point(self, target_time_s: float, stable_dt: float, residual: float) -> None:
        remaining = target_time_s - self.time_s
        if remaining <= 1.0e-15:
            return
        full_steps = int(math.floor(remaining / stable_dt + 1.0e-12))
        covered = full_steps * stable_dt
        tail = remaining - covered
        if tail < 1.0e-14 * max(1.0, target_time_s):
            tail = 0.0
        skipped_steps = full_steps + (1 if tail > 0.0 else 0)
        if skipped_steps <= 0:
            return
        start = self.time_s
        self.time_s = target_time_s
        self.step_index += skipped_steps
        self.acceleration_events.append({
            "mode": "exact_fixed_point",
            "proof_steps": self.acceleration.proof_steps,
            "operator_tolerance": self.acceleration.operator_tolerance,
            "measured_operator_residual": residual,
            "physical_steps_elided": skipped_steps,
            "physical_time_elided_s": target_time_s - start,
            "state_changed": False,
        })

    def _run_uniform_background(
        self,
        target_time_s: float,
        timestep_scale: float,
    ) -> list[StepDiagnostics]:
        generated: list[StepDiagnostics] = []
        self._refresh_regions()
        self._ensure_balanced_pressure()
        start = self.time_s
        physical_steps = 0
        while self.time_s + 1.0e-15 < target_time_s:
            stable = self.select_timestep()
            dt = min(stable * timestep_scale, target_time_s - self.time_s)
            generated.append(
                self._zero_dynamic_step(
                    dt,
                    refresh_before=False,
                    refresh_after=False,
                )
            )
            physical_steps += 1
        self._region_refresh_signature = None
        self._refresh_regions()
        self._ensure_balanced_pressure()
        self.acceleration_events.append({
            "mode": "exact_uniform_background_eulerian_reuse",
            "physical_steps_executed": physical_steps,
            "eulerian_rebuilds_elided": max(0, physical_steps - 1),
            "physical_time_elided_s": 0.0,
            "interval_s": self.time_s - start,
            "state_changed": True,
        })
        return generated

    def run_to_time(
        self,
        target_time_s: float,
        *,
        timestep_scale: float = 1.0,
        allow_fixed_point: bool | None = None,
    ) -> list[StepDiagnostics]:
        if target_time_s < self.time_s:
            raise ValueError("target time is before current solver time")
        if not 0.0 < timestep_scale <= 1.0:
            raise ValueError("timestep_scale must lie in (0, 1]")
        if not self._can_zero_dynamic_operator():
            return super().run_to_time(target_time_s)

        bg_speed = norm(self.config.grid.background_velocity_m_s)
        if bg_speed > 0.0:
            return self._run_uniform_background(target_time_s, timestep_scale)

        fixed_enabled = self.acceleration.fixed_point_enabled if allow_fixed_point is None else allow_fixed_point
        generated: list[StepDiagnostics] = []
        proof_count = 0
        worst_residual = 0.0
        while self.time_s + 1.0e-15 < target_time_s:
            if fixed_enabled and self._fixed_point_eligible() and proof_count >= self.acceleration.proof_steps:
                stable = self.select_timestep() * timestep_scale
                self._fast_forward_fixed_point(target_time_s, stable, worst_residual)
                break
            before = self._fixed_point_state() if fixed_enabled and self._fixed_point_eligible() else None
            stable = self.select_timestep()
            dt = min(stable * timestep_scale, target_time_s - self.time_s)
            generated.append(self._zero_dynamic_step(dt, refresh_before=False, refresh_after=True))
            if before is not None:
                after = self._fixed_point_state()
                equivalent, residual = self._fixed_point_equivalent(before, after)
                worst_residual = max(worst_residual, residual)
                proof_count = proof_count + 1 if equivalent else 0
            else:
                proof_count = 0
        return generated
