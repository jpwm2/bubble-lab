"""Deterministic supported-class fixtures for global multi-region CFD validation."""
from __future__ import annotations

from bubblelab.solvers.contact_lubrication import measure_axis_gap_geometry
from bubblelab.solvers.transient.geometry import FilmFront, icosphere
from bubblelab.solvers.transient.grid import GridConfig, RegionProperties
from bubblelab.solvers.transient.solver import (
    TimeStepPolicy,
    TransientConfig,
    TransientSoapFilmSolver,
)


def _translate(front: FilmFront, dx: float) -> None:
    front.vertices = [(x + dx, y, z) for x, y, z in front.vertices]


def _base_config(
    *,
    cells: int,
    extent_m: float,
    exterior_density_kg_m3: float,
    exterior_viscosity_pa_s: float,
    interior_density_kg_m3: float,
    interior_viscosity_pa_s: float,
    pressure_iterations: int,
    pressure_tolerance_s_inv: float,
    bubble_ids: tuple[str, ...],
) -> TransientConfig:
    origin = (-0.5 * extent_m, -0.5 * extent_m, -0.5 * extent_m)
    grid = GridConfig(
        cells=(cells, cells, cells),
        origin_m=origin,
        extent_m=(extent_m, extent_m, extent_m),
        density_kg_m3=exterior_density_kg_m3,
        dynamic_viscosity_pa_s=exterior_viscosity_pa_s,
        background_velocity_m_s=(0.0, 0.0, 0.0),
        pressure_iterations=pressure_iterations,
        pressure_tolerance_s_inv=pressure_tolerance_s_inv,
    )
    return TransientConfig(
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
            for bubble_id in bubble_ids
        },
    )


def build_supported_two_bubble_solver(
    *,
    cells: int = 14,
    extent_m: float = 0.024,
    radius_m: float = 0.003,
    gap_m: float = 0.0045,
    subdivisions: int = 1,
    exterior_density_kg_m3: float = 1.204,
    exterior_viscosity_pa_s: float = 1.825e-5,
    interior_density_kg_m3: float = 1.05,
    interior_viscosity_pa_s: float = 1.65e-5,
    pressure_iterations: int = 120,
    pressure_tolerance_s_inv: float = 2.0e-6,
) -> TransientSoapFilmSolver:
    """Build two separated tracked bubbles with an exact measured center-axis gap."""
    if cells < 8:
        raise ValueError("fixture requires at least eight cells per axis")
    if gap_m <= 0.0 or radius_m <= 0.0:
        raise ValueError("fixture radius and gap must be positive")
    center_offset = radius_m + 0.5 * gap_m
    first = icosphere(
        radius_m=radius_m,
        center_m=(-center_offset, 0.0, 0.0),
        subdivisions=subdivisions,
        bubble_id="bubble-a",
        surface_tension_n_m=0.0,
    )
    second = icosphere(
        radius_m=radius_m,
        center_m=(center_offset, 0.0, 0.0),
        subdivisions=subdivisions,
        bubble_id="bubble-b",
        surface_tension_n_m=0.0,
    )
    measured = measure_axis_gap_geometry(first, second)
    correction = 0.5 * (gap_m - measured.gap_m)
    _translate(first, -correction)
    _translate(second, correction)
    measured = measure_axis_gap_geometry(first, second)
    if abs(measured.gap_m - gap_m) > 2.0e-14 * max(1.0, gap_m):
        raise RuntimeError("fixture failed to place the requested triangulated gap")

    config = _base_config(
        cells=cells,
        extent_m=extent_m,
        exterior_density_kg_m3=exterior_density_kg_m3,
        exterior_viscosity_pa_s=exterior_viscosity_pa_s,
        interior_density_kg_m3=interior_density_kg_m3,
        interior_viscosity_pa_s=interior_viscosity_pa_s,
        pressure_iterations=pressure_iterations,
        pressure_tolerance_s_inv=pressure_tolerance_s_inv,
        bubble_ids=("bubble-a", "bubble-b"),
    )
    return TransientSoapFilmSolver([first, second], config)


