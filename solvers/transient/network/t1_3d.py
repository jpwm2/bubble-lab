"""Bounded genuinely-3D T1 topology support for the transient film network.

The supported class is deliberately narrower than unrestricted 3D foam topology.
It is the volume-preserving bilinear-shear embedding

    X(x, y, z) = (x + s*y*z, y, z)

of the already-qualified isolated four-region T1 neighborhood.  For ``s != 0``
the outer sheets are non-planar and the two pre-event Plateau lines have
different 3D directions, so this is not the existing straight extrusion under a
rigid/global-affine relabeling.  The inverse map is analytic.  Eligibility is
therefore checked by (1) proving the authoritative geometry is genuinely 3D and
(2) inverse-mapping it into the accepted production T1 detector.

This module does not claim arbitrary 3D T1 surgery or singular liquid-border
hydrodynamics.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
from typing import Iterable

from bubblelab.solvers.equilibrium.network import FilmNetwork, FilmPatch
from bubblelab.solvers.transient.network.core import (
    NetworkStepperSettings,
    TransientNetworkState,
    advance,
    diagnostics,
)
from bubblelab.solvers.transient.network.t1 import (
    EligibilityResult,
    T1Lineage,
    T1TransactionSettings,
    build_supported_pre_t1_network,
    detect_t1_eligibility,
    internal_adjacency_pairs,
    perform_t1_transaction,
)

Vec3 = tuple[float, float, float]

SUPPORTED_CLASS = "volume-preserving-bilinear-shear-of-qualified-four-region-t1"


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


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
    return (value[0] / length, value[1] / length, value[2] / length)


def _mean(points: Iterable[Vec3]) -> Vec3:
    values = tuple(points)
    if not values:
        raise ValueError("cannot average an empty point set")
    inv = 1.0 / len(values)
    return (
        sum(point[0] for point in values) * inv,
        sum(point[1] for point in values) * inv,
        sum(point[2] for point in values) * inv,
    )


def _distance(a: Vec3, b: Vec3) -> float:
    return _norm(_sub(a, b))


def shear_point(point: Vec3, shear_m_inv: float) -> Vec3:
    """Apply the supported divergence-free bilinear shear."""
    x, y, z = point
    return (x + shear_m_inv * y * z, y, z)


def unshear_point(point: Vec3, shear_m_inv: float) -> Vec3:
    """Exact inverse of :func:`shear_point`."""
    x, y, z = point
    return (x - shear_m_inv * y * z, y, z)


def _mapped_network(
    network: FilmNetwork,
    shear_m_inv: float,
    *,
    inverse: bool,
) -> FilmNetwork:
    mapper = unshear_point if inverse else shear_point
    patches = []
    for patch in network.patches:
        # The accepted T1 local sheets are open non-volume-contributing patches;
        # separate closed support shells carry gas volume.  Keep those shells
        # unchanged so the 3D local topology operation cannot manufacture gas.
        if patch.contributes_to_volume:
            mesh = patch.mesh
        else:
            vertices = tuple(mapper(vertex, shear_m_inv) for vertex in patch.mesh.vertices)
            mesh = patch.mesh.with_vertices(vertices)
        patches.append(FilmPatch(
            id=patch.id,
            mesh=mesh,
            adjacent=patch.adjacent,
            sheet_tension_n_m=patch.sheet_tension_n_m,
            fixed_vertex_indices=patch.fixed_vertex_indices,
            contributes_to_volume=patch.contributes_to_volume,
        ))
    mapped = FilmNetwork(network.regions, tuple(patches), network.junctions)
    mapped.validate()
    return mapped


def shear_network(network: FilmNetwork, shear_m_inv: float) -> FilmNetwork:
    return _mapped_network(network, shear_m_inv, inverse=False)


def unshear_network(network: FilmNetwork, shear_m_inv: float) -> FilmNetwork:
    return _mapped_network(network, shear_m_inv, inverse=True)


def _state_from_network(
    network: FilmNetwork,
    source: TransientNetworkState | None = None,
) -> TransientNetworkState:
    state = TransientNetworkState.from_network(network)
    if source is None:
        return state
    return replace(state, time_s=source.time_s, step_index=source.step_index)


def _patch_nonplanarity_m(patch: FilmPatch) -> float:
    vertices = patch.mesh.vertices
    if len(vertices) < 4:
        return 0.0
    origin = vertices[0]
    first = None
    for index in range(1, len(vertices)):
        delta = _sub(vertices[index], origin)
        if _norm(delta) > 1.0e-12:
            first = delta
            break
    if first is None:
        return 0.0
    normal = None
    for index in range(1, len(vertices)):
        candidate = _cross(first, _sub(vertices[index], origin))
        if _norm(candidate) > 1.0e-12:
            normal = _unit(candidate)
            break
    if normal is None:
        return 0.0
    return max(abs(_dot(_sub(vertex, origin), normal)) for vertex in vertices)


def _junction_direction(network: FilmNetwork, junction_index: int) -> Vec3:
    junction = network.junctions[junction_index]
    patch_by_id = {patch.id: patch for patch in network.patches}
    film_id = junction.incident_film_ids[0]
    indices = junction.vertex_indices_by_film[0]
    vertices = patch_by_id[film_id].mesh.vertices
    return _unit(_sub(vertices[indices[-1]], vertices[indices[0]]))


def genuine_3d_metrics(network: FilmNetwork) -> dict[str, float]:
    local = tuple(patch for patch in network.patches if not patch.contributes_to_volume)
    max_nonplanarity = max((_patch_nonplanarity_m(patch) for patch in local), default=0.0)
    spread = 0.0
    if len(network.junctions) >= 2:
        directions = tuple(_junction_direction(network, index) for index in range(len(network.junctions)))
        for left in range(len(directions)):
            for right in range(left + 1, len(directions)):
                spread = max(spread, 1.0 - abs(_dot(directions[left], directions[right])))
    return {
        "max_patch_nonplanarity_m": max_nonplanarity,
        "junction_direction_spread": spread,
    }


@dataclass(frozen=True)
class T13DSettings:
    shear_m_inv: float = 0.50
    minimum_nonplanarity_fraction: float = 0.01
    minimum_junction_direction_spread: float = 1.0e-6
    geometry_absolute_tolerance_m: float = 1.0e-10
    base: T1TransactionSettings = field(default_factory=T1TransactionSettings)

    def validate(self) -> None:
        self.base.validate()
        if abs(self.shear_m_inv) <= 1.0e-12:
            raise ValueError("3D T1 shear magnitude must be non-zero")
        if self.minimum_nonplanarity_fraction <= 0.0:
            raise ValueError("minimum nonplanarity fraction must be positive")
        if self.minimum_junction_direction_spread <= 0.0:
            raise ValueError("minimum junction direction spread must be positive")
        if self.geometry_absolute_tolerance_m <= 0.0:
            raise ValueError("geometry absolute tolerance must be positive")


@dataclass(frozen=True)
class T13DEligibilityResult:
    eligible: bool
    reason: str
    supported_class: str
    base: EligibilityResult
    max_patch_nonplanarity_m: float
    required_nonplanarity_m: float
    junction_direction_spread: float
    shear_m_inv: float


@dataclass(frozen=True)
class T13DTransactionResult:
    before: TransientNetworkState
    after: TransientNetworkState
    eligibility: T13DEligibilityResult
    lineage: T1Lineage
    volume_errors_before: tuple[tuple[str, float], ...]
    volume_errors_after: tuple[tuple[str, float], ...]
    energy_before_j: float
    energy_after_j: float
    adjacency_before: tuple[tuple[str, str], ...]
    adjacency_after: tuple[tuple[str, str], ...]
    seed_requires_relaxation: bool = True


class T13DTransactionError(ValueError):
    """Raised when geometry falls outside the bounded supported 3D class."""


def build_supported_pre_t1_3d_network(
    resolution_m: float = 0.12,
    collapse_fraction: float = 0.35,
    half_extent_m: float = 1.0,
    depth_m: float = 0.6,
    sheet_tension_n_m: float = 1.0,
    id_prefix: str = "",
    origin_xy: tuple[float, float] = (0.0, 0.0),
    shear_m_inv: float = 0.50,
) -> FilmNetwork:
    canonical = build_supported_pre_t1_network(
        resolution_m=resolution_m,
        collapse_fraction=collapse_fraction,
        half_extent_m=half_extent_m,
        depth_m=depth_m,
        sheet_tension_n_m=sheet_tension_n_m,
        id_prefix=id_prefix,
        origin_xy=origin_xy,
    )
    return shear_network(canonical, shear_m_inv)


def build_supported_pre_t1_3d_state(**kwargs: object) -> TransientNetworkState:
    return TransientNetworkState.from_network(build_supported_pre_t1_3d_network(**kwargs))


def detect_t1_3d_eligibility(
    state_or_network: TransientNetworkState | FilmNetwork,
    settings: T13DSettings | None = None,
) -> T13DEligibilityResult:
    cfg = settings or T13DSettings()
    cfg.validate()
    network = (
        state_or_network.to_network()
        if isinstance(state_or_network, TransientNetworkState)
        else state_or_network
    )
    canonical = unshear_network(network, cfg.shear_m_inv)
    base = detect_t1_eligibility(canonical, cfg.base.eligibility)
    metrics = genuine_3d_metrics(network)
    required = max(
        cfg.geometry_absolute_tolerance_m,
        cfg.minimum_nonplanarity_fraction * max(base.resolution_m, cfg.geometry_absolute_tolerance_m),
    )
    if not base.eligible:
        return T13DEligibilityResult(
            False,
            "inverse-mapped geometry is outside the accepted four-region T1 class: " + base.reason,
            SUPPORTED_CLASS,
            base,
            metrics["max_patch_nonplanarity_m"],
            required,
            metrics["junction_direction_spread"],
            cfg.shear_m_inv,
        )
    if metrics["max_patch_nonplanarity_m"] < required:
        return T13DEligibilityResult(
            False,
            "geometry does not exhibit resolved non-coplanar film shape",
            SUPPORTED_CLASS,
            base,
            metrics["max_patch_nonplanarity_m"],
            required,
            metrics["junction_direction_spread"],
            cfg.shear_m_inv,
        )
    if metrics["junction_direction_spread"] < cfg.minimum_junction_direction_spread:
        return T13DEligibilityResult(
            False,
            "Plateau-line directions remain effectively parallel/extruded",
            SUPPORTED_CLASS,
            base,
            metrics["max_patch_nonplanarity_m"],
            required,
            metrics["junction_direction_spread"],
            cfg.shear_m_inv,
        )
    return T13DEligibilityResult(
        True,
        "supported non-coplanar bilinear-shear 3D T1 neighborhood",
        SUPPORTED_CLASS,
        base,
        metrics["max_patch_nonplanarity_m"],
        required,
        metrics["junction_direction_spread"],
        cfg.shear_m_inv,
    )


def _volume_errors(network: FilmNetwork) -> tuple[tuple[str, float], ...]:
    return tuple(
        (
            region.id,
            abs(network.region_volume(region.id) - region.target_volume_m3)
            / region.target_volume_m3,
        )
        for region in network.regions
    )


def perform_t1_3d_transaction(
    state: TransientNetworkState,
    settings: T13DSettings | None = None,
) -> T13DTransactionResult:
    """Execute one deterministic T1 event in the bounded genuine-3D class."""
    cfg = settings or T13DSettings()
    cfg.validate()
    eligibility = detect_t1_3d_eligibility(state, cfg)
    if not eligibility.eligible:
        raise T13DTransactionError(eligibility.reason)

    before_network = state.to_network()
    canonical_before = _state_from_network(
        unshear_network(before_network, cfg.shear_m_inv),
        state,
    )
    canonical_result = perform_t1_transaction(canonical_before, cfg.base)
    after_network = shear_network(canonical_result.after.to_network(), cfg.shear_m_inv)
    after = _state_from_network(after_network, state)

    before_errors = _volume_errors(before_network)
    after_errors = _volume_errors(after_network)
    max_error = max((value for _, value in after_errors), default=0.0)
    if max_error > cfg.base.volume_relative_tolerance:
        raise T13DTransactionError(
            f"3D T1 gas-volume conservation failed: {max_error:.6e}"
        )

    before_regions = tuple(region.id for region in before_network.regions)
    after_regions = tuple(region.id for region in after_network.regions)
    if before_regions != after_regions:
        raise T13DTransactionError("3D T1 changed stable gas-region identity/order")

    return T13DTransactionResult(
        before=state,
        after=after,
        eligibility=eligibility,
        lineage=canonical_result.lineage,
        volume_errors_before=before_errors,
        volume_errors_after=after_errors,
        energy_before_j=before_network.surface_energy_j(),
        energy_after_j=after_network.surface_energy_j(),
        adjacency_before=internal_adjacency_pairs(before_network),
        adjacency_after=internal_adjacency_pairs(after_network),
    )


def warp_discretization_residual_m(
    canonical: FilmNetwork,
    warped: FilmNetwork,
    shear_m_inv: float,
) -> float:
    """Measure piecewise-linear geometry error against the exact 3D embedding.

    At each triangle barycenter, compare the exact bilinear map of the canonical
    barycenter with the barycenter of the mapped triangle.  The quantity is a
    genuine surface-geometry discretization residual and should converge under
    mesh refinement.
    """
    warped_by_id = {patch.id: patch for patch in warped.patches}
    residual = 0.0
    for patch in canonical.patches:
        if patch.contributes_to_volume:
            continue
        mapped_patch = warped_by_id[patch.id]
        for face in patch.mesh.faces:
            canonical_center = _mean(patch.mesh.vertices[index] for index in face)
            exact = shear_point(canonical_center, shear_m_inv)
            linear = _mean(mapped_patch.mesh.vertices[index] for index in face)
            residual = max(residual, _distance(exact, linear))
    return residual


def _switch_benchmark() -> dict[str, object]:
    cfg = T13DSettings()
    state = build_supported_pre_t1_3d_state(shear_m_inv=cfg.shear_m_inv)
    base_on_3d = detect_t1_eligibility(state)
    result = perform_t1_3d_transaction(state, cfg)
    neighborhood = result.eligibility.base.neighborhood
    if neighborhood is None:
        raise AssertionError("eligible 3D T1 is missing its base neighborhood")
    old_pair = tuple(sorted(neighborhood.old_adjacent_regions))
    new_pair = tuple(sorted(neighborhood.opposite_regions))
    before_pairs = set(result.adjacency_before)
    after_pairs = set(result.adjacency_after)
    after_network = result.after.to_network()
    junction_by_id = {junction.id: junction for junction in after_network.junctions}
    created_film = result.lineage.created_film_ids[0]
    created_incidence_ok = all(
        junction_id in junction_by_id
        and created_film in junction_by_id[junction_id].incident_film_ids
        for junction_id in result.lineage.created_junction_ids
    )
    replay = perform_t1_3d_transaction(state, cfg)
    deterministic = (
        replay.lineage == result.lineage
        and replay.after.topology_signature() == result.after.topology_signature()
        and replay.after.positions == result.after.positions
    )
    passed = (
        result.eligibility.eligible
        and not base_on_3d.eligible
        and old_pair in before_pairs
        and old_pair not in after_pairs
        and new_pair not in before_pairs
        and new_pair in after_pairs
        and created_incidence_ok
        and deterministic
    )
    return {
        "pass": passed,
        "supported_class": SUPPORTED_CLASS,
        "existing_extruded_detector_rejects_3d": not base_on_3d.eligible,
        "max_patch_nonplanarity_m": result.eligibility.max_patch_nonplanarity_m,
        "required_nonplanarity_m": result.eligibility.required_nonplanarity_m,
        "junction_direction_spread": result.eligibility.junction_direction_spread,
        "old_pair": list(old_pair),
        "new_pair": list(new_pair),
        "before_adjacency": [list(pair) for pair in result.adjacency_before],
        "after_adjacency": [list(pair) for pair in result.adjacency_after],
        "retired_films": list(result.lineage.retired_film_ids),
        "created_films": list(result.lineage.created_film_ids),
        "retired_junctions": list(result.lineage.retired_junction_ids),
        "created_junctions": list(result.lineage.created_junction_ids),
        "created_film_incidence_ok": created_incidence_ok,
        "deterministic_replay": deterministic,
    }


def _conservation_benchmark() -> dict[str, object]:
    cfg = T13DSettings()
    state = build_supported_pre_t1_3d_state(shear_m_inv=cfg.shear_m_inv)
    result = perform_t1_3d_transaction(state, cfg)
    before_ids = tuple(region.id for region in result.before.to_network().regions)
    after_ids = tuple(region.id for region in result.after.to_network().regions)
    max_before = max((value for _, value in result.volume_errors_before), default=0.0)
    max_after = max((value for _, value in result.volume_errors_after), default=0.0)
    replay = perform_t1_3d_transaction(state, cfg)
    deterministic = (
        result.lineage == replay.lineage
        and result.after.positions == replay.after.positions
    )
    passed = (
        before_ids == after_ids
        and tuple(result.lineage.preserved_region_ids) == before_ids
        and max_before <= cfg.base.volume_relative_tolerance
        and max_after <= cfg.base.volume_relative_tolerance
        and deterministic
    )
    return {
        "pass": passed,
        "region_ids_before": list(before_ids),
        "region_ids_after": list(after_ids),
        "max_relative_volume_error_before": max_before,
        "max_relative_volume_error_after": max_after,
        "volume_relative_tolerance": cfg.base.volume_relative_tolerance,
        "event_id": result.lineage.event_id,
        "deterministic_replay": deterministic,
        "energy_before_j": result.energy_before_j,
        "energy_after_j": result.energy_after_j,
    }


def _refinement_benchmark() -> dict[str, object]:
    cfg = T13DSettings()
    resolutions = (0.20, 0.10, 0.05, 0.025)
    rows = []
    for resolution in resolutions:
        canonical = build_supported_pre_t1_network(resolution_m=resolution)
        warped = shear_network(canonical, cfg.shear_m_inv)
        state = TransientNetworkState.from_network(warped)
        eligibility = detect_t1_3d_eligibility(state, cfg)
        result = perform_t1_3d_transaction(state, cfg)
        canonical_result = perform_t1_transaction(
            TransientNetworkState.from_network(canonical),
            cfg.base,
        )
        before_residual = warp_discretization_residual_m(
            canonical,
            warped,
            cfg.shear_m_inv,
        )
        after_residual = warp_discretization_residual_m(
            canonical_result.after.to_network(),
            result.after.to_network(),
            cfg.shear_m_inv,
        )
        rows.append({
            "resolution_m": resolution,
            "eligible": eligibility.eligible,
            "before_geometry_residual_m": before_residual,
            "after_geometry_residual_m": after_residual,
            "adjacency_after": [list(pair) for pair in result.adjacency_after],
        })
    before_values = [float(row["before_geometry_residual_m"]) for row in rows]
    after_values = [float(row["after_geometry_residual_m"]) for row in rows]
    before_monotone = all(right < left for left, right in zip(before_values, before_values[1:]))
    after_monotone = all(right < left for left, right in zip(after_values, after_values[1:]))
    same_topology = all(row["adjacency_after"] == rows[0]["adjacency_after"] for row in rows[1:])
    passed = (
        all(bool(row["eligible"]) for row in rows)
        and before_monotone
        and after_monotone
        and same_topology
        and before_values[-1] < 0.10 * before_values[0]
        and after_values[-1] < 0.10 * after_values[0]
    )
    return {
        "pass": passed,
        "supported_class": SUPPORTED_CLASS,
        "rows": rows,
        "before_residual_strictly_decreases": before_monotone,
        "after_residual_strictly_decreases": after_monotone,
        "topology_invariant_under_refinement": same_topology,
    }


def run_t1_3d_benchmark(name: str) -> dict[str, object]:
    if name == "switch":
        return _switch_benchmark()
    if name == "conservation":
        return _conservation_benchmark()
    if name == "refinement":
        return _refinement_benchmark()
    raise ValueError(f"unknown 3D T1 benchmark: {name}")


def continue_t1_3d(
    result: T13DTransactionResult,
    *,
    steps: int = 1,
    settings: NetworkStepperSettings | None = None,
) -> tuple[TransientNetworkState, tuple[object, ...]]:
    """Continue the authoritative transient network after the topology event."""
    if steps < 0:
        raise ValueError("steps must be non-negative")
    cfg = settings or NetworkStepperSettings(
        dt_s=5.0e-5,
        mobility_m_per_n_s=5.0e-3,
        max_displacement_edge_fraction=0.01,
        volume_relative_tolerance=2.0e-10,
        volume_projection_iterations=24,
        max_backtracks=20,
    )
    current = result.after
    history = []
    for _ in range(steps):
        current, step_diag = advance(current, settings=cfg)
        history.append(step_diag)
    return current, tuple(history)


def runtime_transition_evidence() -> dict[str, object]:
    cfg = T13DSettings()
    state = build_supported_pre_t1_3d_state(shear_m_inv=cfg.shear_m_inv)
    result = perform_t1_3d_transaction(state, cfg)
    continued, history = continue_t1_3d(result, steps=2)
    final_diag = diagnostics(continued)
    max_volume_error = max((value for _, value in final_diag.relative_volume_errors), default=0.0)
    topology_preserved = (
        continued.topology_signature() == result.after.topology_signature()
        and internal_adjacency_pairs(continued) == result.adjacency_after
    )
    passed = (
        len(history) == 2
        and continued.step_index == result.after.step_index + 2
        and continued.time_s > result.after.time_s
        and topology_preserved
        and max_volume_error <= 2.0e-10
        and continued.shared_dof_count() > 0
    )
    return {
        "pass": passed,
        "supported_class": SUPPORTED_CLASS,
        "event_id": result.lineage.event_id,
        "step_index_before_event": state.step_index,
        "step_index_after_event": result.after.step_index,
        "step_index_after_continuation": continued.step_index,
        "time_s_after_continuation": continued.time_s,
        "adjacency_after_event": [list(pair) for pair in result.adjacency_after],
        "topology_preserved_during_continuation": topology_preserved,
        "shared_dof_count": continued.shared_dof_count(),
        "max_relative_volume_error": max_volume_error,
        "step_energy_j": [float(item.surface_energy_j) for item in history],
    }


# Compatibility aliases for callers that use the production T1 naming pattern.
detect_eligibility_3d = detect_t1_3d_eligibility
perform_neighbor_switch_3d = perform_t1_3d_transaction
