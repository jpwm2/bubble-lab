from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Iterable

from bubblelab.solvers.singular_breakup.transactions import child_lineage, conservative_split

Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class MultiNeck3DConfig:
    density_kg_m3: float = 1000.0
    dynamic_viscosity_pa_s: float = 0.001
    surface_tension_n_m: float = 0.072
    time_step_s: float = 2.0e-5
    max_time_s: float = 0.018
    detachment_radius_m: float = 3.2e-4
    coupling_strength: float = 0.45
    coupling_length_m: float = 5.0e-3
    capillary_factor: float = 0.18
    viscous_factor: float = 4.0
    initial_parent_volume_m3: float = 2.0e-8
    neck_centers_m: tuple[Vec3, ...] = (
        (0.0, 0.0, 0.0),
        (0.0032, 0.0025, 0.0018),
        (-0.0027, 0.0034, -0.0015),
    )
    neck_axes: tuple[Vec3, ...] = (
        (1.0, 0.3, 0.2),
        (-0.2, 0.9, 0.35),
        (0.25, -0.1, 0.96),
    )
    initial_radii_m: tuple[float, ...] = (0.00115, 0.00128, 0.00138)
    initial_radial_velocities_m_s: tuple[float, ...] = (-0.025, -0.022, -0.020)
    lineage_root: str = "multineck-liquid-root"


@dataclass(frozen=True)
class MultiNeckSample:
    time_s: float
    radii_m: tuple[float, ...]
    radial_velocities_m_s: tuple[float, ...]
    active: tuple[bool, ...]
    parent_volume_m3: float
    detached_volume_m3: float


@dataclass(frozen=True)
class DetachmentEvent:
    event_index: int
    neck_index: int
    neck_id: str
    time_s: float
    radius_m: float
    radial_velocity_m_s: float
    fragment_id: str
    fragment_volume_m3: float
    fragment_equivalent_radius_m: float
    parent_volume_before_m3: float
    parent_volume_after_m3: float
    transaction_relative_error: float
    position_m: Vec3
    velocity_m_s: Vec3
    active_necks_after: int


@dataclass(frozen=True)
class MultiNeck3DResult:
    config: MultiNeck3DConfig
    samples: tuple[MultiNeckSample, ...]
    events: tuple[DetachmentEvent, ...]
    initial_liquid_volume_m3: float
    final_parent_volume_m3: float
    detached_volume_m3: float
    liquid_volume_relative_error: float
    max_transaction_relative_error: float
    geometry_noncoplanarity: float
    interaction_enabled: bool
    solver_digest: str
    provenance: dict[str, object]


def _norm(v: Vec3) -> float:
    return math.sqrt(sum(x * x for x in v))


def _unit(v: Vec3) -> Vec3:
    n = _norm(v)
    if n <= 0.0:
        raise ValueError("zero-length vector")
    return tuple(x / n for x in v)  # type: ignore[return-value]


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return tuple(a[i] - b[i] for i in range(3))  # type: ignore[return-value]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot(a: Vec3, b: Vec3) -> float:
    return sum(a[i] * b[i] for i in range(3))


def geometry_noncoplanarity(config: MultiNeck3DConfig) -> float:
    p0, p1, p2 = config.neck_centers_m[:3]
    axis0 = _unit(config.neck_axes[0])
    u = _sub(p1, p0)
    v = _sub(p2, p0)
    denom = _norm(u) * _norm(v)
    if denom <= 0.0:
        return 0.0
    return abs(_dot(_cross(u, v), axis0)) / denom


def _validate(config: MultiNeck3DConfig) -> None:
    count = len(config.neck_centers_m)
    if count < 3:
        raise ValueError("at least three necks are required for the supported 3D class")
    if not (
        len(config.neck_axes)
        == len(config.initial_radii_m)
        == len(config.initial_radial_velocities_m_s)
        == count
    ):
        raise ValueError("all neck arrays must have identical length")
    positive = (
        config.density_kg_m3,
        config.dynamic_viscosity_pa_s,
        config.surface_tension_n_m,
        config.time_step_s,
        config.max_time_s,
        config.detachment_radius_m,
        config.coupling_length_m,
        config.capillary_factor,
        config.viscous_factor,
        config.initial_parent_volume_m3,
    )
    if any((not math.isfinite(x)) or x <= 0.0 for x in positive):
        raise ValueError("physical and numerical scalar parameters must be finite and positive")
    if not math.isfinite(config.coupling_strength) or config.coupling_strength < 0.0:
        raise ValueError("coupling_strength must be finite and non-negative")
    if any(r <= config.detachment_radius_m for r in config.initial_radii_m):
        raise ValueError("initial radii must exceed detachment radius")
    if any(not math.isfinite(v) for v in config.initial_radial_velocities_m_s):
        raise ValueError("initial radial velocities must be finite")
    for axis in config.neck_axes:
        _unit(axis)
    if geometry_noncoplanarity(config) <= 0.05:
        raise ValueError("neck geometry is insufficiently non-coplanar for the supported class")


