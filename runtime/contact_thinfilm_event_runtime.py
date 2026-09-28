"""Contact -> finite-thickness thin-film -> rupture/coalescence integration.

This adapter owns no new physics.  It runs the accepted contact transition until
its exact first shared-film geometry exists, seeds the accepted thin-film/event
runtime from explicit scenario state, and preserves the contact-created geometry
and IDs across the handoff.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from bubblelab.runtime.contact_runtime import run_contact_transition
from bubblelab.runtime.event_runtime import run_event_frames
from bubblelab.runtime.runner import _canonical_bytes, _decorate, scenario_hash
from bubblelab.runtime.thinfilm_runtime import feature_flags, output_cadence_s, thinfilm_config

VERSION = "0.1.0"
BACKEND_IDENTITY = "bubblelab-contact-thinfilm-events-runtime"


class ContactThinFilmEventConfigurationError(ValueError):
    """Raised when an integration scenario cannot be handed off without invention."""


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContactThinFilmEventConfigurationError(f"{name} must be an object")
    return value


def _explicit_physical_state(scenario: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    editable = _mapping(scenario.get("user_editable") or {}, "user_editable")
    film = _mapping(editable.get("thinfilm"), "user_editable.thinfilm")
    missing = [
        key
        for key in ("initial_thickness_m", "initial_surfactant_mol_m2")
        if key not in film
    ]
    if missing:
        raise ContactThinFilmEventConfigurationError(
            "contact thin-film handoff requires explicit " + ", ".join(missing)
        )
    flags = feature_flags(film)
    if not flags["gas_diffusion"]:
        raise ContactThinFilmEventConfigurationError(
            "contact thin-film event integration requires enable_gas_diffusion=true"
        )
    runtime = _mapping(editable.get("runtime"), "user_editable.runtime")
    if "output_cadence_s" not in runtime:
        raise ContactThinFilmEventConfigurationError(
            "contact thin-film handoff requires explicit runtime.output_cadence_s"
        )
    cadence = output_cadence_s(scenario)
    if cadence is None:
        raise ContactThinFilmEventConfigurationError("output_cadence_s is required")
    events = _mapping(editable.get("events"), "user_editable.events")

    bubbles = list(scenario.get("initial_bubbles") or [])
    if len(bubbles) != 2:
        raise ContactThinFilmEventConfigurationError(
            "contact thin-film event integration requires exactly two initial bubbles"
        )
    for bubble in bubbles:
        identifier = str(bubble.get("id"))
        for key in ("gas_amount_mol", "temperature_k"):
            if bubble.get(key) is None:
                raise ContactThinFilmEventConfigurationError(
                    f"bubble {identifier} requires explicit {key} for gas-transfer handoff"
                )
    return film, events


def _features_for_contact(source: Mapping[str, Any]) -> dict[str, bool]:
    features = {
        "film_sheet_geometry": True,
        "bulk_incompressible_flow": True,
        "automatic_contact_detection": True,
        "transient_contact_detection": True,
        "topology_change": True,
        "shared_films": True,
        "shared_film_topology": True,
        "dynamic_shared_films": True,
    }
    return features


def _contact_scenario(scenario: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(dict(scenario))
    requested = dict(out.get("requested_solver") or {})
    requested["backend"] = "contact-transition"
    requested["features"] = _features_for_contact(scenario)
    out["requested_solver"] = requested
    editable = dict(out.get("user_editable") or {})
    editable["features"] = _features_for_contact(scenario)
    out["user_editable"] = editable
    return out


def _matrix_rows(ref: Mapping[str, Any], width: int, name: str) -> list[list[Any]]:
    if ref.get("storage") != "INLINE":
        raise ContactThinFilmEventConfigurationError(f"{name} must use INLINE storage")
    shape = ref.get("shape")
    values = ref.get("values")
    if not isinstance(shape, Sequence) or len(shape) != 2 or int(shape[1]) != width:
        raise ContactThinFilmEventConfigurationError(f"{name} has invalid shape")
    rows = int(shape[0])
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise ContactThinFilmEventConfigurationError(f"{name} values are invalid")
    values_list = list(values)
    if len(values_list) == rows and all(
        isinstance(row, Sequence) and not isinstance(row, (str, bytes)) and len(row) == width
        for row in values_list
    ):
        return [list(row) for row in values_list]
    if len(values_list) == rows * width:
        return [
            [values_list[row * width + column] for column in range(width)]
            for row in range(rows)
        ]
    raise ContactThinFilmEventConfigurationError(f"{name} value count does not match shape")


def _flat_inline(ref: Mapping[str, Any], width: int, name: str) -> dict[str, Any]:
    rows = _matrix_rows(ref, width, name)
    return {
        "storage": "INLINE",
        "dtype": str(ref.get("dtype")),
        "shape": [len(rows), width],
        "values": [value for row in rows for value in row],
    }


def _geometry_digest(mesh: Mapping[str, Any]) -> str:
    payload = {
        "id": mesh["id"],
        "vertices": _matrix_rows(_mapping(mesh["vertices"], "vertices"), 3, "vertices"),
        "faces": _matrix_rows(_mapping(mesh["faces"], "faces"), 3, "faces"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _find_handoff(frames: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    matches: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for frame in frames:
        for event in (frame.get("topology") or {}).get("events", []):
            if event.get("transition_kind") == "CONTACT_FORMATION":
                matches.append((frame, event))
    if len(matches) != 1:
        raise RuntimeError("accepted contact runtime must emit exactly one CONTACT_FORMATION")
    frame, event = matches[0]
    result = copy.deepcopy(dict(frame))
    contact_event = copy.deepcopy(dict(event))
    return result, contact_event


def _shared_objects(frame: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    shared_films = [item for item in frame["film_regions"] if item.get("kind") == "SHARED"]
    if len(shared_films) != 1:
        raise RuntimeError("contact handoff must contain exactly one shared film")
    film = copy.deepcopy(shared_films[0])
    meshes = [item for item in frame["surface_meshes"] if item.get("id") == film.get("mesh_id")]
    if len(meshes) != 1:
        raise RuntimeError("contact handoff shared film must own exactly one mesh")
    return copy.deepcopy(meshes[0]), film


def _handoff_bubbles(
    scenario: Mapping[str, Any],
    handoff: Mapping[str, Any],
) -> list[dict[str, Any]]:
    source = {str(item["id"]): item for item in scenario["initial_bubbles"]}
    output: list[dict[str, Any]] = []
    for bubble in handoff["bubbles"]:
        identifier = str(bubble["id"])
        if identifier not in source:
            raise RuntimeError(f"contact handoff introduced unexpected bubble ID {identifier}")
        result = copy.deepcopy(dict(bubble))
        original = source[identifier]
        for key in ("gas_amount_mol", "temperature_k", "gas_species", "mass_kg", "molar_mass_kg_mol"):
            if key in original:
                result[key] = copy.deepcopy(original[key])
        output.append(result)
    if set(item["id"] for item in output) != set(source):
        raise RuntimeError("contact handoff did not preserve both canonical bubble IDs")
    return output


def _event_scenario(
    scenario: Mapping[str, Any],
    handoff: Mapping[str, Any],
    shared_mesh: Mapping[str, Any],
    shared_film: Mapping[str, Any],
) -> dict[str, Any]:
    out = copy.deepcopy(dict(scenario))
    requested = dict(out.get("requested_solver") or {})
    events = _mapping((out.get("user_editable") or {}).get("events"), "user_editable.events")
    rupture = bool(events.get("enable_rupture", True))
    requested["backend"] = "thinfilm-events"
    requested["features"] = {
        "shared_film_topology": True,
        "drainage": True,
        "surfactant_diffusion": True,
        "variable_surface_tension": True,
        "gas_diffusion": True,
        "coarsening": True,
        "rupture": rupture,
        "coalescence": rupture,
        "topology_change": rupture,
    }
    out["requested_solver"] = requested
    editable = dict(out.get("user_editable") or {})
    editable["features"] = copy.deepcopy(requested["features"])
    out["user_editable"] = editable
    out["scenario_id"] = str(scenario["scenario_id"]) + "-post-contact"
    out["initial_bubbles"] = _handoff_bubbles(scenario, handoff)

    mesh = copy.deepcopy(dict(shared_mesh))
    mesh["vertices"] = _flat_inline(_mapping(mesh["vertices"], "vertices"), 3, "vertices")
    mesh["faces"] = _flat_inline(_mapping(mesh["faces"], "faces"), 3, "faces")
    mesh["vertex_count"] = int(mesh["vertices"]["shape"][0])
    mesh["face_count"] = int(mesh["faces"]["shape"][0])
    mesh["fields"] = {}
    out["initial_surface_meshes"] = [mesh]
    out["initial_film_regions"] = [copy.deepcopy(dict(shared_film))]
    out["initial_junctions"] = []
    return out


def _phase(frame: Mapping[str, Any]) -> str:
    event = frame.get("event_runtime") or {}
    return str(event.get("phase") or "THINFILM")


def _merge_contact_context(
    frame: dict[str, Any],
    handoff: Mapping[str, Any],
    shared_mesh_id: str,
    shared_film_id: str,
) -> None:
    if _phase(frame) != "PRE_EVENT":
        return
    existing_meshes = {str(item["id"]) for item in frame["surface_meshes"]}
    for mesh in handoff["surface_meshes"]:
        if str(mesh["id"]) != shared_mesh_id and str(mesh["id"]) not in existing_meshes:
            frame["surface_meshes"].append(copy.deepcopy(mesh))
    existing_films = {str(item["id"]) for item in frame["film_regions"]}
    for film in handoff["film_regions"]:
        if str(film["id"]) != shared_film_id and str(film["id"]) not in existing_films:
            frame["film_regions"].append(copy.deepcopy(film))
    frame["junctions"] = copy.deepcopy(handoff["junctions"])
    adjacency = frame["topology"].setdefault("adjacency", [])
    seen = {str(item.get("film_id")) for item in adjacency}
    for item in handoff["topology"]["adjacency"]:
        if str(item.get("film_id")) not in seen:
            adjacency.append(copy.deepcopy(item))


def _normalize_frame(
    frame: dict[str, Any],
    *,
    index: int,
    phase: str,
    source_solver: str,
    source_contact_time_s: float,
    shared_film_id: str,
    shared_mesh_id: str,
    geometry_digest: str,
    source_junction_ids: Sequence[str],
) -> dict[str, Any]:
    out = copy.deepcopy(frame)
    out["frame_id"] = f"contact-thinfilm-event-{index:06d}-{phase.lower()}"
    solver = out["manifest"].get("solver") or {}
    out["manifest"]["solver"] = {
        "backend": BACKEND_IDENTITY,
        "version": VERSION,
        "adapter": "contact-created-shared-film-to-accepted-thinfilm-events",
    }
    provenance = out["manifest"].setdefault("provenance", {})
    provenance.update({
        "producer": "bubblelab.runtime.contact_thinfilm_event_runtime",
        "phase_solver": source_solver,
        "integration_time_origin": "accepted CONTACT_FORMATION event",
        "source_contact_event_time_s": source_contact_time_s,
        "shared_film_geometry_digest": geometry_digest,
        "shared_film_geometry_handoff": "exact contact-created vertices/faces; storage layout only may be flattened",
    })
    out.setdefault("diagnostics", {})["contact_thinfilm_event_runtime"] = {
        "phase": phase,
        "source_contact_event_time_s": source_contact_time_s,
        "shared_film_id": shared_film_id,
        "shared_mesh_id": shared_mesh_id,
        "shared_film_geometry_digest": geometry_digest,
        "source_contact_ring_junction_ids": list(source_junction_ids),
        "thinfilm_contact_ring_boundary_condition": "accepted SurfaceTransportState no-flux open-boundary edges",
        "fully_coupled_pre_contact_lubrication": "NOT_IMPLEMENTED",
        "singular_rupture_cfd": "NOT_IMPLEMENTED",
    }
    return out


def run_contact_thinfilm_event_frames(
    scenario: Mapping[str, Any],
    *,
    contact_frames: int = 12,
    thinfilm_frames: int = 8,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run accepted contact, then accepted thin-film/event physics from that exact film."""
    if contact_frames < 2 or thinfilm_frames < 1:
        raise ContactThinFilmEventConfigurationError("contact_frames >= 2 and thinfilm_frames >= 1 are required")
    film_config, _ = _explicit_physical_state(scenario)

    contact_input = _contact_scenario(scenario)
    contact_output, contact_meta = run_contact_transition(contact_input, contact_frames)
    handoff, contact_event = _find_handoff(contact_output)
    shared_mesh, shared_film = _shared_objects(handoff)
    source_digest = _geometry_digest(shared_mesh)
    source_contact_time = float(contact_event["time_s"])
    junction_ids = [str(item["id"]) for item in handoff["junctions"]]

    downstream_input = _event_scenario(scenario, handoff, shared_mesh, shared_film)
    downstream_mesh = downstream_input["initial_surface_meshes"][0]
    if _geometry_digest(downstream_mesh) != source_digest:
        raise RuntimeError("shared-film geometry changed during contact -> thin-film handoff")
    downstream, event_meta = run_event_frames(downstream_input, thinfilm_frames)

    # The integration clock starts at the accepted contact event.  Preserve the
    # original contact solver time as provenance instead of modifying accepted
    # event-runtime state references or event localization times.
    handoff["simulation_time_s"] = 0.0
    handoff_event = next(
        event for event in handoff["topology"]["events"]
        if event.get("transition_kind") == "CONTACT_FORMATION"
    )
    handoff_event.setdefault("provenance", {})["source_contact_simulation_time_s"] = source_contact_time
    handoff_event["time_s"] = 0.0
    contact_diag = handoff["diagnostics"]["contact_transition"]
    contact_diag["source_contact_event_time_s"] = source_contact_time
    contact_diag["event_time_s"] = 0.0

    normalized: list[dict[str, Any]] = []
    normalized.append(_normalize_frame(
        handoff,
        index=0,
        phase="CONTACT_HANDOFF",
        source_solver="bubblelab.runtime.contact_runtime",
        source_contact_time_s=source_contact_time,
        shared_film_id=str(shared_film["id"]),
        shared_mesh_id=str(shared_mesh["id"]),
        geometry_digest=source_digest,
        source_junction_ids=junction_ids,
    ))
    for raw in downstream:
        candidate = copy.deepcopy(raw)
        _merge_contact_context(
            candidate,
            handoff,
            str(shared_mesh["id"]),
            str(shared_film["id"]),
        )
        normalized.append(_normalize_frame(
            candidate,
            index=len(normalized),
            phase=_phase(candidate),
            source_solver="bubblelab.runtime.event_runtime",
            source_contact_time_s=source_contact_time,
            shared_film_id=str(shared_film["id"]),
            shared_mesh_id=str(shared_mesh["id"]),
            geometry_digest=source_digest,
            source_junction_ids=junction_ids,
        ))

    event_types: list[str] = []
    seen_events: set[str] = set()
    for frame in normalized:
        for event in frame["topology"]["events"]:
            event_id = str(event["id"])
            if event_id not in seen_events:
                seen_events.add(event_id)
                event_types.append(str(event["type"]))

    flags = feature_flags(film_config)
    return normalized, {
        "identity": BACKEND_IDENTITY,
        "version": VERSION,
        "mode": "accepted contact geometry -> accepted thin-film/gas transport -> accepted topology events",
        "contact_backend": contact_meta,
        "thinfilm_event_backend": event_meta,
        "source_contact_event_time_s": source_contact_time,
        "integration_time_origin": "CONTACT_FORMATION",
        "shared_film_id": str(shared_film["id"]),
        "shared_mesh_id": str(shared_mesh["id"]),
        "shared_film_geometry_digest": source_digest,
        "source_contact_ring_junction_ids": junction_ids,
        "drainage_enabled": flags["drainage"],
        "surfactant_diffusion_enabled": flags["surfactant_diffusion"],
        "gas_diffusion_enabled": flags["gas_diffusion"],
        "event_types": event_types,
    }


