"""Canonical SCENARIO -> accepted backend -> deterministic replay bundle."""
from __future__ import annotations
import copy, hashlib, json, math, sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIB = ROOT / "bubblelab" / "python"
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
if str(PYTHON_LIB) not in sys.path: sys.path.insert(0, str(PYTHON_LIB))

from bubblelab_contract import assert_valid
from bubblelab.solvers.equilibrium import icosphere as equilibrium_icosphere, solve_prescribed_volume
from bubblelab.solvers.equilibrium.export import canonical_frame as equilibrium_frame, SOLVER_VERSION as EQUILIBRIUM_VERSION
from bubblelab.solvers.transient import GridConfig, TransientConfig, TransientSoapFilmSolver, frame_dict as transient_frame
from bubblelab.solvers.transient.geometry import icosphere as transient_icosphere
from bubblelab.runtime.boundary_runtime import (
    BoundaryRuntimeConfigurationError,
    UnsupportedBoundaryFeature,
    solid_boundaries_from_scenario,
)
from bubblelab.runtime.contact_runtime import (
    ContactRuntimeConfigurationError,
    run_contact_transition,
)
from bubblelab.runtime.network_runtime import (
    NetworkRuntimeConfigurationError,
    is_network_equilibrium_scenario,
    run_network_equilibrium,
)
from bubblelab.runtime.thinfilm_runtime import (
    advance_transient_coupled,
    attach_transient_thinfilm,
    augment_transient_frame,
    feature_flags as thinfilm_feature_flags,
    output_cadence_s,
    run_pairwise_gas_frames,
    thinfilm_config,
)
from bubblelab.runtime.transient_network_runtime import (
    TransientNetworkRuntimeConfigurationError,
    run_transient_network,
)

class UnsupportedScenarioFeature(ValueError):
    pass

UNSUPPORTED = {
    "rupture", "coalescence", "adaptive_mesh_refinement", "amr",
    "cfd", "vof", "level_set", "topology_change",
}

