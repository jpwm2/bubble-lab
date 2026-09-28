"""Deterministic authoritative runtime session controls.

This module intentionally owns orchestration only.  It delegates all physical
updates to the accepted backend and never substitutes browser/replay motion for
solver time.
"""
from __future__ import annotations

import copy
import shutil
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from bubblelab.solvers.transient import GridConfig, TransientConfig, TransientSoapFilmSolver
from bubblelab.solvers.transient.geometry import icosphere as transient_icosphere
from bubblelab.solvers.transient import frame_dict as transient_frame

from .boundary_runtime import (
    BoundaryRuntimeConfigurationError,
    UnsupportedBoundaryFeature,
    solid_boundaries_from_scenario,
)
from .runner import (
    UnsupportedScenarioFeature,
    assert_valid,
    _canonical_bytes,
    _decorate,
    _feature_guard,
    _run_equilibrium,
    _single_bubble,
    _tension,
    scenario_hash,
)
from .thinfilm_runtime import (
    advance_transient_coupled,
    attach_transient_thinfilm,
    augment_transient_frame,
    thinfilm_config,
)


class SessionState(str, Enum):
    CREATED = "CREATED"
    PAUSED = "PAUSED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SessionControlError(ValueError):
    """Base class for deterministic session-control failures."""


class UnsupportedSessionCapability(SessionControlError):
    """Requested control is not honestly supported by the selected backend."""


class InvalidSessionCommand(SessionControlError):
    """Command is invalid for the current session state or payload."""


def _backend_from_scenario(scenario: Mapping[str, Any], backend: str | None) -> str:
    requested = scenario.get("requested_solver") or {}
    declared = requested.get("backend") if isinstance(requested, Mapping) else None
    selected = backend or declared
    if not selected:
        raise SessionControlError(
            "session backend must be supplied or declared by requested_solver.backend"
        )
    if declared not in (None, selected):
        raise SessionControlError(
            f"scenario requested backend {declared!r}, session selected {selected!r}"
        )
    return str(selected)


