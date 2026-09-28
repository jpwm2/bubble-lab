from __future__ import annotations
from dataclasses import asdict
import math
from typing import Any, Mapping
from bubblelab.solvers.events.rim_breakup.multihole_solver import MultiHoleRimBreakupConfig, evolve_multihole_rim_breakup, evolve_isolated_superposition_reference

_FIELDS = {
    'azimuthal_cells','outer_radius_m','hole_center_distance_m','initial_hole_radii_m','film_thickness_m','density_kg_m3','dynamic_viscosity_pa_s','surface_tension_n_m',
    'hole_modes','hole_amplitudes','hole_phases_rad','interaction_range_m','interaction_strength','bridge_target_fraction','bridge_sigma_rad','exchange_limit_fraction',
    'time_step_s','max_time_s','ligament_amplitude_fraction','detachment_neck_radius_ratio','partition_neck_radius_ratio'
}


def _config(scenario: Mapping[str, Any]) -> MultiHoleRimBreakupConfig:
    editable = scenario.get('user_editable')
    if not isinstance(editable, Mapping):
        raise ValueError('user_editable must be an object')
    raw = editable.get('multihole_rim_breakup')
    if not isinstance(raw, Mapping):
        raise ValueError('user_editable.multihole_rim_breakup is required')
    if raw.get('model') != 'INTERACTING_MULTIHOLE_RIM_V1':
        raise ValueError('unsupported multihole rim breakup model')
    values = {key: raw[key] for key in _FIELDS if key in raw}
    if 'initial_hole_radii_m' in values:
        values['initial_hole_radii_m'] = tuple(values['initial_hole_radii_m'])
    for key in ('hole_modes','hole_amplitudes','hole_phases_rad'):
        if key in values:
            values[key] = tuple(tuple(row) for row in values[key])
    return MultiHoleRimBreakupConfig(**values)


def run_multihole_rim_breakup_runtime(scenario: Mapping[str, Any]) -> dict[str, Any]:
    config = _config(scenario)
    result = evolve_multihole_rim_breakup(config)
    isolated = evolve_isolated_superposition_reference(config)
    runtime = scenario.get('runtime', {})
    continuation_dt = float(runtime.get('continuation_dt_s', 0.01)) if isinstance(runtime, Mapping) else 0.01
    if not math.isfinite(continuation_dt) or continuation_dt < 0.0:
        raise ValueError('runtime.continuation_dt_s must be finite and non-negative')
    droplets=[]
    for drop in result.droplets:
        x0,y0=drop.position_m
        droplets.append({
            'id': drop.id,
            'source_hole': drop.source_hole,
            'volume_m3': drop.volume_m3,
            'mass_kg': drop.mass_kg,
            'equivalent_radius_m': drop.equivalent_radius_m,
            'position_m': [x0,y0,0.0],
            'velocity_m_s': [drop.velocity_m_s[0],drop.velocity_m_s[1],0.0],
            'momentum_kg_m_s': [drop.momentum_kg_m_s[0],drop.momentum_kg_m_s[1],0.0],
            'continued_position_m': [x0+continuation_dt*drop.velocity_m_s[0],y0+continuation_dt*drop.velocity_m_s[1],0.0],
            'source_cells': [drop.source_start_cell,drop.source_end_cell],
        })
    holes=[]
    for hole in (0,1):
        holes.append({
            'hole_index': hole,
            'initial_radius_m': config.initial_hole_radii_m[hole],
            'final_radius_m': result.final_hole_radii_m[hole],
            'final_retraction_speed_m_s': result.final_retraction_speeds_m_s[hole],
            'seed_modes': list(config.hole_modes[hole]),
            'initial_mode_amplitudes': dict(result.initial_mode_amplitudes[hole]),
            'final_mode_amplitudes': dict(result.final_mode_amplitudes[hole]),
            'evolved_neck_cells': list(result.neck_cells[hole]),
            'rim_volume_m3': result.final_rim_volume_m3[hole],
        })
    relative_shift = abs(result.detachment_time_s-isolated.detachment_time_s)/isolated.detachment_time_s
    return {
        'status': 'PASS',
        'scenario_id': str(scenario.get('scenario_id','multihole-rim-breakup-runtime')),
        'supported_class': result.provenance['supported_class'],
        'event_sequence': [
            {'type':'TWO_HOLE_RETRACTION','time_s':result.samples[1].time_s},
            {'type':'RIM_INTERACTION_ONSET','time_s':result.interaction_onset_time_s},
            {'type':'MULTIHOLE_LIGAMENT_ONSET','time_s':result.ligament_onset_time_s},
            {'type':'STATE_DERIVED_MULTIRIM_DETACHMENT','time_s':result.detachment_time_s},
        ],
        'holes': holes,
        'interaction': {
            'final_gap_m': result.final_gap_m,
            'isolated_reference_detachment_time_s': isolated.detachment_time_s,
            'coupled_detachment_time_s': result.detachment_time_s,
            'detachment_time_relative_shift': relative_shift,
            'state_model': result.provenance['state_model'],
            'interaction_model': result.provenance['interaction_model'],
            'independent_run_stitching': result.provenance['independent_run_stitching'],
        },
        'droplets': droplets,
        'budgets': {
            'initial_liquid_volume_m3': result.initial_liquid_volume_m3,
            'remaining_film_volume_m3': result.remaining_film_volume_m3,
            'pre_detachment_rim_volume_m3': result.pre_detachment_rim_volume_m3,
            'detached_droplet_volume_m3': result.droplet_volume_m3,
            'liquid_volume_relative_error': result.liquid_volume_relative_error,
        },
        'continuation': {
            'model': 'BALLISTIC_FIRST_POST_DETACHMENT_SAMPLE',
            'dt_s': continuation_dt,
            'source_solver_digest': result.solver_digest,
            'exact_evolved_velocity_seed': True,
        },
        'provenance': result.provenance,
        'solver_digest': result.solver_digest,
        'config': asdict(config),
        'claim_boundary': {
            'unrestricted_3d_multi_hole_interaction':'UNSUPPORTED',
            'singular_3d_ligament_pinchoff':'UNSUPPORTED',
            'turbulent_atomization':'UNSUPPORTED',
            'aerodynamic_secondary_breakup':'UNSUPPORTED',
            'broad_spray_statistics':'UNSUPPORTED',
        },
    }
