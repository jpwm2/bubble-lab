"""Small deterministic geometry helpers for fragmentation research benchmarks."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Iterable

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
    if n <= 1.0e-300:
        raise ValueError("zero-length vector")
    return mul(a, 1.0 / n)


def mean(points: Iterable[Vec3]) -> Vec3:
    pts = list(points)
    if not pts:
        return (0.0, 0.0, 0.0)
    inv = 1.0 / float(len(pts))
    return (
        math.fsum(p[0] for p in pts) * inv,
        math.fsum(p[1] for p in pts) * inv,
        math.fsum(p[2] for p in pts) * inv,
    )


@dataclass(frozen=True)
class TriMesh:
    vertices: tuple[Vec3, ...]
    faces: tuple[Face, ...]

    def signed_volume(self) -> float:
        return math.fsum(
            dot(self.vertices[i], cross(self.vertices[j], self.vertices[k])) / 6.0
            for i, j, k in self.faces
        )

    def volume(self) -> float:
        return abs(self.signed_volume())

    def volume_centroid(self) -> Vec3:
        signed = self.signed_volume()
        if abs(signed) <= 1.0e-300:
            return mean(self.vertices)
        accum = [0.0, 0.0, 0.0]
        for i, j, k in self.faces:
            a, b, c = self.vertices[i], self.vertices[j], self.vertices[k]
            tetra = dot(a, cross(b, c)) / 6.0
            for axis in range(3):
                accum[axis] += tetra * (a[axis] + b[axis] + c[axis]) / 4.0
        return (accum[0] / signed, accum[1] / signed, accum[2] / signed)

    def mean_edge_length(self) -> float:
        edges: set[tuple[int, int]] = set()
        for a, b, c in self.faces:
            for i, j in ((a, b), (b, c), (c, a)):
                edges.add((i, j) if i < j else (j, i))
        if not edges:
            return 0.0
        return math.fsum(norm(sub(self.vertices[a], self.vertices[b])) for a, b in edges) / len(edges)


def _oriented(vertices: list[Vec3], faces: list[Face]) -> TriMesh:
    mesh = TriMesh(tuple(vertices), tuple(faces))
    if mesh.signed_volume() < 0.0:
        mesh = TriMesh(mesh.vertices, tuple((a, c, b) for a, b, c in mesh.faces))
    return mesh


def _surface_of_revolution(
    radius_at_x: Callable[[float], float],
    half_length: float,
    axial_segments: int,
    circum_segments: int,
) -> TriMesh:
    if half_length <= 0.0:
        raise ValueError("half_length must be positive")
    if axial_segments < 6 or circum_segments < 12:
        raise ValueError("benchmark mesh resolution is too small")

    vertices: list[Vec3] = [(-half_length, 0.0, 0.0)]
    rings: list[list[int]] = []
    for i in range(1, axial_segments):
        x = -half_length + 2.0 * half_length * i / axial_segments
        radius = radius_at_x(x)
        if radius <= 0.0:
            raise ValueError("interior profile radius must be positive")
        ring: list[int] = []
        for j in range(circum_segments):
            angle = 2.0 * math.pi * j / circum_segments
            ring.append(len(vertices))
            vertices.append((x, radius * math.cos(angle), radius * math.sin(angle)))
        rings.append(ring)
    right_pole = len(vertices)
    vertices.append((half_length, 0.0, 0.0))

    faces: list[Face] = []
    first = rings[0]
    for j in range(circum_segments):
        k = (j + 1) % circum_segments
        faces.append((0, first[k], first[j]))

    for left, right in zip(rings[:-1], rings[1:]):
        for j in range(circum_segments):
            k = (j + 1) % circum_segments
            faces.append((left[j], left[k], right[k]))
            faces.append((left[j], right[k], right[j]))

    last = rings[-1]
    for j in range(circum_segments):
        k = (j + 1) % circum_segments
        faces.append((last[j], last[k], right_pole))
    return _oriented(vertices, faces)


def ellipsoid_mesh(
    *,
    half_length: float = 1.8,
    minor_radius: float = 1.0,
    axial_segments: int = 24,
    circum_segments: int = 36,
) -> TriMesh:
    def profile(x: float) -> float:
        q = x / half_length
        return minor_radius * math.sqrt(max(0.0, 1.0 - q * q))

    return _surface_of_revolution(profile, half_length, axial_segments, circum_segments)


def necked_mesh(
    *,
    half_length: float = 1.8,
    minor_radius: float = 1.0,
    neck_depth: float = 0.58,
    neck_width: float = 0.48,
    asymmetry: float = 0.10,
    axial_segments: int = 24,
    circum_segments: int = 36,
) -> TriMesh:
    if not 0.0 < neck_depth < 0.9:
        raise ValueError("neck_depth must lie in (0, 0.9)")
    if neck_width <= 0.0:
        raise ValueError("neck_width must be positive")

    def profile(x: float) -> float:
        q = x / half_length
        base = minor_radius * math.sqrt(max(0.0, 1.0 - q * q))
        throat = 1.0 - neck_depth * math.exp(-((x / neck_width) ** 2))
        skew = 1.0 + asymmetry * q
        return base * throat * skew

    return _surface_of_revolution(profile, half_length, axial_segments, circum_segments)


def rotate_mesh(mesh: TriMesh, axis: Vec3, angle_rad: float) -> TriMesh:
    k = unit(axis)
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)

    def rotate(v: Vec3) -> Vec3:
        term1 = mul(v, c)
        term2 = mul(cross(k, v), s)
        term3 = mul(k, dot(k, v) * (1.0 - c))
        return add(add(term1, term2), term3)

    return TriMesh(tuple(rotate(v) for v in mesh.vertices), mesh.faces)
