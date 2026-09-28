"""Deterministic block-structured adaptive Eulerian hierarchy.

The AMR hierarchy keeps a coarse periodic reference grid over the full domain and
adds nested Cartesian patches around the tracked film.  Refinement decisions are
based on geometric distance from parent-cell centers to tracked triangles, then
snapped to parent-cell boundaries.  This makes the hierarchy deterministic for a
fixed front and configuration.

Velocity and pressure are explicitly prolonged from parent to child when a patch
is created.  After every level advance, child velocity and pressure are
restricted back to covered parent cells by volume averaging.  Constant fields
and constant-density integrated momentum are therefore exactly preserved up to
floating-point roundoff.  Density, viscosity, region labels, and capillary jump
potentials are not transferred: the solver recomputes them from authoritative
front geometry on every level after each regrid.

Each level executes the same variable-density, jump-balanced pressure projection
as the accepted uniform backend.  Fine patches receive a one-cell shell filled
from their parent before advancing, and restriction returns the fine correction
to the parent.  This is a deterministic nested-grid correction scheme rather
than a single-grid refinement mask; cells covered by a child are excluded from
composite diagnostics and cell-budget accounting.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from .geometry import FilmFront, Vec3, dot, sub
from .grid import EulerianGasGrid, GridConfig


@dataclass(frozen=True)
class AMRConfig:
    enabled: bool = False
    max_levels: int = 1
    refinement_ratio: int = 2
    front_band_cells: float = 0.90
    min_patch_parent_cells: int = 2
    boundary_fill_cells: int = 1

    def __post_init__(self) -> None:
        if self.max_levels < 0:
            raise ValueError("AMR max_levels must be non-negative")
        if self.refinement_ratio < 2:
            raise ValueError("AMR refinement_ratio must be at least 2")
        if self.front_band_cells <= 0.0:
            raise ValueError("AMR front_band_cells must be positive")
        if self.min_patch_parent_cells < 2:
            raise ValueError("AMR min_patch_parent_cells must be at least 2")
        if self.boundary_fill_cells < 1:
            raise ValueError("AMR boundary_fill_cells must be positive")


@dataclass
class AMRLevel:
    level: int
    grid: EulerianGasGrid
    parent_bounds: tuple[int, int, int, int, int, int] | None

    @property
    def cell_count(self) -> int:
        return self.grid.nx * self.grid.ny * self.grid.nz


def _point_segment_distance(a: Vec3, b: Vec3, p: Vec3) -> float:
    ab = sub(b, a)
    ap = sub(p, a)
    denom = dot(ab, ab)
    if denom <= 1.0e-300:
        return math.sqrt(dot(ap, ap))
    t = max(0.0, min(1.0, dot(ap, ab) / denom))
    q = (a[0] + t * ab[0], a[1] + t * ab[1], a[2] + t * ab[2])
    d = sub(p, q)
    return math.sqrt(dot(d, d))


def point_triangle_distance(p: Vec3, a: Vec3, b: Vec3, c: Vec3) -> float:
    """Shortest Euclidean distance from p to triangle abc."""
    ab = sub(b, a)
    ac = sub(c, a)
    ap = sub(p, a)
    d1 = dot(ab, ap)
    d2 = dot(ac, ap)
    if d1 <= 0.0 and d2 <= 0.0:
        return math.sqrt(dot(ap, ap))

    bp = sub(p, b)
    d3 = dot(ab, bp)
    d4 = dot(ac, bp)
    if d3 >= 0.0 and d4 <= d3:
        return math.sqrt(dot(bp, bp))

    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        v = d1 / (d1 - d3)
        q = (a[0] + v * ab[0], a[1] + v * ab[1], a[2] + v * ab[2])
        d = sub(p, q)
        return math.sqrt(dot(d, d))

    cp = sub(p, c)
    d5 = dot(ab, cp)
    d6 = dot(ac, cp)
    if d6 >= 0.0 and d5 <= d6:
        return math.sqrt(dot(cp, cp))

    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        w = d2 / (d2 - d6)
        q = (a[0] + w * ac[0], a[1] + w * ac[1], a[2] + w * ac[2])
        d = sub(p, q)
        return math.sqrt(dot(d, d))

    va = d3 * d6 - d5 * d4
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:
        edge = sub(c, b)
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        q = (b[0] + w * edge[0], b[1] + w * edge[1], b[2] + w * edge[2])
        d = sub(p, q)
        return math.sqrt(dot(d, d))

    denom = va + vb + vc
    if abs(denom) <= 1.0e-300:
        return min(
            _point_segment_distance(a, b, p),
            _point_segment_distance(b, c, p),
            _point_segment_distance(c, a, p),
        )
    inv = 1.0 / denom
    v = vb * inv
    w = vc * inv
    q = (
        a[0] + ab[0] * v + ac[0] * w,
        a[1] + ab[1] * v + ac[1] * w,
        a[2] + ab[2] * v + ac[2] * w,
    )
    d = sub(p, q)
    return math.sqrt(dot(d, d))


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


class AdaptiveEulerianGasGrid:
    """Nested deterministic AMR hierarchy with composite diagnostics."""

    def __init__(self, config: GridConfig, amr: AMRConfig):
        if not amr.enabled:
            raise ValueError("AdaptiveEulerianGasGrid requires enabled AMRConfig")
        self.config = config
        self.amr_config = amr
        self.levels: list[AMRLevel] = [AMRLevel(0, EulerianGasGrid(config), None)]

    @property
    def base(self) -> EulerianGasGrid:
        return self.levels[0].grid

    @property
    def finest(self) -> EulerianGasGrid:
        return self.levels[-1].grid

    @property
    def nx(self) -> int:
        return self.base.nx

    @property
    def ny(self) -> int:
        return self.base.ny

    @property
    def nz(self) -> int:
        return self.base.nz

    @property
    def h(self) -> float:
        return self.finest.h

    @property
    def cell_volume(self) -> float:
        return self.base.cell_volume

    @property
    def u(self):
        return self.base.u

    @property
    def v(self):
        return self.base.v

    @property
    def w(self):
        return self.base.w

    @property
    def pressure(self):
        return self.base.pressure

    @property
    def region_labels(self):
        return self.base.region_labels

    @property
    def density(self):
        return self.base.density

    @property
    def dynamic_viscosity(self):
        return self.base.dynamic_viscosity

    @property
    def capillary_pressure_potential(self):
        return self.base.capillary_pressure_potential

    @property
    def last_projection_iterations(self) -> int:
        return sum(level.grid.last_projection_iterations for level in self.levels)

    @property
    def last_projection_residual(self) -> float:
        return max((level.grid.last_projection_residual for level in self.levels), default=0.0)

    @property
    def hydrostatic_reference_density_kg_m3(self):
        return self.base.hydrostatic_reference_density_kg_m3

    def _idx(self, i: int, j: int, k: int) -> int:
        return self.base._idx(i, j, k)

    def _ijk(self, q: int) -> tuple[int, int, int]:
        return self.base._ijk(q)

    def cell_center(self, i: int, j: int, k: int) -> Vec3:
        return self.base.cell_center(i, j, k)

    def level_grids(self) -> list[EulerianGasGrid]:
        return [level.grid for level in self.levels]

    @staticmethod
    def _sample_scalar(grid: EulerianGasGrid, field: list[float], p: Vec3) -> float:
        return sum(weight * field[q] for q, weight in grid._weights(p))

    def _point_in_grid(self, p: Vec3, grid: EulerianGasGrid) -> bool:
        for x, origin, extent in zip(p, grid.config.origin_m, grid.config.extent_m):
            if x < origin or x >= origin + extent:
                return False
        return True

    def _distance_to_fronts(self, p: Vec3, fronts: Iterable[FilmFront], limit: float) -> float:
        best = float("inf")
        for front in fronts:
            lo, hi = _front_bounds(front)
            if (
                p[0] < lo[0] - limit or p[0] > hi[0] + limit
                or p[1] < lo[1] - limit or p[1] > hi[1] + limit
                or p[2] < lo[2] - limit or p[2] > hi[2] + limit
            ):
                continue
            for ia, ib, ic in front.faces:
                d = point_triangle_distance(
                    p, front.vertices[ia], front.vertices[ib], front.vertices[ic]
                )
                if d < best:
                    best = d
                    if best <= limit:
                        return best
        return best

    def _expand_axis(self, lo: int, hi: int, n: int) -> tuple[int, int]:
        target = self.amr_config.min_patch_parent_cells
        while hi - lo < target:
            if lo > 0:
                lo -= 1
            elif hi < n:
                hi += 1
            else:
                break
            if hi - lo < target and hi < n:
                hi += 1
        return lo, hi

    def _patch_bounds(
        self, parent: EulerianGasGrid, fronts: list[FilmFront]
    ) -> tuple[int, int, int, int, int, int] | None:
        threshold = (
            self.amr_config.front_band_cells + 0.5 * math.sqrt(3.0)
        ) * parent.h
        marked: list[tuple[int, int, int]] = []
        for k in range(parent.nz):
            for j in range(parent.ny):
                for i in range(parent.nx):
                    p = parent.cell_center(i, j, k)
                    if self._distance_to_fronts(p, fronts, threshold) <= threshold:
                        marked.append((i, j, k))
        if not marked:
            return None
        i0 = min(x[0] for x in marked)
        i1 = max(x[0] for x in marked) + 1
        j0 = min(x[1] for x in marked)
        j1 = max(x[1] for x in marked) + 1
        k0 = min(x[2] for x in marked)
        k1 = max(x[2] for x in marked) + 1
        i0, i1 = self._expand_axis(i0, i1, parent.nx)
        j0, j1 = self._expand_axis(j0, j1, parent.ny)
        k0, k1 = self._expand_axis(k0, k1, parent.nz)
        return (i0, i1, j0, j1, k0, k1)

    def _child_config(
        self, parent: EulerianGasGrid, bounds: tuple[int, int, int, int, int, int]
    ) -> GridConfig:
        i0, i1, j0, j1, k0, k1 = bounds
        ratio = self.amr_config.refinement_ratio
        ox, oy, oz = parent.config.origin_m
        origin = (ox + i0 * parent.h, oy + j0 * parent.h, oz + k0 * parent.h)
        extent = (
            (i1 - i0) * parent.h,
            (j1 - j0) * parent.h,
            (k1 - k0) * parent.h,
        )
        return GridConfig(
            cells=((i1 - i0) * ratio, (j1 - j0) * ratio, (k1 - k0) * ratio),
            origin_m=origin,
            extent_m=extent,
            density_kg_m3=parent.config.density_kg_m3,
            dynamic_viscosity_pa_s=parent.config.dynamic_viscosity_pa_s,
            background_velocity_m_s=parent.config.background_velocity_m_s,
            pressure_iterations=parent.config.pressure_iterations,
            pressure_tolerance_s_inv=parent.config.pressure_tolerance_s_inv,
        )

    def _same_grid(self, grid: EulerianGasGrid, config: GridConfig) -> bool:
        return grid.config == config

    def _prolong_parent_to_child(
        self, parent: EulerianGasGrid, child: EulerianGasGrid, boundary_only: bool = False
    ) -> None:
        shell = self.amr_config.boundary_fill_cells
        for q in range(len(child.u)):
            i, j, k = child._ijk(q)
            if boundary_only and not (
                i < shell or j < shell or k < shell
                or i >= child.nx - shell
                or j >= child.ny - shell
                or k >= child.nz - shell
            ):
                continue
            p = child.cell_center(i, j, k)
            vel = parent.sample_dynamic_velocity(p)
            child.u[q], child.v[q], child.w[q] = vel
            child.pressure[q] = self._sample_scalar(parent, parent.pressure, p)

    def _restrict_child_to_parent(self, level_index: int) -> None:
        level = self.levels[level_index]
        if level_index <= 0 or level.parent_bounds is None:
            return
        child = level.grid
        parent = self.levels[level_index - 1].grid
        i0, i1, j0, j1, k0, k1 = level.parent_bounds
        r = self.amr_config.refinement_ratio
        inv_count = 1.0 / float(r ** 3)
        for pk in range(k0, k1):
            for pj in range(j0, j1):
                for pi in range(i0, i1):
                    sums = [0.0, 0.0, 0.0, 0.0]
                    ci0 = (pi - i0) * r
                    cj0 = (pj - j0) * r
                    ck0 = (pk - k0) * r
                    for dk in range(r):
                        for dj in range(r):
                            for di in range(r):
                                cq = child._idx(ci0 + di, cj0 + dj, ck0 + dk)
                                sums[0] += child.u[cq]
                                sums[1] += child.v[cq]
                                sums[2] += child.w[cq]
                                sums[3] += child.pressure[cq]
                    pq = parent._idx(pi, pj, pk)
                    parent.u[pq] = sums[0] * inv_count
                    parent.v[pq] = sums[1] * inv_count
                    parent.w[pq] = sums[2] * inv_count
                    parent.pressure[pq] = sums[3] * inv_count

    def regrid(self, fronts: list[FilmFront]) -> None:
        desired: list[AMRLevel] = [self.levels[0]]
        parent = desired[0].grid
        for level_number in range(1, self.amr_config.max_levels + 1):
            bounds = self._patch_bounds(parent, fronts)
            if bounds is None:
                break
            config = self._child_config(parent, bounds)
            old = self.levels[level_number] if level_number < len(self.levels) else None
            if old is not None and old.parent_bounds == bounds and self._same_grid(old.grid, config):
                child = old.grid
            else:
                child = EulerianGasGrid(config)
                self._prolong_parent_to_child(parent, child, boundary_only=False)
            desired.append(AMRLevel(level_number, child, bounds))
            parent = child
        self.levels = desired

    def prolong_all(self) -> None:
        for idx in range(1, len(self.levels)):
            self._prolong_parent_to_child(
                self.levels[idx - 1].grid,
                self.levels[idx].grid,
                boundary_only=False,
            )

    def restrict_all(self) -> None:
        for idx in range(len(self.levels) - 1, 0, -1):
            self._restrict_child_to_parent(idx)

    def sample_dynamic_velocity(self, p: Vec3, fields=None) -> Vec3:
        if fields is not None:
            return self.base.sample_dynamic_velocity(p, fields)
        for level in reversed(self.levels):
            if self._point_in_grid(p, level.grid):
                return level.grid.sample_dynamic_velocity(p)
        return self.base.sample_dynamic_velocity(p)

    def sample_velocity(self, p: Vec3, fields=None) -> Vec3:
        if fields is not None:
            return self.base.sample_velocity(p, fields)
        dyn = self.sample_dynamic_velocity(p)
        bg = self.config.background_velocity_m_s
        return (dyn[0] + bg[0], dyn[1] + bg[1], dyn[2] + bg[2])

    def spread_vertex_forces(self, points, forces):
        return self.base.spread_vertex_forces(points, forces)

    def total_integrated_force(self, force_density):
        return self.base.total_integrated_force(force_density)

    def _covered_by_child(self, level_index: int, i: int, j: int, k: int) -> bool:
        child_index = level_index + 1
        if child_index >= len(self.levels):
            return False
        bounds = self.levels[child_index].parent_bounds
        if bounds is None:
            return False
        i0, i1, j0, j1, k0, k1 = bounds
        return i0 <= i < i1 and j0 <= j < j1 and k0 <= k < k1

    def _active_indices(self, level_index: int):
        grid = self.levels[level_index].grid
        for q in range(len(grid.u)):
            i, j, k = grid._ijk(q)
            if not self._covered_by_child(level_index, i, j, k):
                yield q

    def active_cell_counts_by_level(self) -> dict[str, int]:
        return {
            str(level.level): sum(1 for _ in self._active_indices(idx))
            for idx, level in enumerate(self.levels)
        }

    def active_cell_count(self) -> int:
        return sum(self.active_cell_counts_by_level().values())

    def hierarchy_signature(self) -> tuple:
        return tuple(
            (
                level.level,
                tuple(float(x) for x in level.grid.config.origin_m),
                tuple(float(x) for x in level.grid.config.extent_m),
                tuple(level.grid.config.cells),
                float(level.grid.h),
                level.parent_bounds,
            )
            for level in self.levels
        )

    def state_signature(self) -> tuple:
        return (
            self.hierarchy_signature(),
            tuple(
                (
                    tuple(level.grid.u),
                    tuple(level.grid.v),
                    tuple(level.grid.w),
                    tuple(level.grid.pressure),
                    tuple(level.grid.region_labels),
                )
                for level in self.levels
            ),
        )

    def minimum_density(self) -> float:
        return min(min(level.grid.density) for level in self.levels)

    def maximum_kinematic_viscosity(self) -> float:
        best = 0.0
        for level in self.levels:
            for mu, rho in zip(level.grid.dynamic_viscosity, level.grid.density):
                best = max(best, mu / rho)
        return best

    def divergence_linf(self) -> float:
        return max(
            (max((abs(x) for x in level.grid.divergence()), default=0.0) for level in self.levels),
            default=0.0,
        )

    def max_speed(self) -> float:
        return max((level.grid.max_speed() for level in self.levels), default=0.0)

    def kinetic_energy(self) -> float:
        bg = self.config.background_velocity_m_s
        total = 0.0
        for idx, level in enumerate(self.levels):
            g = level.grid
            vol = g.cell_volume
            for q in self._active_indices(idx):
                total += 0.5 * g.density[q] * (
                    (g.u[q] + bg[0]) ** 2
                    + (g.v[q] + bg[1]) ** 2
                    + (g.w[q] + bg[2]) ** 2
                ) * vol
        return total

    def pressure_jump(self, region_label: str, physical: bool = False) -> float:
        """Return a gauge-invariant region/exterior jump on the finest useful level.

        Each nested projection fixes its own arbitrary constant pressure gauge.
        Mixing absolute pressures across levels would therefore contaminate a
        pressure difference.  The film jump is local, so evaluate it on the
        finest level containing cells on both sides of the interface.
        """
        for level in reversed(self.levels):
            labels = level.grid.region_labels
            if region_label in labels and "EXTERIOR" in labels:
                return (
                    level.grid.mean_pressure(region_label, physical=physical)
                    - level.grid.mean_pressure("EXTERIOR", physical=physical)
                )
        raise ValueError(
            f"region {region_label!r} and EXTERIOR do not coexist on an AMR level"
        )

    def mean_pressure(self, region_label: str, physical: bool = True) -> float:
        weighted = 0.0
        volume = 0.0
        for idx, level in enumerate(self.levels):
            g = level.grid
            field = g.physical_pressure_field() if physical else g.pressure
            cell_volume = g.cell_volume
            for q in self._active_indices(idx):
                if g.region_labels[q] == region_label:
                    weighted += field[q] * cell_volume
                    volume += cell_volume
        if volume <= 0.0:
            raise ValueError(f"region {region_label!r} has no active AMR cells")
        return weighted / volume

    def region_volume(self, region_label: str) -> float:
        total = 0.0
        for idx, level in enumerate(self.levels):
            g = level.grid
            total += sum(
                g.cell_volume
                for q in self._active_indices(idx)
                if g.region_labels[q] == region_label
            )
        return total

    def composite_region_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for idx, level in enumerate(self.levels):
            g = level.grid
            for q in self._active_indices(idx):
                label = g.region_labels[q]
                counts[label] = counts.get(label, 0) + 1
        return counts

    def physical_pressure_field(self) -> list[float]:
        return self.base.physical_pressure_field()

    def advance(
        self,
        dt: float,
        force_density,
        gravity_m_s2: Vec3,
        hydrostatic_reference_density_kg_m3: float | None = None,
    ) -> None:
        for idx, level in enumerate(self.levels):
            grid = level.grid
            if idx > 0:
                self._prolong_parent_to_child(
                    self.levels[idx - 1].grid, grid, boundary_only=True
                )
            if idx == 0:
                local_force = force_density
            else:
                n = len(grid.u)
                local_force = ([0.0] * n, [0.0] * n, [0.0] * n)
            grid.advance(
                dt,
                local_force,
                gravity_m_s2,
                hydrostatic_reference_density_kg_m3=hydrostatic_reference_density_kg_m3,
            )
        self.restrict_all()

    def diagnostics(self) -> dict[str, object]:
        return {
            "enabled": True,
            "levels": len(self.levels),
            "max_refinement_level": len(self.levels) - 1,
            "refinement_ratio": self.amr_config.refinement_ratio,
            "front_band_cells": self.amr_config.front_band_cells,
            "active_cells_by_level": self.active_cell_counts_by_level(),
            "active_cell_count": self.active_cell_count(),
            "base_cell_size_m": self.base.h,
            "finest_cell_size_m": self.finest.h,
            "criterion": "triangle-distance band on parent cell centers",
            "transfer": {
                "velocity": "trilinear prolongation; volume-average restriction",
                "pressure": "trilinear prolongation; volume-average restriction",
                "density_viscosity_region_jump": "recomputed from tracked geometry",
            },
            "coarse_fine_interface": "one-fine-cell parent fill plus fine-to-parent correction",
        }
