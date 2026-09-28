"""Direct geometry-driven 3D T1 hydrodynamics for a bounded foam neighborhood.

Supported class
---------------
This module supports one isolated four-gas T1 neighborhood whose collapsing
shared film is bounded by exactly two sampled Plateau-border curves.  The five
local sheets may be genuinely non-coplanar and the two Plateau curves may be
non-parallel/curved.  All five local sheets must be marked
``contributes_to_volume=False``; gas volume is carried by the authoritative
closed support sheets already present in the network.  This keeps the topology
change conservative without pretending to solve arbitrary closed-cell surgery.

Event model
-----------
No inverse map to the legacy quasi-2D/bilinear detector is used. Event timing
comes directly from the current 3D mesh. On each old Plateau curve, every
incident sheet contributes the surface-tension co-normal traction implied by
its boundary triangles. Those line tractions are integrated and projected onto
the curve-to-curve separation direction obtained from arclength-weighted
polyline centroids to obtain the capillary generalized collapse force
``F = dE/dell``. The local liquid-border motion is modeled as overdamped force
balance

    d ell / dt = - mobility * F.

The force is evaluated on the actual undeformed 3D mesh, avoiding an arbitrary
virtual interior displacement field. Both the force direction and gap use line
integrals rather than vertex averages, so conforming subdivision of the same
piecewise-linear geometry leaves the forecast unchanged up to floating-point
roundoff. The predicted T1 time is the deterministic midpoint quadrature down
to twice the configured Plateau-border core radius. A non-positive force rejects
the spontaneous event. This remains a local hydrodynamic closure, not resolved
singular liquid-border CFD.

At the predicted event geometry the old shared film and old two triple lines are
retired.  The opposite gas pair receives a new shared-film seed whose two new
Plateau curves are displaced along the local direction perpendicular to the old
curve tangent and collapse direction.  The sign is fixed by the actual outer
sheet geometry of the two old-adjacent gases.  Stable gas IDs and all unaffected
film IDs are preserved.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
import re
import statistics
from typing import Iterable

from bubblelab.solvers.equilibrium.mesh import SurfaceMesh
from bubblelab.solvers.equilibrium.network import EXTERIOR, FilmNetwork, FilmPatch, PlateauJunction
from bubblelab.solvers.transient.network.core import TransientNetworkState
from bubblelab.solvers.transient.network.t1 import (
    T1Lineage,
    build_supported_pre_t1_network,
    internal_adjacency_pairs,
)

Vec3 = tuple[float, float, float]
SUPPORTED_CLASS = "isolated-four-region-curvilinear-3d-overdamped-direct-traction"


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a: Vec3, s: float) -> Vec3:
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(a: Vec3) -> float:
    return math.sqrt(_dot(a, a))


def _distance(a: Vec3, b: Vec3) -> float:
    return _norm(_sub(a, b))


def _unit(a: Vec3) -> Vec3:
    length = _norm(a)
    if length <= 1.0e-15:
        raise ValueError("cannot normalize zero-length 3D geometry")
    return _mul(a, 1.0 / length)


def _mean(points: Iterable[Vec3]) -> Vec3:
    values = tuple(points)
    if not values:
        raise ValueError("cannot average empty 3D geometry")
    inv = 1.0 / len(values)
    return (
        sum(value[0] for value in values) * inv,
        sum(value[1] for value in values) * inv,
        sum(value[2] for value in values) * inv,
    )


def _polyline_centroid(points: tuple[Vec3, ...]) -> Vec3:
    """Return the exact arclength centroid of a piecewise-linear curve."""
    if len(points) < 2:
        raise ValueError("polyline centroid requires at least two points")
    total = 0.0
    weighted = (0.0, 0.0, 0.0)
    for left, right in zip(points, points[1:]):
        length = _distance(left, right)
        if length <= 1.0e-15:
            continue
        total += length
        weighted = _add(weighted, _mul(_add(left, right), 0.5 * length))
    if total <= 1.0e-15:
        raise ValueError("polyline centroid requires non-zero arclength")
    return _mul(weighted, 1.0 / total)


def _rms_distance(left: tuple[Vec3, ...], right: tuple[Vec3, ...]) -> float:
    if len(left) != len(right) or not left:
        return math.inf
    return math.sqrt(sum(_distance(a, b) ** 2 for a, b in zip(left, right)) / len(left))


def _patch_map(network: FilmNetwork) -> dict[str, FilmPatch]:
    return {patch.id: patch for patch in network.patches}


def _junction_map(network: FilmNetwork) -> dict[str, PlateauJunction]:
    return {junction.id: junction for junction in network.junctions}


def _junctions_for_film(network: FilmNetwork, film_id: str) -> tuple[PlateauJunction, ...]:
    return tuple(junction for junction in network.junctions if film_id in junction.incident_film_ids)


def _junction_indices(junction: PlateauJunction, film_id: str) -> tuple[int, ...]:
    return junction.vertex_indices_by_film[junction.incident_film_ids.index(film_id)]


def _junction_points(network: FilmNetwork, junction: PlateauJunction, film_id: str) -> tuple[Vec3, ...]:
    patch = _patch_map(network)[film_id]
    return tuple(patch.mesh.vertices[index] for index in _junction_indices(junction, film_id))


def _third_region(patch: FilmPatch, known: str) -> str | None:
    other = tuple(value for value in patch.adjacent if value != known)
    return other[0] if len(other) == 1 else None


def _nonplanarity_m(patch: FilmPatch) -> float:
    vertices = patch.mesh.vertices
    if len(vertices) < 4:
        return 0.0
    origin = vertices[0]
    first: Vec3 | None = None
    for vertex in vertices[1:]:
        delta = _sub(vertex, origin)
        if _norm(delta) > 1.0e-12:
            first = delta
            break
    if first is None:
        return 0.0
    normal: Vec3 | None = None
    for vertex in vertices[1:]:
        candidate = _cross(first, _sub(vertex, origin))
        if _norm(candidate) > 1.0e-12:
            normal = _unit(candidate)
            break
    if normal is None:
        return 0.0
    return max(abs(_dot(_sub(vertex, origin), normal)) for vertex in vertices)


def _curve_tangent(points: tuple[Vec3, ...], sample: int) -> Vec3:
    if sample == 0:
        return _unit(_sub(points[1], points[0]))
    if sample == len(points) - 1:
        return _unit(_sub(points[-1], points[-2]))
    return _unit(_sub(points[sample + 1], points[sample - 1]))


def _median_local_edge(network: FilmNetwork, film_ids: tuple[str, ...]) -> float:
    by_id = _patch_map(network)
    lengths = [
        length
        for film_id in film_ids
        for length in by_id[film_id].mesh.edge_lengths()
        if length > 0.0
    ]
    if not lengths:
        raise ValueError("local T1 mesh has no non-zero edges")
    return statistics.median(lengths)


@dataclass(frozen=True)
class DirectT1Settings:
    plateau_border_core_radius_m: float = 0.010
    mobility_m_per_n_s: float = 2.0e-2
    hydrodynamic_segments: int = 32
    force_difference_fraction: float = 2.0e-4
    minimum_driving_force_n: float = 1.0e-7
    minimum_nonplanarity_m: float = 2.0e-4
    minimum_tangent_spread: float = 1.0e-5
    minimum_samples: int = 3
    maximum_core_to_edge_ratio: float = 0.50
    post_event_seed_factor: float = 1.25
    volume_relative_tolerance: float = 1.0e-12

    def validate(self) -> None:
        if self.plateau_border_core_radius_m <= 0.0:
            raise ValueError("Plateau-border core radius must be positive")
        if self.mobility_m_per_n_s <= 0.0:
            raise ValueError("T1 mobility must be positive")
        if self.hydrodynamic_segments < 4:
            raise ValueError("hydrodynamic quadrature requires at least four segments")
        if not 1.0e-7 <= self.force_difference_fraction <= 1.0e-2:
            raise ValueError("force finite-difference fraction is outside the stable range")
        if self.minimum_driving_force_n <= 0.0:
            raise ValueError("minimum driving force must be positive")
        if self.minimum_nonplanarity_m <= 0.0 or self.minimum_tangent_spread <= 0.0:
            raise ValueError("3D eligibility thresholds must be positive")
        if self.minimum_samples < 3:
            raise ValueError("direct 3D T1 requires at least three Plateau samples")
        if not 0.0 < self.maximum_core_to_edge_ratio <= 1.0:
            raise ValueError("maximum core-to-edge ratio must lie in (0, 1]")
        if self.post_event_seed_factor <= 0.0:
            raise ValueError("post-event seed factor must be positive")
        if self.volume_relative_tolerance <= 0.0:
            raise ValueError("volume tolerance must be positive")


@dataclass(frozen=True)
class DirectT1Neighborhood:
    collapsing_film_id: str
    old_junction_ids: tuple[str, str]
    old_adjacent_regions: tuple[str, str]
    opposite_regions: tuple[str, str]
    outer_film_ids_by_old_junction: tuple[tuple[str, str], tuple[str, str]]
    region_outer_films: tuple[tuple[str, tuple[str, str]], ...]
    local_film_ids: tuple[str, ...]


@dataclass(frozen=True)
class DirectT1EligibilityResult:
    eligible: bool
    reason: str
    supported_class: str
    neighborhood: DirectT1Neighborhood | None
    initial_gap_m: float
    event_gap_m: float
    resolution_m: float
    max_nonplanarity_m: float
    junction_tangent_spread: float
    second_curve_reversed: bool


@dataclass(frozen=True)
class HydrodynamicForecast:
    event_time_s: float
    initial_gap_m: float
    event_gap_m: float
    initial_force_n: float
    minimum_force_n: float
    maximum_force_n: float
    local_energy_initial_j: float
    local_energy_event_j: float
    quadrature_segments: int


@dataclass(frozen=True)
class DirectT1TransactionResult:
    before: TransientNetworkState
    after: TransientNetworkState
    eligibility: DirectT1EligibilityResult
    forecast: HydrodynamicForecast
    lineage: T1Lineage
    adjacency_before: tuple[tuple[str, str], ...]
    adjacency_after: tuple[tuple[str, str], ...]
    volume_errors_before: tuple[tuple[str, float], ...]
    volume_errors_after: tuple[tuple[str, float], ...]
    energy_before_j: float
    energy_after_j: float
    seed_requires_relaxation: bool = True


class DirectT1Error(ValueError):
    """Raised when geometry or hydrodynamics is outside the bounded direct-3D class."""


def _discover_neighborhood(network: FilmNetwork) -> DirectT1Neighborhood:
    by_film = _patch_map(network)
    region_ids = {region.id for region in network.regions}
    candidates = []
    for central in network.patches:
        if central.contributes_to_volume:
            continue
        if EXTERIOR in central.adjacent or not set(central.adjacent).issubset(region_ids):
            continue
        junctions = tuple(sorted(_junctions_for_film(network, central.id), key=lambda item: item.id))
        if len(junctions) != 2:
            continue
        old_a, old_b = central.adjacent
        opposite: list[str] = []
        outer_groups: list[tuple[str, str]] = []
        region_outer: dict[str, list[str]] = {old_a: [], old_b: []}
        ok = True
        for junction in junctions:
            outer = tuple(film_id for film_id in junction.incident_film_ids if film_id != central.id)
            if len(outer) != 2 or len(set(outer)) != 2:
                ok = False
                break
            touches_a = [film_id for film_id in outer if old_a in by_film[film_id].adjacent]
            touches_b = [film_id for film_id in outer if old_b in by_film[film_id].adjacent]
            if len(touches_a) != 1 or len(touches_b) != 1 or touches_a[0] == touches_b[0]:
                ok = False
                break
            third_a = _third_region(by_film[touches_a[0]], old_a)
            third_b = _third_region(by_film[touches_b[0]], old_b)
            if (
                third_a is None
                or third_a != third_b
                or third_a == EXTERIOR
                or third_a in central.adjacent
                or third_a not in region_ids
            ):
                ok = False
                break
            opposite.append(third_a)
            outer_groups.append(tuple(sorted(outer)))
            region_outer[old_a].append(touches_a[0])
            region_outer[old_b].append(touches_b[0])
        if not ok or len(set(opposite)) != 2:
            continue
        participating = set(central.adjacent) | set(opposite)
        if len(participating) != 4:
            continue
        future_pair = tuple(sorted(opposite))
        if any(
            EXTERIOR not in patch.adjacent and tuple(sorted(patch.adjacent)) == future_pair
            for patch in network.patches
        ):
            continue
        local = (central.id, *outer_groups[0], *outer_groups[1])
        if len(set(local)) != 5:
            continue
        if any(by_film[film_id].contributes_to_volume for film_id in local):
            continue
        candidates.append(DirectT1Neighborhood(
            collapsing_film_id=central.id,
            old_junction_ids=(junctions[0].id, junctions[1].id),
            old_adjacent_regions=tuple(sorted(central.adjacent)),
            opposite_regions=tuple(sorted(opposite)),
            outer_film_ids_by_old_junction=(outer_groups[0], outer_groups[1]),
            region_outer_films=tuple(
                (region_id, tuple(sorted(film_ids)))
                for region_id, film_ids in sorted(region_outer.items())
            ),
            local_film_ids=tuple(sorted(set(local))),
        ))
    if len(candidates) != 1:
        if not candidates:
            raise DirectT1Error("no isolated four-region direct-3D T1 neighborhood was found")
        raise DirectT1Error("multiple direct-3D T1 neighborhoods are ambiguous")
    return candidates[0]


def _ordered_curves(
    network: FilmNetwork,
    neighborhood: DirectT1Neighborhood,
) -> tuple[
    tuple[Vec3, ...],
    tuple[Vec3, ...],
    bool,
    tuple[int, ...],
    tuple[int, ...],
]:
    junctions = _junction_map(network)
    first = junctions[neighborhood.old_junction_ids[0]]
    second = junctions[neighborhood.old_junction_ids[1]]
    first_indices = _junction_indices(first, neighborhood.collapsing_film_id)
    second_indices = _junction_indices(second, neighborhood.collapsing_film_id)
    first_points = _junction_points(network, first, neighborhood.collapsing_film_id)
    second_points_raw = _junction_points(network, second, neighborhood.collapsing_film_id)
    if len(first_points) != len(second_points_raw):
        raise DirectT1Error("the two collapsing Plateau curves use different sample counts")
    same = _rms_distance(first_points, second_points_raw)
    reversed_points = tuple(reversed(second_points_raw))
    reversed_error = _rms_distance(first_points, reversed_points)
    reverse = reversed_error < same
    second_points = reversed_points if reverse else second_points_raw
    second_indices_ordered = tuple(reversed(second_indices)) if reverse else second_indices
    return first_points, second_points, reverse, first_indices, second_indices_ordered


def _gap(first: tuple[Vec3, ...], second: tuple[Vec3, ...]) -> float:
    return _distance(_polyline_centroid(first), _polyline_centroid(second))


def _tangent_spread(first: tuple[Vec3, ...], second: tuple[Vec3, ...]) -> float:
    return max(
        1.0 - abs(_dot(_curve_tangent(first, i), _curve_tangent(second, i)))
        for i in range(len(first))
    )


def detect_direct_t1_eligibility(
    state_or_network: TransientNetworkState | FilmNetwork,
    settings: DirectT1Settings | None = None,
) -> DirectT1EligibilityResult:
    cfg = settings or DirectT1Settings()
    try:
        cfg.validate()
        network = state_or_network.to_network() if isinstance(state_or_network, TransientNetworkState) else state_or_network
        network.validate()
        neighborhood = _discover_neighborhood(network)
        first, second, reversed_curve, _, _ = _ordered_curves(network, neighborhood)
        if len(first) < cfg.minimum_samples:
            raise DirectT1Error("Plateau curves are under-sampled for direct 3D T1")
        initial_gap = _gap(first, second)
        event_gap = 2.0 * cfg.plateau_border_core_radius_m
        if initial_gap <= event_gap:
            raise DirectT1Error("the supplied state is already at or beyond the T1 core-contact geometry")
        resolution = _median_local_edge(network, neighborhood.local_film_ids)
        if event_gap / resolution > cfg.maximum_core_to_edge_ratio:
            raise DirectT1Error("Plateau-border core is too large relative to the local mesh scale")
        by_id = _patch_map(network)
        nonplanarity = max(_nonplanarity_m(by_id[film_id]) for film_id in neighborhood.local_film_ids)
        if nonplanarity < cfg.minimum_nonplanarity_m:
            raise DirectT1Error("local sheets are not resolved as genuinely non-coplanar")
        spread = _tangent_spread(first, second)
        if spread < cfg.minimum_tangent_spread:
            raise DirectT1Error("the two Plateau curves are effectively parallel/extruded")
        return DirectT1EligibilityResult(
            True,
            "supported isolated curvilinear 3D neighborhood",
            SUPPORTED_CLASS,
            neighborhood,
            initial_gap,
            event_gap,
            resolution,
            nonplanarity,
            spread,
            reversed_curve,
        )
    except ValueError as exc:
        return DirectT1EligibilityResult(
            False,
            str(exc),
            SUPPORTED_CLASS,
            None,
            0.0,
            2.0 * cfg.plateau_border_core_radius_m if cfg.plateau_border_core_radius_m > 0.0 else 0.0,
            0.0,
            0.0,
            0.0,
            False,
        )


def _canonical_indices(
    junction: PlateauJunction,
    film_id: str,
    reverse: bool,
) -> tuple[int, ...]:
    indices = _junction_indices(junction, film_id)
    return tuple(reversed(indices)) if reverse else indices


def _contracted_network(
    network: FilmNetwork,
    neighborhood: DirectT1Neighborhood,
    scale: float,
    second_reversed: bool,
) -> FilmNetwork:
    if not 0.0 < scale <= 1.05:
        raise DirectT1Error("virtual contraction scale is outside the supported interval")
    junctions = _junction_map(network)
    first = junctions[neighborhood.old_junction_ids[0]]
    second = junctions[neighborhood.old_junction_ids[1]]
    first_points, second_points, _, _, _ = _ordered_curves(network, neighborhood)
    contracted_first = []
    contracted_second = []
    for left, right in zip(first_points, second_points):
        midpoint = _mul(_add(left, right), 0.5)
        half = _mul(_sub(right, left), 0.5 * scale)
        contracted_first.append(_sub(midpoint, half))
        contracted_second.append(_add(midpoint, half))
    mutable = {patch.id: list(patch.mesh.vertices) for patch in network.patches}
    for junction, points, reverse in (
        (first, tuple(contracted_first), False),
        (second, tuple(contracted_second), second_reversed),
    ):
        for film_id in junction.incident_film_ids:
            ordered = _canonical_indices(junction, film_id, reverse)
            for index, point in zip(ordered, points):
                mutable[film_id][index] = point
    patches = tuple(
        FilmPatch(
            id=patch.id,
            mesh=patch.mesh.with_vertices(mutable[patch.id]),
            adjacent=patch.adjacent,
            sheet_tension_n_m=patch.sheet_tension_n_m,
            fixed_vertex_indices=patch.fixed_vertex_indices,
            contributes_to_volume=patch.contributes_to_volume,
        )
        for patch in network.patches
    )
    contracted = FilmNetwork(network.regions, patches, network.junctions)
    contracted.validate()
    return contracted


def _local_energy(network: FilmNetwork, film_ids: tuple[str, ...]) -> float:
    by_id = _patch_map(network)
    return sum(by_id[film_id].sheet_tension_n_m * by_id[film_id].mesh.area() for film_id in film_ids)


def _boundary_traction_integral(
    patch: FilmPatch,
    indices: tuple[int, ...],
) -> Vec3:
    """Integrate one sheet's surface-tension co-normal traction on a Plateau boundary."""
    edge_thirds: dict[tuple[int, int], list[int]] = {}
    for a, b, c in patch.mesh.faces:
        for left, right, third in ((a, b, c), (b, c, a), (c, a, b)):
            edge_thirds.setdefault(tuple(sorted((left, right))), []).append(third)

    total = (0.0, 0.0, 0.0)
    for left, right in zip(indices, indices[1:]):
        va = patch.mesh.vertices[left]
        vb = patch.mesh.vertices[right]
        edge = _sub(vb, va)
        length = _norm(edge)
        if length <= 1.0e-15:
            raise DirectT1Error("Plateau boundary contains a zero-length mesh edge")
        thirds = edge_thirds.get(tuple(sorted((left, right))), ())
        if len(thirds) != 1:
            raise DirectT1Error("Plateau curve must follow a one-sided mesh boundary")
        tangent = _mul(edge, 1.0 / length)
        midpoint = _mul(_add(va, vb), 0.5)
        inward = _sub(patch.mesh.vertices[thirds[0]], midpoint)
        inward = _sub(inward, _mul(tangent, _dot(inward, tangent)))
        conormal = _unit(inward)
        total = _add(total, _mul(conormal, patch.sheet_tension_n_m * length))
    return total


