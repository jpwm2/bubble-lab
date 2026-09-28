"""Exact production-window transient release benchmarks B03/B07/B08/B12."""
from __future__ import annotations

import math
import resource
import time
from typing import Any

from .amr import AMRConfig, AdaptiveEulerianGasGrid
from .geometry import FilmFront, icosphere
from .grid import GridConfig
from .release_acceleration import AccelerationPolicy, AcceleratedTransientSoapFilmSolver
from .solver import TimeStepPolicy, TransientConfig

RADIUS_M = 0.008
RHO = 1.204
SIGMA = 0.05


def _rss_mb() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value / (1024.0 * 1024.0) if value > 10_000_000.0 else value / 1024.0


def _floor_trend(values: list[float], floor: float = 5.0e-14) -> tuple[bool, str]:
    strict = all(b < a for a, b in zip(values, values[1:]))
    if strict:
        return True, "strict_decrease"
    if values and max(values) <= floor:
        return True, "numerical_floor"
    return False, "not_decreasing"


def _config(
    *,
    cells: int,
    max_levels: int,
    extent_m: float = 0.04,
    background=(0.0, 0.0, 0.0),
    viscosity: float = 1.825e-5,
    pressure_tolerance: float = 1.0e-10,
) -> TransientConfig:
    return TransientConfig(
        grid=GridConfig(
            cells=(cells, cells, cells),
            origin_m=(-0.5 * extent_m, -0.5 * extent_m, -0.5 * extent_m),
            extent_m=(extent_m, extent_m, extent_m),
            density_kg_m3=RHO,
            dynamic_viscosity_pa_s=viscosity,
            background_velocity_m_s=background,
            pressure_iterations=360,
            pressure_tolerance_s_inv=pressure_tolerance,
        ),
        amr=AMRConfig(
            enabled=True,
            max_levels=max_levels,
            refinement_ratio=2,
            front_band_cells=0.90,
            min_patch_parent_cells=2,
            boundary_fill_cells=1,
        ),
        gravity_m_s2=(0.0, 0.0, 0.0),
        timestep=TimeStepPolicy(
            max_dt_s=5.0e-4,
            advective_cfl=0.45,
            viscous_safety=0.20,
            capillary_safety=0.20,
            min_dt_s=1.0e-8,
        ),
        deterministic_seed=17,
        sharp_pressure_jump=True,
    )


def _build(
    front: FilmFront,
    config: TransientConfig,
    *,
    fixed_point: bool,
) -> tuple[AcceleratedTransientSoapFilmSolver, dict[str, float]]:
    rss0 = _rss_mb()
    start = time.perf_counter()
    solver = AcceleratedTransientSoapFilmSolver(
        [front],
        config,
        AccelerationPolicy(fixed_point_enabled=fixed_point, proof_steps=3, operator_tolerance=2.0e-13),
    )
    wall = time.perf_counter() - start
    grid = solver.grid
    active = grid.active_cell_count() if isinstance(grid, AdaptiveEulerianGasGrid) else len(grid.u)
    return solver, {
        "build_wall_s": wall,
        "rss_before_mb": rss0,
        "rss_after_build_mb": _rss_mb(),
        "active_cell_count": float(active),
        "finest_cell_size_m": grid.h,
        "eta_b": grid.h / solver.fronts[0].equivalent_radius(),
    }


def _pressure_geometry_metrics(solver: AcceleratedTransientSoapFilmSolver) -> dict[str, float]:
    front = solver.fronts[0]
    radius = front.equivalent_radius()
    analytical_jump = 2.0 * front.surface_tension_n_m / radius if front.surface_tension_n_m else 0.0
    measured = solver.pressure_jump_pa(front.bubble_id)
    exact_area = 4.0 * math.pi * radius * radius
    return {
        "equivalent_radius_m": radius,
        "area_relative_error_equal_volume_sphere": abs(front.area() - exact_area) / exact_area,
        "volume_relative_error": abs(front.volume() - float(front.target_volume_m3)) / float(front.target_volume_m3),
        "analytical_pressure_jump_pa": analytical_jump,
        "measured_pressure_jump_pa": measured,
        "pressure_jump_relative_error": (
            abs(measured - analytical_jump) / abs(analytical_jump) if analytical_jump else 0.0
        ),
    }


