from __future__ import annotations
from dataclasses import asdict
import math
from typing import Any, Mapping
from bubblelab.solvers.events.rim_breakup.multimode_solver import MultimodeRimBreakupConfig, evolve_multimode_rim_breakup

_FIELDS = {"azimuthal_cells","outer_radius_m","initial_mean_hole_radius_m","hole_asymmetry_fraction","hole_asymmetry_mode","film_thickness_m","density_kg_m3","dynamic_viscosity_pa_s","surface_tension_n_m","disturbance_modes","disturbance_amplitudes","disturbance_phases_rad","rim_drag_coefficient","time_step_s","max_time_s","ligament_amplitude_fraction","detachment_neck_radius_ratio","partition_neck_radius_ratio"}


def _config(scenario: Mapping[str, Any]) -> MultimodeRimBreakupConfig:
    editable = scenario.get("user_editable")
    if not isinstance(editable, Mapping): raise ValueError("user_editable must be an object")
    raw = editable.get("rim_multimode_breakup")
    if not isinstance(raw, Mapping): raise ValueError("user_editable.rim_multimode_breakup is required")
    if raw.get("model") != "ASYMMETRIC_MULTIMODE_RIM_SLENDER_JET_V1": raise ValueError("unsupported multimode rim breakup model")
    values = {key: raw[key] for key in _FIELDS if key in raw}
    for key in ("disturbance_modes","disturbance_amplitudes","disturbance_phases_rad"):
        if key in values: values[key] = tuple(values[key])
    return MultimodeRimBreakupConfig(**values)


def run_rim_multimode_breakup_runtime(scenario: Mapping[str, Any]) -> dict[str, Any]:
    config = _config(scenario)
    result = evolve_multimode_rim_breakup(config)
    runtime = scenario.get("runtime", {})
    continuation_dt = float(runtime.get("continuation_dt_s", 0.01)) if isinstance(runtime, Mapping) else 0.01
    if not math.isfinite(continuation_dt) or continuation_dt < 0.0: raise ValueError("runtime.continuation_dt_s must be finite and non-negative")
    droplets=[]
    for drop in result.droplets:
        x0,y0=drop.position_m
        droplets.append({"id":drop.id,"volume_m3":drop.volume_m3,"mass_kg":drop.mass_kg,"equivalent_radius_m":drop.equivalent_radius_m,"position_m":[x0,y0,0.0],"velocity_m_s":[drop.velocity_m_s[0],drop.velocity_m_s[1],0.0],"momentum_kg_m_s":[drop.momentum_kg_m_s[0],drop.momentum_kg_m_s[1],0.0],"continued_position_m":[x0+continuation_dt*drop.velocity_m_s[0],y0+continuation_dt*drop.velocity_m_s[1],0.0],"source_cells":[drop.source_start_cell,drop.source_end_cell]})
    return {"status":"PASS","scenario_id":str(scenario.get("scenario_id","rim-multimode-breakup-runtime")),"supported_class":result.provenance["supported_class"],"event_sequence":[{"type":"ASYMMETRIC_RIM_RETRACTION","time_s":result.samples[1].time_s},{"type":"MULTIMODE_LIGAMENT_ONSET","time_s":result.ligament_onset_time_s},{"type":"STATE_DERIVED_DROPLET_DETACHMENT","time_s":result.detachment_time_s}],"rim":{"final_mean_hole_radius_m":result.final_mean_hole_radius_m,"final_retraction_speed_m_s":result.final_retraction_speed_m_s,"taylor_culick_reference_m_s":config.taylor_culick_speed_m_s,"hole_asymmetry_fraction":config.hole_asymmetry_fraction,"seed_modes":list(config.disturbance_modes),"initial_mode_amplitudes":dict(result.initial_mode_amplitudes),"final_mode_amplitudes":dict(result.final_mode_amplitudes),"evolved_neck_cells":list(result.neck_cells),"volume_per_radian_m3":list(result.final_volume_per_radian_m3),"tangential_velocity_m_s":list(result.final_tangential_velocity_m_s)},"droplets":droplets,"budgets":{"initial_liquid_volume_m3":result.initial_liquid_volume_m3,"remaining_film_volume_m3":result.remaining_film_volume_m3,"detached_droplet_volume_m3":result.droplet_volume_m3,"liquid_volume_relative_error":result.liquid_volume_relative_error,"scalar_radial_momentum_kg_m_s":result.scalar_radial_momentum_kg_m_s,"capillary_impulse_n_s":result.capillary_impulse_n_s,"viscous_impulse_n_s":result.viscous_impulse_n_s,"radial_momentum_residual_kg_m_s":result.radial_momentum_residual_kg_m_s},"continuation":{"model":"BALLISTIC_FIRST_POST_DETACHMENT_SAMPLE","dt_s":continuation_dt,"source_solver_digest":result.solver_digest,"exact_evolved_velocity_seed":True},"provenance":result.provenance,"solver_digest":result.solver_digest,"config":asdict(config),"claim_boundary":{"unrestricted_3d_multi_hole_interaction":"UNSUPPORTED","singular_3d_ligament_pinchoff":"UNSUPPORTED","turbulent_atomization":"UNSUPPORTED","aerodynamic_secondary_breakup":"UNSUPPORTED","broad_spray_statistics":"UNSUPPORTED"}}