def build_supported_three_bubble_solver(
    *,
    cells: int = 14,
    extent_m: float = 0.030,
    radius_m: float = 0.0022,
    left_gap_m: float = 0.0064,
    right_gap_m: float = 0.0060,
    subdivisions: int = 1,
    exterior_density_kg_m3: float = 1.204,
    exterior_viscosity_pa_s: float = 1.825e-5,
    interior_density_kg_m3: float = 1.05,
    interior_viscosity_pa_s: float = 1.65e-5,
    pressure_iterations: int = 120,
    pressure_tolerance_s_inv: float = 2.0e-6,
    front_order: tuple[str, str, str] = ("bubble-a", "bubble-b", "bubble-c"),
) -> TransientSoapFilmSolver:
    """Build a collinear three-bubble chain with two exact resolved gaps.

    ``front_order`` intentionally changes only container order.  Geometry and
    bubble identities remain fixed so permutation-invariance can be measured.
    """
    if cells < 8:
        raise ValueError("fixture requires at least eight cells per axis")
    if radius_m <= 0.0 or left_gap_m <= 0.0 or right_gap_m <= 0.0:
        raise ValueError("fixture radius and both gaps must be positive")
    expected = {"bubble-a", "bubble-b", "bubble-c"}
    if len(front_order) != 3 or set(front_order) != expected:
        raise ValueError("front_order must be a permutation of bubble-a/bubble-b/bubble-c")

    left_center = -(2.0 * radius_m + left_gap_m)
    right_center = 2.0 * radius_m + right_gap_m
    fronts = {
        "bubble-a": icosphere(
            radius_m=radius_m,
            center_m=(left_center, 0.0, 0.0),
            subdivisions=subdivisions,
            bubble_id="bubble-a",
            surface_tension_n_m=0.0,
        ),
        "bubble-b": icosphere(
            radius_m=radius_m,
            center_m=(0.0, 0.0, 0.0),
            subdivisions=subdivisions,
            bubble_id="bubble-b",
            surface_tension_n_m=0.0,
        ),
        "bubble-c": icosphere(
            radius_m=radius_m,
            center_m=(right_center, 0.0, 0.0),
            subdivisions=subdivisions,
            bubble_id="bubble-c",
            surface_tension_n_m=0.0,
        ),
    }

    left_measured = measure_axis_gap_geometry(fronts["bubble-a"], fronts["bubble-b"])
    right_measured = measure_axis_gap_geometry(fronts["bubble-b"], fronts["bubble-c"])
    _translate(fronts["bubble-a"], -(left_gap_m - left_measured.gap_m))
    _translate(fronts["bubble-c"], right_gap_m - right_measured.gap_m)
    left_measured = measure_axis_gap_geometry(fronts["bubble-a"], fronts["bubble-b"])
    right_measured = measure_axis_gap_geometry(fronts["bubble-b"], fronts["bubble-c"])
    tolerance = 2.0e-14 * max(1.0, left_gap_m, right_gap_m)
    if abs(left_measured.gap_m - left_gap_m) > tolerance:
        raise RuntimeError("fixture failed to place the requested left triangulated gap")
    if abs(right_measured.gap_m - right_gap_m) > tolerance:
        raise RuntimeError("fixture failed to place the requested right triangulated gap")

    half_extent = 0.5 * extent_m
    for front in fronts.values():
        if max(abs(vertex[0]) for vertex in front.vertices) >= half_extent:
            raise ValueError("three-bubble fixture does not fit inside the x domain")

    config = _base_config(
        cells=cells,
        extent_m=extent_m,
        exterior_density_kg_m3=exterior_density_kg_m3,
        exterior_viscosity_pa_s=exterior_viscosity_pa_s,
        interior_density_kg_m3=interior_density_kg_m3,
        interior_viscosity_pa_s=interior_viscosity_pa_s,
        pressure_iterations=pressure_iterations,
        pressure_tolerance_s_inv=pressure_tolerance_s_inv,
        bubble_ids=("bubble-a", "bubble-b", "bubble-c"),
    )
    return TransientSoapFilmSolver([fronts[bubble_id] for bubble_id in front_order], config)
