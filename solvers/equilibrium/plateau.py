"""Deterministic three-film Plateau-junction geometry for the B06 benchmark."""
from __future__ import annotations

import math

from .mesh import SurfaceMesh
from .network import EXTERIOR, FilmNetwork, FilmPatch, GasRegion, PlateauJunction


def _regular_tetrahedron(center: tuple[float, float, float], scale_m: float) -> SurfaceMesh:
    cx, cy, cz = center
    raw = (
        (1.0, 1.0, 1.0),
        (1.0, -1.0, -1.0),
        (-1.0, 1.0, -1.0),
        (-1.0, -1.0, 1.0),
    )
    vertices = tuple(
        (cx + scale_m * x, cy + scale_m * y, cz + scale_m * z)
        for x, y, z in raw
    )
    faces = ((0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3))
    return SurfaceMesh(vertices, faces).oriented_outward()


def _twisted_strip(
    *,
    base_angle_rad: float,
    longitudinal_segments: int,
    junction_xy: tuple[float, float],
    radius_m: float,
    height_m: float,
    twist_rad: float,
    forward_diagonal: bool,
) -> tuple[SurfaceMesh, tuple[int, ...], tuple[int, ...]]:
    if longitudinal_segments < 4:
        raise ValueError("Plateau strip requires at least four longitudinal segments")
    if radius_m <= 0.0 or height_m <= 0.0:
        raise ValueError("Plateau strip dimensions must be positive")

    z_values = tuple(
        -0.5 * height_m + height_m * index / longitudinal_segments
        for index in range(longitudinal_segments + 1)
    )
    vertices = [(junction_xy[0], junction_xy[1], z) for z in z_values]
    for z in z_values:
        phase = base_angle_rad + twist_rad * (z / height_m)
        vertices.append((radius_m * math.cos(phase), radius_m * math.sin(phase), z))

    count = longitudinal_segments + 1
    junction_indices = tuple(range(count))
    outer_indices = tuple(range(count, 2 * count))
    faces: list[tuple[int, int, int]] = []
    for index in range(longitudinal_segments):
        j0, j1 = index, index + 1
        o0, o1 = count + index, count + index + 1
        if forward_diagonal:
            faces.extend(((j0, o0, o1), (j0, o1, j1)))
        else:
            faces.extend(((j0, o0, j1), (o0, o1, j1)))

    return SurfaceMesh.from_iterables(vertices, faces), junction_indices, outer_indices


def reference_plateau_network(
    *,
    longitudinal_segments: int = 48,
    tensions_n_m: tuple[float, float, float] = (0.05, 0.05, 0.05),
    junction_offset_m: tuple[float, float] = (1.2e-3, -0.7e-3),
    radius_m: float = 6.0e-3,
    height_m: float = 12.0e-3,
    twist_rad: float = 0.25,
) -> FilmNetwork:
    """Construct a perturbed, volume-constrained three-film numerical test cell.

    The open junction sheets represent the local far field and are excluded from
    gas-volume closure. Each gas region has an independent regular tetrahedral
    closure surface that is already stationary under its own volume constraint.
    This keeps B06 focused on the triple-line first variation while retaining the
    accepted coupled volume-projection machinery.

    The continuous far field is three-fold symmetric. Alternating strip diagonals
    introduce a deterministic discretization bias that vanishes with longitudinal
    refinement, so the angle-convergence test is not a hard-coded 120-degree case.
    """
    if len(tensions_n_m) != 3 or any(value <= 0.0 for value in tensions_n_m):
        raise ValueError("three positive film tensions are required")

    film_ids = ("film-ab", "film-bc", "film-ca")
    adjacency = (
        ("bubble-a", "bubble-b"),
        ("bubble-b", "bubble-c"),
        ("bubble-c", "bubble-a"),
    )
    forward = (True, False, True)
    patches: list[FilmPatch] = []
    junction_indices: list[tuple[int, ...]] = []

    for index, (film_id, adjacent, tension) in enumerate(zip(film_ids, adjacency, tensions_n_m)):
        mesh, line_indices, outer_indices = _twisted_strip(
            base_angle_rad=2.0 * math.pi * index / 3.0,
            longitudinal_segments=longitudinal_segments,
            junction_xy=junction_offset_m,
            radius_m=radius_m,
            height_m=height_m,
            twist_rad=twist_rad,
            forward_diagonal=forward[index],
        )
        patches.append(FilmPatch(
            id=film_id,
            mesh=mesh,
            adjacent=adjacent,
            sheet_tension_n_m=tension,
            fixed_vertex_indices=outer_indices,
            contributes_to_volume=False,
        ))
        junction_indices.append(line_indices)

    shell_tension = sum(tensions_n_m) / 3.0
    shell_centers = (
        (-2.0e-2, 2.0e-2, 0.0),
        (2.0e-2, 2.0e-2, 0.0),
        (0.0, -2.4e-2, 0.0),
    )
    region_ids = ("bubble-a", "bubble-b", "bubble-c")
    for region_id, center in zip(region_ids, shell_centers):
        patches.append(FilmPatch(
            id=f"outer-{region_id[-1]}",
            mesh=_regular_tetrahedron(center, 2.0e-3),
            adjacent=(region_id, EXTERIOR),
            sheet_tension_n_m=shell_tension,
        ))

    junction = PlateauJunction(
        id="plateau-junction-0",
        incident_film_ids=film_ids,
        vertex_indices_by_film=tuple(junction_indices),
        normal_plane_only=True,
        rigid_normal_translation=True,
    )
    provisional = FilmNetwork(
        tuple(GasRegion(region_id, 1.0) for region_id in region_ids),
        tuple(patches),
        (junction,),
    )
    targets = tuple(
        GasRegion(region_id, provisional.region_volume(region_id))
        for region_id in region_ids
    )
    network = FilmNetwork(targets, tuple(patches), (junction,))
    network.validate()
    return network
