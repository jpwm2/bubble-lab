"""Deterministic quality-preserving remeshing for tracked soap-film fronts.

This module maintains the Lagrangian front only. It never creates or removes
bubble regions and never performs physical topology events. Surface scalar
transfer is expressed as face-integrated areal amount so total amount remains
conservative across mesh connectivity changes.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable

from .geometry import FilmFront, Vec3, add, cross, dot, mean, mul, norm, sub, unit

Edge = tuple[int, int]


@dataclass(frozen=True)
class RemeshConfig:
    """Configuration for deterministic front remeshing."""

    mode: str = "disabled"
    interval_steps: int = 1
    target_edge_length_m: float | None = None
    min_edge_factor: float = 0.45
    max_edge_factor: float = 1.60
    min_angle_deg: float = 20.0
    max_aspect_ratio: float = 3.0
    max_passes: int = 2
    max_operations_per_pass: int = 64
    smoothing_relaxation: float = 0.25
    max_geometry_relative_error: float = 2.0e-3
    amr_cell_size_factor: float = 1.0

    def __post_init__(self) -> None:
        if self.mode not in {"disabled", "interval", "quality"}:
            raise ValueError("remesh mode must be disabled, interval, or quality")
        if self.interval_steps < 1:
            raise ValueError("remesh interval_steps must be >= 1")
        if self.target_edge_length_m is not None and self.target_edge_length_m <= 0.0:
            raise ValueError("target_edge_length_m must be positive when set")
        if not 0.0 < self.min_edge_factor < self.max_edge_factor:
            raise ValueError("edge factors must satisfy 0 < min < max")
        if not 0.0 < self.min_angle_deg < 60.0:
            raise ValueError("min_angle_deg must lie in (0, 60)")
        if self.max_aspect_ratio <= 1.0:
            raise ValueError("max_aspect_ratio must exceed 1")
        if self.max_passes < 1 or self.max_operations_per_pass < 1:
            raise ValueError("remesh pass and operation budgets must be positive")
        if not 0.0 <= self.smoothing_relaxation <= 1.0:
            raise ValueError("smoothing_relaxation must lie in [0, 1]")
        if self.max_geometry_relative_error < 0.0:
            raise ValueError("max_geometry_relative_error must be non-negative")
        if self.amr_cell_size_factor <= 0.0:
            raise ValueError("amr_cell_size_factor must be positive")


@dataclass(frozen=True)
class MeshQuality:
    vertex_count: int
    face_count: int
    min_angle_deg: float
    max_aspect_ratio: float
    min_edge_length_m: float
    max_edge_length_m: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "vertex_count": self.vertex_count,
            "face_count": self.face_count,
            "min_angle_deg": self.min_angle_deg,
            "max_aspect_ratio": self.max_aspect_ratio,
            "min_edge_length_m": self.min_edge_length_m,
            "max_edge_length_m": self.max_edge_length_m,
        }


@dataclass
class ConservativeArealField:
    """Face finite-volume storage for a generic surface amount.

    face_amounts stores the integrated quantity on each triangle, not pointwise
    density. Remapping uses a deterministic nearest-donor areal density followed
    by one global conservative correction. This is transport infrastructure for
    later liquid-mass/surfactant models, not a drainage or surfactant equation.
    """

    name: str
    face_amounts: list[float]

    @classmethod
    def from_density(
        cls,
        front: FilmFront,
        name: str,
        density: float | Callable[[int, Vec3], float],
    ) -> "ConservativeArealField":
        amounts: list[float] = []
        for index, face in enumerate(front.faces):
            value = density(index, _face_centroid(front, face)) if callable(density) else density
            amounts.append(float(value) * _face_area(front, face))
        return cls(name=name, face_amounts=amounts)

    def clone(self) -> "ConservativeArealField":
        return ConservativeArealField(self.name, list(self.face_amounts))

    def total_amount(self) -> float:
        return math.fsum(self.face_amounts)

    def remapped(self, old: FilmFront, new: FilmFront) -> "ConservativeArealField":
        if len(self.face_amounts) != len(old.faces):
            raise ValueError("surface field face count does not match source mesh")
        if not new.faces:
            raise ValueError("cannot remap a surface field to an empty mesh")

        old_total = self.total_amount()
        old_centroids = [_face_centroid(old, face) for face in old.faces]
        old_density: list[float] = []
        for amount, face in zip(self.face_amounts, old.faces):
            area = _face_area(old, face)
            old_density.append(0.0 if area <= 0.0 else amount / area)

        amounts: list[float] = []
        for face in new.faces:
            centroid = _face_centroid(new, face)
            donor = min(
                range(len(old.faces)),
                key=lambda idx: (_distance_squared(centroid, old_centroids[idx]), idx),
            )
            amounts.append(old_density[donor] * _face_area(new, face))

        trial_total = math.fsum(amounts)
        tiny = 1.0e-300
        if abs(old_total) > tiny and abs(trial_total) > tiny:
            scale = old_total / trial_total
            amounts = [amount * scale for amount in amounts]
        elif abs(old_total) > tiny:
            areas = [_face_area(new, face) for face in new.faces]
            area_sum = math.fsum(areas)
            amounts = [old_total * area / area_sum for area in areas]
        if amounts:
            amounts[-1] += old_total - math.fsum(amounts)
        return ConservativeArealField(self.name, amounts)


@dataclass(frozen=True)
class RemeshReport:
    attempted: bool
    operations: dict[str, int]
    operation_log: tuple[str, ...]
    before: MeshQuality
    after: MeshQuality
    volume_relative_change: float
    area_relative_change: float
    centroid_relative_change: float
    field_conservation_relative_error: float
    region_identity_preserved: bool
    target_edge_length_m: float

    @property
    def operation_count(self) -> int:
        return sum(self.operations.values())

    def as_dict(self) -> dict[str, object]:
        return {
            "attempted": self.attempted,
            "operations": dict(self.operations),
            "operation_log": list(self.operation_log),
            "vertices_before": self.before.vertex_count,
            "vertices_after": self.after.vertex_count,
            "faces_before": self.before.face_count,
            "faces_after": self.after.face_count,
            "quality_before": self.before.as_dict(),
            "quality_after": self.after.as_dict(),
            "volume_relative_change_pre_projection": self.volume_relative_change,
            "area_relative_change": self.area_relative_change,
            "centroid_relative_change": self.centroid_relative_change,
            "field_conservation_relative_error": self.field_conservation_relative_error,
            "region_identity_preserved": self.region_identity_preserved,
            "target_edge_length_m": self.target_edge_length_m,
        }

    def signature(self) -> tuple[object, ...]:
        return (
            self.attempted,
            tuple(sorted(self.operations.items())),
            self.operation_log,
            tuple(sorted(self.before.as_dict().items())),
            tuple(sorted(self.after.as_dict().items())),
            self.volume_relative_change,
            self.area_relative_change,
            self.centroid_relative_change,
            self.field_conservation_relative_error,
            self.region_identity_preserved,
            self.target_edge_length_m,
        )


def _distance_squared(a: Vec3, b: Vec3) -> float:
    d = sub(a, b)
    return dot(d, d)


def _face_area(front: FilmFront, face: tuple[int, int, int]) -> float:
    i, j, k = face
    a, b, c = front.vertices[i], front.vertices[j], front.vertices[k]
    return 0.5 * norm(cross(sub(b, a), sub(c, a)))


def _face_centroid(front: FilmFront, face: tuple[int, int, int]) -> Vec3:
    return mul(
        add(add(front.vertices[face[0]], front.vertices[face[1]]), front.vertices[face[2]]),
        1.0 / 3.0,
    )


def _triangle_quality(front: FilmFront, face: tuple[int, int, int]) -> tuple[float, float]:
    points = [front.vertices[index] for index in face]
    lengths = [
        norm(sub(points[1], points[0])),
        norm(sub(points[2], points[1])),
        norm(sub(points[0], points[2])),
    ]
    area = _face_area(front, face)
    if area <= 0.0 or min(lengths) <= 0.0:
        return 0.0, float("inf")

    angles: list[float] = []
    for a, b, opposite in (
        (lengths[0], lengths[2], lengths[1]),
        (lengths[0], lengths[1], lengths[2]),
        (lengths[1], lengths[2], lengths[0]),
    ):
        cosine = (a * a + b * b - opposite * opposite) / (2.0 * a * b)
        cosine = max(-1.0, min(1.0, cosine))
        angles.append(math.degrees(math.acos(cosine)))

    longest = max(lengths)
    aspect = longest * longest / (2.0 * area)
    return min(angles), aspect


def _edges(front: FilmFront) -> list[Edge]:
    edges: set[Edge] = set()
    for face in front.faces:
        for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            edges.add((a, b) if a < b else (b, a))
    return sorted(edges)


def _edge_faces(front: FilmFront) -> dict[Edge, list[int]]:
    result: dict[Edge, list[int]] = {}
    for face_index, face in enumerate(front.faces):
        for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            edge = (a, b) if a < b else (b, a)
            result.setdefault(edge, []).append(face_index)
    return result


def mesh_quality(front: FilmFront) -> MeshQuality:
    edges = _edges(front)
    if not edges:
        raise ValueError("mesh has no edges")
    edge_lengths = [norm(sub(front.vertices[a], front.vertices[b])) for a, b in edges]
    triangle_metrics = [_triangle_quality(front, face) for face in front.faces]
    return MeshQuality(
        vertex_count=len(front.vertices),
        face_count=len(front.faces),
        min_angle_deg=min(metric[0] for metric in triangle_metrics),
        max_aspect_ratio=max(metric[1] for metric in triangle_metrics),
        min_edge_length_m=min(edge_lengths),
        max_edge_length_m=max(edge_lengths),
    )


def _euler_characteristic(front: FilmFront) -> int:
    return len(front.vertices) - len(_edges(front)) + len(front.faces)


def _closed_connected_manifold(front: FilmFront) -> bool:
    edge_map = _edge_faces(front)
    if not edge_map or any(len(face_ids) != 2 for face_ids in edge_map.values()):
        return False

    canonical_faces: set[tuple[int, int, int]] = set()
    for face in front.faces:
        if len(set(face)) != 3 or _face_area(front, face) <= 1.0e-20:
            return False
        key = tuple(sorted(face))
        if key in canonical_faces:
            return False
        canonical_faces.add(key)

    adjacent: list[set[int]] = [set() for _ in front.faces]
    for face_ids in edge_map.values():
        a, b = face_ids
        adjacent[a].add(b)
        adjacent[b].add(a)
    seen = {0}
    stack = [0]
    while stack:
        current = stack.pop()
        for other in adjacent[current]:
            if other not in seen:
                seen.add(other)
                stack.append(other)
    return len(seen) == len(front.faces)


def _front_like(
    front: FilmFront,
    vertices: list[Vec3],
    faces: list[tuple[int, int, int]],
) -> FilmFront:
    return FilmFront(
        bubble_id=front.bubble_id,
        mesh_id=front.mesh_id,
        film_id=front.film_id,
        vertices=list(vertices),
        faces=list(faces),
        surface_tension_n_m=front.surface_tension_n_m,
        target_volume_m3=front.target_volume_m3,
    )


def _relative_change(reference: float, value: float) -> float:
    return abs(value - reference) / max(abs(reference), 1.0e-300)


def _quality_requires_work(quality: MeshQuality, target: float, config: RemeshConfig) -> bool:
    return (
        quality.min_edge_length_m < config.min_edge_factor * target
        or quality.max_edge_length_m > config.max_edge_factor * target
        or quality.min_angle_deg < config.min_angle_deg
        or quality.max_aspect_ratio > config.max_aspect_ratio
    )


class FrontRemesher:
    """Deterministic topology-preserving maintenance of a single closed front."""

    def __init__(self, config: RemeshConfig | None = None):
        self.config = config or RemeshConfig()

    def target_edge_length(
        self,
        front: FilmFront,
        local_eulerian_cell_size_m: float | None = None,
    ) -> float:
        target = self.config.target_edge_length_m or front.mean_edge_length()
        if local_eulerian_cell_size_m is not None and local_eulerian_cell_size_m > 0.0:
            target = min(
                target,
                self.config.amr_cell_size_factor * local_eulerian_cell_size_m,
            )
        return target

    def needs_remesh(
        self,
        front: FilmFront,
        local_eulerian_cell_size_m: float | None = None,
    ) -> bool:
        if self.config.mode == "disabled":
            return False
        target = self.target_edge_length(front, local_eulerian_cell_size_m)
        return _quality_requires_work(mesh_quality(front), target, self.config)

    def _candidate_safe(self, old: FilmFront, candidate: FilmFront) -> bool:
        if not _closed_connected_manifold(candidate):
            return False
        if _euler_characteristic(candidate) != _euler_characteristic(old):
            return False
        if candidate.signed_volume() <= 0.0:
            return False

        scale = max(old.equivalent_radius(), old.mean_edge_length(), 1.0e-30)
        geometry_error = max(
            _relative_change(old.volume(), candidate.volume()),
            _relative_change(old.area(), candidate.area()),
            norm(sub(old.centroid(), candidate.centroid())) / scale,
        )
        return geometry_error <= self.config.max_geometry_relative_error * (1.0 + 1.0e-12)

    def _commit(
        self,
        front: FilmFront,
        candidate: FilmFront,
        fields: dict[str, ConservativeArealField],
    ) -> None:
        old = front.clone()
        remapped = {name: field.remapped(old, candidate) for name, field in fields.items()}
        front.vertices = list(candidate.vertices)
        front.faces = list(candidate.faces)
        for name, field in remapped.items():
            fields[name].face_amounts = field.face_amounts

    def split_edge(
        self,
        front: FilmFront,
        edge: Edge,
        fields: dict[str, ConservativeArealField] | None = None,
        fraction: float = 0.5,
    ) -> bool:
        fields = fields or {}
        edge = tuple(sorted(edge))
        incident = _edge_faces(front).get(edge, [])
        if len(incident) != 2 or not 0.0 < fraction < 1.0:
            return False

        a, b = edge
        new_position = add(
            mul(front.vertices[a], 1.0 - fraction),
            mul(front.vertices[b], fraction),
        )
        vertices = list(front.vertices)
        vertices.append(new_position)
        midpoint = len(vertices) - 1

        incident_set = set(incident)
        faces: list[tuple[int, int, int]] = []
        for face_index, face in enumerate(front.faces):
            if face_index not in incident_set:
                faces.append(face)
                continue
            opposite = next(index for index in face if index not in edge)
            faces.extend(((a, midpoint, opposite), (midpoint, b, opposite)))

        candidate = _front_like(front, vertices, faces)
        if not self._candidate_safe(front, candidate):
            return False
        self._commit(front, candidate, fields)
        return True

    def collapse_edge(
        self,
        front: FilmFront,
        edge: Edge,
        fields: dict[str, ConservativeArealField] | None = None,
    ) -> bool:
        fields = fields or {}
        edge = tuple(sorted(edge))
        incident = _edge_faces(front).get(edge, [])
        if len(incident) != 2:
            return False

        a, b = edge
        neighbors = [set() for _ in front.vertices]
        for x, y in _edges(front):
            neighbors[x].add(y)
            neighbors[y].add(x)
        opposite = {
            next(index for index in front.faces[face_index] if index not in edge)
            for face_index in incident
        }
        if neighbors[a].intersection(neighbors[b]) != opposite:
            return False

        keep, remove = a, b
        raw_faces: list[tuple[int, int, int]] = []
        seen: set[tuple[int, int, int]] = set()
        for face in front.faces:
            replaced = tuple(keep if index == remove else index for index in face)
            if len(set(replaced)) != 3:
                continue
            key = tuple(sorted(replaced))
            if key in seen:
                return False
            seen.add(key)
            raw_faces.append(replaced)

        vertices = [vertex for index, vertex in enumerate(front.vertices) if index != remove]
        faces = [
            tuple(index - 1 if index > remove else index for index in face)
            for face in raw_faces
        ]
        candidate = _front_like(front, vertices, faces)
        if not self._candidate_safe(front, candidate):
            return False
        self._commit(front, candidate, fields)
        return True

    def flip_edge(
        self,
        front: FilmFront,
        edge: Edge,
        fields: dict[str, ConservativeArealField] | None = None,
        require_improvement: bool = True,
    ) -> bool:
        fields = fields or {}
        edge = tuple(sorted(edge))
        edge_map = _edge_faces(front)
        incident = edge_map.get(edge, [])
        if len(incident) != 2:
            return False

        a, b = edge
        c = next(index for index in front.faces[incident[0]] if index not in edge)
        d = next(index for index in front.faces[incident[1]] if index not in edge)
        if c == d or tuple(sorted((c, d))) in edge_map:
            return False

        pa, pb, pc, pd = (
            front.vertices[a],
            front.vertices[b],
            front.vertices[c],
            front.vertices[d],
        )
        n1 = cross(sub(front.vertices[front.faces[incident[0]][1]], front.vertices[front.faces[incident[0]][0]]),
                   sub(front.vertices[front.faces[incident[0]][2]], front.vertices[front.faces[incident[0]][0]]))
        n2 = cross(sub(front.vertices[front.faces[incident[1]][1]], front.vertices[front.faces[incident[1]][0]]),
                   sub(front.vertices[front.faces[incident[1]][2]], front.vertices[front.faces[incident[1]][0]]))
        normal = unit(add(unit(n1), unit(n2)))
        if norm(normal) <= 1.0e-15:
            return False
        old_side_c = dot(cross(sub(pb, pa), sub(pc, pa)), normal)
        old_side_d = dot(cross(sub(pb, pa), sub(pd, pa)), normal)
        new_side_a = dot(cross(sub(pd, pc), sub(pa, pc)), normal)
        new_side_b = dot(cross(sub(pd, pc), sub(pb, pc)), normal)
        scale = max(front.mean_edge_length() ** 2, 1.0e-30)
        side_eps = 1.0e-12 * scale
        if old_side_c * old_side_d >= -side_eps or new_side_a * new_side_b >= -side_eps:
            return False

        kept_faces = [
            face
            for face_index, face in enumerate(front.faces)
            if face_index not in set(incident)
        ]
        new_faces = [(c, d, a), (d, c, b)]
        candidate = _front_like(front, front.vertices, kept_faces + new_faces)
        if not self._candidate_safe(front, candidate):
            return False

        if require_improvement:
            before_metrics = [_triangle_quality(front, front.faces[index]) for index in incident]
            after_metrics = [_triangle_quality(candidate, face) for face in candidate.faces[-2:]]
            before_min = min(metric[0] for metric in before_metrics)
            before_aspect = max(metric[1] for metric in before_metrics)
            after_min = min(metric[0] for metric in after_metrics)
            after_aspect = max(metric[1] for metric in after_metrics)
            if not (
                after_min > before_min + 1.0e-12
                or after_aspect < before_aspect - 1.0e-12
            ):
                return False

        self._commit(front, candidate, fields)
        return True

    def smooth_vertex(
        self,
        front: FilmFront,
        vertex_index: int,
        fields: dict[str, ConservativeArealField] | None = None,
        relaxation: float | None = None,
        require_improvement: bool = True,
    ) -> bool:
        fields = fields or {}
        if vertex_index < 0 or vertex_index >= len(front.vertices):
            return False
        relaxation = self.config.smoothing_relaxation if relaxation is None else relaxation
        if not 0.0 <= relaxation <= 1.0:
            raise ValueError("smoothing relaxation must lie in [0, 1]")

        incident = [index for index, face in enumerate(front.faces) if vertex_index in face]
        neighbors = sorted(
            {
                index
                for face_index in incident
                for index in front.faces[face_index]
                if index != vertex_index
            }
        )
        if len(neighbors) < 3:
            return False

        current = front.vertices[vertex_index]
        average = mean(front.vertices[index] for index in neighbors)
        normal_sum = (0.0, 0.0, 0.0)
        for face_index in incident:
            i, j, k = front.faces[face_index]
            normal_sum = add(
                normal_sum,
                cross(sub(front.vertices[j], front.vertices[i]), sub(front.vertices[k], front.vertices[i])),
            )
        normal = unit(normal_sum)
        if norm(normal) <= 1.0e-15:
            return False
        displacement = sub(average, current)
        tangential = sub(displacement, mul(normal, dot(displacement, normal)))
        move = mul(tangential, relaxation)
        if norm(move) <= 1.0e-15 * max(front.mean_edge_length(), 1.0):
            return False

        vertices = list(front.vertices)
        vertices[vertex_index] = add(current, move)
        candidate = _front_like(front, vertices, front.faces)
        if not self._candidate_safe(front, candidate):
            return False

        if require_improvement:
            before_metrics = [_triangle_quality(front, front.faces[index]) for index in incident]
            after_metrics = [_triangle_quality(candidate, candidate.faces[index]) for index in incident]
            before_min = min(metric[0] for metric in before_metrics)
            before_aspect = max(metric[1] for metric in before_metrics)
            after_min = min(metric[0] for metric in after_metrics)
            after_aspect = max(metric[1] for metric in after_metrics)
            if not (
                after_min > before_min + 1.0e-12
                or after_aspect < before_aspect - 1.0e-12
            ):
                return False

        self._commit(front, candidate, fields)
        return True

    def remesh(
        self,
        front: FilmFront,
        fields: dict[str, ConservativeArealField] | None = None,
        local_eulerian_cell_size_m: float | None = None,
        force: bool = False,
    ) -> RemeshReport:
        fields = fields or {}
        before_front = front.clone()
        before = mesh_quality(front)
        target = self.target_edge_length(front, local_eulerian_cell_size_m)
        field_totals = {name: field.total_amount() for name, field in fields.items()}

        operations = {"split": 0, "collapse": 0, "flip": 0, "smooth": 0}
        operation_log: list[str] = []
        attempted = (
            force
            or self.config.mode == "interval"
            or (
                self.config.mode == "quality"
                and _quality_requires_work(before, target, self.config)
            )
        )

        if attempted:
            for _ in range(self.config.max_passes):
                budget = self.config.max_operations_per_pass

                while budget > 0:
                    candidates = sorted(
                        _edges(front),
                        key=lambda edge: (
                            norm(sub(front.vertices[edge[0]], front.vertices[edge[1]])),
                            edge,
                        ),
                    )
                    accepted: Edge | None = None
                    for edge in candidates:
                        length = norm(sub(front.vertices[edge[0]], front.vertices[edge[1]]))
                        if length >= self.config.min_edge_factor * target:
                            break
                        if self.collapse_edge(front, edge, fields):
                            accepted = edge
                            break
                    if accepted is None:
                        break
                    operations["collapse"] += 1
                    operation_log.append(f"collapse:{accepted[0]}-{accepted[1]}")
                    budget -= 1

                while budget > 0:
                    candidates = sorted(
                        _edges(front),
                        key=lambda edge: (
                            -norm(sub(front.vertices[edge[0]], front.vertices[edge[1]])),
                            edge,
                        ),
                    )
                    accepted = None
                    for edge in candidates:
                        length = norm(sub(front.vertices[edge[0]], front.vertices[edge[1]]))
                        if length <= self.config.max_edge_factor * target:
                            break
                        if self.split_edge(front, edge, fields):
                            accepted = edge
                            break
                    if accepted is None:
                        break
                    operations["split"] += 1
                    operation_log.append(f"split:{accepted[0]}-{accepted[1]}")
                    budget -= 1

                if _quality_requires_work(mesh_quality(front), target, self.config):
                    changed = True
                    while budget > 0 and changed:
                        changed = False
                        for edge in _edges(front):
                            if self.flip_edge(front, edge, fields, require_improvement=True):
                                operations["flip"] += 1
                                operation_log.append(f"flip:{edge[0]}-{edge[1]}")
                                budget -= 1
                                changed = True
                                break

                if _quality_requires_work(mesh_quality(front), target, self.config):
                    for vertex_index in range(len(front.vertices)):
                        if budget <= 0:
                            break
                        if self.smooth_vertex(
                            front,
                            vertex_index,
                            fields,
                            require_improvement=True,
                        ):
                            operations["smooth"] += 1
                            operation_log.append(f"smooth:{vertex_index}")
                            budget -= 1

                if not _quality_requires_work(mesh_quality(front), target, self.config):
                    break

        after = mesh_quality(front)
        field_error = 0.0
        for name, field in fields.items():
            before_total = field_totals[name]
            error = abs(field.total_amount() - before_total) / max(abs(before_total), 1.0e-300)
            field_error = max(field_error, error)

        scale = max(before_front.equivalent_radius(), target, 1.0e-30)
        return RemeshReport(
            attempted=attempted,
            operations=operations,
            operation_log=tuple(operation_log),
            before=before,
            after=after,
            volume_relative_change=_relative_change(before_front.volume(), front.volume()),
            area_relative_change=_relative_change(before_front.area(), front.area()),
            centroid_relative_change=norm(sub(before_front.centroid(), front.centroid())) / scale,
            field_conservation_relative_error=field_error,
            region_identity_preserved=(
                front.bubble_id == before_front.bubble_id
                and front.mesh_id == before_front.mesh_id
                and front.film_id == before_front.film_id
            ),
            target_edge_length_m=target,
        )
