"""Analytical sphere and refinement benchmarks for the equilibrium kernel."""
from __future__ import annotations

import math
from typing import Any

from .solver import SolverSettings, solve_prescribed_volume
from .sphere import icosphere, sphere_area, sphere_volume


def _relative(value: float, exact: float) -> float:
    return abs(value - exact) / abs(exact)


def sphere_case(subdivisions: int = 6, radius_m: float = 1.0e-2, sheet_tension_n_m: float = 0.05) -> dict[str, Any]:
    target_volume = sphere_volume(radius_m)
    exact_area = sphere_area(radius_m)
    exact_pressure = 2.0 * sheet_tension_n_m / radius_m
    raw = icosphere(subdivisions, radius_m)
    raw_quality = raw.quality()
    raw_area_error = _relative(raw.area(), exact_area)
    raw_volume_error = _relative(raw.signed_volume(), target_volume)
    result = solve_prescribed_volume(
        raw,
        target_volume,
        sheet_tension_n_m,
        SolverSettings(max_iterations=40, normalized_force_tolerance=1.0e-3),
    )
    final = result.mesh
    final_quality = final.quality()
    centroid = final.centroid()
    radii = [math.dist(vertex, centroid) for vertex in final.vertices]
    radial_rms = math.sqrt(sum((value - radius_m) ** 2 for value in radii) / len(radii)) / radius_m
    pressure_error = _relative(result.pressure_jump_pa, exact_pressure)
    repeat = solve_prescribed_volume(
        raw,
        target_volume,
        sheet_tension_n_m,
        SolverSettings(max_iterations=40, normalized_force_tolerance=1.0e-3),
    )
    repeatable = (
        result.pressure_jump_pa == repeat.pressure_jump_pa
        and result.relative_volume_error == repeat.relative_volume_error
        and result.normalized_force_residual == repeat.normalized_force_residual
        and result.mesh.vertices == repeat.mesh.vertices
    )
    return {
        "benchmark": "B01+B02+B03A+B11 sphere",
        "subdivisions": subdivisions,
        "radius_m": radius_m,
        "sheet_tension_n_m": sheet_tension_n_m,
        "eta_s_raw": float(raw_quality["median_edge_length_m"]) / radius_m,
        "eta_s_final": float(final_quality["median_edge_length_m"]) / radius_m,
        "raw_area_relative_error": raw_area_error,
        "raw_volume_relative_error": raw_volume_error,
        "final_area_relative_error": _relative(final.area(), exact_area),
        "final_volume_relative_error": result.relative_volume_error,
        "radial_rms_relative_error": radial_rms,
        "pressure_jump_pa": result.pressure_jump_pa,
        "exact_pressure_jump_pa": exact_pressure,
        "young_laplace_relative_error": pressure_error,
        "normalized_force_residual": result.normalized_force_residual,
        "iterations": result.iterations,
        "converged": result.converged,
        "termination_reason": result.termination_reason,
        "deterministic_repeat": repeatable,
        "mesh_quality": final_quality,
    }


def _observed_orders(rows: list[dict[str, float]], key: str) -> list[float]:
    orders = []
    for coarse, fine in zip(rows, rows[1:]):
        h1, h2 = coarse["eta_s"], fine["eta_s"]
        e1, e2 = coarse[key], fine[key]
        orders.append(math.log(e1 / e2) / math.log(h1 / h2))
    return orders


def sphere_convergence(levels: tuple[int, ...] = (3, 4, 5), radius_m: float = 1.0e-2, sheet_tension_n_m: float = 0.05) -> dict[str, Any]:
    target_volume = sphere_volume(radius_m)
    exact_area = sphere_area(radius_m)
    exact_pressure = 2.0 * sheet_tension_n_m / radius_m
    rows: list[dict[str, float]] = []
    for level in levels:
        raw = icosphere(level, radius_m)
        result = solve_prescribed_volume(raw, target_volume, sheet_tension_n_m)
        rows.append({
            "level": float(level),
            "eta_s": float(raw.quality()["median_edge_length_m"]) / radius_m,
            "raw_area_error": _relative(raw.area(), exact_area),
            "raw_volume_error": _relative(raw.signed_volume(), target_volume),
            "pressure_error": _relative(result.pressure_jump_pa, exact_pressure),
            "force_residual": result.normalized_force_residual,
        })
    area_orders = _observed_orders(rows, "raw_area_error")
    volume_orders = _observed_orders(rows, "raw_volume_error")
    pressure_orders = _observed_orders(rows, "pressure_error")
    return {
        "benchmark": "B09 sphere-convergence",
        "levels": list(levels),
        "rows": rows,
        "observed_order": {
            "area": area_orders,
            "volume": volume_orders,
            "pressure": pressure_orders,
        },
        "minimum_observed_order": {
            "area": min(area_orders),
            "volume": min(volume_orders),
            "pressure": min(pressure_orders),
        },
    }


def assert_sphere(metrics: dict[str, Any]) -> None:
    failures = []
    if metrics["eta_s_raw"] > 0.03:
        failures.append(f"eta_s={metrics['eta_s_raw']:.6g} exceeds B01/B02 fine limit 0.03")
    if metrics["raw_area_relative_error"] > 2.0e-3:
        failures.append("raw area error exceeds B01 2e-3")
    if metrics["raw_volume_relative_error"] > 2.0e-3:
        failures.append("raw volume error exceeds B01 2e-3")
    if metrics["final_volume_relative_error"] > 1.0e-8:
        failures.append("constrained volume error exceeds B03A 1e-8")
    if metrics["young_laplace_relative_error"] > 5.0e-3:
        failures.append("pressure error exceeds B02 5e-3")
    if metrics["normalized_force_residual"] > 1.0e-2:
        failures.append("energy-consistent force residual exceeds B02 1e-2")
    if not metrics["converged"]:
        failures.append("solver did not satisfy its declared stopping gates")
    if not metrics["deterministic_repeat"]:
        failures.append("same-build deterministic replay differs")
    if failures:
        raise AssertionError("; ".join(failures))


def assert_convergence(metrics: dict[str, Any]) -> None:
    minimum = metrics["minimum_observed_order"]
    failures = []
    if minimum["area"] < 1.7:
        failures.append(f"area order {minimum['area']:.3f} < B09 gate 1.7")
    if minimum["volume"] < 1.7:
        failures.append(f"volume order {minimum['volume']:.3f} < B09 gate 1.7")
    if minimum["pressure"] < 1.3:
        failures.append(f"pressure order {minimum['pressure']:.3f} < B09 gate 1.3")
    if failures:
        raise AssertionError("; ".join(failures))
