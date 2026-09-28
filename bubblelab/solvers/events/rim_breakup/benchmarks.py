from __future__ import annotations
import math
from .solver import RimBreakupConfig, evolve_rim_breakup, rayleigh_plateau_reference
from .multimode_solver import MultimodeRimBreakupConfig, evolve_multimode_rim_breakup


def retraction_benchmark() -> dict[str, object]:
    result = evolve_rim_breakup()
    reference = result.config.taylor_culick_speed_m_s
    measured = result.final_retraction_speed_m_s
    return {"reference_speed_m_s": reference, "measured_speed_m_s": measured, "relative_error": abs(measured-reference)/reference, "initial_speed_m_s": result.samples[0].retraction_speed_m_s, "capillary_impulse_n_s": result.capillary_impulse_n_s, "viscous_impulse_n_s": result.viscous_impulse_n_s}


def ligament_benchmark() -> dict[str, object]:
    result = evolve_rim_breakup()
    ref = rayleigh_plateau_reference(result.config)
    target = min(result.samples, key=lambda sample: abs(sample.time_s - 0.005))
    initial = result.samples[0]
    measured = math.log(target.mode_amplitude_fraction/initial.mode_amplitude_fraction)/target.time_s
    return {"reference_growth_rate_s_inv": ref["growth_rate_s_inv"], "measured_growth_rate_s_inv": measured, "relative_error": abs(measured-ref["growth_rate_s_inv"])/ref["growth_rate_s_inv"], "dimensionless_wavenumber": ref["dimensionless_wavenumber"], "ligament_onset_time_s": result.ligament_onset_time_s, "detachment_time_s": result.detachment_time_s, "initial_amplitude_fraction": initial.mode_amplitude_fraction, "ligament_amplitude_fraction": result.config.ligament_amplitude_fraction}


def conservation_benchmark() -> dict[str, object]:
    result = evolve_rim_breakup()
    return {"liquid_volume_relative_error": result.liquid_volume_relative_error, "radial_momentum_residual_kg_m_s": result.radial_momentum_residual_kg_m_s, "droplet_count": len(result.droplets), "initial_surface_energy_j": result.initial_surface_energy_j, "final_surface_energy_j": result.final_surface_energy_j, "kinetic_energy_j": result.kinetic_energy_j, "surface_plus_kinetic_change_j": result.surface_plus_kinetic_change_j}


def _interpolated_ligament_onset(result) -> float:
    threshold = result.config.ligament_amplitude_fraction
    for left, right in zip(result.samples, result.samples[1:]):
        y0 = left.mode_amplitude_fraction
        y1 = right.mode_amplitude_fraction
        if y0 < threshold <= y1:
            if y1 <= y0: raise RuntimeError("ligament threshold bracket is not increasing")
            fraction = (threshold - y0) / (y1 - y0)
            return left.time_s + fraction * (right.time_s - left.time_s)
    raise RuntimeError("ligament threshold was not bracketed by the evolved samples")


def refinement_benchmark() -> dict[str, object]:
    configs = [RimBreakupConfig(time_step_s=dt) for dt in (8e-4, 4e-4, 2e-4)]
    results = [evolve_rim_breakup(config) for config in configs]
    event_times = [_interpolated_ligament_onset(result) for result in results]
    trajectories = [r.final_hole_radius_m for r in results]
    return {"time_steps_s": [c.time_step_s for c in configs], "ligament_onset_times_s": event_times, "event_time_measurement": "LINEAR_INTERPOLATION_OF_EVOLVED_THRESHOLD_BRACKET", "final_hole_radii_m": trajectories, "coarse_medium_event_change_s": abs(event_times[0]-event_times[1]), "medium_fine_event_change_s": abs(event_times[1]-event_times[2]), "coarse_medium_trajectory_change_m": abs(trajectories[0]-trajectories[1]), "medium_fine_trajectory_change_m": abs(trajectories[1]-trajectories[2])}


def replay_benchmark() -> dict[str, object]:
    first = evolve_rim_breakup(); second = evolve_rim_breakup()
    exact = first.solver_digest == second.solver_digest and first.final_volume_per_radian_m3 == second.final_volume_per_radian_m3 and first.final_tangential_velocity_m_s == second.final_tangential_velocity_m_s and first.droplets == second.droplets
    return {"exact_replay": exact, "solver_digest": first.solver_digest, "droplet_ids": [d.id for d in first.droplets]}


def asymmetric_retraction_benchmark() -> dict[str, object]:
    r = evolve_multimode_rim_breakup(); c = r.config
    return {"initial_hole_radius_min_m": c.initial_mean_hole_radius_m*(1-c.hole_asymmetry_fraction), "initial_hole_radius_max_m": c.initial_mean_hole_radius_m*(1+c.hole_asymmetry_fraction), "reference_speed_m_s": c.taylor_culick_speed_m_s, "measured_speed_m_s": r.final_retraction_speed_m_s, "relative_speed_error": abs(r.final_retraction_speed_m_s-c.taylor_culick_speed_m_s)/c.taylor_culick_speed_m_s, "initial_speed_m_s": r.samples[0].retraction_speed_m_s}