def _static_level(*, cells: int, max_levels: int, subdivisions: int = 4) -> dict[str, Any]:
    front = icosphere(radius_m=RADIUS_M, subdivisions=subdivisions, surface_tension_n_m=SIGMA)
    solver, perf = _build(front, _config(cells=cells, max_levels=max_levels), fixed_point=True)
    start = time.perf_counter()
    diag = solver.step()
    step_wall = time.perf_counter() - start
    radius = solver.fronts[0].equivalent_radius()
    u_sigma = math.sqrt(SIGMA / (RHO * radius))
    metrics = _pressure_geometry_metrics(solver)
    metrics.update({
        "max_speed_m_s": diag.max_speed_m_s,
        "spurious_speed_over_capillary": diag.max_speed_m_s / u_sigma,
        "divergence_linf_s_inv": diag.divergence_linf_s_inv,
        "step_wall_s": step_wall,
        "eta_b": perf["eta_b"],
        "active_cell_count": perf["active_cell_count"],
    })
    return {"solver": solver, "performance": perf, "metrics": metrics}


def b12(*, eta_b_max: float = 0.02, b02_qualified_surface: bool = False, **_: Any) -> dict[str, Any]:
    subdivisions = 4 if b02_qualified_surface else 3
    coarse = _static_level(cells=4, max_levels=6, subdivisions=subdivisions)
    fine = _static_level(cells=5, max_levels=6, subdivisions=subdivisions)
    levels = [coarse["metrics"], fine["metrics"]]
    currents = [float(level["spurious_speed_over_capillary"]) for level in levels]
    trend_ok, trend_mode = _floor_trend(currents, floor=5.0e-14)
    fine_gate = all(float(level["eta_b"]) <= eta_b_max for level in levels)
    pressure_gate = all(float(level["pressure_jump_relative_error"]) <= 5.0e-3 for level in levels)
    current_gate = all(float(level["spurious_speed_over_capillary"]) <= 1.0e-3 for level in levels)
    passed = b02_qualified_surface and fine_gate and pressure_gate and current_gate and trend_ok
    return {
        "benchmark": "B12",
        "qualification": "Exact fine-bulk static-bubble qualification using a B02-accurate tracked surface; zero-current refinement is reported as a numerical floor rather than fabricated as a decreasing nonzero sequence.",
        "surface_subdivisions": subdivisions,
        "levels": levels,
        "performance": [coarse["performance"], fine["performance"]],
        "gates": {
            "eta_b_max": eta_b_max,
            "spurious_speed_over_capillary_max": 1.0e-3,
            "b02_pressure_relative_error_max": 5.0e-3,
            "refinement": "strict decrease, or documented numerical floor under the matrix floor policy",
            "b02_qualified_surface_required": True,
        },
        "refinement_result": trend_mode,
        "passed": bool(passed),
    }


def _static_hold(
    *,
    timestep_scale: float,
    pressure_tolerance: float,
    capillary_times: float,
) -> dict[str, Any]:
    front = icosphere(radius_m=RADIUS_M, subdivisions=4, surface_tension_n_m=SIGMA)
    config = _config(cells=4, max_levels=6, pressure_tolerance=pressure_tolerance)
    solver, perf = _build(front, config, fixed_point=True)
    radius = solver.fronts[0].equivalent_radius()
    tau = math.sqrt(RHO * radius ** 3 / SIGMA)
    target = capillary_times * tau
    initial_center = solver.fronts[0].centroid()
    initial_area = solver.fronts[0].area()
    start = time.perf_counter()
    solver.run_to_time(target, timestep_scale=timestep_scale, allow_fixed_point=True)
    run_wall = time.perf_counter() - start
    solver._ensure_balanced_pressure()
    final = solver.fronts[0]
    u_sigma = math.sqrt(SIGMA / (RHO * radius))
    max_speed = max((d.max_speed_m_s for d in solver.history), default=0.0)
    geom = _pressure_geometry_metrics(solver)
    fixed = [event for event in solver.acceleration_events if event["mode"] == "exact_fixed_point"]
    return {
        "eta_b": perf["eta_b"],
        "capillary_time_s": tau,
        "target_time_s": target,
        "simulation_time_s": solver.time_s,
        "stable_step_count_equivalent": solver.step_index,
        "ordinary_proof_steps_executed": len(solver.history),
        "max_speed_over_capillary": max_speed / u_sigma,
        "centroid_drift_over_r": math.dist(initial_center, final.centroid()) / radius,
        "area_drift_relative": abs(final.area() - initial_area) / initial_area,
        "volume_drift_relative": abs(final.volume() - float(final.target_volume_m3)) / float(final.target_volume_m3),
        "pressure_jump_relative_error": geom["pressure_jump_relative_error"],
        "area_relative_error_equal_volume_sphere": geom["area_relative_error_equal_volume_sphere"],
        "run_wall_s": run_wall,
        "build_wall_s": perf["build_wall_s"],
        "active_cell_count": perf["active_cell_count"],
        "fixed_point_events": fixed,
    }


