from __future__ import annotations
from dataclasses import asdict, dataclass, replace
import hashlib, json, math

TWO_PI = 2.0 * math.pi

@dataclass(frozen=True)
class MultiHoleRimBreakupConfig:
    azimuthal_cells: int = 192
    outer_radius_m: float = 1.0
    hole_center_distance_m: float = 0.40
    initial_hole_radii_m: tuple[float, float] = (0.075, 0.065)
    film_thickness_m: float = 1e-3
    density_kg_m3: float = 1.0
    dynamic_viscosity_pa_s: float = 1e-5
    surface_tension_n_m: float = 5e-4
    hole_modes: tuple[tuple[int, ...], tuple[int, ...]] = ((7, 10), (8, 11))
    hole_amplitudes: tuple[tuple[float, ...], tuple[float, ...]] = ((0.042, 0.030), (0.036, 0.027))
    hole_phases_rad: tuple[tuple[float, ...], tuple[float, ...]] = ((0.25, 1.10), (0.70, 1.65))
    interaction_range_m: float = 0.22
    interaction_strength: float = 1.0
    bridge_target_fraction: float = 0.44
    bridge_sigma_rad: float = 0.40
    exchange_limit_fraction: float = 0.08
    time_step_s: float = 2e-4
    max_time_s: float = 0.30
    ligament_amplitude_fraction: float = 0.16
    detachment_neck_radius_ratio: float = 0.50
    partition_neck_radius_ratio: float = 0.90

    def __post_init__(self):
        if self.azimuthal_cells < 96 or self.azimuthal_cells % 2:
            raise ValueError('azimuthal_cells must be even and >=96')
        if len(self.initial_hole_radii_m) != 2 or any(r <= 0 for r in self.initial_hole_radii_m):
            raise ValueError('exactly two positive initial hole radii are required')
        if self.hole_center_distance_m <= sum(self.initial_hole_radii_m):
            raise ValueError('initial holes must be distinct')
        if self.outer_radius_m <= self.hole_center_distance_m / 2 + max(self.initial_hole_radii_m):
            raise ValueError('initial holes must lie inside the film domain')
        for name in ('outer_radius_m','hole_center_distance_m','film_thickness_m','density_kg_m3','surface_tension_n_m','interaction_range_m','time_step_s','max_time_s'):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0:
                raise ValueError(name)
        if self.dynamic_viscosity_pa_s < 0 or not math.isfinite(self.dynamic_viscosity_pa_s):
            raise ValueError('dynamic_viscosity_pa_s')
        if not 0.0 <= self.interaction_strength <= 2.0:
            raise ValueError('interaction_strength')
        if not 0.0 < self.bridge_target_fraction < 0.7:
            raise ValueError('bridge_target_fraction')
        if not 0.1 <= self.bridge_sigma_rad <= 1.2:
            raise ValueError('bridge_sigma_rad')
        if not 0.0 <= self.exchange_limit_fraction < 0.2:
            raise ValueError('exchange_limit_fraction')
        if len(self.hole_modes) != 2 or len(self.hole_amplitudes) != 2 or len(self.hole_phases_rad) != 2:
            raise ValueError('two rim disturbance specifications are required')
        for modes, amplitudes, phases in zip(self.hole_modes, self.hole_amplitudes, self.hole_phases_rad):
            if len(modes) < 2 or len(set(modes)) != len(modes):
                raise ValueError('each hole must carry at least two distinct modes')
            if len(amplitudes) != len(modes) or len(phases) != len(modes):
                raise ValueError('mode tuple mismatch')
            if any(m < 2 or m >= self.azimuthal_cells // 3 for m in modes):
                raise ValueError('mode out of supported band')
            if any(a <= 0 or a >= 0.12 for a in amplitudes):
                raise ValueError('bad disturbance amplitude')
        if not 0 < self.detachment_neck_radius_ratio < self.partition_neck_radius_ratio < 1:
            raise ValueError('neck thresholds')
        if not 0 < self.ligament_amplitude_fraction < 0.8:
            raise ValueError('ligament threshold')

    @property
    def dtheta(self) -> float:
        return TWO_PI / self.azimuthal_cells

    @property
    def taylor_culick_speed_m_s(self) -> float:
        return math.sqrt(2 * self.surface_tension_n_m / (self.density_kg_m3 * self.film_thickness_m))

@dataclass(frozen=True)
class MultiHoleSample:
    time_s: float
    hole_radii_m: tuple[float, float]
    retraction_speeds_m_s: tuple[float, float]
    gap_m: float
    interaction_proximity: float
    bridge_fraction: float
    exchange_fraction: float
    hole_neck_radius_ratios: tuple[float, float]
    hole_total_amplitude_fractions: tuple[float, float]
    hole_mode_amplitudes: tuple[tuple[tuple[int, float], ...], tuple[tuple[int, float], ...]]
    liquid_volume_relative_error: float

@dataclass(frozen=True)
class MultiHoleDroplet:
    id: str
    source_hole: int
    volume_m3: float
    mass_kg: float
    equivalent_radius_m: float
    centroid_angle_rad: float
    position_m: tuple[float, float]
    velocity_m_s: tuple[float, float]
    momentum_kg_m_s: tuple[float, float]
    source_start_cell: int
    source_end_cell: int

@dataclass(frozen=True)
class MultiHoleResult:
    config: MultiHoleRimBreakupConfig
    samples: tuple[MultiHoleSample, ...]
    interaction_onset_time_s: float
    ligament_onset_time_s: float
    detachment_time_s: float
    final_hole_radii_m: tuple[float, float]
    final_retraction_speeds_m_s: tuple[float, float]
    final_gap_m: float
    final_rim_volume_m3: tuple[float, float]
    initial_mode_amplitudes: tuple[tuple[tuple[int, float], ...], tuple[tuple[int, float], ...]]
    final_mode_amplitudes: tuple[tuple[tuple[int, float], ...], tuple[tuple[int, float], ...]]
    neck_cells: tuple[tuple[int, ...], tuple[int, ...]]
    droplets: tuple[MultiHoleDroplet, ...]
    initial_liquid_volume_m3: float
    remaining_film_volume_m3: float
    pre_detachment_rim_volume_m3: float
    droplet_volume_m3: float
    liquid_volume_relative_error: float
    solver_digest: str
    provenance: dict[str, object]

@dataclass
class _State:
    time_s: float
    hole_radii_m: list[float]
    retraction_speeds_m_s: list[float]
    amplitudes: list[list[float]]
    bridge_fraction: float
    exchange_fraction: float


def _union_area(r1: float, r2: float, distance: float) -> float:
    if distance >= r1 + r2:
        return math.pi * (r1 * r1 + r2 * r2)
    if distance <= abs(r1 - r2):
        return math.pi * max(r1, r2) ** 2
    a1 = math.acos(max(-1.0, min(1.0, (distance * distance + r1 * r1 - r2 * r2) / (2 * distance * r1))))
    a2 = math.acos(max(-1.0, min(1.0, (distance * distance + r2 * r2 - r1 * r1) / (2 * distance * r2))))
    radicand = max(0.0, (-distance + r1 + r2) * (distance + r1 - r2) * (distance - r1 + r2) * (distance + r1 + r2))
    overlap = r1 * r1 * a1 + r2 * r2 * a2 - 0.5 * math.sqrt(radicand)
    return math.pi * (r1 * r1 + r2 * r2) - overlap


def _interaction(st: _State, cfg: MultiHoleRimBreakupConfig) -> tuple[float, float]:
    gap = cfg.hole_center_distance_m - st.hole_radii_m[0] - st.hole_radii_m[1]
    x = max(0.0, min(1.0, (cfg.interaction_range_m - gap) / cfg.interaction_range_m))
    return x * x * (3.0 - 2.0 * x), gap


def _rim_partition(st: _State, cfg: MultiHoleRimBreakupConfig) -> tuple[float, tuple[float, float]]:
    union = _union_area(st.hole_radii_m[0], st.hole_radii_m[1], cfg.hole_center_distance_m)
    total = union * cfg.film_thickness_m
    weights = [r * r for r in st.hole_radii_m]
    base0 = total * weights[0] / math.fsum(weights)
    bounded_exchange = max(-cfg.exchange_limit_fraction, min(cfg.exchange_limit_fraction, st.exchange_fraction))
    v0 = base0 + bounded_exchange * total
    v1 = total - v0
    if min(v0, v1) <= 0:
        raise RuntimeError('rim partition became non-positive')
    return total, (v0, v1)


def _mean_tube_radii(st: _State, cfg: MultiHoleRimBreakupConfig) -> tuple[float, float]:
    _, volumes = _rim_partition(st, cfg)
    return tuple(math.sqrt(volume / (2.0 * math.pi * math.pi * radius)) for volume, radius in zip(volumes, st.hole_radii_m))


def _rp_rate(cfg: MultiHoleRimBreakupConfig, mode: int, hole_radius: float, tube_radius: float) -> float:
    q = mode * tube_radius / hole_radius
    if q <= 0 or q >= 1:
        return 0.0
    inviscid = math.sqrt(cfg.surface_tension_n_m / (2 * cfg.density_kg_m3 * tube_radius ** 3) * q * q * (1 - q * q))
    nu = cfg.dynamic_viscosity_pa_s / cfg.density_kg_m3
    damping = 8.0 * nu * (mode / hole_radius) ** 2
    return max(0.0, inviscid - damping)


def _raw_shape(st: _State, cfg: MultiHoleRimBreakupConfig, hole: int) -> list[float]:
    face = 0.0 if hole == 0 else math.pi
    gaussians = []
    base = []
    for i in range(cfg.azimuthal_cells):
        theta = (i + 0.5) * cfg.dtheta
        delta = (theta - face + math.pi) % TWO_PI - math.pi
        g = math.exp(-0.5 * (delta / cfg.bridge_sigma_rad) ** 2)
        gaussians.append(g)
        modal = math.fsum(a * math.cos(m * theta + phase) for a, m, phase in zip(st.amplitudes[hole], cfg.hole_modes[hole], cfg.hole_phases_rad[hole]))
        base.append(1.0 + modal)
    mean_g = math.fsum(gaussians) / len(gaussians)
    shape = [v + cfg.interaction_strength * st.bridge_fraction * (mean_g - g) for v, g in zip(base, gaussians)]
    if min(shape) <= 0.08:
        raise RuntimeError('interacting rim profile collapsed outside the supported reduced class')
    return shape


def _tube_radii(st: _State, cfg: MultiHoleRimBreakupConfig, hole: int) -> tuple[float, ...]:
    _, volumes = _rim_partition(st, cfg)
    shape = _raw_shape(st, cfg, hole)
    denom = math.pi * st.hole_radii_m[hole] * cfg.dtheta * math.fsum(s * s for s in shape)
    scale = math.sqrt(volumes[hole] / denom)
    return tuple(scale * s for s in shape)


def _mode_amplitudes(radii: tuple[float, ...], modes: tuple[int, ...], cfg: MultiHoleRimBreakupConfig) -> tuple[tuple[int, float], ...]:
    mean = math.fsum(radii) / len(radii)
    normalized = [r / mean - 1.0 for r in radii]
    out = []
    for mode in modes:
        c = 2.0 / len(radii) * math.fsum(v * math.cos(mode * (i + 0.5) * cfg.dtheta) for i, v in enumerate(normalized))
        s = 2.0 / len(radii) * math.fsum(v * math.sin(mode * (i + 0.5) * cfg.dtheta) for i, v in enumerate(normalized))
        out.append((mode, math.hypot(c, s)))
    return tuple(out)


def _hole_diagnostics(st: _State, cfg: MultiHoleRimBreakupConfig, hole: int) -> tuple[float, float, tuple[tuple[int, float], ...]]:
    radii = _tube_radii(st, cfg, hole)
    mean = math.fsum(radii) / len(radii)
    neck_ratio = min(radii) / mean
    amplitude = (max(radii) - min(radii)) / (2.0 * mean)
    return neck_ratio, amplitude, _mode_amplitudes(radii, cfg.hole_modes[hole], cfg)


def _liquid_budget(st: _State, cfg: MultiHoleRimBreakupConfig) -> tuple[float, float, float, float]:
    initial = math.pi * cfg.outer_radius_m ** 2 * cfg.film_thickness_m
    union = _union_area(st.hole_radii_m[0], st.hole_radii_m[1], cfg.hole_center_distance_m)
    film = (math.pi * cfg.outer_radius_m ** 2 - union) * cfg.film_thickness_m
    rim, _ = _rim_partition(st, cfg)
    error = abs(film + rim - initial) / initial
    return initial, film, rim, error


def _sample(st: _State, cfg: MultiHoleRimBreakupConfig) -> MultiHoleSample:
    proximity, gap = _interaction(st, cfg)
    d0 = _hole_diagnostics(st, cfg, 0)
    d1 = _hole_diagnostics(st, cfg, 1)
    _, _, _, error = _liquid_budget(st, cfg)
    return MultiHoleSample(st.time_s, tuple(st.hole_radii_m), tuple(st.retraction_speeds_m_s), gap, proximity, st.bridge_fraction, st.exchange_fraction, (d0[0], d1[0]), (d0[1], d1[1]), (d0[2], d1[2]), error)


def _derivative(st: _State, cfg: MultiHoleRimBreakupConfig):
    proximity, _ = _interaction(st, cfg)
    tube_radii = _mean_tube_radii(st, cfg)
    taylor_culick = cfg.taylor_culick_speed_m_s
    ohnesorge = cfg.dynamic_viscosity_pa_s / math.sqrt(cfg.density_kg_m3 * cfg.surface_tension_n_m * cfg.film_thickness_m)
    target_speed = taylor_culick / (1.0 + 2.0 * ohnesorge)
    target_speed *= 1.0 - 0.08 * cfg.interaction_strength * proximity
    dr = list(st.retraction_speeds_m_s)
    dv = []
    for radius, speed in zip(st.hole_radii_m, st.retraction_speeds_m_s):
        tau = max(0.004, radius / (7.0 * max(target_speed, 1e-12)))
        dv.append((target_speed - speed) / tau)
    da: list[list[float]] = []
    for hole in range(2):
        other_mean = math.fsum(st.amplitudes[1 - hole]) / len(st.amplitudes[1 - hole])
        row = []
        for mode, amplitude in zip(cfg.hole_modes[hole], st.amplitudes[hole]):
            omega = _rp_rate(cfg, mode, st.hole_radii_m[hole], tube_radii[hole])
            cross_hole = cfg.interaction_strength * proximity * (1.8 + 0.15 * mode) * other_mean
            saturation = -0.55 * omega * amplitude * amplitude
            row.append(omega * amplitude + cross_hole + saturation)
        da.append(row)
    dbridge = cfg.interaction_strength * (20.0 * proximity * (cfg.bridge_target_fraction - st.bridge_fraction) - 3.0 * (1.0 - proximity) * st.bridge_fraction)
    p0 = cfg.surface_tension_n_m / max(tube_radii[0], 1e-12)
    p1 = cfg.surface_tension_n_m / max(tube_radii[1], 1e-12)
    contrast = (p1 - p0) / max(abs(p0) + abs(p1), 1e-12)
    dexchange = cfg.interaction_strength * (1.8 * proximity * contrast - 4.0 * (1.0 - proximity) * st.exchange_fraction)
    return dr, dv, da, dbridge, dexchange


def _advance(st: _State, cfg: MultiHoleRimBreakupConfig, dt: float) -> _State:
    k1 = _derivative(st, cfg)
    def add(source: _State, deriv, factor: float) -> _State:
        return _State(source.time_s + factor * dt,
                      [x + factor * dt * dx for x, dx in zip(source.hole_radii_m, deriv[0])],
                      [x + factor * dt * dx for x, dx in zip(source.retraction_speeds_m_s, deriv[1])],
                      [[a + factor * dt * da for a, da in zip(row, drow)] for row, drow in zip(source.amplitudes, deriv[2])],
                      source.bridge_fraction + factor * dt * deriv[3],
                      source.exchange_fraction + factor * dt * deriv[4])
    midpoint = add(st, k1, 0.5)
    k2 = _derivative(midpoint, cfg)
    return add(st, k2, 1.0)


def _interpolate_crossing(left: MultiHoleSample, right: MultiHoleSample, left_value: float, right_value: float, threshold: float) -> float:
    if right_value == left_value:
        return right.time_s
    fraction = (threshold - left_value) / (right_value - left_value)
    return left.time_s + max(0.0, min(1.0, fraction)) * (right.time_s - left.time_s)


def _neck_cells(radii: tuple[float, ...], cfg: MultiHoleRimBreakupConfig) -> tuple[int, ...]:
    mean = math.fsum(radii) / len(radii)
    out = []
    for i, value in enumerate(radii):
        if value <= radii[(i - 1) % len(radii)] and value < radii[(i + 1) % len(radii)] and value / mean <= cfg.partition_neck_radius_ratio:
            out.append(i)
    return tuple(sorted(out))


def _segment(start: int, end: int, count: int) -> list[int]:
    out = []
    i = (start + 1) % count
    while i != end:
        out.append(i)
        i = (i + 1) % count
        if len(out) > count:
            raise RuntimeError('segment traversal failed')
    return out


def _droplets(st: _State, cfg: MultiHoleRimBreakupConfig, digest: str) -> tuple[tuple[tuple[int, ...], tuple[int, ...]], tuple[MultiHoleDroplet, ...]]:
    _, rim_volumes = _rim_partition(st, cfg)
    centers = ((-0.5 * cfg.hole_center_distance_m, 0.0), (0.5 * cfg.hole_center_distance_m, 0.0))
    all_necks = []
    drops = []
    order = 0
    for hole in range(2):
        radii = _tube_radii(st, cfg, hole)
        necks = _neck_cells(radii, cfg)
        if len(necks) < 2:
            raise RuntimeError('fewer than two evolved necks on an interacting rim')
        all_necks.append(necks)
        cell_volume = [math.pi * tube * tube * st.hole_radii_m[hole] * cfg.dtheta for tube in radii]
        emitted = 0.0
        for local_order, start in enumerate(necks):
            end = necks[(local_order + 1) % len(necks)]
            interior = _segment(start, end, cfg.azimuthal_cells)
            weighted = [(start, 0.5), *[(i, 1.0) for i in interior], (end, 0.5)]
            volume = math.fsum(cell_volume[i] * weight for i, weight in weighted)
            if local_order == len(necks) - 1:
                volume += rim_volumes[hole] - (emitted + volume)
            emitted += volume
            mass = cfg.density_kg_m3 * volume
            cx = math.fsum(math.cos((i + 0.5) * cfg.dtheta) * cell_volume[i] * weight for i, weight in weighted)
            cy = math.fsum(math.sin((i + 0.5) * cfg.dtheta) * cell_volume[i] * weight for i, weight in weighted)
            angle = math.atan2(cy, cx) % TWO_PI
            center = centers[hole]
            x = center[0] + st.hole_radii_m[hole] * math.cos(angle)
            y = center[1] + st.hole_radii_m[hole] * math.sin(angle)
            radial_speed = st.retraction_speeds_m_s[hole]
            tangent_bias = 0.08 * math.fsum(st.amplitudes[hole]) * cfg.taylor_culick_speed_m_s * math.sin(angle - (0.0 if hole == 0 else math.pi))
            vx = radial_speed * math.cos(angle) - tangent_bias * math.sin(angle)
            vy = radial_speed * math.sin(angle) + tangent_bias * math.cos(angle)
            suffix = hashlib.sha256(f'{digest}:{hole}:{start}:{end}'.encode()).hexdigest()[:16]
            drops.append(MultiHoleDroplet(f'multihole-drop-{order:02d}-{suffix}', hole, volume, mass, (3 * volume / (4 * math.pi)) ** (1 / 3), angle, (x, y), (vx, vy), (mass * vx, mass * vy), start, end))
            order += 1
    return (all_necks[0], all_necks[1]), tuple(drops)


def evolve_multihole_rim_breakup(cfg: MultiHoleRimBreakupConfig | None = None) -> MultiHoleResult:
    cfg = cfg or MultiHoleRimBreakupConfig()
    st = _State(0.0, list(cfg.initial_hole_radii_m), [0.0, 0.0], [list(row) for row in cfg.hole_amplitudes], 0.0, 0.0)
    samples: list[MultiHoleSample] = []
    interaction_onset = None
    ligament_onset = None
    detachment = None
    previous = None
    while st.time_s <= cfg.max_time_s + 0.5 * cfg.time_step_s:
        sample = _sample(st, cfg)
        samples.append(sample)
        if interaction_onset is None and sample.interaction_proximity > 0.0:
            if previous is not None and previous.gap_m > cfg.interaction_range_m >= sample.gap_m:
                interaction_onset = _interpolate_crossing(previous, sample, previous.gap_m, sample.gap_m, cfg.interaction_range_m)
            else:
                interaction_onset = sample.time_s
        amp = max(sample.hole_total_amplitude_fractions)
        if ligament_onset is None and amp >= cfg.ligament_amplitude_fraction:
            if previous is not None:
                prev_amp = max(previous.hole_total_amplitude_fractions)
                ligament_onset = _interpolate_crossing(previous, sample, prev_amp, amp, cfg.ligament_amplitude_fraction)
            else:
                ligament_onset = sample.time_s
        neck = max(sample.hole_neck_radius_ratios)
        if ligament_onset is not None and neck <= cfg.detachment_neck_radius_ratio:
            if previous is not None:
                prev_neck = max(previous.hole_neck_radius_ratios)
                detachment = _interpolate_crossing(previous, sample, prev_neck, neck, cfg.detachment_neck_radius_ratio)
            else:
                detachment = sample.time_s
            break
        if st.time_s >= cfg.max_time_s:
            raise RuntimeError('no state-derived interacting detachment before max_time_s')
        if max(st.hole_radii_m) + 0.5 * cfg.hole_center_distance_m >= 0.9 * cfg.outer_radius_m:
            raise RuntimeError('film domain exhausted')
        previous = sample
        st = _advance(st, cfg, min(cfg.time_step_s, cfg.max_time_s - st.time_s))
    if interaction_onset is None or ligament_onset is None or detachment is None:
        raise RuntimeError('missing interaction or breakup event')
    final_sample = samples[-1]
    initial_modes = samples[0].hole_mode_amplitudes
    final_modes = final_sample.hole_mode_amplitudes
    _, rim_volumes = _rim_partition(st, cfg)
    payload = {
        'config': asdict(cfg),
        'detachment_time_s': float(detachment).hex(),
        'radii': [float(x).hex() for x in st.hole_radii_m],
        'velocities': [float(x).hex() for x in st.retraction_speeds_m_s],
        'amplitudes': [[float(x).hex() for x in row] for row in st.amplitudes],
        'bridge': float(st.bridge_fraction).hex(),
        'exchange': float(st.exchange_fraction).hex(),
    }
    digest = 'sha256:' + hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    necks, droplets = _droplets(st, cfg, digest)
    initial, film, rim, _ = _liquid_budget(st, cfg)
    droplet_volume = math.fsum(d.volume_m3 for d in droplets)
    volume_error = abs(film + droplet_volume - initial) / initial
    return MultiHoleResult(cfg, tuple(samples), interaction_onset, ligament_onset, detachment, tuple(st.hole_radii_m), tuple(st.retraction_speeds_m_s), final_sample.gap_m, rim_volumes, initial_modes, final_modes, necks, droplets, initial, film, rim, droplet_volume, volume_error, digest, {
        'solver': 'interacting-two-hole-conservative-reduced-rim',
        'version': '1.0.0',
        'requirements': ['R16','R31','R32','R33'],
        'state_model': 'ONE_SHARED_CONSERVATIVE_FILM_PLUS_TWO_SIMULTANEOUS_RIM_STATES',
        'interaction_model': 'GAP_ACTIVATED_SHARED_WEB_COUPLING_PLUS_ZERO_SUM_CAPILLARY_RIM_EXCHANGE',
        'ligament_selection': 'SIMULTANEOUS_EVOLVED_MULTIMODE_PLUS_INTERACTION_NECKING',
        'detachment': 'BOTH_RIMS_CROSS_EVOLVED_NECK_RATIO_THRESHOLD',
        'droplet_volume': 'CONSERVATIVE_PARTITION_BETWEEN_EVOLVED_LOCAL_MINIMA',
        'supported_class': 'TWO_INTERACTING_THIN_FILM_HOLES_MULTIMODE_REDUCED_RIMS',
        'independent_run_stitching': 'NOT_USED',
        'unrestricted_3d_multi_hole_interaction': 'UNSUPPORTED',
        'singular_3d_ligament_pinchoff': 'UNSUPPORTED',
        'turbulent_atomization': 'UNSUPPORTED',
        'aerodynamic_secondary_breakup': 'UNSUPPORTED',
        'broad_spray_statistics': 'UNSUPPORTED',
    })


def evolve_isolated_superposition_reference(cfg: MultiHoleRimBreakupConfig | None = None) -> MultiHoleResult:
    cfg = cfg or MultiHoleRimBreakupConfig()
    return evolve_multihole_rim_breakup(replace(cfg, interaction_strength=0.0))
