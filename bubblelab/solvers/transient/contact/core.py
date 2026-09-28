"""Deterministic supported-class contact formation for two tracked soap-film fronts."""
from __future__ import annotations

from dataclasses import dataclass
import math
import statistics

from ..geometry import FilmFront, Vec3, add, cross, dot, mean, mul, norm, sub, unit
from ..network.core import TransientNetworkState
from ...equilibrium.mesh import SurfaceMesh
from ...equilibrium.network import (
    EXTERIOR,
    FilmNetwork,
    FilmPatch,
    GasRegion,
    PlateauJunction,
    project_region_volumes,
)


@dataclass(frozen=True)
class ContactSettings:
    """Resolution-aware settings for the supported isolated two-front contact."""

    threshold_edge_fraction: float = 0.45
    max_interpenetration_edge_fraction: float = 0.35
    projection_relative_tolerance: float = 5.0e-10
    projection_iterations: int = 24
    local_volume_budget_fraction: float = 0.12
    candidate_vertex_limit: int = 24

    def validate(self) -> None:
        if not 0.0 < self.threshold_edge_fraction <= 1.0:
            raise ValueError("contact threshold edge fraction must lie in (0, 1]")
        if not 0.0 < self.max_interpenetration_edge_fraction <= 1.0:
            raise ValueError("interpenetration edge fraction must lie in (0, 1]")
        if self.projection_relative_tolerance <= 0.0:
            raise ValueError("projection tolerance must be positive")
        if self.projection_iterations < 1:
            raise ValueError("projection iterations must be positive")
        if not 0.0 < self.local_volume_budget_fraction < 1.0:
            raise ValueError("local volume budget fraction must lie in (0, 1)")
        if self.candidate_vertex_limit < 4:
            raise ValueError("candidate vertex limit must be at least four")


@dataclass(frozen=True)
class ContactObservation:
    parent_ids: tuple[str, str]
    closest_vertex_indices: tuple[int, int]
    closest_surface_locations_m: tuple[Vec3, Vec3]
    nearest_vertex_distance_m: float
    axial_gap_m: float
    separation_metric_m: float
    resolution_m: float
    threshold_m: float
    normal_a_to_b: Vec3
    anchor_vertex_indices: tuple[int, int]
    contact_ring_seed_indices: tuple[tuple[int, ...], tuple[int, ...]]
    contact: bool
    event_key: tuple[object, ...]


@dataclass(frozen=True)
class ContactFormationResult:
    observation: ContactObservation
    raw_network: FilmNetwork
    network: FilmNetwork
    state: TransientNetworkState
    contact_ring_points_m: tuple[Vec3, ...]
    raw_relative_volume_errors: tuple[tuple[str, float], ...]
    projected_relative_volume_errors: tuple[tuple[str, float], ...]
    local_volume_budget_fraction: float

    def signature(self) -> tuple[object, ...]:
        return (
            self.observation.event_key,
            self.state.topology_signature(),
            tuple(tuple(round(value, 15) for value in point) for point in self.state.positions),
            self.contact_ring_points_m,
            self.raw_relative_volume_errors,
            self.projected_relative_volume_errors,
        )


class ContactFormationError(ValueError):
    pass


def _ordered(front_a: FilmFront, front_b: FilmFront) -> tuple[FilmFront, FilmFront]:
    if front_a.bubble_id == front_b.bubble_id:
        raise ContactFormationError("contact parents require distinct stable bubble IDs")
    return tuple(sorted((front_a, front_b), key=lambda front: front.bubble_id))  # type: ignore[return-value]


def _median_edge_length(front: FilmFront) -> float:
    seen: set[tuple[int, int]] = set()
    lengths: list[float] = []
    for face in front.faces:
        for left, right in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            edge = (left, right) if left < right else (right, left)
            if edge not in seen:
                seen.add(edge)
                lengths.append(norm(sub(front.vertices[left], front.vertices[right])))
    if not lengths:
        raise ContactFormationError("contact detection requires a mesh with edges")
    return statistics.median(lengths)


