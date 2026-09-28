from __future__ import annotations
from dataclasses import asdict
import math
from typing import Any, Mapping
from bubblelab.solvers.events.rim_breakup import RimBreakupConfig, evolve_rim_breakup

_CONFIG_FIELDS = {
    "azimuthal_cells", "outer_radius_m", "initial_hole_radius_m", "film_thickness_m",
    "density_kg_m3", "dynamic_viscosity_pa_s", "surface_tension_n_m", "azimuthal_mode",
    "initial_radius_perturbation_fraction", "rim_drag_coefficient", "time_step_s", "max_time_s",
    "ligament_amplitude_fraction", "detachment_neck_radius_ratio",
}


def _config(scenario: Mapping[str, Any]) -> RimBreakupConfig:
    editable = scenario.get("user_editable")
    if not isinstance(editable, Mapping):
        raise ValueError("user_editable must be an object")
    raw = editable.get("rim_breakup")
    if not isinstance(raw, Mapping):
        raise ValueError("user_editable.rim_breakup is required")
    if raw.get("model") != "EXPANDING_TOROIDAL_RIM_SLENDER_JET_V1":
        raise ValueError("unsupported rim breakup model")
    return RimBreakupConfig(**{key: raw[key] for key in _CONFIG_FIELDS if key in raw})


def run_rim_breakup_runtime(scenario: Mapping[str, Any]) -> dict[str, Any]:
    config = _config(scenario)
    result = evolve_rim_breakup(config)
    runtime = scenario.get("runtime", {})
    continuation_dt = float(runtime.get("continuation_dt_s", 0.01)) if isinstance(runtime, Mapping) else 0.01
    if not math.isfinite(continuation_dt) or continuation_dt < 0.0:
        raise ValueError("runtime.continuation_dt_s must be finite and non-negative")
    droplets = []
    for drop in result.droplets:
        x0 = result.final_hole_radius_m * math.cos(drop.centroid_angle_rad)
        y0 = result.final_hole_radius_m * math.sin(drop.centroid_angle_rad)
        droplets.append({
            "id": drop.id,
            "volume_m3": drop.volume_m3,
            "mass_kg": drop.mass_kg,
            "equivalent_radius_m": drop.equivalent_radius_m,
            "position_m": [x0, y0, 0.0],
            "velocity_m_s": [drop.velocity_m_s[0], drop.velocity_m_s[1], 0.0],
            "momentum_kg_m_s": [drop.momentum_kg_m_s[0], drop.momentum_kg_m_s[1], 0.0],
            "continued_position_m": [x0 + continuation_dt * drop.velocity_m_s[0], y0 + continuation_dt * drop.velocity_m_s[1], 0.0],
            "source_cells": [drop.source_start_cell, drop.source_end_cell],
        })
    return {
        "status": "PASS",
        "scenario_id": str(scenario.get("scenario_id", "rim-breakup-runtime")),
        "supported_class": result.provenance["supported_class"],
        "event_sequence": [
            {"type": "RIM_RETRACTION", "time_s": result.samples[1].time_s},
            {"type": "LIGAMENT_ONSET", "time_s": result.ligament_onset_time_s},
            {"type": "DROPLET_DETACHMENT", "time_s": result.detachment_time_s},
        ],
        "rim": {
            "final_hole_radius_m": result.final_hole_radius_m,
            "final_retraction_speed_m_s": result.final_retraction_speed_m_s,
            "taylor_culick_reference_m_s": config.taylor_culick_speed_m_s,
            "volume_per_radian_m3": list(result.final_volume_per_radian_m3),
            "tangential_velocity_m_s": list(result.final_tangential_velocity_m_s),
        },
        "droplets": droplets,
        "budgets": {
            "initial_liquid_volume_m3": result.initial_liquid_volume_m3,
            "remaining_film_volume_m3": result.remaining_film_volume_m3,
            "detached_droplet_volume_m3": result.droplet_volume_m3,
            "liquid_volume_relative_error": result.liquid_volume_relative_error,
            "scalar_radial_momentum_kg_m_s": result.scalar_radial_momentum_kg_m_s,
            "capillary_impulse_n_s": result.capillary_impulse_n_s,
            "viscous_impulse_n_s": result.viscous_impulse_n_s,
            "radial_momentum_residual_kg_m_s": result.radial_momentum_residual_kg_m_s,
            "initial_surface_energy_j": result.initial_surface_energy_j,
            "final_surface_energy_j": result.final_surface_energy_j,
            "kinetic_energy_j": result.kinetic_energy_j,
            "surface_plus_kinetic_change_j": result.surface_plus_kinetic_change_j,
        },
        "continuation": {
            "model": "BALLISTIC_FIRST_POST_DETACHMENT_SAMPLE",
            "dt_s": continuation_dt,
            "source_solver_digest": result.solver_digest,
            "exact_evolved_velocity_seed": True,
        },
        "provenance": result.provenance,
        "solver_digest": result.solver_digest,
        "config": asdict(config),
        "claim_boundary": {
            "arbitrary_3d_multi_hole_rupture": "UNSUPPORTED",
            "broad_spray_size_distribution": "UNSUPPORTED",
            "turbulent_atomization": "UNSUPPORTED",
            "post_detachment_aerodynamic_droplet_cfd": "UNSUPPORTED",
        },
    }
