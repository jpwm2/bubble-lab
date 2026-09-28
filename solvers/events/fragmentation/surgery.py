"""Deterministic single-loop plane cut/cap surgery for a supported closed-front class."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Hashable

from .geometry import Face, TriMesh, Vec3, add, cross, dot, mean, mul, norm, sub, unit


class UnsupportedFragmentation(ValueError):
    """Raised when a neck cannot be promoted to the supported deterministic split."""


@dataclass(frozen=True)
class ChildSurgery:
    side: str
    mesh: TriMesh
    cut_loop_vertex_count: int
    reused_parent_vertex_count: int
    inserted_intersection_vertex_count: int
    cap_face_count: int


@dataclass(frozen=True)
class MeshSplit:
    negative: ChildSurgery
    positive: ChildSurgery
    parent_volume: float
    geometric_volume_sum: float
    geometric_volume_relative_error: float


@dataclass(frozen=True)
class _Point:
    key: Hashable
    position: Vec3
    distance: float


class _Builder:
    def __init__(self, mesh: TriMesh, origin: Vec3, axis: Vec3, coordinate: float, side: int, eps: float) -> None:
        self.mesh = mesh
        self.origin = origin
        self.axis = axis
        self.coordinate = coordinate
        self.side = side
        self.eps = eps
        self.vertices: list[Vec3] = []
        self.faces: list[Face] = []
        self.key_to_index: dict[Hashable, int] = {}
        self.original_keys: set[Hashable] = set()
        self.intersection_keys: set[Hashable] = set()

    def _inside(self, distance: float) -> bool:
        return distance <= self.eps if self.side < 0 else distance >= -self.eps

    def _point_for_vertex(self, idx: int) -> _Point:
        p = self.mesh.vertices[idx]
        d = dot(sub(p, self.origin), self.axis) - self.coordinate
        return _Point(("v", idx), p, d)

    def _intersection(self, a: _Point, b: _Point) -> _Point:
        if abs(a.distance) <= self.eps:
            return _Point(a.key, a.position, 0.0)
        if abs(b.distance) <= self.eps:
            return _Point(b.key, b.position, 0.0)
        if a.distance * b.distance >= 0.0:
            raise RuntimeError("intersection requested for a non-crossing edge")
        # Original mesh edges are shared by adjacent triangles, so this key makes the
        # interpolated cut vertex identical in both clipped faces.
        ai = int(a.key[1]) if isinstance(a.key, tuple) and a.key[0] == "v" else None
        bi = int(b.key[1]) if isinstance(b.key, tuple) and b.key[0] == "v" else None
        if ai is None or bi is None:
            raise RuntimeError("cut clipping expected original-edge endpoints")
        edge = (min(ai, bi), max(ai, bi))
        t = a.distance / (a.distance - b.distance)
        p = add(a.position, mul(sub(b.position, a.position), t))
        return _Point(("e", edge[0], edge[1]), p, 0.0)

    @staticmethod
    def _dedup_polygon(poly: list[_Point]) -> list[_Point]:
        if not poly:
            return []
        out: list[_Point] = []
        for p in poly:
            if not out or p.key != out[-1].key:
                out.append(p)
        if len(out) > 1 and out[0].key == out[-1].key:
            out.pop()
        return out

    def _clip_triangle(self, face: Face) -> list[_Point]:
        poly = [self._point_for_vertex(i) for i in face]
        out: list[_Point] = []
        for current, nxt in zip(poly, poly[1:] + poly[:1]):
            current_in = self._inside(current.distance)
            next_in = self._inside(nxt.distance)
            if current_in and next_in:
                out.append(nxt)
            elif current_in and not next_in:
                out.append(self._intersection(current, nxt))
            elif not current_in and next_in:
                out.append(self._intersection(current, nxt))
                out.append(nxt)
        return self._dedup_polygon(out)

    def _index(self, point: _Point) -> int:
        if point.key not in self.key_to_index:
            self.key_to_index[point.key] = len(self.vertices)
            self.vertices.append(point.position)
            if isinstance(point.key, tuple) and point.key[0] == "v":
                self.original_keys.add(point.key)
            elif isinstance(point.key, tuple) and point.key[0] == "e":
                self.intersection_keys.add(point.key)
        return self.key_to_index[point.key]

    def build_open_surface(self) -> None:
        for face in self.mesh.faces:
            poly = self._clip_triangle(face)
            if len(poly) < 3:
                continue
            indices = [self._index(p) for p in poly]
            # Drop any zero-area triangle created by an on-plane vertex.
            for i in range(1, len(indices) - 1):
                a, b, c = indices[0], indices[i], indices[i + 1]
                pa, pb, pc = self.vertices[a], self.vertices[b], self.vertices[c]
                if norm(cross(sub(pb, pa), sub(pc, pa))) <= self.eps * self.eps:
                    continue
                self.faces.append((a, b, c))
        if not self.faces:
            raise UnsupportedFragmentation("cut produced an empty child surface")

    def _boundary_loop(self) -> list[int]:
        edge_counts: dict[tuple[int, int], int] = {}
        for a, b, c in self.faces:
            for i, j in ((a, b), (b, c), (c, a)):
                edge = (i, j) if i < j else (j, i)
                edge_counts[edge] = edge_counts.get(edge, 0) + 1
        boundary = [edge for edge, count in edge_counts.items() if count == 1]
        if not boundary:
            raise UnsupportedFragmentation("cut did not create an open boundary loop")
        adjacency: dict[int, set[int]] = {}
        for a, b in boundary:
            adjacency.setdefault(a, set()).add(b)
            adjacency.setdefault(b, set()).add(a)
        if any(len(neighbors) != 2 for neighbors in adjacency.values()):
            raise UnsupportedFragmentation("cut boundary is branched or non-manifold")
        # The supported production class contains exactly one separating neck loop.
        start = min(adjacency)
        loop = [start]
        previous: int | None = None
        current = start
        while True:
            choices = sorted(adjacency[current])
            nxt = choices[0] if choices[0] != previous else choices[1]
            if nxt == start:
                break
            if nxt in loop:
                raise UnsupportedFragmentation("cut boundary contains multiple/degenerate cycles")
            loop.append(nxt)
            previous, current = current, nxt
            if len(loop) > len(adjacency):
                raise UnsupportedFragmentation("cut boundary traversal failed")
        if len(loop) != len(adjacency):
            raise UnsupportedFragmentation("kut produced more than one boundary loop")
        # Every boundary vertex must actually lie on the cut plane within tolerance.
        for index in loop:
            d = dot(sub(self.vertices[index], self.origin), self.axis) - self.coordinate
            if abs(d) > 16.0 * self.eps:
                raise UnsupportedFragmentation("open boundary is not the requested cut plane")
        return loop

    def cap_and_finalize(self) -> ChildSurgery:
        loop = self._boundary_loop()
        desired = self.axis if self.side < 0 else mul(self.axis, -1.0)
        center = mean(self.vertices[i] for i in loop)
        # Newell-like area vector for the loop orientation.
        area_vec = (0.0, 0.0, 0.0)
        for i, j in zip(loop, loop[1:] + loop[:1]):
            area_vec = add(area_vec, cross(sub(self.vertices[i], center), sub(self.vertices[j], center)))
        if norm(area_vec) <= self.eps * self.eps:
            raise UnsupportedFragmentation("cut loop area is degenerate")
        if dot(area_vec, desired) < 0.0:
            loop.reverse()
        center_index = len(self.vertices)
        self.vertices.append(center)
        cap_faces = 0
        for i, j in zip(loop, loop[1:] + loop[:1]):
            self.faces.append((center_index, i, j))
            cap_faces += 1
        result = TriMesh(tuple(self.vertices), tuple(self.faces))
        if result.signed_volume() < 0.0:
            # A globally inverted child can be corrected without changing topology.
            result = TriMesh(result.vertices, tuple((a, c, b) for a, b, c in result.faces))
        if not result.is_closed_manifold():
            raise UnsupportedFragmentation("cut/cap result is not a consistently oriented closed manifold")
        if result.volume() <= max(self.eps ** 3, 1.0e-18):
            raise UnsupportedFragmentation("cut/cap result has non-positive or negligible volume")
        side_name = "NEGATIVE_AXIS" if self.side < 0 else "POSITIVE_AXIS"
        return ChildSurgery(
            side=side_name,
            mesh=result,
            cut_loop_vertex_count=len(loop),
            reused_parent_vertex_count=len(self.original_keys),
            inserted_intersection_vertex_count=len(self.intersection_keys),
            cap_face_count=cap_faces,
        )


def split_mesh_by_plane(
    mesh: TriMesh,
    *,
    origin: Vec3,
    axis: Vec3,
    coordinate: float,
    volume_tolerance: float = 5.0e-11,
) -> MeshSplit:
    if not mesh.is_closed_manifold():
        raise UnsupportedFragmentation("parent mesh must be a consistently oriented closed manifold")
    if mesh.volume() <= 0.0:
        raise UnsupportedFragmentation("parent mesh must have positive volume")
    axis = unit(axis)
    eps = max(mesh.mean_edge_length(), 1.0) * 1.0e-10
    negative_builder = _Builder(mesh, origin, axis, coordinate, -1, eps)
    positive_builder = _Builder(mesh, origin, axis, coordinate, 1, eps)
    negative_builder.build_open_surface()
    positive_builder.build_open_surface()
    negative = negative_builder.cap_and_finalize()
    positive = positive_builder.cap_and_finalize()
    parent_volume = mesh.volume()
    total = math.fsum((negative.mesh.volume(), positive.mesh.volume()))
    rel = abs(total - parent_volume) / max(parent_volume, 1.0e-300)
    if rel > volume_tolerance:
        raise UnsupportedFragmentation(
            f"cut/cap geometric volume conservation {rel:.3e} exceeds tolerance {volume_tolerance:.3e}"
        )
    return MeshSplit(negative, positive, parent_volume, total, rel)