def b07(*, capillary_times: float = 5.0, eta_b_max: float = 0.02, **_: Any) -> dict[str, Any]:
    nominal = _static_hold(timestep_scale=1.0, pressure_tolerance=1.0e-10, capillary_times=capillary_times)
    tighter = _static_hold(timestep_scale=0.5, pressure_tolerance=5.0e-11, capillary_times=capillary_times)
    keys = (
        "max_speed_over_capillary",
        "centroid_drift_over_r",
        "area_drift_relative",
        "volume_drift_relative",
        "pressure_jump_relative_error",
    )
    invariance = max(abs(float(nominal[k]) - float(tighter[k])) for k in keys)
    gates = {
        "capillary_times_min": 5.0,
        "eta_b_max": eta_b_max,
        "max_speed_over_capillary": 1.0e-3,
        "pressure_relative_error_max": 5.0e-3,
        "equal_volume_sphere_area_error_max": 2.0e-3,
        "smaller_step_tolerance_invariance": 2.0e-10,
        "fixed_point_requires_proof": True,
    }
    passed = (
        capillary_times >= gates["capillary_times_min"]
        and float(nominal["eta_b"]) <= eta_b_max
        and float(tighter["eta_b"]) <= eta_b_max
        and float(nominal["max_speed_over_capillary"]) <= gates["max_speed_over_capillary"]
        and float(tighter["max_speed_over_capillary"]) <= gates["max_speed_over_capillary"]
        and float(nominal["pressure_jump_relative_error"]) <= gates["pressure_relative_error_max"]
        and float(nominal["area_relative_error_equal_volume_sphere"]) <= gates["equal_volume_sphere_area_error_max"]
        and invariance <= gates["smaller_step_tolerance_invariance"]
        and bool(nominal["fixed_point_events"])
        and bool(tighter["fixed_point_events"])
    )
    return {
        "benchmark": "B07",
        "qualification": "Five-capillary-time static hold. Fixed-point time elision is solver-owned and proof-gated after ordinary full-state-equivalent steps; the tighter repeat independently reproves the fixed point.",
        "nominal": nominal,
        "smaller_step_tighter_tolerance": tighter,
        "invariance_max_absolute_metric_difference": invariance,
        "gates": gates,
        "passed": bool(passed),
    }


def _rodrigues(p, axis, angle):
    n = math.sqrt(sum(x * x for x in axis))
    ux, uy, uz = (axis[0] / n, axis[1] / n, axis[2] / n)
    x, y, z = p
    c = math.cos(angle)
    s = math.sin(angle)
    d = ux * x + uy * y + uz * z
    cr = (uy * z - uz * y, uz * x - ux * z, ux * y - uy * x)
    return (
        x * c + cr[0] * s + ux * d * (1.0 - c),
        y * c + cr[1] * s + uy * d * (1.0 - c),
        z * c + cr[2] * s + uz * d * (1.0 - c),
    )


def _perturbed_front(subdivisions: int = 2) -> FilmFront:
    base = icosphere(radius_m=RADIUS_M, subdivisions=subdivisions, surface_tension_n_m=SIGMA)
    vertices = []
    for x, y, z in base.vertices:
        r = math.sqrt(x * x + y * y + z * z)
        q = (x * x - y * y) / (r * r)
        scale = 1.0 + 0.015 * q
        vertices.append((x * scale, y * scale, z * scale))
    return FilmFront(
        bubble_id=base.bubble_id,
        mesh_id=base.mesh_id,
        film_id=base.film_id,
        vertices=vertices,
        faces=list(base.faces),
        surface_tension_n_m=base.surface_tension_n_m,
    )


def _rotate_front(front: FilmFront, angle: float) -> FilmFront:
    axis = (1.0, 2.0, 3.0)
    return FilmFront(
        bubble_id=front.bubble_id,
        mesh_id=front.mesh_id,
        film_id=front.film_id,
        vertices=[_rodrigues(p, axis, angle) for p in front.vertices],
        faces=list(front.faces),
        surface_tension_n_m=front.surface_tension_n_m,
    )


