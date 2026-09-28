"""Objective solid-boundary benchmarks used by the transient benchmark runner."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from .contact import enforce_front_contact, measure_contact_angle_deg
from .sdf import BoundarySet, PlaneBoundary, WettingParameters
from ..transient.geometry import FilmFront, icosphere
from ..transient.grid import GridConfig
from ..transient.solver import TimeStepPolicy, TransientConfig, TransientSoapFilmSolver


def _grid(background_velocity_m_s=(0.0, 0.0, 0.0)) -> GridConfig:
    return GridConfig(
        cells=(8, 8, 8),
        origin_m=(-0.02, -0.01, -0.02),
        extent_m=(0.04, 0.04, 0.04),
        density_kg_m3=1.204,
        dynamic_viscosity_pa_s=1.825e-5,
        background_velocity_m_s=background_velocity_m_s,
        pressure_iterations=320,
        pressure_tolerance_s_inv=1.0e-9,
    )


def _floor(target_angle_deg: float | None = None) -> PlaneBoundary:
    return PlaneBoundary(
        boundary_id="floor",
        point_m=(0.0, 0.0, 0.0),
        normal_outward=(0.0, 1.0, 0.0),
        wetting=WettingParameters(
            target_contact_angle_deg=target_angle_deg,
            relaxation=0.55,
            iterations=4,
            contact_band_m=5.0e-3,
        ),
    )


def _wall_contact_solver() -> TransientSoapFilmSolver:
    front = icosphere(
        radius_m=0.006,
        center_m=(0.0, 0.0048, 0.0),
        subdivisions=2,
        surface_tension_n_m=0.035,
        bubble_id="wall-bubble",
    )
    center = front.centroid()
    deformed = []
    for x, y, z in front.vertices:
        dx, dy, dz = x - center[0], y - center[1], z - center[2]
        deformed.append((center[0] + 1.12 * dx, center[1] + 0.92 * dy, center[2] + 0.88 * dz))
    front.vertices = deformed
    front.target_volume_m3 = front.volume()
    config = TransientConfig(
        grid=_grid((0.0, -0.04, 0.0)),
        gravity_m_s2=(0.0, 0.0, 0.0),
        timestep=TimeStepPolicy(max_dt_s=2.0e-5, capillary_safety=0.05),
        deterministic_seed=29,
        solid_boundaries=(_floor(),),
        boundary_tolerance_m=1.0e-8,
        boundary_projection_iterations=5,
    )
    return TransientSoapFilmSolver([front], config)


def wall_contact() -> dict[str, Any]:
    solver = _wall_contact_solver()
    initial_vertices = tuple(solver.fronts[0].vertices)
    diagnostic = solver.step(2.0e-5)
    front = solver.fronts[0]
    wall = solver.boundaries.boundaries[0]
    min_distance = min(wall.signed_distance(vertex) for vertex in front.vertices)
    moved = [
        math.sqrt(sum((a - b) ** 2 for a, b in zip(after, before)))
        for before, after in zip(initial_vertices, front.vertices)
    ]
    moving_vertices = sum(distance > 1.0e-12 for distance in moved)
    contact_vertices = diagnostic.boundary_contact_vertex_count
    local_contact = 2 <= contact_vertices < len(front.vertices)
    nonuniform_motion = max(moved, default=0.0) - min(moved, default=0.0) > 1.0e-8
    metrics = {
        "minimum_signed_distance_m": min_distance,
        "max_penetration_pre_m": diagnostic.boundary_max_penetration_pre_m,
        "max_penetration_post_m": diagnostic.boundary_max_penetration_post_m,
        "contact_vertex_count": contact_vertices,
        "contact_face_count": diagnostic.boundary_contact_face_count,
        "moving_vertex_count": moving_vertices,
        "max_relative_volume_error": diagnostic.max_relative_volume_error,
        "position_correction_l1_m": diagnostic.boundary_position_correction_l1_m,
        "local_contact": local_contact,
        "nonuniform_vertex_motion": nonuniform_motion,
    }
    gates = {
        "penetration_tolerance_m": solver.config.boundary_tolerance_m,
        "minimum_contact_vertices": 2,
        "max_relative_volume_error": 2.0e-5,
    }
    passed = (
        min_distance >= -solver.config.boundary_tolerance_m
        and diagnostic.boundary_max_penetration_post_m <= solver.config.boundary_tolerance_m
        and local_contact
        and nonuniform_motion
        and diagnostic.boundary_position_correction_l1_m > 0.0
        and diagnostic.max_relative_volume_error <= gates["max_relative_volume_error"]
        and "floor" in diagnostic.boundary_ids
    )
    return {
        "benchmark": "wall-contact",
        "claim_level": "TRACKED_FRONT_SOLID_CONTACT",
        "matrix_mapping": ["R10", "R11", "R20", "R21", "R31", "R33"],
        "qualification": (
            "Tracked-film SDF no-penetration with free-slip tangential front motion. "
            "The ambient Eulerian grid remains periodic and does not resolve a no-slip wall."
        ),
        "metrics": metrics,
        "gates": gates,
        "boundary_reports": list(diagnostic.boundary_reports),
        "passed": bool(passed),
    }


def _frustum_front() -> FilmFront:
    vertices = [
        (-0.003, -2.0e-4, -0.003),
        (0.003, -2.0e-4, -0.003),
        (0.003, -2.0e-4, 0.003),
        (-0.003, -2.0e-4, 0.003),
        (-0.0042, 0.0020, -0.0042),
        (0.0042, 0.0020, -0.0042),
        (0.0042, 0.0020, 0.0042),
        (-0.0042, 0.0020, 0.0042),
    ]
    faces = [
        (0, 2, 1), (0, 3, 2),
        (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4),
        (1, 2, 6), (1, 6, 5),
        (2, 3, 7), (2, 7, 6),
        (3, 0, 4), (3, 4, 7),
    ]
    return FilmFront(
        bubble_id="wetting-bubble",
        mesh_id="mesh-wetting-bubble",
        film_id="film-wetting-bubble",
        vertices=vertices,
        faces=faces,
        surface_tension_n_m=0.03,
    )


def contact_angle() -> dict[str, Any]:
    target = 60.0
    floor = _floor(target)
    front = _frustum_front()
    boundary_set = BoundarySet((floor,))
    pre = enforce_front_contact(front, boundary_set, 1.0e-8, 2.0e-5, apply_wetting=False)
    contact_indices = pre["boundaries"][0]["contact_vertex_indices"]
    pre_angle = measure_contact_angle_deg(front, floor, contact_indices)
    post = enforce_front_contact(front, boundary_set, 1.0e-8, 2.0e-5, apply_wetting=True)
    contact_indices = post["boundaries"][0]["contact_vertex_indices"]
    post_angle = measure_contact_angle_deg(front, floor, contact_indices)
    if pre_angle is None or post_angle is None:
        pre_residual = post_residual = float("inf")
    else:
        pre_residual = abs(pre_angle - target)
        post_residual = abs(post_angle - target)
    metrics = {
        "target_contact_angle_deg": target,
        "pre_contact_angle_deg": pre_angle,
        "post_contact_angle_deg": post_angle,
        "pre_residual_deg": pre_residual,
        "post_residual_deg": post_residual,
        "contact_vertex_count": post["contact_vertex_count"],
        "max_penetration_post_m": post["max_penetration_post_m"],
    }
    gates = {
        "absolute_contact_angle_error_deg": 18.0,
        "requires_residual_improvement": True,
    }
    passed = (
        post_angle is not None
        and post_residual <= gates["absolute_contact_angle_error_deg"]
        and post_residual < pre_residual
        and post["max_penetration_post_m"] <= 1.0e-8
    )
    return {
        "benchmark": "contact-angle",
        "claim_level": "MODELED_LOCAL_WETTING",
        "matrix_mapping": ["R17", "R20", "R22", "R34", "R35"],
        "qualification": (
            "Contact angle is measured from side-face geometry and relaxed toward the requested value; "
            "it is not copied from configuration. The closed-front mesh does not represent a finite liquid meniscus."
        ),
        "metrics": metrics,
        "gates": gates,
        "passed": bool(passed),
    }


def boundary_replay() -> dict[str, Any]:
    def run() -> tuple[str, TransientSoapFilmSolver]:
        solver = _wall_contact_solver()
        for _ in range(2):
            solver.step(2.0e-5)
        payload = json.dumps(solver.replay_signature(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest(), solver

    hash_a, solver_a = run()
    hash_b, solver_b = run()
    reports_equal = [d.boundary_reports for d in solver_a.history] == [d.boundary_reports for d in solver_b.history]
    ids_sorted = all(tuple(sorted(d.boundary_ids)) == d.boundary_ids for d in solver_a.history)
    passed = hash_a == hash_b and reports_equal and ids_sorted
    return {
        "benchmark": "boundary-replay",
        "claim_level": "DETERMINISTIC_BOUNDARY_REPLAY",
        "matrix_mapping": ["R21", "R33", "R38"],
        "qualification": "Same-build replay includes deterministic contact ordering, geometry and boundary diagnostics.",
        "metrics": {
            "hash_equal": hash_a == hash_b,
            "reports_equal": reports_equal,
            "boundary_ids_stably_sorted": ids_sorted,
        },
        "hashes": [hash_a, hash_b],
        "passed": bool(passed),
    }


BENCHMARKS = {
    "wall-contact": wall_contact,
    "contact-angle": contact_angle,
    "boundary-replay": boundary_replay,
}
