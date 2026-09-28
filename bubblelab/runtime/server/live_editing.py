"""Authoritative paused-state bubble edits for RuntimeSession.

The runtime keeps edit authority in Python/solver state. Geometry edits mutate the
tracked FilmFronts in place, while velocity edits seed the Eulerian velocity field
used by the next physical solver step.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

from bubblelab.solvers.transient.checkpoint import restore_solver, snapshot_solver
from bubblelab.solvers.transient.geometry import icosphere as transient_icosphere


_EDIT_COMMANDS = frozenset(
    {
        "ADD_BUBBLE",
        "DELETE_BUBBLE",
        "MOVE_BUBBLE",
        "RESIZE_BUBBLE",
        "SET_BUBBLE_VELOCITY",
    }
)


def _finite_scalar(value: Any, label: str, invalid_command):
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise invalid_command(f"{label} must be a finite number") from exc
    if not math.isfinite(parsed):
        raise invalid_command(f"{label} must be a finite number")
    return parsed


def _vector3(value: Any, label: str, invalid_command) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise invalid_command(f"{label} must contain exactly three finite numbers")
    return tuple(
        _finite_scalar(item, f"{label}[{index}]", invalid_command)
        for index, item in enumerate(value)
    )  # type: ignore[return-value]


def _bubble_id(value: Any, invalid_command) -> str:
    if not isinstance(value, str) or not value.strip():
        raise invalid_command("bubble_id must be a non-empty string")
    bubble_id = value.strip()
    if bubble_id == "EXTERIOR":
        raise invalid_command("bubble_id EXTERIOR is reserved by the transient solver")
    return bubble_id


def _front(session, bubble_id: str, invalid_command):
    assert session._solver is not None
    for front in session._solver.fronts:
        if front.bubble_id == bubble_id:
            return front
    raise invalid_command(f"unknown bubble id {bubble_id!r}")


def _distance(a, b) -> float:
    return math.sqrt(sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)))


def _bound_radius(front) -> float:
    center = front.centroid()
    return max((_distance(vertex, center) for vertex in front.vertices), default=0.0)


def _validate_nonoverlap(
    session, candidate, invalid_command, replacing_id: str | None = None
) -> None:
    assert session._solver is not None
    center = candidate.centroid()
    radius = _bound_radius(candidate)
    if radius <= 0.0 or not math.isfinite(radius) or candidate.volume() <= 0.0:
        raise invalid_command(
            "edited bubble geometry must remain a finite closed positive-volume front"
        )
    for vertex in candidate.vertices:
        if any(not math.isfinite(float(component)) for component in vertex):
            raise invalid_command("edited bubble geometry contains a non-finite vertex")
    tolerance = max(1.0e-12, session._solver.config.boundary_tolerance_m)
    for other in session._solver.fronts:
        if other.bubble_id == replacing_id:
            continue
        if _distance(center, other.centroid()) <= radius + _bound_radius(other) + tolerance:
            raise invalid_command(
                f"edited bubble {candidate.bubble_id!r} overlaps or touches "
                f"bubble {other.bubble_id!r}"
            )


def _gas_grids(solver):
    level_grids = getattr(solver.grid, "level_grids", None)
    if callable(level_grids):
        return list(level_grids())
    return [solver.grid]


def _validate_region_coverage(session, invalid_command) -> None:
    assert session._solver is not None
    grids = _gas_grids(session._solver)
    for front in session._solver.fronts:
        if not any(front.bubble_id in grid.region_labels for grid in grids):
            raise invalid_command(
                f"edited bubble {front.bubble_id!r} has no authoritative Eulerian region cells; "
                "the requested geometry is outside the resolvable continuation state"
            )


def _seed_bubble_velocity(
    solver, bubble_id: str, velocity: tuple[float, float, float]
) -> None:
    front = next(front for front in solver.fronts if front.bubble_id == bubble_id)
    background = tuple(float(value) for value in solver.config.grid.background_velocity_m_s)
    dynamic = tuple(velocity[index] - background[index] for index in range(3))
    solver._bubble_velocities[bubble_id] = velocity

    for grid in _gas_grids(solver):
        touched = {
            index for index, label in enumerate(grid.region_labels) if label == bubble_id
        }
        weights = getattr(grid, "_weights", None)
        if callable(weights):
            for vertex in front.vertices:
                touched.update(index for index, weight in weights(vertex) if weight > 0.0)
            touched.update(
                index for index, weight in weights(front.centroid()) if weight > 0.0
            )
        for index in touched:
            grid.u[index] = dynamic[0]
            grid.v[index] = dynamic[1]
            grid.w[index] = dynamic[2]
        grid.apply_solid_wall_constraints()


def _refresh_after_geometry_edit(
    session, preserved_velocity: Mapping[str, tuple[float, float, float]]
) -> None:
    assert session._solver is not None
    session._solver._refresh_regions()
    for bubble_id, velocity in preserved_velocity.items():
        if any(front.bubble_id == bubble_id for front in session._solver.fronts):
            _seed_bubble_velocity(session._solver, bubble_id, velocity)


def _emit_edit_frame(session) -> str:
    session.frame_index += 1
    frame = session._export_transient_frame(session.frame_index)
    session.frames.append(frame)
    return str(frame["frame_id"])


def install_runtime_session_editing(
    runtime_session_class,
    session_state,
    invalid_command,
    unsupported_capability,
) -> None:
    """Install the Wave-15 edit surface without changing solver ownership."""

    if getattr(runtime_session_class, "_live_runtime_editing_installed", False):
        return

    original_capabilities_getter = runtime_session_class.capabilities.fget
    original_execute = runtime_session_class.execute

    def _require_editable(self, command: str) -> None:
        self._require_live(command)
        if self._film_config is not None:
            raise unsupported_capability(
                "paused live editing is currently supported only for the base transient "
                "front/grid continuation; coupled thin-film attachment editing is not claimed"
            )
        if self.state != session_state.PAUSED:
            raise invalid_command(f"{command} requires the session to be PAUSED")

    def capabilities(self) -> dict[str, bool]:
        values = dict(original_capabilities_getter(self))
        values["paused_state_edit"] = (
            self.backend == "transient"
            and self._solver is not None
            and self._film_config is None
        )
        return values

    def _run_edit(self, command_name: str, requested: Mapping[str, Any], mutator):
        canonical = dict(requested)
        canonical["authoritative_rebuild"] = "REGION_CLASSIFICATION_ONLY"

        def action():
            _require_editable(self, command_name)
            assert self._solver is not None
            before = snapshot_solver(self._solver)
            try:
                mutator()
                _validate_region_coverage(self, invalid_command)
            except Exception:
                self._solver = restore_solver(before)
                raise
            frame_id = _emit_edit_frame(self)
            return (frame_id,), (), 0.0

        return self._execute_recorded(command_name, canonical, action)

    def add_bubble(
        self,
        bubble_id: str,
        centroid_m,
        equivalent_radius_m: float,
        velocity_m_s,
        surface_tension_n_m: float,
    ):
        parsed_id = _bubble_id(bubble_id, invalid_command)
        center = _vector3(centroid_m, "centroid_m", invalid_command)
        radius = _finite_scalar(
            equivalent_radius_m, "equivalent_radius_m", invalid_command
        )
        velocity = _vector3(velocity_m_s, "velocity_m_s", invalid_command)
        tension = _finite_scalar(
            surface_tension_n_m, "surface_tension_n_m", invalid_command
        )
        if radius <= 0.0:
            raise invalid_command("equivalent_radius_m must be positive")
        if tension < 0.0:
            raise invalid_command("surface_tension_n_m must be non-negative")
        requested = {
            "bubble_id": parsed_id,
            "centroid_m": list(center),
            "equivalent_radius_m": radius,
            "velocity_m_s": list(velocity),
            "surface_tension_n_m": tension,
        }

        def mutate():
            assert self._solver is not None
            if any(front.bubble_id == parsed_id for front in self._solver.fronts):
                raise invalid_command(f"bubble id {parsed_id!r} already exists")
            candidate = transient_icosphere(
                radius_m=radius,
                center_m=center,
                subdivisions=1,
                bubble_id=parsed_id,
                surface_tension_n_m=tension,
            )
            _validate_nonoverlap(self, candidate, invalid_command)
            preserved = dict(self._solver._bubble_velocities)
            self._solver.fronts.append(candidate)
            self._solver.surface_fields[parsed_id] = {}
            preserved[parsed_id] = velocity
            _refresh_after_geometry_edit(self, preserved)

        return _run_edit(self, "ADD_BUBBLE", requested, mutate)

    def delete_bubble(self, bubble_id: str):
        parsed_id = _bubble_id(bubble_id, invalid_command)
        requested = {"bubble_id": parsed_id}

        def mutate():
            assert self._solver is not None
            _front(self, parsed_id, invalid_command)
            if len(self._solver.fronts) <= 1:
                raise invalid_command(
                    "cannot delete the final bubble: the transient solver requires at "
                    "least one tracked front"
                )
            self._solver.fronts = [
                front
                for front in self._solver.fronts
                if front.bubble_id != parsed_id
            ]
            self._solver.surface_fields.pop(parsed_id, None)
            self._solver._bubble_velocities.pop(parsed_id, None)
            preserved = dict(self._solver._bubble_velocities)
            _refresh_after_geometry_edit(self, preserved)

        return _run_edit(self, "DELETE_BUBBLE", requested, mutate)

    def move_bubble(self, bubble_id: str, centroid_m):
        parsed_id = _bubble_id(bubble_id, invalid_command)
        target = _vector3(centroid_m, "centroid_m", invalid_command)
        requested = {"bubble_id": parsed_id, "centroid_m": list(target)}

        def mutate():
            assert self._solver is not None
            current = _front(self, parsed_id, invalid_command)
            candidate = current.clone()
            source = candidate.centroid()
            delta = tuple(target[index] - source[index] for index in range(3))
            candidate.vertices = [
                tuple(vertex[index] + delta[index] for index in range(3))
                for vertex in candidate.vertices
            ]
            _validate_nonoverlap(
                self, candidate, invalid_command, replacing_id=parsed_id
            )
            preserved = dict(self._solver._bubble_velocities)
            current.vertices = list(candidate.vertices)
            _refresh_after_geometry_edit(self, preserved)

        return _run_edit(self, "MOVE_BUBBLE", requested, mutate)

    def resize_bubble(self, bubble_id: str, equivalent_radius_m: float):
        parsed_id = _bubble_id(bubble_id, invalid_command)
        target_radius = _finite_scalar(
            equivalent_radius_m, "equivalent_radius_m", invalid_command
        )
        if target_radius <= 0.0:
            raise invalid_command("equivalent_radius_m must be positive")
        requested = {
            "bubble_id": parsed_id,
            "equivalent_radius_m": target_radius,
        }

        def mutate():
            assert self._solver is not None
            current = _front(self, parsed_id, invalid_command)
            candidate = current.clone()
            current_radius = candidate.equivalent_radius()
            if current_radius <= 0.0:
                raise invalid_command("cannot resize a collapsed bubble front")
            scale = target_radius / current_radius
            center = candidate.centroid()
            candidate.vertices = [
                tuple(
                    center[index]
                    + (vertex[index] - center[index]) * scale
                    for index in range(3)
                )
                for vertex in candidate.vertices
            ]
            candidate.target_volume_m3 = candidate.volume()
            _validate_nonoverlap(
                self, candidate, invalid_command, replacing_id=parsed_id
            )
            preserved = dict(self._solver._bubble_velocities)
            current.vertices = list(candidate.vertices)
            current.target_volume_m3 = candidate.target_volume_m3
            _refresh_after_geometry_edit(self, preserved)

        return _run_edit(self, "RESIZE_BUBBLE", requested, mutate)

    def set_bubble_velocity(self, bubble_id: str, velocity_m_s):
        parsed_id = _bubble_id(bubble_id, invalid_command)
        velocity = _vector3(velocity_m_s, "velocity_m_s", invalid_command)
        requested = {
            "bubble_id": parsed_id,
            "velocity_m_s": list(velocity),
            "authoritative_rebuild": "NONE",
        }

        def action():
            _require_editable(self, "SET_BUBBLE_VELOCITY")
            assert self._solver is not None
            _front(self, parsed_id, invalid_command)
            _seed_bubble_velocity(self._solver, parsed_id, velocity)
            frame_id = _emit_edit_frame(self)
            return (frame_id,), (), 0.0

        return self._execute_recorded(
            "SET_BUBBLE_VELOCITY", requested, action
        )

    def execute(self, command):
        if not isinstance(command, Mapping):
            return original_execute(self, command)
        payload = dict(command)
        raw_name = payload.get("command", payload.get("type"))
        name = raw_name.strip().upper() if isinstance(raw_name, str) else ""
        if name not in _EDIT_COMMANDS:
            return original_execute(self, command)
        if name == "ADD_BUBBLE":
            return add_bubble(
                self,
                payload.get("bubble_id"),
                payload.get("centroid_m"),
                payload.get("equivalent_radius_m"),
                payload.get("velocity_m_s"),
                payload.get("surface_tension_n_m"),
            )
        if name == "DELETE_BUBBLE":
            return delete_bubble(self, payload.get("bubble_id"))
        if name == "MOVE_BUBBLE":
            return move_bubble(
                self, payload.get("bubble_id"), payload.get("centroid_m")
            )
        if name == "RESIZE_BUBBLE":
            return resize_bubble(
                self,
                payload.get("bubble_id"),
                payload.get("equivalent_radius_m"),
            )
        if name == "SET_BUBBLE_VELOCITY":
            return set_bubble_velocity(
                self, payload.get("bubble_id"), payload.get("velocity_m_s")
            )
        return original_execute(self, command)

    runtime_session_class.capabilities = property(capabilities)
    runtime_session_class.add_bubble = add_bubble
    runtime_session_class.delete_bubble = delete_bubble
    runtime_session_class.move_bubble = move_bubble
    runtime_session_class.resize_bubble = resize_bubble
    runtime_session_class.set_bubble_velocity = set_bubble_velocity
    runtime_session_class.execute = execute
    runtime_session_class.SESSION_VERSION = "1.1.0"
    runtime_session_class._live_runtime_editing_installed = True
