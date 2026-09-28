"""Acceptance benchmarks for deterministic production fragmentation."""
from __future__ import annotations

import math
from typing import Any

from .geometry import ellipsoid_mesh, necked_mesh, rotate_mesh
from .neck import diagnose_neck
from .split import ParentState, split_parent
from .surgery import UnsupportedFragmentation


def _relative(a: float, b: float) -> float:
    return abs(a - b) / max(abs(a), abs(b), 1.0e-300)


def _fractions(result: Any) -> tuple[float, float]:
    total = math.fsum(child.represented_volume_m3 for child in result.children)
    return tuple(child.represented_volume_m3 / total for child in result.children)  # type: ignore[return-value]


def _sorted_fraction_error(a: tuple[float, float], b: tuple[float, float]) -> float:
    aa, bb = sorted(a), sorted(b)
    return max(abs(aa[0] - bb[0]), abs(aa[1] - bb[1]))


def neck_split_benchmark(assert_result: bool = False) -> dict[str, Any]:
    mesh = necked_mesh(axial_segments=24, circum_segments=36)
    parent = ParentState("benchmark-necked-parent", mesh, mesh.volume(), 2.5e-6, (0.2, -0.1, 0.05), 7.5e-8)
    result = split_parent(parent, event_time_s=0.01)
    elongated = ellipsoid_mesh(axial_segments=24, circum_segments=36)
    elongated_diag = diagnose_neck(elongated)
    rejected = False
    try:
        split_parent(ParentState("benchmark-ellipsoid", elongated, elongated.volume(), 1.0e-6), event_time_s=0.01)
    except UnsupportedFragmentation:
        rejected = True
    output = {
        "benchmark": "neck-split",
        "event_type": result.event_contract()["type"],
        "parent_status": result.parent_status,
        "child_statuses": [child.status for child in result.children],
        "child_closed_manifold": [child.mesh.is_closed_manifold() for child in result.children],
        "child_positive_volume": [child.mesh.volume() > 0.0 for child in result.children],
        "cut_loop_vertex_counts": [result.surgery.negative.cut_loop_vertex_count, result.surgery.positive.cut_loop_vertex_count],
        "inserted_intersection_vertex_counts": [result.surgery.negative.inserted_intersection_vertex_count, result.surgery.positive.inserted_intersection_vertex_count],
        "reused_parent_vertex_counts": [result.surgery.negative.reused_parent_vertex_count, result.surgery.positive.reused_parent_vertex_count],
        "geometric_volume_relative_error": result.surgery.geometric_volume_relative_error,
        "neck_prominence": result.diagnostic.prominence_ratio,
        "radius_to_spacing": result.diagnostic.radius_to_spacing,
        "ellipsoid_detected": elongated_diag.detected,
        "ellipsoid_split_rejected": rejected,
        "restart_geometry_statuses": [child.geometry_status for child in result.children],
    }
    if assert_result:
        assert output["event_type"] == "SPLIT", output
        assert output["parent_status"] == "SPLIT", output
        assert all(output["child_closed_manifold"]), output
        assert all(output["child_positive_volume"]), output
        assert min(output["inserted_intersection_vertex_counts"]) >= 12, output
        assert min(output["reused_parent_vertex_counts"]) >= 100, output
        assert float(output["geometric_volume_relative_error"]) <= 5.0e-11, output
        assert not output["ellipsoid_detected"], output
        assert output["ellipsoid_split_rejected"], output
    return output


