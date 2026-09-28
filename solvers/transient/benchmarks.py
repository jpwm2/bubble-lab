"""Objective sharp-interface benchmarks for the transient reference backend."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from .geometry import FilmFront, Vec3, icosphere, norm, sub
from .grid import GridConfig, RegionProperties
from .amr import AMRConfig, AdaptiveEulerianGasGrid
from .solver import TimeStepPolicy, TransientConfig, TransientSoapFilmSolver
from .remeshing import ConservativeArealField, FrontRemesher, RemeshConfig, mesh_quality


def _config(
    cells: int = 8,
    gravity: Vec3 = (0.0, 0.0, 0.0),
    region_properties: dict[str, RegionProperties] | None = None,
) -> TransientConfig:
    return TransientConfig(
        grid=GridConfig(
            cells=(cells, cells, cells),
            origin_m=(-0.02, -0.02, -0.02),
            extent_m=(0.04, 0.04, 0.04),
            density_kg_m3=1.204,
            dynamic_viscosity_pa_s=1.825e-5,
            pressure_iterations=360,
            pressure_tolerance_s_inv=1.0e-10,
        ),
        gravity_m_s2=gravity,
        timestep=TimeStepPolicy(max_dt_s=2.0e-5, capillary_safety=0.05),
        deterministic_seed=17,
        region_properties=region_properties or {},
        sharp_pressure_jump=True,
    )


def _front(
    radius_m: float = 0.008,
    subdivisions: int = 2,
    surface_tension_n_m: float = 0.05,
) -> FilmFront:
    return icosphere(
        radius_m=radius_m,
        subdivisions=subdivisions,
        surface_tension_n_m=surface_tension_n_m,
    )


def _static_level(cells: int) -> dict[str, float]:
    initial = _front()
    initial_area = initial.area()
    initial_volume = initial.volume()
    initial_center = initial.centroid()
    radius = initial.equivalent_radius()
    config = _config(cells)
    solver = TransientSoapFilmSolver([initial], config)
    diagnostic = None
    for _ in range(2):
        diagnostic = solver.step()
    assert diagnostic is not None
    final = solver.fronts[0]
    final_center = final.centroid()
    analytical_jump = 2.0 * final.surface_tension_n_m / radius
    measured_jump = solver.pressure_jump_pa(final.bubble_id)
    discrete_target = solver.target_pressure_jump_pa(final.bubble_id)
    capillary_speed = math.sqrt(
        final.surface_tension_n_m / (config.grid.density_kg_m3 * radius)
    )
    return {
        "cells_per_axis": float(cells),
        "eta_bulk": solver.grid.h / radius,
        "eta_surface": final.mean_edge_length() / radius,
        "volume_relative": abs(final.volume() - initial_volume) / initial_volume,
        "area_relative": abs(final.area() - initial_area) / initial_area,
        "centroid_over_r": norm(sub(final_center, initial_center)) / radius,
        "spurious_speed_over_capillary": diagnostic.max_speed_m_s / capillary_speed,
        "pressure_jump_relative_error": abs(measured_jump - analytical_jump) / analytical_jump,
        "discrete_jump_residual": abs(measured_jump - discrete_target) / analytical_jump,
        "divergence_linf_s_inv": diagnostic.divergence_linf_s_inv,
    }


def sharp_static_sphere() -> dict[str, Any]:
    coarse = _static_level(8)
    fine = _static_level(12)
    gates = {
        "volume_relative": 5.0e-10,
        "area_relative": 2.0e-6,
        "centroid_over_r": 2.0e-6,
        "spurious_speed_over_capillary": 1.0e-3,
        "pressure_jump_relative_error": 2.0e-2,
        "discrete_jump_residual": 2.0e-5,
    }
    level_pass = all(
        level[key] <= limit
        for level in (coarse, fine)
        for key, limit in gates.items()
    )
    refinement_pass = (
        fine["spurious_speed_over_capillary"]
        <= max(2.0 * coarse["spurious_speed_over_capillary"], 1.0e-8)
    )
    return {
        "benchmark": "sharp-static-sphere",
        "claim_level": "SHARP_CI_LADDER",
        "matrix_mapping": ["B02", "B03", "B07", "B12"],
        "qualification": (
            "Balanced sharp pressure-jump CI ladder. The uniform CI grids remain "
            "coarser than eta_b<=0.02, so this does not claim final fine-grid B12 "
            "release qualification."
        ),
        "levels": {"coarse": coarse, "fine": fine},
        "gates": gates,
        "refinement_gate": "fine spurious-current ratio <= 2x coarse (or 1e-8 floor)",
        "passed": bool(level_pass and refinement_pass),
    }


def _pressure_level(cells: int, subdivisions: int) -> dict[str, float]:
    front = _front(subdivisions=subdivisions)
    radius = front.equivalent_radius()
    analytical = 2.0 * front.surface_tension_n_m / radius
    solver = TransientSoapFilmSolver([front], _config(cells))
    solver.step()
    measured = solver.pressure_jump_pa(front.bubble_id)
    discrete = solver.target_pressure_jump_pa(front.bubble_id)
    return {
        "cells_per_axis": float(cells),
        "eta_bulk": solver.grid.h / radius,
        "eta_surface": solver.fronts[0].mean_edge_length() / radius,
        "analytical_pressure_jump_pa": analytical,
        "discrete_pressure_jump_pa": discrete,
        "measured_pressure_jump_pa": measured,
        "analytical_relative_error": abs(measured - analytical) / analytical,
        "discrete_relative_error": abs(measured - discrete) / analytical,
    }


def pressure_jump() -> dict[str, Any]:
    coarse = _pressure_level(8, 2)
    fine = _pressure_level(10, 3)
    gates = {
        "discrete_relative_error": 2.0e-5,
        "fine_analytical_relative_error": 5.0e-3,
    }
    passed = (
        coarse["discrete_relative_error"] <= gates["discrete_relative_error"]
        and fine["discrete_relative_error"] <= gates["discrete_relative_error"]
        and fine["analytical_relative_error"] <= gates["fine_analytical_relative_error"]
        and fine["analytical_relative_error"] < 0.5 * coarse["analytical_relative_error"]
    )
    return {
        "benchmark": "pressure-jump",
        "claim_level": "SHARP_CI_LADDER",
        "matrix_mapping": ["B02", "B09"],
        "qualification": (
            "Numerical pressure is compared both with geometry-derived discrete "
            "Young-Laplace jump and the analytical sphere reference. Curvature used "
            "by the solve is derived from the tracked triangle mesh, never from R."
        ),
        "levels": {"coarse": coarse, "fine": fine},
        "gates": gates,
        "refinement_gate": "fine analytical error < 0.5 * coarse analytical error",
        "passed": bool(passed),
    }


def density_contrast() -> dict[str, Any]:
    radius = 0.006
    rho_out = 1.204
    rho_in = 0.60
    g = (0.0, -9.81, 0.0)
    front = _front(radius_m=radius, subdivisions=1, surface_tension_n_m=0.0)
    initial_center = front.centroid()
    config = _config(
        cells=10,
        gravity=g,
        region_properties={
            front.bubble_id: RegionProperties(
                density_kg_m3=rho_in,
                dynamic_viscosity_pa_s=1.2e-5,
            )
        },
    )
    solver = TransientSoapFilmSolver([front], config)
    solver.step(2.0e-5)
    velocity = solver.bubble_velocity(front.bubble_id)
    displacement = solver.fronts[0].centroid()[1] - initial_center[1]

    physical = solver.grid.physical_pressure_field()
    exterior = []
    for q, label in enumerate(solver.grid.region_labels):
        if label == "EXTERIOR":
            _, y, _ = solver.grid.cell_center(*solver.grid._ijk(q))
            hydrostatic_component = physical[q] - solver.grid.pressure[q]
            exterior.append((y, hydrostatic_component))
    exterior.sort()
    low_y, low_p = exterior[0]
    high_y, high_p = exterior[-1]
    hydrostatic_gradient = (high_p - low_p) / (high_y - low_y)
    expected_gradient = rho_out * g[1]
    hydrostatic_relative_error = abs(hydrostatic_gradient - expected_gradient) / abs(expected_gradient)

    metrics = {
        "bubble_vertical_velocity_m_s": velocity[1],
        "bubble_vertical_displacement_m": displacement,
        "minimum_density_kg_m3": min(solver.grid.density),
        "maximum_density_kg_m3": max(solver.grid.density),
        "hydrostatic_gradient_pa_m": hydrostatic_gradient,
        "expected_exterior_hydrostatic_gradient_pa_m": expected_gradient,
        "hydrostatic_gradient_relative_error": hydrostatic_relative_error,
        "divergence_linf_s_inv": solver.grid.divergence_linf(),
    }
    gates = {
        "buoyant_direction": "positive y for rho_inside < rho_outside with gravity in -y",
        "density_absolute_tolerance_kg_m3": 1.0e-12,
        "hydrostatic_gradient_relative_error": 1.0e-10,
        "divergence_linf_s_inv": 2.0e-7,
    }
    passed = (
        velocity[1] > 0.0
        and displacement > 0.0
        and abs(metrics["minimum_density_kg_m3"] - rho_in) <= 1.0e-12
        and abs(metrics["maximum_density_kg_m3"] - rho_out) <= 1.0e-12
        and hydrostatic_relative_error <= gates["hydrostatic_gradient_relative_error"]
        and metrics["divergence_linf_s_inv"] <= gates["divergence_linf_s_inv"]
    )
    return {
        "benchmark": "density-contrast",
        "claim_level": "SHARP_CI_PHYSICS_CHECK",
        "matrix_mapping": ["R10", "R11", "R18", "R32"],
        "qualification": (
            "Periodic reference-box buoyancy check using exterior-density hydrostatic "
            "pressure splitting; this is not a terminal-rise or nonperiodic far-field benchmark."
        ),
        "metrics": metrics,
        "gates": gates,
        "passed": bool(passed),
    }


def zero_g_symmetry() -> dict[str, Any]:
    front = _front()
    initial = front.centroid()
    solver = TransientSoapFilmSolver([front], _config())
    solver.step()
    radius = front.equivalent_radius()
    drift = norm(sub(solver.fronts[0].centroid(), initial)) / radius
    return {
        "benchmark": "zero-g-symmetry",
        "claim_level": "SHARP_CI_SMOKE",
        "matrix_mapping": ["B08"],
        "metrics": {"centroid_over_r": drift},
        "gates": {"centroid_over_r": 2.0e-6},
        "passed": drift <= 2.0e-6,
    }


def _stable_jsonable_signature(signature) -> bytes:
    return json.dumps(signature, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def replay() -> dict[str, Any]:
    def run():
        solver = TransientSoapFilmSolver([_front()], _config())
        for _ in range(2):
            solver.step()
        payload = _stable_jsonable_signature(solver.replay_signature())
        return hashlib.sha256(payload).hexdigest(), solver

    hash_a, a = run()
    hash_b, b = run()
    metrics = {
        "hash_equal": hash_a == hash_b,
        "history_length_equal": len(a.history) == len(b.history),
        "step_count": a.step_index,
    }
    passed = bool(metrics["hash_equal"] and metrics["history_length_equal"])
    return {
        "benchmark": "replay",
        "claim_level": "SHARP_CI_REPLAY",
        "matrix_mapping": ["B11"],
        "qualification": "Exact same-build deterministic replay including region labels and sharp-jump targets.",
        "metrics": metrics,
        "hashes": [hash_a, hash_b],
        "passed": passed,
    }



def _amr_config(max_levels: int = 1, front_band_cells: float = 0.90) -> AMRConfig:
    return AMRConfig(
        enabled=True,
        max_levels=max_levels,
        refinement_ratio=2,
        front_band_cells=front_band_cells,
        min_patch_parent_cells=2,
        boundary_fill_cells=1,
    )


def _amr_solver(
    cells: int = 6,
    subdivisions: int = 2,
    max_levels: int = 1,
) -> TransientSoapFilmSolver:
    front = _front(subdivisions=subdivisions)
    base = _config(cells)
    config = TransientConfig(
        grid=base.grid,
        amr=_amr_config(max_levels=max_levels),
        gravity_m_s2=base.gravity_m_s2,
        timestep=base.timestep,
        deterministic_seed=base.deterministic_seed,
        region_properties=base.region_properties,
        sharp_pressure_jump=True,
    )
    return TransientSoapFilmSolver([front], config)


def _composite_momentum_proxy(grid: AdaptiveEulerianGasGrid) -> tuple[float, float, float]:
    total = [0.0, 0.0, 0.0]
    for level_index, level in enumerate(grid.levels):
        g = level.grid
        for q in grid._active_indices(level_index):
            scale = g.density[q] * g.cell_volume
            total[0] += scale * g.u[q]
            total[1] += scale * g.v[q]
            total[2] += scale * g.w[q]
    return (total[0], total[1], total[2])


def amr_topology() -> dict[str, Any]:
    solver = _amr_solver(cells=8, subdivisions=1, max_levels=2)
    grid = solver.grid
    assert isinstance(grid, AdaptiveEulerianGasGrid)
    twin = _amr_solver(cells=8, subdivisions=1, max_levels=2)
    twin_grid = twin.grid
    assert isinstance(twin_grid, AdaptiveEulerianGasGrid)

    layout_equal = grid.hierarchy_signature() == twin_grid.hierarchy_signature()
    counts = grid.active_cell_counts_by_level()
    coarse_active = counts.get("0", 0)
    fine_active = counts.get(str(len(grid.levels) - 1), 0)

    base = grid.base
    constants = (0.125, -0.25, 0.5)
    base.u = [constants[0]] * len(base.u)
    base.v = [constants[1]] * len(base.v)
    base.w = [constants[2]] * len(base.w)
    grid.prolong_all()
    momentum_before = _composite_momentum_proxy(grid)
    max_constant_error_before = max(
        max(
            max((abs(value - constants[axis]) for value in field), default=0.0)
            for axis, field in enumerate((level.grid.u, level.grid.v, level.grid.w))
        )
        for level in grid.levels
    )
    grid.restrict_all()
    grid.prolong_all()
    momentum_after = _composite_momentum_proxy(grid)
    max_constant_error_after = max(
        max(
            max((abs(value - constants[axis]) for value in field), default=0.0)
            for axis, field in enumerate((level.grid.u, level.grid.v, level.grid.w))
        )
        for level in grid.levels
    )
    momentum_scale = max(
        max(abs(x) for x in momentum_before),
        1.0e-30,
    )
    momentum_relative = max(
        abs(a - b) for a, b in zip(momentum_before, momentum_after)
    ) / momentum_scale

    metrics = {
        "layout_equal": layout_equal,
        "levels": len(grid.levels),
        "active_cells_by_level": counts,
        "active_cell_count": grid.active_cell_count(),
        "base_cell_size_m": grid.base.h,
        "finest_cell_size_m": grid.finest.h,
        "coarse_far_field_active_cells": coarse_active,
        "finest_active_cells": fine_active,
        "max_constant_transfer_error": max(
            max_constant_error_before, max_constant_error_after
        ),
        "momentum_proxy_relative_roundtrip_error": momentum_relative,
    }
    gates = {
        "minimum_levels": 2,
        "max_constant_transfer_error": 1.0e-14,
        "momentum_proxy_relative_roundtrip_error": 1.0e-13,
        "requires_coarse_far_field": True,
        "requires_fine_active_cells": True,
        "requires_deterministic_layout": True,
    }
    passed = (
        layout_equal
        and len(grid.levels) >= gates["minimum_levels"]
        and coarse_active > 0
        and fine_active > 0
        and grid.finest.h < grid.base.h
        and metrics["max_constant_transfer_error"] <= gates["max_constant_transfer_error"]
        and momentum_relative <= gates["momentum_proxy_relative_roundtrip_error"]
    )
    return {
        "benchmark": "amr-topology",
        "claim_level": "AMR_CI_FOUNDATION",
        "matrix_mapping": ["R20", "R21", "R31", "R32", "R34", "R35"],
        "qualification": (
            "Deterministic nested Cartesian hierarchy selected by tracked-triangle "
            "distance. Constant velocity and constant-density momentum proxy are "
            "checked across explicit prolongation/restriction."
        ),
        "metrics": metrics,
        "gates": gates,
        "hierarchy": grid.hierarchy_signature(),
        "passed": bool(passed),
    }


def _uniform_region_volume(solver: TransientSoapFilmSolver, bubble_id: str) -> float:
    return sum(
        solver.grid.cell_volume
        for label in solver.grid.region_labels
        if label == bubble_id
    )


def _static_metrics(solver: TransientSoapFilmSolver) -> dict[str, float]:
    front0 = solver.fronts[0].clone()
    initial_area = front0.area()
    initial_volume = front0.volume()
    initial_center = front0.centroid()
    radius = front0.equivalent_radius()
    diag = solver.step()
    front = solver.fronts[0]
    analytical = 2.0 * front.surface_tension_n_m / radius
    measured = solver.pressure_jump_pa(front.bubble_id)
    capillary_speed = math.sqrt(
        front.surface_tension_n_m / (solver.config.grid.density_kg_m3 * radius)
    )
    if isinstance(solver.grid, AdaptiveEulerianGasGrid):
        represented = solver.grid.region_volume(front.bubble_id)
        active_cells = solver.grid.active_cell_count()
        cell_size = solver.grid.finest.h
    else:
        represented = _uniform_region_volume(solver, front.bubble_id)
        active_cells = len(solver.grid.u)
        cell_size = solver.grid.h
    return {
        "active_cell_count": float(active_cells),
        "finest_eta_b": cell_size / radius,
        "interface_localization_bound_over_r": 0.5 * math.sqrt(3.0) * cell_size / radius,
        "region_volume_relative_error": abs(represented - initial_volume) / initial_volume,
        "volume_drift_relative": abs(front.volume() - initial_volume) / initial_volume,
        "area_drift_relative": abs(front.area() - initial_area) / initial_area,
        "centroid_over_r": norm(sub(front.centroid(), initial_center)) / radius,
        "spurious_speed_over_capillary": diag.max_speed_m_s / capillary_speed,
        "pressure_jump_relative_error": abs(measured - analytical) / analytical,
        "divergence_linf_s_inv": diag.divergence_linf_s_inv,
    }


def amr_static_sphere() -> dict[str, Any]:
    amr_solver = _amr_solver(cells=8, subdivisions=2, max_levels=1)
    amr_grid = amr_solver.grid
    assert isinstance(amr_grid, AdaptiveEulerianGasGrid)
    amr_metrics = _static_metrics(amr_solver)

    peer_cells = max(4, int(amr_grid.active_cell_count() ** (1.0 / 3.0)))
    uniform_solver = TransientSoapFilmSolver(
        [_front(subdivisions=2)],
        _config(peer_cells),
    )
    uniform_metrics = _static_metrics(uniform_solver)

    primary_keys = (
        "volume_drift_relative",
        "area_drift_relative",
        "centroid_over_r",
        "spurious_speed_over_capillary",
        "pressure_jump_relative_error",
    )
    primary_no_worse = all(
        amr_metrics[key] <= max(uniform_metrics[key] * 1.05, 1.0e-12)
        for key in primary_keys
    )
    localization_better = (
        amr_metrics["interface_localization_bound_over_r"]
        < uniform_metrics["interface_localization_bound_over_r"]
    )
    gates = {
        "primary_metric_peer_factor": 1.05,
        "max_divergence_linf_s_inv": 2.0e-6,
        "requires_better_interface_localization_bound": True,
        "budget_rule": "uniform peer uses floor(cuberoot(AMR active-cell count)) cells per axis",
    }
    passed = (
        primary_no_worse
        and localization_better
        and amr_metrics["divergence_linf_s_inv"] <= gates["max_divergence_linf_s_inv"]
    )
    return {
        "benchmark": "amr-static-sphere",
        "claim_level": "AMR_CI_FOUNDATION",
        "matrix_mapping": ["B02", "B03", "B07", "B12", "R20", "R32"],
        "qualification": (
            "Static sharp-interface AMR check against a uniform grid with no more "
            "than the AMR active-cell budget. The CI resolution is reported exactly "
            "and is not labeled final B12 unless eta_b reaches the B12 gate."
        ),
        "amr": amr_metrics,
        "uniform_budget_peer": uniform_metrics,
        "amr_hierarchy": amr_grid.diagnostics(),
        "b12_final_qualified": bool(amr_metrics["finest_eta_b"] <= 0.02),
        "gates": gates,
        "passed": bool(passed),
    }


def _amr_pressure_level(subdivisions: int, max_levels: int) -> dict[str, float]:
    solver = _amr_solver(cells=8, subdivisions=subdivisions, max_levels=max_levels)
    grid = solver.grid
    assert isinstance(grid, AdaptiveEulerianGasGrid)
    front = solver.fronts[0]
    radius = front.equivalent_radius()
    analytical = 2.0 * front.surface_tension_n_m / radius
    solver.step()
    measured = solver.pressure_jump_pa(front.bubble_id)
    discrete = solver.target_pressure_jump_pa(front.bubble_id)
    return {
        "surface_subdivisions": float(subdivisions),
        "max_refinement_level": float(len(grid.levels) - 1),
        "active_cell_count": float(grid.active_cell_count()),
        "finest_eta_b": grid.finest.h / radius,
        "analytical_pressure_jump_pa": analytical,
        "discrete_pressure_jump_pa": discrete,
        "measured_pressure_jump_pa": measured,
        "analytical_relative_error": abs(measured - analytical) / analytical,
        "discrete_relative_error": abs(measured - discrete) / analytical,
    }


def amr_pressure_jump() -> dict[str, Any]:
    levels = [
        _amr_pressure_level(1, 1),
        _amr_pressure_level(2, 1),
        _amr_pressure_level(3, 2),
    ]
    analytical = [level["analytical_relative_error"] for level in levels]
    discrete = [level["discrete_relative_error"] for level in levels]
    trend = analytical[1] < analytical[0] and analytical[2] < analytical[1]
    gates = {
        "max_discrete_relative_error": 5.0e-5,
        "finest_analytical_relative_error": 5.0e-3,
        "requires_strict_analytical_convergence": True,
    }
    passed = (
        max(discrete) <= gates["max_discrete_relative_error"]
        and analytical[-1] <= gates["finest_analytical_relative_error"]
        and trend
    )
    return {
        "benchmark": "amr-pressure-jump",
        "claim_level": "AMR_CI_CONVERGENCE",
        "matrix_mapping": ["B02", "B09", "B12", "R6", "R32"],
        "qualification": (
            "Three AMR/refinement settings report active-cell budget and effective "
            "finest eta_b. Young-Laplace analytical convergence is enforced while "
            "the jump-balanced discrete residual remains bounded."
        ),
        "levels": levels,
        "gates": gates,
        "passed": bool(passed),
    }


def amr_replay() -> dict[str, Any]:
    def run():
        solver = _amr_solver(cells=8, subdivisions=1, max_levels=2)
        for _ in range(2):
            solver.step()
        grid = solver.grid
        assert isinstance(grid, AdaptiveEulerianGasGrid)
        payload = _stable_jsonable_signature(solver.replay_signature())
        return hashlib.sha256(payload).hexdigest(), grid.hierarchy_signature(), solver

    hash_a, hierarchy_a, a = run()
    hash_b, hierarchy_b, b = run()
    metrics = {
        "hash_equal": hash_a == hash_b,
        "hierarchy_equal": hierarchy_a == hierarchy_b,
        "history_length_equal": len(a.history) == len(b.history),
        "step_count": a.step_index,
    }
    return {
        "benchmark": "amr-replay",
        "claim_level": "AMR_CI_REPLAY",
        "matrix_mapping": ["B11", "R31"],
        "qualification": "Exact same-build replay includes AMR hierarchy and per-level grid state.",
        "metrics": metrics,
        "hashes": [hash_a, hash_b],
        "hierarchy": hierarchy_a,
        "passed": bool(
            metrics["hash_equal"]
            and metrics["hierarchy_equal"]
            and metrics["history_length_equal"]
        ),
    }



def _poor_remesh_sphere() -> tuple[FilmFront, float]:
    front = _front(subdivisions=1)
    target = front.mean_edge_length()
    remesher = FrontRemesher(
        RemeshConfig(
            mode="interval",
            target_edge_length_m=target,
            max_geometry_relative_error=1.0e-12,
        )
    )
    edge = tuple(sorted(front.faces[0][:2]))
    if not remesher.split_edge(front, edge, fraction=0.08):
        raise RuntimeError("failed to create deterministic poor-quality sphere")
    return front, target


def _remesh_cube(size: float = 0.006) -> FilmFront:
    s = size
    vertices = [
        (-s, -s, -s),
        (s, -s, -s),
        (s, s, -s),
        (-s, s, -s),
        (-s, -s, s),
        (s, -s, s),
        (s, s, s),
        (-s, s, s),
        (0.20 * s, 0.0, -s),
    ]
    faces = [
        (0, 1, 8), (1, 2, 8), (2, 3, 8), (3, 0, 8),
        (4, 7, 6), (4, 6, 5),
        (0, 4, 5), (0, 5, 1),
        (1, 5, 6), (1, 6, 2),
        (2, 6, 7), (2, 7, 3),
        (3, 7, 4), (3, 4, 0),
    ]
    return FilmFront(
        bubble_id="remesh-cube",
        mesh_id="mesh-remesh-cube",
        film_id="film-remesh-cube",
        vertices=vertices,
        faces=faces,
        surface_tension_n_m=0.05,
    )


def remesh_quality() -> dict[str, Any]:
    front, target = _poor_remesh_sphere()
    before = mesh_quality(front)
    identity = (front.bubble_id, front.mesh_id, front.film_id)
    remesher = FrontRemesher(
        RemeshConfig(
            mode="quality",
            target_edge_length_m=target,
            min_edge_factor=0.45,
            max_edge_factor=1.80,
            min_angle_deg=25.0,
            max_aspect_ratio=3.0,
            max_geometry_relative_error=1.0e-12,
        )
    )
    report = remesher.remesh(front)
    after = mesh_quality(front)
    gates = {
        "minimum_angle_deg": 25.0,
        "maximum_aspect_ratio": 3.0,
        "maximum_volume_relative_change": 1.0e-12,
        "requires_quality_improvement": True,
        "requires_closed_positive_volume": True,
        "requires_region_identity": True,
    }
    metrics = {
        "min_angle_before_deg": before.min_angle_deg,
        "min_angle_after_deg": after.min_angle_deg,
        "max_aspect_before": before.max_aspect_ratio,
        "max_aspect_after": after.max_aspect_ratio,
        "volume_relative_change": report.volume_relative_change,
        "operation_count": report.operation_count,
        "operations": report.operations,
        "positive_signed_volume": front.signed_volume() > 0.0,
        "region_identity_preserved": identity == (front.bubble_id, front.mesh_id, front.film_id),
    }
    passed = (
        after.min_angle_deg >= gates["minimum_angle_deg"]
        and after.max_aspect_ratio <= gates["maximum_aspect_ratio"]
        and after.min_angle_deg > before.min_angle_deg
        and after.max_aspect_ratio < before.max_aspect_ratio
        and report.volume_relative_change <= gates["maximum_volume_relative_change"]
        and report.operation_count > 0
        and metrics["positive_signed_volume"]
        and metrics["region_identity_preserved"]
    )
    return {
        "benchmark": "remesh-quality",
        "claim_level": "FRONT_REMESH_CI",
        "matrix_mapping": ["R7", "R20", "R21", "R32", "R35"],
        "qualification": (
            "A deterministic poor-quality closed sphere is repaired without a "
            "physical topology event or hidden volume projection."
        ),
        "metrics": metrics,
        "gates": gates,
        "passed": bool(passed),
    }


def remesh_conservation() -> dict[str, Any]:
    front = _remesh_cube()
    initial_volume = front.volume()
    initial_area = front.area()
    initial_centroid = front.centroid()
    identity = (front.bubble_id, front.mesh_id, front.film_id)
    field = ConservativeArealField.from_density(
        front,
        "generic_areal_mass",
        lambda index, centroid: 1.0 + 0.02 * index + 0.1 * centroid[0] / 0.006,
    )
    initial_amount = field.total_amount()
    fields = {field.name: field}
    remesher = FrontRemesher(
        RemeshConfig(
            mode="interval",
            target_edge_length_m=front.mean_edge_length(),
            smoothing_relaxation=0.5,
            max_geometry_relative_error=1.0e-12,
        )
    )

    split_edge = (0, 5)
    split_ok = remesher.split_edge(front, split_edge, fields)
    split_vertex = len(front.vertices) - 1
    collapse_ok = split_ok and remesher.collapse_edge(front, (0, split_vertex), fields)
    flip_ok = collapse_ok and remesher.flip_edge(front, (4, 6), fields, require_improvement=False)
    smooth_ok = flip_ok and remesher.smooth_vertex(
        front,
        8,
        fields,
        relaxation=0.5,
        require_improvement=True,
    )

    amount_error = abs(field.total_amount() - initial_amount) / max(abs(initial_amount), 1.0e-300)
    volume_error = abs(front.volume() - initial_volume) / initial_volume
    area_error = abs(front.area() - initial_area) / initial_area
    centroid_error = norm(sub(front.centroid(), initial_centroid)) / 0.006
    identity_ok = identity == (front.bubble_id, front.mesh_id, front.film_id)
    operations = {
        "split": bool(split_ok),
        "collapse": bool(collapse_ok),
        "flip": bool(flip_ok),
        "smooth": bool(smooth_ok),
    }
    gates = {
        "surface_field_relative_error": 1.0e-10,
        "volume_relative_error": 1.0e-12,
        "area_relative_error": 1.0e-12,
        "centroid_over_size": 1.0e-12,
        "requires_all_four_operations": True,
        "requires_region_identity": True,
    }
    passed = (
        all(operations.values())
        and amount_error <= gates["surface_field_relative_error"]
        and volume_error <= gates["volume_relative_error"]
        and area_error <= gates["area_relative_error"]
        and centroid_error <= gates["centroid_over_size"]
        and identity_ok
        and front.signed_volume() > 0.0
    )
    return {
        "benchmark": "remesh-conservation",
        "claim_level": "B14_TRANSFER_INFRASTRUCTURE",
        "matrix_mapping": ["B14", "R14", "R21", "R22", "R32"],
        "qualification": (
            "Generic face-integrated areal mass is conservatively transferred "
            "through split/collapse/flip/tangential-smoothing. This is field-transfer "
            "infrastructure only, not film drainage or surfactant transport physics."
        ),
        "metrics": {
            "operations": operations,
            "surface_field_relative_error": amount_error,
            "volume_relative_error_pre_projection": volume_error,
            "area_relative_error": area_error,
            "centroid_over_size": centroid_error,
            "region_identity_preserved": identity_ok,
            "vertex_count": len(front.vertices),
            "face_count": len(front.faces),
        },
        "gates": gates,
        "passed": bool(passed),
    }


def remesh_replay() -> dict[str, Any]:
    def run() -> tuple[str, tuple, FilmFront, ConservativeArealField]:
        front, target = _poor_remesh_sphere()
        field = ConservativeArealField.from_density(
            front,
            "generic_areal_mass",
            lambda index, centroid: 1.0 + 0.01 * index + centroid[0],
        )
        remesher = FrontRemesher(
            RemeshConfig(
                mode="quality",
                target_edge_length_m=target,
                min_angle_deg=25.0,
                max_aspect_ratio=3.0,
                max_geometry_relative_error=1.0e-12,
            )
        )
        report = remesher.remesh(front, {field.name: field})
        signature = (
            tuple(tuple(float(value) for value in vertex) for vertex in front.vertices),
            tuple(front.faces),
            tuple(field.face_amounts),
            report.signature(),
        )
        return hashlib.sha256(_stable_jsonable_signature(signature)).hexdigest(), signature, front, field

    hash_a, signature_a, front_a, field_a = run()
    hash_b, signature_b, front_b, field_b = run()
    metrics = {
        "hash_equal": hash_a == hash_b,
        "connectivity_equal": front_a.faces == front_b.faces,
        "vertices_equal": front_a.vertices == front_b.vertices,
        "field_equal": field_a.face_amounts == field_b.face_amounts,
        "signature_equal": signature_a == signature_b,
    }
    return {
        "benchmark": "remesh-replay",
        "claim_level": "FRONT_REMESH_CI_REPLAY",
        "matrix_mapping": ["B11", "R31"],
        "qualification": (
            "Exact same-build deterministic replay covers connectivity ordering, "
            "vertex coordinates, conservative surface-field transfer, and operation log."
        ),
        "metrics": metrics,
        "hashes": [hash_a, hash_b],
        "passed": bool(all(metrics.values())),
    }


def static_sphere() -> dict[str, Any]:
    return sharp_static_sphere()


BENCHMARKS = {
    "static-sphere": static_sphere,
    "sharp-static-sphere": sharp_static_sphere,
    "pressure-jump": pressure_jump,
    "density-contrast": density_contrast,
    "zero-g-symmetry": zero_g_symmetry,
    "replay": replay,
    "amr-topology": amr_topology,
    "amr-static-sphere": amr_static_sphere,
    "amr-pressure-jump": amr_pressure_jump,
    "amr-replay": amr_replay,
    "remesh-quality": remesh_quality,
    "remesh-conservation": remesh_conservation,
    "remesh-replay": remesh_replay,
}
