"""Deterministic two-region film-network construction for B04/B05."""
from __future__ import annotations

import math

from .mesh import SurfaceMesh
from .network import EXTERIOR, FilmNetwork, FilmPatch, GasRegion


def _oriented(mesh: SurfaceMesh, axis_sign: float) -> SurfaceMesh:
    if mesh.face_normals()[0][0] * axis_sign >= 0.0:
        return mesh
    return SurfaceMesh(mesh.vertices, tuple((a, c, b) for a, b, c in mesh.faces))


def spherical_outer_cap(
    *,
    axis_sign: int,
    radius_m: float,
    contact_radius_m: float,
    radial_rings: int,
    azimuth_segments: int,
) -> tuple[SurfaceMesh, tuple[int, ...]]:
    if axis_sign not in (-1, 1):
        raise ValueError("axis_sign must be -1 or +1")
    if not (0.0 < contact_radius_m < radius_m):
        raise ValueError("contact radius must lie inside the sphere radius")
    if radial_rings < 2 or azimuth_segments < 6:
        raise ValueError("insufficient cap resolution")

    center_x = axis_sign * math.sqrt(radius_m * radius_m - contact_radius_m * contact_radius_m)
    boundary_angle = math.acos(-abs(center_x) / radius_m)
    vertices = [(center_x + axis_sign * radius_m, 0.0, 0.0)]
    for ring in range(1, radial_rings + 1):
        angle = boundary_angle * ring / radial_rings
        x = center_x + axis_sign * radius_m * math.cos(angle)
        radial = radius_m * math.sin(angle)
        for segment in range(azimuth_segments):
            phase = 2.0 * math.pi * segment / azimuth_segments
            vertices.append((x, radial * math.cos(phase), radial * math.sin(phase)))

    faces: list[tuple[int, int, int]] = []
    for segment in range(azimuth_segments):
        faces.append((0, 1 + segment, 1 + (segment + 1) % azimuth_segments))
    for ring in range(1, radial_rings):
        inner = 1 + (ring - 1) * azimuth_segments
        outer = 1 + ring * azimuth_segments
        for segment in range(azimuth_segments):
            a = inner + segment
            b = inner + (segment + 1) % azimuth_segments
            c = outer + segment
            d = outer + (segment + 1) % azimuth_segments
            faces.extend(((a, c, d), (a, d, b)))

    mesh = _oriented(SurfaceMesh.from_iterables(vertices, faces), float(axis_sign))
    fixed = tuple(range(1 + (radial_rings - 1) * azimuth_segments, 1 + radial_rings * azimuth_segments))
    return mesh, fixed


def shared_disk_or_spherical_cap(
    *,
    contact_radius_m: float,
    radial_rings: int,
    azimuth_segments: int,
    signed_curvature_1_m: float = 0.0,
) -> tuple[SurfaceMesh, tuple[int, ...]]:
    if contact_radius_m <= 0.0:
        raise ValueError("contact radius must be positive")
    if radial_rings < 2 or azimuth_segments < 6:
        raise ValueError("insufficient shared-film resolution")

    curvature = signed_curvature_1_m
    sphere_radius = math.inf if abs(curvature) <= 1.0e-15 else 2.0 / abs(curvature)
    if not math.isinf(sphere_radius) and sphere_radius <= contact_radius_m:
        raise ValueError("requested shared-film curvature cannot span the contact ring")
    curvature_sign = 1.0 if curvature >= 0.0 else -1.0
    center_x = 0.0 if math.isinf(sphere_radius) else -curvature_sign * math.sqrt(
        sphere_radius * sphere_radius - contact_radius_m * contact_radius_m
    )

    vertices = []
    for ring in range(radial_rings + 1):
        radial = contact_radius_m * ring / radial_rings
        if ring == 0:
            x = 0.0 if math.isinf(sphere_radius) else center_x + curvature_sign * sphere_radius
            vertices.append((x, 0.0, 0.0))
            continue
        x = 0.0 if math.isinf(sphere_radius) else center_x + curvature_sign * math.sqrt(
            sphere_radius * sphere_radius - radial * radial
        )
        for segment in range(azimuth_segments):
            phase = 2.0 * math.pi * segment / azimuth_segments
            vertices.append((x, radial * math.cos(phase), radial * math.sin(phase)))

    faces: list[tuple[int, int, int]] = []
    for segment in range(azimuth_segments):
        faces.append((0, 1 + segment, 1 + (segment + 1) % azimuth_segments))
    for ring in range(1, radial_rings):
        inner = 1 + (ring - 1) * azimuth_segments
        outer = 1 + ring * azimuth_segments
        for segment in range(azimuth_segments):
            a = inner + segment
            b = inner + (segment + 1) % azimuth_segments
            c = outer + segment
            d = outer + (segment + 1) % azimuth_segments
            faces.extend(((a, c, d), (a, d, b)))

    mesh = _oriented(SurfaceMesh.from_iterables(vertices, faces), 1.0)
    fixed = tuple(range(1 + (radial_rings - 1) * azimuth_segments, 1 + radial_rings * azimuth_segments))
    return mesh, fixed


