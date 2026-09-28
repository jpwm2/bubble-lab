"""Deterministic geometry primitives for production fragmentation topology surgery."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
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
    inv = 1.0 / len(pts)
    return (
        math.fsum(p[0] for p in pts) * inv,
        math.fsum(p[1] for p in pts) * inv,
        math.fsum(p[2] for p in pts) * inv,
    )


def _finite_vec3(value: Iterable[float], name: str) -> Vec3:
    vals = tuple(float(v) for v in value)
    if len(vals) != 3 or any(not math.isfinite(v) for v in vals):
        raise ValueError(f"{name} must contain three finite values")
    return vals  # type: ignore[return-value]


@dataclass(frozen=True)
class TriMesh:
    vertices: tuple[Vec3, ...]
    faces: tuple[Face, ...]

    def __post_init__(self) -> None:
        if len(self.vertices) < 4 or len(self.faces) < 4:
            raise ValueError("triangular closed surface requires at least four vertices/faces")
        for p in self.vertices:
            _finite_vec3(p, "vertex")
        n = len(self.vertices)
        for face in self.faces:
            if len(face) != 3 or len(set(face)) != 3:
                raise ValueError("faces must contain three distinct indices")
            if any(i < 0 or i >= n for i in face):
                raise ValueError("face index out of range")

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
        edges = self.edge_counts()
        if not edges:
            return 0.0
        return math.fsum(norm(sub(self.vertices[a], self.vertices[b])) for a, b in edges) / len(edges)

    def edge_counts(self) -> dict[tuple[int, int], int]:
        counts: dict[tuple[int, int], int] = {}
        for a, b, c in self.faces:
            for i, j in ((a, b), (b, c), (c, a)):
                edge = (i, j) if i < j else (j, i)
                counts[edge] = counts.get(edge, 0) + 1
        return counts

    def oriented_edge_balance(self) -> dict[tuple[int, int], int]:
        balance: dict[tuple[int, int], int] = {}
        for a, b, c in self.faces:
            for i, j in ((a, b), (b, c), (c, a)):
                key = (i, j) if i < j else (j, i)
                balance[key] = balance.get(key, 0) + (1 if i < j else -1)
        return balance

    def is_closed_manifold(self) -> bool:
        counts = self.edge_counts()
        return bool(counts) and all(count == 2 for count in counts.values()) and all(
            value == 0 for value in self.oriented_edge_balance().values()
        )

    def reoriented_outward(self) -> "TriMesh":
        if self.signed_volume() >= 0.0:
            return self
        return TriMesh(self.vertices, tuple((a, c, b) for a, b, c in self.faces))

    def digest(self) -> str:
        payload = {
            "vertices": [[float(c).hex() for c in p] for p in self.vertices],
            "faces": [list(face) for face in self.faces],
        }
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("ascii")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _oriented(vertices: list[Vec3], faces: list[Face]) -> TriMesh:
    return TriMesh(tuple(vertices), tuple(faces)).reoriented_outward()


def _surface_of_revolution(
    radius_at_x: Callable[[float], float],
    half_length: float,
    axial_segments: int,
    circum_segments: int,
) -> TriMesh:
    if half_length <= 0.0:
        raise ValueError("half_length must be positive")
    if axial_segments < 6 or circum_segments < 12:
        raise ValueError("mesh resolution is too small")
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
    *, half_length: float = 1.8, minor_radius: float = 1.0,
    axial_segments: int = 24, circum_segments: int = 36,
) -> TriMesh:
    def profile(x: float) -> float:
        q = x / half_length
        return minor_radius * math.sqrt(max(0.0, 1.0 - q * q))
    return _surface_of_revolution(profile, half_length, axial_segments, circum_segments)


def necked_mesh(
    *, half_length: float = 1.8, minor_radius: float = 1.0,
    neck_depth: float = 0.58, neck_width: float = 0.48, asymmetry: float = 0.10,
    axial_segments: int = 24, circum_segments: int = 36,
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
        return add(add(mul(v, c), mul(cross(k, v), s)), mul(k, dot(k, v) * (1.0 - c)))
    return TriMesh(tuple(rotate(v) for v in mesh.vertices), mesh.faces)