def _junction_traction(network: FilmNetwork, junction: PlateauJunction) -> Vec3:
    by_id = _patch_map(network)
    total = (0.0, 0.0, 0.0)
    for film_id in junction.incident_film_ids:
        total = _add(
            total,
            _boundary_traction_integral(
                by_id[film_id],
                _junction_indices(junction, film_id),
            ),
        )
    return total


def _direct_gap_capillary_force(
    network: FilmNetwork,
    neighborhood: DirectT1Neighborhood,
) -> float:
    first, second, _, _, _ = _ordered_curves(network, neighborhood)
    separation_direction = _unit(
        _sub(_polyline_centroid(second), _polyline_centroid(first))
    )
    junctions = _junction_map(network)
    force_first = _junction_traction(network, junctions[neighborhood.old_junction_ids[0]])
    force_second = _junction_traction(network, junctions[neighborhood.old_junction_ids[1]])
    # If ell increases, the first curve moves -e/2 and the second +e/2.
    # Surface-tension traction is -grad(E), so dE/dell is the expression below.
    return 0.5 * (
        _dot(force_first, separation_direction)
        - _dot(force_second, separation_direction)
    )


def _force_at_scale(
    network: FilmNetwork,
    neighborhood: DirectT1Neighborhood,
    initial_gap: float,
    scale: float,
    second_reversed: bool,
    cfg: DirectT1Settings,
) -> float:
    # The capillary force comes from the actual resolved Plateau boundaries.
    # Keeping the legacy signature preserves the event integrator/API while
    # deliberately avoiding any virtual interior displacement field.
    del initial_gap, scale, second_reversed, cfg
    return _direct_gap_capillary_force(network, neighborhood)


