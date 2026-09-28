"""Production geometry fixtures for the qualified extruded T1 class.

The local T1 films are open, non-volume-contributing test-cell sheets.  Each gas
region also owns a closed volume-support shell against EXTERIOR.  This is the
existing FilmNetwork convention for open far-field cells and lets the topology
transaction exercise exact production volume bookkeeping without inventing a
closed outer foam topology outside the research-qualified local neighborhood.
"""
from __future__ import annotations

import math

from bubblelab.solvers.equilibrium.mesh import SurfaceMesh
from bubblelab.solvers.equilibrium.network import (
    EXTERIOR,
    FilmNetwork,
    FilmPatch,
    GasRegion,
    PlateauJunction,
)
from bubblelab.solvers.transient.network.core import TransientNetworkState

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]


def _polygon_area(points: tuple[Vec2, ...]) -> float:
    return abs(sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    )) * 0.5


def _grid_strip(
    film_id: str,
    adjacent: tuple[str, str],
    start: Vec2,
    end: Vec2,
    depth_m: float,
    resolution_m: float,
    tension: float,
) -> tuple[FilmPatch, int, int]:
    span = math.hypot(end[0] - start[0], end[1] - start[1])
    if span <= 0.0:
        raise ValueError("film span must be positive")
    span_cells = max(1, math.ceil(span / resolution_m))
    depth_cells = max(2, math.ceil(depth_m / resolution_m))
    sample_count = depth_cells + 1
    vertices: list[Vec3] = []
    for span_index in range(span_cells + 1):
        alpha = span_index / span_cells
        x = start[0] + alpha * (end[0] - start[0])
        y = start[1] + alpha * (end[1] - start[1])
        for depth_index in range(sample_count):
            z = -0.5 * depth_m + depth_index * depth_m / depth_cells
            vertices.append((x, y, z))
    faces: list[tuple[int, int, int]] = []
    for span_index in range(span_cells):
        for depth_index in range(depth_cells):
            a = span_index * sample_count + depth_index
            b = (span_index + 1) * sample_count + depth_index
            c = (span_index + 1) * sample_count + depth_index + 1
            d = span_index * sample_count + depth_index + 1
            faces.append((a, b, c))
            faces.append((a, c, d))
    patch = FilmPatch(
        id=film_id,
        mesh=SurfaceMesh.from_iterables(vertices, faces),
        adjacent=adjacent,
        sheet_tension_n_m=tension,
        contributes_to_volume=False,
    )
    return patch, span_cells, depth_cells


def _boundary_indices(span_cells: int, depth_cells: int, at_start: bool) -> tuple[int, ...]:
    sample_count = depth_cells + 1
    base = 0 if at_start else span_cells * sample_count
    return tuple(base + index for index in range(sample_count))


def _tetra_volume_shell(
    film_id: str,
    region_id: str,
    target_volume_m3: float,
    offset: Vec3,
    tension: float,
) -> FilmPatch:
    scale = (6.0 * target_volume_m3) ** (1.0 / 3.0)
    ox, oy, oz = offset
    vertices = (
        (ox, oy, oz),
        (ox + scale, oy, oz),
        (ox, oy + scale, oz),
        (ox, oy, oz + scale),
    )
    faces = (
        (0, 2, 1),
        (0, 1, 3),
        (0, 3, 2),
        (1, 2, 3),
    )
    mesh = SurfaceMesh.from_iterables(vertices, faces)
    if mesh.signed_volume() <= 0.0:
        raise AssertionError("volume-support tetrahedron orientation is invalid")
    return FilmPatch(
        id=film_id,
        mesh=mesh,
        adjacent=(region_id, EXTERIOR),
        sheet_tension_n_m=tension,
        contributes_to_volume=True,
    )


