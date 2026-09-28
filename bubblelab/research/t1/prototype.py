"""Deterministic eligibility and narrow-class T1 neighbor-switch prototype."""
from __future__ import annotations

from dataclasses import dataclass
import math
from .model import (
    FilmPatch,
    LocalFilmNetwork,
    PlateauLine,
    Vec2,
    _grid_strip,
    boundary_indices,
)


@dataclass(frozen=True)
class EligibilitySettings:
    collapse_threshold_fraction: float = 0.5
    minimum_outer_span_cells: int = 3
    minimum_depth_cells: int = 2
    minimum_triangle_quality: float = 0.08


@dataclass(frozen=True)
class T1Neighborhood:
    collapsing_film_id: str
    old_junction_ids: tuple[str, str]
    old_adjacent_regions: tuple[str, str]
    opposite_regions: tuple[str, str]
    outer_film_ids_by_old_junction: tuple[tuple[str, str], tuple[str, str]]
    region_outer_films: tuple[tuple[str, tuple[str, str]], ...]


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reason: str
    resolution_m: float
    threshold_m: float
    collapsing_length_m: float
    collapsing_area_m2: float
    candidate_film_ids: tuple[str, ...]
    neighborhood: T1Neighborhood | None


@dataclass(frozen=True)
class T1Lineage:
    event_id: str
    retired_film_ids: tuple[str, ...]
    created_film_ids: tuple[str, ...]
    retired_junction_ids: tuple[str, ...]
    created_junction_ids: tuple[str, ...]
    preserved_region_ids: tuple[str, ...]
    preserved_film_ids: tuple[str, ...]


@dataclass(frozen=True)
class T1SwitchResult:
    before: LocalFilmNetwork
    after: LocalFilmNetwork
    eligibility: EligibilityResult
    lineage: T1Lineage
    volume_errors_before: tuple[tuple[str, float], ...]
    volume_errors_after: tuple[tuple[str, float], ...]
    energy_before_j: float
    energy_after_j: float
    force_residual_before: float
    force_residual_after: float
    seed_requires_relaxation: bool = True


def _junctions_for_film(network: LocalFilmNetwork, film_id: str) -> list[PlateauLine]:
    return [junction for junction in network.junctions if film_id in junction.incident_film_ids]


def _other_films(junction: PlateauLine, central: str) -> tuple[str, str]:
    values = tuple(sorted(film_id for film_id in junction.incident_film_ids if film_id != central))
    if len(values) != 2:
        raise ValueError("supported junction must contain the central film plus two outer films")
    return values  # type: ignore[return-value]


def _classify_neighborhood(network: LocalFilmNetwork, central_id: str) -> T1Neighborhood:
    by_film = network.film_by_id()
    central = by_film[central_id]
    junctions = sorted(_junctions_for_film(network, central_id), key=lambda item: item.id)
    if len(junctions) != 2:
        raise ValueError("T1 candidate must be bounded by exactly two Plateau lines")
    old_a, old_b = central.adjacent
    opposite: list[str] = []
    outer_groups: list[tuple[str, str]] = []
    region_outer: dict[str, list[str]] = {old_a: [], old_b: []}
    for junction in junctions:
        outer = _other_films(junction, central_id)
        outer_groups.append(outer)
        touches_a = [film_id for film_id in outer if old_a in by_film[film_id].adjacent]
        touches_b = [film_id for film_id in outer if old_b in by_film[film_id].adjacent]
        if len(touches_a) != 1 or len(touches_b) != 1 or touches_a[0] == touches_b[0]:
            raise ValueError("each old junction must have one outer film on each side of the collapsing film")
        third_a = set(by_film[touches_a[0]].adjacent) - {old_a}
        third_b = set(by_film[touches_b[0]].adjacent) - {old_b}
        if len(third_a) != 1 or third_a != third_b:
            raise ValueError("outer films at an old junction must meet the same opposite gas region")
        third = next(iter(third_a))
        if third in central.adjacent:
            raise ValueError("T1 requires four distinct participating gas regions")
        opposite.append(third)
        region_outer[old_a].append(touches_a[0])
        region_outer[old_b].append(touches_b[0])
    if len(set(opposite)) != 2:
        raise ValueError("the two old junctions must expose two distinct opposite regions")
    future_pair = tuple(sorted(opposite))
    if any(tuple(sorted(film.adjacent)) == future_pair for film in network.films):
        raise ValueError("post-T1 gas adjacency already exists")
    return T1Neighborhood(
        collapsing_film_id=central_id,
        old_junction_ids=(junctions[0].id, junctions[1].id),
        old_adjacent_regions=tuple(sorted(central.adjacent)),
        opposite_regions=tuple(sorted(opposite)),
        outer_film_ids_by_old_junction=(outer_groups[0], outer_groups[1]),
        region_outer_films=tuple(
            (region_id, tuple(sorted(film_ids)))
            for region_id, film_ids in sorted(region_outer.items())
        ),
    )