def forecast_direct_t1(
    state_or_network: TransientNetworkState | FilmNetwork,
    settings: DirectT1Settings | None = None,
) -> tuple[DirectT1EligibilityResult, HydrodynamicForecast]:
    cfg = settings or DirectT1Settings()
    eligibility = detect_direct_t1_eligibility(state_or_network, cfg)
    if not eligibility.eligible or eligibility.neighborhood is None:
        raise DirectT1Error(eligibility.reason)
    network = state_or_network.to_network() if isinstance(state_or_network, TransientNetworkState) else state_or_network
    n = eligibility.neighborhood
    event_scale = eligibility.event_gap_m / eligibility.initial_gap_m
    if not 0.0 < event_scale < 1.0:
        raise DirectT1Error("event scale must lie strictly inside the current gap")
    forces = []
    dt_total = 0.0
    segments = cfg.hydrodynamic_segments
    scale_width = (1.0 - event_scale) / segments
    for index in range(segments):
        scale_mid = 1.0 - (index + 0.5) * scale_width
        force = _force_at_scale(
            network,
            n,
            eligibility.initial_gap_m,
            scale_mid,
            eligibility.second_curve_reversed,
            cfg,
        )
        if force <= cfg.minimum_driving_force_n:
            raise DirectT1Error(
                f"local capillary force does not drive collapse: {force:.6e} N"
            )
        forces.append(force)
        d_gap = eligibility.initial_gap_m * scale_width
        dt_total += d_gap / (cfg.mobility_m_per_n_s * force)
    initial_force = _force_at_scale(
        network,
        n,
        eligibility.initial_gap_m,
        1.0,
        eligibility.second_curve_reversed,
        cfg,
    )
    initial_energy = _local_energy(network, n.local_film_ids)
    event_network = _contracted_network(
        network,
        n,
        event_scale,
        eligibility.second_curve_reversed,
    )
    event_energy = _local_energy(event_network, n.local_film_ids)
    return eligibility, HydrodynamicForecast(
        event_time_s=dt_total,
        initial_gap_m=eligibility.initial_gap_m,
        event_gap_m=eligibility.event_gap_m,
        initial_force_n=initial_force,
        minimum_force_n=min(forces),
        maximum_force_n=max(forces),
        local_energy_initial_j=initial_energy,
        local_energy_event_j=event_energy,
        quadrature_segments=segments,
    )


