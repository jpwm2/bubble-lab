"""Triangulated-gap Reynolds/Taylor lubrication model.

The production slice implemented here is deliberately reduced order.  It uses the
actual tracked-front gap and discrete local curvature, then closes an overdamped
pair-force balance between the outer resolved approach and the asymptotic Taylor
lubrication resistance.  It does not claim a resolved multi-region Navier-Stokes
solution inside the gap.

For two locally convex surfaces with effective radius ``R`` and minimum gap ``h``,
the axisymmetric Reynolds equation gives the Taylor resistance

    F_lub = 6*pi*mu*R**2*U/h

and the local pressure profile

    p(r) = 3*mu*U*R / (h + r**2/(2*R))**2.

The outer relative-motion resistance is represented by the Stokes pair resistance
``6*pi*mu*R``.  Matching the same driving force therefore gives
``U_coupled = U_free / (1 + R/h)`` when ``outer_drag_scale == 1``.  This makes the
pressure response alter authoritative front motion without inventing a collision
threshold or post-hoc event delay.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable

from bubblelab.solvers.transient.geometry import FilmFront, Vec3, dot, mul, norm, sub, unit


@dataclass(frozen=True)
class LubricationSettings:
    """Numerical/physical limits for the reduced-order gap model."""

    enabled: bool = True
    minimum_gap_m: float = 1.0e-7
    onset_gap_over_effective_radius: float = 0.5
    outer_drag_scale: float = 1.0
    volume_relative_tolerance: float = 5.0e-12

    def validate(self) -> None:
        if self.minimum_gap_m <= 0.0:
            raise ValueError("minimum lubrication gap must be positive")
        if self.onset_gap_over_effective_radius <= 0.0:
            raise ValueError("lubrication onset ratio must be positive")
        if self.outer_drag_scale <= 0.0:
            raise ValueError("outer drag scale must be positive")
        if self.volume_relative_tolerance <= 0.0:
            raise ValueError("volume relative tolerance must be positive")


@dataclass(frozen=True)
class GapGeometry:
    """Local gap geometry measured from the authoritative triangulated fronts."""

    parent_ids: tuple[str, str]
    anchor_vertex_indices: tuple[int, int]
    normal_a_to_b: Vec3
    gap_m: float
    local_radius_a_m: float
    local_radius_b_m: float
    effective_radius_m: float
    local_curvature_a_1_m: float
    local_curvature_b_1_m: float
    mesh_resolution_m: float
    geometry_source: str

    def signature(self) -> tuple[object, ...]:
        return (
            self.parent_ids,
            self.anchor_vertex_indices,
            tuple(float(value) for value in self.normal_a_to_b),
            float(self.gap_m),
            float(self.local_radius_a_m),
            float(self.local_radius_b_m),
            float(self.effective_radius_m),
            float(self.local_curvature_a_1_m),
            float(self.local_curvature_b_1_m),
            float(self.mesh_resolution_m),
            self.geometry_source,
        )


@dataclass(frozen=True)
class LubricationResponse:
    """One deterministic force/velocity response for a measured gap."""

    active: bool
    free_closing_speed_m_s: float
    coupled_closing_speed_m_s: float
    correction_speed_m_s: float
    lubrication_resistance_n_s_m: float
    outer_resistance_n_s_m: float
    resistance_ratio: float
    force_n: float
    center_pressure_pa: float
    characteristic_patch_radius_m: float
    radial_drainage_rate_m3_s: float
    viscous_dissipation_w: float
    model: str = "MODELED_REYNOLDS_TAYLOR_OVERDAMPED_PAIR"

    def as_dict(self) -> dict[str, object]:
        return {
            "active": bool(self.active),
            "free_closing_speed_m_s": float(self.free_closing_speed_m_s),
            "coupled_closing_speed_m_s": float(self.coupled_closing_speed_m_s),
            "correction_speed_m_s": float(self.correction_speed_m_s),
            "lubrication_resistance_n_s_m": float(self.lubrication_resistance_n_s_m),
            "outer_resistance_n_s_m": float(self.outer_resistance_n_s_m),
            "resistance_ratio": float(self.resistance_ratio),
            "force_n": float(self.force_n),
            "center_pressure_pa": float(self.center_pressure_pa),
            "characteristic_patch_radius_m": float(self.characteristic_patch_radius_m),
            "radial_drainage_rate_m3_s": float(self.radial_drainage_rate_m3_s),
            "viscous_dissipation_w": float(self.viscous_dissipation_w),
            "model": self.model,
        }


def _front_for_id(fronts: Iterable[FilmFront], bubble_id: str) -> FilmFront:
    matches = [front for front in fronts if front.bubble_id == bubble_id]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one tracked front for {bubble_id!r}")
    return matches[0]


def _median_edge_length(front: FilmFront) -> float:
    lengths: list[float] = []
    seen: set[tuple[int, int]] = set()
    for i, j, k in front.faces:
        for a, b in ((i, j), (j, k), (k, i)):
            edge = (a, b) if a < b else (b, a)
            if edge in seen:
                continue
            seen.add(edge)
            lengths.append(norm(sub(front.vertices[a], front.vertices[b])))
    if not lengths:
        raise ValueError("triangulated lubrication front has no edges")
    lengths.sort()
    middle = len(lengths) // 2
    if len(lengths) % 2:
        return lengths[middle]
    return 0.5 * (lengths[middle - 1] + lengths[middle])


def _local_radius(front: FilmFront, anchor: int) -> tuple[float, float]:
    if anchor < 0 or anchor >= len(front.vertices):
        raise ValueError("lubrication anchor lies outside tracked front")
    curvature_vector = front.normal_curvature_vectors()[anchor]
    curvature = norm(curvature_vector)
    support_radius = norm(sub(front.vertices[anchor], front.centroid()))
    if support_radius <= 0.0:
        support_radius = front.equivalent_radius()
    if curvature <= 1.0e-14:
        return support_radius, 2.0 / support_radius

    # FilmFront.normal_curvature_vectors stores the full area-gradient curvature
    # vector, whose magnitude is approximately 2/R for a sphere.
    radius = 2.0 / curvature
    # Strongly distorted one-ring curvature can be noisy.  The support-radius
    # guard keeps the reduced model finite while remaining entirely geometry based.
    if radius < 0.2 * support_radius or radius > 5.0 * support_radius:
        radius = support_radius
        curvature = 2.0 / radius
    return radius, curvature


def _effective_radius(radius_a_m: float, radius_b_m: float) -> float:
    if radius_a_m <= 0.0 or radius_b_m <= 0.0:
        raise ValueError("local lubrication radii must be positive")
    return 1.0 / (1.0 / radius_a_m + 1.0 / radius_b_m)


def measure_axis_gap_geometry(front_a: FilmFront, front_b: FilmFront) -> GapGeometry:
    """Measure a deterministic local gap using support vertices on the center axis."""
    ordered = sorted((front_a, front_b), key=lambda front: front.bubble_id)
    a, b = ordered[0], ordered[1]
    axis = unit(sub(b.centroid(), a.centroid()))
    if norm(axis) <= 1.0e-15:
        raise ValueError("cannot define lubrication axis for coincident front centroids")
    anchor_a = max(range(len(a.vertices)), key=lambda index: (dot(a.vertices[index], axis), -index))
    anchor_b = min(range(len(b.vertices)), key=lambda index: (dot(b.vertices[index], axis), index))
    gap = dot(sub(b.vertices[anchor_b], a.vertices[anchor_a]), axis)
    radius_a, curvature_a = _local_radius(a, anchor_a)
    radius_b, curvature_b = _local_radius(b, anchor_b)
    return GapGeometry(
        parent_ids=(a.bubble_id, b.bubble_id),
        anchor_vertex_indices=(anchor_a, anchor_b),
        normal_a_to_b=axis,
        gap_m=float(gap),
        local_radius_a_m=radius_a,
        local_radius_b_m=radius_b,
        effective_radius_m=_effective_radius(radius_a, radius_b),
        local_curvature_a_1_m=curvature_a,
        local_curvature_b_1_m=curvature_b,
        mesh_resolution_m=min(_median_edge_length(a), _median_edge_length(b)),
        geometry_source="tracked triangulated support gap + discrete one-ring mean curvature",
    )


def gap_geometry_from_observation(
    fronts: Iterable[FilmFront],
    observation: Any,
) -> GapGeometry:
    """Build local lubrication geometry from the accepted contact observation."""
    parent_ids = tuple(str(value) for value in observation.parent_ids)
    if len(parent_ids) != 2:
        raise ValueError("lubrication observation must have exactly two parents")
    a = _front_for_id(fronts, parent_ids[0])
    b = _front_for_id(fronts, parent_ids[1])
    anchor_a, anchor_b = (int(value) for value in observation.anchor_vertex_indices)
    radius_a, curvature_a = _local_radius(a, anchor_a)
    radius_b, curvature_b = _local_radius(b, anchor_b)
    normal = unit(tuple(float(value) for value in observation.normal_a_to_b))
    if norm(normal) <= 1.0e-15:
        normal = unit(sub(b.centroid(), a.centroid()))
    raw_gap = float(observation.axial_gap_m)
    if raw_gap <= 0.0:
        raw_gap = float(observation.separation_metric_m)
    return GapGeometry(
        parent_ids=(a.bubble_id, b.bubble_id),
        anchor_vertex_indices=(anchor_a, anchor_b),
        normal_a_to_b=normal,
        gap_m=raw_gap,
        local_radius_a_m=radius_a,
        local_radius_b_m=radius_b,
        effective_radius_m=_effective_radius(radius_a, radius_b),
        local_curvature_a_1_m=curvature_a,
        local_curvature_b_1_m=curvature_b,
        mesh_resolution_m=float(observation.resolution_m),
        geometry_source="accepted contact observation on authoritative triangulated tracked fronts + discrete local curvature",
    )


def reynolds_sphere_pressure_pa(
    radius_m: float,
    gap_m: float,
    closing_speed_m_s: float,
    dynamic_viscosity_pa_s: float,
    radial_position_m: float = 0.0,
) -> float:
    """Axisymmetric Reynolds pressure for a local parabolic two-surface gap."""
    if radius_m <= 0.0 or gap_m <= 0.0 or dynamic_viscosity_pa_s <= 0.0:
        raise ValueError("radius, gap, and viscosity must be positive")
    if closing_speed_m_s < 0.0 or radial_position_m < 0.0:
        raise ValueError("closing speed and radial position must be non-negative")
    local_gap = gap_m + radial_position_m * radial_position_m / (2.0 * radius_m)
    return 3.0 * dynamic_viscosity_pa_s * closing_speed_m_s * radius_m / (local_gap * local_gap)


def taylor_lubrication_force_n(
    radius_m: float,
    gap_m: float,
    closing_speed_m_s: float,
    dynamic_viscosity_pa_s: float,
) -> float:
    """Integrated Reynolds/Taylor squeeze-film resistance for two convex surfaces."""
    if radius_m <= 0.0 or gap_m <= 0.0 or dynamic_viscosity_pa_s <= 0.0:
        raise ValueError("radius, gap, and viscosity must be positive")
    if closing_speed_m_s < 0.0:
        raise ValueError("closing speed must be non-negative")
    return 6.0 * math.pi * dynamic_viscosity_pa_s * radius_m * radius_m * closing_speed_m_s / gap_m


def coupled_response(
    geometry: GapGeometry,
    free_closing_speed_m_s: float,
    dynamic_viscosity_pa_s: float,
    settings: LubricationSettings | None = None,
) -> LubricationResponse:
    """Match outer pair drag with Taylor gap resistance and return coupled speed."""
    cfg = settings or LubricationSettings()
    cfg.validate()
    if dynamic_viscosity_pa_s <= 0.0:
        raise ValueError("lubrication viscosity must be positive")
    free_speed = max(0.0, float(free_closing_speed_m_s))
    radius = geometry.effective_radius_m
    gap = max(float(geometry.gap_m), cfg.minimum_gap_m)
    onset = cfg.onset_gap_over_effective_radius * radius
    outer = 6.0 * math.pi * dynamic_viscosity_pa_s * radius * cfg.outer_drag_scale
    if not cfg.enabled or free_speed <= 0.0 or gap > onset:
        return LubricationResponse(
            active=False,
            free_closing_speed_m_s=free_speed,
            coupled_closing_speed_m_s=free_speed,
            correction_speed_m_s=0.0,
            lubrication_resistance_n_s_m=0.0,
            outer_resistance_n_s_m=outer,
            resistance_ratio=0.0,
            force_n=0.0,
            center_pressure_pa=0.0,
            characteristic_patch_radius_m=math.sqrt(max(2.0 * radius * gap, 0.0)),
            radial_drainage_rate_m3_s=0.0,
            viscous_dissipation_w=0.0,
        )

    lubrication = 6.0 * math.pi * dynamic_viscosity_pa_s * radius * radius / gap
    coupled = free_speed * outer / (outer + lubrication)
    force = lubrication * coupled
    pressure = reynolds_sphere_pressure_pa(radius, gap, coupled, dynamic_viscosity_pa_s)
    patch_radius = math.sqrt(2.0 * radius * gap)
    patch_area = math.pi * patch_radius * patch_radius
    drainage_rate = patch_area * coupled
    return LubricationResponse(
        active=True,
        free_closing_speed_m_s=free_speed,
        coupled_closing_speed_m_s=coupled,
        correction_speed_m_s=free_speed - coupled,
        lubrication_resistance_n_s_m=lubrication,
        outer_resistance_n_s_m=outer,
        resistance_ratio=lubrication / outer,
        force_n=force,
        center_pressure_pa=pressure,
        characteristic_patch_radius_m=patch_radius,
        radial_drainage_rate_m3_s=drainage_rate,
        viscous_dissipation_w=force * coupled,
    )


def apply_pair_translation(
    fronts: Iterable[FilmFront],
    geometry: GapGeometry,
    separation_correction_m: float,
    volume_relative_tolerance: float = 5.0e-12,
) -> dict[str, float]:
    """Apply equal/opposite rigid translations, preserving each closed gas volume."""
    correction = float(separation_correction_m)
    if correction < 0.0:
        raise ValueError("lubrication separation correction must be non-negative")
    if volume_relative_tolerance <= 0.0:
        raise ValueError("volume tolerance must be positive")
    front_list = list(fronts)
    a = _front_for_id(front_list, geometry.parent_ids[0])
    b = _front_for_id(front_list, geometry.parent_ids[1])
    before = {a.bubble_id: a.volume(), b.bubble_id: b.volume()}
    half = 0.5 * correction
    delta_a = mul(geometry.normal_a_to_b, -half)
    delta_b = mul(geometry.normal_a_to_b, half)
    if correction > 0.0:
        a.vertices = [
            (point[0] + delta_a[0], point[1] + delta_a[1], point[2] + delta_a[2])
            for point in a.vertices
        ]
        b.vertices = [
            (point[0] + delta_b[0], point[1] + delta_b[1], point[2] + delta_b[2])
            for point in b.vertices
        ]
    errors: dict[str, float] = {}
    for front in (a, b):
        old = before[front.bubble_id]
        error = abs(front.volume() - old) / max(old, 1.0e-300)
        errors[front.bubble_id] = error
        if error > volume_relative_tolerance:
            raise RuntimeError(
                f"rigid lubrication correction changed {front.bubble_id} volume by {error:.3e}"
            )
    return errors