def detect_eligibility(
    network: LocalFilmNetwork,
    settings: EligibilitySettings | None = None,
) -> EligibilityResult:
    cfg = settings or EligibilitySettings()
    try:
        network.validate()
    except ValueError as exc:
        return EligibilityResult(False, f"invalid network: {exc}", 0.0, 0.0, 0.0, 0.0, (), None)

    two_junction = [
        film for film in network.films
        if len(_junctions_for_film(network, film.id)) == 2
    ]
    if not two_junction:
        return EligibilityResult(False, "no film is bounded by two Plateau lines", 0.0, 0.0, 0.0, 0.0, (), None)

    candidate_ids = {film.id for film in two_junction}
    try:
        resolution = network.local_resolution_m(candidate_ids)
    except ValueError as exc:
        return EligibilityResult(False, str(exc), 0.0, 0.0, 0.0, 0.0, (), None)
    threshold = cfg.collapse_threshold_fraction * resolution
    collapsing = sorted(
        (film for film in two_junction if film.span_length_m <= threshold),
        key=lambda film: film.id,
    )
    if len(collapsing) != 1:
        reason = "ambiguous simultaneous collapses" if len(collapsing) > 1 else "no collapsing film is below the resolution-scaled threshold"
        return EligibilityResult(
            False,
            reason,
            resolution,
            threshold,
            min((film.span_length_m for film in two_junction), default=0.0),
            min((film.mesh.area() for film in two_junction), default=0.0),
            tuple(film.id for film in collapsing),
            None,
        )

    candidate = collapsing[0]
    outer_films = [film for film in network.films if film.id != candidate.id]
    if any(film.span_cells < cfg.minimum_outer_span_cells for film in outer_films):
        return EligibilityResult(False, "under-resolved outer-film geometry", resolution, threshold, candidate.span_length_m, candidate.mesh.area(), (candidate.id,), None)
    if any(film.depth_cells < cfg.minimum_depth_cells for film in network.films):
        return EligibilityResult(False, "under-resolved extrusion depth", resolution, threshold, candidate.span_length_m, candidate.mesh.area(), (candidate.id,), None)
    if network.minimum_triangle_quality() < cfg.minimum_triangle_quality:
        return EligibilityResult(False, "local mesh quality is below the supported threshold", resolution, threshold, candidate.span_length_m, candidate.mesh.area(), (candidate.id,), None)

    try:
        neighborhood = _classify_neighborhood(network, candidate.id)
    except ValueError as exc:
        return EligibilityResult(False, str(exc), resolution, threshold, candidate.span_length_m, candidate.mesh.area(), (candidate.id,), None)
    return EligibilityResult(True, "supported isolated four-region collapse", resolution, threshold, candidate.span_length_m, candidate.mesh.area(), (candidate.id,), neighborhood)


def _normalized(v: Vec2) -> Vec2:
    length = math.hypot(v[0], v[1])
    if length <= 1.0e-15:
        raise ValueError("cannot normalize a zero 2D vector")
    return (v[0] / length, v[1] / length)


