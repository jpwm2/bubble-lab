"""Deterministic same-build checkpoint/restart for the transient reference solver."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from typing import Any, Mapping

from bubblelab.solvers.boundary import (
    AxisAlignedBoxBoundary,
    PlaneBoundary,
    SolidBoundary,
    SphereBoundary,
    WettingParameters,
)

from .amr import AMRConfig, AMRLevel, AdaptiveEulerianGasGrid
from .geometry import FilmFront
from .grid import EulerianGasGrid, GridConfig, RegionProperties
from .remeshing import ConservativeArealField, RemeshConfig
from .solver import StepDiagnostics, TimeStepPolicy, TransientConfig, TransientSoapFilmSolver


CONTINUATION_FORMAT_VERSION = "1.0.0"


class CheckpointError(ValueError):
    """Base error for invalid or incompatible continuation state."""


class IncompatibleCheckpointError(CheckpointError):
    """Checkpoint cannot be restored exactly by this solver build."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def payload_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _tuple3(value: Any, name: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise CheckpointError(f"{name} must contain exactly three values")
    return (float(value[0]), float(value[1]), float(value[2]))


def _grid_config_dict(config: GridConfig) -> dict[str, Any]:
    return asdict(config)


def _grid_config_from_dict(raw: Mapping[str, Any]) -> GridConfig:
    return GridConfig(
        cells=tuple(int(x) for x in raw["cells"]),
        origin_m=_tuple3(raw["origin_m"], "grid.origin_m"),
        extent_m=_tuple3(raw["extent_m"], "grid.extent_m"),
        density_kg_m3=float(raw["density_kg_m3"]),
        dynamic_viscosity_pa_s=float(raw["dynamic_viscosity_pa_s"]),
        background_velocity_m_s=_tuple3(
            raw["background_velocity_m_s"], "grid.background_velocity_m_s"
        ),
        pressure_iterations=int(raw["pressure_iterations"]),
        pressure_tolerance_s_inv=float(raw["pressure_tolerance_s_inv"]),
    )


def _wetting_dict(wetting: WettingParameters) -> dict[str, Any]:
    return asdict(wetting)


def _wetting_from_dict(raw: Mapping[str, Any]) -> WettingParameters:
    angle = raw.get("target_contact_angle_deg")
    return WettingParameters(
        target_contact_angle_deg=None if angle is None else float(angle),
        relaxation=float(raw["relaxation"]),
        iterations=int(raw["iterations"]),
        contact_band_m=float(raw["contact_band_m"]),
    )


def _boundary_dict(boundary: SolidBoundary) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": boundary.boundary_type,
        "boundary_id": boundary.boundary_id,
        "wall_velocity_m_s": list(boundary.wall_velocity_m_s),
        "wetting": _wetting_dict(boundary.wetting),
    }
    if isinstance(boundary, PlaneBoundary):
        out.update(
            {
                "point_m": list(boundary.point_m),
                "normal_outward": list(boundary.normal_outward),
            }
        )
    elif isinstance(boundary, SphereBoundary):
        out.update(
            {
                "center_m": list(boundary.center_m),
                "radius_m": boundary.radius_m,
            }
        )
    elif isinstance(boundary, AxisAlignedBoxBoundary):
        out.update(
            {
                "minimum_m": list(boundary.minimum_m),
                "maximum_m": list(boundary.maximum_m),
            }
        )
    else:
        raise IncompatibleCheckpointError(
            f"unsupported solid boundary type {type(boundary).__name__!r}"
        )
    return out


