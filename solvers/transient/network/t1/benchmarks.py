"""Executable production evidence for the supported T1 topology transaction."""
from __future__ import annotations

from dataclasses import asdict

from .fixtures import build_supported_pre_t1_state
from .transaction import (
    T1TransactionSettings,
    detect_t1_eligibility,
    internal_adjacency_pairs,
    perform_t1_transaction,
)


def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return sum((a[index] - b[index]) ** 2 for index in range(3)) ** 0.5


def _mean(points: tuple[tuple[float, float, float], ...]) -> tuple[float, float, float]:
    inv = 1.0 / len(points)
    return tuple(sum(point[axis] for point in points) * inv for axis in range(3))  # type: ignore[return-value]


def _created_film_span(result: object) -> float:
    lineage = result.lineage  # type: ignore[attr-defined]
    network = result.after.to_network()  # type: ignore[attr-defined]
    film_id = lineage.created_film_ids[0]
    centers = []
    by_patch = {patch.id: patch for patch in network.patches}
    patch = by_patch[film_id]
    for junction_id in lineage.created_junction_ids:
        junction = next(item for item in network.junctions if item.id == junction_id)
        position = junction.incident_film_ids.index(film_id)
        indices = junction.vertex_indices_by_film[position]
        centers.append(_mean(tuple(patch.mesh.vertices[index] for index in indices)))
    return _distance(centers[0], centers[1])


def switch_benchmark() -> dict[str, object]:
    state = build_supported_pre_t1_state(resolution_m=0.12)
    eligibility = detect_t1_eligibility(state)
    result = perform_t1_transaction(state)
    before_pairs = set(internal_adjacency_pairs(result.before))
    after_pairs = set(internal_adjacency_pairs(result.after))
    assert eligibility.neighborhood is not None
    old_pair = tuple(sorted(eligibility.neighborhood.old_adjacent_regions))
    new_pair = tuple(sorted(eligibility.neighborhood.opposite_regions))
    created = next(
        patch for patch in result.after.to_network().patches
        if patch.id == result.lineage.created_film_ids[0]
    )
    replay = perform_t1_transaction(build_supported_pre_t1_state(resolution_m=0.12))
    passed = bool(
        eligibility.eligible
        and old_pair in before_pairs
        and old_pair not in after_pairs
        and new_pair not in before_pairs
        and new_pair in after_pairs
        and result.before.topology.region_ids == result.after.topology.region_ids
        and len(result.lineage.retired_film_ids) == 1
        and len(result.lineage.created_film_ids) == 1
        and len(result.lineage.retired_junction_ids) == 2
        and len(result.lineage.created_junction_ids) == 2
        and created.mesh.area() > 0.0
        and result.seed_requires_relaxation
        and result.after.topology_signature() == replay.after.topology_signature()
        and result.after.positions == replay.after.positions
        and result.lineage == replay.lineage
    )
    return {
        "name": "switch",
        "pass": passed,
        "eligibility": asdict(eligibility),
        "lineage": asdict(result.lineage),
        "before_adjacency": tuple(sorted(before_pairs)),
        "after_adjacency": tuple(sorted(after_pairs)),
        "created_film_area_m2": created.mesh.area(),
        "created_film_span_m": _created_film_span(result),
        "deterministic_replay": result.after.topology_signature() == replay.after.topology_signature()
        and result.after.positions == replay.after.positions,
        "seed_requires_relaxation": result.seed_requires_relaxation,
        "claim_boundary": "qualified four-region quasi-2D/extruded class only",
    }


def conservation_benchmark() -> dict[str, object]:
    settings = T1TransactionSettings(volume_relative_tolerance=2.0e-10)
    state = build_supported_pre_t1_state(resolution_m=0.12)
    result = perform_t1_transaction(state, settings)
    before_targets = tuple(
        (region.id, region.target_volume_m3)
        for region in result.before.to_network().regions
    )
    after_targets = tuple(
        (region.id, region.target_volume_m3)
        for region in result.after.to_network().regions
    )
    max_before = max(error for _, error in result.volume_errors_before)
    max_after = max(error for _, error in result.volume_errors_after)
    passed = bool(
        before_targets == after_targets
        and result.before.topology.region_ids == result.after.topology.region_ids
        and max_before <= settings.volume_relative_tolerance
        and max_after <= settings.volume_relative_tolerance
        and result.before.time_s == result.after.time_s
        and result.before.step_index == result.after.step_index
    )
    return {
        "name": "conservation",
        "pass": passed,
        "target_volumes_m3": before_targets,
        "volume_errors_before": result.volume_errors_before,
        "volume_errors_after": result.volume_errors_after,
        "max_relative_volume_error_before": max_before,
        "max_relative_volume_error_after": max_after,
        "configured_tolerance": settings.volume_relative_tolerance,
        "instantaneous_event_preserves_clock": result.before.time_s == result.after.time_s
        and result.before.step_index == result.after.step_index,
    }


def refinement_benchmark() -> dict[str, object]:
    nominal = (0.24, 0.12, 0.06, 0.03)
    settings = T1TransactionSettings(seed_fraction=0.55)
    rows: list[dict[str, object]] = []
    for resolution in nominal:
        state = build_supported_pre_t1_state(resolution_m=resolution)
        eligibility = detect_t1_eligibility(state, settings.eligibility)
        result = perform_t1_transaction(state, settings)
        seed_span = _created_film_span(result)
        max_volume_error = max(error for _, error in result.volume_errors_after)
        rows.append({
            "nominal_resolution_m": resolution,
            "measured_resolution_m": eligibility.resolution_m,
            "collapse_length_m": eligibility.collapsing_length_m,
            "threshold_m": eligibility.threshold_m,
            "collapse_threshold_ratio": eligibility.collapsing_length_m / eligibility.threshold_m,
            "seed_resolution_ratio": seed_span / eligibility.resolution_m,
            "eligible": eligibility.eligible,
            "post_adjacencies": internal_adjacency_pairs(result.after),
            "max_relative_volume_error": max_volume_error,
            "created_film_area_m2": next(
                patch.mesh.area()
                for patch in result.after.to_network().patches
                if patch.id == result.lineage.created_film_ids[0]
            ),
        })
    topology = rows[0]["post_adjacencies"]
    collapse_ratios = [float(row["collapse_threshold_ratio"]) for row in rows]
    seed_ratios = [float(row["seed_resolution_ratio"]) for row in rows]
    passed = bool(
        all(bool(row["eligible"]) for row in rows)
        and all(row["post_adjacencies"] == topology for row in rows[1:])
        and max(collapse_ratios) - min(collapse_ratios) < 0.08
        and max(abs(value - settings.seed_fraction) for value in seed_ratios) < 1.0e-10
        and all(float(row["max_relative_volume_error"]) <= settings.volume_relative_tolerance for row in rows)
        and all(float(row["created_film_area_m2"]) > 0.0 for row in rows)
    )
    return {
        "name": "refinement",
        "pass": passed,
        "rows": rows,
        "interpretation": "The qualified topology switch is invariant under refinement; conservative projection enforces the production volume tolerance at every tested resolution.",
    }


def run_named(name: str) -> dict[str, object]:
    functions = {
        "switch": switch_benchmark,
        "conservation": conservation_benchmark,
        "refinement": refinement_benchmark,
    }
    if name not in functions:
        raise ValueError(f"unknown T1 benchmark {name!r}")
    return functions[name]()
