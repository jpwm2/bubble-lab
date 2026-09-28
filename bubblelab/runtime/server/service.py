"""Deterministic in-process service owning authoritative RuntimeSession objects."""
from __future__ import annotations

import copy
import secrets
from threading import RLock
from typing import Any, Mapping

from bubblelab.runtime.session_control import (
    InvalidSessionCommand,
    RuntimeSession,
    SessionControlError,
    UnsupportedSessionCapability,
)

TRANSPORT_VERSION = "1.0.0"
ALLOWED_BACKENDS = frozenset({"equilibrium", "transient", "thinfilm", "thinfilm-events"})


class LiveSessionTransportError(RuntimeError):
    """Structured transport failure suitable for an HTTP/JSON response."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int = 400,
        session_payload: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = int(status)
        self.session_payload = (
            copy.deepcopy(dict(session_payload)) if session_payload is not None else None
        )


class LiveSessionService:
    """Own RuntimeSession instances and expose only accepted session operations."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._sessions: dict[str, RuntimeSession] = {}

    @staticmethod
    def _selected_backend(scenario: Mapping[str, Any], backend: str | None) -> str | None:
        requested = scenario.get("requested_solver")
        declared = requested.get("backend") if isinstance(requested, Mapping) else None
        selected = backend if backend is not None else declared
        if selected is None:
            return None
        if not isinstance(selected, str) or selected not in ALLOWED_BACKENDS:
            raise LiveSessionTransportError(
                "unsupported_backend",
                f"backend must be one of: {', '.join(sorted(ALLOWED_BACKENDS))}",
            )
        return selected

    @staticmethod
    def _checkpoint_provenance(session: RuntimeSession) -> list[dict[str, Any]]:
        return [
            RuntimeSession._checkpoint_provenance(checkpoint)
            for checkpoint in session.checkpoints
        ]

    @classmethod
    def snapshot(cls, session: RuntimeSession) -> dict[str, Any]:
        backend = copy.deepcopy(getattr(session, "_backend_meta", {}))
        if not isinstance(backend, dict):
            backend = {}
        backend.setdefault("identity", session.backend_identity)
        backend.setdefault("version", "unknown")
        checkpoints = cls._checkpoint_provenance(session)
        return {
            "session_version": session.SESSION_VERSION,
            "scenario": {
                "id": session.source_scenario_id,
                "sha256": session.source_scenario_sha256,
            },
            "backend": backend,
            "random_seed": session.random_seed,
            "state": session.state.value,
            "physical_time_s": session.physical_time_s,
            "frame_index": session.current_frame_index,
            "capabilities": copy.deepcopy(session.capabilities),
            "command_count": len(session.command_history),
            "checkpoint_count": len(checkpoints),
            "checkpoints": checkpoints,
        }

    @classmethod
    def envelope(
        cls,
        session_id: str,
        session: RuntimeSession,
        *,
        command_result: Mapping[str, Any] | None = None,
        checkpoint: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "transport_version": TRANSPORT_VERSION,
            "session_id": session_id,
            "snapshot": cls.snapshot(session),
            "latest_frame": copy.deepcopy(session.frames[-1]) if session.frames else None,
            "command_history": copy.deepcopy(session.command_history),
        }
        if command_result is not None:
            payload["command_result"] = copy.deepcopy(dict(command_result))
        if checkpoint is not None:
            canonical = copy.deepcopy(dict(checkpoint))
            payload["checkpoint"] = canonical
            payload["checkpoint_provenance"] = RuntimeSession._checkpoint_provenance(
                canonical
            )
        return payload

    def _require_session(self, session_id: str) -> RuntimeSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise LiveSessionTransportError(
                "session_not_found",
                f"unknown live session: {session_id}",
                status=404,
            )
        return session

    def _new_session_capability(self) -> str:
        while True:
            session_id = f"live-{secrets.token_urlsafe(24)}"
            if session_id not in self._sessions:
                return session_id

    def create_session(
        self, scenario: Mapping[str, Any], backend: str | None = None
    ) -> dict[str, Any]:
        if not isinstance(scenario, Mapping):
            raise LiveSessionTransportError("invalid_scenario", "scenario must be an object")
        selected = self._selected_backend(scenario, backend)
        try:
            session = RuntimeSession(copy.deepcopy(dict(scenario)), selected)
        except (SessionControlError, ValueError, KeyError, TypeError) as exc:
            raise LiveSessionTransportError(
                "session_create_failed", str(exc), status=422
            ) from exc
        with self._lock:
            session_id = self._new_session_capability()
            self._sessions[session_id] = session
            return self.envelope(session_id, session)

    def get_session(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._require_session(session_id)
            return self.envelope(session_id, session)

    def execute_command(
        self, session_id: str, command: Mapping[str, Any] | str
    ) -> dict[str, Any]:
        with self._lock:
            session = self._require_session(session_id)
            payload = {"command": command} if isinstance(command, str) else copy.deepcopy(dict(command)) if isinstance(command, Mapping) else None
            if payload is None:
                raise LiveSessionTransportError(
                    "invalid_command", "command must be a string or object"
                )
            raw_name = payload.get("command", payload.get("type"))
            name = raw_name.strip().upper() if isinstance(raw_name, str) else ""
            if name == "SAVE_CHECKPOINT" and "path" in payload:
                raise LiveSessionTransportError(
                    "filesystem_path_forbidden",
                    "checkpoint paths are server-owned and cannot be supplied by the browser",
                )
            before_sequence = session.sequence_number
            try:
                result = session.save_checkpoint() if name == "SAVE_CHECKPOINT" else session.execute(payload)
            except SessionControlError as exc:
                last = (
                    session.command_history[-1]
                    if session.sequence_number > before_sequence and session.command_history
                    else None
                )
                status = 409
                if isinstance(exc, UnsupportedSessionCapability):
                    code = "unsupported_capability"
                elif isinstance(exc, InvalidSessionCommand):
                    code = "invalid_command"
                else:
                    code = "session_control_error"
                raise LiveSessionTransportError(
                    code,
                    str(exc),
                    status=status,
                    session_payload=self.envelope(
                        session_id, session, command_result=last
                    ),
                ) from exc
            except Exception as exc:
                last = session.command_history[-1] if session.command_history else None
                raise LiveSessionTransportError(
                    "session_execution_failed",
                    f"{type(exc).__name__}: {exc}",
                    status=500,
                    session_payload=self.envelope(
                        session_id, session, command_result=last
                    ),
                ) from exc

            checkpoint = None
            if name == "SAVE_CHECKPOINT" and session.checkpoints:
                checkpoint = session.checkpoints[-1]
            return self.envelope(
                session_id,
                session,
                command_result=result,
                checkpoint=checkpoint,
            )

    def save_checkpoint(self, session_id: str) -> dict[str, Any]:
        return self.execute_command(session_id, {"command": "SAVE_CHECKPOINT"})

    def get_checkpoint(self, session_id: str, frame_id: str = "latest") -> dict[str, Any]:
        with self._lock:
            session = self._require_session(session_id)
            if not session.checkpoints:
                raise LiveSessionTransportError(
                    "checkpoint_not_found",
                    "the session has no saved checkpoint",
                    status=404,
                )
            if frame_id == "latest":
                checkpoint = session.checkpoints[-1]
            else:
                checkpoint = next(
                    (
                        item
                        for item in session.checkpoints
                        if str(item.get("frame_id", "")) == frame_id
                    ),
                    None,
                )
                if checkpoint is None:
                    raise LiveSessionTransportError(
                        "checkpoint_not_found",
                        f"unknown checkpoint: {frame_id}",
                        status=404,
                    )
            return self.envelope(session_id, session, checkpoint=checkpoint)

    def close_session(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._require_session(session_id)
            snapshot = self.snapshot(session)
            del self._sessions[session_id]
            return {
                "transport_version": TRANSPORT_VERSION,
                "session_id": session_id,
                "closed": True,
                "snapshot": snapshot,
            }
