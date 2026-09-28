"""Discrete area/volume energies, exact first variations, and force diagnostics."""
from __future__ import annotations

import math

from .mesh import SurfaceMesh
from .vector import Vec3, cross, dot, norm, scale, sub, unit


def surface_energy(mesh: SurfaceMesh, sheet_tension_n_m: float) -> float:
    if sheet_tension_n_m < 0.0:
        raise ValueError("sheet tension must be non-negative")
    return sheet_tension_n_m * mesh.area()


def area_gradient(mesh: SurfaceMesh) -> tuple[Vec3, ...]:
    gradients = [[0.0, 0.0, 0.0] for _ in mesh.vertices]
    for ia, ib, ic in mesh.faces:
        a, b, c = mesh.vertices[ia], mesh.vertices[ib], mesh.vertices[ic]
        normal = unit(cross(sub(b, a), sub(c, a)))
        local = (
            scale(cross(sub(b, c), normal), 0.5),
            scale(cross(sub(c, a), normal), 0.5),
            scale(cross(sub(a, b), normal), 0.5),
        )
        for index, grad in zip((ia, ib, ic), local):
            gradients[index][0] += grad[0]
            gradients[index][1] += grad[1]
            gradients[index][2] += grad[2]
    return tuple(tuple(value) for value in gradients)


def volume_gradient(mesh: SurfaceMesh) -> tuple[Vec3, ...]:
    gradients = [[0.0, 0.0, 0.0] for _ in mesh.vertices]
    for ia, ib, ic in mesh.faces:
        a, b, c = mesh.vertices[ia], mesh.vertices[ib], mesh.vertices[ic]
        local = (
            scale(cross(b, c), 1.0 / 6.0),
            scale(cross(c, a), 1.0 / 6.0),
            scale(cross(a, b), 1.0 / 6.0),
        )
        for index, grad in zip((ia, ib, ic), local):
            gradients[index][0] += grad[0]
            gradients[index][1] += grad[1]
            gradients[index][2] += grad[2]
    return tuple(tuple(value) for value in gradients)


def stationarity(mesh: SurfaceMesh, sheet_tension_n_m: float) -> tuple[float, tuple[Vec3, ...]]:
    """Return pressure multiplier and grad(E)-p*grad(V) at every vertex."""
    grad_area = area_gradient(mesh)
    grad_volume = volume_gradient(mesh)
    grad_energy = tuple(scale(value, sheet_tension_n_m) for value in grad_area)
    denominator = sum(dot(value, value) for value in grad_volume)
    if denominator <= 1.0e-30:
        raise ValueError("volume gradient is singular")
    pressure_pa = sum(dot(ge, gv) for ge, gv in zip(grad_energy, grad_volume)) / denominator
    residual = tuple(sub(ge, scale(gv, pressure_pa)) for ge, gv in zip(grad_energy, grad_volume))
    return pressure_pa, residual


def normalized_force_residual(mesh: SurfaceMesh, sheet_tension_n_m: float) -> float:
    _, residual = stationarity(mesh, sheet_tension_n_m)
    quality = mesh.quality()
    h = float(quality["median_edge_length_m"])
    rms_force = math.sqrt(sum(dot(value, value) for value in residual) / len(residual))
    scale_force = max(sheet_tension_n_m * h, 1.0e-30)
    return rms_force / scale_force


def max_force(residual: tuple[Vec3, ...]) -> float:
    return max(norm(value) for value in residual)
