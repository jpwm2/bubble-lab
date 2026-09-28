"""Deterministic validation cases for rupture/coalescence event semantics."""
from __future__ import annotations

import json
import math
from typing import Any

from .criteria import RuptureConfig, RuptureObservation
from .engine import TopologyEventEngine
from .model import BubbleState, EventState, SharedFilmState

AIR_MOLAR_MASS_KG_MOL = 0.02897
R_GAS = 8.31446261815324


def _demo_state(*, seed: int = 17, initial_thickness_m: float = 150.0e-9) -> EventState:
    volume_a = 1.2e-6
    volume_b = 2.0e-6
    temperature = 298.15
    pressure = 101325.0
    amount_a = pressure * volume_a / (R_GAS * temperature)
    amount_b = pressure * volume_b / (R_GAS * temperature)
    mass_a = amount_a * AIR_MOLAR_MASS_KG_MOL
    mass_b = amount_b * AIR_MOLAR_MASS_KG_MOL
    a = BubbleState(
        id="bubble-a", volume_m3=volume_a, gas_amount_mol=amount_a,
        centroid_m=(-0.007, 0.0, 0.0), velocity_m_s=(0.18, 0.03, 0.0),
        temperature_k=temperature, mass_kg=mass_a, gas_species="air",
        molar_mass_kg_mol=AIR_MOLAR_MASS_KG_MOL,
    )
    b = BubbleState(
        id="bubble-b", volume_m3=volume_b, gas_amount_mol=amount_b,
        centroid_m=(0.006, 0.0, 0.0), velocity_m_s=(-0.04, -0.01, 0.0),
        temperature_k=temperature, mass_kg=mass_b, gas_species="air",
        molar_mass_kg_mol=AIR_MOLAR_MASS_KG_MOL,
    )
    film = SharedFilmState(
        id="shared-ab", adjacent=(a.id, b.id),
        min_thickness_m=initial_thickness_m, mean_thickness_m=initial_thickness_m,
        area_m2=1.6e-4, surface_tension_n_m=0.050, mesh_id="shared-ab-mesh",
    )
    return EventState(
        bubbles={a.id: a, b.id: b},
        active_films={film.id: film},
        retired_films={},
        seed=seed,
    )


def _exponential_thickness(time_s: float) -> float:
    h0 = 400.0e-9
    h_floor = 20.0e-9
    tau = 0.23
    return h_floor + (h0 - h_floor) * math.exp(-time_s / tau)


def _analytic_threshold_time(threshold_m: float) -> float:
    h0 = 400.0e-9
    h_floor = 20.0e-9
    tau = 0.23
    return -tau * math.log((threshold_m - h_floor) / (h0 - h_floor))


def _rupture_diagnostics_for_dt(
    dt_s: float,
    threshold_m: float = 100.0e-9,
) -> tuple[float, float, float]:
    state = _demo_state(initial_thickness_m=_exponential_thickness(0.0))
    engine = TopologyEventEngine(RuptureConfig(thickness_threshold_m=threshold_m), seed=state.seed)
    time_s = 0.0
    previous_time_s = time_s
    previous_thickness_m = _exponential_thickness(time_s)
    transition = engine.observe_film(
        state,
        "shared-ab",
        RuptureObservation(time_s=time_s, min_thickness_m=previous_thickness_m),
    )
    state = transition.state
    for _ in range(1000):
        time_s += dt_s
        thickness_m = _exponential_thickness(time_s)
        transition = engine.observe_film(
            state,
            "shared-ab",
            RuptureObservation(time_s=time_s, min_thickness_m=thickness_m),
        )
        state = transition.state
        if transition.emitted_events:
            return transition.emitted_events[0].time_s, previous_time_s, previous_thickness_m
        previous_time_s = time_s
        previous_thickness_m = thickness_m
    raise RuntimeError("trajectory did not reach rupture threshold")


def _rupture_time_for_dt(dt_s: float, threshold_m: float = 100.0e-9) -> float:
    return _rupture_diagnostics_for_dt(dt_s, threshold_m)[0]


