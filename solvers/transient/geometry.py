"""Lagrangian soap-film geometry for the transient reference backend.

The mesh is an oriented, zero-thickness film sheet.  It represents bubble-scale
film geometry only; finite film thickness is deliberately not represented here.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

Vec3 = tuple[float, float, float]
Face = tuple[int, int, int]


def add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def mul(a: Vec3, s: float) -> Vec3:
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def norm(a: Vec3) -> float:
    return math.sqrt(dot(a, a))


def unit(a: Vec3) -> Vec3:
    n = norm(a)
    if n == 0.0:
        return (0.0, 0.0, 0.0)
    return mul(a, 1.0 / n)


def mean(points: Iterable[Vec3]) -> Vec3:
    pts = list(points)
    if not pts:
        return (0.0, 0.0, 0.0)
    inv = 1.0 / len(pts)
    return (
        sum(p[0] for p in pts) * inv,
        sum(p[1] for p in pts) * inv,
        sum(p[2] for p in pts) * inv,
    )


@dataclass
class FilmFront:
    """An oriented closed film sheet with stable region identity."""

    bubble_id: str
    mesh_id: str
    film_id: str
    vertices: list[Vec3]
    faces: list[Face]
    surface_tension_n_m: float
    target_volume_m3: float | None = None

    def __post_init__(self) -> None:
        if not self.vertices or not self.faces:
            raise ValueError("film front requires vertices and faces")
        if self.surface_tension_n_m < 0.0:
            raise ValueError("surface tension must be non-negative")
        self._orient_outward()
        if self.target_volume_m3 is None:
            self.target_volume_m3 = self.volume()
        if self.target_volume_m3 <= 0.0:
            raise ValueError("closed film volume must be positive")

    def clone(self) -> "FilmFront":
        return FilmFront(
            bubble_id=self.bubble_id,
            mesh_id=self.mesh_id,
            film_id=self.film_id,
            vertices=list(self.vertices),
            faces=list(self.faces),
            surface_tension_n_m=self.surface_tension_n_m,
            target_volume_m3=self.target_volume_m3,
        )

    def _orient_outward(self) -> None:
        c = mean(self.vertices)
        oriented: list[Face] = []
        for i, j, k in self.faces:
            a, b, d = self.vertices[i], self.vertices[j], self.vertices[k]
            n = cross(sub(b, a), sub(d, a))
            fc = mul(add(add(a, b), d), 1.0 / 3.0)
            if dot(n, sub(fc, c)) < 0.0:
                oriented.append((i, k, j))
            else:
                oriented.append((i, j, k))
        self.faces = oriented

    def centroid(self) -> Vec3:
        """Area-weighted surface centroid, adequate for closed-sheet diagnostics."""
        total = 0.0
        accum = (0.0, 0.0, 0.0)
        for i, j, k in self.faces:
            a, b, c = self.vertices[i], self.vertices[j], self.vertices[k]
            area = 0.5 * norm(cross(sub(b, a), sub(c, a)))
            fc = mul(add(add(a, b), c), 1.0 / 3.0)
            accum = add(accum, mul(fc, area))
            total += area
        return mul(accum, 1.0 / total) if total > 0.0 else mean(self.vertices)

    def area(self) -> float:
        total = 0.0
        for i, j, k in self.faces:
            a, b, c = self.vertices[i], self.vertices[j], self.vertices[k]
            total += 0.5 * norm(cross(sub(b, a), sub(c, a)))
        return total

    def signed_volume(self) -> float:
        vol6 = 0.0
        for i, j, k in self.faces:
            a, b, c = self.vertices[i], self.vertices[j], self.vertices[k]
            vol6 += dot(a, cross(b, c))
        return vol6 / 6.0

    def volume(self) -> float:
        return abs(self.signed_volume())

    def equivalent_radius(self) -> float:
        return (3.0 * self.volume() / (4.0 * math.pi)) ** (1.0 / 3.0)

    def mean_edge_length(self) -> float:
        seen: set[tuple[int, int]] = set()
        lengths: list[float] = []
        for face in self.faces:
            for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
                edge = (a, b) if a < b else (b, a)
                if edge not in seen:
                    seen.add(edge)
                    lengths.append(norm(sub(self.vertices[a], self.vertices[b])))
        return sum(lengths) / len(lengths)

    def edge_length_bounds(self) -> tuple[float, float]:
        seen: set[tuple[int, int]] = set()
        lengths: list[float] = []
        for face in self.faces:
            for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
                edge = (a, b) if a < b else (b, a)
                if edge not in seen:
                    seen.add(edge)
                    lengths.append(norm(sub(self.vertices[a], self.vertices[b])))
        return min(lengths), max(lengths)

    def capillary_vertex_forces(self) -> list[Vec3]:
        """Return -sigma*dA/dx at vertices, the discrete area first variation.

        These integrated nodal forces have units of newtons and sum to zero for a
        closed surface up to floating-point roundoff.  This is an energy-consistent
        constant-tension capillary discretization for the piecewise-linear front.
        """
        forces = [(0.0, 0.0, 0.0) for _ in self.vertices]
        sigma = self.surface_tension_n_m
        for i, j, k in self.faces:
            a, b, c = self.vertices[i], self.vertices[j], self.vertices[k]
            raw_n = cross(sub(b, a), sub(c, a))
            raw_norm = norm(raw_n)
            if raw_norm == 0.0:
                continue
            n = mul(raw_n, 1.0 / raw_norm)
            grad_a = mul(cross(sub(b, c), n), 0.5)
            grad_b = mul(cross(sub(c, a), n), 0.5)
            grad_c = mul(cross(sub(a, b), n), 0.5)
            for idx, grad in ((i, grad_a), (j, grad_b), (k, grad_c)):
                forces[idx] = add(forces[idx], mul(grad, -sigma))
        return forces

    def normal_curvature_vectors(self) -> list[Vec3]:
        """Area-gradient mean-curvature vector estimate at vertices.

        The vector is defined so that sigma * kappa*n * A_dual equals the
        negative area gradient force.  It is intended for diagnostics and future
        sharp-interface adapters; the capillary force itself uses the area gradient.
        """
        dual_area = [0.0 for _ in self.vertices]
        forces = self.capillary_vertex_forces()
        for i, j, k in self.faces:
            a, b, c = self.vertices[i], self.vertices[j], self.vertices[k]
            area = 0.5 * norm(cross(sub(b, a), sub(c, a)))
            share = area / 3.0
            dual_area[i] += share
            dual_area[j] += share
            dual_area[k] += share
        sigma = self.surface_tension_n_m
        out: list[Vec3] = []
        for area, force in zip(dual_area, forces):
            if sigma == 0.0 or area == 0.0:
                out.append((0.0, 0.0, 0.0))
            else:
                out.append(mul(force, 1.0 / (sigma * area)))
        return out

    def advect(self, velocity_at, dt: float) -> None:
        """Second-order midpoint advection by an interpolated Eulerian velocity."""
        moved: list[Vec3] = []
        for x in self.vertices:
            u0 = velocity_at(x)
            mid = add(x, mul(u0, 0.5 * dt))
            u_mid = velocity_at(mid)
            moved.append(add(x, mul(u_mid, dt)))
        self.vertices = moved

    def project_volume(self) -> float:
        """Globally correct closed-front volume while preserving shape directions.

        The correction is a deterministic conservative front projection used by
        this foundation backend because the compact reference grid does not yet
        implement a locally conservative cut-cell advection scheme.  The returned
        value is the relative pre-correction volume error.
        """
        target = float(self.target_volume_m3)
        current = self.volume()
        if current <= 0.0:
            raise ValueError("front volume collapsed")
        rel = abs(current - target) / target
        scale = (target / current) ** (1.0 / 3.0)
        c = self.centroid()
        self.vertices = [add(c, mul(sub(v, c), scale)) for v in self.vertices]
        return rel


def icosphere(
    radius_m: float = 0.01,
    center_m: Vec3 = (0.0, 0.0, 0.0),
    subdivisions: int = 1,
    bubble_id: str = "bubble-1",
    surface_tension_n_m: float = 0.05,
) -> FilmFront:
    """Build a deterministic outward-oriented icosphere film front."""
    if radius_m <= 0.0:
        raise ValueError("radius must be positive")
    if subdivisions < 0:
        raise ValueError("subdivisions must be non-negative")
    phi = (1.0 + math.sqrt(5.0)) / 2.0
    raw = [
        (-1, phi, 0), (1, phi, 0), (-1, -phi, 0), (1, -phi, 0),
        (0, -1, phi), (0, 1, phi), (0, -1, -phi), (0, 1, -phi),
        (phi, 0, -1), (phi, 0, 1), (-phi, 0, -1), (-phi, 0, 1),
    ]
    vertices: list[Vec3] = [add(center_m, mul(unit((float(x), float(y), float(z))), radius_m)) for x, y, z in raw]
    faces: list[Face] = [
        (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
        (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
        (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
        (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1),
    ]

    for _ in range(subdivisions):
        cache: dict[tuple[int, int], int] = {}

        def midpoint(i: int, j: int) -> int:
            key = (i, j) if i < j else (j, i)
            if key in cache:
                return cache[key]
            p = mul(add(vertices[i], vertices[j]), 0.5)
            direction = unit(sub(p, center_m))
            vertices.append(add(center_m, mul(direction, radius_m)))
            idx = len(vertices) - 1
            cache[key] = idx
            return idx

        refined: list[Face] = []
        for a, b, c in faces:
            ab, bc, ca = midpoint(a, b), midpoint(b, c), midpoint(c, a)
            refined.extend(((a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)))
        faces = refined

    return FilmFront(
        bubble_id=bubble_id,
        mesh_id=f"mesh-{bubble_id}",
        film_id=f"film-{bubble_id}",
        vertices=vertices,
        faces=faces,
        surface_tension_n_m=surface_tension_n_m,
    )
