"""Conservative deterministic parent-to-children split bookkeeping prototype."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any

from geometry import Vec3, add, mul, norm, sub


def stable_id(prefix: str, *parts: object) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


@dataclass(frozen=True)
class ParentState:
    id: str
    target_volume: float
    gas_amount: float | None
    centroid: Vec3
    velocity: Vec3
    mass: float | None


@dataclass(frozen=True)
class ChildState:
    id: str
    target_volume: float
    gas_amount: float | None
    centroid: Vec3
    velocity: Vec3
    mass: float | None
    lineage: tuple[str, ...]
    geometry_status: str = "PROTOTYPE_SPLIT_REQUIRES_PHYSICAL_RELAXATION"


@dataclass(frozen=True)
class SplitResult:
    parent_id: str
    children: tuple[ChildState, ChildState]
    event_id: str
    event_time: float
    trigger_provenance: dict[str, Any]
    conservation: dict[str, float | None | str]
    surface_energy_change: None = None


def _allocate(total: float | None, fraction: float) -> tuple[float | None, float | None]:
    if total is None:
        return None, None
    first = total * fraction
    second = total - first
    return first, second


def _momentum(mass: float | None, velocity: Vec3) -> Vec3 | None:
    if mass is None:
        return None
    return mul(velocity, mass)


def _relative_scalar(reference: float, value: float) -> float:
    return abs(value - reference) / max(abs(reference), 1.0e-300)


def _relative_vector(reference: Vec3, value: Vec3) -> float:
    return norm(sub(value, reference)) / max(norm(reference), 1.0e-300)


def split_parent(
    parent: ParentState,
    *,
    volume_fractions: tuple[float, float],
    provisional_centroids: tuple[Vec3, Vec3],
    event_time: float,
    trigger_provenance: dict[str, Any],
) -> SplitResult:
    f0, f1 = volume_fractions
    if f0 <= 0.0 or f1 <= 0.0 or abs((f0 + f1) - 1.0) > 1.0e-10:
        raise ValueError("child volume fractions must be positive and sum to one")
    if event_time < 0.0 or not math.isfinite(event_time):
        raise ValueError("event time must be finite and non-negative")

    v0, v1 = _allocate(parent.target_volume, f0)
    g0, g1 = _allocate(parent.gas_amount, f0)
    m0, m1 = _allocate(parent.mass, f0)
    assert v0 is not None and v1 is not None

    weights = (m0, m1) if m0 is not None and m1 is not None else (v0, v1)
    total_weight = float(weights[0] + weights[1])
    current_com = tuple(
        (weights[0] * provisional_centroids[0][axis] + weights[1] * provisional_centroids[1][axis]) / total_weight
        for axis in range(3)
    )
    correction = sub(parent.centroid, current_com)
    c0 = add(provisional_centroids[0], correction)
    c1 = add(provisional_centroids[1], correction)

    event_id = stable_id(
        "event",
        "SPLIT_PROTOTYPE",
        parent.id,
        float(event_time).hex(),
        tuple(float(f).hex() for f in volume_fractions),
        trigger_provenance,
    )
    child0_id = stable_id("bubble", parent.id, event_id, "negative-axis")
    child1_id = stable_id("bubble", parent.id, event_id, "positive-axis")

    children = (
        ChildState(child0_id, v0, g0, c0, parent.velocity, m0, (parent.id,)),
        ChildState(child1_id, v1, g1, c1, parent.velocity, m1, (parent.id,)),
    )

    gas_error = None
    if parent.gas_amount is not None and g0 is not None and g1 is not None:
        gas_error = _relative_scalar(parent.gas_amount, math.fsum((g0, g1)))
    volume_error = _relative_scalar(parent.target_volume, math.fsum((v0, v1)))

    child_com = tuple(
        (weights[0] * c0[axis] + weights[1] * c1[axis]) / total_weight for axis in range(3)
    )
    com_error = _relative_vector(parent.centroid, child_com)

    momentum_error = None
    before_momentum = _momentum(parent.mass, parent.velocity)
    p0 = _momentum(m0, parent.velocity)
    p1 = _momentum(m1, parent.velocity)
    if before_momentum is not None and p0 is not None and p1 is not None:
        after_momentum = add(p0, p1)
        momentum_error = _relative_vector(before_momentum, after_momentum)

    return SplitResult(
        parent_id=parent.id,
        children=children,
        event_id=event_id,
        event_time=event_time,
        trigger_provenance=dict(trigger_provenance),
        conservation={
            "target_volume_relative_error": volume_error,
            "gas_amount_relative_error": gas_error,
            "center_of_mass_relative_error": com_error,
            "linear_momentum_relative_error": momentum_error,
            "surface_energy_accounting": "UNRESOLVED_SINGULAR_PINCH_EVENT",
        },
    )
