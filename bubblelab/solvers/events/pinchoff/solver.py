"""Restricted axisymmetric hydrodynamic neck-thinning foundation.

The model evolves the cross-sectional area A and axial velocity u of a slender
axisymmetric neck.  It uses the one-dimensional mass equation

    dA/dt + d(A u)/dz = 0

and the capillary/viscous momentum approximation

    du/dt + u du/dz = -(sigma/rho) d(kappa)/dz
                     + (3 mu / (rho A)) d(A du/dz)/dz,

with the full axisymmetric mean-curvature expression evaluated from the
radius r = sqrt(A/pi).  The implementation is intentionally restricted to a
single smooth axisymmetric neck.  The discrete no-flux boundary condition
makes cross-sectional volume conservation an algebraic property of the mass
update.

Topology is not changed inside this solver.  Integration stops when the neck
radius reaches a resolution-relative limit.  The singular time is estimated
from the dynamically evolved terminal radius trajectory; the limit controls
only where the resolved calculation hands off, not the reported pinch time.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import bisect
import hashlib
import json
import math
from typing import Iterable, Sequence

from bubblelab.solvers.events.fragmentation.geometry import TriMesh


@dataclass(frozen=True)
class PinchOffConfig:
    cell_count: int = 65
    patch_half_length_m: float = 1.5
    parent_half_length_m: float = 3.0
    base_radius_m: float = 1.0
    neck_depth: float = 0.75
    neck_width_m: float = 1.0
    density_kg_m3: float = 1.0
    dynamic_viscosity_pa_s: float = 0.1
    surface_tension_n_m: float = 1.0
    capillary_cfl: float = 0.08
    advection_cfl: float = 0.25
    viscous_cfl: float = 0.08
    positivity_cfl: float = 0.15
    resolution_stop_radius_cells: float = 1.60
    minimum_evolution_time_s: float = 0.05
    max_time_s: float = 4.0
    fit_samples: int = 50

    def __post_init__(self) -> None:
        if self.cell_count < 31 or self.cell_count % 2 == 0:
            raise ValueError("cell_count must be an odd integer >= 31")
        for name in (
            "patch_half_length_m", "parent_half_length_m", "base_radius_m",
            "neck_width_m", "density_kg_m3", "dynamic_viscosity_pa_s",
            "surface_tension_n_m", "capillary_cfl", "advection_cfl",
            "viscous_cfl", "positivity_cfl", "resolution_stop_radius_cells",
            "max_time_s",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if self.patch_half_length_m >= self.parent_half_length_m:
            raise ValueError("patch_half_length_m must lie inside the parent half length")
        if not 0.0 < self.neck_depth < 0.95:
            raise ValueError("neck_depth must lie in (0, 0.95)")
        if self.minimum_evolution_time_s < 0.0 or not math.isfinite(self.minimum_evolution_time_s):
            raise ValueError("minimum_evolution_time_s must be finite and non-negative")
        if self.fit_samples < 12:
            raise ValueError("fit_samples must be at least 12")

    @property
    def cell_width_m(self) -> float:
        return 2.0 * self.patch_half_length_m / self.cell_count

    def coordinates_m(self) -> tuple[float, ...]:
        dx = self.cell_width_m
        return tuple(-self.patch_half_length_m + (i + 0.5) * dx for i in range(self.cell_count))


@dataclass(frozen=True)
class PinchOffSample:
    time_s: float
    minimum_radius_m: float
    minimum_cell: int
    maximum_axial_speed_m_s: float
    volume_relative_error: float


@dataclass(frozen=True)
class PinchOffResult:
    coordinates_m: tuple[float, ...]
    initial_radius_m: tuple[float, ...]
    final_radius_m: tuple[float, ...]
    final_axial_velocity_m_s: tuple[float, ...]
    samples: tuple[PinchOffSample, ...]
    last_resolved_time_s: float
    pinch_time_s: float
    terminal_fit_slope_m_s: float
    initial_patch_volume_m3: float
    final_patch_volume_m3: float
    volume_relative_error: float
    cell_width_m: float
    resolution_stop_radius_m: float
    stop_reason: str
    solver_digest: str
    provenance: dict[str, object]

    @property
    def initial_minimum_radius_m(self) -> float:
        return min(self.initial_radius_m)

    @property
    def final_minimum_radius_m(self) -> float:
        return min(self.final_radius_m)


@dataclass(frozen=True)
class MeshProjection:
    mesh: TriMesh
    raw_volume_relative_error: float
    radial_volume_correction: float
    corrected_volume_relative_error: float


def initial_radius_profile(config: PinchOffConfig) -> tuple[float, ...]:
    radii: list[float] = []
    for x in config.coordinates_m():
        q = x / config.parent_half_length_m
        envelope = config.base_radius_m * math.sqrt(max(0.0, 1.0 - q * q))
        throat = 1.0 - config.neck_depth * math.exp(-((x / config.neck_width_m) ** 2))
        radius = envelope * throat
        if radius <= 0.0 or not math.isfinite(radius):
            raise ValueError("initial profile contains a non-positive radius")
        radii.append(radius)
    return tuple(radii)


def _derivatives(
    area: Sequence[float], velocity: Sequence[float], *, dx: float, rho: float, sigma: float, mu: float
) -> tuple[list[float], list[float], list[float]]:
    n = len(area)
    radius = [math.sqrt(max(value, 1.0e-300) / math.pi) for value in area]
    radius_z = [0.0] * n
    radius_zz = [0.0] * n
    for i in range(n):
        left = radius[i - 1] if i > 0 else radius[i]
        right = radius[i + 1] if i + 1 < n else radius[i]
        radius_z[i] = (right - left) / (2.0 * dx)
        radius_zz[i] = (right - 2.0 * radius[i] + left) / (dx * dx)
    curvature = [
        1.0 / (radius[i] * math.sqrt(1.0 + radius_z[i] * radius_z[i]))
        - radius_zz[i] / ((1.0 + radius_z[i] * radius_z[i]) ** 1.5)
        for i in range(n)
    ]
    pressure_gradient = [0.0] * n
    velocity_z = [0.0] * n
    for i in range(n):
        k_left = curvature[i - 1] if i > 0 else curvature[i]
        k_right = curvature[i + 1] if i + 1 < n else curvature[i]
        pressure_gradient[i] = sigma * (k_right - k_left) / (2.0 * dx)
        u_left = velocity[i - 1] if i > 0 else 0.0
        u_right = velocity[i + 1] if i + 1 < n else 0.0
        velocity_z[i] = (u_right - u_left) / (2.0 * dx)
    area_velocity_gradient = [area[i] * velocity_z[i] for i in range(n)]
    viscous_divergence = [0.0] * n
    for i in range(n):
        left = area_velocity_gradient[i - 1] if i > 0 else 0.0
        right = area_velocity_gradient[i + 1] if i + 1 < n else 0.0
        viscous_divergence[i] = (right - left) / (2.0 * dx)
    mass_flux = [0.0] * (n + 1)
    for face in range(1, n):
        mass_flux[face] = 0.25 * (area[face - 1] + area[face]) * (velocity[face - 1] + velocity[face])
    d_area = [-(mass_flux[i + 1] - mass_flux[i]) / dx for i in range(n)]
    d_velocity = [
        -velocity[i] * velocity_z[i]
        - pressure_gradient[i] / rho
        + (3.0 * mu / rho) * viscous_divergence[i] / max(area[i], 1.0e-300)
        for i in range(n)
    ]
    d_velocity[0] = 0.0
    d_velocity[-1] = 0.0
    return d_area, d_velocity, curvature


def _time_step(config: PinchOffConfig, area: Sequence[float], velocity: Sequence[float], d_area: Sequence[float]) -> float:
    dx = config.cell_width_m
    capillary = config.capillary_cfl * math.sqrt(config.density_kg_m3 * dx ** 3 / config.surface_tension_n_m)
    max_speed = max((abs(value) for value in velocity), default=0.0)
    advection = config.advection_cfl * dx / max(max_speed, 1.0e-12)
    kinematic_viscosity = config.dynamic_viscosity_pa_s / config.density_kg_m3
    viscous = config.viscous_cfl * dx * dx / kinematic_viscosity
    positivity = math.inf
    for value, derivative in zip(area, d_area):
        if derivative < 0.0:
            positivity = min(positivity, config.positivity_cfl * value / (-derivative))
    return min(capillary, advection, viscous, positivity)


def _terminal_zero_time(samples: Sequence[PinchOffSample], count: int) -> tuple[float, float]:
    tail = list(samples[-min(len(samples), count):])
    if len(tail) < 12:
        raise RuntimeError("insufficient terminal samples for pinch-time estimation")
    mean_t = math.fsum(sample.time_s for sample in tail) / len(tail)
    mean_r = math.fsum(sample.minimum_radius_m for sample in tail) / len(tail)
    variance = math.fsum((sample.time_s - mean_t) ** 2 for sample in tail)
    if variance <= 1.0e-300:
        raise RuntimeError("terminal time samples are degenerate")
    slope = math.fsum(
        (sample.time_s - mean_t) * (sample.minimum_radius_m - mean_r) for sample in tail
    ) / variance
    if slope >= 0.0 or not math.isfinite(slope):
        raise RuntimeError("terminal neck trajectory is not collapsing")
    intercept = mean_r - slope * mean_t
    pinch_time = -intercept / slope
    if not math.isfinite(pinch_time) or pinch_time <= tail[-1].time_s:
        raise RuntimeError("terminal trajectory does not yield a future singular time")
    return pinch_time, slope


def evolve_neck(config: PinchOffConfig | None = None) -> PinchOffResult:
    config = config or PinchOffConfig()
    coordinates = config.coordinates_m()
    initial_radius = initial_radius_profile(config)
    area = [math.pi * radius * radius for radius in initial_radius]
    velocity = [0.0] * config.cell_count
    dx = config.cell_width_m
    initial_volume = math.fsum(area) * dx
    stop_radius = config.resolution_stop_radius_cells * dx
    samples: list[PinchOffSample] = []
    time_s = 0.0
    stop_reason = "MAX_TIME_REACHED"
    while time_s < config.max_time_s:
        minimum_area = min(area)
        minimum_cell = area.index(minimum_area)
        minimum_radius = math.sqrt(minimum_area / math.pi)
        volume = math.fsum(area) * dx
        samples.append(PinchOffSample(
            time_s=time_s,
            minimum_radius_m=minimum_radius,
            minimum_cell=minimum_cell,
            maximum_axial_speed_m_s=max(abs(value) for value in velocity),
            volume_relative_error=abs(volume - initial_volume) / initial_volume,
        ))
        if minimum_radius <= stop_radius and time_s >= config.minimum_evolution_time_s:
            stop_reason = "RESOLUTION_LIMIT_REACHED"
            break
        d_area, d_velocity, _ = _derivatives(
            area, velocity, dx=dx, rho=config.density_kg_m3,
            sigma=config.surface_tension_n_m, mu=config.dynamic_viscosity_pa_s,
        )
        dt = min(_time_step(config, area, velocity, d_area), config.max_time_s - time_s)
        if not math.isfinite(dt) or dt <= 1.0e-14:
            raise RuntimeError("pinch-off time step collapsed before the supported resolution limit")
        area_stage = [value + dt * derivative for value, derivative in zip(area, d_area)]
        velocity_stage = [value + dt * derivative for value, derivative in zip(velocity, d_velocity)]
        if min(area_stage) <= 0.0:
            raise RuntimeError("predictor produced non-positive cross-sectional area")
        d_area_stage, d_velocity_stage, _ = _derivatives(
            area_stage, velocity_stage, dx=dx, rho=config.density_kg_m3,
            sigma=config.surface_tension_n_m, mu=config.dynamic_viscosity_pa_s,
        )
        next_area = [
            value + 0.5 * dt * (first + second)
            for value, first, second in zip(area, d_area, d_area_stage)
        ]
        next_velocity = [
            value + 0.5 * dt * (first + second)
            for value, first, second in zip(velocity, d_velocity, d_velocity_stage)
        ]
        if min(next_area) <= 0.0:
            raise RuntimeError("corrector produced non-positive cross-sectional area")
        area = next_area
        velocity = next_velocity
        time_s += dt
    if stop_reason != "RESOLUTION_LIMIT_REACHED":
        raise RuntimeError("neck did not reach the supported resolution-relative handoff limit")
    final_radius = tuple(math.sqrt(value / math.pi) for value in area)
    final_volume = math.fsum(area) * dx
    pinch_time, fit_slope = _terminal_zero_time(samples, config.fit_samples)
    digest_payload = {
        "config": asdict(config),
        "pinch_time": float(pinch_time).hex(),
        "final_radius": [float(value).hex() for value in final_radius],
        "final_velocity": [float(value).hex() for value in velocity],
    }
    digest = "sha256:" + hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    return PinchOffResult(
        coordinates_m=coordinates,
        initial_radius_m=initial_radius,
        final_radius_m=final_radius,
        final_axial_velocity_m_s=tuple(velocity),
        samples=tuple(samples),
        last_resolved_time_s=samples[-1].time_s,
        pinch_time_s=pinch_time,
        terminal_fit_slope_m_s=fit_slope,
        initial_patch_volume_m3=initial_volume,
        final_patch_volume_m3=final_volume,
        volume_relative_error=abs(final_volume - initial_volume) / initial_volume,
        cell_width_m=dx,
        resolution_stop_radius_m=stop_radius,
        stop_reason=stop_reason,
        solver_digest=digest,
        provenance={
            "solver": "axisymmetric-slender-neck",
            "version": "1.0.0",
            "equations": "1D_AREA_CONTINUITY_PLUS_CAPILLARY_VISCOUS_MOMENTUM",
            "space_discretization": "CELL_CENTERED_SECOND_ORDER_FINITE_DIFFERENCE_WITH_CONSERVATIVE_AREA_FLUX",
            "time_integration": "EXPLICIT_HEUN_RK2",
            "topology_handoff": "RESOLUTION_RELATIVE_STOP_WITH_DYNAMIC_ZERO_RADIUS_TIME_FIT",
            "supported_class": "SINGLE_SMOOTH_AXISYMMETRIC_NECK",
            "retracting_liquid_rim": "NOT_RESOLVED",
            "droplet_spray": "NOT_RESOLVED",
        },
    )


def _interpolated_ratio(x: float, result: PinchOffResult, patch_half_length_m: float) -> float:
    coordinates = result.coordinates_m
    ratios = tuple(final / initial for final, initial in zip(result.final_radius_m, result.initial_radius_m))
    if x <= -patch_half_length_m or x >= patch_half_length_m:
        return 1.0
    if x <= coordinates[0]:
        fraction = (x + patch_half_length_m) / (coordinates[0] + patch_half_length_m)
        return 1.0 + fraction * (ratios[0] - 1.0)
    if x >= coordinates[-1]:
        fraction = (patch_half_length_m - x) / (patch_half_length_m - coordinates[-1])
        return 1.0 + fraction * (ratios[-1] - 1.0)
    index = bisect.bisect_right(coordinates, x) - 1
    fraction = (x - coordinates[index]) / (coordinates[index + 1] - coordinates[index])
    return ratios[index] + fraction * (ratios[index + 1] - ratios[index])


def deform_x_axisymmetric_mesh(
    mesh: TriMesh, result: PinchOffResult, *, patch_half_length_m: float
) -> MeshProjection:
    """Project the evolved radius field onto an x-axis surface-of-revolution mesh.

    The local radial deformation is followed by one deterministic global radial
    correction.  Because x is unchanged, uniform radial scaling changes enclosed
    volume quadratically, so the correction restores the parent represented
    volume without moving the axial split location.
    """
    target_volume = mesh.volume()
    deformed_vertices = []
    for x, y, z in mesh.vertices:
        ratio = _interpolated_ratio(x, result, patch_half_length_m)
        deformed_vertices.append((x, y * ratio, z * ratio))
    raw = TriMesh(tuple(deformed_vertices), mesh.faces).reoriented_outward()
    raw_volume = raw.volume()
    if raw_volume <= 0.0:
        raise RuntimeError("deformed parent mesh has non-positive represented volume")
    raw_error = abs(raw_volume - target_volume) / target_volume
    correction = math.sqrt(target_volume / raw_volume)
    corrected_vertices = tuple((x, y * correction, z * correction) for x, y, z in raw.vertices)
    corrected = TriMesh(corrected_vertices, raw.faces).reoriented_outward()
    corrected_error = abs(corrected.volume() - target_volume) / target_volume
    if not corrected.is_closed_manifold():
        raise RuntimeError("pinch-off mesh projection broke parent manifold closure")
    return MeshProjection(corrected, raw_error, correction, corrected_error)
