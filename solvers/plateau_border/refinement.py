"""Conforming spatial refinement utilities for Plateau-border qualification."""
from __future__ import annotations

from bubblelab.solvers.equilibrium.mesh import SurfaceMesh
from bubblelab.solvers.equilibrium.network import FilmNetwork, FilmPatch, PlateauJunction
from bubblelab.solvers.transient.network.core import TransientNetworkState


def conforming_subdivide_state(state: TransientNetworkState) -> TransientNetworkState:
    """Subdivide the five local sheets without changing their physical geometry."""
    network = state.to_network()
    midpoint_maps: dict[str, dict[tuple[int, int], int]] = {}
    patches = []
    for patch in network.patches:
        if patch.contributes_to_volume:
            patches.append(patch)
            continue
        vertices = list(patch.mesh.vertices)
        midpoints: dict[tuple[int, int], int] = {}

        def midpoint(left: int, right: int) -> int:
            key = tuple(sorted((left, right)))
            if key not in midpoints:
                a = vertices[left]
                b = vertices[right]
                midpoints[key] = len(vertices)
                vertices.append(tuple((a[axis] + b[axis]) * 0.5 for axis in range(3)))
            return midpoints[key]

        faces = []
        for a, b, c in patch.mesh.faces:
            ab = midpoint(a, b)
            bc = midpoint(b, c)
            ca = midpoint(c, a)
            faces.extend(((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)))
        original_fixed = set(patch.fixed_vertex_indices)
        fixed = set(original_fixed)
        fixed.update(
            index
            for (left, right), index in midpoints.items()
            if left in original_fixed and right in original_fixed
        )
        patches.append(FilmPatch(
            id=patch.id,
            mesh=SurfaceMesh.from_iterables(vertices, faces),
            adjacent=patch.adjacent,
            sheet_tension_n_m=patch.sheet_tension_n_m,
            fixed_vertex_indices=tuple(sorted(fixed)),
            contributes_to_volume=patch.contributes_to_volume,
        ))
        midpoint_maps[patch.id] = midpoints

    junctions = []
    for junction in network.junctions:
        rows = []
        for film_id, row in zip(junction.incident_film_ids, junction.vertex_indices_by_film):
            midpoints = midpoint_maps[film_id]
            refined = []
            for left, right in zip(row, row[1:]):
                refined.extend((left, midpoints[tuple(sorted((left, right)))]))
            refined.append(row[-1])
            rows.append(tuple(refined))
        junctions.append(PlateauJunction(
            id=junction.id,
            incident_film_ids=junction.incident_film_ids,
            vertex_indices_by_film=tuple(rows),
        ))
    refined = FilmNetwork(network.regions, tuple(patches), tuple(junctions))
    refined.validate()
    return TransientNetworkState.from_network(refined)
