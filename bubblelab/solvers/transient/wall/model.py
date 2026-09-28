"""Resolved SDF no-slip wall geometry for the transient Eulerian gas grid."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from ...boundary import SolidBoundary

Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class WallIntersection:
    """A fluid-cell-to-solid segment crossing an authoritative SDF wall."""

    distance_fraction: float
    boundary_id: str
    wall_velocity_dynamic_m_s: Vec3


class ResolvedNoSlipWallField:
    """Grid-local resolved wall geometry derived from accepted SDF boundaries.

    Cell centers with any non-positive boundary SDF are solid. Fluid-to-solid
    stencil legs are cut at the first SDF zero crossing. The stored Eulerian
    velocity is dynamic (background wind is added only when sampled), therefore
    declared physical wall velocities are converted to dynamic values here.
    """

    _MIN_DISTANCE_FRACTION = 0.10

    def __init__(self, grid: Any, boundaries: Iterable[SolidBoundary]):
        self.grid = grid
        self.boundaries = tuple(sorted(boundaries, key=lambda b: b.boundary_id))
        if not self.boundaries:
            raise ValueError("resolved wall field requires at least one boundary")
        self._solid: list[bool] = []
        self._owner: list[SolidBoundary | None] = []
        for q in range(grid.nx * grid.ny * grid.nz):
            point = grid.cell_center(*grid._ijk(q))
            signed = [(b.signed_distance(point), b) for b in self.boundaries]
            solid = any(distance <= 0.0 for distance, _ in signed)
            self._solid.append(solid)
            if solid:
                self._owner.append(
                    min(signed, key=lambda item: (abs(item[0]), item[1].boundary_id))[1]
                )
            else:
                self._owner.append(None)
        self._crossing_cache: dict[tuple[int, int, int], WallIntersection | None] = {}

    @property
    def fluid_indices(self) -> tuple[int, ...]:
        return tuple(q for q, solid in enumerate(self._solid) if not solid)

    @property
    def solid_cell_count(self) -> int:
        return sum(self._solid)

    def is_solid(self, q: int) -> bool:
        return self._solid[q]

    def point_is_solid(self, point_m: Vec3) -> bool:
        return any(
            boundary.signed_distance(point_m) <= 0.0 for boundary in self.boundaries
        )

    def _dynamic_velocity(self, boundary: SolidBoundary) -> Vec3:
        background = self.grid.config.background_velocity_m_s
        physical = boundary.wall_velocity_m_s
        return (
            physical[0] - background[0],
            physical[1] - background[1],
            physical[2] - background[2],
        )

    def dynamic_wall_velocity_at(self, point_m: Vec3) -> Vec3:
        boundary = min(
            self.boundaries,
            key=lambda item: (abs(item.signed_distance(point_m)), item.boundary_id),
        )
        return self._dynamic_velocity(boundary)

    def dynamic_wall_velocity_for_cell(self, q: int) -> Vec3:
        owner = self._owner[q]
        if owner is None:
            point = self.grid.cell_center(*self.grid._ijk(q))
            return self.dynamic_wall_velocity_at(point)
        return self._dynamic_velocity(owner)

    def intersection(self, q: int, axis: int, offset: int) -> WallIntersection | None:
        """Return the first SDF wall crossed from fluid cell ``q`` along one axis."""
        if offset not in (-1, 1):
            raise ValueError("wall stencil offset must be +/-1")
        key = (q, axis, offset)
        if key in self._crossing_cache:
            return self._crossing_cache[key]
        if self._solid[q]:
            self._crossing_cache[key] = None
            return None

        p0 = self.grid.cell_center(*self.grid._ijk(q))
        p1_list = list(p0)
        p1_list[axis] += offset * self.grid.h
        p1 = (p1_list[0], p1_list[1], p1_list[2])
        candidates: list[tuple[float, str, SolidBoundary]] = []
        for boundary in self.boundaries:
            d0 = boundary.signed_distance(p0)
            d1 = boundary.signed_distance(p1)
            if d0 > 0.0 and d1 <= 0.0:
                denom = d0 - d1
                fraction = d0 / denom if denom > 0.0 else 1.0
                candidates.append((fraction, boundary.boundary_id, boundary))
        if not candidates:
            self._crossing_cache[key] = None
            return None
        fraction, boundary_id, boundary = min(
            candidates, key=lambda item: (item[0], item[1])
        )
        crossing = WallIntersection(
            distance_fraction=max(
                self._MIN_DISTANCE_FRACTION, min(1.0, fraction)
            ),
            boundary_id=boundary_id,
            wall_velocity_dynamic_m_s=self._dynamic_velocity(boundary),
        )
        self._crossing_cache[key] = crossing
        return crossing

    def blocks_positive_face(self, q: int, axis: int) -> bool:
        if self._solid[q]:
            return True
        return self.intersection(q, axis, 1) is not None

    def enforce_velocity(
        self, fields: tuple[list[float], list[float], list[float]]
    ) -> None:
        """Install wall velocity in solid storage and normal velocity on cut faces."""
        u, v, w = fields
        components = (u, v, w)
        for q, solid in enumerate(self._solid):
            if solid:
                velocity = self.dynamic_wall_velocity_for_cell(q)
                u[q], v[q], w[q] = velocity

        # Positive-face storage means a negative face belongs to the -1 neighbor.
        assignments: dict[tuple[int, int], tuple[str, float]] = {}
        for q in self.fluid_indices:
            for axis in range(3):
                for offset in (-1, 1):
                    crossing = self.intersection(q, axis, offset)
                    if crossing is None:
                        continue
                    slot = q if offset == 1 else self.grid._face_neighbor(q, axis, -1)
                    key = (axis, slot)
                    candidate = (
                        crossing.boundary_id,
                        crossing.wall_velocity_dynamic_m_s[axis],
                    )
                    previous = assignments.get(key)
                    if previous is None or candidate[0] < previous[0]:
                        assignments[key] = candidate
        for (axis, slot), (_, value) in assignments.items():
            components[axis][slot] = value
