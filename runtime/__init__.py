"""Solver-neutral runtime orchestration for Bubble Lab."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .bundle import validate_replay_bundle
from .runner import UnsupportedScenarioFeature, run_scenario as _run_base_scenario


def _post_event_relaxation_requested(scenario: Mapping[str, Any]) -> bool:
    for source in (scenario.get("requested_solver") or {}, scenario.get("user_editable") or {}):
        if not isinstance(source, Mapping):
            continue
        features = source.get("features")
        if isinstance(features, Mapping) and bool(features.get("post_event_relaxation")):
            return True
    return False


def run_scenario(
    scenario: Mapping[str, Any],
    backend: str,
    output_dir: str | Path,
    frames: int = 4,
) -> dict[str, Any]:
    """Dispatch canonical runtime backends, including topology-event integration."""
    if backend == "thinfilm-events":
        if _post_event_relaxation_requested(scenario):
            from .postcoalescence_runtime import run_postcoalescence_scenario

            return run_postcoalescence_scenario(scenario, output_dir, frames)
        from .event_runtime import run_event_scenario

        return run_event_scenario(scenario, output_dir, frames)
    return _run_base_scenario(scenario, backend, output_dir, frames)


from .session_control import (
    InvalidSessionCommand,
    RuntimeSession,
    SessionControlError,
    SessionState,
    UnsupportedSessionCapability,
    create_session,
)


__all__ = [
    "UnsupportedScenarioFeature",
    "run_scenario",
    "validate_replay_bundle",
    "SessionState",
    "SessionControlError",
    "UnsupportedSessionCapability",
    "InvalidSessionCommand",
    "RuntimeSession",
    "create_session",
]