def _mean(points: list[Vec2]) -> Vec2:
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def _junction_xy(network: LocalFilmNetwork, junction_id: str) -> Vec2:
    junction = network.junction_by_id()[junction_id]
    film = network.film_by_id()[junction.incident_film_ids[0]]
    indices = junction.vertex_indices_by_film[0]
    points = [film.mesh.vertices[index] for index in indices]
    return (sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points))


def _outer_anchor(film: FilmPatch, junction_point: Vec2) -> Vec2:
    d0 = math.hypot(film.spine[0][0] - junction_point[0], film.spine[0][1] - junction_point[1])
    d1 = math.hypot(film.spine[1][0] - junction_point[0], film.spine[1][1] - junction_point[1])
    return film.spine[1] if d0 <= d1 else film.spine[0]


def _junction_force_residual(network: LocalFilmNetwork) -> float:
    by_film = network.film_by_id()
    residuals: list[float] = []
    for junction in network.junctions:
        point = _junction_xy(network, junction.id)
        force = [0.0, 0.0]
        tension_scale = 0.0
        for film_id in junction.incident_film_ids:
            film = by_film[film_id]
            other = _outer_anchor(film, point)
            direction = _normalized((other[0] - point[0], other[1] - point[1]))
            force[0] += film.sheet_tension_n_m * direction[0]
            force[1] += film.sheet_tension_n_m * direction[1]
            tension_scale += film.sheet_tension_n_m
        residuals.append(math.hypot(force[0], force[1]) / tension_scale)
    return max(residuals, default=0.0)