SUPPORTED_BULK_WALL_FEATURE = "bulk_solid_wall_no_slip"
UNSUPPORTED_BULK_WALL_FEATURES = {
    "no_slip_wall",
    "bulk_no_slip",
    "bulk_solid_fluid_wall_coupling",
    "resolved_bulk_wall_coupling",
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def scenario_hash(scenario: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(scenario)).hexdigest()


def _requested_features(scenario: Mapping[str, Any]) -> dict[str, Any]:
    requested = scenario.get("requested_solver") or {}
    editable = scenario.get("user_editable") or {}
    features: dict[str, Any] = {}
    if isinstance(requested, Mapping):
        maybe = requested.get("features")
        if isinstance(maybe, Mapping):
            features.update(maybe)
    if isinstance(editable, Mapping):
        maybe = editable.get("features")
        if isinstance(maybe, Mapping):
            features.update(maybe)
    return features


def _feature_guard(scenario: Mapping[str, Any], backend: str) -> None:
    features = _requested_features(scenario)
    bad = sorted(
        k for k, v in features.items()
        if k in UNSUPPORTED
        and bool(v)
        and not (backend == "contact-transition" and k == "topology_change")
    )
    if bad:
        raise UnsupportedScenarioFeature("unsupported scenario feature(s): " + ", ".join(bad))

    bad_bulk_wall = sorted(
        key for key, value in features.items()
        if key in UNSUPPORTED_BULK_WALL_FEATURES and bool(value)
    )
    if bad_bulk_wall:
        raise UnsupportedScenarioFeature(
            "unsupported bulk-wall feature alias(es): "
            + ", ".join(bad_bulk_wall)
            + f"; use {SUPPORTED_BULK_WALL_FEATURE}"
        )
    requested_bulk_wall = bool(features.get(SUPPORTED_BULK_WALL_FEATURE))
    if requested_bulk_wall and backend != "transient":
        raise UnsupportedScenarioFeature(
            f"{SUPPORTED_BULK_WALL_FEATURE} is integrated only with the transient backend"
        )

    config = thinfilm_config(scenario)
    requested_thinfilm = any(
        bool(features.get(name))
        for name in ("drainage", "surfactant_diffusion", "variable_surface_tension")
    )
    requested_gas = any(
        bool(features.get(name))
        for name in ("gas_diffusion", "coarsening")
    )
    requested_shared = any(
        bool(features.get(name))
        for name in ("shared_films", "shared_film_topology")
    )
    boundaries = (scenario.get("environment") or {}).get("boundary_refs")

    if backend == "transient":
        if requested_bulk_wall and not boundaries:
            raise UnsupportedScenarioFeature(
                f"{SUPPORTED_BULK_WALL_FEATURE} requires environment.boundary_refs and user_editable.solid_boundaries"
            )
        if bool(features.get("boundary_geometry")) and not boundaries:
            raise UnsupportedScenarioFeature(
                "boundary_geometry requires environment.boundary_refs and user_editable.solid_boundaries"
            )
        if boundaries:
            try:
                solid_boundaries_from_scenario(scenario)
            except UnsupportedBoundaryFeature as exc:
                raise UnsupportedScenarioFeature(str(exc)) from exc
            except BoundaryRuntimeConfigurationError:
                raise
        if requested_thinfilm and config is None:
            names = [
                name for name in ("drainage", "surfactant_diffusion", "variable_surface_tension")
                if bool(features.get(name))
            ]
            raise UnsupportedScenarioFeature(
                ", ".join(names) + " requires user_editable.thinfilm runtime configuration"
            )
        if requested_gas or requested_shared:
            raise UnsupportedScenarioFeature(
                "transient thin-film mode does not support pairwise gas diffusion or shared-film topology"
            )
        if scenario.get("initial_surface_meshes") or scenario.get("initial_film_regions"):
            raise UnsupportedScenarioFeature(
                "transient thin-film mode constructs its transport mesh from the tracked outer FilmFront"
            )
        if scenario.get("initial_junctions"):
            raise UnsupportedScenarioFeature(
                "multi-junction thin-film transport is not supported by transient runtime integration"
            )
        if config is not None and thinfilm_feature_flags(config)["gas_diffusion"]:
            raise UnsupportedScenarioFeature(
                "enable_gas_diffusion requires the thinfilm backend with one shared film"
            )
    elif backend == "thinfilm":
        if boundaries or bool(features.get("boundary_geometry")):
            raise UnsupportedScenarioFeature(
                "solid-boundary geometry is currently integrated only with the transient backend"
            )
        if config is None:
            raise UnsupportedScenarioFeature(
                "thinfilm backend requires user_editable.thinfilm runtime configuration"
            )
        flags = thinfilm_feature_flags(config)
        if not flags["gas_diffusion"]:
            raise UnsupportedScenarioFeature(
                "thinfilm backend currently requires enable_gas_diffusion=true"
            )
        if flags["drainage"] or flags["surfactant_diffusion"]:
            raise UnsupportedScenarioFeature(
                "standalone thinfilm backend supports fixed-film gas diffusion only; "
                "drainage/surfactant transport must use transient coupling"
            )
        if scenario.get("initial_junctions"):
            raise UnsupportedScenarioFeature(
                "unsupported multi-junction transport in thinfilm backend"
            )
        if not requested_gas:
            raise UnsupportedScenarioFeature(
                "thinfilm backend requires gas_diffusion/coarsening to be requested explicitly"
            )
        if not requested_shared:
            raise UnsupportedScenarioFeature(
                "thinfilm backend requires explicit shared_film_topology feature disclosure"
            )
    elif backend == "contact-transition":
        if boundaries or bool(features.get("boundary_geometry")):
            raise UnsupportedScenarioFeature(
                "solid-boundary geometry is outside the supported contact-transition slice"
            )
        if requested_thinfilm or requested_gas:
            raise UnsupportedScenarioFeature(
                "contact-transition does not resolve drainage/surfactant or gas diffusion/coarsening"
            )
        if not requested_shared:
            raise UnsupportedScenarioFeature(
                "contact-transition requires explicit shared-film topology disclosure"
            )
        if not bool(features.get("automatic_contact_detection")):
            raise UnsupportedScenarioFeature(
                "contact-transition requires automatic_contact_detection"
            )
    elif backend == "transient-network":
        if boundaries or bool(features.get("boundary_geometry")):
            raise UnsupportedScenarioFeature(
                "solid-boundary geometry is not integrated with the transient-network backend"
            )
    elif backend == "equilibrium":
        if boundaries or bool(features.get("boundary_geometry")):
            raise UnsupportedScenarioFeature(
                "solid-boundary geometry is currently integrated only with the transient backend"
            )
    else:
        if boundaries or bool(features.get("boundary_geometry")):
            raise UnsupportedScenarioFeature(
                "solid-boundary geometry is currently integrated only with the transient backend"
            )
        for key in ("initial_film_regions", "initial_junctions"):
            values = scenario.get(key)
            if values:
                raise UnsupportedScenarioFeature(
                    f"{key} is not supported by the {backend} runtime slice"
                )


def _single_bubble(scenario: Mapping[str, Any]) -> Mapping[str, Any]:
    bubbles = scenario["initial_bubbles"]
    if len(bubbles) != 1:
        raise UnsupportedScenarioFeature("this integration slice supports exactly one bubble")
    bubble = bubbles[0]
    r = float(bubble["equivalent_radius_m"])
    v = float(bubble["volume_m3"])
    expected = 4.0 * math.pi * r ** 3 / 3.0
    if abs(v - expected) / max(v, expected) > 1.0e-6:
        raise ValueError("equivalent_radius_m and volume_m3 are inconsistent")
    return bubble


def _tension(bubble: Mapping[str, Any]) -> float:
    material = bubble.get("film_material") or {}
    for key in ("effective_sheet_tension_n_m", "surface_tension_n_m"):
        if key in material:
            value = float(material[key])
            if value <= 0: raise ValueError("surface tension must be positive")
            return value
    raise ValueError("film_material.effective_sheet_tension_n_m is required")


def _decorate(frame: dict[str, Any], scenario: Mapping[str, Any], backend: str) -> dict[str, Any]:
    out = copy.deepcopy(frame)
    out["manifest"]["random_seed"] = int(scenario["random_seed"])
    out["manifest"]["provenance"]["source_scenario"] = scenario["scenario_id"]
    out["manifest"]["provenance"]["scenario_sha256"] = scenario_hash(scenario)
    out["manifest"]["provenance"]["runtime_adapter"] = f"bubblelab.runtime/{backend}"
    env = scenario["environment"]
    for key in ("ambient_density_kg_m3", "ambient_dynamic_viscosity_pa_s", "ambient_pressure_pa", "gravity_m_s2", "wind", "flow_metadata", "boundary_refs"):
        if key in env: out["environment"][key] = copy.deepcopy(env[key])
    assert_valid(out)
    return out


def _eulerian_level_grids(solver: TransientSoapFilmSolver) -> list[Any]:
    level_grids = getattr(solver.grid, "level_grids", None)
    if callable(level_grids):
        return list(level_grids())
    return [solver.grid]


def _wall_level_diagnostics(grid: Any, level_index: int) -> dict[str, Any]:
    wall = getattr(grid, "resolved_walls", None)
    if wall is None:
        return {
            "level": level_index,
            "installed": False,
            "cell_size_m": float(grid.h),
            "solid_cell_count": 0,
            "cut_face_count": 0,
            "tangential_reconstruction_sample_count": 0,
            "max_wall_normal_velocity_error_m_s": 0.0,
            "max_wall_tangential_reconstruction_error_m_s": 0.0,
            "max_solid_storage_velocity_error_m_s": 0.0,
            "boundary_ids": [],
        }

    components = (grid.u, grid.v, grid.w)
    cut_faces: set[tuple[int, int]] = set()
    normal_errors: list[float] = []
    tangential_errors: list[float] = []
    solid_errors: list[float] = []

    for q in wall.fluid_indices:
        for axis in range(3):
            for offset in (-1, 1):
                crossing = wall.intersection(q, axis, offset)
                if crossing is None:
                    continue
                slot = q if offset == 1 else grid._face_neighbor(q, axis, -1)
                cut_faces.add((axis, slot))
                normal_errors.append(
                    abs(
                        components[axis][slot]
                        - crossing.wall_velocity_dynamic_m_s[axis]
                    )
                )

                away = grid._face_neighbor(q, axis, -offset)
                if wall.is_solid(away):
                    continue
                fraction = crossing.distance_fraction
                for tangential_axis in range(3):
                    if tangential_axis == axis:
                        continue
                    field = components[tangential_axis]
                    reconstructed = (1.0 + fraction) * field[q] - fraction * field[away]
                    tangential_errors.append(
                        abs(
                            reconstructed
                            - crossing.wall_velocity_dynamic_m_s[tangential_axis]
                        )
                    )

    total_cells = grid.nx * grid.ny * grid.nz
    for q in range(total_cells):
        if not wall.is_solid(q):
            continue
        target = wall.dynamic_wall_velocity_for_cell(q)
        for axis, field in enumerate(components):
            solid_errors.append(abs(field[q] - target[axis]))

    return {
        "level": level_index,
        "installed": True,
        "wall_field": type(wall).__name__,
        "cell_size_m": float(grid.h),
        "solid_cell_count": int(wall.solid_cell_count),
        "cut_face_count": len(cut_faces),
        "tangential_reconstruction_sample_count": len(tangential_errors),
        "max_wall_normal_velocity_error_m_s": max(normal_errors, default=0.0),
        "max_wall_tangential_reconstruction_error_m_s": max(tangential_errors, default=0.0),
        "max_solid_storage_velocity_error_m_s": max(solid_errors, default=0.0),
        "boundary_ids": [boundary.boundary_id for boundary in wall.boundaries],
    }


def _bulk_wall_cfd_diagnostics(
    solver: TransientSoapFilmSolver,
    scenario: Mapping[str, Any],
) -> dict[str, Any]:
    levels = [
        _wall_level_diagnostics(grid, index)
        for index, grid in enumerate(_eulerian_level_grids(solver))
    ]
    installed = bool(levels) and all(level["installed"] for level in levels)
    wall_fields = sorted(
        {str(level.get("wall_field")) for level in levels if level.get("wall_field")}
    )
    return {
        "enabled": bool(solver.boundaries),
        "requested_explicitly": bool(
            _requested_features(scenario).get(SUPPORTED_BULK_WALL_FEATURE)
        ),
        "wall_field": wall_fields[0] if len(wall_fields) == 1 else wall_fields,
        "measurement_source": "authoritative Eulerian velocity state",
        "supported_scope": (
            "fixed SDF wall geometry with spatially uniform declared wall_velocity_m_s per boundary"
        ),
        "arbitrary_deforming_wall_geometry": "NOT_IMPLEMENTED",
        "level_count": len(levels),
        "installed_on_all_levels": installed,
        "solid_cell_count": sum(int(level["solid_cell_count"]) for level in levels),
        "cut_face_count": sum(int(level["cut_face_count"]) for level in levels),
        "tangential_reconstruction_sample_count": sum(
            int(level["tangential_reconstruction_sample_count"]) for level in levels
        ),
        "max_wall_normal_velocity_error_m_s": max(
            (float(level["max_wall_normal_velocity_error_m_s"]) for level in levels),
            default=0.0,
        ),
        "max_wall_tangential_reconstruction_error_m_s": max(
            (
                float(level["max_wall_tangential_reconstruction_error_m_s"])
                for level in levels
            ),
            default=0.0,
        ),
        "max_solid_storage_velocity_error_m_s": max(
            (float(level["max_solid_storage_velocity_error_m_s"]) for level in levels),
            default=0.0,
        ),
        "levels": levels,
    }


def _annotate_transient_wall_frame(
    frame: dict[str, Any],
    solver: TransientSoapFilmSolver,
    scenario: Mapping[str, Any],
) -> dict[str, Any]:
    out = _decorate(frame, scenario, "transient")
    if not solver.boundaries:
        return out

    wall_diag = _bulk_wall_cfd_diagnostics(solver, scenario)
    if not wall_diag["installed_on_all_levels"]:
        raise RuntimeError(
            "solid boundaries are configured but ResolvedNoSlipWallField is not installed on every active Eulerian level"
        )

    disclosures = out["manifest"]["feature_disclosures"]
    disclosures["bulk_solid_wall_no_slip"] = "RESOLVED"
    disclosures["bulk_solid_fluid_wall_coupling"] = "RESOLVED"
    adapter = out["manifest"]["solver"].get("adapter")
    if isinstance(adapter, str) and "sdf-noslip-wall" not in adapter:
        out["manifest"]["solver"]["adapter"] = adapter + "+sdf-noslip-wall"
    out["manifest"]["provenance"]["bulk_solid_wall_cfd"] = {
        "wall_field": wall_diag["wall_field"],
        "measurement_source": wall_diag["measurement_source"],
        "supported_scope": wall_diag["supported_scope"],
        "requested_explicitly": wall_diag["requested_explicitly"],
    }

    flow = out["environment"].setdefault("flow_metadata", {})
    flow["bulk_boundary_condition"] = (
        "periodic outer reference box with resolved SDF cut-stencil no-slip solid walls"
    )
    flow["solid_fluid_bulk_wall_coupling"] = (
        "ResolvedNoSlipWallField installed on every active Eulerian level"
    )
    flow["bulk_wall_motion_scope"] = (
        "spatially uniform wall_velocity_m_s per fixed SDF boundary"
    )

    out["diagnostics"]["bulk_solid_wall_cfd"] = wall_diag
    contact = out["diagnostics"].get("solid_boundary_contact")
    if isinstance(contact, dict):
        contact["bulk_eulerian_wall_coupling"] = "RESOLVED_SDF_CUT_STENCIL_NO_SLIP"

    sharp = out.get("transient_sharp_interface")
    if isinstance(sharp, dict):
        sharp["boundary_condition"] = (
            "periodic outer reference box plus resolved SDF cut-stencil no-slip bulk walls; "
            "tracked film independently obeys SDF no-penetration/free-slip with optional contact-angle law"
        )
        limitations = sharp.get("limitations")
        if isinstance(limitations, list):
            limitations = [
                item for item in limitations
                if "solid SDFs constrain tracked-film geometry only" not in str(item)
            ]
            scope_limit = (
                "resolved bulk wall scope is fixed SDF geometry with spatially uniform declared wall velocity per boundary; "
                "arbitrary deforming wall geometry is not implemented"
            )
            if scope_limit not in limitations:
                limitations.append(scope_limit)
            sharp["limitations"] = limitations

    assert_valid(out)
    return out


def _run_equilibrium(scenario: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if is_network_equilibrium_scenario(scenario):
        try:
            frame, backend_meta = run_network_equilibrium(scenario)
        except NetworkRuntimeConfigurationError as exc:
            raise UnsupportedScenarioFeature(str(exc)) from exc
        return [_decorate(frame, scenario, "equilibrium")], backend_meta

    bubble = _single_bubble(scenario)
    if any(abs(float(x)) > 0 for x in bubble["velocity_m_s"]):
        raise UnsupportedScenarioFeature("equilibrium backend does not support initial bubble velocity")
    gravity = scenario["environment"]["gravity_m_s2"]
    if any(abs(float(x)) > 0 for x in gravity):
        raise UnsupportedScenarioFeature("equilibrium backend supports only zero gravity in this slice")
    if scenario["requested_fidelity_tier"] != "HIGH_FIDELITY":
        raise ValueError("equilibrium backend requires HIGH_FIDELITY request")
    tension = _tension(bubble)
    radius = float(bubble["equivalent_radius_m"])
    target = float(bubble["volume_m3"])
    center = tuple(float(x) for x in bubble["centroid_m"])
    mesh = equilibrium_icosphere(2, radius, center)
    result = solve_prescribed_volume(mesh, target, tension)
    frame = equilibrium_frame(
        result, target_volume_m3=target, sheet_tension_n_m=tension,
        bubble_id=str(bubble["id"]), frame_id="equilibrium-final",
        random_seed=int(scenario["random_seed"]),
    )
    return [_decorate(frame, scenario, "equilibrium")], {
        "identity": "bubblelab-equilibrium", "version": EQUILIBRIUM_VERSION,
        "quasi_static": "final physical state only; optimizer iterations are not physical time frames",
    }


def _run_transient(scenario: Mapping[str, Any], frames: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    bubble = _single_bubble(scenario)
    if any(abs(float(x)) > 0 for x in bubble["velocity_m_s"]):
        raise UnsupportedScenarioFeature("transient foundation does not support independent initial bubble velocity; use environment.wind")
    if frames < 1:
        raise ValueError("--frames must be >= 1")
    tension = _tension(bubble)
    env = scenario["environment"]
    wind = tuple(float(x) for x in ((env.get("wind") or {}).get("velocity_m_s") or (0, 0, 0)))
    try:
        boundaries = solid_boundaries_from_scenario(scenario)
    except UnsupportedBoundaryFeature as exc:
        raise UnsupportedScenarioFeature(str(exc)) from exc
    grid = GridConfig(
        density_kg_m3=float(env["ambient_density_kg_m3"]),
        dynamic_viscosity_pa_s=float(env["ambient_dynamic_viscosity_pa_s"]),
        background_velocity_m_s=wind,
    )
    transient_config = TransientConfig(
        grid=grid,
        gravity_m_s2=tuple(float(x) for x in env["gravity_m_s2"]),
        deterministic_seed=int(scenario["random_seed"]),
        solid_boundaries=boundaries,
    )
    front = transient_icosphere(
        radius_m=float(bubble["equivalent_radius_m"]),
        center_m=tuple(float(x) for x in bubble["centroid_m"]),
        subdivisions=1,
        bubble_id=str(bubble["id"]),
        surface_tension_n_m=tension,
    )
    solver = TransientSoapFilmSolver([front], transient_config)
    film_config = thinfilm_config(scenario)

    if film_config is None:
        output = [
            _annotate_transient_wall_frame(
                transient_frame(solver, "transient-000000"), solver, scenario
            )
        ]
        for i in range(1, frames):
            solver.step()
            output.append(
                _annotate_transient_wall_frame(
                    transient_frame(solver, f"transient-{i:06d}"), solver, scenario
                )
            )
        backend_meta: dict[str, Any] = {
            "identity": "bubblelab-transient-reference",
            "version": solver.VERSION,
        }
        wall_diag = output[-1]["diagnostics"].get("bulk_solid_wall_cfd")
        if wall_diag is not None:
            backend_meta["bulk_wall_cfd"] = copy.deepcopy(wall_diag)
        return output, backend_meta

    attachment = attach_transient_thinfilm(solver, scenario, film_config)
    cadence = output_cadence_s(scenario)
    if cadence is None:
        cadence = solver.select_timestep()

    output: list[dict[str, Any]] = []
    initial = augment_transient_frame(
        transient_frame(solver, "transient-000000"),
        attachment,
        film_config,
    )
    output.append(_annotate_transient_wall_frame(initial, solver, scenario))
    last_step = None
    last_transfer = None
    for i in range(1, frames):
        target = i * cadence
        while solver.time_s + 1.0e-15 < target:
            remaining = target - solver.time_s
            dt = solver.select_timestep(remaining)
            last_step, last_transfer = advance_transient_coupled(
                solver,
                attachment,
                film_config,
                dt,
            )
        frame = augment_transient_frame(
            transient_frame(solver, f"transient-{i:06d}"),
            attachment,
            film_config,
            step_diagnostics=last_step,
            transfer_diagnostics=last_transfer,
        )
        output.append(_annotate_transient_wall_frame(frame, solver, scenario))
    backend_meta = {
        "identity": "bubblelab-transient-reference",
        "version": solver.VERSION,
        "thinfilm_extension": "bubblelab-reduced-thinfilm",
        "operator_split": (
            "transient bulk/front -> conservative areal transfer -> "
            "thin-film/surfactant -> updated tension"
        ),
    }
    wall_diag = output[-1]["diagnostics"].get("bulk_solid_wall_cfd")
    if wall_diag is not None:
        backend_meta["bulk_wall_cfd"] = copy.deepcopy(wall_diag)
    return output, backend_meta


def run_scenario(scenario: Mapping[str, Any], backend: str, output_dir: str | Path, frames: int = 4) -> dict[str, Any]:
    scenario = copy.deepcopy(dict(scenario))
    assert_valid(scenario)
    _feature_guard(scenario, backend)
    requested = scenario.get("requested_solver") or {}
    declared = requested.get("backend") if isinstance(requested, Mapping) else None
    if declared not in (None, backend):
        raise ValueError(f"scenario requested backend {declared!r}, CLI selected {backend!r}")
    if backend == "equilibrium":
        physical_frames, backend_meta = _run_equilibrium(scenario)
    elif backend == "transient":
        physical_frames, backend_meta = _run_transient(scenario, frames)
    elif backend == "thinfilm":
        raw_frames, backend_meta = run_pairwise_gas_frames(scenario, frames)
        physical_frames = [
            _decorate(frame, scenario, "thinfilm")
            for frame in raw_frames
        ]
    elif backend == "contact-transition":
        try:
            raw_frames, backend_meta = run_contact_transition(scenario, frames)
        except ContactRuntimeConfigurationError as exc:
            raise UnsupportedScenarioFeature(str(exc)) from exc
        physical_frames = [
            _decorate(frame, scenario, "contact-transition")
            for frame in raw_frames
        ]
    elif backend == "transient-network":
        try:
            raw_frames, backend_meta = run_transient_network(scenario, frames)
        except TransientNetworkRuntimeConfigurationError as exc:
            raise UnsupportedScenarioFeature(str(exc)) from exc
        physical_frames = [
            _decorate(frame, scenario, "transient-network")
            for frame in raw_frames
        ]
    else:
        raise ValueError(
            "backend must be equilibrium, transient, thinfilm, contact-transition, or transient-network"
        )

    out = Path(output_dir)
    frames_dir = out / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    refs = []
    for index, frame in enumerate(physical_frames):
        rel = f"frames/{index:06d}.json"
        (out / rel).write_bytes(_canonical_bytes(frame) + b"\n")
        refs.append({"frame_id": frame["frame_id"], "path": rel, "simulation_time_s": frame["simulation_time_s"]})
    cadence = (
        float(backend_meta["timestep_s"])
        if backend == "transient-network"
        else output_cadence_s(scenario)
    )
    replay = {
        "bundle_version": "1.0.0",
        "contract_version": "1.0.0",
        "scenario": {"id": scenario["scenario_id"], "sha256": scenario_hash(scenario)},
        "backend": backend_meta,
        "random_seed": scenario["random_seed"],
        "run_settings": {
            "backend": backend,
            "requested_frames": frames if backend in ("transient", "thinfilm", "contact-transition", "transient-network") else None,
            "output_cadence_s": cadence,
        },
        "frames": refs,
        "checkpoints": [],
        "provenance": {"producer": "bubblelab.runtime", "source_scenario": scenario["scenario_id"]},
        "fidelity": {
            "requested": scenario["requested_fidelity_tier"],
            "produced": physical_frames[-1]["manifest"]["fidelity_tier"],
            "feature_disclosures": physical_frames[-1]["manifest"]["feature_disclosures"],
            "checkpoint_continuation": "NOT_IMPLEMENTED",
        },
    }
    boundary_refs = (scenario.get("environment") or {}).get("boundary_refs")
    if boundary_refs:
        replay["run_settings"]["boundary_refs"] = list(boundary_refs)
    requested_features = _requested_features(scenario)
    if backend == "transient" and bool(requested_features.get(SUPPORTED_BULK_WALL_FEATURE)):
        replay["run_settings"]["bulk_solid_wall_no_slip_requested"] = True
    wall_diag = physical_frames[-1].get("diagnostics", {}).get("bulk_solid_wall_cfd")
    if wall_diag is not None:
        replay["provenance"]["bulk_solid_wall_cfd"] = {
            "status": "RESOLVED",
            "wall_field": wall_diag["wall_field"],
            "measurement_source": wall_diag["measurement_source"],
            "supported_scope": wall_diag["supported_scope"],
            "requested_explicitly": wall_diag["requested_explicitly"],
        }
    (out / "replay.json").write_bytes(_canonical_bytes(replay) + b"\n")
    return replay
