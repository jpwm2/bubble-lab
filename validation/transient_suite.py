"""Integrated validation harness for the accepted transient Bubble Lab stack.

This module deliberately consumes accepted solver/runtime benchmark APIs instead
of re-implementing physics.  It adds provenance, exact run-window metadata and
fidelity qualifications so foundation evidence is not promoted to a stronger
claim than the producing benchmark supports.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import bubblelab.solvers.transient.benchmarks as transient_api
import bubblelab.solvers.boundary.benchmarks as boundary_api
import bubblelab.solvers.events.benchmarks as event_api
from bubblelab.runtime.postcoalescence_runtime import run_postcoalescence_frames
from bubblelab.solvers.transient.geometry import icosphere
from bubblelab.solvers.transient.grid import GridConfig
from bubblelab.solvers.transient.solver import TimeStepPolicy, TransientConfig, TransientSoapFilmSolver

_REPO_ROOT = Path(__file__).resolve().parents[2]
_POST_EVENT_SCENARIO = _REPO_ROOT / "bubblelab/scenarios/runtime/two-bubble-coalescence-relaxation.scenario.json"
_CLASSIFICATIONS = ("RESOLVED", "MODELED", "VISUAL_ONLY", "NOT_IMPLEMENTED")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _record(
    gate_id: str,
    title: str,
    matrix_mapping: list[str],
    classification: str,
    setup: dict[str, Any],
    evidence: dict[str, Any],
    thresholds: dict[str, Any],
    provenance: list[str],
    limitations: list[str],
    *,
    passed: bool | None = None,
) -> dict[str, Any]:
    if classification not in _CLASSIFICATIONS:
        raise ValueError(f"unknown classification: {classification}")
    if passed is None:
        passed = bool(evidence.get("passed"))
    return {
        "gate_id": gate_id,
        "title": title,
        "matrix_mapping": matrix_mapping,
        "classification": classification,
        "setup": setup,
        "evidence": evidence,
        "thresholds": thresholds,
        "provenance": provenance,
        "limitations": limitations,
        "passed": bool(passed),
    }


def _short_static_window() -> dict[str, Any]:
    """Measure the exact time window represented by the accepted static smoke case."""
    front = icosphere(radius_m=0.008, subdivisions=2, surface_tension_n_m=0.05)
    initial_volume = front.volume()
    config = TransientConfig(
        grid=GridConfig(
            cells=(12, 12, 12),
            origin_m=(-0.02, -0.02, -0.02),
            extent_m=(0.04, 0.04, 0.04),
            density_kg_m3=1.204,
            dynamic_viscosity_pa_s=1.825e-5,
            pressure_iterations=360,
            pressure_tolerance_s_inv=1.0e-10,
        ),
        gravity_m_s2=(0.0, 0.0, 0.0),
        timestep=TimeStepPolicy(max_dt_s=2.0e-5, capillary_safety=0.05),
        deterministic_seed=17,
        sharp_pressure_jump=True,
    )
    solver = TransientSoapFilmSolver([front], config)
    diagnostics = [solver.step(), solver.step()]
    final_volume = solver.fronts[0].volume()
    return {
        "start_time_s": 0.0,
        "end_time_s": solver.time_s,
        "step_count": solver.step_index,
        "timesteps_s": [item.timestep_s for item in diagnostics],
        "cells_per_axis": 12,
        "eta_bulk": solver.grid.h / front.equivalent_radius(),
        "initial_volume_m3": initial_volume,
        "final_volume_m3": final_volume,
        "volume_relative_drift": abs(final_volume - initial_volume) / initial_volume,
        "maximum_reported_volume_error": max(item.max_relative_volume_error for item in diagnostics),
    }


def _mesh(frame: dict[str, Any], mesh_id: str | None = None) -> dict[str, Any]:
    meshes = frame.get("surface_meshes", [])
    if mesh_id is None:
        if len(meshes) != 1:
            raise AssertionError("expected exactly one post-event surface mesh")
        return meshes[0]
    matches = [mesh for mesh in meshes if str(mesh.get("id")) == mesh_id]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one surface mesh {mesh_id!r}")
    return matches[0]


def _postcoalescence_evidence() -> tuple[dict[str, Any], dict[str, Any]]:
    scenario = json.loads(_POST_EVENT_SCENARIO.read_text(encoding="utf-8"))
    requested_frames = 16
    frames, backend_meta = run_postcoalescence_frames(scenario, requested_frames)
    event_frames = [frame for frame in frames if frame.get("event_runtime", {}).get("phase") == "EVENT"]
    post = [
        frame for frame in frames
        if frame.get("event_runtime", {}).get("phase") == "POST_EVENT_TRANSIENT_RELAXATION"
    ]
    event_frame = event_frames[0] if len(event_frames) == 1 else {}
    events = list((event_frame.get("topology") or {}).get("events") or [])
    event_ids = [str(event.get("id")) for event in events]
    event_types = [str(event.get("type")) for event in events]

    restart_meshes = [
        mesh for mesh in event_frame.get("surface_meshes", [])
        if isinstance(mesh.get("restart_geometry"), dict)
    ]
    restart_geometry_preserved = False
    geometry_evolved = False
    if len(restart_meshes) == 1 and post:
        event_mesh = restart_meshes[0]
        seed_mesh = _mesh(post[0], str(event_mesh["id"]))
        restart_geometry_preserved = (
            seed_mesh.get("vertices") == event_mesh.get("vertices")
            and seed_mesh.get("faces") == event_mesh.get("faces")
            and post[0].get("diagnostics", {}).get("post_event_relaxation", {}).get("seed_geometry_preserved") is True
        )
        initial_signature = (
            seed_mesh.get("vertex_count"),
            seed_mesh.get("face_count"),
            canonical_json(seed_mesh.get("vertices")),
            canonical_json(seed_mesh.get("faces")),
        )
        for frame in post[1:]:
            mesh = _mesh(frame, str(seed_mesh["id"]))
            signature = (
                mesh.get("vertex_count"),
                mesh.get("face_count"),
                canonical_json(mesh.get("vertices")),
                canonical_json(mesh.get("faces")),
            )
            if signature != initial_signature:
                geometry_evolved = True
                break

    post_times = [float(frame["simulation_time_s"]) for frame in post]
    event_time = float(event_frame["simulation_time_s"]) if event_frame else None
    times_valid = bool(
        len(post) >= 3
        and event_time is not None
        and post_times[0] == event_time
        and all(after > before for before, after in zip(post_times, post_times[1:]))
    )
    event_history_preserved = bool(
        events
        and event_types == ["RUPTURE", "COALESCENCE"]
        and all(list((frame.get("topology") or {}).get("events") or []) == events for frame in post)
        and all(frame.get("event_runtime", {}).get("event_ids") == event_ids for frame in post)
    )

    volume_errors = [
        float(frame.get("diagnostics", {}).get("post_event_relaxation", {}).get("volume_relative_error", math.inf))
        for frame in post
    ]
    export_volume_errors = [
        float(frame.get("diagnostics", {}).get("max_relative_volume_error", math.inf))
        for frame in post
    ]
    targets = [
        float(frame.get("diagnostics", {}).get("post_event_relaxation", {}).get("target_volume_m3", math.nan))
        for frame in post
    ]
    target_constant = bool(targets and all(value == targets[0] for value in targets) and math.isfinite(targets[0]))

    lineage_preserved = False
    child_id = None
    parents: list[str] | tuple[str, ...] | None = None
    coalescence = next((event for event in events if event.get("type") == "COALESCENCE"), None)
    if coalescence is not None:
        lineage = coalescence.get("lineage") or {}
        if len(lineage) == 1:
            child_id, parents = next(iter(lineage.items()))
            lineage_preserved = all(
                frame.get("event_runtime", {}).get("child_bubble_id") == child_id
                and frame.get("event_runtime", {}).get("parent_lineage") == parents
                and any(
                    bubble.get("id") == child_id
                    and bubble.get("lineage") == parents
                    and bubble.get("status") == "ALIVE"
                    for bubble in frame.get("bubbles", [])
                )
                for frame in post
            )

    physical_advancement = bool(
        post
        and post[0].get("event_runtime", {}).get("post_event_relaxation") == "INITIALIZED_FROM_CONSERVATIVE_RESTART"
        and not post[0].get("event_runtime", {}).get("physical_advancement_after_event")
        and all(
            frame.get("event_runtime", {}).get("post_event_relaxation") == "PHYSICALLY_ADVANCED"
            and frame.get("event_runtime", {}).get("physical_advancement_after_event") is True
            for frame in post[1:]
        )
    )

    max_volume = max(volume_errors, default=math.inf)
    max_export_volume = max(export_volume_errors, default=math.inf)
    volume_limit = 5.0e-10
    checks = {
        "single_event_frame": len(event_frames) == 1,
        "event_order": event_types == ["RUPTURE", "COALESCENCE"],
        "event_history_preserved": event_history_preserved,
        "post_event_frame_count": len(post),
        "time_window_valid": times_valid,
        "restart_geometry_preserved": restart_geometry_preserved,
        "geometry_evolved_after_seed": geometry_evolved,
        "target_volume_constant": target_constant,
        "max_volume_relative_error": max_volume,
        "max_export_volume_relative_error": max_export_volume,
        "lineage_preserved": lineage_preserved,
        "physical_advancement_after_seed": physical_advancement,
        "child_bubble_id": child_id,
        "parent_lineage": parents,
        "event_ids": event_ids,
        "event_time_s": event_time,
        "first_post_time_s": post_times[0] if post_times else None,
        "last_post_time_s": post_times[-1] if post_times else None,
    }
    passed = bool(
        checks["single_event_frame"]
        and checks["event_order"]
        and event_history_preserved
        and times_valid
        and restart_geometry_preserved
        and geometry_evolved
        and target_constant
        and max_volume <= volume_limit
        and max_export_volume <= volume_limit
        and lineage_preserved
        and physical_advancement
    )
    evidence = {
        "benchmark": "post-coalescence-continuation",
        "checks": checks,
        "backend": backend_meta,
        "passed": passed,
    }
    setup = {
        "scenario_id": scenario["scenario_id"],
        "random_seed": scenario["random_seed"],
        "requested_frames": requested_frames,
        "output_cadence_s": scenario["user_editable"]["runtime"]["output_cadence_s"],
        "initial_bubble_count": len(scenario["initial_bubbles"]),
        "initial_shared_film_count": len(scenario["initial_film_regions"]),
        "qualified_time_window_s": [event_time, post_times[-1] if post_times else None],
    }
    return evidence, setup


def run_validation() -> dict[str, Any]:
    static = transient_api.sharp_static_sphere()
    static_window = _short_static_window()
    pressure = transient_api.pressure_jump()
    density = transient_api.density_contrast()
    symmetry = transient_api.zero_g_symmetry()
    replay = transient_api.replay()
    amr_topology = transient_api.amr_topology()
    amr_static = transient_api.amr_static_sphere()
    amr_pressure = transient_api.amr_pressure_jump()
    amr_replay = transient_api.amr_replay()
    remesh_quality = transient_api.remesh_quality()
    remesh_conservation = transient_api.remesh_conservation()
    remesh_replay = transient_api.remesh_replay()
    wall = boundary_api.wall_contact()
    angle = boundary_api.contact_angle()
    boundary_replay = boundary_api.boundary_replay()
    event_conservation = event_api.coalescence_conservation_benchmark()
    rupture_threshold = event_api.rupture_threshold_benchmark()
    rupture_convergence = event_api.rupture_convergence_benchmark()
    event_replay = event_api.event_replay_benchmark()
    post_event, post_setup = _postcoalescence_evidence()

    records = [
        _record(
            "transient-static-foundation",
            "Static sharp-interface volume/stability/spurious-current foundation",
            ["B03", "B07", "B12"],
            "MODELED",
            {
                "geometry": "single isolated icosphere",
                "gravity_m_s2": [0.0, 0.0, 0.0],
                "short_window": static_window,
                "benchmark_levels": ["8^3", "12^3"],
            },
            static,
            static["gates"],
            ["bubblelab.solvers.transient.benchmarks.sharp_static_sphere", "BENCHMARK_MATRIX B03/B07/B12"],
            [
                "The accepted CI ladder is a short static smoke/foundation run, not the B03 >=10-characteristic-time transient qualification.",
                "The accepted CI grids are coarser than eta_b <= 0.02, so this does not claim final B12 release qualification.",
                "The hold window is shorter than the B07 >=5-capillary-time transient stability requirement.",
            ],
        ),
        _record(
            "pressure-density-support",
            "Sharp pressure-jump convergence and density-contrast support",
            ["B09", "B12"],
            "MODELED",
            {
                "pressure_levels": len(pressure["levels"]),
                "density_case": "rho_inside=0.60 kg/m3, rho_outside=1.204 kg/m3, gravity=-9.81 m/s2 y",
            },
            {"pressure_jump": pressure, "density_contrast": density, "passed": bool(pressure["passed"] and density["passed"])},
            {"pressure_jump": pressure["gates"], "density_contrast": density["gates"]},
            ["bubblelab.solvers.transient.benchmarks.pressure_jump", "bubblelab.solvers.transient.benchmarks.density_contrast"],
            ["The density check is a periodic reference-box buoyancy/hydrostatic check, not a terminal-rise or nonperiodic far-field benchmark."],
        ),
        _record(
            "zero-g-symmetry",
            "Zero-gravity centroid symmetry smoke",
            ["B08"],
            "MODELED",
            {"gravity_m_s2": [0.0, 0.0, 0.0], "steps": 1, "scope": "accepted transient smoke"},
            symmetry,
            symmetry["gates"],
            ["bubblelab.solvers.transient.benchmarks.zero_g_symmetry", "BENCHMARK_MATRIX B08"],
            ["This smoke case does not include the rotated, non-grid-aligned repeat required for full B08 qualification."],
        ),
        _record(
            "deterministic-replay",
            "Same-build deterministic transient replay",
            ["B11"],
            "RESOLVED",
            {"runs": 2, "steps_per_run": replay["metrics"]["step_count"], "comparison": "exact SHA-256 replay signature"},
            replay,
            {"hash_equal": True, "history_length_equal": True},
            ["bubblelab.solvers.transient.benchmarks.replay", "BENCHMARK_MATRIX B11"],
            ["Exact replay is a same-build deterministic property; it is not a cross-platform bitwise-portability claim."],
        ),
        _record(
            "amr-integration",
            "AMR hierarchy, static behavior, pressure convergence and replay",
            ["B03", "B07", "B11", "B12"],
            "MODELED",
            {
                "topology_levels": amr_topology["metrics"]["levels"],
                "active_cells_by_level": amr_topology["metrics"]["active_cells_by_level"],
                "static_finest_eta_b": amr_static["amr"]["finest_eta_b"],
                "b12_final_qualified": amr_static["b12_final_qualified"],
                "pressure_level_count": len(amr_pressure["levels"]),
            },
            {
                "topology": amr_topology,
                "static": amr_static,
                "pressure": amr_pressure,
                "replay": amr_replay,
                "passed": bool(amr_topology["passed"] and amr_static["passed"] and amr_pressure["passed"] and amr_replay["passed"]),
            },
            {
                "topology": amr_topology["gates"],
                "static": amr_static["gates"],
                "pressure": amr_pressure["gates"],
            },
            [
                "bubblelab.solvers.transient.benchmarks.amr_topology",
                "bubblelab.solvers.transient.benchmarks.amr_static_sphere",
                "bubblelab.solvers.transient.benchmarks.amr_pressure_jump",
                "bubblelab.solvers.transient.benchmarks.amr_replay",
            ],
            ["AMR evidence remains foundation/convergence evidence and is not promoted to final B12 unless the producing benchmark reports b12_final_qualified=true."],
        ),
        _record(
            "conservative-remeshing",
            "Conservative remeshing quality, transfer and replay",
            ["B14", "B11"],
            "RESOLVED",
            {"operations": ["split", "collapse", "flip", "tangential smoothing"], "field": "generic face-integrated areal mass"},
            {
                "quality": remesh_quality,
                "conservation": remesh_conservation,
                "replay": remesh_replay,
                "passed": bool(remesh_quality["passed"] and remesh_conservation["passed"] and remesh_replay["passed"]),
            },
            {"quality": remesh_quality["gates"], "conservation": remesh_conservation["gates"]},
            ["bubblelab.solvers.transient.benchmarks.remesh_quality", "bubblelab.solvers.transient.benchmarks.remesh_conservation", "bubblelab.solvers.transient.benchmarks.remesh_replay"],
            ["B14 evidence validates conservative mesh-transfer infrastructure; it is not film-drainage or surfactant-transport physics."],
        ),
        _record(
            "boundary-contact",
            "Tracked-front wall contact and modeled wetting",
            [],
            "MODELED",
            {"wall": "plane y=0", "kinematics": "tracked-front no-penetration with free-slip tangential motion", "contact_angle_target_deg": angle["metrics"]["target_contact_angle_deg"]},
            {
                "wall_contact": wall,
                "contact_angle": angle,
                "replay": boundary_replay,
                "passed": bool(wall["passed"] and angle["passed"] and boundary_replay["passed"]),
            },
            {"wall_contact": wall["gates"], "contact_angle": angle["gates"]},
            ["bubblelab.solvers.boundary.benchmarks.wall_contact", "bubblelab.solvers.boundary.benchmarks.contact_angle", "bubblelab.solvers.boundary.benchmarks.boundary_replay"],
            ["The ambient Eulerian grid remains periodic; this is not a resolved no-slip wall CFD benchmark.", "The wetting law is a local geometric model and the closed-front mesh is not a finite liquid meniscus."],
        ),
        _record(
            "coalescence-conservation",
            "Topology-event bookkeeping conservation",
            ["B10", "B11"],
            "MODELED",
            {"trigger_time_s": 0.125, "parents": ["bubble-a", "bubble-b"], "expected_event_order": ["RUPTURE", "COALESCENCE"]},
            {
                "conservation": event_conservation,
                "replay": event_replay,
                "passed": bool(event_conservation["passed"] and event_replay["passed"]),
            },
            {
                "gas_relative_error": 1.0e-12,
                "target_volume_relative_error": 1.0e-12,
                "momentum_relative_error": 1.0e-12,
                "restart_geometry_volume_relative_error": 1.0e-12,
                "exact_event_order": ["RUPTURE", "COALESCENCE"],
            },
            ["bubblelab.solvers.events.benchmarks.coalescence_conservation_benchmark", "bubblelab.solvers.events.benchmarks.event_replay_benchmark", "BENCHMARK_MATRIX B10/B11"],
            ["This is event bookkeeping/restart conservation; singular coalescence flow and full surface-energy evolution are not claimed resolved."],
        ),
        _record(
            "rupture-time-convergence",
            "Rupture threshold localization and timestep convergence",
            ["B16"],
            "MODELED",
            {"thickness_threshold_m": rupture_threshold["threshold_m"], "timesteps_s": rupture_convergence["timestep_s"], "trajectory": rupture_threshold["method"]},
            {
                "threshold": rupture_threshold,
                "convergence": rupture_convergence,
                "passed": bool(rupture_threshold["passed"] and rupture_convergence["passed"]),
            },
            {"threshold_relative_time_error": 0.005, "fine_vs_finer_relative_shift": 0.02, "pre_event_fine_vs_finer_shift_over_hcrit": 0.02, "requires_decreasing_error": True},
            ["bubblelab.solvers.events.benchmarks.rupture_threshold_benchmark", "bubblelab.solvers.events.benchmarks.rupture_convergence_benchmark", "BENCHMARK_MATRIX B16"],
            ["The accepted convergence case refines timestep on a deterministic thinning trajectory; it does not add an independent spatial-refinement rupture study."],
        ),
        _record(
            "post-coalescence-continuation",
            "Authoritative restart and qualified post-coalescence transient continuation",
            ["B03", "B10", "B11"],
            "MODELED",
            post_setup,
            post_event,
            {"minimum_post_event_frames": 3, "maximum_volume_relative_error": 5.0e-10, "event_order": ["RUPTURE", "COALESCENCE"], "restart_seed_geometry": "exact", "lineage": "exact"},
            ["bubblelab.runtime.postcoalescence_runtime.run_postcoalescence_frames", "bubblelab.runtime.tools.validate_post_event_relaxation"],
            ["Qualification is limited to the reported short stable post-event window; long-time decay to equilibrium is not independently convergence-qualified.", "The adapter does not claim resolved singular coalescence CFD, rim retraction, spray/droplets or fragmentation."],
        ),
    ]

    capability_classification = {
        "sharp_interface_transient": "MODELED",
        "amr": "MODELED",
        "conservative_remeshing": "RESOLVED",
        "solid_contact_and_wetting": "MODELED",
        "topology_event_bookkeeping": "MODELED",
        "deterministic_same_build_replay": "RESOLVED",
        "post_coalescence_relaxation": "MODELED",
        "singular_rupture_coalescence_cfd": "NOT_IMPLEMENTED",
        "rim_retraction": "NOT_IMPLEMENTED",
        "spray_droplets_fragmentation": "NOT_IMPLEMENTED",
        "rendering_evidence": "VISUAL_ONLY",
    }
    passed = all(record["passed"] for record in records)
    result: dict[str, Any] = {
        "schema_version": 1,
        "suite": "integrated-transient-physics-validation",
        "classification_vocabulary": list(_CLASSIFICATIONS),
        "capability_classification": capability_classification,
        "records": records,
        "summary": {
            "passed": passed,
            "record_count": len(records),
            "passed_count": sum(record["passed"] for record in records),
            "failed_count": sum(not record["passed"] for record in records),
            "matrix_ids_covered": sorted({item for record in records for item in record["matrix_mapping"]}),
        },
        "limitations": [
            "Foundation or short-window evidence is kept explicitly qualified and is not promoted to final long-time or fine-grid release qualification.",
            "Boundary contact is MODELED tracked-front no-penetration/free-slip wetting, not no-slip solid-fluid CFD.",
            "Post-coalescence continuation is MODELED over its stated stable window and does not resolve singular rupture/coalescence physics.",
        ],
    }
    result["replay_payload_sha256"] = canonical_hash(result)
    return result


def failed_gate_messages(result: dict[str, Any]) -> list[str]:
    return [
        f"{record['gate_id']}: accepted/integration evidence failed"
        for record in result["records"]
        if not record["passed"]
    ]