def reference_two_bubble_network(
    *,
    radius_a_m: float,
    radius_b_m: float,
    contact_radius_m: float,
    sheet_tension_n_m: float,
    outer_rings: int = 16,
    shared_rings: int = 18,
    azimuth_segments: int = 96,
) -> FilmNetwork:
    """Build a stationary analytical reference, then use its volumes only as targets."""
    outer_a, fixed_a = spherical_outer_cap(
        axis_sign=-1,
        radius_m=radius_a_m,
        contact_radius_m=contact_radius_m,
        radial_rings=outer_rings,
        azimuth_segments=azimuth_segments,
    )
    outer_b, fixed_b = spherical_outer_cap(
        axis_sign=1,
        radius_m=radius_b_m,
        contact_radius_m=contact_radius_m,
        radial_rings=outer_rings,
        azimuth_segments=azimuth_segments,
    )
    pressure_difference = 2.0 * sheet_tension_n_m * (1.0 / radius_a_m - 1.0 / radius_b_m)
    shared_curvature = pressure_difference / sheet_tension_n_m
    shared, fixed_shared = shared_disk_or_spherical_cap(
        contact_radius_m=contact_radius_m,
        radial_rings=shared_rings,
        azimuth_segments=azimuth_segments,
        signed_curvature_1_m=shared_curvature,
    )

    patches = (
        FilmPatch("outer-a", outer_a, ("bubble-a", EXTERIOR), sheet_tension_n_m, fixed_a),
        FilmPatch("outer-b", outer_b, ("bubble-b", EXTERIOR), sheet_tension_n_m, fixed_b),
        FilmPatch("shared-ab", shared, ("bubble-a", "bubble-b"), sheet_tension_n_m, fixed_shared),
    )
    provisional = FilmNetwork((GasRegion("bubble-a", 1.0), GasRegion("bubble-b", 1.0)), patches)
    targets = (
        GasRegion("bubble-a", provisional.region_volume("bubble-a")),
        GasRegion("bubble-b", provisional.region_volume("bubble-b")),
    )
    network = FilmNetwork(targets, patches)
    network.validate()
    return network


def perturb_shared_film(network: FilmNetwork, amplitude_m: float) -> FilmNetwork:
    """Apply a smooth deterministic normal perturbation; the contact ring stays fixed."""
    shared = next(patch for patch in network.patches if patch.id == "shared-ab")
    contact_radius = max(math.hypot(y, z) for _, y, z in shared.mesh.vertices)
    patches = []
    for patch in network.patches:
        if patch.id != "shared-ab":
            patches.append(patch)
            continue
        fixed = set(patch.fixed_vertex_indices)
        vertices = []
        for index, (x, y, z) in enumerate(patch.mesh.vertices):
            radial = math.hypot(y, z)
            displacement = 0.0 if index in fixed else amplitude_m * (1.0 - (radial / contact_radius) ** 2)
            vertices.append((x + displacement, y, z))
        patches.append(FilmPatch(
            id=patch.id,
            mesh=patch.mesh.with_vertices(vertices),
            adjacent=patch.adjacent,
            sheet_tension_n_m=patch.sheet_tension_n_m,
            fixed_vertex_indices=patch.fixed_vertex_indices,
        ))
    return FilmNetwork(network.regions, tuple(patches))