class RuntimeSession:
    """Backend-neutral control surface backed by authoritative solver state."""

    SESSION_VERSION = "1.0.0"

    def __init__(self, scenario: Mapping[str, Any], backend: str | None = None):
        self._source_scenario = copy.deepcopy(dict(scenario))
        assert_valid(self._source_scenario)
        self.backend = _backend_from_scenario(self._source_scenario, backend)
        _feature_guard(self._source_scenario, self.backend)

        self.source_scenario_id = str(self._source_scenario["scenario_id"])
        self.source_scenario_sha256 = scenario_hash(self._source_scenario)
        self.random_seed = int(self._source_scenario["random_seed"])
        self.command_history: list[dict[str, Any]] = []
        self.frames: list[dict[str, Any]] = []
        self.checkpoints: list[dict[str, Any]] = []
        self.sequence_number = 0
        self.frame_index = 0
        self.last_error: str | None = None

        self._solver: TransientSoapFilmSolver | None = None
        self._film_config = None
        self._film_attachment = None
        self._last_step = None
        self._last_transfer = None
        self._backend_meta: dict[str, Any] = {}
        self.state = SessionState.CREATED

        if self.backend == "transient":
            self._initialize_transient()
        elif self.backend == "equilibrium":
            physical_frames, meta = _run_equilibrium(self._source_scenario)
            self.frames = physical_frames
            self._backend_meta = meta
            self.state = SessionState.COMPLETED
        elif self.backend in {"thinfilm", "thinfilm-events"}:
            raise UnsupportedSessionCapability(
                f"{self.backend} does not expose a restartable live backend handle; "
                "batch replay remains available but authoritative STEP/RUN_TO_TIME is unsupported"
            )
        else:
            raise SessionControlError(
                "backend must be equilibrium, transient, thinfilm, or thinfilm-events"
            )

        self._initial_frame = copy.deepcopy(self.frames[0])
        self._initial_signature = self._authoritative_signature()

    @classmethod
    def from_checkpoint(
        cls, checkpoint: Mapping[str, Any] | str | Path
    ) -> "RuntimeSession":
        """Restore an authoritative same-build session through the accepted checkpoint core."""
        from .checkpoint_runtime import load_checkpoint, restore_session

        if isinstance(checkpoint, Mapping):
            document = copy.deepcopy(dict(checkpoint))
        else:
            document = load_checkpoint(checkpoint)
        restored = restore_session(document)
        if not isinstance(restored, cls):
            raise SessionControlError("checkpoint restore returned an unexpected session type")

        state = document.get("checkpoint_state")
        if not isinstance(state, Mapping):
            raise SessionControlError("restored checkpoint is missing checkpoint_state")
        source = state.get("source_scenario")
        integrity = state.get("integrity")
        requested = {
            "checkpoint_frame_id": str(document.get("frame_id", "")),
            "same_build_only": state.get("same_build_only") is True,
            "source_scenario_sha256": (
                str(source.get("sha256"))
                if isinstance(source, Mapping) and source.get("sha256") is not None
                else ""
            ),
            "continuation_sha256": (
                str(integrity.get("continuation_sha256"))
                if isinstance(integrity, Mapping)
                and integrity.get("continuation_sha256") is not None
                else ""
            ),
        }
        before_state = restored.state
        before_time = restored.physical_time_s
        restored._record(
            "RESTORE_CHECKPOINT",
            requested=requested,
            before_state=before_state,
            before_time=before_time,
            emitted_checkpoint_ids=(str(document["frame_id"]),),
        )
        return restored

    @property
    def physical_time_s(self) -> float:
        if self._solver is not None:
            return float(self._solver.time_s)
        return float(self.frames[-1]["simulation_time_s"]) if self.frames else 0.0

    @property
    def current_frame_index(self) -> int:
        return self.frame_index

    @property
    def backend_identity(self) -> str:
        return str(self._backend_meta["identity"])

    @property
    def capabilities(self) -> dict[str, bool]:
        live = self.backend == "transient" and self._solver is not None
        return {
            "pause": live,
            "resume": live,
            "step": live,
            "run_to_time": live,
            "reset": live,
            "persistent_checkpoint_restart": live,
            "paused_state_edit": False,
        }

    def _initialize_transient(self) -> None:
        bubble = _single_bubble(self._source_scenario)
        if any(abs(float(x)) > 0 for x in bubble["velocity_m_s"]):
            raise UnsupportedScenarioFeature(
                "transient foundation does not support independent initial bubble velocity; "
                "use environment.wind"
            )
        tension = _tension(bubble)
        env = self._source_scenario["environment"]
        wind = tuple(
            float(x)
            for x in ((env.get("wind") or {}).get("velocity_m_s") or (0, 0, 0))
        )
        try:
            boundaries = solid_boundaries_from_scenario(self._source_scenario)
        except UnsupportedBoundaryFeature as exc:
            raise UnsupportedScenarioFeature(str(exc)) from exc
        except BoundaryRuntimeConfigurationError:
            raise

        grid = GridConfig(
            density_kg_m3=float(env["ambient_density_kg_m3"]),
            dynamic_viscosity_pa_s=float(env["ambient_dynamic_viscosity_pa_s"]),
            background_velocity_m_s=wind,
        )
        config = TransientConfig(
            grid=grid,
            gravity_m_s2=tuple(float(x) for x in env["gravity_m_s2"]),
            deterministic_seed=self.random_seed,
            solid_boundaries=boundaries,
        )
        front = transient_icosphere(
            radius_m=float(bubble["equivalent_radius_m"]),
            center_m=tuple(float(x) for x in bubble["centroid_m"]),
            subdivisions=1,
            bubble_id=str(bubble["id"]),
            surface_tension_n_m=tension,
        )
        self._solver = TransientSoapFilmSolver([front], config)
        self._film_config = thinfilm_config(self._source_scenario)
        self._film_attachment = (
            attach_transient_thinfilm(
                self._solver, self._source_scenario, self._film_config
            )
            if self._film_config is not None
            else None
        )
        self._backend_meta = {
            "identity": "bubblelab-transient-reference",
            "version": self._solver.VERSION,
        }
        if self._film_config is not None:
            self._backend_meta.update(
                {
                    "thinfilm_extension": "bubblelab-reduced-thinfilm",
                    "operator_split": (
                        "transient bulk/front -> conservative areal transfer -> "
                        "thin-film/surfactant -> updated tension"
                    ),
                }
            )
        self.frames = [self._export_transient_frame(0)]
        self.frame_index = 0
        self.state = SessionState.CREATED

    def _export_transient_frame(self, index: int) -> dict[str, Any]:
        assert self._solver is not None
        frame_id = f"session-{index:06d}"
        if self._film_config is None:
            raw = transient_frame(self._solver, frame_id)
        else:
            raw = augment_transient_frame(
                transient_frame(self._solver, frame_id),
                self._film_attachment,
                self._film_config,
                step_diagnostics=self._last_step,
                transfer_diagnostics=self._last_transfer,
            )
        return _decorate(raw, self._source_scenario, "transient")

    def _authoritative_signature(self) -> Any:
        if self._solver is not None:
            return self._solver.replay_signature()
        return _canonical_bytes(self.frames)

    def _require_live(self, command: str) -> None:
        if self.backend != "transient" or self._solver is None:
            raise UnsupportedSessionCapability(
                f"{command} is unsupported for {self.backend}: "
                "the backend does not expose authoritative physical-time stepping"
            )

    def _record(
        self,
        command: str,
        *,
        requested: Mapping[str, Any] | None,
        before_state: SessionState,
        before_time: float,
        emitted_frame_ids: Sequence[str] = (),
        emitted_checkpoint_ids: Sequence[str] = (),
        result: str = "ACCEPTED",
        error: str | None = None,
        overshoot_s: float = 0.0,
    ) -> dict[str, Any]:
        self.sequence_number += 1
        entry: dict[str, Any] = {
            "sequence": self.sequence_number,
            "command": command,
            "requested": copy.deepcopy(dict(requested or {})),
            "result": result,
            "state_before": before_state.value,
            "state_after": self.state.value,
            "physical_time_before_s": before_time,
            "physical_time_after_s": self.physical_time_s,
            "overshoot_s": float(overshoot_s),
            "emitted_frame_ids": list(emitted_frame_ids),
            "emitted_checkpoint_ids": list(emitted_checkpoint_ids),
        }
        if error is not None:
            entry["error"] = error
        self.command_history.append(entry)
        return copy.deepcopy(entry)

    def _execute_recorded(self, name: str, requested: Mapping[str, Any], action):
        before_state = self.state
        before_time = self.physical_time_s
        try:
            emitted_frames, emitted_checkpoints, overshoot = action()
        except SessionControlError as exc:
            self._record(
                name,
                requested=requested,
                before_state=before_state,
                before_time=before_time,
                result="REJECTED",
                error=str(exc),
            )
            raise
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.state = SessionState.FAILED
            self._record(
                name,
                requested=requested,
                before_state=before_state,
                before_time=before_time,
                result="FAILED",
                error=self.last_error,
            )
            raise
        return self._record(
            name,
            requested=requested,
            before_state=before_state,
            before_time=before_time,
            emitted_frame_ids=emitted_frames,
            emitted_checkpoint_ids=emitted_checkpoints,
            overshoot_s=overshoot,
        )

    def pause(self) -> dict[str, Any]:
        def action():
            self._require_live("PAUSE")
            if self.state == SessionState.FAILED:
                raise InvalidSessionCommand("cannot pause a FAILED session")
            if self.state == SessionState.COMPLETED:
                raise InvalidSessionCommand("cannot pause a COMPLETED session")
            self.state = SessionState.PAUSED
            return (), (), 0.0

        return self._execute_recorded("PAUSE", {}, action)

    def resume(self) -> dict[str, Any]:
        def action():
            self._require_live("RESUME")
            if self.state == SessionState.FAILED:
                raise InvalidSessionCommand("cannot resume a FAILED session")
            if self.state == SessionState.COMPLETED:
                raise InvalidSessionCommand("cannot resume a COMPLETED session")
            self.state = SessionState.RUNNING
            return (), (), 0.0

        return self._execute_recorded("RESUME", {}, action)

    def _advance_one(self, remaining_s: float | None = None) -> str:
        assert self._solver is not None
        dt = self._solver.select_timestep(remaining_s)
        if self._film_config is None:
            self._last_step = self._solver.step(dt)
            self._last_transfer = None
        else:
            self._last_step, self._last_transfer = advance_transient_coupled(
                self._solver,
                self._film_attachment,
                self._film_config,
                dt,
            )
        self.frame_index += 1
        frame = self._export_transient_frame(self.frame_index)
        self.frames.append(frame)
        return str(frame["frame_id"])

    def step(self) -> dict[str, Any]:
        def action():
            self._require_live("STEP")
            if self.state != SessionState.PAUSED:
                raise InvalidSessionCommand("STEP requires the session to be PAUSED")
            frame_id = self._advance_one()
            self.state = SessionState.PAUSED
            return (frame_id,), (), 0.0

        return self._execute_recorded("STEP", {}, action)

    def run_to_time(self, target_time_s: float) -> dict[str, Any]:
        requested = {"target_time_s": float(target_time_s)}

        def action():
            self._require_live("RUN_TO_TIME")
            assert self._solver is not None
            target = float(target_time_s)
            if target < 0.0:
                raise InvalidSessionCommand("target_time_s must be non-negative")
            if self.state != SessionState.RUNNING:
                raise InvalidSessionCommand(
                    "RUN_TO_TIME requires the session to be RUNNING"
                )
            if target + 1.0e-15 < self._solver.time_s:
                raise InvalidSessionCommand(
                    "target time is before current physical time"
                )
            emitted: list[str] = []
            while self._solver.time_s + 1.0e-15 < target:
                emitted.append(self._advance_one(target - self._solver.time_s))
            overshoot = max(0.0, self._solver.time_s - target)
            self.state = SessionState.PAUSED
            return tuple(emitted), (), overshoot

        return self._execute_recorded("RUN_TO_TIME", requested, action)

    def reset(self) -> dict[str, Any]:
        def action():
            self._require_live("RESET")
            self._solver = None
            self._film_config = None
            self._film_attachment = None
            self._last_step = None
            self._last_transfer = None
            self.frames = []
            self.checkpoints = []
            self.frame_index = 0
            self.last_error = None
            self._initialize_transient()
            if self._authoritative_signature() != self._initial_signature:
                self.state = SessionState.FAILED
                raise SessionControlError(
                    "reset failed deterministic authoritative-state reproduction"
                )
            return (str(self.frames[0]["frame_id"]),), (), 0.0

        return self._execute_recorded("RESET", {}, action)

    def save_checkpoint(self, path: str | Path | None = None) -> dict[str, Any]:
        requested = {} if path is None else {"path": str(Path(path))}

        def action():
            self._require_live("SAVE_CHECKPOINT")
            if self.state == SessionState.FAILED:
                raise InvalidSessionCommand("cannot checkpoint a FAILED session")
            if self.state == SessionState.COMPLETED:
                raise InvalidSessionCommand("cannot checkpoint a COMPLETED session")

            # Local import avoids the intentional checkpoint_runtime -> session_control
            # dependency becoming a module-import cycle.
            from .checkpoint_runtime import checkpoint_document, write_checkpoint

            document = (
                checkpoint_document(self)
                if path is None
                else write_checkpoint(self, Path(path))
            )
            self.checkpoints.append(copy.deepcopy(document))
            return (), (str(document["frame_id"]),), 0.0

        return self._execute_recorded("SAVE_CHECKPOINT", requested, action)

    def execute(self, command: str | Mapping[str, Any]) -> dict[str, Any]:
        if isinstance(command, str):
            payload: dict[str, Any] = {"command": command}
        elif isinstance(command, Mapping):
            payload = copy.deepcopy(dict(command))
        else:
            raise InvalidSessionCommand("command must be a string or object")
        raw_name = payload.get("command", payload.get("type"))
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise InvalidSessionCommand("command object requires command/type")
        name = raw_name.strip().upper()
        if name == "PAUSE":
            return self.pause()
        if name == "RESUME":
            return self.resume()
        if name == "STEP":
            return self.step()
        if name == "RUN_TO_TIME":
            if "target_time_s" in payload:
                target = payload["target_time_s"]
            elif "time_s" in payload:
                target = payload["time_s"]
            elif "target" in payload:
                target = payload["target"]
            else:
                raise InvalidSessionCommand("RUN_TO_TIME requires target_time_s")
            return self.run_to_time(float(target))
        if name == "RESET":
            return self.reset()
        if name == "SAVE_CHECKPOINT":
            path = payload.get("path")
            if path is not None and not isinstance(path, str):
                raise InvalidSessionCommand("SAVE_CHECKPOINT path must be a string")
            return self.save_checkpoint(path)
        raise InvalidSessionCommand(f"unsupported session command: {name}")

    @staticmethod
    def _checkpoint_provenance(checkpoint: Mapping[str, Any]) -> dict[str, Any]:
        state = checkpoint.get("checkpoint_state")
        if not isinstance(state, Mapping):
            raise SessionControlError("stored checkpoint is missing checkpoint_state")
        source = state.get("source_scenario")
        backend = state.get("backend")
        integrity = state.get("integrity")
        if (
            not isinstance(source, Mapping)
            or not isinstance(backend, Mapping)
            or not isinstance(integrity, Mapping)
        ):
            raise SessionControlError("stored checkpoint provenance is incomplete")
        return {
            "frame_id": str(checkpoint["frame_id"]),
            "simulation_time_s": float(checkpoint["simulation_time_s"]),
            "same_build_only": state.get("same_build_only") is True,
            "runtime_checkpoint_version": str(
                state.get("runtime_checkpoint_version", "")
            ),
            "continuation_format_version": str(
                state.get("continuation_format_version", "")
            ),
            "source_scenario": copy.deepcopy(dict(source)),
            "backend": copy.deepcopy(dict(backend)),
            "integrity": copy.deepcopy(dict(integrity)),
        }

    def export_bundle(self, output_dir: str | Path) -> dict[str, Any]:
        if not self.frames:
            raise SessionControlError("cannot export a session with no canonical frames")
        out = Path(output_dir)
        frames_dir = out / "frames"
        checkpoints_dir = out / "checkpoints"
        if frames_dir.exists():
            shutil.rmtree(frames_dir)
        if checkpoints_dir.exists():
            shutil.rmtree(checkpoints_dir)
        frames_dir.mkdir(parents=True, exist_ok=True)

        refs = []
        for index, frame in enumerate(self.frames):
            rel = f"frames/{index:06d}.json"
            (out / rel).write_bytes(_canonical_bytes(frame) + b"\n")
            refs.append(
                {
                    "frame_id": frame["frame_id"],
                    "path": rel,
                    "simulation_time_s": frame["simulation_time_s"],
                }
            )

        checkpoint_refs = []
        checkpoint_provenance = []
        if self.checkpoints:
            checkpoints_dir.mkdir(parents=True, exist_ok=True)
        for index, checkpoint in enumerate(self.checkpoints):
            rel = f"checkpoints/{index:06d}.json"
            (out / rel).write_bytes(_canonical_bytes(checkpoint) + b"\n")
            provenance = self._checkpoint_provenance(checkpoint)
            checkpoint_refs.append(
                {
                    "frame_id": provenance["frame_id"],
                    "path": rel,
                    "simulation_time_s": provenance["simulation_time_s"],
                    "same_build_only": provenance["same_build_only"],
                }
            )
            checkpoint_provenance.append(provenance)

        replay = {
            "bundle_version": "1.0.0",
            "contract_version": "1.0.0",
            "scenario": {
                "id": self.source_scenario_id,
                "sha256": self.source_scenario_sha256,
            },
            "backend": copy.deepcopy(self._backend_meta),
            "random_seed": self.random_seed,
            "run_settings": {
                "backend": self.backend,
                "requested_frames": None,
                "output_cadence_s": None,
                "session_control": True,
            },
            "frames": refs,
            "checkpoints": checkpoint_refs,
            "provenance": {
                "producer": "bubblelab.runtime.session_control",
                "source_scenario": self.source_scenario_id,
            },
            "fidelity": {
                "requested": self._source_scenario["requested_fidelity_tier"],
                "produced": self.frames[-1]["manifest"]["fidelity_tier"],
                "feature_disclosures": self.frames[-1]["manifest"][
                    "feature_disclosures"
                ],
                "checkpoint_continuation": (
                    "SAME_BUILD_EXACT"
                    if self.capabilities["persistent_checkpoint_restart"]
                    else "UNAVAILABLE"
                ),
            },
            "session_control": {
                "version": self.SESSION_VERSION,
                "state": self.state.value,
                "physical_time_s": self.physical_time_s,
                "frame_index": self.frame_index,
                "checkpoint_count": len(checkpoint_refs),
                "command_log": "commands.json",
                "metadata": "session.json",
            },
        }
        boundary_refs = (self._source_scenario.get("environment") or {}).get(
            "boundary_refs"
        )
        if boundary_refs:
            replay["run_settings"]["boundary_refs"] = list(boundary_refs)

        session_meta = {
            "session_version": self.SESSION_VERSION,
            "scenario": replay["scenario"],
            "backend": copy.deepcopy(self._backend_meta),
            "random_seed": self.random_seed,
            "state": self.state.value,
            "physical_time_s": self.physical_time_s,
            "frame_index": self.frame_index,
            "capabilities": self.capabilities,
            "command_count": len(self.command_history),
            "checkpoint_count": len(checkpoint_provenance),
            "checkpoints": checkpoint_provenance,
        }
        (out / "commands.json").write_bytes(
            _canonical_bytes(self.command_history) + b"\n"
        )
        (out / "session.json").write_bytes(_canonical_bytes(session_meta) + b"\n")
        (out / "replay.json").write_bytes(_canonical_bytes(replay) + b"\n")
        return replay


def create_session(
    scenario: Mapping[str, Any], backend: str | None = None
) -> RuntimeSession:
    return RuntimeSession(scenario, backend)


def restore_session_checkpoint(
    checkpoint: Mapping[str, Any] | str | Path,
) -> RuntimeSession:
    """Session-control convenience API for same-build persistent restart."""
    return RuntimeSession.from_checkpoint(checkpoint)


# Install the scoped live-edit transaction surface after RuntimeSession is fully
# defined. The implementation lives under runtime/server/** because that path is
# explicitly assigned to this worker and is also the loopback transport boundary.
from .server.live_editing import install_runtime_session_editing

install_runtime_session_editing(
    RuntimeSession,
    SessionState,
    InvalidSessionCommand,
    UnsupportedSessionCapability,
)