def perform_neighbor_switch(
    network: LocalFilmNetwork,
    seed_fraction: float = 0.55,
    settings: EligibilitySettings | None = None,
) -> T1SwitchResult:
    eligibility = detect_eligibility(network, settings)
    if not eligibility.eligible or eligibility.neighborhood is None:
        raise ValueError(f"network is not eligible for supported T1 surgery: {eligibility.reason}")
    if seed_fraction <= 0.0:
        raise ValueError("post-switch seed fraction must be positive")
    n = eligibility.neighborhood
    by_film = network.film_by_id()
    old_junction_points = [_junction_xy(network, jid) for jid in n.old_junction_ids]
    center = _mean(old_junction_points)

    # Persistent outer-film far anchors define the new seed direction from actual
    # represented geometry, rather than from a graph drawing or film naming.
    side_centers: dict[str, Vec2] = {}
    for region_id, film_ids in n.region_outer_films:
        anchors: list[Vec2] = []
        for film_id in film_ids:
            film = by_film[film_id]
            old_junction = next(j for j in network.junctions if film_id in j.incident_film_ids)
            anchors.append(_outer_anchor(film, _junction_xy(network, old_junction.id)))
        side_centers[region_id] = _mean(anchors)
    side_ids = tuple(sorted(side_centers))
    direction = _normalized((
        side_centers[side_ids[1]][0] - side_centers[side_ids[0]][0],
        side_centers[side_ids[1]][1] - side_centers[side_ids[0]][1],
    ))
    seed_length = seed_fraction * eligibility.resolution_m
    p_left = (center[0] - 0.5 * seed_length * direction[0], center[1] - 0.5 * seed_length * direction[1])
    p_right = (center[0] + 0.5 * seed_length * direction[0], center[1] + 0.5 * seed_length * direction[1])
    side_point = {side_ids[0]: p_left, side_ids[1]: p_right}

    event_number = network.generation + 1
    event_id = f"t1:{event_number:06d}"
    new_film_id = f"film:{n.opposite_regions[0]}{n.opposite_regions[1]}:{event_id}"
    new_junction_ids = (
        f"junction:{side_ids[0]}:{event_id}",
        f"junction:{side_ids[1]}:{event_id}",
    )

    preserved_ids = tuple(sorted(film.id for film in network.films if film.id != n.collapsing_film_id))
    new_films: list[FilmPatch] = []
    outer_at_side: dict[str, list[str]] = {region_id: [] for region_id in side_ids}
    for region_id, film_ids in n.region_outer_films:
        point = side_point[region_id]
        for film_id in film_ids:
            old = by_film[film_id]
            old_junction = next(j for j in network.junctions if film_id in j.incident_film_ids)
            anchor = _outer_anchor(old, _junction_xy(network, old_junction.id))
            rebuilt = _grid_strip(
                old.id,
                old.adjacent,
                point,
                anchor,
                network.depth_m,
                eligibility.resolution_m,
                old.sheet_tension_n_m,
            )
            new_films.append(rebuilt)
            outer_at_side[region_id].append(old.id)
    central = _grid_strip(
        new_film_id,
        n.opposite_regions,
        p_left,
        p_right,
        network.depth_m,
        eligibility.resolution_m,
        by_film[n.collapsing_film_id].sheet_tension_n_m,
    )
    new_films.append(central)
    new_by_id = {film.id: film for film in new_films}

    junctions: list[PlateauLine] = []
    for index, region_id in enumerate(side_ids):
        outer = tuple(sorted(outer_at_side[region_id]))
        point = side_point[region_id]
        incident = (new_film_id, outer[0], outer[1])
        central_at_start = index == 0
        index_lists = [boundary_indices(new_by_id[new_film_id], central_at_start)]
        for film_id in outer:
            film = new_by_id[film_id]
            at_start = math.hypot(film.spine[0][0] - point[0], film.spine[0][1] - point[1]) < 1.0e-10
            index_lists.append(boundary_indices(film, at_start))
        junctions.append(PlateauLine(new_junction_ids[index], incident, tuple(index_lists)))

    anchor_by_pair: dict[tuple[str, str], Vec2] = {}
    for film in new_films:
        if film.id == new_film_id:
            continue
        pair = tuple(sorted(film.adjacent))
        side_region = next(region for region in side_ids if region in pair)
        anchor_by_pair[pair] = _outer_anchor(film, side_point[side_region])
    a, b = side_ids
    c, d = n.opposite_regions
    ac = anchor_by_pair[tuple(sorted((a, c)))]
    ad = anchor_by_pair[tuple(sorted((a, d)))]
    bc = anchor_by_pair[tuple(sorted((b, c)))]
    bd = anchor_by_pair[tuple(sorted((b, d)))]
    cells = (
        (a, (ac, p_left, ad)),
        (b, (p_right, bc, bd)),
        (c, (ac, bc, p_right, p_left)),
        (d, (p_left, p_right, bd, ad)),
    )
    after = LocalFilmNetwork(
        region_ids=network.region_ids,
        films=tuple(sorted(new_films, key=lambda film: film.id)),
        junctions=tuple(sorted(junctions, key=lambda junction: junction.id)),
        region_cells_xy=tuple(sorted(cells)),
        target_region_volumes_m3=network.target_region_volumes_m3,
        depth_m=network.depth_m,
        generation=event_number,
    )
    after.validate()
    lineage = T1Lineage(
        event_id=event_id,
        retired_film_ids=(n.collapsing_film_id,),
        created_film_ids=(new_film_id,),
        retired_junction_ids=n.old_junction_ids,
        created_junction_ids=new_junction_ids,
        preserved_region_ids=tuple(sorted(network.region_ids)),
        preserved_film_ids=preserved_ids,
    )
    return T1SwitchResult(
        before=network,
        after=after,
        eligibility=eligibility,
        lineage=lineage,
        volume_errors_before=tuple(sorted(network.relative_volume_errors().items())),
        volume_errors_after=tuple(sorted(after.relative_volume_errors().items())),
        energy_before_j=network.surface_energy_j(),
        energy_after_j=after.surface_energy_j(),
        force_residual_before=_junction_force_residual(network),
        force_residual_after=_junction_force_residual(after),
    )
