"""Deterministic closed-front fixtures for bounded T1-through-global-CFD validation."""
from __future__ import annotations

from typing import Sequence

from bubblelab.solvers.transient.geometry import FilmFront, icosphere, norm
from bubblelab.solvers.transient.grid import GridConfig, RegionProperties
from bubblelab.solvers.transient.solver import (
    TimeStepPolicy,
    TransientConfig,
    TransientSoapFilmSolver,
)


def _cyclic(point: tuple[float, float, float], axis_cycle: int) -> tuple[float, float, float]:
    cycle = axis_cycle % 3
    if cycle == 0:
        return point
    if cycle == 1:
        return (point[1], point[2], point[0])
    return (point[2], point[0], point[1])


def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return norm((a[0] - b[0], a[1] - b[1], a[2] - b[2]))


def build_supported_four_region_t1_solver(
    *,
    region_ids: Sequence[str],
    old_pair: tuple[str, str],
    cells: int = 14,
    extent_m: float = 0.014,
    radius_m: float = 0.00120,
    old_pair_gap_m: float = 0.00035,
    transverse_offset_m: float = 0.00310,
    transverse_z_offset_m: float = 0.00135,
    subdivisions: int = 1,
    exterior_density_kg_m3: float = 1.204,
    exterior_viscosity_pa_s: float = 1.825e-5,
    interior_density_kg_m3: float = 1.05,
    interior_viscosity_pa_s: float = 1.65e-5,
    pressure_iterations: int = 120,
    pressure_tolerance_s_inv: float = 2.0e-6,
    front_order: Sequence[str] | None = None,
    axis_cycle: int = 0,
) -> TransientSoapFilmSolver:
    """Build four stable gas fronts around one supported T1 neighborhood.

    The old-adjacent pair is deliberately separated by less than one Eulerian cell
    at the default resolution.  Their regularized immersed supports therefore
    overlap and exercise the partitioned shared-support treatment.  The opposite
    pair is offset out of plane so all four fronts participate in the same 3D field
    without introducing a second physical surface intersection.
    """
    ids = tuple(sorted(str(value) for value in region_ids))
    if len(ids) != 4 or len(set(ids)) != 4:
        raise ValueError("four-region T1 fixture requires exactly four unique gas IDs")
    pair = tuple(sorted(old_pair))
    if len(set(pair)) != 2 or not set(pair).issubset(ids):
        raise ValueError("old_pair must contain two distinct fixture gas IDs")
    opposite = tuple(value for value in ids if value not in pair)
    if cells < 8:
        raise ValueError("four-region T1 fixture requires at least eight cells per axis")
    if min(extent_m, radius_m, old_pair_gap_m) <= 0.0:
        raise ValueError("fixture extent, radius and old-pair gap must be positive")
    if front_order is None:
        order = ids
    else:
        order = tuple(str(value) for value in front_order)
        if len(order) != 4 or set(order) != set(ids):
            raise ValueError("front_order must be a permutation of the four gas IDs")

    half_separation = radius_m + 0.5 * old_pair_gap_m
    base_centers = {
        pair[0]: (-half_separation, 0.0, 0.0),
        pair[1]: (half_separation, 0.0, 0.0),
        opposite[0]: (0.0, -transverse_offset_m, -transverse_z_offset_m),
        opposite[1]: (0.0, transverse_offset_m, transverse_z_offset_m),
    }
    centers = {key: _cyclic(value, axis_cycle) for key, value in base_centers.items()}
    minimum_center_distance = min(
        _distance(centers[left], centers[right])
        for i, left in enumerate(ids)
        for right in ids[i + 1 :]
    )
    if minimum_center_distance <= 2.0 * radius_m:
        raise ValueError("four-region support spheres physically intersect")

    fronts = {
        bubble_id: icosphere(
            radius_m=radius_m,
            center_m=centers[bubble_id],
            subdivisions=subdivisions,
            bubble_id=bubble_id,
            surface_tension_n_m=0.0,
        )
        for bubble_id in ids
    }
    half_extent = 0.5 * extent_m
    for front in fronts.values():
        if any(
            max(abs(vertex[axis]) for vertex in front.vertices) >= half_extent
            for axis in range(3)
        ):
            raise ValueError("four-region T1 fixture does not fit inside the Eulerian domain")

    grid = GridConfig(
        cells=(cells, cells, cells),
        origin_m=(-half_extent, -half_extent, -half_extent),
        extent_m=(extent_m, extent_m, extent_m),
        density_kg_m3=exterior_density_kg_m3,
        dynamic_viscosity_pa_s=exterior_viscosity_pa_s,
        background_velocity_m_s=(0.0, 0.0, 0.0),
        pressure_iterations=pressure_iterations,
        pressure_tolerance_s_inv=pressure_tolerance_s_inv,
    )
    config = TransientConfig(
        grid=grid,
        gravity_m_s2=(0.0, 0.0, 0.0),
        timestep=TimeStepPolicy(
            max_dt_s=2.0e-4,
            advective_cfl=0.35,
            viscous_safety=0.15,
            capillary_safety=0.20,
            min_dt_s=1.0e-9,
        ),
        preserve_closed_bubble_volume=True,
        sharp_pressure_jump=False,
        region_properties={
            bubble_id: RegionProperties(
                interior_density_kg_m3,
                interior_viscosity_pa_s,
            )
            for bubble_id in ids
        },
    )
    return TransientSoapFilmSolver([fronts[bubble_id] for bubble_id in order], config)
