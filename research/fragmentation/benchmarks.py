"""Executable evidence for fragmentation research decisions."""
from __future__ import annotations

import math
from typing import Any

from geometry import add, mul, necked_mesh, ellipsoid_mesh, rotate_mesh
from neck import diagnose_neck
from bookkeeping import ParentState, split_parent


def _relative(a: float, b: float) -> float:
    return abs(a - b) / max(abs(a), abs(b), 1.0e-300)


def _sorted_fraction_error(a: tuple[float, float], b: tuple[float, float]) -> float:
    aa, bb = sorted(a), sorted(b)
    return max(abs(aa[0] - bb[0]), abs(aa[1] - bb[1]))


def neck_detection_benchmark(assert_result: bool = False) -> dict[str, Any]:
    mesh = necked_mesh(axial_segments=24, circum_segments=36)
    diagnostic = diagnose_neck(mesh)
    elongated = diagnose_neck(ellipsoid_mesh(axial_segments=24, circum_segments=36))
    rotated = diagnose_neck(rotate_mesh(mesh, (0.31, 0.77, 0.55), 0.83))

    radius_rotation_error = _relative(float(diagnostic.neck_radius or 0.0), float(rotated.neck_radius or 0.0))
    fraction_rotation_error = _sorted_fraction_error(
        diagnostic.child_volume_fractions or (0.0, 0.0),
        rotated.child_volume_fractions or (0.0, 0.0),
    )
    result = {
        "benchmark": "neck-detection",
        "necked_detected": diagnostic.detected,
        "ellipsoid_detected": elongated.detected,
        "topologically_separable": diagnostic.topologically_separable,
        "neck_radius": diagnostic.neck_radius,
        "mesh_spacing": diagnostic.mesh_spacing,
        "radius_to_spacing": diagnostic.radius_to_spacing,
        "prominence_ratio": diagnostic.prominence_ratio,
        "cut_coordinate": diagnostic.cut_coordinate,
        "child_volume_fractions": diagnostic.child_volume_fractions,
        "rotation_radius_relative_error": radius_rotation_error,
        "rotation_child_fraction_max_error": fraction_rotation_error,
        "rotated_detected": rotated.detected,
    }
    if assert_result:
        assert diagnostic.detected, result
        assert diagnostic.topologically_separable, result
        assert not elongated.detected, result
        assert rotated.detected, result
        assert diagnostic.prominence_ratio >= 1.30, result
        assert radius_rotation_error <= 0.035, result
        assert fraction_rotation_error <= 0.025, result
    return result


def split_bookkeeping_benchmark(assert_result: bool = False) -> dict[str, Any]:
    mesh = necked_mesh(axial_segments=24, circum_segments=36)
    diagnostic = diagnose_neck(mesh)
    if not diagnostic.detected or diagnostic.child_volume_fractions is None or diagnostic.child_axis_centroids is None:
        raise RuntimeError("neck benchmark did not produce a split candidate")

    axis = diagnostic.axis
    origin = diagnostic.origin
    provisional = tuple(add(origin, mul(axis, t)) for t in diagnostic.child_axis_centroids)
    parent = ParentState(
        id="research-parent-1",
        target_volume=mesh.volume(),
        gas_amount=2.75e-6,
        centroid=mesh.volume_centroid(),
        velocity=(0.35, -0.12, 0.08),
        mass=8.4e-8,
    )
    provenance = {
        "source": "RESEARCH_BENCHMARK",
        "criterion": "MESH_CROSS_SECTIONAL_NECK_AND_SEPARATING_CUT",
        "neck_radius": diagnostic.neck_radius,
        "mesh_spacing": diagnostic.mesh_spacing,
        "prominence_ratio": diagnostic.prominence_ratio,
        "requires_dynamic_confirmation": True,
    }
    result_a = split_parent(
        parent,
        volume_fractions=diagnostic.child_volume_fractions,
        provisional_centroids=provisional,
        event_time=0.0125,
        trigger_provenance=provenance,
    )
    result_b = split_parent(
        parent,
        volume_fractions=diagnostic.child_volume_fractions,
        provisional_centroids=provisional,
        event_time=0.0125,
        trigger_provenance=provenance,
    )
    conservation = result_a.conservation
    output = {
        "benchmark": "split-bookkeeping",
        "event_id": result_a.event_id,
        "child_ids": [child.id for child in result_a.children],
        "lineage": {child.id: list(child.lineage) for child in result_a.children},
        "child_volume_fractions": diagnostic.child_volume_fractions,
        "conservation": conservation,
        "deterministic_replay": result_a == result_b,
        "geometry_statuses": [child.geometry_status for child in result_a.children],
        "surface_energy_change": result_a.surface_energy_change,
    }
    if assert_result:
        assert result_a == result_b, output
        assert conservation["target_volume_relative_error"] <= 1.0e-12, output
        assert float(conservation["gas_amount_relative_error"] or 0.0) <= 1.0e-12, output
        assert float(conservation["center_of_mass_relative_error"] or 0.0) <= 1.0e-12, output
        assert float(conservation["linear_momentum_relative_error"] or 0.0) <= 1.0e-12, output
        assert result_a.surface_energy_change is None, output
        assert all(child.lineage == (parent.id,) for child in result_a.children), output
    return output