def _nearest_vertex_pair(front_a: FilmFront, front_b: FilmFront) -> tuple[int, int, float]:
    best: tuple[float, int, int] | None = None
    for index_a, point_a in enumerate(front_a.vertices):
        for index_b, point_b in enumerate(front_b.vertices):
            delta = sub(point_b, point_a)
            distance2 = dot(delta, delta)
            candidate = (distance2, index_a, index_b)
            if best is None or candidate < best:
                best = candidate
    assert best is not None
    return best[1], best[2], math.sqrt(best[0])


def _star_cycle(front: FilmFront, anchor: int) -> tuple[int, ...]:
    if anchor < 0 or anchor >= len(front.vertices):
        raise ContactFormationError("contact anchor lies outside parent mesh")
    ring_edges: list[tuple[int, int]] = []
    for face in front.faces:
        if anchor not in face:
            continue
        others = [index for index in face if index != anchor]
        if len(others) != 2:
            raise ContactFormationError("invalid triangular vertex star")
        ring_edges.append((others[0], others[1]))
    if len(ring_edges) < 3:
        raise ContactFormationError("contact anchor does not have a closed one-ring")

    adjacency: dict[int, set[int]] = {}
    for left, right in ring_edges:
        adjacency.setdefault(left, set()).add(right)
        adjacency.setdefault(right, set()).add(left)
    if any(len(neighbors) != 2 for neighbors in adjacency.values()):
        raise ContactFormationError("contact anchor one-ring is not manifold")

    start = min(adjacency)
    next_vertex = min(adjacency[start])
    cycle = [start]
    previous = start
    current = next_vertex
    while current != start:
        if current in cycle:
            raise ContactFormationError("contact anchor one-ring self-intersects topologically")
        cycle.append(current)
        options = sorted(adjacency[current] - {previous})
        if len(options) != 1:
            raise ContactFormationError("contact anchor one-ring traversal is ambiguous")
        previous, current = current, options[0]
        if len(cycle) > len(adjacency):
            raise ContactFormationError("contact anchor one-ring traversal did not close")
    if len(cycle) != len(adjacency):
        raise ContactFormationError("contact anchor one-ring is disconnected")
    return tuple(cycle)


def _select_compatible_anchors(
    front_a: FilmFront,
    front_b: FilmFront,
    location_a: Vec3,
    location_b: Vec3,
    limit: int,
) -> tuple[int, int, tuple[int, ...], tuple[int, ...]]:
    candidates_a = sorted(
        range(len(front_a.vertices)),
        key=lambda index: (dot(sub(front_a.vertices[index], location_a), sub(front_a.vertices[index], location_a)), index),
    )[:limit]
    candidates_b = sorted(
        range(len(front_b.vertices)),
        key=lambda index: (dot(sub(front_b.vertices[index], location_b), sub(front_b.vertices[index], location_b)), index),
    )[:limit]

    stars_a: dict[int, tuple[int, ...]] = {}
    stars_b: dict[int, tuple[int, ...]] = {}
    for index in candidates_a:
        try:
            stars_a[index] = _star_cycle(front_a, index)
        except ContactFormationError:
            pass
    for index in candidates_b:
        try:
            stars_b[index] = _star_cycle(front_b, index)
        except ContactFormationError:
            pass

    best: tuple[float, int, int] | None = None
    for index_a, ring_a in stars_a.items():
        for index_b, ring_b in stars_b.items():
            if len(ring_a) != len(ring_b) or len(ring_a) < 5:
                continue
            da = sub(front_a.vertices[index_a], location_a)
            db = sub(front_b.vertices[index_b], location_b)
            pair = sub(front_b.vertices[index_b], front_a.vertices[index_a])
            score = dot(da, da) + dot(db, db) + 0.05 * dot(pair, pair)
            candidate = (score, index_a, index_b)
            if best is None or candidate < best:
                best = candidate
    if best is None:
        raise ContactFormationError(
            "no compatible local one-rings were found for deterministic shared-film surgery"
        )
    ia, ib = best[1], best[2]
    return ia, ib, stars_a[ia], stars_b[ib]


