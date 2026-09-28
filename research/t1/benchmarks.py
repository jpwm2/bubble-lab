"""Executable benchmark evidence for the scoped T1 research prototype."""
from __future__ import annotations

from dataclasses import asdict
import math

from .model import build_pre_t1_network, combine_disjoint_networks, translate_network
from .prototype import detect_eligibility, perform_neighbor_switch


def eligibility_benchmark() -> dict[str, object]:
    network = build_pre_t1_network(0.12)
    result = detect_eligibility(network)
    coarse = detect_eligibility(build_pre_t1_network(0.8))
    second = translate_network(build_pre_t1_network(0.12, id_prefix="x:"), 3.0, 0.0)
    ambiguous = detect_eligibility(combine_disjoint_networks(network, second))
    return {
        "name": "eligibility",
        "pass": bool(
            result.eligible
            and result.neighborhood is not None
            and len(result.neighborhood.old_adjacent_regions) == 2
            and len(result.neighborhood.opposite_regions) == 2
            and not coarse.eligible
            and "under-resolved" in coarse.reason
            and not ambiguous.eligible
            and ambiguous.reason == "ambiguous simultaneous collapses"
        ),
        "supported": asdict(result),
        "coarse_rejection": asdict(coarse),
        "ambiguous_rejection": asdict(ambiguous),
    }


def neighbor_switch_benchmark() -> dict[str, object]:
    network = build_pre_t1_network(0.12)
    result = perform_neighbor_switch(network)
    before_pairs = {tuple(sorted(film.adjacent)) for film in result.before.films}
    after_pairs = {tuple(sorted(film.adjacent)) for film in result.after.films}
    retired_pair = tuple(sorted(result.eligibility.neighborhood.old_adjacent_regions))  # type: ignore[union-attr]
    created_pair = tuple(sorted(result.eligibility.neighborhood.opposite_regions))  # type: ignore[union-attr]
    max_volume_error = max(dict(result.volume_errors_after).values())
    topology_ok = retired_pair in before_pairs and retired_pair not in after_pairs and created_pair not in before_pairs and created_pair in after_pairs
    return {
        "name": "neighbor-switch",
        "pass": bool(
            topology_ok
            and result.before.region_ids == result.after.region_ids
            and result.lineage.preserved_region_ids == tuple(sorted(result.before.region_ids))
            and len(after_pairs) == len(result.after.films)
            and max_volume_error < 0.08
            and result.after.minimum_triangle_quality() > 0.08
            and result.seed_requires_relaxation
        ),
        "lineage": asdict(result.lineage),
        "topology_before": result.before.topology_signature(),
        "topology_after": result.after.topology_signature(),
        "volume_errors_before": result.volume_errors_before,
        "volume_errors_after": result.volume_errors_after,
        "max_volume_error_after": max_volume_error,
        "surface_energy_before_j": result.energy_before_j,
        "surface_energy_after_j": result.energy_after_j,
        "surface_energy_delta_j": result.energy_after_j - result.energy_before_j,
        "junction_force_residual_before": result.force_residual_before,
        "junction_force_residual_after": result.force_residual_after,
        "minimum_feature_scale_after_m": result.after.minimum_feature_scale_m(),
        "minimum_triangle_quality_after": result.after.minimum_triangle_quality(),
        "seed_requires_relaxation": result.seed_requires_relaxation,
        "singular_energy_resolved": False,
    }


def refinement_benchmark() -> dict[str, object]:
    nominal = (0.24, 0.12, 0.06, 0.03)
    rows: list[dict[str, object]] = []
    for h in nominal:
        result = perform_neighbor_switch(build_pre_t1_network(h))
        eligibility = result.eligibility
        max_error = max(dict(result.volume_errors_after).values())
        rows.append({
            "nominal_resolution_m": h,
            "measured_resolution_m": eligibility.resolution_m,
            "collapse_length_m": eligibility.collapsing_length_m,
            "threshold_m": eligibility.threshold_m,
            "collapse_threshold_ratio": eligibility.collapsing_length_m / eligibility.threshold_m,
            "eligible": eligibility.eligible,
            "post_adjacencies": tuple(sorted(tuple(sorted(film.adjacent)) for film in result.after.films)),
            "max_relative_volume_error": max_error,
            "surface_energy_delta_j": result.energy_after_j - result.energy_before_j,
            "minimum_triangle_quality": result.after.minimum_triangle_quality(),
        })
    errors = [float(row["max_relative_volume_error"]) for row in rows]
    ratios = [float(row["collapse_threshold_ratio"]) for row in rows]
    slopes = [
        math.log(errors[i] / errors[i + 1]) / math.log(nominal[i] / nominal[i + 1])
        for i in range(len(errors) - 1)
    ]
    topology = rows[0]["post_adjacencies"]
    passed = (
        all(bool(row["eligible"]) for row in rows)
        and all(row["post_adjacencies"] == topology for row in rows[1:])
        and all(errors[i + 1] < errors[i] for i in range(len(errors) - 1))
        and min(slopes) > 0.75
        and max(ratios) - min(ratios) < 0.18
    )
    return {
        "name": "refinement",
        "pass": bool(passed),
        "rows": rows,
        "observed_volume_error_orders": slopes,
        "interpretation": "Raw seed volume error converges approximately first-order because the new finite seed displaces junctions O(h) against fixed far geometry; production use requires conservative projection/relaxation.",
    }


def run_named(name: str) -> dict[str, object]:
    functions = {
        "eligibility": eligibility_benchmark,
        "neighbor-switch": neighbor_switch_benchmark,
        "refinement": refinement_benchmark,
    }
    if name not in functions:
        raise ValueError(f"unknown benchmark {name!r}")
    return functions[name]()