def neck_resolution_benchmark(assert_result: bool = False) -> dict[str, Any]:
    levels = (
        ("coarse", 16, 24),
        ("medium", 24, 36),
        ("fine", 36, 54),
    )
    rows: list[dict[str, Any]] = []
    for name, axial, circum in levels:
        base_mesh = necked_mesh(axial_segments=axial, circum_segments=circum)
        base = diagnose_neck(base_mesh)
        rotated = diagnose_neck(rotate_mesh(base_mesh, (0.41, 0.23, 0.88), 0.67))
        if base.child_volume_fractions is None or rotated.child_volume_fractions is None:
            raise RuntimeError(f"resolution level {name} did not detect a neck")
        rows.append({
            "level": name,
            "axial_segments": axial,
            "circum_segments": circum,
            "mesh_spacing": base.mesh_spacing,
            "neck_radius": base.neck_radius,
            "cut_abs": abs(float(base.cut_coordinate or 0.0)),
            "child_volume_fractions": base.child_volume_fractions,
            "prominence_ratio": base.prominence_ratio,
            "orientation_radius_error": _relative(float(base.neck_radius or 0.0), float(rotated.neck_radius or 0.0)),
            "orientation_cut_error": abs(abs(float(base.cut_coordinate or 0.0)) - abs(float(rotated.cut_coordinate or 0.0))),
            "orientation_fraction_error": _sorted_fraction_error(base.child_volume_fractions, rotated.child_volume_fractions),
            "detected": base.detected and rotated.detected,
            "separable": base.topologically_separable and rotated.topologically_separable,
        })

    coarse, medium, fine = rows
    radius_cm = _relative(float(coarse["neck_radius"]), float(medium["neck_radius"]))
    radius_mf = _relative(float(medium["neck_radius"]), float(fine["neck_radius"]))
    fraction_cm = _sorted_fraction_error(coarse["child_volume_fractions"], medium["child_volume_fractions"])
    fraction_mf = _sorted_fraction_error(medium["child_volume_fractions"], fine["child_volume_fractions"])
    cut_cm = abs(float(coarse["cut_abs"]) - float(medium["cut_abs"]))
    cut_mf = abs(float(medium["cut_abs"]) - float(fine["cut_abs"]))

    result = {
        "benchmark": "neck-resolution",
        "levels": rows,
        "refinement_deltas": {
            "radius_coarse_medium": radius_cm,
            "radius_medium_fine": radius_mf,
            "fraction_coarse_medium": fraction_cm,
            "fraction_medium_fine": fraction_mf,
            "cut_coarse_medium": cut_cm,
            "cut_medium_fine": cut_mf,
        },
        "convergence_trend": {
            "radius_improves": radius_mf <= 1.35 * radius_cm,
            "fraction_improves": fraction_mf <= 1.35 * fraction_cm + 1.0e-12,
            "cut_improves": cut_mf <= 1.35 * cut_cm + 1.0e-12,
        },
    }
    if assert_result:
        assert all(row["detected"] and row["separable"] for row in rows), result
        assert max(float(row["orientation_radius_error"]) for row in rows) <= 0.05, result
        assert max(float(row["orientation_fraction_error"]) for row in rows) <= 0.035, result
        assert radius_mf <= 0.08, result
        assert fraction_mf <= 0.025, result
        assert cut_mf <= 0.08, result
        assert all(result["convergence_trend"].values()), result
    return result


def all_benchmarks(assert_result: bool = False) -> dict[str, Any]:
    return {
        "neck_detection": neck_detection_benchmark(assert_result),
        "split_bookkeeping": split_bookkeeping_benchmark(assert_result),
        "neck_resolution": neck_resolution_benchmark(assert_result),
    }