def _far_center(patch: FilmPatch, junction_indices: tuple[int, ...]) -> Vec3:
    excluded = set(junction_indices)
    candidates = tuple(
        vertex for index, vertex in enumerate(patch.mesh.vertices) if index not in excluded
    )
    return _mean(candidates or patch.mesh.vertices)


def _event_switch_curves(
    event_network: FilmNetwork,
    neighborhood: DirectT1Neighborhood,
    second_reversed: bool,
    seed_length_m: float,
) -> tuple[tuple[Vec3, ...], tuple[Vec3, ...], tuple[str, str]]:
    by_id = _patch_map(event_network)
    junctions = _junction_map(event_network)
    first_j = junctions[neighborhood.old_junction_ids[0]]
    second_j = junctions[neighborhood.old_junction_ids[1]]
    first, second, _, _, _ = _ordered_curves(event_network, neighborhood)
    region_outer = dict(neighborhood.region_outer_films)
    side_ids = tuple(sorted(region_outer))
    side_centers = {}
    for side_id in side_ids:
        centers = []
        for film_id in region_outer[side_id]:
            junction = first_j if film_id in first_j.incident_film_ids else second_j
            reverse = second_reversed if junction.id == second_j.id else False
            centers.append(_far_center(by_id[film_id], _canonical_indices(junction, film_id, reverse)))
        side_centers[side_id] = _mean(centers)
    side_vector = _sub(side_centers[side_ids[1]], side_centers[side_ids[0]])
    midpoints = tuple(_mul(_add(left, right), 0.5) for left, right in zip(first, second))
    left_curve = []
    right_curve = []
    for index, (left, right, midpoint) in enumerate(zip(first, second, midpoints)):
        tangent = _curve_tangent(midpoints, index)
        collapse = _unit(_sub(right, left))
        direction = _cross(tangent, collapse)
        direction = _sub(direction, _mul(tangent, _dot(direction, tangent)))
        if _norm(direction) <= 1.0e-12:
            raise DirectT1Error("local switch direction is singular")
        direction = _unit(direction)
        if _dot(direction, side_vector) < 0.0:
            direction = _mul(direction, -1.0)
        half = _mul(direction, 0.5 * seed_length_m)
        left_curve.append(_sub(midpoint, half))
        right_curve.append(_add(midpoint, half))
    return tuple(left_curve), tuple(right_curve), side_ids


