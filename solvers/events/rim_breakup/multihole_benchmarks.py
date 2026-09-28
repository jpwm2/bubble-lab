from __future__ import annotations
from dataclasses import replace
from .multihole_solver import MultiHoleRimBreakupConfig, evolve_multihole_rim_breakup, evolve_isolated_superposition_reference


def interaction_benchmark() -> dict[str, object]:
    cfg = MultiHoleRimBreakupConfig()
    result = evolve_multihole_rim_breakup(cfg)
    isolated = evolve_isolated_superposition_reference(cfg)
    probe_time = min(0.10, 0.9 * result.detachment_time_s)
    coupled_probe = min(result.samples, key=lambda s: abs(s.time_s - probe_time))
    isolated_probe = min(isolated.samples, key=lambda s: abs(s.time_s - probe_time))
    neck_change = max(abs(a-b)/max(abs(b),1e-12) for a,b in zip(coupled_probe.hole_neck_radius_ratios, isolated_probe.hole_neck_radius_ratios))
    event_shift = abs(result.detachment_time_s-isolated.detachment_time_s)/isolated.detachment_time_s
    coupled_mass = [sum(d.volume_m3 for d in result.droplets if d.source_hole==h) for h in (0,1)]
    isolated_mass = [sum(d.volume_m3 for d in isolated.droplets if d.source_hole==h) for h in (0,1)]
    coupled_share = coupled_mass[0]/sum(coupled_mass)
    isolated_share = isolated_mass[0]/sum(isolated_mass)
    return {
        'interaction_onset_time_s': result.interaction_onset_time_s,
        'ligament_onset_time_s': result.ligament_onset_time_s,
        'detachment_time_s': result.detachment_time_s,
        'isolated_detachment_time_s': isolated.detachment_time_s,
        'detachment_time_relative_shift': event_shift,
        'probe_time_s': probe_time,
        'neck_trajectory_relative_change': neck_change,
        'detached_mass_share_change': abs(coupled_share-isolated_share),
        'final_gap_m': result.final_gap_m,
        'state_model': result.provenance['state_model'],
        'interaction_model': result.provenance['interaction_model'],
        'independent_run_stitching': result.provenance['independent_run_stitching'],
    }


def mode_coupling_benchmark() -> dict[str, object]:
    cfg = MultiHoleRimBreakupConfig()
    result = evolve_multihole_rim_breakup(cfg)
    isolated = evolve_isolated_superposition_reference(cfg)
    probe_time = 0.10
    coupled_probe = min(result.samples, key=lambda s: abs(s.time_s-probe_time))
    isolated_probe = min(isolated.samples, key=lambda s: abs(s.time_s-probe_time))
    changes=[]
    for hole in (0,1):
        coupled = dict(coupled_probe.hole_mode_amplitudes[hole])
        reference = dict(isolated_probe.hole_mode_amplitudes[hole])
        for mode in coupled:
            changes.append(abs(coupled[mode]-reference[mode])/reference[mode])
    return {
        'probe_time_s': coupled_probe.time_s,
        'hole_modes': [list(row) for row in cfg.hole_modes],
        'initial_mode_amplitudes': [[list(pair) for pair in row] for row in result.initial_mode_amplitudes],
        'coupled_probe_mode_amplitudes': [[list(pair) for pair in row] for row in coupled_probe.hole_mode_amplitudes],
        'isolated_probe_mode_amplitudes': [[list(pair) for pair in row] for row in isolated_probe.hole_mode_amplitudes],
        'max_interaction_mode_relative_change': max(changes),
        'coupled_bridge_fraction': coupled_probe.bridge_fraction,
        'coupled_exchange_fraction': coupled_probe.exchange_fraction,
    }


def conservation_benchmark() -> dict[str, object]:
    result = evolve_multihole_rim_breakup()
    per_hole = [sum(d.volume_m3 for d in result.droplets if d.source_hole==hole) for hole in (0,1)]
    return {
        'liquid_volume_relative_error': result.liquid_volume_relative_error,
        'pre_detachment_rim_volume_m3': result.pre_detachment_rim_volume_m3,
        'droplet_volume_m3': result.droplet_volume_m3,
        'rim_volume_by_hole_m3': list(result.final_rim_volume_m3),
        'droplet_volume_by_hole_m3': per_hole,
        'droplet_count': len(result.droplets),
        'neck_count_by_hole': [len(row) for row in result.neck_cells],
    }


def response_benchmark() -> dict[str, object]:
    base = MultiHoleRimBreakupConfig(max_time_s=0.4)
    cases = {
        'gamma_low': replace(base, surface_tension_n_m=4e-4),
        'gamma_high': replace(base, surface_tension_n_m=6e-4),
        'rho_low': replace(base, density_kg_m3=0.8),
        'rho_high': replace(base, density_kg_m3=1.2),
        'mu_low': replace(base, dynamic_viscosity_pa_s=5e-6),
        'mu_high': replace(base, dynamic_viscosity_pa_s=3e-5),
    }
    results = {key: evolve_multihole_rim_breakup(config) for key,config in cases.items()}
    return {key: {'detachment_time_s': value.detachment_time_s, 'mean_retraction_speed_m_s': sum(value.final_retraction_speeds_m_s)/2.0} for key,value in results.items()}