def observe_contact(
    front_a: FilmFront,
    front_b: FilmFront,
    settings: ContactSettings | None = None,
) -> ContactObservation:
    """Measure mesh-based approach and return a deterministic contact decision."""
    cfg = settings or ContactSettings()
    cfg.validate()
    a, b = _ordered(front_a, front_b)
    h_a = _median_edge_length(a)
    h_b = _median_edge_length(b)
    resolution = min(h_a, h_b)
    threshold = cfg.threshold_edge_fraction * resolution

    index_a, index_b, nearest = _nearest_vertex_pair(a, b)
    location_a = a.vertices[index_a]
    location_b = b.vertices[index_b]

    center_axis = unit(sub(b.centroid(), a.centroid()))
    if norm(center_axis) <= 1.0e-15:
        center_axis = unit(sub(location_b, location_a))
    if norm(center_axis) <= 1.0e-15:
        raise ContactFormationError("contact normal is undefined for coincident parent geometry")

    support_a = max(dot(vertex, center_axis) for vertex in a.vertices)
    support_b = min(dot(vertex, center_axis) for vertex in b.vertices)
    axial_gap = support_b - support_a
    if axial_gap < -cfg.max_interpenetration_edge_fraction * resolution:
        raise ContactFormationError(
            "parents exceed the supported interpenetration budget before contact formation"
        )

    separation = min(nearest, max(axial_gap, 0.0))
    normal = unit(sub(location_b, location_a))
    if norm(normal) <= 1.0e-15 or dot(normal, center_axis) < 0.25:
        normal = center_axis
    elif dot(normal, center_axis) < 0.0:
        normal = mul(normal, -1.0)

    anchor_a, anchor_b, ring_a, ring_b = _select_compatible_anchors(
        a,
        b,
        location_a,
        location_b,
        cfg.candidate_vertex_limit,
    )
    contacted = separation <= threshold
    event_key = (
        a.bubble_id,
        b.bubble_id,
        anchor_a,
        anchor_b,
        tuple(ring_a),
        tuple(ring_b),
        round(separation, 15),
        round(threshold, 15),
    )
    return ContactObservation(
        parent_ids=(a.bubble_id, b.bubble_id),
        closest_vertex_indices=(index_a, index_b),
        closest_surface_locations_m=(location_a, location_b),
        nearest_vertex_distance_m=nearest,
        axial_gap_m=axial_gap,
        separation_metric_m=separation,
        resolution_m=resolution,
        threshold_m=threshold,
        normal_a_to_b=normal,
        anchor_vertex_indices=(anchor_a, anchor_b),
        contact_ring_seed_indices=(ring_a, ring_b),
        contact=contacted,
        event_key=event_key,
    )


def _plane_basis(normal: Vec3) -> tuple[Vec3, Vec3]:
    reference = (1.0, 0.0, 0.0)
    if abs(dot(normal, reference)) > 0.80:
        reference = (0.0, 1.0, 0.0)
    axis_u = unit(cross(reference, normal))
    axis_v = unit(cross(normal, axis_u))
    if norm(axis_u) <= 1.0e-15 or norm(axis_v) <= 1.0e-15:
        raise ContactFormationError("failed to build a contact-plane basis")
    return axis_u, axis_v


def _project_to_plane(point: Vec3, center: Vec3, normal: Vec3) -> Vec3:
    return sub(point, mul(normal, dot(sub(point, center), normal)))


def _angular_order(
    front: FilmFront,
    indices: tuple[int, ...],
    center: Vec3,
    normal: Vec3,
) -> tuple[int, ...]:
    axis_u, axis_v = _plane_basis(normal)

    def key(index: int) -> tuple[float, int]:
        radial = sub(_project_to_plane(front.vertices[index], center, normal), center)
        angle = math.atan2(dot(radial, axis_v), dot(radial, axis_u))
        return angle, index

    return tuple(sorted(indices, key=key))