def mode_competition_benchmark() -> dict[str, object]:
    r = evolve_multimode_rim_breakup(); initial = dict(r.initial_mode_amplitudes); final = dict(r.final_mode_amplitudes)
    return {"seed_modes": list(r.config.disturbance_modes), "initial_mode_amplitudes": initial, "final_mode_amplitudes": final, "growth_factors": {m: final[m]/initial[m] for m in initial}, "competition_ratio_initial": initial[r.config.disturbance_modes[1]]/initial[r.config.disturbance_modes[0]], "competition_ratio_final": final[r.config.disturbance_modes[1]]/final[r.config.disturbance_modes[0]], "evolved_neck_count": len(r.neck_cells), "droplet_count": len(r.droplets), "ligament_onset_time_s": r.ligament_onset_time_s, "detachment_time_s": r.detachment_time_s}


def multimode_conservation_benchmark() -> dict[str, object]:
    r = evolve_multimode_rim_breakup()
    return {"liquid_volume_relative_error": r.liquid_volume_relative_error, "radial_momentum_residual_kg_m_s": r.radial_momentum_residual_kg_m_s, "pre_detachment_rim_volume_m3": r.pre_detachment_rim_volume_m3, "droplet_volume_m3": r.droplet_volume_m3, "droplet_count": len(r.droplets)}


def multimode_response_benchmark() -> dict[str, object]:
    cases = {"gamma_low": MultimodeRimBreakupConfig(surface_tension_n_m=4e-4,max_time_s=.8), "gamma_high": MultimodeRimBreakupConfig(surface_tension_n_m=6e-4,max_time_s=.8), "rho_low": MultimodeRimBreakupConfig(density_kg_m3=.8,max_time_s=.8), "rho_high": MultimodeRimBreakupConfig(density_kg_m3=1.2,max_time_s=.8), "mu_low": MultimodeRimBreakupConfig(dynamic_viscosity_pa_s=5e-6,max_time_s=.8), "mu_high": MultimodeRimBreakupConfig(dynamic_viscosity_pa_s=3e-5,max_time_s=.8)}
    results = {k: evolve_multimode_rim_breakup(v) for k,v in cases.items()}
    return {k: {"detachment_time_s": r.detachment_time_s, "final_retraction_speed_m_s": r.final_retraction_speed_m_s} for k,r in results.items()}


def multimode_refinement_benchmark() -> dict[str, object]:
    dts = (8e-4,4e-4,2e-4); results = [evolve_multimode_rim_breakup(MultimodeRimBreakupConfig(time_step_s=dt)) for dt in dts]
    fixed=[]
    for r in results:
        s=min(r.samples,key=lambda x:abs(x.time_s-.02)); fixed.append((s.mean_hole_radius_m,dict(s.mode_amplitudes)[10]))
    return {"time_steps_s": list(dts), "detachment_times_s": [r.detachment_time_s for r in results], "coarse_medium_event_change_s": abs(results[0].detachment_time_s-results[1].detachment_time_s), "medium_fine_event_change_s": abs(results[1].detachment_time_s-results[2].detachment_time_s), "coarse_medium_radius_change_m": abs(fixed[0][0]-fixed[1][0]), "medium_fine_radius_change_m": abs(fixed[1][0]-fixed[2][0]), "coarse_medium_mode_change": abs(fixed[0][1]-fixed[1][1]), "medium_fine_mode_change": abs(fixed[1][1]-fixed[2][1])}


def multimode_replay_benchmark() -> dict[str, object]:
    first=evolve_multimode_rim_breakup(); second=evolve_multimode_rim_breakup()
    exact = first.solver_digest == second.solver_digest and first.final_volume_per_radian_m3 == second.final_volume_per_radian_m3 and first.final_tangential_velocity_m_s == second.final_tangential_velocity_m_s and first.droplets == second.droplets
    return {"exact_replay": exact, "solver_digest": first.solver_digest, "droplet_ids": [d.id for d in first.droplets]}


def run(name: str) -> dict[str, object]:
    funcs = {"retraction": retraction_benchmark, "ligament": ligament_benchmark, "conservation": conservation_benchmark, "refinement": refinement_benchmark, "replay": replay_benchmark, "asymmetric-retraction": asymmetric_retraction_benchmark, "mode-competition": mode_competition_benchmark, "multimode-conservation": multimode_conservation_benchmark, "multimode-response": multimode_response_benchmark, "multimode-refinement": multimode_refinement_benchmark, "multimode-replay": multimode_replay_benchmark}
    if name not in funcs: raise ValueError(f"unknown benchmark {name}")
    return funcs[name]()