def rupture_threshold_benchmark(*, assert_pass: bool = False) -> dict[str, Any]:
    threshold = 100.0e-9
    estimated = _rupture_time_for_dt(0.02, threshold)
    analytical = _analytic_threshold_time(threshold)
    relative_error = abs(estimated - analytical) / analytical
    result = {
        "benchmark": "rupture-threshold",
        "threshold_m": threshold,
        "estimated_event_time_s": estimated,
        "analytical_crossing_time_s": analytical,
        "relative_event_time_error": relative_error,
        "method": "accepted-state thinning trajectory plus deterministic linear crossing localization",
        "passed": relative_error <= 0.005,
    }
    if assert_pass and not result["passed"]:
        raise AssertionError(json.dumps(result, sort_keys=True))
    return result


def coalescence_conservation_benchmark(*, assert_pass: bool = False) -> dict[str, Any]:
    state = _demo_state()
    initial_a = state.bubbles["bubble-a"]
    initial_b = state.bubbles["bubble-b"]
    engine = TopologyEventEngine(RuptureConfig(thickness_threshold_m=100.0e-9), seed=state.seed)
    transition = engine.trigger_user_rupture(
        state, "shared-ab", time_s=0.125, detail="B10 deterministic trigger"
    )
    final = transition.state
    child = next(bubble for bubble in final.bubbles.values() if bubble.status == "ALIVE")
    coalescence = transition.emitted_events[1]
    gas_before = math.fsum((initial_a.gas_amount_mol or 0.0, initial_b.gas_amount_mol or 0.0))
    gas_after = child.gas_amount_mol or 0.0
    volume_before = math.fsum((initial_a.volume_m3, initial_b.volume_m3))
    momentum_before = tuple(
        math.fsum((
            initial_a.mass_kg * initial_a.velocity_m_s[axis],
            initial_b.mass_kg * initial_b.velocity_m_s[axis],
        ))
        for axis in range(3)
    )
    momentum_after = tuple(child.mass_kg * child.velocity_m_s[axis] for axis in range(3))
    momentum_delta = math.sqrt(
        math.fsum((momentum_after[i] - momentum_before[i]) ** 2 for i in range(3))
    )
    momentum_scale = max(
        math.sqrt(math.fsum(value * value for value in momentum_before)),
        1.0e-300,
    )
    checks = {
        "shared_film_removed": "shared-ab" not in final.active_films,
        "shared_film_retired": final.retired_films["shared-ab"].status == "RUPTURED",
        "parent_a_retired": final.bubbles["bubble-a"].status == "MERGED",
        "parent_b_retired": final.bubbles["bubble-b"].status == "MERGED",
        "lineage_exact": child.lineage == ("bubble-a", "bubble-b"),
        "gas_relative_error": abs(gas_after - gas_before) / gas_before,
        "target_volume_relative_error": abs(child.volume_m3 - volume_before) / volume_before,
        "momentum_relative_error": momentum_delta / momentum_scale,
        "restart_geometry_volume_relative_error": child.restart_geometry.volume_relative_error(),
        "event_order": [event.type for event in transition.emitted_events],
        "bubble_bookkeeping_complete": (
            set(final.bubbles) == {"bubble-a", "bubble-b", child.id}
            and sum(item.status == "ALIVE" for item in final.bubbles.values()) == 1
        ),
        "surface_energy_accounted": (
            coalescence.conservation.get("removed_shared_film_surface_energy_j", 0.0) > 0.0
            and coalescence.conservation.get("bookkeeping_surface_energy_change_j", 0.0) < 0.0
            and coalescence.conservation.get("full_surface_energy_change_j") is None
        ),
    }
    passed = (
        checks["shared_film_removed"]
        and checks["shared_film_retired"]
        and checks["parent_a_retired"]
        and checks["parent_b_retired"]
        and checks["lineage_exact"]
        and checks["gas_relative_error"] <= 1.0e-12
        and checks["target_volume_relative_error"] <= 1.0e-12
        and checks["momentum_relative_error"] <= 1.0e-12
        and checks["restart_geometry_volume_relative_error"] <= 1.0e-12
        and checks["event_order"] == ["RUPTURE", "COALESCENCE"]
        and checks["bubble_bookkeeping_complete"]
        and checks["surface_energy_accounted"]
        and coalescence.lineage == {child.id: ("bubble-a", "bubble-b")}
    )
    result = {
        "benchmark": "coalescence-conservation",
        **checks,
        "child_id": child.id,
        "passed": passed,
    }
    if assert_pass and not passed:
        raise AssertionError(json.dumps(result, sort_keys=True))
    return result