def _replace_patch_vertices(patch: FilmPatch, updates: dict[int, Vec3]) -> FilmPatch:
    vertices = list(patch.mesh.vertices)
    for index, point in updates.items():
        vertices[index] = point
    return FilmPatch(
        id=patch.id,
        mesh=patch.mesh.with_vertices(vertices),
        adjacent=patch.adjacent,
        sheet_tension_n_m=patch.sheet_tension_n_m,
        fixed_vertex_indices=patch.fixed_vertex_indices,
        contributes_to_volume=patch.contributes_to_volume,
    )


def _curve_strip(
    film_id: str,
    adjacent: tuple[str, str],
    first: tuple[Vec3, ...],
    second: tuple[Vec3, ...],
    tension: float,
    contributes_to_volume: bool,
) -> FilmPatch:
    if len(first) != len(second) or len(first) < 3:
        raise DirectT1Error("new T1 film requires matching curves with at least three samples")
    count = len(first)
    vertices = first + second
    faces = []
    for index in range(count - 1):
        a = index
        b = count + index
        c = count + index + 1
        d = index + 1
        faces.append((a, b, c))
        faces.append((a, c, d))
    return FilmPatch(
        id=film_id,
        mesh=SurfaceMesh.from_iterables(vertices, faces),
        adjacent=adjacent,
        sheet_tension_n_m=tension,
        contributes_to_volume=contributes_to_volume,
    )


