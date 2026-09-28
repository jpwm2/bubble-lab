"""Persistent same-build checkpoint/restart for authoritative transient runtime sessions."""
from __future__ import annotations

import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from bubblelab.solvers.transient.checkpoint import (
    CONTINUATION_FORMAT_VERSION,
    CheckpointError,
    IncompatibleCheckpointError,
    authoritative_state as authoritative_solver_state,
    canonical_bytes,
    restore_solver,
    snapshot_solver,
)
from bubblelab.solvers.transient.thinfilm_adapter import ThinFilmAttachment

from .runner import assert_valid, scenario_hash
from .session_control import RuntimeSession, SessionState


RUNTIME_CHECKPOINT_VERSION = "1.0.0"


class CheckpointRuntimeError(CheckpointError):
    """Invalid, corrupt, or unsupported runtime checkpoint."""


def _thinfilm_state(session: RuntimeSession) -> dict[str, Any] | None:
    attachment = session._film_attachment
    if attachment is None:
        return None
    state = attachment.state
    return {
        "bubble_id": attachment.front.bubble_id,
        "parameters": asdict(attachment.parameters),
        "thickness_m": list(state.thickness_m),
        "surfactant_mol_m2": list(state.surfactant_mol_m2),
        "capillary_pressure_pa": list(state.capillary_pressure_pa),
        "liquid_amount_m3": state.liquid_amount_m3(),
        "surfactant_amount_mol": state.surfactant_amount_mol(),
    }


def _continuation_payload(session: RuntimeSession) -> dict[str, Any]:
    if session.backend != "transient" or session._solver is None:
        raise CheckpointRuntimeError(
            "persistent checkpoint/restart is supported only for a live transient session"
        )
    if session.state in {SessionState.FAILED, SessionState.COMPLETED}:
        raise CheckpointRuntimeError(
            f"cannot checkpoint transient session in state {session.state.value}"
        )
    return {
        "source_scenario": copy.deepcopy(session._source_scenario),
        "solver": snapshot_solver(session._solver),
        "thinfilm": _thinfilm_state(session),
        "runtime": {
            "state": session.state.value,
            "frame_index": session.frame_index,
            "sequence_number": session.sequence_number,
            "command_history": copy.deepcopy(session.command_history),
            "last_error": session.last_error,
            "random_seed": session.random_seed,
        },
    }


def checkpoint_document(session: RuntimeSession) -> dict[str, Any]:
    """Create a schema-v1 CHECKPOINT carrying opaque authoritative continuation state."""
    if not session.frames:
        raise CheckpointRuntimeError("session has no canonical frame to anchor checkpoint")
    continuation = _continuation_payload(session)
    digest = hashlib.sha256(canonical_bytes(continuation)).hexdigest()
    frame = copy.deepcopy(session.frames[-1])
    frame["kind"] = "CHECKPOINT"
    frame["frame_id"] = f"checkpoint-{session.frame_index:06d}"
    frame["simulation_time_s"] = session.physical_time_s
    frame["checkpoint_state"] = {
        "runtime_checkpoint_version": RUNTIME_CHECKPOINT_VERSION,
        "continuation_format_version": CONTINUATION_FORMAT_VERSION,
        "same_build_only": True,
        "backend": {
            "identity": session.backend_identity,
            "version": session._solver.VERSION,
        },
        "source_scenario": {
            "id": session.source_scenario_id,
            "sha256": session.source_scenario_sha256,
        },
        "simulation_time_s": session.physical_time_s,
        "frame_index": session.frame_index,
        "integrity": {
            "algorithm": "sha256",
            "canonicalization": "json-sort-keys-compact-utf8",
            "continuation_sha256": digest,
        },
        "continuation": continuation,
    }
    assert_valid(frame)
    return frame


def write_checkpoint(session: RuntimeSession, path: str | Path) -> dict[str, Any]:
    document = checkpoint_document(session)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(canonical_bytes(document) + b"\n")
    return document


