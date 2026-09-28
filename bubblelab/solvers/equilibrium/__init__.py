"""High-fidelity quasi-static equilibrium primitives for Bubble Lab."""

from .mesh import SurfaceMesh
from .network import (
    FilmNetwork,
    FilmPatch,
    GasRegion,
    NetworkEquilibriumResult,
    NetworkSolverSettings,
    PlateauJunction,
    junction_geometry_diagnostics,
    project_region_volumes,
    solve_film_network,
)
from .solver import EquilibriumResult, SolverSettings, solve_prescribed_volume
from .sphere import icosphere, radius_from_volume

__all__ = [
    "EquilibriumResult",
    "FilmNetwork",
    "FilmPatch",
    "GasRegion",
    "NetworkEquilibriumResult",
    "NetworkSolverSettings",
    "PlateauJunction",
    "SolverSettings",
    "SurfaceMesh",
    "icosphere",
    "junction_geometry_diagnostics",
    "project_region_volumes",
    "radius_from_volume",
    "solve_film_network",
    "solve_prescribed_volume",
]
