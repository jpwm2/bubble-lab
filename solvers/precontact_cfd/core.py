"""Numerically resolved local thin-gap incompressible squeeze-flow foundation.

This module advances beyond the reduced Reynolds/Taylor production force by solving
an axisymmetric finite-volume pressure problem whose face conductances are themselves
obtained from a discretized no-slip Stokes velocity solve across the measured gap.
Taylor/Reynolds closed forms are intentionally absent from the production solve and
are reserved for validation code.

The supported class is one isolated two-front gap. Authoritative triangulated front
geometry supplies the minimum gap and local curvatures through ``GapGeometry``; those
measurements define a deterministic local parabolic patch. The patch is not a global
multi-region replacement for the accepted transient solver.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from bubblelab.solvers.contact_lubrication import GapGeometry


@dataclass(frozen=True)
class PrecontactCFDSettings:
    """Physical/numerical limits for the supported local thin-gap solve."""

    enabled: bool = True
    minimum_gap_m: float = 1.0e-7
    onset_gap_over_effective_radius: float = 0.5
    outer_drag_scale: float = 1.0
    radial_cells: int = 64
    gap_cells: int = 16
    radial_extent_over_sqrt_2rh: float = 100.0
    radial_stretch: float = 6.0
    volume_relative_tolerance: float = 5.0e-12

    def validate(self) -> None:
        if self.minimum_gap_m <= 0.0:
            raise ValueError("minimum CFD gap must be positive")
        if self.onset_gap_over_effective_radius <= 0.0:
            raise ValueError("CFD onset ratio must be positive")
        if self.outer_drag_scale <= 0.0:
            raise ValueError("outer drag scale must be positive")
        if self.radial_cells < 8:
            raise ValueError("pre-contact CFD requires at least 8 radial cells")
        if self.gap_cells < 4:
            raise ValueError("pre-contact CFD requires at least 4 gap cells")
        if self.radial_extent_over_sqrt_2rh < 8.0:
            raise ValueError("pre-contact CFD radial extent is too small")
        if self.radial_stretch <= 0.0:
            raise ValueError("pre-contact CFD radial stretch must be positive")
        if self.volume_relative_tolerance <= 0.0:
            raise ValueError("volume tolerance must be positive")


@dataclass(frozen=True)
class ThinGapField:
    """Resolved pressure and radial velocity field for one local gap patch."""

    radial_faces_m: tuple[float, ...]
    radial_centers_m: tuple[float, ...]
    gap_at_faces_m: tuple[float, ...]
    gap_at_centers_m: tuple[float, ...]
    pressure_pa: tuple[float, ...]
    radial_velocity_faces_m_s: tuple[tuple[float, ...], ...]
    closing_speed_m_s: float
    lower_wall_normal_velocity_m_s: float
    upper_wall_normal_velocity_m_s: float
    pressure_force_n: float
    center_pressure_pa: float
    outer_radial_outflow_m3_s: float
    swept_gap_volume_rate_m3_s: float
    mass_balance_relative_residual: float
    max_pressure_equation_residual_m3_s: float
    max_wall_slip_m_s: float
    max_radial_velocity_m_s: float
    max_wall_shear_pa: float
    viscous_dissipation_w: float

    def compact_dict(self) -> dict[str, object]:
        pressure_samples = _sample_values(self.radial_centers_m, self.pressure_pa, 9)
        velocity_indices = _sample_indices(len(self.radial_velocity_faces_m_s), 5)
        velocity_samples = [
            {
                "radial_face_m": float(self.radial_faces_m[index]),
                "radial_velocity_m_s": [
                    float(value) for value in self.radial_velocity_faces_m_s[index]
                ],
            }
            for index in velocity_indices
        ]
        return {
            "radial_cells": len(self.radial_centers_m),
            "gap_cells": len(self.radial_velocity_faces_m_s[0]) - 1,
            "radial_extent_m": float(self.radial_faces_m[-1]),
            "pressure_force_n": float(self.pressure_force_n),
            "center_pressure_pa": float(self.center_pressure_pa),
            "max_radial_velocity_m_s": float(self.max_radial_velocity_m_s),
            "max_wall_shear_pa": float(self.max_wall_shear_pa),
            "outer_radial_outflow_m3_s": float(self.outer_radial_outflow_m3_s),
            "swept_gap_volume_rate_m3_s": float(self.swept_gap_volume_rate_m3_s),
            "mass_balance_relative_residual": float(self.mass_balance_relative_residual),
            "max_pressure_equation_residual_m3_s": float(
                self.max_pressure_equation_residual_m3_s
            ),
            "max_wall_slip_m_s": float(self.max_wall_slip_m_s),
            "viscous_dissipation_w": float(self.viscous_dissipation_w),
            "pressure_profile_samples": pressure_samples,
            "radial_velocity_profile_samples": velocity_samples,
            "moving_interface_bc_m_s": {
                "lower_normal": float(self.lower_wall_normal_velocity_m_s),
                "upper_normal": float(self.upper_wall_normal_velocity_m_s),
                "tangential_no_slip": 0.0,
            },
        }


@dataclass(frozen=True)
class PrecontactCFDResponse:
    """Numerical traction feedback for one pre-contact step."""

    active: bool
    free_closing_speed_m_s: float
    coupled_closing_speed_m_s: float
    correction_speed_m_s: float
    outer_resistance_n_s_m: float
    cfd_resistance_n_s_m: float
    resistance_ratio: float
    force_n: float
    center_pressure_pa: float
    characteristic_patch_radius_m: float
    radial_outflow_m3_s: float
    viscous_dissipation_w: float
    field: ThinGapField | None
    model: str = "LOCAL_DISCRETIZED_INCOMPRESSIBLE_THIN_GAP_CFD"

    def as_dict(self) -> dict[str, object]:
        return {
            "active": bool(self.active),
            "free_closing_speed_m_s": float(self.free_closing_speed_m_s),
            "coupled_closing_speed_m_s": float(self.coupled_closing_speed_m_s),
            "correction_speed_m_s": float(self.correction_speed_m_s),
            "outer_resistance_n_s_m": float(self.outer_resistance_n_s_m),
            "cfd_resistance_n_s_m": float(self.cfd_resistance_n_s_m),
            "resistance_ratio": float(self.resistance_ratio),
            "force_n": float(self.force_n),
            "center_pressure_pa": float(self.center_pressure_pa),
            "characteristic_patch_radius_m": float(self.characteristic_patch_radius_m),
            "radial_outflow_m3_s": float(self.radial_outflow_m3_s),
            "viscous_dissipation_w": float(self.viscous_dissipation_w),
            "model": self.model,
            "field": None if self.field is None else self.field.compact_dict(),
        }


def _sample_indices(length: int, count: int) -> list[int]:
    if length <= 0:
        return []
    if count <= 1 or length == 1:
        return [0]
    out = {
        min(length - 1, int(round(index * (length - 1) / (count - 1))))
        for index in range(count)
    }
    return sorted(out)


def _sample_values(
    coordinates: tuple[float, ...],
    values: tuple[float, ...],
    count: int,
) -> list[dict[str, float]]:
    return [
        {"radial_position_m": float(coordinates[index]), "pressure_pa": float(values[index])}
        for index in _sample_indices(len(values), count)
    ]


def _solve_tridiagonal(
    lower: list[float],
    diagonal: list[float],
    upper: list[float],
    rhs: list[float],
) -> list[float]:
    count = len(diagonal)
    if not (len(lower) == len(upper) == len(rhs) == count):
        raise ValueError("tridiagonal arrays must have equal length")
    if count == 0:
        return []
    a = list(lower)
    b = list(diagonal)
    c = list(upper)
    d = list(rhs)
    for index in range(1, count):
        if abs(b[index - 1]) <= 1.0e-300:
            raise RuntimeError("singular thin-gap tridiagonal system")
        factor = a[index] / b[index - 1]
        b[index] -= factor * c[index - 1]
        d[index] -= factor * d[index - 1]
    if abs(b[-1]) <= 1.0e-300:
        raise RuntimeError("singular thin-gap tridiagonal system")
    solution = [0.0] * count
    solution[-1] = d[-1] / b[-1]
    for index in range(count - 2, -1, -1):
        if abs(b[index]) <= 1.0e-300:
            raise RuntimeError("singular thin-gap tridiagonal system")
        solution[index] = (d[index] - c[index] * solution[index + 1]) / b[index]
    return solution


def _stokes_profile(
    gap_m: float,
    dynamic_viscosity_pa_s: float,
    pressure_gradient_pa_m: float,
    gap_cells: int,
) -> tuple[tuple[float, ...], float, float]:
    """Solve mu*d2u/dz2=dp/dr with no-slip at both moving interfaces."""
    if gap_m <= 0.0 or dynamic_viscosity_pa_s <= 0.0:
        raise ValueError("gap and viscosity must be positive")
    if gap_cells < 2:
        raise ValueError("gap velocity solve requires at least two cells")
    dz = gap_m / gap_cells
    interior_count = gap_cells - 1
    coefficient = dynamic_viscosity_pa_s / (dz * dz)
    lower = [0.0] * interior_count
    diagonal = [-2.0 * coefficient] * interior_count
    upper = [0.0] * interior_count
    rhs = [float(pressure_gradient_pa_m)] * interior_count
    for index in range(1, interior_count):
        lower[index] = coefficient
    for index in range(interior_count - 1):
        upper[index] = coefficient
    interior = _solve_tridiagonal(lower, diagonal, upper, rhs)
    velocity = (0.0, *interior, 0.0)
    integrated_flux = 0.0
    dissipation_per_area = 0.0
    for index in range(gap_cells):
        integrated_flux += 0.5 * (velocity[index] + velocity[index + 1]) * dz
        shear_rate = (velocity[index + 1] - velocity[index]) / dz
        dissipation_per_area += dynamic_viscosity_pa_s * shear_rate * shear_rate * dz
    return tuple(float(value) for value in velocity), integrated_flux, dissipation_per_area


def _numerical_mobility(
    gap_m: float,
    dynamic_viscosity_pa_s: float,
    gap_cells: int,
) -> float:
    _, unit_gradient_flux, _ = _stokes_profile(
        gap_m,
        dynamic_viscosity_pa_s,
        1.0,
        gap_cells,
    )
    mobility = -unit_gradient_flux
    if mobility <= 0.0:
        raise RuntimeError("no-slip gap velocity solve produced non-positive mobility")
    return mobility


def _radial_grid(
    effective_radius_m: float,
    gap_m: float,
    settings: PrecontactCFDSettings,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    characteristic = math.sqrt(2.0 * effective_radius_m * gap_m)
    radial_extent = settings.radial_extent_over_sqrt_2rh * characteristic
    denominator = math.sinh(settings.radial_stretch)
    faces = tuple(
        radial_extent
        * math.sinh(settings.radial_stretch * index / settings.radial_cells)
        / denominator
        for index in range(settings.radial_cells + 1)
    )
    centers = tuple(
        0.5 * (faces[index] + faces[index + 1])
        for index in range(settings.radial_cells)
    )
    return faces, centers


def solve_thin_gap_field(
    geometry: GapGeometry,
    closing_speed_m_s: float,
    dynamic_viscosity_pa_s: float,
    settings: PrecontactCFDSettings | None = None,
) -> ThinGapField:
    """Solve pressure and no-slip radial velocity on a deterministic local patch."""
    cfg = settings or PrecontactCFDSettings()
    cfg.validate()
    speed = float(closing_speed_m_s)
    if speed < 0.0:
        raise ValueError("closing speed must be non-negative")
    if dynamic_viscosity_pa_s <= 0.0:
        raise ValueError("ambient dynamic viscosity must be positive")
    radius = float(geometry.effective_radius_m)
    if radius <= 0.0:
        raise ValueError("effective gap radius must be positive")
    minimum_gap = max(float(geometry.gap_m), cfg.minimum_gap_m)
    radial_faces, radial_centers = _radial_grid(radius, minimum_gap, cfg)
    gap_faces = tuple(
        minimum_gap + radial * radial / (2.0 * radius) for radial in radial_faces
    )
    gap_centers = tuple(
        minimum_gap + radial * radial / (2.0 * radius) for radial in radial_centers
    )
    mobilities = tuple(
        _numerical_mobility(gap, dynamic_viscosity_pa_s, cfg.gap_cells)
        for gap in gap_faces
    )

    count = cfg.radial_cells
    lower = [0.0] * count
    diagonal = [0.0] * count
    upper = [0.0] * count
    rhs = [0.0] * count
    for index in range(count):
        west_radius = radial_faces[index]
        east_radius = radial_faces[index + 1]
        west_coefficient = 0.0
        if index > 0:
            west_distance = radial_centers[index] - radial_centers[index - 1]
            west_coefficient = west_radius * mobilities[index] / west_distance
        if index < count - 1:
            east_distance = radial_centers[index + 1] - radial_centers[index]
        else:
            east_distance = radial_faces[index + 1] - radial_centers[index]
        east_coefficient = east_radius * mobilities[index + 1] / east_distance
        if index > 0:
            lower[index] = -west_coefficient
        diagonal[index] = west_coefficient + east_coefficient
        if index < count - 1:
            upper[index] = -east_coefficient
        rhs[index] = speed * 0.5 * (
            east_radius * east_radius - west_radius * west_radius
        )

    pressure = tuple(_solve_tridiagonal(lower, diagonal, upper, rhs))
    pressure_gradients = [0.0] * (count + 1)
    for face_index in range(1, count):
        pressure_gradients[face_index] = (
            pressure[face_index] - pressure[face_index - 1]
        ) / (radial_centers[face_index] - radial_centers[face_index - 1])
    pressure_gradients[-1] = -pressure[-1] / (
        radial_faces[-1] - radial_centers[-1]
    )

    velocity_profiles: list[tuple[float, ...]] = []
    radial_fluxes: list[float] = []
    face_dissipation_per_area: list[float] = []
    max_wall_slip = 0.0
    max_velocity = 0.0
    max_wall_shear = 0.0
    for face_index, gradient in enumerate(pressure_gradients):
        velocity, flux, dissipation_per_area = _stokes_profile(
            gap_faces[face_index],
            dynamic_viscosity_pa_s,
            gradient,
            cfg.gap_cells,
        )
        velocity_profiles.append(velocity)
        radial_fluxes.append(flux)
        face_dissipation_per_area.append(dissipation_per_area)
        max_wall_slip = max(max_wall_slip, abs(velocity[0]), abs(velocity[-1]))
        max_velocity = max(max_velocity, *(abs(value) for value in velocity))
        dz = gap_faces[face_index] / cfg.gap_cells
        bottom_shear = dynamic_viscosity_pa_s * (
            velocity[1] - velocity[0]
        ) / dz
        top_shear = dynamic_viscosity_pa_s * (
            velocity[-1] - velocity[-2]
        ) / dz
        max_wall_shear = max(max_wall_shear, abs(bottom_shear), abs(top_shear))

    pressure_force = 0.0
    max_equation_residual = 0.0
    dissipation = 0.0
    for index in range(count):
        west_radius = radial_faces[index]
        east_radius = radial_faces[index + 1]
        annulus_area = math.pi * (
            east_radius * east_radius - west_radius * west_radius
        )
        pressure_force += pressure[index] * annulus_area
        source = speed * 0.5 * (
            east_radius * east_radius - west_radius * west_radius
        )
        residual = (
            east_radius * radial_fluxes[index + 1]
            - west_radius * radial_fluxes[index]
            - source
        )
        max_equation_residual = max(max_equation_residual, abs(residual))
        average_dissipation_per_area = 0.5 * (
            face_dissipation_per_area[index]
            + face_dissipation_per_area[index + 1]
        )
        dissipation += average_dissipation_per_area * annulus_area

    outer_outflow = 2.0 * math.pi * radial_faces[-1] * radial_fluxes[-1]
    swept_rate = math.pi * radial_faces[-1] * radial_faces[-1] * speed
    balance_scale = max(abs(swept_rate), 1.0e-300)
    balance_residual = abs(outer_outflow - swept_rate) / balance_scale

    return ThinGapField(
        radial_faces_m=radial_faces,
        radial_centers_m=radial_centers,
        gap_at_faces_m=gap_faces,
        gap_at_centers_m=gap_centers,
        pressure_pa=pressure,
        radial_velocity_faces_m_s=tuple(velocity_profiles),
        closing_speed_m_s=speed,
        lower_wall_normal_velocity_m_s=0.5 * speed,
        upper_wall_normal_velocity_m_s=-0.5 * speed,
        pressure_force_n=float(pressure_force),
        center_pressure_pa=float(pressure[0] if pressure else 0.0),
        outer_radial_outflow_m3_s=float(outer_outflow),
        swept_gap_volume_rate_m3_s=float(swept_rate),
        mass_balance_relative_residual=float(balance_residual),
        max_pressure_equation_residual_m3_s=float(max_equation_residual),
        max_wall_slip_m_s=float(max_wall_slip),
        max_radial_velocity_m_s=float(max_velocity),
        max_wall_shear_pa=float(max_wall_shear),
        viscous_dissipation_w=float(dissipation),
    )


def coupled_cfd_response(
    geometry: GapGeometry,
    free_closing_speed_m_s: float,
    dynamic_viscosity_pa_s: float,
    settings: PrecontactCFDSettings | None = None,
) -> PrecontactCFDResponse:
    """Use numerically integrated CFD traction to modify the outer approach speed."""
    cfg = settings or PrecontactCFDSettings()
    cfg.validate()
    if dynamic_viscosity_pa_s <= 0.0:
        raise ValueError("ambient dynamic viscosity must be positive")
    free_speed = max(0.0, float(free_closing_speed_m_s))
    radius = float(geometry.effective_radius_m)
    gap = max(float(geometry.gap_m), cfg.minimum_gap_m)
    if radius <= 0.0:
        raise ValueError("effective gap radius must be positive")
    outer_resistance = (
        6.0 * math.pi * dynamic_viscosity_pa_s * radius * cfg.outer_drag_scale
    )
    characteristic_radius = math.sqrt(2.0 * radius * gap)
    active = (
        cfg.enabled
        and free_speed > 0.0
        and gap <= cfg.onset_gap_over_effective_radius * radius
    )
    if not active:
        return PrecontactCFDResponse(
            active=False,
            free_closing_speed_m_s=free_speed,
            coupled_closing_speed_m_s=free_speed,
            correction_speed_m_s=0.0,
            outer_resistance_n_s_m=outer_resistance,
            cfd_resistance_n_s_m=0.0,
            resistance_ratio=0.0,
            force_n=0.0,
            center_pressure_pa=0.0,
            characteristic_patch_radius_m=characteristic_radius,
            radial_outflow_m3_s=0.0,
            viscous_dissipation_w=0.0,
            field=None,
        )

    trial_field = solve_thin_gap_field(
        geometry,
        free_speed,
        dynamic_viscosity_pa_s,
        cfg,
    )
    cfd_resistance = trial_field.pressure_force_n / free_speed
    if cfd_resistance < 0.0:
        raise RuntimeError("resolved thin-gap traction has the wrong sign")
    coupled_speed = (
        free_speed * outer_resistance / (outer_resistance + cfd_resistance)
    )
    field = solve_thin_gap_field(
        geometry,
        coupled_speed,
        dynamic_viscosity_pa_s,
        cfg,
    )
    return PrecontactCFDResponse(
        active=True,
        free_closing_speed_m_s=free_speed,
        coupled_closing_speed_m_s=coupled_speed,
        correction_speed_m_s=free_speed - coupled_speed,
        outer_resistance_n_s_m=outer_resistance,
        cfd_resistance_n_s_m=cfd_resistance,
        resistance_ratio=cfd_resistance / outer_resistance,
        force_n=field.pressure_force_n,
        center_pressure_pa=field.center_pressure_pa,
        characteristic_patch_radius_m=characteristic_radius,
        radial_outflow_m3_s=field.outer_radial_outflow_m3_s,
        viscous_dissipation_w=field.viscous_dissipation_w,
        field=field,
    )


def taylor_reference_force_n(
    radius_m: float,
    gap_m: float,
    closing_speed_m_s: float,
    dynamic_viscosity_pa_s: float,
) -> float:
    """Closed-form validation reference; never used by the production CFD solve."""
    if radius_m <= 0.0 or gap_m <= 0.0 or dynamic_viscosity_pa_s <= 0.0:
        raise ValueError("reference radius, gap, and viscosity must be positive")
    if closing_speed_m_s < 0.0:
        raise ValueError("reference closing speed must be non-negative")
    return (
        6.0
        * math.pi
        * dynamic_viscosity_pa_s
        * radius_m
        * radius_m
        * closing_speed_m_s
        / gap_m
    )
