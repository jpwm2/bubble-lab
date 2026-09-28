"""Deterministic physical benchmarks for the many-bubble gas network."""
from __future__ import annotations

from dataclasses import asdict
import copy
import math

from .model import (
    GasNetworkState,
    GasRegionState,
    SharedFilmEdge,
    advance_gas_network,
    equilibrium_amount_mol,
    sphere_volume_m3,
)


def three_bubble_chain(*, enabled: bool = True) -> GasNetworkState:
    ambient = 101325.0
    temperature = 298.15
    gamma = 0.03
    radii = (
        ("small", 0.70e-3),
        ("medium", 1.00e-3),
        ("large", 1.40e-3),
    )
    regions = []
    for region_id, radius in radii:
        volume = sphere_volume_m3(radius)
        regions.append(
            GasRegionState(
                id=region_id,
                amount_mol=equilibrium_amount_mol(
                    volume, ambient, gamma, temperature
                ),
                volume_m3=volume,
                temperature_k=temperature,
                surface_tension_n_m=gamma,
            )
        )
    edges = (
        SharedFilmEdge(
            id="film-small-medium",
            region_a="small",
            region_b="medium",
            shared_area_m2=1.20e-6,
            film_thickness_m=0.80e-6,
            permeability_mol_m_per_m2_s_pa=1.0e-11,
        ),
        SharedFilmEdge(
            id="film-medium-large",
            region_a="medium",
            region_b="large",
            shared_area_m2=1.40e-6,
            film_thickness_m=0.85e-6,
            permeability_mol_m_per_m2_s_pa=1.0e-11,
        ),
    )
    state = GasNetworkState(
        regions=regions,
        edges=edges,
        ambient_pressure_pa=ambient,
        diffusion_enabled=enabled,
    )
    state.validate()
    state.assert_constitutive_consistency()
    return state


def _run(total_time_s: float, dt_s: float) -> tuple[GasNetworkState, list]:
    state = three_bubble_chain()
    diagnostics = []
    steps = int(round(total_time_s / dt_s))
    if not math.isclose(steps * dt_s, total_time_s, rel_tol=0.0, abs_tol=1.0e-14):
        raise ValueError("total_time_s must be an integer multiple of dt_s")
    for _ in range(steps):
        diagnostics.append(advance_gas_network(state, dt_s))
    return state, diagnostics


def _state_vector(state: GasNetworkState) -> tuple[float, ...]:
    return tuple(
        value
        for region in state.regions
        for value in (region.amount_mol, region.volume_m3, region.pressure_pa())
    )


def conservation_benchmark() -> dict:
    state = three_bubble_chain()
    initial_total = state.total_amount_mol()
    initial_ids = (state.region_ids(), state.edge_ids())
    worst_step_drift = 0.0
    worst_antisym = 0.0
    max_active = 0
    for _ in range(80):
        diag = advance_gas_network(state, 0.025)
        worst_step_drift = max(worst_step_drift, diag.total_relative_drift)
        worst_antisym = max(
            worst_antisym, diag.max_edge_antisymmetry_residual_mol
        )
        max_active = max(max_active, diag.max_simultaneous_active_edges)
    final_total = state.total_amount_mol()
    total_drift = abs(final_total - initial_total) / initial_total

    repeat, _ = _run(2.0, 0.025)
    deterministic = _state_vector(state) == _state_vector(repeat)
    stable_ids = initial_ids == (state.region_ids(), state.edge_ids())
    return {
        "benchmark": "conservation",
        "region_count": len(state.regions),
        "shared_film_edge_count": len(state.edges),
        "max_simultaneous_active_edges": max_active,
        "total_relative_drift": total_drift,
        "worst_step_relative_drift": worst_step_drift,
        "max_edge_antisymmetry_residual_mol": worst_antisym,
        "stable_region_and_edge_ids": stable_ids,
        "deterministic_repeat": deterministic,
        "passed": (
            len(state.regions) >= 3
            and len(state.edges) >= 2
            and max_active >= 2
            and total_drift <= 1.0e-12
            and worst_step_drift <= 1.0e-12
            and worst_antisym <= 1.0e-30
            and stable_ids
            and deterministic
        ),
    }