def _distance(a: Vec3, b: Vec3) -> float:
    return _norm(_sub(a, b))


def _acceleration(
    config: MultiNeck3DConfig,
    i: int,
    radii: list[float],
    velocities: list[float],
    active: list[bool],
) -> float:
    radius = max(radii[i], config.detachment_radius_m * 0.6)
    capillary = -config.capillary_factor * config.surface_tension_n_m / (
        config.density_kg_m3 * radius * radius
    )
    viscous = -config.viscous_factor * config.dynamic_viscosity_pa_s * velocities[i] / (
        config.density_kg_m3 * radius * radius
    )
    coupled = 0.0
    if config.coupling_strength > 0.0:
        for j in range(len(radii)):
            if j == i or not active[j]:
                continue
            distance = _distance(config.neck_centers_m[i], config.neck_centers_m[j])
            if distance <= 0.0:
                continue
            radius_contrast = (
                config.coupling_strength
                * (config.surface_tension_n_m / config.density_kg_m3)
                * (radii[j] - radii[i])
                / (distance ** 3)
            )
            cooperative = (
                -config.coupling_strength
                * 0.04
                * config.surface_tension_n_m
                / (config.density_kg_m3 * radius * radius)
                * math.exp(-distance / config.coupling_length_m)
            )
            coupled += radius_contrast + cooperative
    return capillary + viscous + coupled


def _fragment_volume(
    config: MultiNeck3DConfig,
    neck_index: int,
    radii: list[float],
    active: list[bool],
    parent_volume_m3: float,
) -> float:
    neighbor_radii = [
        radii[j]
        for j in range(len(radii))
        if j != neck_index and active[j]
    ]
    neighbor_scale = (
        sum(neighbor_radii) / len(neighbor_radii)
        if neighbor_radii
        else config.initial_radii_m[neck_index]
    )
    local_scale = 0.5 * (config.detachment_radius_m + neighbor_scale)
    equivalent_radius = max(1.6 * config.detachment_radius_m, 0.72 * local_scale)
    geometric_volume = (4.0 / 3.0) * math.pi * equivalent_radius ** 3
    return min(geometric_volume, 0.25 * parent_volume_m3)


def _fragment_velocity(
    config: MultiNeck3DConfig,
    neck_index: int,
    radial_velocity_m_s: float,
) -> Vec3:
    axis = _unit(config.neck_axes[neck_index])
    capillary_speed = math.sqrt(
        config.surface_tension_n_m
        / (config.density_kg_m3 * config.detachment_radius_m)
    )
    speed = max(0.0, -0.25 * radial_velocity_m_s + 0.10 * capillary_speed)
    return tuple(speed * x for x in axis)  # type: ignore[return-value]