def build_supported_pre_t1_network(
    resolution_m: float = 0.12,
    collapse_fraction: float = 0.35,
    half_extent_m: float = 1.0,
    depth_m: float = 0.6,
    sheet_tension_n_m: float = 1.0,
    id_prefix: str = "",
    origin_xy: Vec2 = (0.0, 0.0),
) -> FilmNetwork:
    """Build the exact qualified four-region production T1 test cell."""
    if resolution_m <= 0.0 or half_extent_m <= 0.0 or depth_m <= 0.0:
        raise ValueError("positive geometric scales are required")
    if not 0.0 < collapse_fraction < 1.0:
        raise ValueError("collapse fraction must lie in (0, 1)")
    if sheet_tension_n_m <= 0.0:
        raise ValueError("sheet tension must be positive")

    def rid(name: str) -> str:
        return f"{id_prefix}{name}"

    def fid(name: str) -> str:
        return f"{id_prefix}film:{name}"

    def jid(name: str) -> str:
        return f"{id_prefix}junction:{name}"

    ox, oy = origin_xy
    length = collapse_fraction * resolution_m
    top = (ox, oy + 0.5 * length)
    bottom = (ox, oy - 0.5 * length)
    nw = (ox - half_extent_m, oy + half_extent_m)
    ne = (ox + half_extent_m, oy + half_extent_m)
    se = (ox + half_extent_m, oy - half_extent_m)
    sw = (ox - half_extent_m, oy - half_extent_m)

    specifications = (
        ("AB:central", (rid("A"), rid("B")), top, bottom),
        ("AC", (rid("A"), rid("C")), top, nw),
        ("BC", (rid("B"), rid("C")), top, ne),
        ("AD", (rid("A"), rid("D")), bottom, sw),
        ("BD", (rid("B"), rid("D")), bottom, se),
    )
    local: dict[str, tuple[FilmPatch, int, int]] = {}
    for name, adjacent, start, end in specifications:
        local[fid(name)] = _grid_strip(
            fid(name),
            adjacent,
            start,
            end,
            depth_m,
            resolution_m,
            sheet_tension_n_m,
        )

    central, central_span, central_depth = local[fid("AB:central")]
    ac, ac_span, ac_depth = local[fid("AC")]
    bc, bc_span, bc_depth = local[fid("BC")]
    ad, ad_span, ad_depth = local[fid("AD")]
    bd, bd_span, bd_depth = local[fid("BD")]
    if len({central_depth, ac_depth, bc_depth, ad_depth, bd_depth}) != 1:
        raise AssertionError("fixture strips must share the extrusion discretization")
    top_junction = PlateauJunction(
        id=jid("top"),
        incident_film_ids=(central.id, ac.id, bc.id),
        vertex_indices_by_film=(
            _boundary_indices(central_span, central_depth, True),
            _boundary_indices(ac_span, ac_depth, True),
            _boundary_indices(bc_span, bc_depth, True),
        ),
    )
    bottom_junction = PlateauJunction(
        id=jid("bottom"),
        incident_film_ids=(central.id, ad.id, bd.id),
        vertex_indices_by_film=(
            _boundary_indices(central_span, central_depth, False),
            _boundary_indices(ad_span, ad_depth, True),
            _boundary_indices(bd_span, bd_depth, True),
        ),
    )

    cells = (
        (rid("A"), (nw, top, bottom, sw)),
        (rid("B"), (top, ne, se, bottom)),
        (rid("C"), (nw, ne, top)),
        (rid("D"), (bottom, se, sw)),
    )
    targets = {
        region_id: _polygon_area(cell) * depth_m
        for region_id, cell in cells
    }
    regions = tuple(GasRegion(region_id, targets[region_id]) for region_id, _ in cells)
    shells = tuple(
        _tetra_volume_shell(
            film_id=f"{id_prefix}volume:{name}",
            region_id=rid(name),
            target_volume_m3=targets[rid(name)],
            offset=(ox + 4.0 + 2.5 * index, oy + 4.0, 2.0),
            tension=0.05 * sheet_tension_n_m,
        )
        for index, name in enumerate(("A", "B", "C", "D"))
    )
    patches = tuple(item[0] for item in local.values()) + shells
    network = FilmNetwork(regions, patches, (top_junction, bottom_junction))
    network.validate()
    for region in regions:
        error = abs(network.region_volume(region.id) - region.target_volume_m3) / region.target_volume_m3
        if error > 1.0e-12:
            raise AssertionError("fixture volume-support shell does not match its target")
    return network


def build_supported_pre_t1_state(**kwargs: object) -> TransientNetworkState:
    return TransientNetworkState.from_network(build_supported_pre_t1_network(**kwargs))


def combine_disjoint_networks(*networks: FilmNetwork) -> FilmNetwork:
    """Combine qualified local cells to exercise ambiguity rejection."""
    if not networks:
        raise ValueError("at least one network is required")
    regions = tuple(region for network in networks for region in network.regions)
    patches = tuple(patch for network in networks for patch in network.patches)
    junctions = tuple(junction for network in networks for junction in network.junctions)
    combined = FilmNetwork(regions, patches, junctions)
    combined.validate()
    return combined


def combine_disjoint_states(*states: TransientNetworkState) -> TransientNetworkState:
    return TransientNetworkState.from_network(
        combine_disjoint_networks(*(state.to_network() for state in states))
    )


build_pre_t1_network = build_supported_pre_t1_network
build_pre_t1_state = build_supported_pre_t1_state