def _align_ring(
    front_a: FilmFront,
    ring_a: tuple[int, ...],
    front_b: FilmFront,
    ring_b: tuple[int, ...],
    center: Vec3,
    normal: Vec3,
) -> tuple[tuple[int, ...], tuple[int, ...], tuple[Vec3, ...]]:
    ordered_a = _angular_order(front_a, ring_a, center, normal)
    ordered_b_base = _angular_order(front_b, ring_b, center, normal)
    projected_a = tuple(_project_to_plane(front_a.vertices[index], center, normal) for index in ordered_a)
    count = len(ordered_a)

    best: tuple[float, int, int] | None = None
    best_order_b: tuple[int, ...] | None = None
    for reverse in (0, 1):
        source = ordered_b_base if reverse == 0 else tuple(reversed(ordered_b_base))
        for shift in range(count):
            candidate_order = tuple(source[(sample + shift) % count] for sample in range(count))
            projected_b = tuple(
                _project_to_plane(front_b.vertices[index], center, normal)
                for index in candidate_order
            )
            mismatch = math.fsum(
                dot(sub(point_b, point_a), sub(point_b, point_a))
                for point_a, point_b in zip(projected_a, projected_b)
            )
            candidate = (mismatch, reverse, shift)
            if best is None or candidate < best:
                best = candidate
                best_order_b = candidate_order
    assert best_order_b is not None

    projected_b = tuple(
        _project_to_plane(front_b.vertices[index], center, normal)
        for index in best_order_b
    )
    common = tuple(
        mul(add(point_a, point_b), 0.5)
        for point_a, point_b in zip(projected_a, projected_b)
    )
    ring_center = mean(common)
    if min(norm(sub(point, ring_center)) for point in common) <= 1.0e-12:
        raise ContactFormationError("contact ring collapsed during local surgery")
    return ordered_a, best_order_b, common


def _carve_parent_patch(
    front: FilmFront,
    anchor: int,
    ordered_ring: tuple[int, ...],
    common_ring: tuple[Vec3, ...],
) -> tuple[SurfaceMesh, tuple[int, ...]]:
    vertices = list(front.vertices)
    for index, point in zip(ordered_ring, common_ring):
        vertices[index] = point
    faces = [face for face in front.faces if anchor not in face]
    used = sorted({index for face in faces for index in face})
    remap = {old: new for new, old in enumerate(used)}
    compact_vertices = tuple(vertices[index] for index in used)
    compact_faces = tuple(tuple(remap[index] for index in face) for face in faces)
    ring_indices = tuple(remap[index] for index in ordered_ring)
    mesh = SurfaceMesh.from_iterables(compact_vertices, compact_faces)
    mesh.validate(require_closed=False, require_outward=False)
    return mesh, ring_indices


def _shared_disk(
    common_ring: tuple[Vec3, ...],
    normal: Vec3,
) -> tuple[SurfaceMesh, tuple[int, ...]]:
    center = mean(common_ring)
    vertices = (center,) + tuple(common_ring)
    count = len(common_ring)
    faces = tuple((0, 1 + sample, 1 + ((sample + 1) % count)) for sample in range(count))
    mesh = SurfaceMesh.from_iterables(vertices, faces)
    first = mesh.faces[0]
    first_normal = cross(
        sub(mesh.vertices[first[1]], mesh.vertices[first[0]]),
        sub(mesh.vertices[first[2]], mesh.vertices[first[0]]),
    )
    if dot(first_normal, normal) < 0.0:
        faces = tuple((a, c, b) for a, b, c in faces)
        mesh = SurfaceMesh.from_iterables(vertices, faces)
    mesh.validate(require_closed=False, require_outward=False)
    return mesh, tuple(range(1, count + 1))


def _volume_errors(network: FilmNetwork) -> tuple[tuple[str, float], ...]:
    return tuple(
        (
            region.id,
            abs(network.region_volume(region.id) - region.target_volume_m3)
            / region.target_volume_m3,
        )
        for region in network.regions
    )