def run_contact_thinfilm_event_scenario(
    scenario: Mapping[str, Any],
    output_dir: str | Path,
    *,
    contact_frames: int = 12,
    thinfilm_frames: int = 8,
) -> dict[str, Any]:
    """Write a deterministic canonical replay bundle for the integrated runtime."""
    from bubblelab_contract import assert_valid

    scenario_copy = copy.deepcopy(dict(scenario))
    assert_valid(scenario_copy)
    raw_frames, backend_meta = run_contact_thinfilm_event_frames(
        scenario_copy,
        contact_frames=contact_frames,
        thinfilm_frames=thinfilm_frames,
    )
    physical_frames = [
        _decorate(frame, scenario_copy, "contact-thinfilm-event") for frame in raw_frames
    ]
    out = Path(output_dir)
    (out / "frames").mkdir(parents=True, exist_ok=True)
    refs: list[dict[str, Any]] = []
    for index, frame in enumerate(physical_frames):
        rel = f"frames/{index:06d}.json"
        (out / rel).write_bytes(_canonical_bytes(frame) + b"\n")
        refs.append({
            "frame_id": frame["frame_id"],
            "path": rel,
            "simulation_time_s": frame["simulation_time_s"],
        })

    replay = {
        "bundle_version": "1.0.0",
        "contract_version": "1.0.0",
        "scenario": {"id": scenario_copy["scenario_id"], "sha256": scenario_hash(scenario_copy)},
        "backend": backend_meta,
        "random_seed": scenario_copy["random_seed"],
        "run_settings": {
            "backend": "contact-thinfilm-event",
            "contact_frames": contact_frames,
            "thinfilm_frames": thinfilm_frames,
            "output_cadence_s": output_cadence_s(scenario_copy),
            "time_origin": "CONTACT_FORMATION",
        },
        "frames": refs,
        "checkpoints": [],
        "provenance": {
            "producer": "bubblelab.runtime.contact_thinfilm_event_runtime",
            "source_scenario": scenario_copy["scenario_id"],
        },
        "fidelity": {
            "requested": scenario_copy["requested_fidelity_tier"],
            "produced": physical_frames[-1]["manifest"]["fidelity_tier"],
            "feature_disclosures": physical_frames[-1]["manifest"]["feature_disclosures"],
            "checkpoint_continuation": "NOT_IMPLEMENTED",
        },
    }
    (out / "replay.json").write_bytes(_canonical_bytes(replay) + b"\n")
    return replay
