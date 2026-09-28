"""B04/B05 validation cases for the coupled equilibrium film network."""
from __future__ import annotations

import math
import statistics
from typing import Any

from .mesh import SurfaceMesh
from .network import FilmPatch, NetworkEquilibriumResult, NetworkSolverSettings, solve_film_network
from .shared_geometry import perturb_shared_film, reference_two_bubble_network

_TENSION = 0.05
_CONTACT_RADIUS_M = 0.006
_FILM_SPAN_M = 2.0 * _CONTACT_RADIUS_M
_SETTINGS = NetworkSolverSettings(
    max_iterations=80,
    relative_volume_tolerance=1.0e-10,
    normalized_force_tolerance=8.0e-3,
    initial_step_fraction=0.04,
)


def _shared_patch(result: NetworkEquilibriumResult) -> FilmPatch:
    return next(patch for patch in result.network.patches if patch.id == "shared-ab")


def _central_vertices(mesh: SurfaceMesh, fraction: float = 0.60) -> list[tuple[float, float, float]]:
    radius = max(math.hypot(y, z) for _, y, z in mesh.vertices)
    cutoff = fraction * radius
    return [vertex for vertex in mesh.vertices if math.hypot(vertex[1], vertex[2]) <= cutoff + 1.0e-15]


def _fit_plane_deviation(mesh: SurfaceMesh) -> float:
    """RMS distance to x=c0+c1*y+c2*z in the declared central 60 percent."""
    points = _central_vertices(mesh)
    s1 = float(len(points))
    sy = sum(y for _, y, _ in points)
    sz = sum(z for _, _, z in points)
    syy = sum(y * y for _, y, _ in points)
    syz = sum(y * z for _, y, z in points)
    szz = sum(z * z for _, _, z in points)
    sx = sum(x for x, _, _ in points)
    syx = sum(y * x for x, y, _ in points)
    szx = sum(z * x for x, _, z in points)

    matrix = [[s1, sy, sz], [sy, syy, syz], [sz, syz, szz]]
    rhs = [sx, syx, szx]
    coefficients = _solve_small(matrix, rhs)
    residuals = [
        x - (coefficients[0] + coefficients[1] * y + coefficients[2] * z)
        for x, y, z in points
    ]
    return math.sqrt(sum(value * value for value in residuals) / len(residuals))


