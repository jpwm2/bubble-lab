"""Deterministic production T1 topology transaction for the qualified local class.

This module intentionally supports only the four-region quasi-2D/extruded class
qualified by ``bubblelab.research.t1``.  Eligibility is reconstructed from the
current authoritative ``TransientNetworkState`` geometry and Plateau incidence;
film names are never used to infer the topology.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
import re
import statistics
from typing import Iterable

from bubblelab.solvers.equilibrium.mesh import SurfaceMesh
from bubblelab.solvers.equilibrium.network import (
    EXTERIOR,
    FilmNetwork,
    FilmPatch,
    PlateauJunction,
    project_region_volumes,
)
from bubblelab.solvers.transient.network.core import TransientNetworkState

Vec3 = tuple[float, float, float]


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a: Vec3, scale: float) -> Vec3:
    return (a[0] * scale, a[1] * scale, a[2] * scale)


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(value: Vec3) -> float:
    return math.sqrt(_dot(value, value))


def _unit(value: Vec3) -> Vec3:
    length = _norm(value)
    if length <= 1.0e-15:
        raise ValueError("cannot normalize zero-length geometry")
    return _mul(value, 1.0 / length)


def _mean(points: Iterable[Vec3]) -> Vec3:
    values = tuple(points)
    if not values:
        raise ValueError("cannot average an empty geometry set")
    inv = 1.0 / len(values)
    return (
        sum(point[0] for point in values) * inv,
        sum(point[1] for point in values) * inv,
        sum(point[2] for point in values) * inv,
    )


def _distance(a: Vec3, b: Vec3) -> float:
    return _norm(_sub(a, b))


@dataclass(frozen=True)
class T1EligibilitySettings:
    collapse_threshold_fraction: float = 0.5
    minimum_outer_span_cells: int = 3
    minimum_depth_cells: int = 2
    minimum_triangle_quality: float = 0.08
    geometry_absolute_tolerance_m: float = 1.0e-10
    geometry_relative_tolerance: float = 1.0e-8

    def validate(self) -> None:
        if not 0.0 < self.collapse_threshold_fraction < 1.0:
            raise ValueError("collapse threshold fraction must lie in (0, 1)")
        if self.minimum_outer_span_cells < 1 or self.minimum_depth_cells < 2:
            raise ValueError("supported T1 mesh cell minima are invalid")
        if not 0.0 < self.minimum_triangle_quality <= 1.0:
            raise ValueError("minimum triangle quality must lie in (0, 1]")
        if self.geometry_absolute_tolerance_m <= 0.0 or self.geometry_relative_tolerance <= 0.0:
            raise ValueError("geometry tolerances must be positive")


@dataclass(frozen=True)
class T1TransactionSettings:
    eligibility: T1EligibilitySettings = field(default_factory=T1EligibilitySettings)
    seed_fraction: float = 0.55
    volume_relative_tolerance: float = 2.0e-10
    volume_projection_iterations: int = 24

    def validate(self) -> None:
        self.eligibility.validate()
        if self.seed_fraction <= 0.0:
            raise ValueError("post-switch seed fraction must be positive")
        if self.volume_relative_tolerance <= 0.0:
            raise ValueError("volume tolerance must be positive")
        if self.volume_projection_iterations < 1:
            raise ValueError("volume projection iterations must be positive")


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
class T1TransactionResult:
    before: TransientNetworkState
    after: TransientNetworkState
    eligibility: EligibilityResult
    lineage: T1Lineage
    volume_errors_before: tuple[tuple[str, float], ...]
    volume_errors_after: tuple[tuple[str, float], ...]
    energy_before_j: float
    energy_after_j: float
    seed_requires_relaxation: bool = True

    @property
    def before_network(self) -> FilmNetwork:
        return self.before.to_network()

    @property
    def after_network(self) -> FilmNetwork:
        return self.after.to_network()


class T1TransactionError(ValueError):
    """Raised when the production transaction cannot satisfy its narrow contract."""


@dataclass(frozen=True)
class _StripInfo:
    junction_id: str
    film_id: str
    junction_center: Vec3
    far_center: Vec3
    far_indices: tuple[int, ...]
    span_cells: int
    span_length_m: float
    extrusion_offsets: tuple[Vec3, ...]
    extrusion_axis: Vec3


@dataclass(frozen=True)
class _CandidateAnalysis:
    neighborhood: T1Neighborhood
    resolution_m: float
    threshold_m: float
    collapse_length_m: float
    collapse_area_m2: float
    depth_cells: int
    minimum_quality: float
    outer_span_cells: tuple[int, ...]


def _as_network(value: TransientNetworkState | FilmNetwork) -> FilmNetwork:
    return value.to_network() if isinstance(value, TransientNetworkState) else value


def _patch_map(network: FilmNetwork) -> dict[str, FilmPatch]:
    return {patch.id: patch for patch in network.patches}


def _junctions_for_film(network: FilmNetwork, film_id: str) -> tuple[PlateauJunction, ...]:
    return tuple(junction for junction in network.junctions if film_id in junction.incident_film_ids)


def _junction_points(
    network: FilmNetwork,
    junction: PlateauJunction,
    film_id: str,
) -> tuple[Vec3, ...]:
    position = junction.incident_film_ids.index(film_id)
    patch = _patch_map(network)[film_id]
    indices = junction.vertex_indices_by_film[position]
    return tuple(patch.mesh.vertices[index] for index in indices)


def _junction_indices(junction: PlateauJunction, film_id: str) -> tuple[int, ...]:
    position = junction.incident_film_ids.index(film_id)
    return junction.vertex_indices_by_film[position]


def _line_frame(points: tuple[Vec3, ...], cfg: T1EligibilitySettings) -> tuple[Vec3, Vec3, tuple[Vec3, ...]]:
    if len(points) < cfg.minimum_depth_cells + 1:
        raise ValueError("under-resolved extrusion depth")
    center = _mean(points)
    axis = _unit(_sub(points[-1], points[0]))
    depth = _distance(points[0], points[-1])
    tolerance = max(
        cfg.geometry_absolute_tolerance_m,
        cfg.geometry_relative_tolerance * max(depth, 1.0),
    )
    projections = []
    for point in points:
        delta = _sub(point, center)
        projection = _dot(delta, axis)
        projections.append(projection)
        normal = _sub(delta, _mul(axis, projection))
        if _norm(normal) > tolerance:
            raise ValueError("general 3D/non-extruded Plateau geometry is unsupported")
    if any(right <= left for left, right in zip(projections, projections[1:])):
        raise ValueError("Plateau extrusion samples must be ordered monotonically")
    return center, axis, tuple(_sub(point, center) for point in points)


def _offset_error(left: tuple[Vec3, ...], right: tuple[Vec3, ...]) -> float:
    if len(left) != len(right):
        return math.inf
    return max((_distance(a, b) for a, b in zip(left, right)), default=0.0)


def _matching_offsets(
    reference: tuple[Vec3, ...],
    candidate: tuple[Vec3, ...],
    tolerance: float,
) -> bool:
    return min(
        _offset_error(reference, candidate),
        _offset_error(reference, tuple(reversed(candidate))),
    ) <= tolerance


def _triangle_quality(mesh: SurfaceMesh) -> float:
    values = []
    for ia, ib, ic in mesh.faces:
        a, b, c = mesh.vertices[ia], mesh.vertices[ib], mesh.vertices[ic]
        ab = _distance(a, b)
        bc = _distance(b, c)
        ca = _distance(c, a)
        semiperimeter = 0.5 * (ab + bc + ca)
        area_sq = max(
            semiperimeter
            * (semiperimeter - ab)
            * (semiperimeter - bc)
            * (semiperimeter - ca),
            0.0,
        )
        area = math.sqrt(area_sq)
        denom = ab * ab + bc * bc + ca * ca
        values.append(4.0 * math.sqrt(3.0) * area / denom if denom else 0.0)
    return min(values, default=0.0)


def _plane_tolerance(
    span_length: float,
    offsets: tuple[Vec3, ...],
    cfg: T1EligibilitySettings,
) -> float:
    depth = max((_norm(offset) for offset in offsets), default=0.0) * 2.0
    return max(
        cfg.geometry_absolute_tolerance_m,
        cfg.geometry_relative_tolerance * max(span_length, depth, 1.0),
    )


def _validate_planar_strip(
    patch: FilmPatch,
    start: Vec3,
    end: Vec3,
    axis: Vec3,
    offsets: tuple[Vec3, ...],
    cfg: T1EligibilitySettings,
) -> None:
    span = _sub(end, start)
    span = _sub(span, _mul(axis, _dot(span, axis)))
    if _norm(span) <= cfg.geometry_absolute_tolerance_m:
        raise ValueError("film span is parallel to extrusion direction")
    normal = _unit(_cross(axis, span))
    tolerance = _plane_tolerance(_norm(span), offsets, cfg)
    for vertex in patch.mesh.vertices:
        if abs(_dot(_sub(vertex, start), normal)) > tolerance:
            raise ValueError("general 3D/non-planar film geometry is unsupported")


def _far_boundary_info(
    network: FilmNetwork,
    patch: FilmPatch,
    junction: PlateauJunction,
    cfg: T1EligibilitySettings,
) -> _StripInfo:
    points = _junction_points(network, junction, patch.id)
    center, axis, offsets = _line_frame(points, cfg)
    sample_count = len(points)
    if len(patch.mesh.vertices) % sample_count != 0:
        raise ValueError("supported T1 strip must use a structured extrusion grid")
    stations = len(patch.mesh.vertices) // sample_count
    if stations < 2:
        raise ValueError("supported T1 strip requires at least two span stations")

    radial: list[tuple[float, int]] = []
    for index, vertex in enumerate(patch.mesh.vertices):
        delta = _sub(vertex, center)
        perpendicular = _sub(delta, _mul(axis, _dot(delta, axis)))
        radial.append((_norm(perpendicular), index))
    radial.sort(key=lambda item: (-item[0], item[1]))
    far_indices = tuple(index for _, index in radial[:sample_count])
    far_radii = tuple(value for value, _ in radial[:sample_count])
    far_radius = max(far_radii, default=0.0)
    tolerance = max(
        cfg.geometry_absolute_tolerance_m,
        cfg.geometry_relative_tolerance * max(far_radius, 1.0),
    )
    if far_radius <= tolerance:
        raise ValueError("outer film has no resolved span away from its junction")
    if min(far_radii) < far_radius - tolerance:
        raise ValueError("supported T1 outer film has no single extruded far boundary")

    far_indices = tuple(sorted(
        far_indices,
        key=lambda index: _dot(_sub(patch.mesh.vertices[index], center), axis),
    ))
    far_points = tuple(patch.mesh.vertices[index] for index in far_indices)
    far_center = _mean(far_points)
    far_offsets = tuple(_sub(point, far_center) for point in far_points)
    offset_tolerance = _plane_tolerance(_distance(center, far_center), offsets, cfg)
    if not _matching_offsets(offsets, far_offsets, offset_tolerance):
        raise ValueError("outer film extrusion samples do not form the supported ruled strip")
    _validate_planar_strip(patch, center, far_center, axis, offsets, cfg)
    return _StripInfo(
        junction_id=junction.id,
        film_id=patch.id,
        junction_center=center,
        far_center=far_center,
        far_indices=far_indices,
        span_cells=stations - 1,
        span_length_m=_distance(center, far_center),
        extrusion_offsets=offsets,
        extrusion_axis=axis,
    )


def _candidate_analysis(
    network: FilmNetwork,
    central_id: str,
    cfg: T1EligibilitySettings,
) -> _CandidateAnalysis:
    by_film = _patch_map(network)
    central = by_film[central_id]
    region_ids = {region.id for region in network.regions}
    if EXTERIOR in central.adjacent or not set(central.adjacent).issubset(region_ids):
        raise ValueError("T1 candidate must be an internal gas-gas film")

    junctions = tuple(sorted(_junctions_for_film(network, central_id), key=lambda item: item.id))
    if len(junctions) != 2:
        raise ValueError("T1 candidate must be bounded by exactly two Plateau lines")
    old_a, old_b = central.adjacent
    opposite: list[str] = []
    outer_groups: list[tuple[str, str]] = []
    region_outer: dict[str, list[str]] = {old_a: [], old_b: []}
    outer_infos: dict[str, _StripInfo] = {}

    first_points = _junction_points(network, junctions[0], central_id)
    first_center, first_axis, first_offsets = _line_frame(first_points, cfg)
    second_points = _junction_points(network, junctions[1], central_id)
    second_center, second_axis, second_offsets = _line_frame(second_points, cfg)
    offset_tolerance = _plane_tolerance(_distance(first_center, second_center), first_offsets, cfg)
    if abs(abs(_dot(first_axis, second_axis)) - 1.0) > cfg.geometry_relative_tolerance:
        raise ValueError("general 3D/nonparallel Plateau lines are unsupported")
    if not _matching_offsets(first_offsets, second_offsets, offset_tolerance):
        raise ValueError("Plateau lines do not share the supported extrusion sampling")
    _validate_planar_strip(central, first_center, second_center, first_axis, first_offsets, cfg)

    for junction in junctions:
        outer = tuple(sorted(film_id for film_id in junction.incident_film_ids if film_id != central_id))
        if len(outer) != 2:
            raise ValueError("supported junction must contain the central film plus two outer films")
        if len(set(outer)) != 2:
            raise ValueError("non-manifold repeated outer-film incidence is unsupported")
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
        if third == EXTERIOR or third in central.adjacent or third not in region_ids:
            raise ValueError("T1 requires four distinct participating gas regions")
        opposite.append(third)
        region_outer[old_a].append(touches_a[0])
        region_outer[old_b].append(touches_b[0])
        for film_id in outer:
            if len(_junctions_for_film(network, film_id)) != 1:
                raise ValueError("supported outer films must terminate at exactly one local Plateau line")
            if film_id not in outer_infos:
                outer_infos[film_id] = _far_boundary_info(network, by_film[film_id], junction, cfg)

    if len(set(opposite)) != 2:
        raise ValueError("the two old junctions must expose two distinct opposite regions")
    if len(outer_infos) != 4:
        raise ValueError("supported T1 neighborhood requires four distinct outer films")
    participating = set(central.adjacent) | set(opposite)
    if len(participating) != 4:
        raise ValueError("supported T1 neighborhood must contain exactly four gas regions")
    future_pair = tuple(sorted(opposite))
    for patch in network.patches:
        if EXTERIOR not in patch.adjacent and tuple(sorted(patch.adjacent)) == future_pair:
            raise ValueError("post-T1 gas adjacency already exists")

    resolution = statistics.median(
        info.span_length_m / info.span_cells for info in outer_infos.values()
    )
    if resolution <= 0.0:
        raise ValueError("local T1 resolution must be positive")
    collapse_length = _distance(first_center, second_center)
    threshold = cfg.collapse_threshold_fraction * resolution
    local_ids = {central_id, *outer_infos.keys()}
    quality = min(_triangle_quality(by_film[film_id].mesh) for film_id in local_ids)
    neighborhood = T1Neighborhood(
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
    return _CandidateAnalysis(
        neighborhood=neighborhood,
        resolution_m=resolution,
        threshold_m=threshold,
        collapse_length_m=collapse_length,
        collapse_area_m2=central.mesh.area(),
        depth_cells=len(first_offsets) - 1,
        minimum_quality=quality,
        outer_span_cells=tuple(sorted(info.span_cells for info in outer_infos.values())),
    )


def detect_t1_eligibility(
    state_or_network: TransientNetworkState | FilmNetwork,
    settings: T1EligibilitySettings | None = None,
) -> EligibilityResult:
    """Detect the single qualified collapsing film from authoritative geometry."""
    cfg = settings or T1EligibilitySettings()
    try:
        cfg.validate()
        network = _as_network(state_or_network)
        network.validate()
    except ValueError as exc:
        return EligibilityResult(False, f"invalid network: {exc}", 0.0, 0.0, 0.0, 0.0, (), None)

    regions = {region.id for region in network.regions}
    two_junction = tuple(sorted(
        patch.id
        for patch in network.patches
        if EXTERIOR not in patch.adjacent
        and set(patch.adjacent).issubset(regions)
        and len(_junctions_for_film(network, patch.id)) == 2
    ))
    if not two_junction:
        return EligibilityResult(False, "no film is bounded by two Plateau lines", 0.0, 0.0, 0.0, 0.0, (), None)

    analyses: list[_CandidateAnalysis] = []
    failures: list[tuple[str, str]] = []
    for film_id in two_junction:
        try:
            analyses.append(_candidate_analysis(network, film_id, cfg))
        except ValueError as exc:
            failures.append((film_id, str(exc)))

    collapsing = [item for item in analyses if item.collapse_length_m <= item.threshold_m]
    if len(collapsing) > 1:
        return EligibilityResult(
            False,
            "ambiguous simultaneous collapses",
            min(item.resolution_m for item in collapsing),
            min(item.threshold_m for item in collapsing),
            min(item.collapse_length_m for item in collapsing),
            min(item.collapse_area_m2 for item in collapsing),
            tuple(sorted(item.neighborhood.collapsing_film_id for item in collapsing)),
            None,
        )
    if not collapsing:
        if len(analyses) == 1:
            item = analyses[0]
            return EligibilityResult(
                False,
                "no collapsing film is below the resolution-scaled threshold",
                item.resolution_m,
                item.threshold_m,
                item.collapse_length_m,
                item.collapse_area_m2,
                (),
                None,
            )
        if failures:
            film_id, reason = sorted(failures)[0]
            return EligibilityResult(False, f"unsupported T1 candidate {film_id!r}: {reason}", 0.0, 0.0, 0.0, 0.0, (), None)
        return EligibilityResult(False, "no supported isolated T1 neighborhood", 0.0, 0.0, 0.0, 0.0, (), None)

    item = collapsing[0]
    if len(two_junction) != 1:
        return EligibilityResult(
            False,
            "multiple two-junction neighborhoods are outside the supported isolated T1 class",
            item.resolution_m,
            item.threshold_m,
            item.collapse_length_m,
            item.collapse_area_m2,
            (item.neighborhood.collapsing_film_id,),
            None,
        )
    if min(item.outer_span_cells) < cfg.minimum_outer_span_cells:
        return EligibilityResult(
            False,
            "under-resolved outer-film geometry",
            item.resolution_m,
            item.threshold_m,
            item.collapse_length_m,
            item.collapse_area_m2,
            (item.neighborhood.collapsing_film_id,),
            None,
        )
    if item.depth_cells < cfg.minimum_depth_cells:
        return EligibilityResult(
            False,
            "under-resolved extrusion depth",
            item.resolution_m,
            item.threshold_m,
            item.collapse_length_m,
            item.collapse_area_m2,
            (item.neighborhood.collapsing_film_id,),
            None,
        )
    if item.minimum_quality < cfg.minimum_triangle_quality:
        return EligibilityResult(
            False,
            "local mesh quality is below the supported threshold",
            item.resolution_m,
            item.threshold_m,
            item.collapse_length_m,
            item.collapse_area_m2,
            (item.neighborhood.collapsing_film_id,),
            None,
        )
    return EligibilityResult(
        True,
        "supported isolated four-region extruded collapse",
        item.resolution_m,
        item.threshold_m,
        item.collapse_length_m,
        item.collapse_area_m2,
        (item.neighborhood.collapsing_film_id,),
        item.neighborhood,
    )


def _build_strip(
    film_id: str,
    adjacent: tuple[str, str],
    start: Vec3,
    end: Vec3,
    extrusion_offsets: tuple[Vec3, ...],
    resolution_m: float,
    tension: float,
    contributes_to_volume: bool,
    fixed_end_samples: tuple[bool, ...] = (),
) -> FilmPatch:
    span = _distance(start, end)
    if span <= 0.0:
        raise ValueError("film strip span must be positive")
    span_cells = max(1, math.ceil(span / resolution_m))
    sample_count = len(extrusion_offsets)
    if sample_count < 3:
        raise ValueError("supported film strip needs at least three extrusion samples")
    vertices: list[Vec3] = []
    for span_index in range(span_cells + 1):
        alpha = span_index / span_cells
        center = _add(start, _mul(_sub(end, start), alpha))
        vertices.extend(_add(center, offset) for offset in extrusion_offsets)
    faces: list[tuple[int, int, int]] = []
    for span_index in range(span_cells):
        for depth_index in range(sample_count - 1):
            a = span_index * sample_count + depth_index
            b = (span_index + 1) * sample_count + depth_index
            c = (span_index + 1) * sample_count + depth_index + 1
            d = span_index * sample_count + depth_index + 1
            faces.append((a, b, c))
            faces.append((a, c, d))
    if fixed_end_samples and len(fixed_end_samples) != sample_count:
        raise ValueError("fixed far-boundary mask must match extrusion sample count")
    fixed = tuple(
        span_cells * sample_count + index
        for index, is_fixed in enumerate(fixed_end_samples)
        if is_fixed
    )
    return FilmPatch(
        id=film_id,
        mesh=SurfaceMesh.from_iterables(vertices, faces),
        adjacent=adjacent,
        sheet_tension_n_m=tension,
        fixed_vertex_indices=fixed,
        contributes_to_volume=contributes_to_volume,
    )


def _boundary_indices(patch: FilmPatch, at_start: bool, sample_count: int) -> tuple[int, ...]:
    if len(patch.mesh.vertices) % sample_count != 0:
        raise ValueError("strip vertex count is not compatible with extrusion samples")
    stations = len(patch.mesh.vertices) // sample_count
    base = 0 if at_start else (stations - 1) * sample_count
    return tuple(base + index for index in range(sample_count))


def _volume_errors(network: FilmNetwork) -> tuple[tuple[str, float], ...]:
    return tuple(sorted(
        (
            region.id,
            abs(network.region_volume(region.id) - region.target_volume_m3)
            / region.target_volume_m3,
        )
        for region in network.regions
    ))


def _next_event_serial(network: FilmNetwork) -> int:
    pattern = re.compile(r":t1:(\d+)$")
    values = []
    for identifier in [*(patch.id for patch in network.patches), *(junction.id for junction in network.junctions)]:
        match = pattern.search(identifier)
        if match:
            values.append(int(match.group(1)))
    return max(values, default=0) + 1


def internal_adjacency_pairs(
    state_or_network: TransientNetworkState | FilmNetwork,
) -> tuple[tuple[str, str], ...]:
    network = _as_network(state_or_network)
    region_ids = {region.id for region in network.regions}
    return tuple(sorted(
        tuple(sorted(patch.adjacent))
        for patch in network.patches
        if EXTERIOR not in patch.adjacent and set(patch.adjacent).issubset(region_ids)
    ))


def perform_t1_transaction(
    state: TransientNetworkState,
    settings: T1TransactionSettings | None = None,
) -> T1TransactionResult:
    """Execute one conservative topology surgery and return a relaxation seed."""
    cfg = settings or T1TransactionSettings()
    cfg.validate()
    before_network = state.to_network()
    eligibility = detect_t1_eligibility(before_network, cfg.eligibility)
    if not eligibility.eligible or eligibility.neighborhood is None:
        raise T1TransactionError(
            f"network is not eligible for supported production T1 surgery: {eligibility.reason}"
        )
    n = eligibility.neighborhood
    by_film = _patch_map(before_network)
    old_junctions = {
        junction.id: junction for junction in before_network.junctions
        if junction.id in n.old_junction_ids
    }
    central_old = by_film[n.collapsing_film_id]

    first_junction = old_junctions[n.old_junction_ids[0]]
    second_junction = old_junctions[n.old_junction_ids[1]]
    first_points = _junction_points(before_network, first_junction, n.collapsing_film_id)
    first_center, extrusion_axis, extrusion_offsets = _line_frame(first_points, cfg.eligibility)
    second_center = _mean(_junction_points(before_network, second_junction, n.collapsing_film_id))
    event_center = _mean((first_center, second_center))

    outer_info: dict[str, _StripInfo] = {}
    for junction in (first_junction, second_junction):
        for film_id in junction.incident_film_ids:
            if film_id == n.collapsing_film_id:
                continue
            outer_info[film_id] = _far_boundary_info(
                before_network,
                by_film[film_id],
                junction,
                cfg.eligibility,
            )

    region_outer = dict(n.region_outer_films)
    side_centers = {
        region_id: _mean(outer_info[film_id].far_center for film_id in film_ids)
        for region_id, film_ids in region_outer.items()
    }
    side_ids = tuple(sorted(side_centers))
    raw_direction = _sub(side_centers[side_ids[1]], side_centers[side_ids[0]])
    raw_direction = _sub(raw_direction, _mul(extrusion_axis, _dot(raw_direction, extrusion_axis)))
    direction = _unit(raw_direction)
    seed_length = cfg.seed_fraction * eligibility.resolution_m
    endpoints = {
        side_ids[0]: _add(event_center, _mul(direction, -0.5 * seed_length)),
        side_ids[1]: _add(event_center, _mul(direction, 0.5 * seed_length)),
    }

    serial = _next_event_serial(before_network)
    event_id = f"t1:{serial:06d}"
    new_film_id = f"film:{n.opposite_regions[0]}{n.opposite_regions[1]}:{event_id}"
    new_junction_ids = (
        f"junction:{side_ids[0]}:{event_id}",
        f"junction:{side_ids[1]}:{event_id}",
    )
    existing_ids = {patch.id for patch in before_network.patches}
    if new_film_id in existing_ids:
        raise T1TransactionError("deterministic T1 film ID collides with existing topology")

    rebuilt_outer: dict[str, FilmPatch] = {}
    for side_id in side_ids:
        for film_id in region_outer[side_id]:
            old = by_film[film_id]
            info = outer_info[film_id]
            fixed_set = set(old.fixed_vertex_indices)
            junction_set = set(_junction_indices(old_junctions[info.junction_id], film_id))
            far_set = set(info.far_indices)
            if not fixed_set.issubset(junction_set | far_set):
                raise T1TransactionError(
                    "supported T1 outer film cannot preserve interior fixed-vertex constraints"
                )
            if fixed_set & junction_set:
                raise T1TransactionError(
                    "supported T1 event cannot move a fixed collapsing Plateau line"
                )
            far_fixed = tuple(index in fixed_set for index in info.far_indices)
            rebuilt_outer[film_id] = _build_strip(
                film_id=old.id,
                adjacent=old.adjacent,
                start=endpoints[side_id],
                end=info.far_center,
                extrusion_offsets=extrusion_offsets,
                resolution_m=eligibility.resolution_m,
                tension=old.sheet_tension_n_m,
                contributes_to_volume=old.contributes_to_volume,
                fixed_end_samples=far_fixed,
            )

    new_central = _build_strip(
        film_id=new_film_id,
        adjacent=n.opposite_regions,
        start=endpoints[side_ids[0]],
        end=endpoints[side_ids[1]],
        extrusion_offsets=extrusion_offsets,
        resolution_m=eligibility.resolution_m,
        tension=central_old.sheet_tension_n_m,
        contributes_to_volume=central_old.contributes_to_volume,
    )

    patches: list[FilmPatch] = []
    for patch in before_network.patches:
        if patch.id == n.collapsing_film_id:
            continue
        patches.append(rebuilt_outer.get(patch.id, patch))
    patches.append(new_central)
    patches.sort(key=lambda patch: patch.id)
    patch_after = {patch.id: patch for patch in patches}

    sample_count = len(extrusion_offsets)
    new_junctions: list[PlateauJunction] = []
    for side_index, side_id in enumerate(side_ids):
        outer = tuple(sorted(region_outer[side_id]))
        central_indices = _boundary_indices(
            new_central,
            at_start=side_index == 0,
            sample_count=sample_count,
        )
        outer_indices = tuple(
            _boundary_indices(patch_after[film_id], at_start=True, sample_count=sample_count)
            for film_id in outer
        )
        new_junctions.append(PlateauJunction(
            id=new_junction_ids[side_index],
            incident_film_ids=(new_film_id, outer[0], outer[1]),
            vertex_indices_by_film=(central_indices, outer_indices[0], outer_indices[1]),
        ))

    junctions = [
        junction for junction in before_network.junctions
        if junction.id not in set(n.old_junction_ids)
    ]
    junctions.extend(new_junctions)
    junctions.sort(key=lambda junction: junction.id)
    after_network = FilmNetwork(before_network.regions, tuple(patches), tuple(junctions))
    try:
        after_network.validate()
    except ValueError as exc:
        raise T1TransactionError(f"post-T1 topology is invalid before volume projection: {exc}") from exc

    after_errors = _volume_errors(after_network)
    if max((error for _, error in after_errors), default=0.0) > cfg.volume_relative_tolerance:
        try:
            after_network = project_region_volumes(
                after_network,
                relative_tolerance=0.25 * cfg.volume_relative_tolerance,
                max_iterations=cfg.volume_projection_iterations,
            )
        except (ValueError, RuntimeError) as exc:
            raise T1TransactionError(f"post-T1 conservative volume projection failed: {exc}") from exc
        after_network.validate()
        after_errors = _volume_errors(after_network)
    max_error = max((error for _, error in after_errors), default=0.0)
    if max_error > cfg.volume_relative_tolerance:
        raise T1TransactionError(
            f"post-T1 volume tolerance not met: {max_error:.6e} > {cfg.volume_relative_tolerance:.6e}"
        )

    old_pair = tuple(sorted(n.old_adjacent_regions))
    new_pair = tuple(sorted(n.opposite_regions))
    before_pairs = set(internal_adjacency_pairs(before_network))
    after_pairs = set(internal_adjacency_pairs(after_network))
    if old_pair not in before_pairs or old_pair in after_pairs or new_pair in before_pairs or new_pair not in after_pairs:
        raise T1TransactionError("T1 transaction did not perform the required neighbor switch")
    if new_central.mesh.area() <= 0.0:
        raise T1TransactionError("created T1 film has zero geometry")

    try:
        after_raw = TransientNetworkState.from_network(after_network)
    except (ValueError, RuntimeError) as exc:
        raise T1TransactionError(f"post-T1 state cannot initialize transient shared DOFs: {exc}") from exc
    after_state = replace(
        after_raw,
        time_s=state.time_s,
        step_index=state.step_index,
    )
    lineage = T1Lineage(
        event_id=event_id,
        retired_film_ids=(n.collapsing_film_id,),
        created_film_ids=(new_film_id,),
        retired_junction_ids=n.old_junction_ids,
        created_junction_ids=new_junction_ids,
        preserved_region_ids=tuple(region.id for region in before_network.regions),
        preserved_film_ids=tuple(sorted(
            patch.id for patch in before_network.patches if patch.id != n.collapsing_film_id
        )),
    )
    return T1TransactionResult(
        before=state,
        after=after_state,
        eligibility=eligibility,
        lineage=lineage,
        volume_errors_before=_volume_errors(before_network),
        volume_errors_after=after_errors,
        energy_before_j=before_network.surface_energy_j(),
        energy_after_j=after_network.surface_energy_j(),
    )


def perform_neighbor_switch(
    state: TransientNetworkState,
    seed_fraction: float = 0.55,
    settings: T1EligibilitySettings | None = None,
) -> T1TransactionResult:
    """Compatibility-shaped entry point matching the research prototype vocabulary."""
    return perform_t1_transaction(
        state,
        T1TransactionSettings(
            eligibility=settings or T1EligibilitySettings(),
            seed_fraction=seed_fraction,
        ),
    )


# Research-shaped alias retained intentionally for callers graduating from the evidence package.
detect_eligibility = detect_t1_eligibility
apply_t1_transaction = perform_t1_transaction
