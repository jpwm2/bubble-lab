"""Deterministic transient continuation from production fragmentation child meshes."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from bubblelab.runtime.fragmentation_runtime import run_fragmentation_frames
from bubblelab.runtime.runner import _canonical_bytes, scenario_hash
from bubblelab.solvers.transient import (
    FilmFront,
    GridConfig,
    RemeshConfig,
    TransientConfig,
    TransientSoapFilmSolver,
    frame_dict as transient_frame,
)

BACKEND_IDENTITY = "fragmentation-to-transient-relaxation"
BACKEND_VERSION = "1.0.0"
PHASE = "POST_FRAGMENTATION_TRANSIENT_RELAXATION"


def _wind_velocity(scenario: Mapping[str, Any]) -> tuple[float, float, float]:
    raw = (scenario["environment"].get("wind") or {}).get("velocity_m_s") or (0.0, 0.0, 0.0)
    values = tuple(float(value) for value in raw)
    if len(values) != 3 or any(not math.isfinite(value) for value in values):
        raise ValueError("environment.wind.velocity_m_s must contain three finite values")
    return values  # type: ignore[return-value]


def _config(scenario: Mapping[str, Any]) -> Mapping[str, Any]:
    editable = scenario.get("user_editable")
    if not isinstance(editable, Mapping):
        raise ValueError("user_editable must be an object")
    value = editable.get("postfragmentation_relaxation", {})
    if not isinstance(value, Mapping):
        raise ValueError("user_editable.postfragmentation_relaxation must be an object")
    return value


def _unflatten(values: Any, width: int, name: str) -> tuple[tuple[Any, ...], ...]:
    if not isinstance(values, list) or len(values) % width:
        raise RuntimeError(f"{name} has invalid flattened storage")
    return tuple(tuple(values[i + j] for j in range(width)) for i in range(0, len(values), width))


def _mesh_arrays(mesh: Mapping[str, Any]) -> tuple[tuple[tuple[float, float, float], ...], tuple[tuple[int, int, int], ...]]:
    raw_vertices = _unflatten(mesh["vertices"]["values"], 3, "restart vertices")
    raw_faces = _unflatten(mesh["faces"]["values"], 3, "restart faces")
    vertices = tuple(tuple(float(value) for value in vertex) for vertex in raw_vertices)
    faces = tuple(tuple(int(value) for value in face) for face in raw_faces)
    return vertices, faces  # type: ignore[return-value]


def _mesh_digest(vertices: Any, faces: Any) -> str:
    payload = json.dumps(
        {"vertices": vertices, "faces": faces},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _closed_oriented_manifold(faces: Any) -> bool:
    counts: dict[tuple[int, int], int] = {}
    balance: dict[tuple[int, int], int] = {}
    for face in faces:
        if len(face) != 3 or len(set(face)) != 3:
            return False
        for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            key = (a, b) if a < b else (b, a)
            counts[key] = counts.get(key, 0) + 1
            balance[key] = balance.get(key, 0) + (1 if a < b else -1)
    return bool(counts) and all(count == 2 and balance[edge] == 0 for edge, count in counts.items())


def _film_tension(split_frame: Mapping[str, Any], bubble_id: str) -> float:
    matches = [
        film for film in split_frame["film_regions"]
        if str(film["adjacent"][0]) == bubble_id and str(film["adjacent"][1]) == "EXTERIOR"
    ]
    if len(matches) != 1:
        raise RuntimeError(f"fragmentation child {bubble_id!r} has no unique outer film")
    value = float(matches[0]["surface_tension_n_m"])
    if value <= 0.0 or not math.isfinite(value):
        raise RuntimeError("fragmentation child film tension must be finite and positive")
    return value


def _active_children(split_frame: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    events = split_frame.get("topology", {}).get("events", [])
    split_events = [event for event in events if event.get("type") == "SPLIT"]
    if len(split_events) != 1:
        raise RuntimeError("post-fragmentation continuation requires exactly one SPLIT event")
    child_ids = [str(value) for value in split_events[0]["bubble_ids_after"]]
    if len(child_ids) != 2:
        raise RuntimeError("supported fragmentation continuation requires exactly two children")
    by_id = {str(bubble["id"]): bubble for bubble in split_frame["bubbles"]}
    try:
        return [by_id[child_id] for child_id in child_ids]
    except KeyError as exc:
        raise RuntimeError("SPLIT event child is missing from fragmentation frame") from exc


def _grid_for_fronts(fronts: list[FilmFront], scenario: Mapping[str, Any], translation: tuple[float, float, float]) -> GridConfig:
    config = _config(scenario)
    cells = int(config.get("grid_cells_per_axis", 10))
    if cells < 4:
        raise ValueError("grid_cells_per_axis must be at least four")
    coordinates = [vertex for front in fronts for vertex in front.vertices]
    lo = tuple(min(vertex[axis] for vertex in coordinates) for axis in range(3))
    hi = tuple(max(vertex[axis] for vertex in coordinates) for axis in range(3))
    span = max(hi[axis] - lo[axis] for axis in range(3))
    if span <= 0.0 or not math.isfinite(span):
        raise RuntimeError("fragmentation restart mesh has invalid bounds")
    margin_fraction = float(config.get("grid_margin_fraction", 0.20))
    if margin_fraction <= 0.0 or not math.isfinite(margin_fraction):
        raise ValueError("grid_margin_fraction must be finite and positive")
    extent = span * (1.0 + 2.0 * margin_fraction)
    center = tuple(0.5 * (lo[axis] + hi[axis]) for axis in range(3))
    origin = tuple(center[axis] - 0.5 * extent for axis in range(3))
    wind = _wind_velocity(scenario)
    background = tuple(wind[axis] + translation[axis] for axis in range(3))
    environment = scenario["environment"]
    return GridConfig(
        cells=(cells, cells, cells),
        origin_m=origin,  # type: ignore[arg-type]
        extent_m=(extent, extent, extent),
        density_kg_m3=float(environment["ambient_density_kg_m3"]),
        dynamic_viscosity_pa_s=float(environment["ambient_dynamic_viscosity_pa_s"]),
        background_velocity_m_s=background,  # type: ignore[arg-type]
    )


def _build_solver(split_frame: Mapping[str, Any], scenario: Mapping[str, Any]) -> tuple[TransientSoapFilmSolver, dict[str, Any]]:
    children = _active_children(split_frame)
    meshes = {str(mesh["owner_bubble_ids"][0]): mesh for mesh in split_frame["surface_meshes"]}
    fronts: list[FilmFront] = []
    source: dict[str, Any] = {}
    velocities = [tuple(float(value) for value in child["velocity_m_s"]) for child in children]
    if any(velocity != velocities[0] for velocity in velocities[1:]):
        raise RuntimeError(
            "accepted transient backend cannot seed independent child bulk velocities; fragmentation children must share translation velocity"
        )
    for child in children:
        bubble_id = str(child["id"])
        try:
            mesh = meshes[bubble_id]
        except KeyError as exc:
            raise RuntimeError(f"fragmentation child {bubble_id!r} has no restart mesh") from exc
        vertices, faces = _mesh_arrays(mesh)
        if not bool(mesh.get("closed_manifold")) or not _closed_oriented_manifold(faces):
            raise RuntimeError("fragmentation restart mesh is not a closed oriented manifold")
        film = next(
            film for film in split_frame["film_regions"]
            if str(film["adjacent"][0]) == bubble_id
        )
        front = FilmFront(
            bubble_id=bubble_id,
            mesh_id=str(mesh["id"]),
            film_id=str(film["id"]),
            vertices=list(vertices),
            faces=list(faces),
            surface_tension_n_m=_film_tension(split_frame, bubble_id),
            target_volume_m3=float(child["volume_m3"]),
        )
        if tuple(front.vertices) != vertices or tuple(front.faces) != faces:
            raise RuntimeError("accepted FilmFront initialization changed authoritative fragmentation child mesh")
        represented = float(mesh["represented_volume_m3"])
        if abs(front.volume() - represented) / max(represented, 1.0e-300) > 1.0e-12:
            raise RuntimeError("FilmFront volume differs from authoritative fragmentation mesh")
        source[bubble_id] = {
            "vertices": vertices,
            "faces": faces,
            "mesh_digest": str(mesh["mesh_digest"]),
            "target_volume_m3": float(child["volume_m3"]),
            "lineage": tuple(str(value) for value in child.get("lineage", [])),
            "velocity_m_s": velocities[len(fronts)],
            "gas_amount_mol": child.get("gas_amount_mol"),
            "temperature_k": child.get("temperature_k"),
            "gas_species": child.get("gas_species"),
        }
        fronts.append(front)
    transient_config = TransientConfig(
        grid=_grid_for_fronts(fronts, scenario, velocities[0]),
        gravity_m_s2=tuple(float(value) for value in scenario["environment"]["gravity_m_s2"]),
        deterministic_seed=int(scenario["random_seed"]),
        preserve_closed_bubble_volume=True,
        sharp_pressure_jump=False,
        remeshing=RemeshConfig(mode="quality"),
    )
    solver = TransientSoapFilmSolver(fronts, transient_config)
    solver.time_s = float(split_frame["simulation_time_s"])
    for front in solver.fronts:
        seed = source[front.bubble_id]
        if tuple(front.vertices) != seed["vertices"] or tuple(front.faces) != seed["faces"]:
            raise RuntimeError("transient solver construction changed authoritative fragmentation restart mesh")
    return solver, source


def _child_metrics(front: FilmFront, source: Mapping[str, Any], velocity: tuple[float, float, float]) -> dict[str, Any]:
    target = float(source["target_volume_m3"])
    sphere_area = (36.0 * math.pi * target * target) ** (1.0 / 3.0)
    area = front.area()
    return {
        "volume_m3": front.volume(),
        "target_volume_m3": target,
        "volume_relative_error": abs(front.volume() - target) / target,
        "centroid_m": list(front.centroid()),
        "velocity_m_s": list(velocity),
        "surface_area_m2": area,
        "minimum_sphere_area_m2": sphere_area,
        "surface_area_excess_m2": max(0.0, area - sphere_area),
        "vertex_count": len(front.vertices),
        "face_count": len(front.faces),
        "closed_oriented_manifold": _closed_oriented_manifold(front.faces),
        "mesh_state_digest": _mesh_digest(front.vertices, front.faces),
        "source_fragmentation_mesh_digest": source["mesh_digest"],
    }


def _composed_fragmentation_frame(
    frame: Mapping[str, Any], scenario: Mapping[str, Any], *, stage: str
) -> dict[str, Any]:
    """Wrap fragmentation-stage frames in the composed replay backend identity."""
    out = copy.deepcopy(dict(frame))
    stage_solver = copy.deepcopy(out["manifest"]["solver"])
    out["manifest"]["solver"] = {
        "backend": BACKEND_IDENTITY,
        "version": BACKEND_VERSION,
        "adapter": f"production-fragmentation-{stage}-in-postfragmentation-replay",
    }
    provenance = out["manifest"].setdefault("provenance", {})
    provenance.update({
        "producer": "bubblelab.runtime.postfragmentation_relaxation",
        "source_scenario": scenario["scenario_id"],
        "scenario_sha256": scenario_hash(scenario),
        "fragmentation_backend": stage_solver,
        "analytic_surface_replacement": False,
    })
    return out


def _combined_frame(
    solver: TransientSoapFilmSolver,
    split_frame: Mapping[str, Any],
    scenario: Mapping[str, Any],
    source: Mapping[str, Mapping[str, Any]],
    *,
    index: int,
) -> dict[str, Any]:
    raw = transient_frame(solver, f"{scenario['scenario_id']}-{index + 2:06d}-relax")
    out = copy.deepcopy(raw)
    child_dynamic = {str(bubble["id"]): bubble for bubble in raw["bubbles"]}
    history = copy.deepcopy(list(split_frame["bubbles"]))
    for bubble in history:
        bubble_id = str(bubble["id"])
        if bubble_id not in child_dynamic:
            continue
        dynamic = child_dynamic[bubble_id]
        for key in (
            "volume_m3", "equivalent_radius_m", "centroid_m", "velocity_m_s",
            "pressure_pa", "status", "gas_properties", "film_material",
        ):
            if key in dynamic:
                bubble[key] = copy.deepcopy(dynamic[key])
        bubble["lineage"] = list(source[bubble_id]["lineage"])
        bubble["gas_amount_mol"] = source[bubble_id]["gas_amount_mol"]
        bubble["temperature_k"] = source[bubble_id]["temperature_k"]
        bubble["gas_species"] = source[bubble_id]["gas_species"]
    out["bubbles"] = history
    out["topology"] = {
        "adjacency": [
            {"a": film["adjacent"][0], "b": film["adjacent"][1], "film_id": film["id"]}
            for film in raw["film_regions"]
        ],
        "events": copy.deepcopy(split_frame["topology"]["events"]),
    }
    out["environment"] = copy.deepcopy(scenario["environment"])
    disclosures = copy.deepcopy(raw["manifest"].get("feature_disclosures", {}))
    disclosures.update(copy.deepcopy(split_frame["manifest"].get("feature_disclosures", {})))
    disclosures.update({
        "fragmentation_topology_surgery": "MODELED",
        "post_split_physical_relaxation": "MODELED",
        "post_split_restart_geometry": "MODELED",
        "geometry_evolution": "MODELED",
        "singular_pinch_off_cfd": "NOT_IMPLEMENTED",
        "retracting_liquid_rim": "NOT_IMPLEMENTED",
        "droplet_spray": "NOT_IMPLEMENTED",
        "arbitrary_multi_neck_topology": "NOT_IMPLEMENTED",
    })
    out["manifest"]["feature_disclosures"] = disclosures
    out["manifest"]["solver"] = {
        "backend": BACKEND_IDENTITY,
        "version": BACKEND_VERSION,
        "adapter": "production-SPLIT-cut-cap-mesh-to-accepted-transient-front-tracking",
    }
    provenance = out["manifest"].setdefault("provenance", {})
    provenance.update({
        "producer": "bubblelab.runtime.postfragmentation_relaxation",
        "source_scenario": scenario["scenario_id"],
        "scenario_sha256": scenario_hash(scenario),
        "fragmentation_backend": split_frame["manifest"]["solver"],
        "transient_backend": raw["manifest"]["solver"],
        "restart_seed_geometry": "authoritative production SPLIT cut/cap child meshes",
        "analytic_surface_replacement": False,
    })
    metrics: dict[str, Any] = {}
    for front in solver.fronts:
        velocity = solver.bubble_velocity(front.bubble_id)
        if index == 0:
            velocity = source[front.bubble_id]["velocity_m_s"]
        metrics[front.bubble_id] = _child_metrics(front, source[front.bubble_id], velocity)
    out.setdefault("diagnostics", {})["postfragmentation_relaxation"] = {
        "relaxation_frame_index": index,
        "solver_step_index": solver.step_index,
        "seed_geometry_preserved": index == 0,
        "restart_mesh_authoritative": True,
        "analytic_surface_replacement": False,
        "max_child_volume_relative_error": max(value["volume_relative_error"] for value in metrics.values()),
        "all_children_closed_oriented_manifold": all(value["closed_oriented_manifold"] for value in metrics.values()),
        "children": metrics,
    }
    out["postfragmentation_runtime"] = {
        "phase": PHASE,
        "split_event_ids": [str(event["id"]) for event in split_frame["topology"]["events"]],
        "parent_bubble_id": str(split_frame["topology"]["events"][0]["bubble_ids_before"][0]),
        "child_bubble_ids": [front.bubble_id for front in solver.fronts],
        "parent_lineage": {bubble_id: list(source[bubble_id]["lineage"]) for bubble_id in source},
        "source_split_frame_id": split_frame["frame_id"],
        "restart_mesh_authoritative": True,
        "physical_advancement_after_split": index > 0,
        "solver_step_index": solver.step_index,
    }
    return out


def run_postfragmentation_frames(
    scenario: Mapping[str, Any], frames: int = 16
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if frames < 4:
        raise ValueError("post-fragmentation relaxation requires at least four replay frames")
    fragmentation_frames, fragmentation_backend = run_fragmentation_frames(scenario)
    if len(fragmentation_frames) != 2:
        raise RuntimeError("production fragmentation runtime did not emit pre-split and split frames")
    pre_frame, split_frame = fragmentation_frames
    solver, source = _build_solver(split_frame, scenario)
    config = _config(scenario)
    cadence = float(config.get("output_cadence_s", 5.0e-4))
    if cadence <= 0.0 or not math.isfinite(cadence):
        raise ValueError("postfragmentation output_cadence_s must be finite and positive")
    physical = [
        _composed_fragmentation_frame(pre_frame, scenario, stage="pre-split"),
        _composed_fragmentation_frame(split_frame, scenario, stage="split"),
    ]
    event_time = float(split_frame["simulation_time_s"])
    post_count = frames - len(physical)
    for index in range(post_count):
        if index > 0:
            solver.run_to_time(event_time + index * cadence)
        physical.append(_combined_frame(solver, split_frame, scenario, source, index=index))
    if solver.step_index <= 0:
        raise RuntimeError("post-fragmentation replay did not physically advance the transient solver")
    if any(not _closed_oriented_manifold(front.faces) for front in solver.fronts):
        raise RuntimeError("post-fragmentation transient window produced a non-manifold child front")
    return physical, {
        "identity": BACKEND_IDENTITY,
        "version": BACKEND_VERSION,
        "mode": "production deterministic SPLIT followed by accepted two-front transient relaxation",
        "fragmentation_backend": fragmentation_backend,
        "transient_backend": {"identity": "bubblelab-transient-reference", "version": solver.VERSION},
        "output_cadence_s": cadence,
        "post_split_frame_count": post_count,
        "singular_pinch_off_cfd": "NOT_IMPLEMENTED",
        "retracting_liquid_rim": "NOT_IMPLEMENTED",
        "droplet_spray": "NOT_IMPLEMENTED",
        "final_equilibrium_proof": "NOT_CLAIMED",
    }


def run_postfragmentation_scenario(
    scenario: Mapping[str, Any], output_dir: str | Path, frames: int = 16
) -> dict[str, Any]:
    from bubblelab_contract import assert_valid

    scenario_copy = copy.deepcopy(dict(scenario))
    assert_valid(scenario_copy)
    physical, backend = run_postfragmentation_frames(scenario_copy, frames)
    for frame in physical:
        assert_valid(frame)
    out = Path(output_dir)
    (out / "frames").mkdir(parents=True, exist_ok=True)
    refs: list[dict[str, Any]] = []
    for index, frame in enumerate(physical):
        rel = f"frames/{index:06d}.json"
        (out / rel).write_bytes(_canonical_bytes(frame) + b"\n")
        refs.append({
            "frame_id": frame["frame_id"],
            "path": rel,
            "simulation_time_s": frame["simulation_time_s"],
        })
    split_frame = physical[1]
    replay = {
        "bundle_version": "1.0.0",
        "contract_version": "1.0.0",
        "scenario": {"id": scenario_copy["scenario_id"], "sha256": scenario_hash(scenario_copy)},
        "backend": backend,
        "random_seed": scenario_copy["random_seed"],
        "run_settings": {
            "backend": BACKEND_IDENTITY,
            "requested_frames": frames,
            "output_cadence_s": backend["output_cadence_s"],
        },
        "frames": refs,
        "checkpoints": [],
        "provenance": {
            "producer": "bubblelab.runtime.postfragmentation_relaxation",
            "source_scenario": scenario_copy["scenario_id"],
            "source_split_frame_id": split_frame["frame_id"],
        },
        "fragmentation": {
            "event_ids": [str(event["id"]) for event in split_frame["topology"]["events"]],
            "parent_bubble_ids": list(split_frame["topology"]["events"][0]["bubble_ids_before"]),
            "child_bubble_ids": list(split_frame["topology"]["events"][0]["bubble_ids_after"]),
            "restart_geometry": "authoritative production SPLIT cut/cap child meshes",
        },
        "fidelity": {
            "requested": scenario_copy["requested_fidelity_tier"],
            "produced": physical[-1]["manifest"]["fidelity_tier"],
            "feature_disclosures": physical[-1]["manifest"]["feature_disclosures"],
            "final_equilibrium_proof": "NOT_CLAIMED",
        },
    }
    (out / "replay.json").write_bytes(_canonical_bytes(replay) + b"\n")
    return replay