def _solve_small(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    n = len(rhs)
    rows = [list(row) + [rhs[index]] for index, row in enumerate(matrix)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(rows[row][column]))
        if abs(rows[pivot][column]) <= 1.0e-30:
            raise ValueError("singular benchmark fit")
        rows[column], rows[pivot] = rows[pivot], rows[column]
        scale = rows[column][column]
        for j in range(column, n + 1):
            rows[column][j] /= scale
        for row in range(n):
            if row == column:
                continue
            factor = rows[row][column]
            for j in range(column, n + 1):
                rows[row][j] -= factor * rows[column][j]
    return [rows[index][n] for index in range(n)]


def fit_near_planar_curvature(mesh: SurfaceMesh) -> float:
    """Fit x=c+b*r^2 over the central 60 percent and return kappa about +x."""
    points = _central_vertices(mesh)
    radial2 = [y * y + z * z for _, y, z in points]
    xs = [x for x, _, _ in points]
    mean_r2 = sum(radial2) / len(radial2)
    mean_x = sum(xs) / len(xs)
    denominator = sum((value - mean_r2) ** 2 for value in radial2)
    if denominator <= 1.0e-30:
        return 0.0
    slope = sum((r2 - mean_r2) * (x - mean_x) for r2, x in zip(radial2, xs)) / denominator
    return -4.0 * slope


def fit_shared_sphere_curvature(mesh: SurfaceMesh) -> tuple[float, float]:
    """Fit a sphere of revolution to solved vertices; return signed kappa and RMS fit error.

    The fit is diagnostic only.  The solver never consumes this curvature.
    """
    points = list(mesh.vertices)
    xs = [x for x, _, _ in points]
    radial_equation = [x * x + y * y + z * z for x, y, z in points]
    mean_x = sum(xs) / len(xs)
    mean_q = sum(radial_equation) / len(radial_equation)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator <= 1.0e-28:
        return 0.0, math.sqrt(sum(x * x for x in xs) / len(xs))

    slope = sum((x - mean_x) * (q - mean_q) for x, q in zip(xs, radial_equation)) / denominator
    intercept = mean_q - slope * mean_x
    center_x = 0.5 * slope
    radius_sq = intercept + center_x * center_x
    if radius_sq <= 0.0:
        raise ValueError("sphere fit produced a non-positive radius")
    radius = math.sqrt(radius_sq)
    sign = 1.0 if mean_x > center_x else -1.0
    radial_errors = [
        math.sqrt((x - center_x) ** 2 + y * y + z * z) - radius
        for x, y, z in points
    ]
    rms = math.sqrt(sum(value * value for value in radial_errors) / len(radial_errors))
    return sign * 2.0 / radius, rms


def _solve_case(radius_a_m: float, radius_b_m: float, perturbation_m: float) -> NetworkEquilibriumResult:
    reference = reference_two_bubble_network(
        radius_a_m=radius_a_m,
        radius_b_m=radius_b_m,
        contact_radius_m=_CONTACT_RADIUS_M,
        sheet_tension_n_m=_TENSION,
    )
    initial = perturb_shared_film(reference, perturbation_m)
    return solve_film_network(initial, _SETTINGS)


def equal_pressure_result() -> NetworkEquilibriumResult:
    return _solve_case(0.012, 0.012, 1.0e-6)


def unequal_pressure_result() -> NetworkEquilibriumResult:
    return _solve_case(0.010, 0.014, 2.0e-6)


def b04_equal_pressure_flatness() -> dict[str, Any]:
    result = equal_pressure_result()
    repeat = equal_pressure_result()
    shared = _shared_patch(result)
    pressure_difference = result.pressures_pa["bubble-a"] - result.pressures_pa["bubble-b"]
    fitted_curvature = fit_near_planar_curvature(shared.mesh)
    plane_rms = _fit_plane_deviation(shared.mesh)
    median_edge = statistics.median(shared.mesh.edge_lengths())
    max_edge = max(shared.mesh.edge_lengths())
    curvature_scale = _TENSION / _FILM_SPAN_M
    deterministic = (
        result.pressures_pa == repeat.pressures_pa
        and result.relative_volume_residuals == repeat.relative_volume_residuals
        and tuple(patch.mesh.vertices for patch in result.network.patches)
        == tuple(patch.mesh.vertices for patch in repeat.network.patches)
    )
    return {
        "benchmark": "B04 equal-pressure common-film flatness",
        "film_span_m": _FILM_SPAN_M,
        "eta_s": median_edge / _FILM_SPAN_M,
        "h_max_over_l": max_edge / _FILM_SPAN_M,
        "kappa_fit_1_m": fitted_curvature,
        "kappa_rms_l": abs(fitted_curvature) * _FILM_SPAN_M,
        "plane_deviation": plane_rms / _FILM_SPAN_M,
        "pressure_difference_pa": pressure_difference,
        "pressure_curvature_residual": abs(pressure_difference - _TENSION * fitted_curvature) / curvature_scale,
        "relative_volume_residuals": result.relative_volume_residuals,
        "normalized_projected_force": result.normalized_force_residual,
        "iterations": result.iterations,
        "converged": result.converged,
        "termination_reason": result.termination_reason,
        "deterministic_repeat": deterministic,
        "measurement": "central-60-percent plane/quadratic fit from solved shared-film vertices",
    }


def b05_unequal_pressure_curvature() -> dict[str, Any]:
    result = unequal_pressure_result()
    repeat = unequal_pressure_result()
    shared = _shared_patch(result)
    pressure_difference = result.pressures_pa["bubble-a"] - result.pressures_pa["bubble-b"]
    target_curvature = pressure_difference / _TENSION
    fitted_curvature, fit_rms = fit_shared_sphere_curvature(shared.mesh)
    median_edge = statistics.median(shared.mesh.edge_lengths())
    max_edge = max(shared.mesh.edge_lengths())
    normalization = max(abs(target_curvature), 1.0 / _FILM_SPAN_M)
    pressure_scale = max(abs(pressure_difference), _TENSION / _FILM_SPAN_M)
    deterministic = (
        result.pressures_pa == repeat.pressures_pa
        and result.relative_volume_residuals == repeat.relative_volume_residuals
        and tuple(patch.mesh.vertices for patch in result.network.patches)
        == tuple(patch.mesh.vertices for patch in repeat.network.patches)
    )
    normalized_error = abs(fitted_curvature - target_curvature) / normalization
    return {
        "benchmark": "B05 unequal-pressure common-film curvature",
        "film_span_m": _FILM_SPAN_M,
        "eta_s": median_edge / _FILM_SPAN_M,
        "h_max_over_l": max_edge / _FILM_SPAN_M,
        "pressure_a_pa": result.pressures_pa["bubble-a"],
        "pressure_b_pa": result.pressures_pa["bubble-b"],
        "pressure_difference_pa": pressure_difference,
        "target_curvature_1_m": target_curvature,
        "fitted_curvature_1_m": fitted_curvature,
        "normalized_curvature_error": normalized_error,
        "mean_relation_error": abs(fitted_curvature - target_curvature) / max(abs(target_curvature), 1.0e-30),
        "area_weighted_curvature_error": normalized_error,
        "pressure_curvature_residual": abs(pressure_difference - _TENSION * fitted_curvature) / pressure_scale,
        "curvature_fit_rms_m": fit_rms,
        "sign_consistent": fitted_curvature * pressure_difference > 0.0,
        "relative_volume_residuals": result.relative_volume_residuals,
        "normalized_projected_force": result.normalized_force_residual,
        "iterations": result.iterations,
        "converged": result.converged,
        "termination_reason": result.termination_reason,
        "deterministic_repeat": deterministic,
        "measurement": "sphere-of-revolution fit to solved shared-film vertices; fit is diagnostic-only",
    }


def assert_b04(metrics: dict[str, Any]) -> None:
    failures = []
    if metrics["eta_s"] > 3.0e-2:
        failures.append(f"eta_s={metrics['eta_s']:.6g} exceeds B04 fine target 0.03")
    if metrics["kappa_rms_l"] > 3.0e-3:
        failures.append("B04 kappa_rms*L exceeds 3e-3")
    if metrics["plane_deviation"] > 3.0e-3:
        failures.append("B04 plane deviation exceeds 3e-3")
    if metrics["pressure_curvature_residual"] > 1.0e-2:
        failures.append("B04 pressure/curvature residual exceeds 1e-2")
    if max(metrics["relative_volume_residuals"].values()) > 1.0e-8:
        failures.append("B04 coupled volume residual exceeds 1e-8")
    if not metrics["converged"]:
        failures.append("B04 network solve did not converge")
    if not metrics["deterministic_repeat"]:
        failures.append("B04 deterministic repeat differs")
    if failures:
        raise AssertionError("; ".join(failures))


def assert_b05(metrics: dict[str, Any]) -> None:
    failures = []
    if metrics["eta_s"] > 3.0e-2:
        failures.append(f"eta_s={metrics['eta_s']:.6g} exceeds B05 fine target 0.03")
    if metrics["normalized_curvature_error"] > 1.0e-2:
        failures.append("B05 normalized curvature error exceeds 1e-2")
    if metrics["area_weighted_curvature_error"] > 2.0e-2:
        failures.append("B05 curvature error exceeds 2e-2")
    if metrics["pressure_curvature_residual"] > 1.0e-2:
        failures.append("B05 pressure/curvature residual exceeds 1e-2")
    if not metrics["sign_consistent"]:
        failures.append("B05 curvature sign disagrees with pressure ordering")
    if max(metrics["relative_volume_residuals"].values()) > 1.0e-8:
        failures.append("B05 coupled volume residual exceeds 1e-8")
    if not metrics["converged"]:
        failures.append("B05 network solve did not converge")
    if not metrics["deterministic_repeat"]:
        failures.append("B05 deterministic repeat differs")
    if failures:
        raise AssertionError("; ".join(failures))