def assert_benchmark(name: str, payload: dict[str, object]) -> None:
    if name == "retraction":
        if float(payload["initial_speed_m_s"]) != 0.0 or float(payload["relative_error"]) > 0.02: raise AssertionError("dynamically evolved rim retraction does not approach Taylor-Culick scaling")
    elif name == "ligament":
        q=float(payload["dimensionless_wavenumber"])
        if not 0.0 < q < 1.0 or float(payload["relative_error"]) > 0.12: raise AssertionError("early rim-mode growth does not match the long-wave Rayleigh-Plateau reference")
        if not float(payload["detachment_time_s"]) > float(payload["ligament_onset_time_s"]): raise AssertionError("detachment must follow dynamically detected ligament onset")
    elif name == "conservation":
        if float(payload["liquid_volume_relative_error"]) > 1e-12: raise AssertionError("liquid volume conservation gate failed")
        if abs(float(payload["radial_momentum_residual_kg_m_s"])) > 1e-12: raise AssertionError("radial momentum impulse accounting failed")
        if not all(math.isfinite(float(payload[key])) for key in ("initial_surface_energy_j","final_surface_energy_j","kinetic_energy_j","surface_plus_kinetic_change_j")): raise AssertionError("surface/kinetic energy budget was not reported finitely")
    elif name == "refinement":
        if payload.get("event_time_measurement") != "LINEAR_INTERPOLATION_OF_EVOLVED_THRESHOLD_BRACKET": raise AssertionError("refinement event time must be measured from evolved threshold brackets")
        if not float(payload["medium_fine_event_change_s"]) < float(payload["coarse_medium_event_change_s"]): raise AssertionError("ligament event time did not improve under temporal refinement")
        if not float(payload["medium_fine_trajectory_change_m"]) < float(payload["coarse_medium_trajectory_change_m"]): raise AssertionError("rim trajectory did not improve under temporal refinement")
    elif name == "replay" and not bool(payload["exact_replay"]): raise AssertionError("deterministic replay mismatch")
    elif name == "asymmetric-retraction":
        if not float(payload["initial_hole_radius_max_m"]) > float(payload["initial_hole_radius_min_m"]) or float(payload["initial_speed_m_s"]) != 0.0 or float(payload["relative_speed_error"]) > 0.03: raise AssertionError("asymmetric retraction gate failed")
    elif name == "mode-competition":
        if len(payload["seed_modes"]) < 2 or min(payload["initial_mode_amplitudes"].values()) <= 0.0 or min(payload["growth_factors"].values()) <= 1.0: raise AssertionError("simultaneous mode growth gate failed")
        if abs(float(payload["competition_ratio_final"])-float(payload["competition_ratio_initial"])) < 0.2: raise AssertionError("mode competition did not alter relative modal strength")
        if int(payload["droplet_count"]) in payload["seed_modes"] or int(payload["evolved_neck_count"]) != int(payload["droplet_count"]): raise AssertionError("detachment count appears mode-scripted")
        if not float(payload["detachment_time_s"]) > float(payload["ligament_onset_time_s"]) > 0.0: raise AssertionError("multimode event ordering failed")
    elif name == "multimode-conservation":
        if float(payload["liquid_volume_relative_error"]) > 1e-12 or abs(float(payload["radial_momentum_residual_kg_m_s"])) > 1e-12 or abs(float(payload["pre_detachment_rim_volume_m3"])-float(payload["droplet_volume_m3"])) > 1e-12: raise AssertionError("multimode conservation gate failed")
    elif name == "multimode-response":
        if not payload['gamma_high']['final_retraction_speed_m_s'] > payload['gamma_low']['final_retraction_speed_m_s']: raise AssertionError("surface tension response failed")
        if not payload['rho_low']['final_retraction_speed_m_s'] > payload['rho_high']['final_retraction_speed_m_s']: raise AssertionError("density response failed")
        if not payload['mu_high']['detachment_time_s'] > payload['mu_low']['detachment_time_s']: raise AssertionError("viscous response failed")
    elif name == "multimode-refinement":
        if not payload['medium_fine_event_change_s'] < payload['coarse_medium_event_change_s']: raise AssertionError("event refinement failed")
        if not payload['medium_fine_radius_change_m'] < payload['coarse_medium_radius_change_m']: raise AssertionError("trajectory refinement failed")
        if not payload['medium_fine_mode_change'] < payload['coarse_medium_mode_change']: raise AssertionError("mode refinement failed")
    elif name == "multimode-replay" and not bool(payload["exact_replay"]): raise AssertionError("multimode deterministic replay mismatch")