def coarsening_benchmark() -> dict:
    state = three_bubble_chain()
    before = {
        region.id: (region.amount_mol, region.volume_m3, region.pressure_pa())
        for region in state.regions
    }
    max_active = 0
    for _ in range(80):
        diag = advance_gas_network(state, 0.025)
        max_active = max(max_active, diag.max_simultaneous_active_edges)
    after = {
        region.id: (region.amount_mol, region.volume_m3, region.pressure_pa())
        for region in state.regions
    }
    small_volume_change = after["small"][1] - before["small"][1]
    large_volume_change = after["large"][1] - before["large"][1]
    small_amount_change = after["small"][0] - before["small"][0]
    large_amount_change = after["large"][0] - before["large"][0]
    pressure_order_initial = (
        before["small"][2] > before["medium"][2] > before["large"][2]
    )
    constitutive_feedback = (
        after["small"][2] > before["small"][2]
        and after["large"][2] < before["large"][2]
    )
    relative_small_shrink = -small_volume_change / before["small"][1]
    relative_large_growth = large_volume_change / before["large"][1]
    return {
        "benchmark": "coarsening",
        "initial": before,
        "final": after,
        "small_volume_change_m3": small_volume_change,
        "large_volume_change_m3": large_volume_change,
        "small_amount_change_mol": small_amount_change,
        "large_amount_change_mol": large_amount_change,
        "relative_small_shrink": relative_small_shrink,
        "relative_large_growth": relative_large_growth,
        "initial_pressure_order_small_to_large": pressure_order_initial,
        "pressure_volume_feedback_observed": constitutive_feedback,
        "max_simultaneous_active_edges": max_active,
        "passed": (
            pressure_order_initial
            and small_volume_change < 0.0
            and large_volume_change > 0.0
            and small_amount_change < 0.0
            and large_amount_change > 0.0
            and relative_small_shrink > 1.0e-4
            and relative_large_growth > 1.0e-5
            and constitutive_feedback
            and max_active >= 2
        ),
    }


def refinement_benchmark() -> dict:
    total = 2.0
    coarse, _ = _run(total, 0.050)
    medium, _ = _run(total, 0.025)
    fine, _ = _run(total, 0.0125)
    reference, _ = _run(total, 0.00625)

    reference_vector = _state_vector(reference)

    def relative_l1(state: GasNetworkState) -> float:
        values = _state_vector(state)
        numerator = math.fsum(
            abs(value - expected)
            for value, expected in zip(values, reference_vector)
        )
        denominator = math.fsum(abs(value) for value in reference_vector)
        return numerator / denominator

    coarse_error = relative_l1(coarse)
    medium_error = relative_l1(medium)
    fine_error = relative_l1(fine)
    return {
        "benchmark": "refinement",
        "coarse_dt_s": 0.050,
        "medium_dt_s": 0.025,
        "fine_dt_s": 0.0125,
        "reference_dt_s": 0.00625,
        "coarse_relative_l1_error": coarse_error,
        "medium_relative_l1_error": medium_error,
        "fine_relative_l1_error": fine_error,
        "medium_to_coarse_ratio": medium_error / max(coarse_error, 1.0e-300),
        "fine_to_medium_ratio": fine_error / max(medium_error, 1.0e-300),
        "passed": (
            coarse_error > medium_error > fine_error > 0.0
            and medium_error / coarse_error < 0.80
            and fine_error / medium_error < 0.80
        ),
    }


BENCHMARKS = {
    "conservation": conservation_benchmark,
    "coarsening": coarsening_benchmark,
    "refinement": refinement_benchmark,
}


def run_benchmark(name: str) -> dict:
    try:
        fn = BENCHMARKS[name]
    except KeyError as exc:
        raise ValueError(f"unknown gas-network benchmark: {name}") from exc
    return fn()
