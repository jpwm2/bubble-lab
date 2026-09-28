#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[5]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from bubblelab.solvers.equilibrium.mesh import SurfaceMesh
from bubblelab.solvers.equilibrium.network import FilmNetwork, FilmPatch, PlateauJunction
from bubblelab.solvers.transient.network.core import TransientNetworkState
from bubblelab.solvers.transient.network.t1_3d import detect_t1_3d_eligibility
from bubblelab.solvers.transient.network.t1_hydrodynamics import (
    DirectT1Settings,
    build_direct_3d_t1_state,
    perform_direct_t1_transaction,
)


def _settings() -> DirectT1Settings:
    return DirectT1Settings(
        plateau_border_core_radius_m=0.010,
        hydrodynamic_segments=32,
    )


def _direct_state(**kwargs: object) -> TransientNetworkState:
    return build_direct_3d_t1_state(
        amplitude_m_inv=0.8,
        y_saturation_m=0.04,
        **kwargs,
    )


def _rotate(point: tuple[float, float, float]) -> tuple[float, float, float]:
    ax, ay, az = 0.41, -0.27, 0.63
    x, y, z = point
    cx, sx = math.cos(ax), math.sin(ax)
    y, z = cx * y - sx * z, sx * y + cx * z
    cy, sy = math.cos(ay), math.sin(ay)
    x, z = cy * x + sy * z, -sy * x + cy * z
    cz, sz = math.cos(az), math.sin(az)
    return (cz * x - sz * y, sz * x + cz * y, z)


def _rotate_state(state: TransientNetworkState) -> TransientNetworkState:
    network = state.to_network()
    patches = tuple(
        FilmPatch(
            id=patch.id,
            mesh=patch.mesh.with_vertices(_rotate(vertex) for vertex in patch.mesh.vertices),
            adjacent=patch.adjacent,
            sheet_tension_n_m=patch.sheet_tension_n_m,
            fixed_vertex_indices=patch.fixed_vertex_indices,
            contributes_to_volume=patch.contributes_to_volume,
        )
        for patch in network.patches
    )
    return TransientNetworkState.from_network(FilmNetwork(network.regions, patches, network.junctions))


def _subdivide_local_state(state: TransientNetworkState) -> TransientNetworkState:
    """Conformingly subdivide the five local sheets without changing geometry."""
    network = state.to_network()
    midpoint_maps: dict[str, dict[tuple[int, int], int]] = {}
    patches = []
    for patch_ in network.patches:
        if patch_.contributes_to_volume:
            patches.append(patch_)
            continue
        vertices = list(patch_.mesh.vertices)
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
        for a, b, c in patch_.mesh.faces:
            ab = midpoint(a, b)
            bc = midpoint(b, c)
            ca = midpoint(c, a)
            faces.extend(((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)))
        original_fixed = set(patch_.fixed_vertex_indices)
        fixed = set(original_fixed)
        fixed.update(
            index
            for (left, right), index in midpoints.items()
            if left in original_fixed and right in original_fixed
        )
        patches.append(FilmPatch(
            id=patch_.id,
            mesh=SurfaceMesh.from_iterables(vertices, faces),
            adjacent=patch_.adjacent,
            sheet_tension_n_m=patch_.sheet_tension_n_m,
            fixed_vertex_indices=tuple(sorted(fixed)),
            contributes_to_volume=patch_.contributes_to_volume,
        ))
        midpoint_maps[patch_.id] = midpoints

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
    refined_network = FilmNetwork(network.regions, tuple(patches), tuple(junctions))
    refined_network.validate()
    return TransientNetworkState.from_network(refined_network)


def switch_probe() -> dict[str, object]:
    cfg = _settings()
    rows = []
    supported_class = ""
    for mode in ("twisted-saturation", "saddle-saturation"):
        state = _direct_state(mode=mode)
        legacy = detect_t1_3d_eligibility(state)
        with patch(
            "bubblelab.solvers.transient.network.t1_3d.detect_t1_3d_eligibility",
            side_effect=AssertionError("legacy detector was called"),
        ), patch(
            "bubblelab.solvers.transient.network.t1_3d.perform_t1_3d_transaction",
            side_effect=AssertionError("legacy transaction was called"),
        ):
            result = perform_direct_t1_transaction(state, cfg)
        neighborhood = result.eligibility.neighborhood
        if neighborhood is None:
            raise AssertionError("eligible result has no neighborhood")
        supported_class = result.eligibility.supported_class
        rows.append({
            "mode": mode,
            "legacy_bilinear_eligible": legacy.eligible,
            "event_time_s": result.forecast.event_time_s,
            "initial_force_n": result.forecast.initial_force_n,
            "old_pair": list(neighborhood.old_adjacent_regions),
            "new_pair": list(neighborhood.opposite_regions),
            "adjacency_before": [list(value) for value in result.adjacency_before],
            "adjacency_after": [list(value) for value in result.adjacency_after],
            "created_film": result.lineage.created_film_ids[0],
            "created_junctions": list(result.lineage.created_junction_ids),
            "max_nonplanarity_m": result.eligibility.max_nonplanarity_m,
            "junction_tangent_spread": result.eligibility.junction_tangent_spread,
        })
    return {"probe": "switch", "supported_class": supported_class, "fixtures": rows}