def rupture_convergence_benchmark(*, assert_pass: bool = False) -> dict[str, Any]:
    threshold = 100.0e-9
    analytical = _analytic_threshold_time(threshold)
    characteristic_drainage_time_s = 0.23
    dts = (0.02, 0.01, 0.005)
    diagnostics = tuple(_rupture_diagnostics_for_dt(dt, threshold) for dt in dts)
    times = tuple(item[0] for item in diagnostics)
    pre_times = tuple(item[1] for item in diagnostics)
    pre_thickness = tuple(item[2] for item in diagnostics)
    errors = tuple(abs(value - analytical) for value in times)
    fine_finer_relative_shift = abs(times[1] - times[2]) / characteristic_drainage_time_s
    pre_event_relative_shift = abs(pre_thickness[1] - pre_thickness[2]) / threshold
    converging = errors[2] < errors[1] < errors[0]
    pre_event_converging = (
        abs(pre_thickness[2] - threshold)
        < abs(pre_thickness[1] - threshold)
        < abs(pre_thickness[0] - threshold)
    )
    passed = (
        fine_finer_relative_shift <= 0.02
        and pre_event_relative_shift <= 0.02
        and converging
        and pre_event_converging
    )
    result = {
        "benchmark": "rupture-convergence",
        "timestep_s": list(dts),
        "rupture_time_s": list(times),
        "analytical_time_s": analytical,
        "absolute_error_s": list(errors),
        "fine_vs_finer_relative_shift": fine_finer_relative_shift,
        "relative_shift_normalization": "characteristic_drainage_time_s",
        "characteristic_drainage_time_s": characteristic_drainage_time_s,
        "pre_event_time_s": list(pre_times),
        "pre_event_min_thickness_m": list(pre_thickness),
        "pre_event_fine_vs_finer_shift_over_hcrit": pre_event_relative_shift,
        "convergence_trend": converging,
        "pre_event_state_convergence_trend": pre_event_converging,
        "passed": passed,
    }
    if assert_pass and not passed:
        raise AssertionError(json.dumps(result, sort_keys=True))
    return result


def _replay_payload() -> dict[str, Any]:
    state = _demo_state(seed=20260918)
    engine = TopologyEventEngine(
        RuptureConfig(thickness_threshold_m=100.0e-9, dwell_time_s=0.01),
        seed=state.seed,
    )
    samples = (
        (0.00, 150.0e-9),
        (0.02, 115.0e-9),
        (0.04, 85.0e-9),
        (0.06, 70.0e-9),
    )
    for time_s, thickness in samples:
        transition = engine.observe_film(
            state,
            "shared-ab",
            RuptureObservation(time_s=time_s, min_thickness_m=thickness),
        )
        state = transition.state
        if transition.emitted_events:
            break
    return state.canonical_payload()


def event_replay_benchmark(*, assert_pass: bool = False) -> dict[str, Any]:
    first = _replay_payload()
    second = _replay_payload()
    first_json = json.dumps(first, sort_keys=True, separators=(",", ":"), allow_nan=False)
    second_json = json.dumps(second, sort_keys=True, separators=(",", ":"), allow_nan=False)
    passed = first_json == second_json
    result = {
        "benchmark": "event-replay",
        "identical": passed,
        "state_ref": first["state_ref"],
        "event_ids": [event["id"] for event in first["events"]],
        "event_times_s": [event["time_s"] for event in first["events"]],
        "passed": passed,
    }
    if assert_pass and not passed:
        raise AssertionError(json.dumps(result, sort_keys=True))
    return result


def demo_transition() -> EventState:
    state = _demo_state(seed=23, initial_thickness_m=150.0e-9)
    engine = TopologyEventEngine(RuptureConfig(thickness_threshold_m=100.0e-9), seed=state.seed)
    state = engine.observe_film(
        state,
        "shared-ab",
        RuptureObservation(time_s=0.0, min_thickness_m=150.0e-9),
    ).state
    return engine.observe_film(
        state,
        "shared-ab",
        RuptureObservation(time_s=0.05, min_thickness_m=70.0e-9),
    ).state
