"""Release-style equilibrium validation harness.

The harness consumes accepted equilibrium benchmark adapters and records
machine-readable evidence without modifying solver behavior.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import math
from pathlib import Path
from typing import Any, Callable

import bubblelab.solvers.equilibrium.benchmarks as sphere_api
import bubblelab.solvers.equilibrium.plateau_benchmarks as plateau_api
import bubblelab.solvers.equilibrium.shared_benchmarks as shared_api

REQUIRED_BENCHMARK_IDS = ("B01", "B02", "B04", "B05", "B06", "B09", "B11", "B13")
REQUIREMENTS = ("R6", "R7", "R8", "R9", "R31", "R32", "R33", "R38")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _source_sha256(module: Any) -> str:
    path = inspect.getsourcefile(module)
    if not path:
        return "unavailable"
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _assertion_status(assertion: Callable[[dict[str, Any]], None], metrics: dict[str, Any]) -> dict[str, Any]:
    try:
        assertion(metrics)
    except AssertionError as exc:
        return {"passed": False, "detail": str(exc)}
    return {"passed": True, "detail": "accepted benchmark adapter assertion passed"}


def _gate(metric: str, value: Any, relation: str, threshold: Any, passed: bool, source: str) -> dict[str, Any]:
    return {
        "metric": metric,
        "value": value,
        "relation": relation,
        "threshold": threshold,
        "passed": bool(passed),
        "source": source,
    }


def gate_le(metric: str, value: float, limit: float, source: str) -> dict[str, Any]:
    return _gate(metric, value, "<=", limit, math.isfinite(value) and value <= limit, source)


def gate_ge(metric: str, value: float, limit: float, source: str) -> dict[str, Any]:
    return _gate(metric, value, ">=", limit, math.isfinite(value) and value >= limit, source)


def gate_true(metric: str, value: bool, source: str) -> dict[str, Any]:
    return _gate(metric, bool(value), "==", True, bool(value), source)


def gate_zero(metric: str, value: int, source: str) -> dict[str, Any]:
    return _gate(metric, int(value), "==", 0, int(value) == 0, source)


def _adapter_gate(name: str, status: dict[str, Any]) -> dict[str, Any]:
    gate = gate_true(name, bool(status["passed"]), "accepted solver benchmark assertion")
    gate["detail"] = status["detail"]
    return gate


def _record(
    benchmark_id: str,
    title: str,
    requirements: list[str],
    setup: dict[str, Any],
    resolution: dict[str, Any],
    metrics: dict[str, Any],
    gates: list[dict[str, Any]],
    termination: dict[str, Any] | None = None,
    convergence: dict[str, Any] | None = None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": benchmark_id,
        "title": title,
        "requirements": requirements,
        "setup": setup,
        "resolution": resolution,
        "metrics": metrics,
        "gates": gates,
        "passed": all(gate["passed"] for gate in gates),
        "termination": termination,
        "convergence": convergence,
        "limitations": limitations or [],
    }


def _energy_metrics() -> tuple[dict[str, Any], dict[str, Any]]:
    result = plateau_api.plateau_three_result(longitudinal_segments=48)
    history = list(result.energy_history_j)
    relative_increases: list[float] = []
    for before, after in zip(history, history[1:]):
        relative_increases.append(max(0.0, (after - before) / max(abs(before), 1.0e-30)))
    maximum_increase = max(relative_increases, default=0.0)
    count_over_gate = sum(value > 1.0e-10 for value in relative_increases)
    metrics = {
        "accepted_step_count": max(0, len(history) - 1),
        "initial_energy_j": history[0] if history else result.initial_surface_energy_j,
        "final_energy_j": history[-1] if history else result.surface_energy_j,
        "relative_energy_drop": (
            (history[0] - history[-1]) / max(abs(history[0]), 1.0e-30)
            if len(history) >= 2
            else 0.0
        ),
        "maximum_relative_step_increase": maximum_increase,
        "step_increase_count_above_1e-10": count_over_gate,
        "relative_volume_residuals": result.relative_volume_residuals,
        "normalized_projected_force": result.normalized_force_residual,
        "iterations": result.iterations,
        "converged": result.converged,
    }
    termination = {
        "reason": result.termination_reason,
        "converged": result.converged,
        "iterations": result.iterations,
    }
    return metrics, termination


def run_validation() -> dict[str, Any]:
    sphere = sphere_api.sphere_case()
    sphere_conv = sphere_api.sphere_convergence()
    b04 = shared_api.b04_equal_pressure_flatness()
    b05 = shared_api.b05_unequal_pressure_curvature()
    b06 = plateau_api.plateau_three()
    plateau_conv = plateau_api.plateau_convergence()
    energy, energy_termination = _energy_metrics()

    sphere_assert = _assertion_status(sphere_api.assert_sphere, sphere)
    sphere_conv_assert = _assertion_status(sphere_api.assert_convergence, sphere_conv)
    b04_assert = _assertion_status(shared_api.assert_b04, b04)
    b05_assert = _assertion_status(shared_api.assert_b05, b05)
    b06_assert = _assertion_status(plateau_api.assert_plateau_three, b06)
    plateau_conv_assert = _assertion_status(plateau_api.assert_plateau_convergence, plateau_conv)

    min_area_order = float(sphere_conv["minimum_observed_order"]["area"])
    min_volume_order = float(sphere_conv["minimum_observed_order"]["volume"])
    min_pressure_order = float(sphere_conv["minimum_observed_order"]["pressure"])
    min_plateau_order = min(float(value) for value in plateau_conv["observed_orders"])

    records: list[dict[str, Any]] = []

    records.append(_record(
        "B01",
        "Sphere area and volume geometry",
        ["R7", "R32"],
        {
            "geometry": "isolated icosphere",
            "radius_m": sphere["radius_m"],
            "sheet_tension_n_m": sphere["sheet_tension_n_m"],
            "gravity": "zero",
        },
        {
            "eta_s_raw": sphere["eta_s_raw"],
            "eta_s_final": sphere["eta_s_final"],
            "convergence_levels": sphere_conv["levels"],
        },
        {
            "raw_area_relative_error": sphere["raw_area_relative_error"],
            "raw_volume_relative_error": sphere["raw_volume_relative_error"],
            "final_volume_relative_error": sphere["final_volume_relative_error"],
            "radial_rms_relative_error": sphere["radial_rms_relative_error"],
            "minimum_area_order": min_area_order,
            "minimum_volume_order": min_volume_order,
        },
        [
            gate_le("eta_s_raw", float(sphere["eta_s_raw"]), 3.0e-2, "BENCHMARK_MATRIX B01"),
            gate_le("raw_area_relative_error", float(sphere["raw_area_relative_error"]), 2.0e-3, "BENCHMARK_MATRIX B01"),
            gate_le("raw_volume_relative_error", float(sphere["raw_volume_relative_error"]), 2.0e-3, "BENCHMARK_MATRIX B01"),
            gate_le("final_volume_relative_error", float(sphere["final_volume_relative_error"]), 1.0e-8, "BENCHMARK_MATRIX B01/B03A"),
            gate_ge("minimum_area_order", min_area_order, 1.7, "BENCHMARK_MATRIX B01/B09"),
            gate_ge("minimum_volume_order", min_volume_order, 1.7, "BENCHMARK_MATRIX B01/B09"),
            _adapter_gate("accepted_sphere_assertion", sphere_assert),
        ],
        termination={
            "reason": sphere["termination_reason"],
            "converged": sphere["converged"],
            "iterations": sphere["iterations"],
        },
        convergence={
            "rows": sphere_conv["rows"],
            "observed_order": sphere_conv["observed_order"],
        },
    ))

    records.append(_record(
        "B02",
        "Young-Laplace sphere pressure",
        ["R6", "R32"],
        {
            "pressure_convention": "Delta p = 2 sigma_f / R",
            "radius_m": sphere["radius_m"],
            "sheet_tension_n_m": sphere["sheet_tension_n_m"],
        },
        {"eta_s_raw": sphere["eta_s_raw"], "convergence_levels": sphere_conv["levels"]},
        {
            "pressure_jump_pa": sphere["pressure_jump_pa"],
            "exact_pressure_jump_pa": sphere["exact_pressure_jump_pa"],
            "young_laplace_relative_error": sphere["young_laplace_relative_error"],
            "normalized_force_residual": sphere["normalized_force_residual"],
            "minimum_pressure_order": min_pressure_order,
        },
        [
            gate_le("eta_s_raw", float(sphere["eta_s_raw"]), 3.0e-2, "BENCHMARK_MATRIX B02"),
            gate_le("young_laplace_relative_error", float(sphere["young_laplace_relative_error"]), 5.0e-3, "BENCHMARK_MATRIX B02"),
            gate_le("normalized_force_residual", float(sphere["normalized_force_residual"]), 1.0e-2, "BENCHMARK_MATRIX B02"),
            gate_ge("minimum_pressure_order", min_pressure_order, 1.5, "BENCHMARK_MATRIX B02"),
            _adapter_gate("accepted_sphere_assertion", sphere_assert),
        ],
        termination={
            "reason": sphere["termination_reason"],
            "converged": sphere["converged"],
            "iterations": sphere["iterations"],
        },
        convergence={
            "rows": sphere_conv["rows"],
            "pressure_orders": sphere_conv["observed_order"]["pressure"],
        },
    ))

    records.append(_record(
        "B04",
        "Equal-pressure common-film flatness",
        ["R8", "R32"],
        {
            "geometry": "two bubbles with persistent shared film",
            "pressure_relation": "equal pressure target",
            "measurement": b04["measurement"],
        },
        {"eta_s": b04["eta_s"], "h_max_over_l": b04["h_max_over_l"]},
        {
            "kappa_rms_l": b04["kappa_rms_l"],
            "plane_deviation": b04["plane_deviation"],
            "pressure_curvature_residual": b04["pressure_curvature_residual"],
            "relative_volume_residuals": b04["relative_volume_residuals"],
            "normalized_projected_force": b04["normalized_projected_force"],
            "deterministic_repeat": b04["deterministic_repeat"],
        },
        [
            gate_le("eta_s", float(b04["eta_s"]), 3.0e-2, "BENCHMARK_MATRIX B04"),
            gate_le("kappa_rms_l", float(b04["kappa_rms_l"]), 3.0e-3, "BENCHMARK_MATRIX B04"),
            gate_le("plane_deviation", float(b04["plane_deviation"]), 3.0e-3, "BENCHMARK_MATRIX B04"),
            gate_le("pressure_curvature_residual", float(b04["pressure_curvature_residual"]), 1.0e-2, "BENCHMARK_MATRIX B04"),
            gate_le("maximum_relative_volume_residual", max(float(v) for v in b04["relative_volume_residuals"].values()), 1.0e-8, "accepted B04 adapter"),
            gate_true("converged", bool(b04["converged"]), "accepted B04 adapter"),
            gate_true("deterministic_repeat", bool(b04["deterministic_repeat"]), "accepted B04 adapter"),
            _adapter_gate("accepted_b04_assertion", b04_assert),
        ],
        termination={
            "reason": b04["termination_reason"],
            "converged": b04["converged"],
            "iterations": b04["iterations"],
        },
        limitations=[
            "The accepted B04 adapter exposes fine-resolution evidence but not a shared-film refinement ladder; the harness does not invent one."
        ],
    ))

    records.append(_record(
        "B05",
        "Unequal-pressure shared-film curvature",
        ["R8", "R32"],
        {
            "geometry": "two bubbles with unequal pressure and persistent shared film",
            "measurement": b05["measurement"],
        },
        {"eta_s": b05["eta_s"], "h_max_over_l": b05["h_max_over_l"]},
        {
            "pressure_a_pa": b05["pressure_a_pa"],
            "pressure_b_pa": b05["pressure_b_pa"],
            "pressure_difference_pa": b05["pressure_difference_pa"],
            "target_curvature_1_m": b05["target_curvature_1_m"],
            "fitted_curvature_1_m": b05["fitted_curvature_1_m"],
            "normalized_curvature_error": b05["normalized_curvature_error"],
            "mean_relation_error": b05["mean_relation_error"],
            "area_weighted_curvature_error": b05["area_weighted_curvature_error"],
            "pressure_curvature_residual": b05["pressure_curvature_residual"],
            "sign_consistent": b05["sign_consistent"],
            "relative_volume_residuals": b05["relative_volume_residuals"],
            "deterministic_repeat": b05["deterministic_repeat"],
        },
        [
            gate_le("eta_s", float(b05["eta_s"]), 3.0e-2, "BENCHMARK_MATRIX B05"),
            gate_le("mean_relation_error", float(b05["mean_relation_error"]), 1.0e-2, "BENCHMARK_MATRIX B05"),
            gate_le("area_weighted_curvature_error", float(b05["area_weighted_curvature_error"]), 2.0e-2, "BENCHMARK_MATRIX B05"),
            gate_le("pressure_curvature_residual", float(b05["pressure_curvature_residual"]), 1.0e-2, "accepted B05 adapter"),
            gate_true("sign_consistent", bool(b05["sign_consistent"]), "BENCHMARK_MATRIX B05"),
            gate_le("maximum_relative_volume_residual", max(float(v) for v in b05["relative_volume_residuals"].values()), 1.0e-8, "accepted B05 adapter"),
            gate_true("converged", bool(b05["converged"]), "accepted B05 adapter"),
            gate_true("deterministic_repeat", bool(b05["deterministic_repeat"]), "accepted B05 adapter"),
            _adapter_gate("accepted_b05_assertion", b05_assert),
        ],
        termination={
            "reason": b05["termination_reason"],
            "converged": b05["converged"],
            "iterations": b05["iterations"],
        },
        limitations=[
            "The accepted B05 adapter exposes fine-resolution evidence but not a shared-film refinement ladder; the harness does not synthesize solver data."
        ],
    ))

    records.append(_record(
        "B06",
        "Equal-tension Plateau junction",
        ["R9", "R32"],
        {
            "geometry": "three equal-tension films meeting on one junction",
            "analytical_reference_deg": b06["analytical_reference_deg"],
            "measurement": b06["measurement"],
        },
        {
            "junction_eta": b06["junction_eta"],
            "longitudinal_segments": b06["longitudinal_segments"],
            "convergence_segments": [level["longitudinal_segments"] for level in plateau_conv["levels"]],
        },
        {
            "initial_angle_rms_error_deg": b06["initial_angle_rms_error_deg"],
            "angle_rms_error_deg": b06["angle_rms_error_deg"],
            "angle_max_error_deg": b06["angle_max_error_deg"],
            "junction_force_residual": b06["junction_force_residual"],
            "relative_volume_residuals": b06["relative_volume_residuals"],
            "surface_energy_j": b06["surface_energy_j"],
            "initial_surface_energy_j": b06["initial_surface_energy_j"],
            "minimum_observed_angle_order": min_plateau_order,
        },
        [
            gate_le("junction_eta", float(b06["junction_eta"]), 3.0e-2, "BENCHMARK_MATRIX B06"),
            gate_le("angle_rms_error_deg", float(b06["angle_rms_error_deg"]), 1.0, "BENCHMARK_MATRIX B06"),
            gate_le("angle_max_error_deg", float(b06["angle_max_error_deg"]), 2.0, "BENCHMARK_MATRIX B06"),
            gate_le("junction_force_residual", float(b06["junction_force_residual"]), 5.0e-3, "BENCHMARK_MATRIX B06"),
            gate_le("maximum_relative_volume_residual", max(float(v) for v in b06["relative_volume_residuals"].values()), 1.0e-8, "accepted B06 adapter"),
            gate_true("converged", bool(b06["converged"]), "accepted B06 adapter"),
            gate_true("energy_nonincrease", bool(b06["energy_nonincrease"]), "accepted B06 adapter"),
            gate_ge("minimum_observed_angle_order", min_plateau_order, 0.9, "BENCHMARK_MATRIX B06/B09"),
            _adapter_gate("accepted_b06_assertion", b06_assert),
            _adapter_gate("accepted_plateau_convergence_assertion", plateau_conv_assert),
        ],
        termination={
            "reason": b06["termination_reason"],
            "converged": b06["converged"],
            "iterations": b06["iterations"],
        },
        convergence={
            "levels": plateau_conv["levels"],
            "observed_orders": plateau_conv["observed_orders"],
        },
    ))

    records.append(_record(
        "B09",
        "Mesh-refinement convergence",
        ["R20", "R32"],
        {
            "families": ["smooth sphere geometry/pressure", "Plateau junction angle"],
            "method": "accepted deterministic benchmark refinement ladders",
        },
        {
            "sphere_levels": sphere_conv["levels"],
            "plateau_segments": [level["longitudinal_segments"] for level in plateau_conv["levels"]],
        },
        {
            "minimum_area_order": min_area_order,
            "minimum_volume_order": min_volume_order,
            "minimum_pressure_order": min_pressure_order,
            "minimum_plateau_angle_order": min_plateau_order,
        },
        [
            gate_ge("minimum_area_order", min_area_order, 1.7, "BENCHMARK_MATRIX B09"),
            gate_ge("minimum_volume_order", min_volume_order, 1.7, "BENCHMARK_MATRIX B09"),
            gate_ge("minimum_pressure_order", min_pressure_order, 1.3, "BENCHMARK_MATRIX B09"),
            gate_ge("minimum_plateau_angle_order", min_plateau_order, 0.9, "BENCHMARK_MATRIX B09"),
            _adapter_gate("accepted_sphere_convergence_assertion", sphere_conv_assert),
            _adapter_gate("accepted_plateau_convergence_assertion", plateau_conv_assert),
        ],
        convergence={
            "sphere": sphere_conv,
            "plateau": plateau_conv,
        },
        limitations=[
            "The current accepted shared-film adapters do not expose B04/B05 refinement ladders, so B09 reports the available smooth-sphere and Plateau ladders without fabricating shared-film convergence."
        ],
    ))

    physics_payload = {
        "sphere": sphere,
        "sphere_convergence": sphere_conv,
        "b04": b04,
        "b05": b05,
        "b06": b06,
        "plateau_convergence": plateau_conv,
        "energy": energy,
    }
    replay_hash = canonical_hash(physics_payload)

    records.append(_record(
        "B11",
        "Deterministic replay",
        ["R31"],
        {
            "mode": "same-build deterministic replay",
            "comparison": "exact machine-readable output comparison by compare_validation_runs.py",
        },
        {"seed": None, "threads": 1, "processes": 1},
        {
            "sphere_internal_repeat": sphere["deterministic_repeat"],
            "b04_internal_repeat": b04["deterministic_repeat"],
            "b05_internal_repeat": b05["deterministic_repeat"],
            "replay_payload_sha256": replay_hash,
        },
        [
            gate_true("sphere_internal_repeat", bool(sphere["deterministic_repeat"]), "B11"),
            gate_true("b04_internal_repeat", bool(b04["deterministic_repeat"]), "B11"),
            gate_true("b05_internal_repeat", bool(b05["deterministic_repeat"]), "B11"),
            gate_true("replay_payload_hash_present", len(replay_hash) == 64, "B11"),
        ],
        limitations=[
            "Full-suite deterministic equality is enforced by running this suite twice and asserting exact comparison with compare_validation_runs.py."
        ],
    ))

    records.append(_record(
        "B13",
        "Surface-energy monotonic relaxation",
        ["R6", "R7"],
        {
            "case": "48-segment equal-tension Plateau relaxation",
            "accepted_step_rule": "no unexplained relative energy increase above 1e-10",
        },
        {"longitudinal_segments": 48},
        energy,
        [
            gate_ge("accepted_step_count", float(energy["accepted_step_count"]), 1.0, "BENCHMARK_MATRIX B13"),
            gate_le("maximum_relative_step_increase", float(energy["maximum_relative_step_increase"]), 1.0e-10, "BENCHMARK_MATRIX B13"),
            gate_zero("step_increase_count_above_1e-10", int(energy["step_increase_count_above_1e-10"]), "BENCHMARK_MATRIX B13"),
            gate_true("converged", bool(energy["converged"]), "accepted Plateau solver result"),
            gate_le("maximum_relative_volume_residual", max(float(v) for v in energy["relative_volume_residuals"].values()), 1.0e-8, "equilibrium volume gate"),
        ],
        termination=energy_termination,
    ))

    failed = [record["id"] for record in records if not record["passed"]]
    provenance = {
        "backend": "bubblelab.solvers.equilibrium",
        "fidelity_tier": "HIGH_FIDELITY",
        "active_feature_classification": [
            "quasi-static prescribed-volume equilibrium",
            "persistent shared-film equilibrium",
            "Plateau junction equilibrium",
        ],
        "adapter_source_sha256": {
            "sphere": _source_sha256(sphere_api),
            "shared_film": _source_sha256(shared_api),
            "plateau": _source_sha256(plateau_api),
        },
        "seed": None,
        "thread_process_count": {"threads": 1, "processes": 1},
        "bulk_grid_resolution": None,
        "timestep": None,
        "remeshing": "not used by this equilibrium validation harness",
    }
    result = {
        "schema_version": 1,
        "suite": "bubble-equilibrium-validation",
        "scope_statement": "This validation covers equilibrium physics only.",
        "requirements": list(REQUIREMENTS),
        "required_benchmark_ids": list(REQUIRED_BENCHMARK_IDS),
        "provenance": provenance,
        "benchmarks": records,
        "replay_payload_sha256": replay_hash,
        "summary": {
            "passed": not failed,
            "benchmark_count": len(records),
            "failed_benchmarks": failed,
        },
        "limitations": [
            "Transient multiphase flow, film drainage, gas diffusion, coalescence, rupture, and rendering are outside this equilibrium-only validation.",
            "B04/B05 accepted adapters currently provide fine-resolution absolute checks but no independent refinement ladder.",
            "No wall-clock timestamp is included in deterministic result content.",
        ],
    }
    canonical_json(result)
    return result


def failed_gate_messages(result: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    for record in result["benchmarks"]:
        for gate in record["gates"]:
            if not gate["passed"]:
                messages.append(
                    f"{record['id']} {gate['metric']}: value={gate['value']!r} "
                    f"required {gate['relation']} {gate['threshold']!r}"
                )
    return messages