def conservation_probe() -> dict[str, object]:
    cfg = _settings()
    state = _direct_state(mode="saddle-saturation")
    first = perform_direct_t1_transaction(state, cfg)
    second = perform_direct_t1_transaction(state, cfg)
    return {
        "probe": "conservation",
        "max_relative_volume_error": max(error for _, error in first.volume_errors_after),
        "stable_region_ids": (
            [region.id for region in first.after.to_network().regions]
            == [region.id for region in first.before.to_network().regions]
        ),
        "deterministic_forecast": first.forecast == second.forecast,
        "deterministic_lineage": first.lineage == second.lineage,
        "deterministic_state": first.after == second.after,
        "event_time_s": first.forecast.event_time_s,
    }


def refinement_probe() -> dict[str, object]:
    # Refinement must isolate discretization from geometry. Start with one
    # physical piecewise-linear 3D neighborhood and conformingly subdivide it;
    # regenerating a nonlinear analytic warp at a new resolution changes the
    # represented surface and confounds geometric sampling error with mesh
    # dependence of the event model itself.
    cfg = DirectT1Settings(
        plateau_border_core_radius_m=0.010,
        hydrodynamic_segments=32,
        maximum_core_to_edge_ratio=1.0,
    )
    state = _direct_state(
        resolution_m=0.12,
        initial_gap_m=0.050,
        mode="twisted-saturation",
    )
    rows = []
    for level in range(3):
        result = perform_direct_t1_transaction(state, cfg)
        neighborhood = result.eligibility.neighborhood
        if neighborhood is None:
            raise AssertionError("eligible refinement result has no neighborhood")
        rows.append({
            "level": level,
            "resolution_m": result.eligibility.resolution_m,
            "initial_gap_m": result.eligibility.initial_gap_m,
            "event_time_s": result.forecast.event_time_s,
            "initial_force_n": result.forecast.initial_force_n,
            "created_pair": list(neighborhood.opposite_regions),
            "max_volume_error": max(error for _, error in result.volume_errors_after),
        })
        if level < 2:
            state = _subdivide_local_state(state)

    reference_gap = float(rows[0]["initial_gap_m"])
    reference_time = float(rows[0]["event_time_s"])
    reference_force = float(rows[0]["initial_force_n"])
    return {
        "probe": "refinement",
        "event_gap_m": 2.0 * cfg.plateau_border_core_radius_m,
        "rows": rows,
        "max_gap_drift_m": max(abs(float(row["initial_gap_m"]) - reference_gap) for row in rows),
        "max_event_time_drift_s": max(abs(float(row["event_time_s"]) - reference_time) for row in rows),
        "max_force_drift_n": max(abs(float(row["initial_force_n"]) - reference_force) for row in rows),
    }


def rotation_probe() -> dict[str, object]:
    cfg = _settings()
    state = _direct_state(mode="twisted-saturation")
    rotated = _rotate_state(state)
    base = perform_direct_t1_transaction(state, cfg)
    turned = perform_direct_t1_transaction(rotated, cfg)
    return {
        "probe": "rotation",
        "base_event_time_s": base.forecast.event_time_s,
        "rotated_event_time_s": turned.forecast.event_time_s,
        "event_time_abs_error_s": abs(base.forecast.event_time_s - turned.forecast.event_time_s),
        "force_abs_error_n": abs(base.forecast.initial_force_n - turned.forecast.initial_force_n),
        "same_post_topology": base.adjacency_after == turned.adjacency_after,
    }


def _assert_probe(result: dict[str, object]) -> None:
    probe = result["probe"]
    if probe == "switch":
        fixtures = result["fixtures"]
        assert isinstance(fixtures, list) and len(fixtures) >= 2
        for row in fixtures:
            assert row["legacy_bilinear_eligible"] is False
            assert row["event_time_s"] > 0 and row["initial_force_n"] > 0
            assert row["old_pair"] in row["adjacency_before"] and row["old_pair"] not in row["adjacency_after"]
            assert row["new_pair"] not in row["adjacency_before"] and row["new_pair"] in row["adjacency_after"]
            assert len(row["created_junctions"]) == 2
            assert row["max_nonplanarity_m"] > 0 and row["junction_tangent_spread"] > 0
    elif probe == "conservation":
        assert result["max_relative_volume_error"] <= 1.0e-12
        assert result["stable_region_ids"]
        assert result["deterministic_forecast"] and result["deterministic_lineage"] and result["deterministic_state"]
    elif probe == "refinement":
        rows = result["rows"]
        assert isinstance(rows, list) and len(rows) >= 3
        assert len({tuple(row["created_pair"]) for row in rows}) == 1
        assert max(row["max_volume_error"] for row in rows) <= 1.0e-12
        assert all(float(rows[index + 1]["resolution_m"]) < float(rows[index]["resolution_m"]) for index in range(len(rows) - 1))
        assert result["max_gap_drift_m"] <= 1.0e-12
        assert result["max_force_drift_n"] <= 1.0e-12
        assert result["max_event_time_drift_s"] <= 1.0e-11
    elif probe == "rotation":
        assert result["same_post_topology"]
        scale = max(abs(result["base_event_time_s"]), 1.0)
        assert result["event_time_abs_error_s"] <= 1.0e-10 * scale
        assert result["force_abs_error_n"] <= 1.0e-10
    else:
        raise AssertionError(f"unknown benchmark probe {probe!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("probe", choices=("switch", "conservation", "refinement", "rotation"))
    parser.add_argument("--assert", dest="assert_result", action="store_true")
    args = parser.parse_args()
    functions = {
        "switch": switch_probe,
        "conservation": conservation_probe,
        "refinement": refinement_probe,
        "rotation": rotation_probe,
    }
    result = functions[args.probe]()
    if args.assert_result:
        _assert_probe(result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())