def _boundary_from_dict(raw: Mapping[str, Any]) -> SolidBoundary:
    common = {
        "boundary_id": str(raw["boundary_id"]),
        "wall_velocity_m_s": _tuple3(raw["wall_velocity_m_s"], "boundary.wall_velocity_m_s"),
        "wetting": _wetting_from_dict(raw["wetting"]),
    }
    kind = raw.get("type")
    if kind == "PLANE":
        return PlaneBoundary(
            **common,
            point_m=_tuple3(raw["point_m"], "boundary.point_m"),
            normal_outward=_tuple3(raw["normal_outward"], "boundary.normal_outward"),
        )
    if kind == "SPHERE":
        return SphereBoundary(
            **common,
            center_m=_tuple3(raw["center_m"], "boundary.center_m"),
            radius_m=float(raw["radius_m"]),
        )
    if kind == "AABB":
        return AxisAlignedBoxBoundary(
            **common,
            minimum_m=_tuple3(raw["minimum_m"], "boundary.minimum_m"),
            maximum_m=_tuple3(raw["maximum_m"], "boundary.maximum_m"),
        )
    raise IncompatibleCheckpointError(f"unsupported solid boundary checkpoint type {kind!r}")


def _config_dict(config: TransientConfig) -> dict[str, Any]:
    return {
        "grid": _grid_config_dict(config.grid),
        "amr": asdict(config.amr),
        "gravity_m_s2": list(config.gravity_m_s2),
        "timestep": asdict(config.timestep),
        "deterministic_seed": config.deterministic_seed,
        "preserve_closed_bubble_volume": config.preserve_closed_bubble_volume,
        "region_properties": {
            bubble_id: asdict(properties)
            for bubble_id, properties in sorted(config.region_properties.items())
        },
        "sharp_pressure_jump": config.sharp_pressure_jump,
        "remeshing": asdict(config.remeshing),
        "solid_boundaries": [_boundary_dict(item) for item in config.solid_boundaries],
        "boundary_tolerance_m": config.boundary_tolerance_m,
        "boundary_projection_iterations": config.boundary_projection_iterations,
    }


def _config_from_dict(raw: Mapping[str, Any]) -> TransientConfig:
    amr = raw["amr"]
    timestep = raw["timestep"]
    remesh = raw["remeshing"]
    return TransientConfig(
        grid=_grid_config_from_dict(raw["grid"]),
        amr=AMRConfig(
            enabled=bool(amr["enabled"]),
            max_levels=int(amr["max_levels"]),
            refinement_ratio=int(amr["refinement_ratio"]),
            front_band_cells=float(amr["front_band_cells"]),
            min_patch_parent_cells=int(amr["min_patch_parent_cells"]),
            boundary_fill_cells=int(amr["boundary_fill_cells"]),
        ),
        gravity_m_s2=_tuple3(raw["gravity_m_s2"], "config.gravity_m_s2"),
        timestep=TimeStepPolicy(
            max_dt_s=float(timestep["max_dt_s"]),
            advective_cfl=float(timestep["advective_cfl"]),
            viscous_safety=float(timestep["viscous_safety"]),
            capillary_safety=float(timestep["capillary_safety"]),
            min_dt_s=float(timestep["min_dt_s"]),
        ),
        deterministic_seed=int(raw["deterministic_seed"]),
        preserve_closed_bubble_volume=bool(raw["preserve_closed_bubble_volume"]),
        region_properties={
            str(bubble_id): RegionProperties(
                density_kg_m3=float(properties["density_kg_m3"]),
                dynamic_viscosity_pa_s=float(properties["dynamic_viscosity_pa_s"]),
            )
            for bubble_id, properties in raw["region_properties"].items()
        },
        sharp_pressure_jump=bool(raw["sharp_pressure_jump"]),
        remeshing=RemeshConfig(
            mode=str(remesh["mode"]),
            interval_steps=int(remesh["interval_steps"]),
            target_edge_length_m=(
                None
                if remesh["target_edge_length_m"] is None
                else float(remesh["target_edge_length_m"])
            ),
            min_edge_factor=float(remesh["min_edge_factor"]),
            max_edge_factor=float(remesh["max_edge_factor"]),
            min_angle_deg=float(remesh["min_angle_deg"]),
            max_aspect_ratio=float(remesh["max_aspect_ratio"]),
            max_passes=int(remesh["max_passes"]),
            max_operations_per_pass=int(remesh["max_operations_per_pass"]),
            smoothing_relaxation=float(remesh["smoothing_relaxation"]),
            max_geometry_relative_error=float(remesh["max_geometry_relative_error"]),
            amr_cell_size_factor=float(remesh["amr_cell_size_factor"]),
        ),
        solid_boundaries=tuple(_boundary_from_dict(item) for item in raw["solid_boundaries"]),
        boundary_tolerance_m=float(raw["boundary_tolerance_m"]),
        boundary_projection_iterations=int(raw["boundary_projection_iterations"]),
    )


