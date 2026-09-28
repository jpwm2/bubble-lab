"""Deterministic mesh-based neck diagnostics and partition evidence."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from geometry import TriMesh, Vec3, add, dot, mean, mul, norm, sub, unit, cross


@dataclass(frozen=True)
class SliceSample:
    coordinate: float
    area: float
    point_count: int


@dataclass(frozen=True)
class NeckDiagnostic:
    detected: bool
    axis: Vec3
    origin: Vec3
    cut_coordinate: float | None
    neck_area: float | None
    neck_radius: float | None
    prominence_ratio: float
    mesh_spacing: float
    radius_to_spacing: float | None
    cut_loop_points: tuple[Vec3, ...]
    topologically_separable: bool
    left_face_count: int
    right_face_count: int
    crossing_face_count: int
    child_volume_fractions: tuple[float, float] | None
    child_axis_centroids: tuple[float, float] | None
    samples: tuple[SliceSample, ...]


def _mat_vec(m: tuple[tuple[float, float, float], ...], v: Vec3) -> Vec3:
    return (
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    )


def principal_axis(mesh: TriMesh) -> Vec3:
    c = mesh.volume_centroid()
    centered = [sub(v, c) for v in mesh.vertices]
    n = float(len(centered))
    covariance = tuple(
        tuple(math.fsum(p[i] * p[j] for p in centered) / n for j in range(3))
        for i in range(3)
    )
    diagonal = (covariance[0][0], covariance[1][1], covariance[2][2])
    seed_axis = max(range(3), key=lambda i: (diagonal[i], -i))
    v: Vec3 = tuple(1.0 if i == seed_axis else 0.0 for i in range(3))  # type: ignore[assignment]
    for _ in range(64):
        nxt = _mat_vec(covariance, v)
        if norm(nxt) <= 1.0e-300:
            break
        nxt = unit(nxt)
        if norm(sub(nxt, v)) < 1.0e-14 or norm(add(nxt, v)) < 1.0e-14:
            v = nxt
            break
        v = nxt
    for component in v:
        if abs(component) > 1.0e-12:
            if component < 0.0:
                v = mul(v, -1.0)
            break
    return unit(v)


def _plane_basis(normal: Vec3) -> tuple[Vec3, Vec3]:
    n = unit(normal)
    helper: Vec3 = (1.0, 0.0, 0.0) if abs(n[0]) < 0.8 else (0.0, 1.0, 0.0)
    u = unit(cross(n, helper))
    v = unit(cross(n, u))
    return u, v


def _deduplicate(points: Iterable[Vec3], tolerance: float) -> list[Vec3]:
    if tolerance <= 0.0:
        tolerance = 1.0e-12
    buckets: dict[tuple[int, int, int], Vec3] = {}
    inv = 1.0 / tolerance
    for p in points:
        key = (round(p[0] * inv), round(p[1] * inv), round(p[2] * inv))
        buckets.setdefault(key, p)
    return list(buckets.values())


def _slice_points(mesh: TriMesh, origin: Vec3, axis: Vec3, coordinate: float) -> list[Vec3]:
    scale = max(mesh.mean_edge_length(), 1.0)
    eps = 1.0e-10 * scale
    intersections: list[Vec3] = []
    for face in mesh.faces:
        tri = [mesh.vertices[index] for index in face]
        distances = [dot(sub(p, origin), axis) - coordinate for p in tri]
        local: list[Vec3] = []
        for edge in ((0, 1), (1, 2), (2, 0)):
            ia, ib = edge
            a, b = tri[ia], tri[ib]
            da, db = distances[ia], distances[ib]
            if abs(da) <= eps and abs(db) <= eps:
                local.extend((a, b))
            elif abs(da) <= eps:
                local.append(a)
            elif abs(db) <= eps:
                local.append(b)
            elif da * db < 0.0:
                fraction = da / (da - db)
                local.append(add(a, mul(sub(b, a), fraction)))
        intersections.extend(_deduplicate(local, eps * 10.0))
    return _deduplicate(intersections, eps * 50.0)


def cross_section(mesh: TriMesh, origin: Vec3, axis: Vec3, coordinate: float) -> tuple[float, tuple[Vec3, ...]]:
    points = _slice_points(mesh, origin, axis, coordinate)
    if len(points) < 3:
        return 0.0, tuple(points)
    u, v = _plane_basis(axis)
    center = mean(points)
    ordered = sorted(
        points,
        key=lambda p: math.atan2(dot(sub(p, center), v), dot(sub(p, center), u)),
    )
    projected = [(dot(sub(p, center), u), dot(sub(p, center), v)) for p in ordered]
    area2 = math.fsum(
        projected[i][0] * projected[(i + 1) % len(projected)][1]
        - projected[(i + 1) % len(projected)][0] * projected[i][1]
        for i in range(len(projected))
    )
    return abs(area2) * 0.5, tuple(ordered)


def _face_components(mesh: TriMesh, face_indices: set[int]) -> int:
    if not face_indices:
        return 0
    edge_faces: dict[tuple[int, int], list[int]] = {}
    for face_index in face_indices:
        a, b, c = mesh.faces[face_index]
        for i, j in ((a, b), (b, c), (c, a)):
            edge = (i, j) if i < j else (j, i)
            edge_faces.setdefault(edge, []).append(face_index)
    adjacency: dict[int, set[int]] = {index: set() for index in face_indices}
    for indices in edge_faces.values():
        if len(indices) == 2:
            a, b = indices
            adjacency[a].add(b)
            adjacency[b].add(a)
    remaining = set(face_indices)
    count = 0
    while remaining:
        count += 1
        seed = min(remaining)
        stack = [seed]
        remaining.remove(seed)
        while stack:
            current = stack.pop()
            for other in adjacency[current]:
                if other in remaining:
                    remaining.remove(other)
                    stack.append(other)
    return count


def partition_faces(mesh: TriMesh, origin: Vec3, axis: Vec3, coordinate: float) -> tuple[set[int], set[int], set[int], bool]:
    eps = max(mesh.mean_edge_length(), 1.0) * 1.0e-10
    left: set[int] = set()
    right: set[int] = set()
    crossing: set[int] = set()
    for index, face in enumerate(mesh.faces):
        distances = [dot(sub(mesh.vertices[v], origin), axis) - coordinate for v in face]
        if max(distances) < -eps:
            left.add(index)
        elif min(distances) > eps:
            right.add(index)
        else:
            crossing.add(index)
    separable = bool(left and right and crossing) and _face_components(mesh, left) == 1 and _face_components(mesh, right) == 1
    return left, right, crossing, separable


def _integrate(samples: list[SliceSample], cut: float) -> tuple[float, float, float, float]:
    left_v = right_v = 0.0
    left_m = right_m = 0.0
    for a, b in zip(samples[:-1], samples[1:]):
        t0, t1 = a.coordinate, b.coordinate
        if t1 <= t0:
            continue
        if t0 < cut < t1:
            fraction = (cut - t0) / (t1 - t0)
            area_cut = a.area + fraction * (b.area - a.area)
            pieces = ((t0, cut, a.area, area_cut, "L"), (cut, t1, area_cut, b.area, "R"))
        else:
            pieces = ((t0, t1, a.area, b.area, "L" if t1 <= cut else "R"),)
        for x0, x1, y0, y1, side in pieces:
            width = x1 - x0
            volume = 0.5 * (y0 + y1) * width
            moment = width * (y0 * (2.0 * x0 + x1) + y1 * (x0 + 2.0 * x1)) / 6.0
            if side == "L":
                left_v += volume
                left_m += moment
            else:
                right_v += volume
                right_m += moment
    return left_v, right_v, left_m, right_m


def diagnose_neck(
    mesh: TriMesh,
    *,
    sample_count: int = 101,
    minimum_prominence: float = 1.30,
) -> NeckDiagnostic:
    if sample_count < 31 or sample_count % 2 == 0:
        raise ValueError("sample_count must be an odd integer >= 31")
    origin = mesh.volume_centroid()
    axis = principal_axis(mesh)
    coordinates = [dot(sub(v, origin), axis) for v in mesh.vertices]
    lo, hi = min(coordinates), max(coordinates)
    span = hi - lo
    if span <= 0.0:
        raise ValueError("mesh has zero extent along principal axis")

    samples: list[SliceSample] = [SliceSample(lo, 0.0, 1)]
    loops: dict[int, tuple[Vec3, ...]] = {}
    for i in range(1, sample_count - 1):
        t = lo + span * i / (sample_count - 1)
        area, loop = cross_section(mesh, origin, axis, t)
        samples.append(SliceSample(t, area, len(loop)))
        loops[i] = loop
    samples.append(SliceSample(hi, 0.0, 1))

    lower = max(2, int(0.24 * (sample_count - 1)))
    upper = min(sample_count - 3, int(0.76 * (sample_count - 1)))
    candidate = min(range(lower, upper + 1), key=lambda i: (samples[i].area, abs(samples[i].coordinate), i))
    candidate_area = samples[candidate].area
    left_peak = max((sample.area for sample in samples[2:candidate]), default=0.0)
    right_peak = max((sample.area for sample in samples[candidate + 1 : -2]), default=0.0)
    prominence = min(left_peak, right_peak) / max(candidate_area, 1.0e-300)
    local_minimum = samples[candidate].area <= samples[candidate - 1].area and samples[candidate].area <= samples[candidate + 1].area
    detected = bool(candidate_area > 0.0 and local_minimum and prominence >= minimum_prominence)

    spacing = mesh.mean_edge_length()
    if not detected:
        return NeckDiagnostic(
            detected=False,
            axis=axis,
            origin=origin,
            cut_coordinate=None,
            neck_area=None,
            neck_radius=None,
            prominence_ratio=prominence,
            mesh_spacing=spacing,
            radius_to_spacing=None,
            cut_loop_points=(),
            topologically_separable=False,
            left_face_count=0,
            right_face_count=0,
            crossing_face_count=0,
            child_volume_fractions=None,
            child_axis_centroids=None,
            samples=tuple(samples),
        )

    cut = samples[candidate].coordinate
    left, right, crossing, separable = partition_faces(mesh, origin, axis, cut)
    left_v, right_v, left_m, right_m = _integrate(samples, cut)
    total = left_v + right_v
    fractions = (left_v / total, right_v / total) if total > 0.0 else None
    centroids = (
        left_m / left_v if left_v > 0.0 else cut,
        right_m / right_v if right_v > 0.0 else cut,
    )
    radius = math.sqrt(candidate_area / math.pi)
    return NeckDiagnostic(
        detected=True,
        axis=axis,
        origin=origin,
        cut_coordinate=cut,
        neck_area=candidate_area,
        neck_radius=radius,
        prominence_ratio=prominence,
        mesh_spacing=spacing,
        radius_to_spacing=radius / spacing if spacing > 0.0 else None,
        cut_loop_points=loops.get(candidate, ()),
        topologically_separable=separable,
        left_face_count=len(left),
        right_face_count=len(right),
        crossing_face_count=len(crossing),
        child_volume_fractions=fractions,
        child_axis_centroids=centroids,
        samples=tuple(samples),
    )