def form_contact(
    front_a: FilmFront,
    front_b: FilmFront,
    settings: ContactSettings | None = None,
) -> ContactFormationResult:
    """Carve one local contact and hand it off as a shared-DOF transient network."""
    cfg = settings or ContactSettings()
    cfg.validate()
    a, b = _ordered(front_a, front_b)
    observation = observe_contact(a, b, cfg)
    if not observation.contact:
        raise ContactFormationError(
            f"fronts are separated by {observation.separation_metric_m:.6g} m; "
            f"contact threshold is {observation.threshold_m:.6g} m"
        )
    if not math.isclose(
        a.surface_tension_n_m,
        b.surface_tension_n_m,
        rel_tol=1.0e-12,
        abs_tol=1.0e-15,
    ):
        raise ContactFormationError(
            "supported contact formation requires matching parent sheet tensions"
        )

    contact_center = mul(
        add(
            observation.closest_surface_locations_m[0],
            observation.closest_surface_locations_m[1],
        ),
        0.5,
    )
    ring_a, ring_b, common_ring = _align_ring(
        a,
        observation.contact_ring_seed_indices[0],
        b,
        observation.contact_ring_seed_indices[1],
        contact_center,
        observation.normal_a_to_b,
    )
    mesh_a, ring_indices_a = _carve_parent_patch(
        a,
        observation.anchor_vertex_indices[0],
        ring_a,
        common_ring,
    )
    mesh_b, ring_indices_b = _carve_parent_patch(
        b,
        observation.anchor_vertex_indices[1],
        ring_b,
        common_ring,
    )
    shared_mesh, shared_ring_indices = _shared_disk(common_ring, observation.normal_a_to_b)

    shared_id = f"shared:{a.bubble_id}:{b.bubble_id}"
    junction_id = f"contact-ring:{a.bubble_id}:{b.bubble_id}"
    patches = (
        FilmPatch(
            a.film_id,
            mesh_a,
            (a.bubble_id, EXTERIOR),
            a.surface_tension_n_m,
        ),
        FilmPatch(
            b.film_id,
            mesh_b,
            (b.bubble_id, EXTERIOR),
            b.surface_tension_n_m,
        ),
        FilmPatch(
            shared_id,
            shared_mesh,
            (a.bubble_id, b.bubble_id),
            0.5 * (a.surface_tension_n_m + b.surface_tension_n_m),
        ),
    )
    regions = (
        GasRegion(a.bubble_id, float(a.target_volume_m3)),
        GasRegion(b.bubble_id, float(b.target_volume_m3)),
    )
    junction = PlateauJunction(
        id=junction_id,
        incident_film_ids=(a.film_id, shared_id, b.film_id),
        vertex_indices_by_film=(
            ring_indices_a,
            shared_ring_indices,
            ring_indices_b,
        ),
    )
    raw_network = FilmNetwork(regions, patches, (junction,))
    raw_network.validate()
    raw_errors = _volume_errors(raw_network)
    if max(error for _, error in raw_errors) > cfg.local_volume_budget_fraction:
        raise ContactFormationError(
            "local contact surgery exceeded the configured pre-projection volume budget"
        )

    projected = project_region_volumes(
        raw_network,
        relative_tolerance=cfg.projection_relative_tolerance,
        max_iterations=cfg.projection_iterations,
    )
    projected.validate()
    projected_errors = _volume_errors(projected)
    if max(error for _, error in projected_errors) > 5.0 * cfg.projection_relative_tolerance:
        raise ContactFormationError("coupled region-volume projection did not converge")

    state = TransientNetworkState.from_network(projected)
    if state.shared_dof_count() != len(common_ring):
        raise ContactFormationError(
            "transient handoff did not collapse the contact ring to authoritative shared DOFs"
        )
    return ContactFormationResult(
        observation=observation,
        raw_network=raw_network,
        network=projected,
        state=state,
        contact_ring_points_m=common_ring,
        raw_relative_volume_errors=raw_errors,
        projected_relative_volume_errors=projected_errors,
        local_volume_budget_fraction=cfg.local_volume_budget_fraction,
    )
