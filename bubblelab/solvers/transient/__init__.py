"""Bubble Lab transient front-tracking sharp-interface reference backend."""
from .geometry import FilmFront, icosphere
from .grid import EulerianGasGrid, GridConfig, RegionProperties
from .amr import AMRConfig, AdaptiveEulerianGasGrid
from .solver import TimeStepPolicy, TransientConfig, TransientSoapFilmSolver
from .release_acceleration import (
    AccelerationPolicy,
    AcceleratedTransientSoapFilmSolver,
    ReleaseAdaptiveEulerianGasGrid,
)
from .remeshing import ConservativeArealField, FrontRemesher, MeshQuality, RemeshConfig, RemeshReport, mesh_quality
from .export import frame_dict

__all__ = [
    "FilmFront", "icosphere", "EulerianGasGrid", "GridConfig", "RegionProperties",
    "AMRConfig", "AdaptiveEulerianGasGrid", "ReleaseAdaptiveEulerianGasGrid",
    "TimeStepPolicy", "TransientConfig", "TransientSoapFilmSolver",
    "AccelerationPolicy", "AcceleratedTransientSoapFilmSolver",
    "ConservativeArealField", "FrontRemesher", "MeshQuality", "RemeshConfig",
    "RemeshReport", "mesh_quality", "frame_dict",
]
