from __future__ import annotations

from dataclasses import replace
from typing import Callable

from .multineck3d import MultiNeck3DConfig, evolve_multineck_breakup


def _first_event_time(config: MultiNeck3DConfig) -> float:
    result = evolve_multineck_breakup(config)
    if not result.events:
        raise AssertionError("no detachment event was produced")
    return result.events[0].time_s


def benchmark_geometry(assert_mode: bool = False) -> dict[str, object]:
    result = evolve_multineck_breakup()
    before_first = next(
        sample for sample in result.samples if sample.time_s < result.events[0].time_s
    )
    active_before = sum(before_first.active)
    report = {
        "name": "multineck-3d-geometry",
        "status": "PASS",
        "geometry_noncoplanarity": result.geometry_noncoplanarity,
        "active_necks_before_first_event": active_before,
        "event_count": len(result.events),
        "event_necks": [event.neck_id for event in result.events],
        "supported_class": result.provenance["supported_class"],
    }
    if assert_mode:
        assert result.geometry_noncoplanarity > 0.15
        assert active_before >= 2
        assert len(result.events) >= 2
        assert len({event.neck_index for event in result.events}) >= 2
    return report


def benchmark_interaction(assert_mode: bool = False) -> dict[str, object]:
    coupled = evolve_multineck_breakup()
    isolated_config = replace(coupled.config, coupling_strength=0.0)
    isolated = evolve_multineck_breakup(isolated_config)
    paired = min(len(coupled.events), len(isolated.events))
    shifts = [
        abs(coupled.events[i].time_s - isolated.events[i].time_s)
        / isolated.events[i].time_s
        for i in range(paired)
    ]
    max_shift = max(shifts, default=0.0)
    report = {
        "name": "multineck-3d-interaction",
        "status": "PASS",
        "coupled_event_times_s": [event.time_s for event in coupled.events],
        "isolated_event_times_s": [event.time_s for event in isolated.events],
        "relative_event_time_shifts": shifts,
        "max_relative_event_time_shift": max_shift,
    }
    if assert_mode:
        assert paired >= 2
        assert max_shift >= 0.02
    return report


def benchmark_conservation(assert_mode: bool = False) -> dict[str, object]:
    result = evolve_multineck_breakup()
    report = {
        "name": "multineck-3d-conservation",
        "status": "PASS",
        "initial_liquid_volume_m3": result.initial_liquid_volume_m3,
        "final_parent_volume_m3": result.final_parent_volume_m3,
        "detached_volume_m3": result.detached_volume_m3,
        "liquid_volume_relative_error": result.liquid_volume_relative_error,
        "max_transaction_relative_error": result.max_transaction_relative_error,
        "transaction_errors": [event.transaction_relative_error for event in result.events],
    }
    if assert_mode:
        assert len(result.events) >= 2
        assert result.max_transaction_relative_error <= 1.0e-12
        assert result.liquid_volume_relative_error <= 1.0e-12
    return report


def benchmark_response(assert_mode: bool = False) -> dict[str, object]:
    base = MultiNeck3DConfig()
    base_time = _first_event_time(base)
    high_sigma_time = _first_event_time(
        replace(base, surface_tension_n_m=base.surface_tension_n_m * 1.25)
    )
    high_viscosity_time = _first_event_time(
        replace(base, dynamic_viscosity_pa_s=base.dynamic_viscosity_pa_s * 2.0)
    )
    report = {
        "name": "multineck-3d-response",
        "status": "PASS",
        "base_first_event_time_s": base_time,
        "high_surface_tension_first_event_time_s": high_sigma_time,
        "high_viscosity_first_event_time_s": high_viscosity_time,
        "surface_tension_response": "EARLIER_DETACHMENT",
        "viscosity_response": "LATER_DETACHMENT",
    }
    if assert_mode:
        assert high_sigma_time < base_time
        assert high_viscosity_time > base_time
    return report


def benchmark_refinement(assert_mode: bool = False) -> dict[str, object]:
    base = MultiNeck3DConfig()
    dts = (8.0e-5, 4.0e-5, 2.0e-5)
    times = [_first_event_time(replace(base, time_step_s=dt)) for dt in dts]
    coarse_medium = abs(times[0] - times[1]) / times[1]
    medium_fine = abs(times[1] - times[2]) / times[2]
    report = {
        "name": "multineck-3d-refinement",
        "status": "PASS",
        "time_steps_s": list(dts),
        "first_event_times_s": times,
        "coarse_medium_relative_shift": coarse_medium,
        "medium_fine_relative_shift": medium_fine,
    }
    if assert_mode:
        assert medium_fine <= 0.02
        assert medium_fine <= coarse_medium
    return report


def benchmark_replay(assert_mode: bool = False) -> dict[str, object]:
    first = evolve_multineck_breakup()
    second = evolve_multineck_breakup()
    first_events = [(event.neck_id, event.time_s, event.fragment_id) for event in first.events]
    second_events = [(event.neck_id, event.time_s, event.fragment_id) for event in second.events]
    report = {
        "name": "multineck-3d-replay",
        "status": "PASS",
        "solver_digest": first.solver_digest,
        "repeat_solver_digest": second.solver_digest,
        "events_exact": first_events == second_events,
    }
    if assert_mode:
        assert first.solver_digest == second.solver_digest
        assert first_events == second_events
    return report


_BENCHMARKS: dict[str, Callable[[bool], dict[str, object]]] = {
    "multineck-3d-geometry": benchmark_geometry,
    "multineck-3d-interaction": benchmark_interaction,
    "multineck-3d-conservation": benchmark_conservation,
    "multineck-3d-response": benchmark_response,
    "multineck-3d-refinement": benchmark_refinement,
    "multineck-3d-replay": benchmark_replay,
}


def run_benchmark(name: str, assert_mode: bool = False) -> dict[str, object]:
    try:
        runner = _BENCHMARKS[name]
    except KeyError as exc:
        raise ValueError(f"unknown benchmark: {name}") from exc
    return runner(assert_mode)
