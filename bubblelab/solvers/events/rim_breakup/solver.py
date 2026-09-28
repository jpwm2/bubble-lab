from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Sequence

_TWO_PI = 2.0 * math.pi


@dataclass(frozen=True)
class RimBreakupConfig:
    azimuthal_cells: int = 160
    outer_radius_m: float = 1.0
    initial_hole_radius_m: float = 0.1
    film_thickness_m: float = 1.0e-3
    density_kg_m3: float = 1.0
    dynamic_viscosity_pa_s: float = 1.0e-5
    surface_tension_n_m: float = 5.0e-4
    azimuthal_mode: int = 10
    initial_radius_perturbation_fraction: float = 0.03
    rim_drag_coefficient: float = 1.0
    time_step_s: float = 1.0e-4
    max_time_s: float = 0.5
    ligament_amplitude_fraction: float = 0.10
    detachment_neck_radius_ratio: float = 0.50

    def __post_init__(self) -> None:
        if self.azimuthal_cells < 48 or self.azimuthal_cells % 2:
            raise ValueError("azimuthal_cells must be an even integer >= 48")
        if self.azimuthal_cells % self.azimuthal_mode:
            raise ValueError("azimuthal_cells must be divisible by azimuthal_mode")
        if self.azimuthal_mode < 2:
            raise ValueError("azimuthal_mode must be >= 2")
        for name in (
            "outer_radius_m", "initial_hole_radius_m", "film_thickness_m",
            "density_kg_m3", "surface_tension_n_m", "time_step_s", "max_time_s",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if not 0.0 < self.initial_hole_radius_m < self.outer_radius_m:
            raise ValueError("initial_hole_radius_m must lie inside outer_radius_m")
        if self.dynamic_viscosity_pa_s < 0.0 or not math.isfinite(self.dynamic_viscosity_pa_s):
            raise ValueError("dynamic_viscosity_pa_s must be finite and non-negative")
        if self.rim_drag_coefficient < 0.0 or not math.isfinite(self.rim_drag_coefficient):
            raise ValueError("rim_drag_coefficient must be finite and non-negative")
        if not 0.0 < self.initial_radius_perturbation_fraction < 0.2:
            raise ValueError("initial_radius_perturbation_fraction must lie in (0, 0.2)")
        if not self.initial_radius_perturbation_fraction < self.ligament_amplitude_fraction < 0.9:
            raise ValueError("ligament_amplitude_fraction must exceed the initial perturbation")
        if not 0.0 < self.detachment_neck_radius_ratio < 1.0:
            raise ValueError("detachment_neck_radius_ratio must lie in (0, 1)")

    @property
    def dtheta(self) -> float:
        return _TWO_PI / self.azimuthal_cells

    @property
    def taylor_culick_speed_m_s(self) -> float:
        return math.sqrt(2.0 * self.surface_tension_n_m / (self.density_kg_m3 * self.film_thickness_m))


@dataclass(frozen=True)
class RimSample:
    time_s: float
    hole_radius_m: float
    retraction_speed_m_s: float
    mean_tube_radius_m: float
    minimum_tube_radius_m: float
    maximum_tube_radius_m: float
    mode_amplitude_fraction: float
    neck_radius_ratio: float
    liquid_volume_relative_error: float


@dataclass(frozen=True)
class DetachedDroplet:
    id: str
    volume_m3: float
    mass_kg: float
    equivalent_radius_m: float
    centroid_angle_rad: float
    velocity_m_s: tuple[float, float]
    momentum_kg_m_s: tuple[float, float]
    source_start_cell: int
    source_end_cell: int


@dataclass(frozen=True)
class RimBreakupResult:
    config: RimBreakupConfig
    samples: tuple[RimSample, ...]
    ligament_onset_time_s: float
    detachment_time_s: float
    final_hole_radius_m: float
    final_retraction_speed_m_s: float
    final_volume_per_radian_m3: tuple[float, ...]
    final_tangential_velocity_m_s: tuple[float, ...]
    droplets: tuple[DetachedDroplet, ...]
    initial_liquid_volume_m3: float
    remaining_film_volume_m3: float
    pre_detachment_rim_volume_m3: float
    droplet_volume_m3: float
    liquid_volume_relative_error: float
    scalar_radial_momentum_kg_m_s: float
    capillary_impulse_n_s: float
    viscous_impulse_n_s: float
    radial_momentum_residual_kg_m_s: float
    initial_surface_energy_j: float
    final_surface_energy_j: float
    kinetic_energy_j: float
    surface_plus_kinetic_change_j: float
    solver_digest: str
    provenance: dict[str, object]


@dataclass
class _State:
    time_s: float
    hole_radius_m: float
    radial_momentum_kg_m_s: float
    deviations_m3_per_rad: list[float]
    tangential_velocity_m_s: list[float]
    capillary_impulse_n_s: float
    viscous_impulse_n_s: float


def _rp_growth_rate(config: RimBreakupConfig, hole_radius_m: float, tube_radius_m: float) -> float:
    q = config.azimuthal_mode * tube_radius_m / hole_radius_m
    if q <= 0.0 or q >= 1.0:
        return 0.0
    return math.sqrt(
        config.surface_tension_n_m
        / (2.0 * config.density_kg_m3 * tube_radius_m ** 3)
        * q * q * (1.0 - q * q)
    )


def rayleigh_plateau_reference(config: RimBreakupConfig | None = None) -> dict[str, float]:
    config = config or RimBreakupConfig()
    a = config.initial_hole_radius_m
    mean_area = 0.5 * a * config.film_thickness_m
    b = math.sqrt(mean_area / math.pi)
    q = config.azimuthal_mode * b / a
    return {
        "mean_tube_radius_m": b,
        "dimensionless_wavenumber": q,
        "growth_rate_s_inv": _rp_growth_rate(config, a, b),
    }


def _initial_state(config: RimBreakupConfig) -> _State:
    a = config.initial_hole_radius_m
    mean_w = 0.5 * a * a * config.film_thickness_m
    raw = [
        math.cos(config.azimuthal_mode * (i + 0.5) * config.dtheta)
        for i in range(config.azimuthal_cells)
    ]
    raw_mean = math.fsum(raw) / config.azimuthal_cells
    deviations = [
        2.0 * mean_w * config.initial_radius_perturbation_fraction * (value - raw_mean)
        for value in raw
    ]
    deviations[-1] = -math.fsum(deviations[:-1])
    omega = rayleigh_plateau_reference(config)["growth_rate_s_inv"]
    tangential = [
        -2.0 * a * omega * config.initial_radius_perturbation_fraction / config.azimuthal_mode
        * math.sin(config.azimuthal_mode * (i + 0.5) * config.dtheta)
        for i in range(config.azimuthal_cells)
    ]
    return _State(0.0, a, 0.0, deviations, tangential, 0.0, 0.0)


def _geometry(state: _State, config: RimBreakupConfig) -> tuple[list[float], list[float], list[float], float, float]:
    a = state.hole_radius_m
    mean_w = 0.5 * a * a * config.film_thickness_m
    w = [mean_w + value for value in state.deviations_m3_per_rad]
    if min(w) <= 0.0:
        raise RuntimeError("rim cross-sectional volume became non-positive")
    areas = [value / a for value in w]
    radii = [math.sqrt(value / math.pi) for value in areas]
    mean_radius = math.fsum(radii) / len(radii)
    amplitude = (max(radii) - min(radii)) / (2.0 * mean_radius)
    return w, areas, radii, mean_radius, amplitude


def _liquid_volume(state: _State, config: RimBreakupConfig) -> tuple[float, float, float]:
    w, _, _, _, _ = _geometry(state, config)
    film = math.pi * (config.outer_radius_m ** 2 - state.hole_radius_m ** 2) * config.film_thickness_m
    rim = math.fsum(w) * config.dtheta
    return film + rim, film, rim


def _derivatives(state: _State, config: RimBreakupConfig):
    a = state.hole_radius_m
    w, _, radii, _, _ = _geometry(state, config)
    rim_mass = config.density_kg_m3 * math.pi * a * a * config.film_thickness_m
    radial_speed = state.radial_momentum_kg_m_s / rim_mass
    capillary_force = 4.0 * math.pi * config.surface_tension_n_m * a
    viscous_force = 2.0 * math.pi * config.rim_drag_coefficient * config.dynamic_viscosity_pa_s * a * radial_speed

    curvature: list[float] = []
    dtheta = config.dtheta
    for i, radius in enumerate(radii):
        second_theta = (radii[(i + 1) % len(radii)] - 2.0 * radius + radii[(i - 1) % len(radii)]) / (dtheta * dtheta)
        curvature.append(1.0 / radius - second_theta / (a * a))

    volume_flux = [w_i * u_i / a for w_i, u_i in zip(w, state.tangential_velocity_m_s)]
    dev_dot: list[float] = []
    u_dot: list[float] = []
    nu = 3.0 * config.dynamic_viscosity_pa_s / config.density_kg_m3
    for i, u_i in enumerate(state.tangential_velocity_m_s):
        im = (i - 1) % len(w)
        ip = (i + 1) % len(w)
        flux_right = 0.5 * (volume_flux[i] + volume_flux[ip])
        flux_left = 0.5 * (volume_flux[im] + volume_flux[i])
        dev_dot.append(-(flux_right - flux_left) / dtheta)
        du_dtheta = (state.tangential_velocity_m_s[ip] - state.tangential_velocity_m_s[im]) / (2.0 * dtheta)
        dkappa_dtheta = (curvature[ip] - curvature[im]) / (2.0 * dtheta)
        d2u_dtheta2 = (state.tangential_velocity_m_s[ip] - 2.0 * u_i + state.tangential_velocity_m_s[im]) / (dtheta * dtheta)
        u_dot.append(
            -(u_i / a) * du_dtheta
            - (config.surface_tension_n_m / (config.density_kg_m3 * a)) * dkappa_dtheta
            + nu * d2u_dtheta2 / (a * a)
        )
    return radial_speed, capillary_force - viscous_force, dev_dot, u_dot, capillary_force, viscous_force


def _advance(state: _State, config: RimBreakupConfig, dt: float) -> _State:
    k1 = _derivatives(state, config)
    predictor = _State(
        time_s=state.time_s + dt,
        hole_radius_m=state.hole_radius_m + dt * k1[0],
        radial_momentum_kg_m_s=state.radial_momentum_kg_m_s + dt * k1[1],
        deviations_m3_per_rad=[value + dt * derivative for value, derivative in zip(state.deviations_m3_per_rad, k1[2])],
        tangential_velocity_m_s=[value + dt * derivative for value, derivative in zip(state.tangential_velocity_m_s, k1[3])],
        capillary_impulse_n_s=state.capillary_impulse_n_s + dt * k1[4],
        viscous_impulse_n_s=state.viscous_impulse_n_s + dt * k1[5],
    )
    k2 = _derivatives(predictor, config)
    return _State(
        time_s=state.time_s + dt,
        hole_radius_m=state.hole_radius_m + 0.5 * dt * (k1[0] + k2[0]),
        radial_momentum_kg_m_s=state.radial_momentum_kg_m_s + 0.5 * dt * (k1[1] + k2[1]),
        deviations_m3_per_rad=[
            value + 0.5 * dt * (first + second)
            for value, first, second in zip(state.deviations_m3_per_rad, k1[2], k2[2])
        ],
        tangential_velocity_m_s=[
            value + 0.5 * dt * (first + second)
            for value, first, second in zip(state.tangential_velocity_m_s, k1[3], k2[3])
        ],
        capillary_impulse_n_s=state.capillary_impulse_n_s + 0.5 * dt * (k1[4] + k2[4]),
        viscous_impulse_n_s=state.viscous_impulse_n_s + 0.5 * dt * (k1[5] + k2[5]),
    )


def _sample(state: _State, config: RimBreakupConfig, initial_volume: float) -> RimSample:
    liquid, _, _ = _liquid_volume(state, config)
    _, _, radii, mean_radius, amplitude = _geometry(state, config)
    rim_mass = config.density_kg_m3 * math.pi * state.hole_radius_m ** 2 * config.film_thickness_m
    return RimSample(
        time_s=state.time_s,
        hole_radius_m=state.hole_radius_m,
        retraction_speed_m_s=state.radial_momentum_kg_m_s / rim_mass,
        mean_tube_radius_m=mean_radius,
        minimum_tube_radius_m=min(radii),
        maximum_tube_radius_m=max(radii),
        mode_amplitude_fraction=amplitude,
        neck_radius_ratio=min(radii) / mean_radius,
        liquid_volume_relative_error=abs(liquid - initial_volume) / initial_volume,
    )


def _segment_indices(start_min: int, end_min: int, count: int) -> list[int]:
    out: list[int] = []
    i = (start_min + 1) % count
    while i != end_min:
        out.append(i)
        i = (i + 1) % count
        if len(out) > count:
            raise RuntimeError("failed to traverse detached segment")
    return out


def _droplets(state: _State, config: RimBreakupConfig, solver_digest_seed: str) -> tuple[DetachedDroplet, ...]:
    w, _, radii, _, _ = _geometry(state, config)
    cells_per_wave = config.azimuthal_cells // config.azimuthal_mode
    minima = []
    for wave in range(config.azimuthal_mode):
        lo = wave * cells_per_wave
        hi = lo + cells_per_wave
        minima.append(min(range(lo, hi), key=lambda i: radii[i]))
    minima.sort()
    dtheta = config.dtheta
    rim_mass = config.density_kg_m3 * math.pi * state.hole_radius_m ** 2 * config.film_thickness_m
    radial_speed = state.radial_momentum_kg_m_s / rim_mass
    droplets: list[DetachedDroplet] = []
    for order, start in enumerate(minima):
        end = minima[(order + 1) % len(minima)]
        indices = _segment_indices(start, end, config.azimuthal_cells)
        weighted = [(start, 0.5), *[(i, 1.0) for i in indices], (end, 0.5)]
        volume = math.fsum(w[i] * dtheta * weight for i, weight in weighted)
        mass = config.density_kg_m3 * volume
        cx = math.fsum(math.cos((i + 0.5) * dtheta) * w[i] * weight for i, weight in weighted)
        cy = math.fsum(math.sin((i + 0.5) * dtheta) * w[i] * weight for i, weight in weighted)
        angle = math.atan2(cy, cx) % _TWO_PI
        px = 0.0
        py = 0.0
        for i, weight in weighted:
            theta = (i + 0.5) * dtheta
            cell_mass = config.density_kg_m3 * w[i] * dtheta * weight
            u = state.tangential_velocity_m_s[i]
            vx = radial_speed * math.cos(theta) - u * math.sin(theta)
            vy = radial_speed * math.sin(theta) + u * math.cos(theta)
            px += cell_mass * vx
            py += cell_mass * vy
        velocity = (px / mass, py / mass)
        suffix = hashlib.sha256(f"{solver_digest_seed}:{order}:{start}:{end}".encode("ascii")).hexdigest()[:16]
        droplets.append(DetachedDroplet(
            id=f"rim-drop-{order:02d}-{suffix}",
            volume_m3=volume,
            mass_kg=mass,
            equivalent_radius_m=(3.0 * volume / (4.0 * math.pi)) ** (1.0 / 3.0),
            centroid_angle_rad=angle,
            velocity_m_s=velocity,
            momentum_kg_m_s=(px, py),
            source_start_cell=start,
            source_end_cell=end,
        ))
    return tuple(droplets)


def _surface_energy(state: _State, config: RimBreakupConfig) -> float:
    _, _, radii, _, _ = _geometry(state, config)
    remaining_film_area = 2.0 * math.pi * (config.outer_radius_m ** 2 - state.hole_radius_m ** 2)
    rim_area = math.fsum(_TWO_PI * radius * state.hole_radius_m * config.dtheta for radius in radii)
    return config.surface_tension_n_m * (remaining_film_area + rim_area)


def evolve_rim_breakup(config: RimBreakupConfig | None = None) -> RimBreakupResult:
    config = config or RimBreakupConfig()
    state = _initial_state(config)
    initial_volume = math.pi * config.outer_radius_m ** 2 * config.film_thickness_m
    initial_energy = _surface_energy(state, config)
    samples: list[RimSample] = []
    ligament_onset: float | None = None
    while state.time_s <= config.max_time_s + 0.5 * config.time_step_s:
        sample = _sample(state, config, initial_volume)
        samples.append(sample)
        if ligament_onset is None and sample.mode_amplitude_fraction >= config.ligament_amplitude_fraction:
            ligament_onset = state.time_s
        if ligament_onset is not None and sample.neck_radius_ratio <= config.detachment_neck_radius_ratio:
            break
        if state.hole_radius_m >= 0.98 * config.outer_radius_m:
            raise RuntimeError("film exhausted before the instability reached detachment")
        if state.time_s >= config.max_time_s:
            raise RuntimeError("rim instability did not reach detachment before max_time_s")
        state = _advance(state, config, min(config.time_step_s, config.max_time_s - state.time_s))
    if ligament_onset is None:
        raise RuntimeError("rim instability did not reach the ligament threshold")

    w, _, _, _, _ = _geometry(state, config)
    pre_rim_volume = math.fsum(w) * config.dtheta
    digest_payload = {
        "config": asdict(config),
        "detachment_time_s": float(state.time_s).hex(),
        "hole_radius_m": float(state.hole_radius_m).hex(),
        "w": [float(value).hex() for value in w],
        "u": [float(value).hex() for value in state.tangential_velocity_m_s],
    }
    digest = "sha256:" + hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    droplets = _droplets(state, config, digest)
    droplet_volume = math.fsum(drop.volume_m3 for drop in droplets)
    _, remaining_film, _ = _liquid_volume(state, config)
    volume_error = abs(remaining_film + droplet_volume - initial_volume) / initial_volume

    kinetic = 0.0
    dtheta = config.dtheta
    rim_mass = config.density_kg_m3 * math.pi * state.hole_radius_m ** 2 * config.film_thickness_m
    radial_speed = state.radial_momentum_kg_m_s / rim_mass
    for w_i, u_i in zip(w, state.tangential_velocity_m_s):
        cell_mass = config.density_kg_m3 * w_i * dtheta
        kinetic += 0.5 * cell_mass * (radial_speed ** 2 + u_i ** 2)
    final_energy = config.surface_tension_n_m * (
        2.0 * math.pi * (config.outer_radius_m ** 2 - state.hole_radius_m ** 2)
        + math.fsum(4.0 * math.pi * drop.equivalent_radius_m ** 2 for drop in droplets)
    )
    momentum_residual = state.radial_momentum_kg_m_s - (state.capillary_impulse_n_s - state.viscous_impulse_n_s)
    return RimBreakupResult(
        config=config,
        samples=tuple(samples),
        ligament_onset_time_s=ligament_onset,
        detachment_time_s=state.time_s,
        final_hole_radius_m=state.hole_radius_m,
        final_retraction_speed_m_s=radial_speed,
        final_volume_per_radian_m3=tuple(w),
        final_tangential_velocity_m_s=tuple(state.tangential_velocity_m_s),
        droplets=droplets,
        initial_liquid_volume_m3=initial_volume,
        remaining_film_volume_m3=remaining_film,
        pre_detachment_rim_volume_m3=pre_rim_volume,
        droplet_volume_m3=droplet_volume,
        liquid_volume_relative_error=volume_error,
        scalar_radial_momentum_kg_m_s=state.radial_momentum_kg_m_s,
        capillary_impulse_n_s=state.capillary_impulse_n_s,
        viscous_impulse_n_s=state.viscous_impulse_n_s,
        radial_momentum_residual_kg_m_s=momentum_residual,
        initial_surface_energy_j=initial_energy,
        final_surface_energy_j=final_energy,
        kinetic_energy_j=kinetic,
        surface_plus_kinetic_change_j=(final_energy + kinetic) - initial_energy,
        solver_digest=digest,
        provenance={
            "solver": "expanding-toroidal-rim-slender-jet",
            "version": "1.0.0",
            "requirements": ["R16", "R31", "R32", "R33"],
            "radial_dynamics": "VARIABLE_MASS_CAPILLARY_MOMENTUM_WITH_VISCOUS_DRAG",
            "azimuthal_dynamics": "CONSERVATIVE_SLENDER_JET_VOLUME_PLUS_CAPILLARY_VISCOUS_MOMENTUM",
            "instability_reference": "LONG_WAVE_RAYLEIGH_PLATEAU",
            "detachment": "DYNAMIC_NECK_RATIO_THRESHOLD_ON_EVOLVED_RIM_STATE",
            "droplet_volume": "FINITE_VOLUME_PARTITION_BETWEEN_EVOLVED_NECK_MINIMA",
            "supported_class": "ONE_CIRCULAR_THIN_FILM_HOLE_ONE_AZIMUTHAL_MODE",
            "arbitrary_3d_multi_hole_rupture": "UNSUPPORTED",
            "spray_distribution": "UNSUPPORTED",
            "turbulent_atomization": "UNSUPPORTED",
        },
    )