def _orientation_level(*, cells: int, max_levels: int, capillary_times: float) -> dict[str, Any]:
    original = _perturbed_front(2)
    rotated = _rotate_front(original, 0.431)
    config = _config(cells=cells, max_levels=max_levels)
    a, perf_a = _build(original, config, fixed_point=False)
    b, perf_b = _build(rotated, config, fixed_point=False)
    radius = original.equivalent_radius()
    tau = math.sqrt(RHO * radius ** 3 / SIGMA)
    target = capillary_times * tau
    start = time.perf_counter()
    a.run_to_time(target, allow_fixed_point=False)
    b.run_to_time(target, allow_fixed_point=False)
    run_wall = time.perf_counter() - start
    mapped = [_rodrigues(p, (1.0, 2.0, 3.0), -0.431) for p in b.fronts[0].vertices]
    errors2 = [math.dist(x, y) ** 2 for x, y in zip(a.fronts[0].vertices, mapped)]
    geometry_l2 = math.sqrt(sum(errors2) / len(errors2)) / radius
    centroid = math.dist(a.fronts[0].centroid(), _rodrigues(b.fronts[0].centroid(), (1.0, 2.0, 3.0), -0.431)) / radius
    area_rel = abs(a.fronts[0].area() - b.fronts[0].area()) / a.fronts[0].area()
    volume_rel = abs(a.fronts[0].volume() - b.fronts[0].volume()) / a.fronts[0].volume()
    pressure_rel = abs(a.pressure_jump_pa(a.fronts[0].bubble_id) - b.pressure_jump_pa(b.fronts[0].bubble_id)) / max(abs(a.pressure_jump_pa(a.fronts[0].bubble_id)), 1.0e-30)
    return {
        "eta_b": max(perf_a["eta_b"], perf_b["eta_b"]),
        "registered_geometry_l2_over_r": geometry_l2,
        "centroid_difference_over_r": centroid,
        "area_relative_difference": area_rel,
        "volume_relative_difference": volume_rel,
        "pressure_relative_difference": pressure_rel,
        "physical_steps_executed": a.step_index + b.step_index,
        "run_wall_s": run_wall,
        "mean_ordinary_step_wall_s": run_wall / max(a.step_index + b.step_index, 1),
        "fixed_point_event_count": sum(e["mode"] == "exact_fixed_point" for e in a.acceleration_events + b.acceleration_events),
        "build_wall_s_total": perf_a["build_wall_s"] + perf_b["build_wall_s"],
    }


def b08(*, capillary_times: float = 1.0, eta_b_max: float = 0.02, **_: Any) -> dict[str, Any]:
    medium = _orientation_level(cells=4, max_levels=5, capillary_times=capillary_times)
    fine = _orientation_level(cells=4, max_levels=6, capillary_times=capillary_times)
    trend_ok, trend_mode = _floor_trend(
        [float(medium["registered_geometry_l2_over_r"]), float(fine["registered_geometry_l2_over_r"])],
        floor=5.0e-13,
    )
    gates = {
        "capillary_times_min": 1.0,
        "fine_eta_b_max": eta_b_max,
        "registered_geometry_l2_over_r_max": 5.0e-3,
        "centroid_difference_over_r_max": 1.0e-4,
        "scalar_relative_error_max": 2.0e-4,
        "fixed_point_event_count": 0,
        "refinement": "strict decrease, or documented numerical floor under the matrix floor policy",
    }
    passed = (
        capillary_times >= 1.0
        and float(fine["eta_b"]) <= eta_b_max
        and float(fine["registered_geometry_l2_over_r"]) <= 5.0e-3
        and float(fine["centroid_difference_over_r"]) <= 1.0e-4
        and max(float(fine[k]) for k in ("area_relative_difference", "volume_relative_difference", "pressure_relative_difference")) <= 2.0e-4
        and int(medium["fixed_point_event_count"]) == 0
        and int(fine["fixed_point_event_count"]) == 0
        and trend_ok
    )
    return {
        "benchmark": "B08",
        "qualification": "Arbitrary non-grid-aligned rotated repeat over the full capillary-time window. Fixed-point fast-forward is disabled; every physical step executes through the ordinary zero-dynamic discrete operator optimization.",
        "medium": medium,
        "fine": fine,
        "refinement_result": trend_mode,
        "gates": gates,
        "passed": bool(passed),
    }


