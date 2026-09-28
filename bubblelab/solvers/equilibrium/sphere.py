"""Deterministic icosphere generation and scalar sphere relations."""
from __future__ import annotations

import math

from .mesh import SurfaceMesh
from .vector import Vec3, add, norm, scale


def radius_from_volume(volume_m3: float) -> float:
    if volume_m3 <= 0.0:
        raise ValueError("volume must be positive")
    return (3.0 * volume_m3 / (4.0 * math.pi)) ** (1.0 / 3.0)


def sphere_area(radius_m: float) -> float:
    return 4.0 * math.pi * radius_m * radius_m


def sphere_volume(radius_m: float) -> float:
    return 4.0 * math.pi * radius_m ** 3 / 3.0


def _on_sphere(value: Vec3, radius_m: float, center_m: Vec3) -> Vec3:
    length = norm(value)
    if length <= 1.0e-30:
        raise ValueError("cannot project zero vector onto sphere")
    return add(center_m, scale(value, radius_m / length))


def icosphere(subdivisions: int, radius_m: float = 1.0, center_m: Vec3 = (0.0, 0.0, 0.0)) -> SurfaceMesh:
    if subdivisions < 0:
        raise ValueError("subdivisions must be non-negative")
    if radius_m <= 0.0:
        raise ValueError("radius must be positive")
    golden = (1.0 + math.sqrt(5.0)) / 2.0
    raw = [
        (-1.0, golden, 0.0), (1.0, golden, 0.0), (-1.0, -golden, 0.0), (1.0, -golden, 0.0),
        (0.0, -1.0, golden), (0.0, 1.0, golden), (0.0, -1.0, -golden), (0.0, 1.0, -golden),
        (golden, 0.0, -1.0), (golden, 0.0, 1.0), (-golden, 0.0, -1.0), (-golden, 0.0, 1.0),
    ]
    vertices = [_on_sphere(value, radius_m, center_m) for value in raw]
    faces = [
        (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
        (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
        (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
        (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1),
    ]
    for _ in range(subdivisions):
        midpoint_cache: dict[tuple[int, int], int] = {}
        refined: list[tuple[int, int, int]] = []

        def midpoint(i: int, j: int) -> int:
            key = (i, j) if i < j else (j, i)
            if key in midpoint_cache:
                return midpoint_cache[key]
            vi, vj = vertices[i], vertices[j]
            relative_midpoint = (
                0.5 * (vi[0] + vj[0]) - center_m[0],
                0.5 * (vi[1] + vj[1]) - center_m[1],
                0.5 * (vi[2] + vj[2]) - center_m[2],
            )
            index = len(vertices)
            vertices.append(_on_sphere(relative_midpoint, radius_m, center_m))
            midpoint_cache[key] = index
            return index

        for a, b, c in faces:
            ab, bc, ca = midpoint(a, b), midpoint(b, c), midpoint(c, a)
            refined.extend(((a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)))
        faces = refined
    mesh = SurfaceMesh.from_iterables(vertices, faces)
    mesh.validate()
    return mesh