def _volume_errors(network: FilmNetwork) -> tuple[tuple[str, float], ...]:
    return tuple(
        (
            region.id,
            abs(network.region_volume(region.id) - region.target_volume_m3) / region.target_volume_m3,
        )
        for region in network.regions
    )


def _next_event_serial(network: FilmNetwork) -> int:
    pattern = re.compile(r":t1h:(\d+)$")
    values = []
    for identifier in [*(patch.id for patch in network.patches), *(junction.id for junction in network.junctions)]:
        match = pattern.search(identifier)
        if match:
            values.append(int(match.group(1)))
    return max(values, default=0) + 1


def perform_direct_t1_transaction(
    state: TransientNetworkState,
    settings: DirectT1Settings | None = None,
) -> DirectT1TransactionResult:
    cfg = settings or DirectT1Settings()
    cfg.validate()
    eligibility, forecast = forecast_direct_t1(state, cfg)
    if eligibility.neighborhood is None:
        raise DirectT1Error("eligible direct-3D T1 result lost its neighborhood")
    n = eligibility.neighborhood
    before_network = state.to_network()
    event_scale = forecast.event_gap_m / forecast.initial_gap_m
    event_network = _contracted_network(
        before_network,
        n,
        event_scale,
        eligibility.second_curve_reversed,
    )
    by_id = _patch_map(event_network)
    junctions = _junction_map(event_network)
    first_j = junctions[n.old_junction_ids[0]]
    second_j = junctions[n.old_junction_ids[1]]
    seed_length = cfg.post_event_seed_factor * forecast.event_gap_m
    side0_curve, side1_curve, side_ids = _event_switch_curves(
        event_network,
        n,
        eligibility.second_curve_reversed,
        seed_length,
    )
    region_outer = dict(n.region_outer_films)
    updates_by_film: dict[str, dict[int, Vec3]] = {}
    junction_indices_by_side: dict[str, list[tuple[str, tuple[int, ...]]]] = {
        side_ids[0]: [], side_ids[1]: []
    }
    for side_index, side_id in enumerate(side_ids):
        target_curve = side0_curve if side_index == 0 else side1_curve
        for film_id in region_outer[side_id]:
            old_junction = first_j if film_id in first_j.incident_film_ids else second_j
            reverse = eligibility.second_curve_reversed if old_junction.id == second_j.id else False
            ordered = _canonical_indices(old_junction, film_id, reverse)
            if any(index in set(by_id[film_id].fixed_vertex_indices) for index in ordered):
                raise DirectT1Error("a collapsing Plateau curve contains a fixed outer-film vertex")
            updates_by_film.setdefault(film_id, {}).update(dict(zip(ordered, target_curve)))
            junction_indices_by_side[side_id].append((film_id, ordered))

    central_old = by_id[n.collapsing_film_id]
    serial = _next_event_serial(before_network)
    event_id = f"t1h:{serial:06d}"
    new_film_id = f"film:{n.opposite_regions[0]}{n.opposite_regions[1]}:{event_id}"
    if new_film_id in by_id:
        raise DirectT1Error("deterministic direct-T1 film ID collides with existing topology")
    new_central = _curve_strip(
        new_film_id,
        n.opposite_regions,
        side0_curve,
        side1_curve,
        central_old.sheet_tension_n_m,
        central_old.contributes_to_volume,
    )
    patches = []
    for patch in event_network.patches:
        if patch.id == n.collapsing_film_id:
            continue
        patches.append(_replace_patch_vertices(patch, updates_by_film.get(patch.id, {})))
    patches.append(new_central)
    patches.sort(key=lambda patch: patch.id)

    new_junctions = []
    count = len(side0_curve)
    new_junction_ids = []
    for side_index, side_id in enumerate(side_ids):
        entries = sorted(junction_indices_by_side[side_id], key=lambda item: item[0])
        if len(entries) != 2:
            raise DirectT1Error("each post-T1 side must own exactly two outer films")
        central_indices = tuple(
            (0 if side_index == 0 else count) + sample for sample in range(count)
        )
        junction_id = f"junction:{side_id}:{event_id}"
        new_junction_ids.append(junction_id)
        new_junctions.append(PlateauJunction(
            id=junction_id,
            incident_film_ids=(new_film_id, entries[0][0], entries[1][0]),
            vertex_indices_by_film=(central_indices, entries[0][1], entries[1][1]),
        ))
    retained_junctions = [
        junction for junction in event_network.junctions if junction.id not in set(n.old_junction_ids)
    ]
    all_junctions = tuple(sorted((*retained_junctions, *new_junctions), key=lambda item: item.id))
    after_network = FilmNetwork(event_network.regions, tuple(patches), all_junctions)
    try:
        after_network.validate()
    except ValueError as exc:
        raise DirectT1Error(f"post-T1 3D topology is invalid: {exc}") from exc

    before_errors = _volume_errors(before_network)
    after_errors = _volume_errors(after_network)
    max_error = max((value for _, value in after_errors), default=0.0)
    if max_error > cfg.volume_relative_tolerance:
        raise DirectT1Error(
            f"direct-3D T1 gas-volume conservation failed: {max_error:.6e}"
        )
    if tuple(region.id for region in before_network.regions) != tuple(region.id for region in after_network.regions):
        raise DirectT1Error("direct-3D T1 changed stable gas-region identities")
    old_pair = tuple(sorted(n.old_adjacent_regions))
    new_pair = tuple(sorted(n.opposite_regions))
    before_pairs = set(internal_adjacency_pairs(before_network))
    after_pairs = set(internal_adjacency_pairs(after_network))
    if old_pair not in before_pairs or old_pair in after_pairs or new_pair in before_pairs or new_pair not in after_pairs:
        raise DirectT1Error("direct-3D T1 did not perform the required adjacency switch")

    after_raw = TransientNetworkState.from_network(after_network)
    after_state = replace(
        after_raw,
        time_s=state.time_s + forecast.event_time_s,
        step_index=state.step_index,
    )
    lineage = T1Lineage(
        event_id=event_id,
        retired_film_ids=(n.collapsing_film_id,),
        created_film_ids=(new_film_id,),
        retired_junction_ids=n.old_junction_ids,
        created_junction_ids=tuple(new_junction_ids),
        preserved_region_ids=tuple(region.id for region in before_network.regions),
        preserved_film_ids=tuple(sorted(
            patch.id for patch in before_network.patches if patch.id != n.collapsing_film_id
        )),
    )
    return DirectT1TransactionResult(
        before=state,
        after=after_state,
        eligibility=eligibility,
        forecast=forecast,
        lineage=lineage,
        adjacency_before=internal_adjacency_pairs(before_network),
        adjacency_after=internal_adjacency_pairs(after_network),
        volume_errors_before=before_errors,
        volume_errors_after=after_errors,
        energy_before_j=before_network.surface_energy_j(),
        energy_after_j=after_network.surface_energy_j(),
    )