def refinement_benchmark() -> dict[str, object]:
    dts=(8e-4,4e-4,2e-4)
    results=[evolve_multihole_rim_breakup(MultiHoleRimBreakupConfig(time_step_s=dt)) for dt in dts]
    probes=[]
    for result in results:
        sample=min(result.samples,key=lambda s:abs(s.time_s-0.08))
        probes.append((sample.hole_radii_m[0],dict(sample.hole_mode_amplitudes[0])[10]))
    return {
        'time_steps_s': list(dts),
        'detachment_times_s': [r.detachment_time_s for r in results],
        'coarse_medium_event_change_s': abs(results[0].detachment_time_s-results[1].detachment_time_s),
        'medium_fine_event_change_s': abs(results[1].detachment_time_s-results[2].detachment_time_s),
        'coarse_medium_radius_change_m': abs(probes[0][0]-probes[1][0]),
        'medium_fine_radius_change_m': abs(probes[1][0]-probes[2][0]),
        'coarse_medium_mode_change': abs(probes[0][1]-probes[1][1]),
        'medium_fine_mode_change': abs(probes[1][1]-probes[2][1]),
    }


def replay_benchmark() -> dict[str, object]:
    first=evolve_multihole_rim_breakup()
    second=evolve_multihole_rim_breakup()
    exact = first.solver_digest==second.solver_digest and first.droplets==second.droplets and first.final_mode_amplitudes==second.final_mode_amplitudes
    return {'exact_replay': exact, 'solver_digest': first.solver_digest, 'droplet_ids': [d.id for d in first.droplets]}


def run(name: str) -> dict[str, object]:
    funcs = {
        'multihole-interaction': interaction_benchmark,
        'multihole-mode-coupling': mode_coupling_benchmark,
        'multihole-conservation': conservation_benchmark,
        'multihole-response': response_benchmark,
        'multihole-refinement': refinement_benchmark,
        'multihole-replay': replay_benchmark,
    }
    if name not in funcs:
        raise ValueError(f'unknown multihole benchmark {name}')
    return funcs[name]()


def assert_benchmark(name: str, payload: dict[str, object]) -> None:
    if name == 'multihole-interaction':
        if not float(payload['interaction_onset_time_s']) <= float(payload['ligament_onset_time_s']) < float(payload['detachment_time_s']):
            raise AssertionError('rim interaction must begin before or during ligament formation')
        if float(payload['detachment_time_relative_shift']) < 0.05:
            raise AssertionError('interacting detachment differs by less than 5% from isolated superposition')
        if float(payload['neck_trajectory_relative_change']) < 0.05:
            raise AssertionError('interacting neck trajectory differs by less than 5% from isolated superposition')
        if float(payload['final_gap_m']) <= 0.0:
            raise AssertionError('default interacting evidence should precede hole coalescence')
        if payload['independent_run_stitching'] != 'NOT_USED':
            raise AssertionError('stitched independent runs do not qualify')
    elif name == 'multihole-mode-coupling':
        if len(payload['hole_modes']) != 2 or min(len(row) for row in payload['hole_modes']) < 2:
            raise AssertionError('both rims must carry simultaneous modal content')
        if float(payload['max_interaction_mode_relative_change']) < 0.05 or float(payload['coupled_bridge_fraction']) <= 0.0:
            raise AssertionError('shared-state interaction did not measurably alter mode evolution')
    elif name == 'multihole-conservation':
        if float(payload['liquid_volume_relative_error']) > 1e-12:
            raise AssertionError('multihole liquid-volume conservation failed')
        if abs(float(payload['pre_detachment_rim_volume_m3'])-float(payload['droplet_volume_m3'])) > 1e-12:
            raise AssertionError('detached volume does not equal pre-detachment rim volume')
        if max(abs(float(a)-float(b)) for a,b in zip(payload['rim_volume_by_hole_m3'],payload['droplet_volume_by_hole_m3'])) > 1e-12:
            raise AssertionError('per-hole conservative partition failed')
        if int(payload['droplet_count']) != sum(int(x) for x in payload['neck_count_by_hole']):
            raise AssertionError('fragment count is not derived from evolved necks')
    elif name == 'multihole-response':
        if not payload['gamma_high']['mean_retraction_speed_m_s'] > payload['gamma_low']['mean_retraction_speed_m_s']:
            raise AssertionError('surface-tension response failed')
        if not payload['rho_low']['mean_retraction_speed_m_s'] > payload['rho_high']['mean_retraction_speed_m_s']:
            raise AssertionError('inertial-density response failed')
        if not payload['mu_high']['detachment_time_s'] > payload['mu_low']['detachment_time_s']:
            raise AssertionError('viscous detachment response failed')
    elif name == 'multihole-refinement':
        if not payload['medium_fine_event_change_s'] < payload['coarse_medium_event_change_s']:
            raise AssertionError('multihole event time did not improve under refinement')
        if not payload['medium_fine_radius_change_m'] < payload['coarse_medium_radius_change_m']:
            raise AssertionError('multihole trajectory did not improve under refinement')
        if not payload['medium_fine_mode_change'] < payload['coarse_medium_mode_change']:
            raise AssertionError('multihole mode evolution did not improve under refinement')
    elif name == 'multihole-replay' and not bool(payload['exact_replay']):
        raise AssertionError('multihole deterministic replay mismatch')