def _front_dict(front: FilmFront) -> dict[str, Any]:
    return {
        "bubble_id": front.bubble_id,
        "mesh_id": front.mesh_id,
        "film_id": front.film_id,
        "vertices": [list(vertex) for vertex in front.vertices],
        "faces": [list(face) for face in front.faces],
        "surface_tension_n_m": front.surface_tension_n_m,
        "target_volume_m3": front.target_volume_m3,
    }


def _front_from_dict(raw: Mapping[str, Any]) -> FilmFront:
    return FilmFront(
        bubble_id=str(raw["bubble_id"]),
        mesh_id=str(raw["mesh_id"]),
        film_id=str(raw["film_id"]),
        vertices=[_tuple3(value, "front.vertex") for value in raw["vertices"]],
        faces=[tuple(int(index) for index in face) for face in raw["faces"]],
        surface_tension_n_m=float(raw["surface_tension_n_m"]),
        target_volume_m3=float(raw["target_volume_m3"]),
    )


def _grid_state_dict(grid: EulerianGasGrid) -> dict[str, Any]:
    return {
        "config": _grid_config_dict(grid.config),
        "u": list(grid.u),
        "v": list(grid.v),
        "w": list(grid.w),
        "pressure": list(grid.pressure),
        "region_labels": list(grid.region_labels),
        "density": list(grid.density),
        "dynamic_viscosity": list(grid.dynamic_viscosity),
        "capillary_pressure_potential": list(grid.capillary_pressure_potential),
        "last_projection_iterations": grid.last_projection_iterations,
        "last_projection_residual": grid.last_projection_residual,
        "last_gravity_m_s2": list(grid.last_gravity_m_s2),
        "hydrostatic_reference_density_kg_m3": grid.hydrostatic_reference_density_kg_m3,
    }


def _restore_grid_state(raw: Mapping[str, Any]) -> EulerianGasGrid:
    grid = EulerianGasGrid(_grid_config_from_dict(raw["config"]))
    expected = grid.nx * grid.ny * grid.nz
    array_names = (
        "u",
        "v",
        "w",
        "pressure",
        "region_labels",
        "density",
        "dynamic_viscosity",
        "capillary_pressure_potential",
    )
    for name in array_names:
        values = list(raw[name])
        if len(values) != expected:
            raise CheckpointError(
                f"grid field {name!r} has {len(values)} values, expected {expected}"
            )
        setattr(grid, name, values)
    grid.u = [float(value) for value in grid.u]
    grid.v = [float(value) for value in grid.v]
    grid.w = [float(value) for value in grid.w]
    grid.pressure = [float(value) for value in grid.pressure]
    grid.region_labels = [str(value) for value in grid.region_labels]
    grid.density = [float(value) for value in grid.density]
    grid.dynamic_viscosity = [float(value) for value in grid.dynamic_viscosity]
    grid.capillary_pressure_potential = [
        float(value) for value in grid.capillary_pressure_potential
    ]
    grid.last_projection_iterations = int(raw["last_projection_iterations"])
    grid.last_projection_residual = float(raw["last_projection_residual"])
    grid.last_gravity_m_s2 = _tuple3(raw["last_gravity_m_s2"], "grid.last_gravity_m_s2")
    hydro = raw.get("hydrostatic_reference_density_kg_m3")
    grid.hydrostatic_reference_density_kg_m3 = None if hydro is None else float(hydro)
    return grid