def load_checkpoint(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CheckpointRuntimeError(f"checkpoint file does not exist: {target}") from exc
    except json.JSONDecodeError as exc:
        raise CheckpointRuntimeError(f"checkpoint JSON is corrupt: {target}") from exc
    if not isinstance(value, dict):
        raise CheckpointRuntimeError("checkpoint root must be an object")
    return value


def _verify_checkpoint(document: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    try:
        assert_valid(dict(document))
    except Exception as exc:
        raise CheckpointRuntimeError(f"checkpoint contract validation failed: {exc}") from exc
    if document.get("kind") != "CHECKPOINT":
        raise CheckpointRuntimeError("restart input is not a CHECKPOINT")
    state = document.get("checkpoint_state")
    if not isinstance(state, Mapping):
        raise CheckpointRuntimeError("checkpoint_state must be an object")
    if state.get("runtime_checkpoint_version") != RUNTIME_CHECKPOINT_VERSION:
        raise IncompatibleCheckpointError(
            "unsupported runtime checkpoint version "
            f"{state.get('runtime_checkpoint_version')!r}"
        )
    if state.get("continuation_format_version") != CONTINUATION_FORMAT_VERSION:
        raise IncompatibleCheckpointError(
            "unsupported solver continuation format "
            f"{state.get('continuation_format_version')!r}"
        )
    if state.get("same_build_only") is not True:
        raise IncompatibleCheckpointError("checkpoint does not declare same-build restart semantics")
    continuation = state.get("continuation")
    if not isinstance(continuation, Mapping):
        raise CheckpointRuntimeError("checkpoint continuation payload is missing")
    integrity = state.get("integrity")
    if not isinstance(integrity, Mapping) or integrity.get("algorithm") != "sha256":
        raise CheckpointRuntimeError("checkpoint integrity metadata is missing or unsupported")
    expected = integrity.get("continuation_sha256")
    actual = hashlib.sha256(canonical_bytes(continuation)).hexdigest()
    if not isinstance(expected, str) or expected != actual:
        raise CheckpointRuntimeError("checkpoint continuation integrity digest mismatch")
    return state, continuation


def _restore_thinfilm(
    session: RuntimeSession,
    payload: Mapping[str, Any] | None,
) -> None:
    if payload is None:
        if session._film_config is not None:
            raise CheckpointRuntimeError(
                "checkpoint omitted thin-film continuation for a thin-film scenario"
            )
        session._film_attachment = None
        return

    if session._film_config is None or session._film_attachment is None:
        raise CheckpointRuntimeError(
            "checkpoint contains thin-film continuation for a scenario without thin-film mode"
        )
    if session._solver is None or len(session._solver.fronts) != 1:
        raise CheckpointRuntimeError("thin-film restart requires exactly one restored FilmFront")

    front = session._solver.fronts[0]
    if str(payload.get("bubble_id")) != front.bubble_id:
        raise CheckpointRuntimeError("thin-film checkpoint bubble identity mismatch")

    template = session._film_attachment
    saved_parameters = payload.get("parameters")
    if not isinstance(saved_parameters, Mapping):
        raise CheckpointRuntimeError("thin-film parameter state is missing")
    if canonical_bytes(asdict(template.parameters)) != canonical_bytes(saved_parameters):
        raise IncompatibleCheckpointError(
            "thin-film parameter state differs from the source scenario/current build"
        )

    attachment = ThinFilmAttachment(
        front,
        thickness_m=[float(value) for value in payload["thickness_m"]],
        surfactant_mol_m2=[
            float(value) for value in payload["surfactant_mol_m2"]
        ],
        parameters=template.parameters,
    )
    capillary = [float(value) for value in payload["capillary_pressure_pa"]]
    if len(capillary) != len(attachment.state.mesh.faces):
        raise CheckpointRuntimeError("thin-film capillary-pressure face count mismatch")
    attachment.state.capillary_pressure_pa = capillary

    fields = session._solver.surface_fields.get(front.bubble_id, {})
    required = {attachment.LIQUID_FIELD, attachment.SURFACTANT_FIELD}
    if not required.issubset(fields):
        raise CheckpointRuntimeError(
            "solver checkpoint is missing conservative thin-film continuation fields"
        )
    attachment._fields = {
        attachment.LIQUID_FIELD: fields[attachment.LIQUID_FIELD],
        attachment.SURFACTANT_FIELD: fields[attachment.SURFACTANT_FIELD],
    }

    if attachment.state.liquid_amount_m3() != float(payload["liquid_amount_m3"]):
        raise CheckpointRuntimeError("thin-film liquid amount failed exact restart verification")
    if attachment.state.surfactant_amount_mol() != float(
        payload["surfactant_amount_mol"]
    ):
        raise CheckpointRuntimeError(
            "thin-film surfactant amount failed exact restart verification"
        )
    session._film_attachment = attachment


def restore_session(document: Mapping[str, Any]) -> RuntimeSession:
    """Reconstruct a fresh RuntimeSession from an authoritative CHECKPOINT."""
    state, continuation = _verify_checkpoint(document)
    scenario = continuation.get("source_scenario")
    if not isinstance(scenario, Mapping):
        raise CheckpointRuntimeError("checkpoint source scenario is missing")
    source_meta = state.get("source_scenario")
    if not isinstance(source_meta, Mapping):
        raise CheckpointRuntimeError("checkpoint source-scenario metadata is missing")
    calculated_hash = scenario_hash(scenario)
    if str(source_meta.get("id")) != str(scenario.get("scenario_id")):
        raise CheckpointRuntimeError("checkpoint source scenario ID mismatch")
    if str(source_meta.get("sha256")) != calculated_hash:
        raise CheckpointRuntimeError("checkpoint source scenario hash mismatch")

    backend_meta = state.get("backend")
    if not isinstance(backend_meta, Mapping):
        raise CheckpointRuntimeError("checkpoint backend metadata is missing")

    fresh = RuntimeSession(scenario, backend="transient")
    if fresh.backend_identity != str(backend_meta.get("identity")):
        raise IncompatibleCheckpointError("checkpoint backend identity does not match current build")
    if fresh._solver is None:
        raise CheckpointRuntimeError("fresh transient runtime did not create a solver")
    if fresh._solver.VERSION != str(backend_meta.get("version")):
        raise IncompatibleCheckpointError(
            "checkpoint backend version does not match current build; "
            "cross-version restart is not claimed"
        )

    fresh._solver = restore_solver(continuation["solver"])
    runtime = continuation.get("runtime")
    if not isinstance(runtime, Mapping):
        raise CheckpointRuntimeError("runtime continuation metadata is missing")
    if int(runtime.get("random_seed")) != fresh.random_seed:
        raise CheckpointRuntimeError("checkpoint runtime seed differs from source scenario")
    if fresh._solver.config.deterministic_seed != fresh.random_seed:
        raise CheckpointRuntimeError("restored solver seed differs from source scenario")

    thinfilm = continuation.get("thinfilm")
    if thinfilm is not None and not isinstance(thinfilm, Mapping):
        raise CheckpointRuntimeError("thinfilm continuation must be an object or null")
    _restore_thinfilm(fresh, thinfilm)

    try:
        fresh.state = SessionState(str(runtime["state"]))
    except ValueError as exc:
        raise CheckpointRuntimeError(
            f"unsupported saved runtime state {runtime.get('state')!r}"
        ) from exc
    if fresh.state in {SessionState.FAILED, SessionState.COMPLETED}:
        raise CheckpointRuntimeError(
            f"checkpoint cannot restart saved state {fresh.state.value}"
        )
    fresh.frame_index = int(runtime["frame_index"])
    fresh.sequence_number = int(runtime["sequence_number"])
    history = runtime.get("command_history")
    if not isinstance(history, list):
        raise CheckpointRuntimeError("runtime command history must be an array")
    fresh.command_history = copy.deepcopy(history)
    last_error = runtime.get("last_error")
    fresh.last_error = None if last_error is None else str(last_error)

    if fresh.frame_index != int(state["frame_index"]):
        raise CheckpointRuntimeError("checkpoint frame index metadata mismatch")
    if fresh._solver.time_s != float(state["simulation_time_s"]):
        raise CheckpointRuntimeError("checkpoint simulation time does not match restored solver")
    if fresh._solver.time_s != float(document["simulation_time_s"]):
        raise CheckpointRuntimeError("checkpoint frame time does not match restored solver")

    current = copy.deepcopy(dict(document))
    current.pop("checkpoint_state", None)
    current["kind"] = "FRAME"
    fresh.frames = [current]
    fresh.checkpoints = [copy.deepcopy(dict(document))]
    fresh._last_step = None
    fresh._last_transfer = None
    return fresh


def restore_session_from_file(path: str | Path) -> RuntimeSession:
    return restore_session(load_checkpoint(path))


def authoritative_runtime_state(session: RuntimeSession) -> dict[str, Any]:
    if session._solver is None or session.backend != "transient":
        raise CheckpointRuntimeError("authoritative runtime state requires a live transient session")
    return {
        "source_scenario": {
            "id": session.source_scenario_id,
            "sha256": session.source_scenario_sha256,
        },
        "backend": {
            "identity": session.backend_identity,
            "version": session._solver.VERSION,
        },
        "physical_time_s": session.physical_time_s,
        "frame_index": session.frame_index,
        "solver": authoritative_solver_state(session._solver),
        "thinfilm": _thinfilm_state(session),
    }


def authoritative_runtime_digest(session: RuntimeSession) -> str:
    return hashlib.sha256(canonical_bytes(authoritative_runtime_state(session))).hexdigest()