def _warp_point(point: Vec3, mode: str, amplitude_m_inv: float, y_saturation_m: float) -> Vec3:
    x, y, z = point
    ys = y_saturation_m * math.tanh(y / y_saturation_m)
    if mode == "twisted-saturation":
        return (
            x + amplitude_m_inv * (0.20 * y * z + 0.07 * z * z),
            ys + amplitude_m_inv * (0.035 * x * z + 0.012 * z * z),
            z + amplitude_m_inv * (0.045 * x * y + 0.015 * y * z),
        )
    if mode == "saddle-saturation":
        return (
            x + amplitude_m_inv * (0.12 * y * z + 0.09 * z * z + 0.025 * y * y),
            ys + amplitude_m_inv * (0.028 * x * z - 0.010 * x * y),
            z + amplitude_m_inv * (0.038 * x * y - 0.018 * y * z + 0.008 * x * z),
        )
    raise ValueError(f"unknown direct-3D fixture warp mode: {mode!r}")


def build_direct_3d_t1_network(
    *,
    resolution_m: float = 0.10,
    initial_gap_m: float = 0.050,
    half_extent_m: float = 1.0,
    depth_m: float = 0.60,
    sheet_tension_n_m: float = 1.0,
    mode: str = "twisted-saturation",
    amplitude_m_inv: float = 0.35,
    y_saturation_m: float = 0.080,
) -> FilmNetwork:
    """Build a genuinely non-coplanar fixture outside the legacy bilinear-shear family.

    The source topology is the accepted isolated four-region cell, but its local
    non-volume sheets are pushed through a saturating-y plus multi-coordinate
    polynomial deformation.  Because both ``y`` and ``z`` are changed and the
    deformation contains quadratic terms, no map ``x -> x + s*y*z`` can invert
    this fixture back into the legacy extruded class.
    """
    if resolution_m <= 0.0 or not 0.0 < initial_gap_m < resolution_m:
        raise ValueError("fixture requires 0 < initial_gap_m < resolution_m")
    if y_saturation_m <= 0.0:
        raise ValueError("fixture y saturation scale must be positive")
    canonical = build_supported_pre_t1_network(
        resolution_m=resolution_m,
        collapse_fraction=initial_gap_m / resolution_m,
        half_extent_m=half_extent_m,
        depth_m=depth_m,
        sheet_tension_n_m=sheet_tension_n_m,
    )
    patches = []
    for patch in canonical.patches:
        if patch.contributes_to_volume:
            mesh = patch.mesh
        else:
            mesh = patch.mesh.with_vertices(
                _warp_point(vertex, mode, amplitude_m_inv, y_saturation_m)
                for vertex in patch.mesh.vertices
            )
        patches.append(FilmPatch(
            id=patch.id,
            mesh=mesh,
            adjacent=patch.adjacent,
            sheet_tension_n_m=patch.sheet_tension_n_m,
            fixed_vertex_indices=patch.fixed_vertex_indices,
            contributes_to_volume=patch.contributes_to_volume,
        ))
    network = FilmNetwork(canonical.regions, tuple(patches), canonical.junctions)
    network.validate()
    return network


def build_direct_3d_t1_state(**kwargs: object) -> TransientNetworkState:
    return TransientNetworkState.from_network(build_direct_3d_t1_network(**kwargs))