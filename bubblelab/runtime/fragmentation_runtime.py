"""Authoritative deterministic runtime/export path for supported fragmentation splits."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from bubblelab.solvers.events.fragmentation import ParentState, TriMesh, necked_mesh, split_parent

BACKEND_IDENTITY = "fragmentation-topology"
BACKEND_VERSION = "1.0.0"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def _scenario_hash(scenario: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(scenario)).hexdigest()


def _vec3(value: Any, name: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{name} must contain three components")
    result = tuple(float(v) for v in value)
    if any(not math.isfinite(v) for v in result):
        raise ValueError(f"{name} must contain finite components")
    return result  # type: ignore[return-value]


def _fragmentation_config(scenario: Mapping[str, Any]) -> Mapping[str, Any]:
    editable = scenario.get("user_editable")
    if not isinstance(editable, Mapping):
        raise ValueError("user_editable must be an object")
    config = editable.get("fragmentation")
    if not isinstance(config, Mapping):
        raise ValueError("user_editable.fragmentation is required")
    return config


def _parent_mesh(config: Mapping[str, Any]) -> TriMesh:
    inline = config.get("parent_mesh")
    if isinstance(inline, Mapping):
        vertices = inline.get("vertices")
        faces = inline.get("faces")
        if not isinstance(vertices, list) or not isinstance(faces, list):
            raise ValueError("parent_mesh requires vertices and faces arrays")
        return TriMesh(
            tuple(_vec3(v, "parent_mesh vertex") for v in vertices),
            tuple(tuple(int(i) for i in face) for face in faces),  # type: ignore[arg-type]
        ).reoriented_outward()
    generator = config.get("generator")
    if not isinstance(generator, Mapping) or generator.get("type") != "NECKED_SURFACE_OF_REVOLUTION":
        raise ValueError("fragmentation requires inline parent_mesh or supported necked generator")
    return necked_mesh(
        half_length=float(generator.get("half_length_m", 1.8)),
        minor_radius=float(generator.get("minor_radius_m", 1.0)),
        neck_depth=float(generator.get("neck_depth", 0.58)),
        neck_width=float(generator.get("neck_width_m", 0.48)),
        asymmetry=float(generator.get("asymmetry", 0.10)),
        axial_segments=int(generator.get("axial_segments", 24)),
        circum_segments=int(generator.get("circum_segments", 36)),
    )


def _manifest(scenario: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": "1.0.0",
        "units": {
            "system": "SI", "length": "m", "time": "s", "mass": "kg",
            "pressure": "Pa", "temperature": "K", "amount": "mol",
        },
        "solver": {"backend": BACKEND_IDENTITY, "version": BACKEND_VERSION, "adapter": None},
        "fidelity_tier": scenario["requested_fidelity_tier"],
        "feature_disclosures": {
            "fragmentation_topology_surgery": "MODELED",
            "singular_pinch_off_cfd": "NOT_IMPLEMENTED",
            "post_split_physical_relaxation": "NOT_IMPLEMENTED",
            "retracting_liquid_rim": "NOT_IMPLEMENTED",
            "droplet_spray": "NOT_IMPLEMENTED",
        },
        "random_seed": int(scenario["random_seed"]),
        "provenance": {
            "producer": "bubblelab.runtime.fragmentation_runtime",
            "source_scenario": scenario["scenario_id"],
            "tolerances": {"geometric_volume_relative": 5.0e-11},
        },
    }


def _mesh_contract(mesh_id: str, owner_id: str, mesh: TriMesh, *, parent_mesh_digest: str | None = None) -> dict[str, Any]:
    vertices = [component for point in mesh.vertices for component in point]
    faces = [index for face in mesh.faces for index in face]
    result = {
        "id": mesh_id,
        "geometry_role": "OUTER_FILM",
        "owner_bubble_ids": [owner_id],
        "region_labels": [owner_id, "EXTERIOR"],
        "vertex_count": len(mesh.vertices),
        "face_count": len(mesh.faces),
        "vertices": {"storage": "INLINE", "dtype": "float64", "shape": [len(mesh.vertices), 3], "values": vertices},
        "faces": {"storage": "INLINE", "dtype": "uint32", "shape": [len(mesh.faces), 3], "values": faces},
        "fields": {},
        "closed_manifold": mesh.is_closed_manifold(),
        "represented_volume_m3": mesh.volume(),
        "mesh_digest": mesh.digest(),
    }
    if parent_mesh_digest is not None:
        result["derived_from_parent_mesh_digest"] = parent_mesh_digest
    return result


def _equivalent_radius(volume: float) -> float:
    return (3.0 * volume / (4.0 * math.pi)) ** (1.0 / 3.0)


def _bubble_contract(
    bubble_id: str,
    volume_m3: float,
    centroid: tuple[float, float, float],
    velocity: tuple[float, float, float],
    status: str,
    *,
    gas_amount: float | None,
    temperature: float | None,
    gas_species: str | None,
    lineage: list[str] | None = None,
    geometry_status: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": bubble_id,
        "volume_m3": volume_m3,
        "equivalent_radius_m": _equivalent_radius(volume_m3),
        "centroid_m": list(centroid),
        "velocity_m_s": list(velocity),
        "status": status,
        "pressure_pa": None,
        "temperature_k": temperature,
        "gas_amount_mol": gas_amount,
        "gas_species": gas_species,
        "film_material": None,
    }
    if lineage is not None:
        result["lineage"] = lineage
    if geometry_status is not None:
        result["restart_geometry_status"] = geometry_status
    return result


def _film(film_id: str, bubble_id: str, mesh_id: str, surface_tension: float) -> dict[str, Any]:
    return {
        "id": film_id,
        "kind": "OUTER",
        "adjacent": [bubble_id, "EXTERIOR"],
        "mesh_id": mesh_id,
        "surface_tension_n_m": surface_tension,
        "thickness": None,
    }


def _frame(
    scenario: Mapping[str, Any], *, frame_id: str, time_s: float,
    bubbles: list[dict[str, Any]], meshes: list[dict[str, Any]], films: list[dict[str, Any]],
    events: list[dict[str, Any]], phase: str, diagnostics: dict[str, Any],
) -> dict[str, Any]:
    adjacency = [
        {"a": film["adjacent"][0], "b": film["adjacent"][1], "film_id": film["id"]}
        for film in films
    ]
    return {
        "contract_version": "1.0.0",
        "kind": "FRAME",
        "frame_id": frame_id,
        "simulation_time_s": time_s,
        "manifest": _manifest(scenario),
        "environment": copy.deepcopy(scenario["environment"]),
        "bubbles": bubbles,
        "surface_meshes": meshes,
        "film_regions": films,
        "junctions": [],
        "topology": {"adjacency": adjacency, "events": events},
        "diagnostics": diagnostics,
        "fragmentation_runtime": {"phase": phase, "backend": BACKEND_IDENTITY},
    }


def run_fragmentation_frames(scenario: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(scenario.get("initial_bubbles"), list) or len(scenario["initial_bubbles"]) != 1:
        raise ValueError("fragmentation runtime currently supports exactly one parent bubble")
    source = scenario["initial_bubbles"][0]
    config = _fragmentation_config(scenario)
    mesh = _parent_mesh(config)
    parent_id = str(source["id"])
    target_volume = float(source["volume_m3"])
    velocity = _vec3(source.get("velocity_m_s", [0.0, 0.0, 0.0]), "velocity_m_s")
    gas_amount = None if source.get("gas_amount_mol") is None else float(source["gas_amount_mol"])
    mass_kg = None if source.get("mass_kg") is None else float(source["mass_kg"])
    temperature = float(source.get("temperature_k") or 298.15)
    gas_species = source.get("gas_species")
    event_time = float(config.get("event_time_s", 0.0125))
    surface_tension = float(config.get("surface_tension_n_m", 0.03))
    parent = ParentState(
        parent_id, mesh, target_volume, gas_amount,
        velocity_m_s=velocity, mass_kg=mass_kg, temperature_k=temperature, gas_species=gas_species,
    )
    result = split_parent(parent, event_time_s=event_time)
    parent_centroid = mesh.volume_centroid()
    parent_mesh_id = f"mesh-{parent_id}-pre-split"
    pre_film_id = f"film-{parent_id}-pre-split"
    pre = _frame(
        scenario,
        frame_id=f"{scenario['scenario_id']}-000000-pre",
        time_s=0.0,
        bubbles=[_bubble_contract(parent_id, target_volume, parent_centroid, velocity, "ALIVE", gas_amount=gas_amount, temperature=temperature, gas_species=gas_species)],
        meshes=[_mesh_contract(parent_mesh_id, parent_id, mesh)],
        films=[_film(pre_film_id, parent_id, parent_mesh_id, surface_tension)],
        events=[],
        phase="PRE_SPLIT",
        diagnostics={
            "max_relative_volume_error": 0.0,
            "mesh_quality": {
                "parent_closed_manifold": mesh.is_closed_manifold(),
                "parent_mesh_digest": mesh.digest(),
                "neck_prominence_ratio": result.diagnostic.prominence_ratio,
                "neck_radius_to_spacing": result.diagnostic.radius_to_spacing,
            },
        },
    )
    post_bubbles = [
        _bubble_contract(parent_id, target_volume, parent_centroid, velocity, "SPLIT", gas_amount=gas_amount, temperature=temperature, gas_species=gas_species),
    ]
    post_meshes: list[dict[str, Any]] = []
    post_films: list[dict[str, Any]] = []
    for index, child in enumerate(result.children):
        post_bubbles.append(_bubble_contract(
            child.id, child.target_volume_m3, child.centroid_m, child.velocity_m_s, child.status,
            gas_amount=child.gas_amount_mol, temperature=child.temperature_k, gas_species=child.gas_species,
            lineage=list(child.lineage), geometry_status=child.geometry_status,
        ))
        mesh_id = f"mesh-{child.id}"
        post_meshes.append(_mesh_contract(mesh_id, child.id, child.mesh, parent_mesh_digest=mesh.digest()))
        post_films.append(_film(f"film-{child.id}", child.id, mesh_id, surface_tension))
    post = _frame(
        scenario,
        frame_id=f"{scenario['scenario_id']}-000001-split",
        time_s=event_time,
        bubbles=post_bubbles,
        meshes=post_meshes,
        films=post_films,
        events=[result.event_contract()],
        phase="POST_SPLIT_RESTART",
        diagnostics={
            "max_relative_volume_error": max(
                float(result.conservation["target_volume_relative_error"] or 0.0),
                float(result.conservation["geometric_volume_relative_error"] or 0.0),
            ),
            "mesh_quality": {
                "children_closed_manifold": [child.mesh.is_closed_manifold() for child in result.children],
                "cut_loop_vertex_counts": [result.surgery.negative.cut_loop_vertex_count, result.surgery.positive.cut_loop_vertex_count],
                "inserted_intersection_vertex_counts": [result.surgery.negative.inserted_intersection_vertex_count, result.surgery.positive.inserted_intersection_vertex_count],
                "restart_geometry_requires_relaxation": True,
            },
        },
    )
    backend = {
        "identity": BACKEND_IDENTITY,
        "version": BACKEND_VERSION,
        "mode": "deterministic supported-class triangulated neck split",
        "event_id": result.event_id,
        "parent_mesh_digest": mesh.digest(),
        "conservation": dict(result.conservation),
        "fidelity_boundary": result.event_contract()["fidelity_boundary"],
    }
    return [pre, post], backend


def run_fragmentation_scenario(scenario: Mapping[str, Any], output_dir: str | Path) -> dict[str, Any]:
    scenario_copy = copy.deepcopy(dict(scenario))
    frames, backend = run_fragmentation_frames(scenario_copy)
    out = Path(output_dir)
    (out / "frames").mkdir(parents=True, exist_ok=True)
    refs: list[dict[str, Any]] = []
    for index, frame in enumerate(frames):
        rel = f"frames/{index:06d}.json"
        (out / rel).write_bytes(_canonical_bytes(frame) + b"\n")
        refs.append({"frame_id": frame["frame_id"], "path": rel, "simulation_time_s": frame["simulation_time_s"]})
    replay = {
        "bundle_version": "1.0.0",
        "contract_version": "1.0.0",
        "scenario": {"id": scenario_copy["scenario_id"], "sha256": _scenario_hash(scenario_copy)},
        "backend": backend,
        "random_seed": scenario_copy["random_seed"],
        "run_settings": {"backend": BACKEND_IDENTITY, "frame_count": len(frames)},
        "frames": refs,
        "checkpoints": [],
        "provenance": {"producer": "bubblelab.runtime.fragmentation_runtime", "source_scenario": scenario_copy["scenario_id"]},
        "fragmentation": {
            "event_ids": [event["id"] for event in frames[-1]["topology"]["events"]],
            "terminal_phase": frames[-1]["fragmentation_runtime"]["phase"],
            "restart_geometry_requires_physical_relaxation": True,
        },
    }
    (out / "replay.json").write_bytes(_canonical_bytes(replay) + b"\n")
    return replay
