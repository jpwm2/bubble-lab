"""B06 three-film Plateau junction validation and convergence checks."""
from __future__ import annotations

import math
from typing import Any

from .network import (
    NetworkEquilibriumResult,
    NetworkSolverSettings,
    junction_geometry_diagnostics,
    solve_film_network,
)
from .plateau import reference_plateau_network

_ANALYTICAL_EQUAL_ANGLE_DEG = 120.0
_EQUAL_TENSION = (0.05, 0.05, 0.05)


def _settings() -> NetworkSolverSettings:
    return NetworkSolverSettings(
        max_iterations=300,
        relative_volume_tolerance=1.0e-10,
        normalized_force_tolerance=5.0e-5,
        junction_force_tolerance=5.0e-3,
        initial_step_fraction=0.08,
    )


def plateau_three_result(
    *,
    longitudinal_segments: int = 48,
    tensions_n_m: tuple[float, float, float] = _EQUAL_TENSION,
    twist_rad: float = 0.25,
) -> NetworkEquilibriumResult:
    network = reference_plateau_network(
        longitudinal_segments=longitudinal_segments,
        tensions_n_m=tensions_n_m,
        twist_rad=twist_rad,
    )
    return solve_film_network(network, _settings())


def _flat_angles(diagnostics: dict[str, object]) -> list[float]:
    return [angle for triple in diagnostics["pairwise_angles_deg"] for angle in triple]


def _angle_metrics(angles: list[float]) -> tuple[float, float]:
    errors = [angle - _ANALYTICAL_EQUAL_ANGLE_DEG for angle in angles]
    rms = math.sqrt(sum(error * error for error in errors) / len(errors))
    return rms, max(abs(error) for error in errors)


def plateau_three(*, longitudinal_segments: int = 48) -> dict[str, Any]:
    initial = reference_plateau_network(longitudinal_segments=longitudinal_segments)
    initial_diag = junction_geometry_diagnostics(initial, "plateau-junction-0")
    initial_rms, _ = _angle_metrics(_flat_angles(initial_diag))

    result = solve_film_network(initial, _settings())
    diagnostics = junction_geometry_diagnostics(result.network, "plateau-junction-0")
    angles = _flat_angles(diagnostics)
    rms, maximum = _angle_metrics(angles)
    energy_monotone = all(
        after <= before + 1.0e-10 * max(abs(before), 1.0e-30)
        for before, after in zip(result.energy_history_j, result.energy_history_j[1:])
    )
    return {
        "benchmark": "B06 three-film Plateau junction",
        "longitudinal_segments": longitudinal_segments,
        "junction_eta": 1.0 / longitudinal_segments,
        "initial_angle_rms_error_deg": initial_rms,
        "angle_rms_error_deg": rms,
        "angle_max_error_deg": maximum,
        "junction_force_residual": float(diagnostics["max_force_residual"]),
        "relative_volume_residuals": result.relative_volume_residuals,
        "normalized_projected_force": result.normalized_force_residual,
        "surface_energy_j": result.surface_energy_j,
        "initial_surface_energy_j": result.initial_surface_energy_j,
        "energy_nonincrease": energy_monotone,
        "iterations": result.iterations,
        "converged": result.converged,
        "termination_reason": result.termination_reason,
        "measured_angles_deg": angles,
        "measurement": diagnostics["measurement"],
        "analytical_reference_deg": _ANALYTICAL_EQUAL_ANGLE_DEG,
    }


def assert_plateau_three(metrics: dict[str, Any]) -> None:
    failures = []
    if metrics["initial_angle_rms_error_deg"] <= 1.0:
        failures.append("B06 initial geometry is already too close to equilibrium")
    if metrics["angle_rms_error_deg"] > 1.0:
        failures.append("B06 RMS Plateau angle error exceeds 1 degree")
    if metrics["angle_max_error_deg"] > 2.0:
        failures.append("B06 maximum Plateau angle error exceeds 2 degrees")
    if metrics["junction_force_residual"] > 5.0e-3:
        failures.append("B06 junction force residual exceeds 5e-3")
    if max(metrics["relative_volume_residuals"].values()) > 1.0e-8:
        failures.append("B06 gas-volume residual exceeds 1e-8")
    if not metrics["energy_nonincrease"]:
        failures.append("B06 accepted energy history contains an unexplained increase")
    if not metrics["converged"]:
        failures.append("B06 network solve did not converge")
    if failures:
        raise AssertionError("; ".join(failures))


def plateau_convergence() -> dict[str, Any]:
    levels = [plateau_three(longitudinal_segments=value) for value in (20, 28, 40)]
    errors = [level["angle_rms_error_deg"] for level in levels]
    hs = [level["junction_eta"] for level in levels]
    orders = [
        math.log(errors[index] / errors[index + 1]) / math.log(hs[index] / hs[index + 1])
        for index in range(len(levels) - 1)
    ]
    return {
        "benchmark": "B06 Plateau junction refinement",
        "levels": levels,
        "observed_orders": orders,
        "fine_angle_rms_error_deg": errors[-1],
        "fine_force_residual": levels[-1]["junction_force_residual"],
        "measurement": "three-level longitudinal refinement of the common-line triangulated film network",
    }


def assert_plateau_convergence(metrics: dict[str, Any]) -> None:
    levels = metrics["levels"]
    errors = [level["angle_rms_error_deg"] for level in levels]
    forces = [level["junction_force_residual"] for level in levels]
    failures = []
    if not (errors[0] > errors[1] > errors[2]):
        failures.append("B06 angle error does not decrease under refinement")
    if min(metrics["observed_orders"]) < 0.9:
        failures.append("B06 observed Plateau-angle order is below 0.9")
    if forces[-1] > forces[0] or forces[-1] > 5.0e-3:
        failures.append("B06 junction force residual degrades under refinement")
    if any(max(level["relative_volume_residuals"].values()) > 1.0e-8 for level in levels):
        failures.append("B06 volume constraint degrades under refinement")
    if not all(level["converged"] for level in levels):
        failures.append("B06 refinement contains an unconverged solve")
    if failures:
        raise AssertionError("; ".join(failures))


def unequal_tension_metrics() -> dict[str, Any]:
    equal = plateau_three_result(longitudinal_segments=24, twist_rad=0.0)
    unequal = plateau_three_result(
        longitudinal_segments=24,
        tensions_n_m=(0.05, 0.04, 0.03),
        twist_rad=0.0,
    )
    equal_diag = junction_geometry_diagnostics(equal.network, "plateau-junction-0")
    unequal_diag = junction_geometry_diagnostics(unequal.network, "plateau-junction-0")
    equal_angles = _flat_angles(equal_diag)
    unequal_angles = _flat_angles(unequal_diag)
    return {
        "maximum_angle_change_deg": max(abs(a - b) for a, b in zip(equal_angles, unequal_angles)),
        "junction_force_residual": float(unequal_diag["max_force_residual"]),
        "equal_angles_deg": equal_angles,
        "unequal_angles_deg": unequal_angles,
        "converged": unequal.converged,
    }
