"""Runtime parsing for accepted tracked-film SDF solid boundaries.

This module translates canonical SCENARIO data into the already-accepted
``bubblelab.solvers.boundary`` objects.  It intentionally contains no contact
physics of its own.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from bubblelab.solvers.boundary import (
    AxisAlignedBoxBoundary,
    PlaneBoundary,
    SolidBoundary,
    SphereBoundary,
    WettingParameters,
)


class BoundaryRuntimeConfigurationError(ValueError):
    """Invalid deterministic runtime boundary configuration."""


class UnsupportedBoundaryFeature(BoundaryRuntimeConfigurationError):
    """Boundary request exceeds the accepted tracked-film SDF model."""


_NO_SLIP_KEYS = {
    "no_slip",
    "bulk_no_slip",
    "bulk_wall_condition",
    "bulk_eulerian_wall_coupling",
    "resolved_bulk_wall_coupling",
}


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BoundaryRuntimeConfigurationError(f"{label} must be an object")
    return value


def _vec3(value: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise BoundaryRuntimeConfigurationError(f"{label} must contain exactly three numbers")
    try:
        result = tuple(float(component) for component in value)
    except (TypeError, ValueError) as exc:
        raise BoundaryRuntimeConfigurationError(f"{label} must contain exactly three numbers") from exc
    if not all(component == component and abs(component) != float("inf") for component in result):
        raise BoundaryRuntimeConfigurationError(f"{label} must contain finite numbers")
    return result  # type: ignore[return-value]


def _reject_unknown(spec: Mapping[str, Any], allowed: set[str], label: str) -> None:
    no_slip = sorted(set(spec) & _NO_SLIP_KEYS)
    if no_slip:
        raise UnsupportedBoundaryFeature(
            "resolved no-slip bulk-wall CFD is not implemented by the transient runtime; "
            f"unsupported parameter(s): {', '.join(no_slip)}"
        )
    unknown = sorted(set(spec) - allowed)
    if unknown:
        raise BoundaryRuntimeConfigurationError(
            f"unsupported {label} parameter(s): {', '.join(unknown)}"
        )


def _wetting(boundary_id: str, value: Any) -> WettingParameters:
    if value is None:
        return WettingParameters()
    spec = _mapping(value, f"boundary {boundary_id!r} wetting")
    _reject_unknown(
        spec,
        {
            "target_contact_angle_deg",
            "relaxation",
            "iterations",
            "contact_band_m",
        },
        f"boundary {boundary_id!r} wetting",
    )
    try:
        return WettingParameters(
            target_contact_angle_deg=(
                None
                if spec.get("target_contact_angle_deg") is None
                else float(spec["target_contact_angle_deg"])
            ),
            relaxation=float(spec.get("relaxation", 0.45)),
            iterations=int(spec.get("iterations", 3)),
            contact_band_m=float(spec.get("contact_band_m", 2.0e-3)),
        )
    except (TypeError, ValueError) as exc:
        raise BoundaryRuntimeConfigurationError(
            f"invalid wetting configuration for boundary {boundary_id!r}: {exc}"
        ) from exc


def _parse_boundary(value: Any) -> SolidBoundary:
    spec = _mapping(value, "solid boundary")
    boundary_id = spec.get("id")
    if not isinstance(boundary_id, str) or not boundary_id:
        raise BoundaryRuntimeConfigurationError("solid boundary id must be a non-empty string")
    kind = spec.get("type")
    if not isinstance(kind, str) or not kind:
        raise BoundaryRuntimeConfigurationError(f"boundary {boundary_id!r} type is required")
    normalized = kind.strip().upper()
    common = {"id", "type", "wall_velocity_m_s", "wetting"}
    wall_velocity = _vec3(spec.get("wall_velocity_m_s", (0.0, 0.0, 0.0)), f"boundary {boundary_id!r} wall_velocity_m_s")
    wetting = _wetting(boundary_id, spec.get("wetting"))

    try:
        if normalized in {"PLANE", "FLOOR"}:
            _reject_unknown(spec, common | {"point_m", "normal_outward"}, f"boundary {boundary_id!r}")
            if "point_m" not in spec or "normal_outward" not in spec:
                raise BoundaryRuntimeConfigurationError(
                    f"plane boundary {boundary_id!r} requires point_m and normal_outward"
                )
            return PlaneBoundary(
                boundary_id=boundary_id,
                wall_velocity_m_s=wall_velocity,
                wetting=wetting,
                point_m=_vec3(spec["point_m"], f"boundary {boundary_id!r} point_m"),
                normal_outward=_vec3(spec["normal_outward"], f"boundary {boundary_id!r} normal_outward"),
            )
        if normalized == "SPHERE":
            _reject_unknown(spec, common | {"center_m", "radius_m"}, f"boundary {boundary_id!r}")
            if "center_m" not in spec or "radius_m" not in spec:
                raise BoundaryRuntimeConfigurationError(
                    f"sphere boundary {boundary_id!r} requires center_m and radius_m"
                )
            return SphereBoundary(
                boundary_id=boundary_id,
                wall_velocity_m_s=wall_velocity,
                wetting=wetting,
                center_m=_vec3(spec["center_m"], f"boundary {boundary_id!r} center_m"),
                radius_m=float(spec["radius_m"]),
            )
        if normalized in {"AABB", "AXIS_ALIGNED_BOX"}:
            _reject_unknown(spec, common | {"minimum_m", "maximum_m"}, f"boundary {boundary_id!r}")
            if "minimum_m" not in spec or "maximum_m" not in spec:
                raise BoundaryRuntimeConfigurationError(
                    f"AABB boundary {boundary_id!r} requires minimum_m and maximum_m"
                )
            return AxisAlignedBoxBoundary(
                boundary_id=boundary_id,
                wall_velocity_m_s=wall_velocity,
                wetting=wetting,
                minimum_m=_vec3(spec["minimum_m"], f"boundary {boundary_id!r} minimum_m"),
                maximum_m=_vec3(spec["maximum_m"], f"boundary {boundary_id!r} maximum_m"),
            )
    except BoundaryRuntimeConfigurationError:
        raise
    except (TypeError, ValueError) as exc:
        raise BoundaryRuntimeConfigurationError(
            f"invalid {normalized.lower()} boundary {boundary_id!r}: {exc}"
        ) from exc

    raise UnsupportedBoundaryFeature(
        f"unsupported solid boundary geometry {kind!r} for boundary {boundary_id!r}; "
        "supported types are plane/floor, sphere, and AABB"
    )


def solid_boundaries_from_scenario(scenario: Mapping[str, Any]) -> tuple[SolidBoundary, ...]:
    """Resolve ``environment.boundary_refs`` to deterministic SDF objects.

    Definitions live in ``user_editable.solid_boundaries`` and are selected by
    stable ID.  An empty/missing ``boundary_refs`` preserves legacy runtime
    behavior exactly by returning an empty tuple without interpreting boundary
    definitions.
    """
    environment = _mapping(scenario.get("environment") or {}, "environment")
    refs = environment.get("boundary_refs")
    if refs in (None, []):
        return ()
    if not isinstance(refs, list) or not all(isinstance(item, str) and item for item in refs):
        raise BoundaryRuntimeConfigurationError(
            "environment.boundary_refs must be an array of non-empty boundary IDs"
        )
    if len(refs) != len(set(refs)):
        raise BoundaryRuntimeConfigurationError("environment.boundary_refs must not contain duplicates")

    editable = _mapping(scenario.get("user_editable") or {}, "user_editable")
    definitions = editable.get("solid_boundaries")
    if not isinstance(definitions, list) or not definitions:
        raise BoundaryRuntimeConfigurationError(
            "environment.boundary_refs requires user_editable.solid_boundaries definitions"
        )

    by_id: dict[str, Mapping[str, Any]] = {}
    for value in definitions:
        spec = _mapping(value, "solid boundary")
        boundary_id = spec.get("id")
        if not isinstance(boundary_id, str) or not boundary_id:
            raise BoundaryRuntimeConfigurationError("solid boundary id must be a non-empty string")
        if boundary_id in by_id:
            raise BoundaryRuntimeConfigurationError(f"duplicate solid boundary id: {boundary_id}")
        by_id[boundary_id] = spec

    missing = [boundary_id for boundary_id in refs if boundary_id not in by_id]
    if missing:
        raise BoundaryRuntimeConfigurationError(
            "unknown boundary reference(s): " + ", ".join(missing)
        )

    return tuple(_parse_boundary(by_id[boundary_id]) for boundary_id in refs)