def _solver_grid_dict(solver: TransientSoapFilmSolver) -> dict[str, Any]:
    if isinstance(solver.grid, AdaptiveEulerianGasGrid):
        return {
            "kind": "AMR",
            "levels": [
                {
                    "level": level.level,
                    "parent_bounds": (
                        None if level.parent_bounds is None else list(level.parent_bounds)
                    ),
                    "grid": _grid_state_dict(level.grid),
                }
                for level in solver.grid.levels
            ],
        }
    if type(solver.grid) is EulerianGasGrid:
        return {"kind": "UNIFORM", "grid": _grid_state_dict(solver.grid)}
    raise IncompatibleCheckpointError(
        f"unsupported transient grid implementation {type(solver.grid).__name__!r}"
    )


def _restore_solver_grid(
    raw: Mapping[str, Any], config: TransientConfig
) -> EulerianGasGrid | AdaptiveEulerianGasGrid:
    kind = raw.get("kind")
    if kind == "UNIFORM":
        if config.amr.enabled:
            raise CheckpointError("uniform checkpoint conflicts with AMR-enabled configuration")
        return _restore_grid_state(raw["grid"])
    if kind == "AMR":
        if not config.amr.enabled:
            raise CheckpointError("AMR checkpoint conflicts with AMR-disabled configuration")
        levels_raw = list(raw.get("levels") or [])
        if not levels_raw or int(levels_raw[0]["level"]) != 0:
            raise CheckpointError("AMR checkpoint requires level zero")
        hierarchy = AdaptiveEulerianGasGrid(config.grid, config.amr)
        restored: list[AMRLevel] = []
        for expected_level, item in enumerate(levels_raw):
            level_index = int(item["level"])
            if level_index != expected_level:
                raise CheckpointError("AMR levels must be contiguous and deterministically ordered")
            bounds_raw = item.get("parent_bounds")
            bounds = (
                None
                if bounds_raw is None
                else tuple(int(value) for value in bounds_raw)
            )
            if level_index == 0 and bounds is not None:
                raise CheckpointError("AMR level zero must not have parent bounds")
            if level_index > 0 and (bounds is None or len(bounds) != 6):
                raise CheckpointError("refined AMR level requires six parent bounds")
            restored.append(
                AMRLevel(
                    level_index,
                    _restore_grid_state(item["grid"]),
                    bounds,
                )
            )
        hierarchy.levels = restored
        return hierarchy
    raise IncompatibleCheckpointError(f"unsupported grid checkpoint kind {kind!r}")


def _diagnostic_dict(diagnostic: StepDiagnostics) -> dict[str, Any]:
    return asdict(diagnostic)


def _diagnostic_from_dict(raw: Mapping[str, Any]) -> StepDiagnostics:
    data = dict(raw)
    data["net_capillary_force_n"] = _tuple3(
        data["net_capillary_force_n"], "diagnostic.net_capillary_force_n"
    )
    data["remesh_reports"] = tuple(data.get("remesh_reports") or ())
    data["boundary_ids"] = tuple(str(value) for value in data.get("boundary_ids") or ())
    data["boundary_reports"] = tuple(data.get("boundary_reports") or ())
    return StepDiagnostics(**data)