def conservation_benchmark(assert_result: bool = False) -> dict[str, Any]:
    mesh = necked_mesh(axial_segments=24, circum_segments=36)
    parent = ParentState(
        "benchmark-conservation-parent", mesh, 7.125, 2.75e-6,
        velocity_m_s=(0.35, -0.12, 0.08), mass_kg=8.4e-8,
    )
    a = split_parent(parent, event_time_s=0.0125)
    b = split_parent(parent, event_time_s=0.0125)
    output = {
        "benchmark": "conservation",
        "deterministic_replay": a == b,
        "event_id": a.event_id,
        "child_ids": [child.id for child in a.children],
        "child_lineage": {child.id: list(child.lineage) for child in a.children},
        "child_target_volumes": [child.target_volume_m3 for child in a.children],
        "child_gas_amounts": [child.gas_amount_mol for child in a.children],
        "conservation": dict(a.conservation),
        "event": a.event_contract(),
    }
    if assert_result:
        conservation = a.conservation
        assert a == b, output
        assert float(conservation["target_volume_relative_error"] or 0.0) <= 1.0e-12, output
        assert float(conservation["gas_amount_relative_error"] or 0.0) <= 1.0e-12, output
        assert float(conservation["geometric_volume_relative_error"] or 0.0) <= 5.0e-11, output
        assert float(conservation["center_of_mass_scale_relative_error"] or 0.0) <= 1.0e-11, output
        assert float(conservation["linear_momentum_relative_error"] or 0.0) <= 1.0e-12, output
        assert all(child.lineage == (parent.id,) for child in a.children), output
        assert a.event_contract()["type"] == "SPLIT", output
    return output


def refinement_benchmark(assert_result: bool = False) -> dict[str, Any]:
    levels = (("coarse", 16, 24), ("medium", 24, 36), ("fine", 36, 54))
    rows: list[dict[str, Any]] = []
    for name, axial, circum in levels:
        mesh = necked_mesh(axial_segments=axial, circum_segments=circum)
        rotated_mesh = rotate_mesh(mesh, (0.41, 0.23, 0.88), 0.67)
        result = split_parent(ParentState(f"refine-{name}", mesh, mesh.volume(), 1.0e-6), event_time_s=0.02)
        rotated = split_parent(ParentState(f"refine-{name}-rot", rotated_mesh, rotated_mesh.volume(), 1.0e-6), event_time_s=0.02)
        base_f = _fractions(result)
        rot_f = _fractions(rotated)
        rows.append({
            "level": name,
            "axial_segments": axial,
            "circum_segments": circum,
            "mesh_spacing": result.diagnostic.mesh_spacing,
            "neck_radius": result.diagnostic.neck_radius,
            "cut_abs": abs(float(result.diagnostic.cut_coordinate or 0.0)),
            "child_volume_fractions": base_f,
            "geometric_volume_relative_error": result.surgery.geometric_volume_relative_error,
            "orientation_radius_error": _relative(float(result.diagnostic.neck_radius or 0.0), float(rotated.diagnostic.neck_radius or 0.0)),
            "orientation_cut_error": abs(abs(float(result.diagnostic.cut_coordinate or 0.0)) - abs(float(rotated.diagnostic.cut_coordinate or 0.0))),
            "orientation_fraction_error": _sorted_fraction_error(base_f, rot_f),
            "base_event_type": result.event_contract()["type"],
            "rotated_event_type": rotated.event_contract()["type"],
        })
    coarse, medium, fine = rows
    deltas = {
        "radius_coarse_medium": _relative(float(coarse["neck_radius"]), float(medium["neck_radius"])),
        "radius_medium_fine": _relative(float(medium["neck_radius"]), float(fine["neck_radius"])),
        "fraction_coarse_medium": _sorted_fraction_error(coarse["child_volume_fractions"], medium["child_volume_fractions"]),
        "fraction_medium_fine": _sorted_fraction_error(medium["child_volume_fractions"], fine["child_volume_fractions"]),
        "cut_coarse_medium": abs(float(coarse["cut_abs"]) - float(medium["cut_abs"])),
        "cut_medium_fine": abs(float(medium["cut_abs"]) - float(fine["cut_abs"])),
    }
    result = {"benchmark": "refinement", "levels": rows, "refinement_deltas": deltas}
    if assert_result:
        assert all(row["base_event_type"] == "SPLIT" and row["rotated_event_type"] == "SPLIT" for row in rows), result
        assert max(float(row["orientation_radius_error"]) for row in rows) <= 0.06, result
        assert max(float(row["orientation_fraction_error"]) for row in rows) <= 0.04, result
        assert max(float(row["geometric_volume_relative_error"]) for row in rows) <= 5.0e-11, result
        assert float(deltas["radius_medium_fine"]) <= 0.08, result
        assert float(deltas["fraction_medium_fine"]) <= 0.03, result
        assert float(deltas["cut_medium_fine"]) <= 0.08, result
    return result
