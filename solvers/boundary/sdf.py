"""Deterministic signed-distance solid boundaries for tracked soap-film contact.

Sign convention: signed distance is positive in the fluid-accessible region,
zero on the solid surface, and negative inside the solid.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Iterable

Vec3 = tuple[float, float, float]


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a: Vec3, s: float) -> Vec3:
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a: Vec3) -> float:
    return math.sqrt(_dot(a, a))


def _unit(a: Vec3) -> Vec3:
    n = _norm(a)
    if n <= 0.0:
        raise ValueError("boundary normal must be non-zero")
    return _mul(a, 1.0 / n)


def _clamp(x: float, lo: float, hi: float) -> float:
    return min(max(x, lo), hi)


@dataclass(frozen=True)
class WettingParameters:
    """Local geometric wetting law attached to a solid boundary.

    ``target_contact_angle_deg`` is measured as the acute angle between the
    local film tangent plane and the solid tangent plane.  Angles above 90 deg
    are represented by their supplementary acute angle because the present
    closed-front model does not carry a separate liquid-side orientation at a
    topologically open contact line.
    """

    target_contact_angle_deg: float | None = None
    relaxation: float = 0.45
    iterations: int = 3
    contact_band_m: float = 2.0e-3

    def __post_init__(self) -> None:
        if self.target_contact_angle_deg is not None:
            if not 0.0 < self.target_contact_angle_deg < 180.0:
                raise ValueError("target contact angle must be in (0, 180) degrees")
        if not 0.0 < self.relaxation <= 1.0:
            raise ValueError("wetting relaxation must be in (0, 1]")
        if self.iterations < 0:
            raise ValueError("wetting iterations must be non-negative")
        if self.contact_band_m < 0.0:
            raise ValueError("contact band must be non-negative")

    @property
    def effective_acute_angle_deg(self) -> float | None:
        if self.target_contact_angle_deg is None:
            return None
        return min(self.target_contact_angle_deg, 180.0 - self.target_contact_angle_deg)


@dataclass(frozen=True)
class SolidBoundary:
    """Base class for deterministic solid SDF boundaries."""

    boundary_id: str
    wall_velocity_m_s: Vec3 = (0.0, 0.0, 0.0)
    wetting: WettingParameters = field(default_factory=WettingParameters)

    def __post_init__(self) -> None:
        if not self.boundary_id:
            raise ValueError("boundary_id must be non-empty")

    @property
    def boundary_type(self) -> str:
        raise NotImplementedError

    def signed_distance(self, point_m: Vec3) -> float:
        raise NotImplementedError

    def outward_normal(self, point_m: Vec3) -> Vec3:
        raise NotImplementedError

    def closest_point(self, point_m: Vec3) -> Vec3:
        d = self.signed_distance(point_m)
        n = self.outward_normal(point_m)
        return _sub(point_m, _mul(n, d))

    def metadata(self) -> dict[str, object]:
        return {
            "boundary_id": self.boundary_id,
            "boundary_type": self.boundary_type,
            "wall_velocity_m_s": list(self.wall_velocity_m_s),
            "wetting_target_contact_angle_deg": self.wetting.target_contact_angle_deg,
            "wetting_model": "local-edge-slope-relaxation" if self.wetting.target_contact_angle_deg is not None else "disabled",
        }


@dataclass(frozen=True)
class PlaneBoundary(SolidBoundary):
    point_m: Vec3 = (0.0, 0.0, 0.0)
    normal_outward: Vec3 = (0.0, 1.0, 0.0)

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "normal_outward", _unit(self.normal_outward))

    @property
    def boundary_type(self) -> str:
        return "PLANE"

    def signed_distance(self, point_m: Vec3) -> float:
        return _dot(_sub(point_m, self.point_m), self.normal_outward)

    def outward_normal(self, point_m: Vec3) -> Vec3:
        return self.normal_outward


@dataclass(frozen=True)
class SphereBoundary(SolidBoundary):
    center_m: Vec3 = (0.0, 0.0, 0.0)
    radius_m: float = 1.0

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.radius_m <= 0.0:
            raise ValueError("sphere radius must be positive")

    @property
    def boundary_type(self) -> str:
        return "SPHERE"

    def signed_distance(self, point_m: Vec3) -> float:
        return _norm(_sub(point_m, self.center_m)) - self.radius_m

    def outward_normal(self, point_m: Vec3) -> Vec3:
        delta = _sub(point_m, self.center_m)
        if _norm(delta) <= 1.0e-30:
            return (1.0, 0.0, 0.0)
        return _unit(delta)

    def closest_point(self, point_m: Vec3) -> Vec3:
        return _add(self.center_m, _mul(self.outward_normal(point_m), self.radius_m))


@dataclass(frozen=True)
class AxisAlignedBoxBoundary(SolidBoundary):
    minimum_m: Vec3 = (-0.5, -0.5, -0.5)
    maximum_m: Vec3 = (0.5, 0.5, 0.5)

    def __post_init__(self) -> None:
        super().__post_init__()
        if any(lo >= hi for lo, hi in zip(self.minimum_m, self.maximum_m)):
            raise ValueError("box minimum must be strictly smaller than maximum")

    @property
    def boundary_type(self) -> str:
        return "AABB"

    def signed_distance(self, point_m: Vec3) -> float:
        center = tuple((lo + hi) * 0.5 for lo, hi in zip(self.minimum_m, self.maximum_m))
        half = tuple((hi - lo) * 0.5 for lo, hi in zip(self.minimum_m, self.maximum_m))
        q = tuple(abs(x - c) - h for x, c, h in zip(point_m, center, half))
        outside = tuple(max(v, 0.0) for v in q)
        outside_distance = _norm(outside)  # type: ignore[arg-type]
        inside_distance = min(max(q), 0.0)
        return outside_distance + inside_distance

    def _inside_face(self, point_m: Vec3) -> tuple[Vec3, Vec3]:
        candidates: list[tuple[float, int, int, Vec3, Vec3]] = []
        axes = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        for axis, (x, lo, hi) in enumerate(zip(point_m, self.minimum_m, self.maximum_m)):
            p_lo = list(point_m)
            p_lo[axis] = lo
            p_hi = list(point_m)
            p_hi[axis] = hi
            n_lo = tuple(-v for v in axes[axis])
            n_hi = axes[axis]
            candidates.append((x - lo, axis, 0, tuple(p_lo), n_lo))
            candidates.append((hi - x, axis, 1, tuple(p_hi), n_hi))
        _, _, _, projected, normal = min(candidates, key=lambda item: (item[0], item[1], item[2]))
        return projected, normal

    def closest_point(self, point_m: Vec3) -> Vec3:
        inside = all(lo <= x <= hi for x, lo, hi in zip(point_m, self.minimum_m, self.maximum_m))
        if inside:
            return self._inside_face(point_m)[0]
        return tuple(_clamp(x, lo, hi) for x, lo, hi in zip(point_m, self.minimum_m, self.maximum_m))  # type: ignore[return-value]

    def outward_normal(self, point_m: Vec3) -> Vec3:
        inside = all(lo <= x <= hi for x, lo, hi in zip(point_m, self.minimum_m, self.maximum_m))
        if inside:
            return self._inside_face(point_m)[1]
        projected = self.closest_point(point_m)
        delta = _sub(point_m, projected)
        if _norm(delta) <= 1.0e-30:
            return self._inside_face(projected)[1]
        return _unit(delta)


class BoundarySet:
    """Stable-ID ordered collection with deterministic tie breaking."""

    def __init__(self, boundaries: Iterable[SolidBoundary] = ()) -> None:
        ordered = tuple(sorted(boundaries, key=lambda boundary: boundary.boundary_id))
        ids = [boundary.boundary_id for boundary in ordered]
        if len(ids) != len(set(ids)):
            raise ValueError("solid boundary IDs must be unique")
        self.boundaries = ordered

    def __bool__(self) -> bool:
        return bool(self.boundaries)

    def __iter__(self):
        return iter(self.boundaries)

    def nearest(self, point_m: Vec3) -> SolidBoundary | None:
        if not self.boundaries:
            return None
        return min(self.boundaries, key=lambda boundary: (boundary.signed_distance(point_m), boundary.boundary_id))

    def metadata(self) -> list[dict[str, object]]:
        return [boundary.metadata() for boundary in self.boundaries]