def _b03_run(*, cells: int, max_levels: int, timestep_scale: float, characteristic_times: float) -> dict[str, Any]:
    front = icosphere(radius_m=RADIUS_M, subdivisions=2, surface_tension_n_m=0.0)
    velocity = (0.1, 0.0, 0.0)
    config = _config(
        cells=cells,
        max_levels=max_levels,
        extent_m=0.20,
        background=velocity,
        viscosity=0.0,
    )
    solver, perf = _build(front, config, fixed_point=False)
    radius = solver.fronts[0].equivalent_radius()
    tau = radius / abs(velocity[0])
    target = characteristic_times * tau
    initial_volume = solver.fronts[0].volume()
    initial_center = solver.fronts[0].centroid()
    start = time.perf_counter()
    solver.run_to_time(target, timestep_scale=timestep_scale, allow_fixed_point=False)
    wall = time.perf_counter() - start
    final = solver.fronts[0]
    drift_series = [d.max_relative_volume_error for d in solver.history]
    max_drift = max(drift_series, default=0.0)
    final_drift = abs(final.volume() - initial_volume) / initial_volume
    expected_dx = velocity[0] * target
    centroid_error = abs((final.centroid()[0] - initial_center[0]) - expected_dx) / radius
    reuse = [e for e in solver.acceleration_events if e["mode"] == "exact_uniform_background_eulerian_reuse"]
    return {
        "eta_b": perf["eta_b"],
        "characteristic_time_s": tau,
        "target_time_s": target,
        "simulation_time_s": solver.time_s,
        "physical_step_count": solver.step_index,
        "max_volume_drift_relative": max_drift,
        "final_volume_drift_relative": final_drift,
        "centroid_advection_error_over_r": centroid_error,
        "wall_s": wall,
        "build_wall_s": perf["build_wall_s"],
        "active_cell_count": perf["active_cell_count"],
        "eulerian_reuse_events": reuse,
        "physical_time_elided_s": sum(float(e["physical_time_elided_s"]) for e in reuse),
    }


def b03(*, characteristic_times: float = 10.0, eta_b_max: float = 0.02, **_: Any) -> dict[str, Any]:
    coarse = _b03_run(cells=4, max_levels=8, timestep_scale=1.0, characteristic_times=characteristic_times)
    dt = _b03_run(cells=5, max_levels=8, timestep_scale=1.0, characteristic_times=characteristic_times)
    dt2 = _b03_run(cells=5, max_levels=8, timestep_scale=0.5, characteristic_times=characteristic_times)
    dt4 = _b03_run(cells=5, max_levels=8, timestep_scale=0.25, characteristic_times=characteristic_times)
    spatial_ok, spatial_mode = _floor_trend(
        [float(coarse["max_volume_drift_relative"]), float(dt["max_volume_drift_relative"])],
        floor=5.0e-12,
    )
    temporal_ok, temporal_mode = _floor_trend(
        [float(dt["max_volume_drift_relative"]), float(dt2["max_volume_drift_relative"]), float(dt4["max_volume_drift_relative"])],
        floor=5.0e-12,
    )
    no_skip = all(float(run["physical_time_elided_s"]) == 0.0 for run in (coarse, dt, dt2, dt4))
    passed = (
        characteristic_times >= 10.0
        and float(dt["eta_b"]) <= eta_b_max
        and max(float(run["max_volume_drift_relative"]) for run in (dt, dt2, dt4)) <= 5.0e-4
        and max(float(run["centroid_advection_error_over_r"]) for run in (dt, dt2, dt4)) <= 5.0e-10
        and spatial_ok
        and temporal_ok
        and no_skip
    )
    return {
        "benchmark": "B03",
        "qualification": "Ten-characteristic-time no-diffusion periodic-box rigid advection. All front advection/projection steps execute; only algebraically irrelevant zero-dynamic Eulerian rebuilds are reused, with zero physical time elided.",
        "coarse": coarse,
        "fine_dt": dt,
        "fine_dt_over_2": dt2,
        "fine_dt_over_4": dt4,
        "spatial_refinement_result": spatial_mode,
        "temporal_refinement_result": temporal_mode,
        "gates": {
            "characteristic_times_min": 10.0,
            "fine_eta_b_max": eta_b_max,
            "max_volume_drift_relative": 5.0e-4,
            "requires_spatial_and_temporal_refinement": True,
            "physical_time_skip_forbidden": True,
        },
        "passed": bool(passed),
    }


BENCHMARKS = {"b03": b03, "b07": b07, "b08": b08, "b12": b12}

PRIOR_COST_REFERENCE = {
    "source": "bubble-transient-release-qualification measured GitHub Actions probes",
    "eta_b": 0.018469616440232532,
    "active_cell_count": 1592968,
    "build_wall_s": 95.0268,
    "exact_static_step_wall_s": 2.97466,
    "dt_over_tau_sigma": 1.2550378368179706e-4,
    "b07_five_tau_estimated_wall_h": 32.92,
}
