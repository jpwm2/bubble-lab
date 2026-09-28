"""Executable evidence for the supported axisymmetric pinch-off foundation."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from .solver import PinchOffConfig, PinchOffResult, evolve_neck


def _nearest_radius(result: PinchOffResult, time_s: float) -> float:
    return min(result.samples, key=lambda sample: abs(sample.time_s - time_s)).minimum_radius_m


def neck_benchmark() -> dict[str, Any]:
    result = evolve_neck()
    tail = result.samples[-8:]
    return {
        "benchmark": "neck",
        "solver": result.provenance,
        "cell_count": len(result.coordinates_m),
        "cell_width_m": result.cell_width_m,
        "initial_minimum_radius_m": result.initial_minimum_radius_m,
        "final_minimum_radius_m": result.final_minimum_radius_m,
        "last_resolved_time_s": result.last_resolved_time_s,
        "pinch_time_s": result.pinch_time_s,
        "terminal_fit_slope_m_s": result.terminal_fit_slope_m_s,
        "maximum_axial_speed_m_s": max(sample.maximum_axial_speed_m_s for sample in result.samples),
        "terminal_radius_monotone": all(
            later.minimum_radius_m < earlier.minimum_radius_m for earlier, later in zip(tail[:-1], tail[1:])
        ),
        "volume_relative_error": result.volume_relative_error,
        "stop_reason": result.stop_reason,
        "solver_digest": result.solver_digest,
    }


def refinement_benchmark() -> dict[str, Any]:
    base = PinchOffConfig()
    runs = [evolve_neck(replace(base, cell_count=count)) for count in (33, 49, 65)]
    pinch_times = [run.pinch_time_s for run in runs]
    coarse_medium = abs(pinch_times[0] - pinch_times[1])
    medium_fine = abs(pinch_times[1] - pinch_times[2])
    probe_time = 0.50
    probe_radii = [_nearest_radius(run, probe_time) for run in runs]
    probe_coarse_medium = abs(probe_radii[0] - probe_radii[1])
    probe_medium_fine = abs(probe_radii[1] - probe_radii[2])
    return {
        "benchmark": "refinement",
        "cell_counts": [33, 49, 65],
        "pinch_times_s": pinch_times,
        "pinch_time_coarse_medium_delta_s": coarse_medium,
        "pinch_time_medium_fine_delta_s": medium_fine,
        "probe_time_s": probe_time,
        "probe_minimum_radii_m": probe_radii,
        "probe_coarse_medium_delta_m": probe_coarse_medium,
        "probe_medium_fine_delta_m": probe_medium_fine,
        "pinch_time_refines": medium_fine < coarse_medium,
        "trajectory_refines": probe_medium_fine < probe_coarse_medium,
        "volume_relative_errors": [run.volume_relative_error for run in runs],
    }


def conservation_benchmark() -> dict[str, Any]:
    first = evolve_neck()
    second = evolve_neck()
    return {
        "benchmark": "conservation",
        "initial_patch_volume_m3": first.initial_patch_volume_m3,
        "final_patch_volume_m3": first.final_patch_volume_m3,
        "volume_relative_error": first.volume_relative_error,
        "maximum_history_volume_relative_error": max(sample.volume_relative_error for sample in first.samples),
        "deterministic_repeat": first.solver_digest == second.solver_digest and first.pinch_time_s == second.pinch_time_s,
        "first_digest": first.solver_digest,
        "second_digest": second.solver_digest,
    }


def assert_benchmark(name: str, payload: dict[str, Any]) -> None:
    if name == "neck":
        if payload["stop_reason"] != "RESOLUTION_LIMIT_REACHED":
            raise AssertionError("neck evolution did not reach the resolution-relative singular handoff")
        if not payload["final_minimum_radius_m"] < 0.40 * payload["initial_minimum_radius_m"]:
            raise AssertionError("resolved neck did not thin substantially")
        if not payload["pinch_time_s"] > payload["last_resolved_time_s"]:
            raise AssertionError("dynamic singular time must lie beyond the last resolved state")
        if not payload["terminal_fit_slope_m_s"] < 0.0:
            raise AssertionError("terminal neck radius must be collapsing")
        if not payload["terminal_radius_monotone"]:
            raise AssertionError("terminal neck trajectory is not monotone")
        if not payload["maximum_axial_speed_m_s"] > 0.1:
            raise AssertionError("hydrodynamic evolution did not produce axial flow")
        if not payload["volume_relative_error"] <= 2.0e-12:
            raise AssertionError("neck evolution exceeded the volume-conservation gate")
        return
    if name == "refinement":
        if not payload["pinch_time_refines"]:
            raise AssertionError("pinch-time change did not decrease under refinement")
        if not payload["trajectory_refines"]:
            raise AssertionError("neck trajectory change did not decrease under refinement")
        if not payload["pinch_time_medium_fine_delta_s"] < 0.10:
            raise AssertionError("medium/fine pinch-time difference is too large")
        if max(payload["volume_relative_errors"]) > 2.0e-12:
            raise AssertionError("refinement runs violated volume conservation")
        return
    if name == "conservation":
        if not payload["volume_relative_error"] <= 2.0e-12:
            raise AssertionError("terminal volume error exceeds the gate")
        if not payload["maximum_history_volume_relative_error"] <= 2.0e-12:
            raise AssertionError("history volume error exceeds the gate")
        if not payload["deterministic_repeat"]:
            raise AssertionError("pinch-off evolution is not deterministic")
        return
    raise ValueError(f"unknown benchmark {name!r}")