def snapshot_solver(solver: TransientSoapFilmSolver) -> dict[str, Any]:
    if type(solver) is not TransientSoapFilmSolver:
        raise IncompatibleCheckpointError(
            "same-build restart currently supports TransientSoapFilmSolver exactly; "
            f"got {type(solver).__name__}"
        )
    return {
        "continuation_format_version": CONTINUATION_FORMAT_VERSION,
        "solver_class": "TransientSoapFilmSolver",
        "solver_version": solver.VERSION,
        "deterministic_seed": solver.config.deterministic_seed,
        "time_s": solver.time_s,
        "step_index": solver.step_index,
        "config": _config_dict(solver.config),
        "fronts": [_front_dict(front) for front in solver.fronts],
        "grid": _solver_grid_dict(solver),
        "bubble_velocities": {
            bubble_id: list(value)
            for bubble_id, value in sorted(solver._bubble_velocities.items())
        },
        "pressure_jumps_pa": dict(sorted(solver._pressure_jumps_pa.items())),
        "surface_fields": {
            bubble_id: {
                name: {
                    "name": field.name,
                    "face_amounts": list(field.face_amounts),
                }
                for name, field in sorted(fields.items())
            }
            for bubble_id, fields in sorted(solver.surface_fields.items())
        },
        "history": [_diagnostic_dict(item) for item in solver.history],
    }


def restore_solver(payload: Mapping[str, Any]) -> TransientSoapFilmSolver:
    if payload.get("continuation_format_version") != CONTINUATION_FORMAT_VERSION:
        raise IncompatibleCheckpointError(
            "unsupported transient continuation format "
            f"{payload.get('continuation_format_version')!r}"
        )
    if payload.get("solver_class") != "TransientSoapFilmSolver":
        raise IncompatibleCheckpointError(
            f"unsupported solver class {payload.get('solver_class')!r}"
        )
    if payload.get("solver_version") != TransientSoapFilmSolver.VERSION:
        raise IncompatibleCheckpointError(
            "checkpoint solver version "
            f"{payload.get('solver_version')!r} does not match "
            f"{TransientSoapFilmSolver.VERSION!r}; portable cross-version restart is not claimed"
        )

    config = _config_from_dict(payload["config"])
    if int(payload.get("deterministic_seed")) != config.deterministic_seed:
        raise CheckpointError("deterministic seed disagrees with serialized solver configuration")
    fronts = [_front_from_dict(item) for item in payload["fronts"]]
    solver = TransientSoapFilmSolver(fronts, config)
    solver.grid = _restore_solver_grid(payload["grid"], config)
    solver.time_s = float(payload["time_s"])
    solver.step_index = int(payload["step_index"])
    solver.history = [_diagnostic_from_dict(item) for item in payload.get("history", [])]
    solver._bubble_velocities = {
        str(bubble_id): _tuple3(value, f"bubble velocity {bubble_id}")
        for bubble_id, value in payload["bubble_velocities"].items()
    }
    solver._pressure_jumps_pa = {
        str(bubble_id): float(value)
        for bubble_id, value in payload["pressure_jumps_pa"].items()
    }

    expected_ids = {front.bubble_id for front in solver.fronts}
    if set(solver._bubble_velocities) != expected_ids:
        raise CheckpointError("bubble velocity state does not match restored fronts")
    fields: dict[str, dict[str, ConservativeArealField]] = {}
    raw_fields = payload.get("surface_fields") or {}
    if set(raw_fields) != expected_ids:
        raise CheckpointError("surface-field state does not match restored fronts")
    for front in solver.fronts:
        front_fields: dict[str, ConservativeArealField] = {}
        for name, field_raw in raw_fields[front.bubble_id].items():
            stored_name = str(field_raw["name"])
            if stored_name != name:
                raise CheckpointError("surface-field name/key mismatch")
            amounts = [float(value) for value in field_raw["face_amounts"]]
            if len(amounts) != len(front.faces):
                raise CheckpointError(
                    f"surface field {name!r} face count does not match restored front"
                )
            front_fields[name] = ConservativeArealField(stored_name, amounts)
        fields[front.bubble_id] = front_fields
    solver.surface_fields = fields
    return solver


def authoritative_state(solver: TransientSoapFilmSolver) -> dict[str, Any]:
    """Return the exact same-build numerical continuation state used for comparisons."""
    return snapshot_solver(solver)