def _digest_payload(
    config: MultiNeck3DConfig,
    events: Iterable[DetachmentEvent],
    final_parent_volume_m3: float,
) -> str:
    payload = {
        "config": asdict(config),
        "events": [asdict(event) for event in events],
        "final_parent_volume_m3": final_parent_volume_m3,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def evolve_multineck_breakup(config: MultiNeck3DConfig | None = None) -> MultiNeck3DResult:
    config = config or MultiNeck3DConfig()
    _validate(config)

    radii = list(config.initial_radii_m)
    velocities = list(config.initial_radial_velocities_m_s)
    active = [True] * len(radii)
    parent_volume = config.initial_parent_volume_m3
    detached_volume = 0.0
    events: list[DetachmentEvent] = []
    samples: list[MultiNeckSample] = [
        MultiNeckSample(
            0.0,
            tuple(radii),
            tuple(velocities),
            tuple(active),
            parent_volume,
            detached_volume,
        )
    ]
    t = 0.0
    step = 0

    while t < config.max_time_s and any(active):
        dt = min(config.time_step_s, config.max_time_s - t)
        if dt <= 0.0:
            break

        old_radii = radii.copy()
        old_velocities = velocities.copy()
        a0 = [
            _acceleration(config, i, radii, velocities, active) if active[i] else 0.0
            for i in range(len(radii))
        ]
        midpoint_radii = [
            radii[i] + 0.5 * dt * velocities[i] if active[i] else radii[i]
            for i in range(len(radii))
        ]
        midpoint_velocities = [
            velocities[i] + 0.5 * dt * a0[i] if active[i] else velocities[i]
            for i in range(len(radii))
        ]
        amid = [
            _acceleration(config, i, midpoint_radii, midpoint_velocities, active)
            if active[i]
            else 0.0
            for i in range(len(radii))
        ]

        crossings: list[tuple[float, int]] = []
        for i in range(len(radii)):
            if not active[i]:
                continue
            radii[i] += dt * midpoint_velocities[i]
            velocities[i] += dt * amid[i]
            if radii[i] <= config.detachment_radius_m:
                denom = old_radii[i] - radii[i]
                fraction = (
                    (old_radii[i] - config.detachment_radius_m) / denom
                    if denom > 0.0
                    else 1.0
                )
                fraction = min(1.0, max(0.0, fraction))
                crossings.append((t + dt * fraction, i))

        for event_time, i in sorted(crossings):
            if not active[i]:
                continue
            interpolated_velocity = old_velocities[i] + (
                (event_time - t) / dt
            ) * (velocities[i] - old_velocities[i])
            radii[i] = config.detachment_radius_m
            fragment_volume = _fragment_volume(config, i, radii, active, parent_volume)
            tx = conservative_split(parent_volume, fragment_volume)
            parent_volume = tx.parent_after_m3
            detached_volume += tx.detached_m3
            active[i] = False
            event_index = len(events) + 1
            velocity = _fragment_velocity(config, i, interpolated_velocity)
            fragment_radius = (3.0 * fragment_volume / (4.0 * math.pi)) ** (1.0 / 3.0)
            events.append(
                DetachmentEvent(
                    event_index=event_index,
                    neck_index=i,
                    neck_id=f"neck-{i:02d}",
                    time_s=event_time,
                    radius_m=config.detachment_radius_m,
                    radial_velocity_m_s=interpolated_velocity,
                    fragment_id=child_lineage(config.lineage_root, event_index, 0),
                    fragment_volume_m3=fragment_volume,
                    fragment_equivalent_radius_m=fragment_radius,
                    parent_volume_before_m3=tx.parent_before_m3,
                    parent_volume_after_m3=tx.parent_after_m3,
                    transaction_relative_error=tx.relative_error,
                    position_m=config.neck_centers_m[i],
                    velocity_m_s=velocity,
                    active_necks_after=sum(active),
                )
            )

        t += dt
        step += 1
        if crossings or step % 20 == 0 or t >= config.max_time_s:
            samples.append(
                MultiNeckSample(
                    t,
                    tuple(radii),
                    tuple(velocities),
                    tuple(active),
                    parent_volume,
                    detached_volume,
                )
            )

    total_after = parent_volume + detached_volume
    volume_error = abs(config.initial_parent_volume_m3 - total_after) / config.initial_parent_volume_m3
    max_tx_error = max((event.transaction_relative_error for event in events), default=0.0)
    noncoplanarity = geometry_noncoplanarity(config)
    digest = _digest_payload(config, events, parent_volume)
    provenance: dict[str, object] = {
        "supported_class": "NONCOPLANAR_3D_INTERACTING_MULTI_NECK_REDUCED_CAPILLARY_CLASS",
        "state_model": "COUPLED_SLENDER_NECK_CAPILLARY_VISCOUS_INERTIAL_ODE",
        "topology_transactions": "STATE_DERIVED_RADIUS_CROSSINGS_WITH_CONSERVATIVE_SPLIT",
        "interaction_model": "PAIRWISE_GEOMETRIC_CAPILLARY_COUPLING",
        "event_time_scripting": False,
        "hardcoded_fragment_count": False,
        "broad_spray_claim": False,
        "unrestricted_3d_cfd_claim": False,
    }
    return MultiNeck3DResult(
        config=config,
        samples=tuple(samples),
        events=tuple(events),
        initial_liquid_volume_m3=config.initial_parent_volume_m3,
        final_parent_volume_m3=parent_volume,
        detached_volume_m3=detached_volume,
        liquid_volume_relative_error=volume_error,
        max_transaction_relative_error=max_tx_error,
        geometry_noncoplanarity=noncoplanarity,
        interaction_enabled=config.coupling_strength > 0.0,
        solver_digest=digest,
        provenance=provenance,
    )
