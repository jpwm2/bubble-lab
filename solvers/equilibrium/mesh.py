"""Oriented triangular closed-surface mesh and geometry diagnostics."""
from __future__ import annotations

from dataclasses import dataclass
import math
import statistics
from typing import Iterable

from .vector import Vec3, cross, dot, mean, norm, scale, sub, unit

Face = tuple[int, int, int]


@dataclass(frozen=True)
class SurfaceMesh:
    """A deterministic, outward-oriented triangular closed surface."""

    vertices: tuple[Vec3, ...]
    faces: tuple[Face, ...]

    @classmethod
    def from_iterables(cls, vertices: Iterable[Vec3], faces: Iterable[Face]) -> "SurfaceMesh":
        return cls(tuple(tuple(map(float, v)) for v in vertices), tuple(tuple(map(int, f)) for f in faces))

    def with_vertices(self, vertices: Iterable[Vec3]) -> "SurfaceMesh":
        return SurfaceMesh.from_iterables(vertices, self.faces)

    def validate(self, *, require_closed: bool = True, require_outward: bool = True) -> None:
        if len(self.vertices) < 4:
            raise ValueError("closed surface requires at least four vertices")
        if len(self.faces) < 4:
            raise ValueError("closed surface requires at least four faces")
        edge_counts: dict[tuple[int, int], int] = {}
        for face_index, face in enumerate(self.faces):
            if len(set(face)) != 3:
                raise ValueError(f"face {face_index} repeats a vertex")
            if min(face) < 0 or max(face) >= len(self.vertices):
                raise ValueError(f"face {face_index} references a vertex outside the mesh")
            a, b, c = (self.vertices[index] for index in face)
            doubled_area = norm(cross(sub(b, a), sub(c, a)))
            if doubled_area <= 1.0e-18:
                raise ValueError(f"face {face_index} is degenerate")
            for i, j in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
                key = (i, j) if i < j else (j, i)
                edge_counts[key] = edge_counts.get(key, 0) + 1
        if require_closed:
            bad = [edge for edge, count in edge_counts.items() if count != 2]
            if bad:
                raise ValueError(f"surface is not closed/manifold; {len(bad)} edge incidences are invalid")
        if require_outward and self.signed_volume() <= 0.0:
            raise ValueError("surface orientation must have positive signed volume")

    def oriented_outward(self) -> "SurfaceMesh":
        volume = self.signed_volume()
        if abs(volume) <= 1.0e-30:
            raise ValueError("cannot orient a zero-volume surface")
        if volume > 0.0:
            return self
        return SurfaceMesh(self.vertices, tuple((a, c, b) for a, b, c in self.faces))

    def area(self) -> float:
        total = 0.0
        for ia, ib, ic in self.faces:
            a, b, c = self.vertices[ia], self.vertices[ib], self.vertices[ic]
            total += 0.5 * norm(cross(sub(b, a), sub(c, a)))
        return total

    def signed_volume(self) -> float:
        total = 0.0
        for ia, ib, ic in self.faces:
            a, b, c = self.vertices[ia], self.vertices[ib], self.vertices[ic]
            total += dot(a, cross(b, c)) / 6.0
        return total

    def centroid(self) -> Vec3:
        return mean(self.vertices)

    def face_normals(self) -> tuple[Vec3, ...]:
        normals = []
        for ia, ib, ic in self.faces:
            a, b, c = self.vertices[ia], self.vertices[ib], self.vertices[ic]
            normals.append(unit(cross(sub(b, a), sub(c, a))))
        return tuple(normals)

    def unique_edges(self) -> tuple[tuple[int, int], ...]:
        edges: set[tuple[int, int]] = set()
        for a, b, c in self.faces:
            for i, j in ((a, b), (b, c), (c, a)):
                edges.add((i, j) if i < j else (j, i))
        return tuple(sorted(edges))

    def edge_lengths(self) -> tuple[float, ...]:
        return tuple(norm(sub(self.vertices[i], self.vertices[j])) for i, j in self.unique_edges())

    def quality(self) -> dict[str, float | int]:
        lengths = self.edge_lengths()
        min_angle = 180.0
        max_aspect = 0.0
        for ia, ib, ic in self.faces:
            a, b, c = self.vertices[ia], self.vertices[ib], self.vertices[ic]
            side_lengths = (norm(sub(b, c)), norm(sub(c, a)), norm(sub(a, b)))
            longest = max(side_lengths)
            doubled_area = norm(cross(sub(b, a), sub(c, a)))
            altitude = doubled_area / longest
            max_aspect = max(max_aspect, longest / max(altitude, 1.0e-30))
            for opposite, s1, s2 in (
                (side_lengths[0], side_lengths[1], side_lengths[2]),
                (side_lengths[1], side_lengths[2], side_lengths[0]),
                (side_lengths[2], side_lengths[0], side_lengths[1]),
            ):
                cosine = (s1 * s1 + s2 * s2 - opposite * opposite) / max(2.0 * s1 * s2, 1.0e-30)
                cosine = min(1.0, max(-1.0, cosine))
                min_angle = min(min_angle, math.degrees(math.acos(cosine)))
        return {
            "vertex_count": len(self.vertices),
            "face_count": len(self.faces),
            "edge_count": len(lengths),
            "median_edge_length_m": statistics.median(lengths),
            "max_edge_length_m": max(lengths),
            "min_edge_length_m": min(lengths),
            "min_triangle_angle_deg": min_angle,
            "max_aspect_ratio": max_aspect,
        }
