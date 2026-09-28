"""Projected constrained surface-energy minimizer for prescribed-volume bubbles."""
from __future__ import annotations

from dataclasses import dataclass
import math

from .energy import max_force, normalized_force_residual, stationarity, surface_energy
from .mesh import SurfaceMesh
from .vector import Vec3, add, scale, sub


@dataclass(frozen=True)
class SolverSettings:
    max_iterations: int = 200
    relative_volume_tolerance: float = 1.0e-10
    normalized_force_tolerance: float = 1.0e-3
    initial_step_fraction: float = 0.15
    minimum_step_fraction: float = 1.0e-8
    max_backtracks: int = 24
    energy_roundoff_allowance: float = 1.0e-13


@dataclass(frozen=True)
class EquilibriumResult:
    mesh: SurfaceMesh
    pressure_jump_pa: float
    converged: bool
    termination_reason: str
    iterations: int
    relative_volume_error: float
    normalized_force_residual: float
    surface_energy_j: float
    initial_surface_energy_j: float
    energy_history_j: tuple[float, ...]
    accepted_step_fractions: tuple[float, ...]


def _project_exact_volume(mesh: SurfaceMesh, target_volume_m3: float) -> SurfaceMesh:
    current = mesh.signed_volume()
    if current <= 0.0:
        raise ValueError("volume projection requires a positively oriented closed mesh")
    factor = (target_volume_m3 / current) ** (1.0 / 3.0)
    center = mesh.centroid()
    vertices = tuple(add(center, scale(sub(vertex, center), factor)) for vertex in mesh.vertices)
    return mesh.with_vertices(vertices)


def _relative_volume_error(mesh: SurfaceMesh, target_volume_m3: float) -> float:
    return abs(mesh.signed_volume() - target_volume_m3) / target_volume_m3


def solve_prescribed_volume(
    mesh: SurfaceMesh,
    target_volume_m3: float,
    sheet_tension_n_m: float,
    settings: SolverSettings | None = None,
) -> EquilibriumResult:
    """Minimize sigma*A subject to V=V_target using tangent projection plus exact retraction.

    The pressure jump is the discrete Lagrange multiplier that best satisfies
    grad(E) = p * grad(V) in the least-squares sense. Trial steps move along the
    projected energy gradient and are retracted exactly to the volume manifold by
    isotropic scaling about the vertex centroid. A backtracking line search accepts
    only non-increasing physical surface energy.
    """
    if target_volume_m3 <= 0.0:
        raise ValueError("target volume must be positive")
    if sheet_tension_n_m <= 0.0:
        raise ValueError("sheet tension must be positive")
    cfg = settings or SolverSettings()
    mesh.validate()
    current = _project_exact_volume(mesh, target_volume_m3)
    current.validate()
    initial_energy = surface_energy(current, sheet_tension_n_m)
    energy_history = [initial_energy]
    accepted_steps: list[float] = []
    termination = "maximum_iterations"
    converged = False
    iterations = 0

    for iteration in range(cfg.max_iterations + 1):
        iterations = iteration
        pressure_pa, projected_gradient = stationarity(current, sheet_tension_n_m)
        force_residual = normalized_force_residual(current, sheet_tension_n_m)
        volume_error = _relative_volume_error(current, target_volume_m3)
        if volume_error <= cfg.relative_volume_tolerance and force_residual <= cfg.normalized_force_tolerance:
            termination = "converged"
            converged = True
            break
        if iteration == cfg.max_iterations:
            break

        max_node_force = max_force(projected_gradient)
        if max_node_force <= 1.0e-30:
            termination = "stationary"
            converged = volume_error <= cfg.relative_volume_tolerance
            break
        median_edge = float(current.quality()["median_edge_length_m"])
        base_scale = cfg.initial_step_fraction * median_edge / max_node_force
        current_energy = energy_history[-1]
        accepted = False
        fraction = cfg.initial_step_fraction

        for _ in range(cfg.max_backtracks):
            scale_factor = base_scale * (fraction / cfg.initial_step_fraction)
            trial_vertices: list[Vec3] = [
                sub(vertex, scale(force, scale_factor))
                for vertex, force in zip(current.vertices, projected_gradient)
            ]
            trial = _project_exact_volume(current.with_vertices(trial_vertices), target_volume_m3)
            try:
                trial.validate()
            except ValueError:
                fraction *= 0.5
                if fraction < cfg.minimum_step_fraction:
                    break
                continue
            trial_energy = surface_energy(trial, sheet_tension_n_m)
            allowance = cfg.energy_roundoff_allowance * max(abs(current_energy), 1.0)
            if trial_energy <= current_energy + allowance:
                current = trial
                energy_history.append(trial_energy)
                accepted_steps.append(fraction)
                accepted = True
                break
            fraction *= 0.5
            if fraction < cfg.minimum_step_fraction:
                break

        if not accepted:
            termination = "line_search_stalled"
            break

    pressure_pa, _ = stationarity(current, sheet_tension_n_m)
    final_force = normalized_force_residual(current, sheet_tension_n_m)
    final_volume_error = _relative_volume_error(current, target_volume_m3)
    if not converged and final_volume_error <= cfg.relative_volume_tolerance and final_force <= cfg.normalized_force_tolerance:
        converged = True
        termination = "converged"
    return EquilibriumResult(
        mesh=current,
        pressure_jump_pa=pressure_pa,
        converged=converged,
        termination_reason=termination,
        iterations=iterations,
        relative_volume_error=final_volume_error,
        normalized_force_residual=final_force,
        surface_energy_j=surface_energy(current, sheet_tension_n_m),
        initial_surface_energy_j=initial_energy,
        energy_history_j=tuple(energy_history),
        accepted_step_fractions=tuple(accepted_steps),
    )
