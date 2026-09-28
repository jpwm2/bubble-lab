"""Closed-front fixtures for bounded many-contact T1/global-CFD validation."""
from __future__ import annotations

import math
from typing import Sequence

from bubblelab.solvers.transient.geometry import icosphere, norm
from bubblelab.solvers.transient.grid import GridConfig, RegionProperties
from bubblelab.solvers.transient.solver import (
    TimeStepPolicy,
    TransientConfig,
    TransientSoapFilmSolver,
)


def _cyclic(
    point: tuple[float, float, float], axis_cycle: int
) -> tuple[float, float, float]:
    cycle = axis_cycle % 3
    if cycle == 0:
        return point
    if cycle == 1:
        return (point[1], point[2], point[0])
    return (point[2], point[0], point[1])


def _distance(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
) -> float:
    return norm((a[0] - b[0], a[1] - b[1], a[2] - b[2]))


def build_supported_manycontact_t1_solver(
    *,
    region_ids: Sequence[str],
    old_pair: tuple[str, str],
    extra_region_id: str = "E",
    cells: int = 10,
    extent_m: float = 0.010,
    radius_m: float = 0.00105,
    old_pair_gap_m: float = 0.00028,
    transverse_offset_m: float = 0.00275,
    transverse_z_offset_m: float = 0.00160,
    non_event_gap_m: float = 0.00018,
    non_event_lateral_offset_m: float = 0.00025,
    subdivisions: int = 2,
    exterior_density_kg_m3: float = 970.0,
    exterior_viscosity_pa_s: float = 50.0,
    interior_density_kg_m3: float = 1.204,
    interior_viscosity_pa_s: float = 1.825e-5,
    pressure_iterations: int = 120,
    pressure_tolerance_s_inv: float = 2.0e-6,
    front_order: Sequence[str] | None = None,
    axis_cycle: int = 0,
) -> TransientSoapFilmSolver:
    """Build a five-front field with one T1 pair and one extra active contact.

    The four topology regions retain the accepted non-coplanar arrangement.  The
    fifth support region is placed at a resolved physical gap from the first
    event-region front, predominantly out of the event-pair axis.  Thus the
    non-event gap can perturb the global pressure/viscous field without directly
    prescribing the event pair's scalar closing velocity.
    """

    topology_ids = tuple(sorted(str(value) for value in region_ids))
    if len(topology_ids) != 4 or len(set(topology_ids)) != 4:
        raise ValueError(
            "many-contact T1 fixture requires exactly four topology gas IDs"
        )
    extra_id = str(extra_region_id)
    if extra_id in topology_ids:
        raise ValueError("extra support region ID must be distinct")
    support_ids = tuple(sorted((*topology_ids, extra_id)))

    pair = tuple(sorted(old_pair))
    if len(set(pair)) != 2 or not set(pair).issubset(topology_ids):
        raise ValueError(
            "old_pair must contain two distinct topology gas IDs"
        )
    opposite = tuple(value for value in topology_ids if value not in pair)
    if cells < 8:
        raise ValueError(
            "many-contact T1 fixture requires at least eight cells per axis"
        )
    if min(
        extent_m,
        radius_m,
        old_pair_gap_m,
        transverse_offset_m,
        transverse_z_offset_m,
        non_event_gap_m,
    ) <= 0.0:
        raise ValueError("many-contact fixture lengths must be positive")
    if non_event_lateral_offset_m < 0.0:
        raise ValueError(
            "many-contact non-event lateral offset must be non-negative"
        )

    if front_order is None:
        order = support_ids
    else:
        order = tuple(str(value) for value in front_order)
        if len(order) != len(support_ids) or set(order) != set(support_ids):
            raise ValueError(
                "front_order must be a permutation of all support IDs"
            )

    half_separation = radius_m + 0.5 * old_pair_gap_m
    base_centers: dict[str, tuple[float, float, float]] = {
        pair[0]: (-half_separation, 0.0, 0.0),
        pair[1]: (half_separation, 0.0, 0.0),
        opposite[0]: (
            0.0,
            -transverse_offset_m,
            -transverse_z_offset_m,
        ),
        opposite[1]: (
            0.0,
            transverse_offset_m,
            transverse_z_offset_m,
        ),
    }

    non_event_center_distance = 2.0 * radius_m + non_event_gap_m
    if non_event_lateral_offset_m >= non_event_center_distance:
        raise ValueError(
            "non-event lateral offset must be smaller than center distance"
        )
    normal_offset = math.sqrt(
        non_event_center_distance * non_event_center_distance
        - non_event_lateral_offset_m * non_event_lateral_offset_m
    )
    anchor = base_centers[pair[0]]
    base_centers[extra_id] = (
        anchor[0],
        anchor[1] + non_event_lateral_offset_m,
        anchor[2] + normal_offset,
    )

    centers = {
        key: _cyclic(value, axis_cycle)
        for key, value in base_centers.items()
    }
    minimum_center_distance = min(
        _distance(centers[left], centers[right])
        for i, left in enumerate(support_ids)
        for right in support_ids[i + 1 :]
    )
    if minimum_center_distance <= 2.0 * radius_m:
        raise ValueError(
            "many-contact support spheres physically intersect"
        )

    fronts = {
        bubble_id: icosphere(
            radius_m=radius_m,
            center_m=centers[bubble_id],
            subdivisions=subdivisions,
            bubble_id=bubble_id,
            surface_tension_n_m=0.0,
        )
        for bubble_id in support_ids
    }
    half_extent = 0.5 * extent_m
    for front in fronts.values():
        if any(
            max(abs(vertex[axis]) for vertex in front.vertices)
            >= half_extent
            for axis in range(3)
        ):
            raise ValueError(
                "many-contact T1 fixture does not fit inside Eulerian domain"
            )

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
            for bubble_id in support_ids
        },
    )
    return TransientSoapFilmSolver(
        [fronts[bubble_id] for bubble_id in order], config
    )
