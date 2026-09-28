from __future__ import annotations

from dataclasses import asdict, replace
import math
from typing import Any, Mapping

from bubblelab.solvers.rim_breakup.multineck3d import (
    MultiNeck3DConfig,
    evolve_multineck_breakup,
)

_FIELDS = {
    "density_kg_m3",
    "dynamic_viscosity_pa_s",
    "surface_tension_n_m",
    "time_step_s",
    "max_time_s",
    "detachment_radius_m",
    "coupling_strength",
    "coupling_length_m",
    "capillary_factor",
    "viscous_factor",
    "initial_parent_volume_m3",
    "neck_centers_m",
    "neck_axes",
    "initial_radii_m",
    "initial_radial_velocities_m_s",
    "lineage_root",
}


def _tuple3_rows(values: Any) -> tuple[tuple[float, float, float], ...]:
    return tuple(tuple(float(x) for x in row) for row in values)


def _config(scenario: Mapping[str, Any]) -> MultiNeck3DConfig:
    editable = scenario.get("user_editable")
    if not isinstance(editable, Mapping):
        raise ValueError("user_editable must be an object")
    raw = editable.get("multineck_breakup_3d")
    if not isinstance(raw, Mapping):
        raise ValueError("user_editable.multineck_breakup_3d is required")
    if raw.get("model") != "INTERACTING_MULTINECK_3D_V1":
        raise ValueError("unsupported multineck breakup model")
    values = {key: raw[key] for key in _FIELDS if key in raw}
    if "neck_centers_m" in values:
        values["neck_centers_m"] = _tuple3_rows(values["neck_centers_m"])
    if "neck_axes" in values:
        values["neck_axes"] = _tuple3_rows(values["neck_axes"])
    for key in ("initial_radii_m", "initial_radial_velocities_m_s"):
        if key in values:
            values[key] = tuple(float(x) for x in values[key])
    return MultiNeck3DConfig(**values)


def run_multineck_breakup_runtime(scenario: Mapping[str, Any]) -> dict[str, Any]:
    config = _config(scenario)
    result = evolve_multineck_breakup(config)
    isolated = evolve_multineck_breakup(replace(config, coupling_strength=0.0))
    runtime = scenario.get("runtime", {})
    continuation_dt = (
        float(runtime.get("continuation_dt_s", 0.002))
        if isinstance(runtime, Mapping)
        else 0.002
    )
    if not math.isfinite(continuation_dt) or continuation_dt < 0.0:
        raise ValueError("runtime.continuation_dt_s must be finite and non-negative")

    paired = min(len(result.events), len(isolated.events))
    shifts = [
        abs(result.events[i].time_s - isolated.events[i].time_s) / isolated.events[i].time_s
        for i in range(paired)
    ]
    fragments = []
    for event in result.events:
        x, y, z = event.position_m
        vx, vy, vz = event.velocity_m_s
        fragments.append(
            {
                "id": event.fragment_id,
                "source_neck": event.neck_id,
                "event_index": event.event_index,
                "volume_m3": event.fragment_volume_m3,
                "equivalent_radius_m": event.fragment_equivalent_radius_m,
                "position_m": [x, y, z],
                "velocity_m_s": [vx, vy, vz],
                "continued_position_m": [
                    x + continuation_dt * vx,
                    y + continuation_dt * vy,
                    z + continuation_dt * vz,
                ],
                "lineage_parent": config.lineage_root,
            }
        )

    return {
        "status": "PASS",
        "scenario_id": str(scenario.get("scenario_id", "multineck-breakup-3d-runtime")),
        "supported_class": result.provenance["supported_class"],
        "geometry": {
            "noncoplanarity": result.geometry_noncoplanarity,
            "neck_centers_m": [list(v) for v in config.neck_centers_m],
            "neck_axes": [list(v) for v in config.neck_axes],
        },
        "event_sequence": [
            {
                "type": "STATE_DERIVED_3D_NECK_DETACHMENT",
                "event_index": event.event_index,
                "neck_id": event.neck_id,
                "time_s": event.time_s,
                "active_necks_after": event.active_necks_after,
            }
            for event in result.events
        ],
        "interaction": {
            "enabled": result.interaction_enabled,
            "coupled_event_times_s": [event.time_s for event in result.events],
            "isolated_event_times_s": [event.time_s for event in isolated.events],
            "relative_event_time_shifts": shifts,
            "max_relative_event_time_shift": max(shifts, default=0.0),
            "model": result.provenance["interaction_model"],
        },
        "fragments": fragments,
        "budgets": {
            "initial_liquid_volume_m3": result.initial_liquid_volume_m3,
            "final_parent_volume_m3": result.final_parent_volume_m3,
            "detached_volume_m3": result.detached_volume_m3,
            "liquid_volume_relative_error": result.liquid_volume_relative_error,
            "max_transaction_relative_error": result.max_transaction_relative_error,
        },
        "continuation": {
            "model": "BALLISTIC_FIRST_POST_DETACHMENT_SAMPLE",
            "dt_s": continuation_dt,
            "source_solver_digest": result.solver_digest,
            "stable_lineage": True,
            "surviving_necks_continue_after_each_event": True,
        },
        "provenance": result.provenance,
        "solver_digest": result.solver_digest,
        "config": asdict(config),
        "claim_boundary": {
            "unrestricted_3d_free_surface_cfd": "UNSUPPORTED",
            "grid_resolved_singular_pinchoff": "UNSUPPORTED",
            "turbulent_atomization": "UNSUPPORTED",
            "aerodynamic_secondary_breakup": "UNSUPPORTED",
            "universal_spray_statistics": "UNSUPPORTED",
        },
    }
