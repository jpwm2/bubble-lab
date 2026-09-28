"""Runtime coupling for accepted reduced-order thin-film physics.

The transient coupling is deliberately operator split:

1. advance the accepted transient bulk/front solver,
2. conservatively reinterpret attached areal amounts on the updated/remeshed front,
3. advance the accepted thin-film/surfactant transport state,
4. expose the updated mean surface tension to the next transient step.

Film thickness remains a lower-dimensional MODELED field.  This module never
claims that the liquid layer is volumetrically resolved.
"""
from __future__ import annotations

import copy
from dataclasses import asdict
import math
from typing import Any, Mapping, Sequence

from bubblelab.solvers.thinfilm import (
    GasRegionState,
    GasTransferPair,
    SurfaceMesh,
    SurfaceTransportParameters,
    SurfaceTransportState,
)
from bubblelab.solvers.transient.thinfilm_adapter import (
    ThinFilmAttachment,
    ThinFilmTransferDiagnostics,
)


THINFILM_KEYS = {
    "initial_thickness_m",
    "initial_surfactant_mol_m2",
    "enable_drainage",
    "enable_surfactant_diffusion",
    "enable_gas_diffusion",
    "dynamic_viscosity_pa_s",
    "liquid_density_kg_m3",
    "surfactant_diffusivity_m2_s",
    "clean_surface_tension_n_m",
    "surface_elasticity_n_m_per_mol_m2",
    "minimum_surface_tension_n_m",
    "disjoining_coefficient_pa_m3",
    "positivity_safety",
    "max_substeps",
    "gas_permeability_mol_m_per_m2_s_pa",
}
RUNTIME_KEYS = {"output_cadence_s"}


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def thinfilm_config(scenario: Mapping[str, Any]) -> Mapping[str, Any] | None:
    editable = scenario.get("user_editable") or {}
    editable = _mapping(editable, "user_editable")
    raw = editable.get("thinfilm")
    if raw is None:
        return None
    config = _mapping(raw, "user_editable.thinfilm")
    unknown = sorted(set(config) - THINFILM_KEYS)
    if unknown:
        raise ValueError("unsupported thin-film runtime setting(s): " + ", ".join(unknown))
    return config


def output_cadence_s(scenario: Mapping[str, Any]) -> float | None:
    editable = scenario.get("user_editable") or {}
    editable = _mapping(editable, "user_editable")
    raw = editable.get("runtime")
    if raw is None:
        return None
    runtime = _mapping(raw, "user_editable.runtime")
    unknown = sorted(set(runtime) - RUNTIME_KEYS)
    if unknown:
        raise ValueError("unsupported runtime setting(s): " + ", ".join(unknown))
    if "output_cadence_s" not in runtime:
        return None
    value = float(runtime["output_cadence_s"])
    if value <= 0.0 or not math.isfinite(value):
        raise ValueError("output_cadence_s must be a finite positive number")
    return value


def _bool(config: Mapping[str, Any], key: str, default: bool) -> bool:
    if key not in config:
        return default
    value = config[key]
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be boolean")
    return value


def feature_flags(config: Mapping[str, Any]) -> dict[str, bool]:
    return {
        "drainage": _bool(config, "enable_drainage", True),
        "surfactant_diffusion": _bool(config, "enable_surfactant_diffusion", True),
        "gas_diffusion": _bool(config, "enable_gas_diffusion", False),
    }


def _positive_float(
    config: Mapping[str, Any],
    key: str,
    default: float,
    *,
    allow_zero: bool = False,
) -> float:
    value = float(config.get(key, default))
    if not math.isfinite(value):
        raise ValueError(f"{key} must be finite")
    if value < 0.0 or (not allow_zero and value <= 0.0):
        relation = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{key} must be {relation}")
    return value


def _positive_int(config: Mapping[str, Any], key: str, default: int) -> int:
    value = config.get(key, default)
    if isinstance(value, bool) or int(value) != value or int(value) < 1:
        raise ValueError(f"{key} must be a positive integer")
    return int(value)


def _field_values(value: Any, count: int, name: str) -> list[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        values = [float(value)] * count
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = [float(item) for item in value]
        if len(values) != count:
            raise ValueError(f"{name} must contain one value per transport face")
    else:
        raise ValueError(f"{name} must be a scalar or face-value array")
    if any(not math.isfinite(item) or item < 0.0 for item in values):
        raise ValueError(f"{name} values must be finite and non-negative")
    return values


def surface_parameters(
    scenario: Mapping[str, Any],
    config: Mapping[str, Any],
) -> SurfaceTransportParameters:
    flags = feature_flags(config)
    gravity = (
        tuple(float(x) for x in scenario["environment"]["gravity_m_s2"])
        if flags["drainage"]
        else (0.0, 0.0, 0.0)
    )
    if len(gravity) != 3:
        raise ValueError("gravity_m_s2 must have three components")
    diffusivity = (
        _positive_float(
            config,
            "surfactant_diffusivity_m2_s",
            1.0e-9,
            allow_zero=True,
        )
        if flags["surfactant_diffusion"]
        else 0.0
    )
    disjoining = (
        float(config.get("disjoining_coefficient_pa_m3", 0.0))
        if flags["drainage"]
        else 0.0
    )
    if not math.isfinite(disjoining):
        raise ValueError("disjoining_coefficient_pa_m3 must be finite")
    return SurfaceTransportParameters(
        dynamic_viscosity_pa_s=_positive_float(
            config, "dynamic_viscosity_pa_s", 1.0e-3
        ),
        liquid_density_kg_m3=_positive_float(
            config, "liquid_density_kg_m3", 1000.0, allow_zero=True
        ),
        gravity_m_s2=gravity,
        surfactant_diffusivity_m2_s=diffusivity,
        clean_surface_tension_n_m=_positive_float(
            config, "clean_surface_tension_n_m", 0.050
        ),
        surface_elasticity_n_m_per_mol_m2=_positive_float(
            config,
            "surface_elasticity_n_m_per_mol_m2",
            2.0e3,
            allow_zero=True,
        ),
        minimum_surface_tension_n_m=_positive_float(
            config, "minimum_surface_tension_n_m", 0.020
        ),
        disjoining_coefficient_pa_m3=disjoining,
        positivity_safety=_positive_float(config, "positivity_safety", 0.45),
        max_substeps=_positive_int(config, "max_substeps", 10000),
    )


def attach_transient_thinfilm(
    solver: Any,
    scenario: Mapping[str, Any],
    config: Mapping[str, Any],
) -> ThinFilmAttachment:
    if len(solver.fronts) != 1:
        raise ValueError("transient thin-film coupling requires exactly one FilmFront")
    flags = feature_flags(config)
    if flags["gas_diffusion"]:
        raise ValueError("pairwise gas diffusion is not supported by transient thin-film mode")
    front = solver.fronts[0]
    count = len(front.faces)
    h = _field_values(
        config.get("initial_thickness_m", 8.0e-6),
        count,
        "initial_thickness_m",
    )
    gamma = _field_values(
        config.get("initial_surfactant_mol_m2", 0.0),
        count,
        "initial_surfactant_mol_m2",
    )
    attachment = ThinFilmAttachment(
        front,
        thickness_m=h,
        surfactant_mol_m2=gamma,
        parameters=surface_parameters(scenario, config),
    )
    for name, field in attachment.conservative_fields().items():
        solver.surface_fields[front.bubble_id][name] = field
    tensions = attachment.surface_tension_n_m()
    if tensions:
        front.surface_tension_n_m = math.fsum(tensions) / len(tensions)
    return attachment


def _face_velocity(solver: Any, front: Any) -> list[tuple[float, float, float]]:
    values: list[tuple[float, float, float]] = []
    for face in front.faces:
        samples = [solver.grid.sample_velocity(front.vertices[index]) for index in face]
        values.append(
            (
                math.fsum(v[0] for v in samples) / 3.0,
                math.fsum(v[1] for v in samples) / 3.0,
                math.fsum(v[2] for v in samples) / 3.0,
            )
        )
    return values


def advance_transient_coupled(
    solver: Any,
    attachment: ThinFilmAttachment,
    config: Mapping[str, Any],
    dt_s: float,
) -> tuple[Any, ThinFilmTransferDiagnostics]:
    """Advance one geometry/bulk -> transfer -> thin-film operator-split step."""
    solver.step(dt_s)
    front = solver.fronts[0]
    transfer = attachment.consume_remesh(
        front,
        solver.surface_fields[front.bubble_id],
    )
    flags = feature_flags(config)
    capillary = None
    if flags["drainage"]:
        jump = float(solver.target_pressure_jump_pa(front.bubble_id))
        capillary = [jump] * len(front.faces)
    step = attachment.advance(
        dt_s,
        face_velocity_m_s=_face_velocity(solver, front),
        capillary_pressure_pa=capillary,
    )
    for name, field in attachment.conservative_fields().items():
        solver.surface_fields[front.bubble_id][name] = field
    return step, transfer


def _array(dtype: str, shape: list[int], values: Sequence[Any]) -> dict[str, Any]:
    return {
        "storage": "INLINE",
        "dtype": dtype,
        "shape": shape,
        "values": list(values),
    }


def augment_transient_frame(
    frame: dict[str, Any],
    attachment: ThinFilmAttachment,
    config: Mapping[str, Any],
    *,
    step_diagnostics: Any | None = None,
    transfer_diagnostics: ThinFilmTransferDiagnostics | None = None,
) -> dict[str, Any]:
    out = copy.deepcopy(frame)
    state = attachment.state
    sigma = list(attachment.surface_tension_n_m())
    flags = feature_flags(config)
    mesh = next(
        (item for item in out["surface_meshes"] if item["id"] == state.mesh.mesh_id),
        None,
    )
    if mesh is None:
        raise ValueError("transient frame is missing the thin-film transport mesh")
    mesh.setdefault("fields", {})
    mesh["fields"]["film_thickness_m"] = _array(
        "float64", [len(state.thickness_m)], state.thickness_m
    )
    mesh["fields"]["surfactant_mol_m2"] = _array(
        "float64", [len(state.surfactant_mol_m2)], state.surfactant_mol_m2
    )
    mesh["fields"]["surface_tension_n_m"] = _array(
        "float64", [len(sigma)], sigma
    )

    mean_sigma = math.fsum(sigma) / len(sigma)
    film = next(
        (item for item in out["film_regions"] if item.get("mesh_id") == state.mesh.mesh_id),
        None,
    )
    if film is None:
        raise ValueError("transient frame is missing the thin-film region")
    film["surface_tension_n_m"] = mean_sigma
    film["thickness"] = {
        "representation": "FACE_FIELD",
        "field": "film_thickness_m",
        "units": "m",
        "fidelity": "MODELED",
    }
    for bubble in out["bubbles"]:
        if bubble["id"] == attachment.front.bubble_id:
            material = bubble.setdefault("film_material", {})
            material["effective_sheet_tension_n_m"] = mean_sigma
            material["surface_tension_source"] = "thin-film surfactant constitutive model"

    disclosures = out["manifest"]["feature_disclosures"]
    disclosures["film_thickness"] = "MODELED"
    disclosures["drainage"] = "MODELED" if flags["drainage"] else "NOT_IMPLEMENTED"
    disclosures["film_drainage"] = disclosures["drainage"]
    disclosures["surfactant_transport"] = "MODELED"
    disclosures["surfactant_diffusion"] = (
        "MODELED" if flags["surfactant_diffusion"] else "NOT_IMPLEMENTED"
    )
    disclosures["surface_tension"] = "MODELED"
    disclosures["marangoni_response"] = "MODELED"
    disclosures["gas_diffusion"] = "NOT_IMPLEMENTED"
    disclosures["coarsening"] = "NOT_IMPLEMENTED"
    out["manifest"]["provenance"]["thinfilm_operator_split"] = (
        "transient bulk/front -> conservative areal transfer -> "
        "thin-film/surfactant transport -> updated tension for next transient step"
    )

    thinfilm_diag: dict[str, Any] = {
        "min_thickness_m": min(state.thickness_m),
        "max_thickness_m": max(state.thickness_m),
        "liquid_amount_m3": state.liquid_amount_m3(),
        "surfactant_amount_mol": state.surfactant_amount_mol(),
        "min_surface_tension_n_m": min(sigma),
        "max_surface_tension_n_m": max(sigma),
        "mean_surface_tension_n_m": mean_sigma,
        "drainage_terms_enabled": flags["drainage"],
        "surfactant_diffusion_enabled": flags["surfactant_diffusion"],
        "face_velocity_source": "transient Eulerian velocity sampled at updated face vertices",
        "capillary_pressure_source": (
            "transient target pressure jump, uniform on the closed outer film"
            if flags["drainage"]
            else "disabled with drainage terms"
        ),
    }
    if step_diagnostics is not None:
        thinfilm_diag["step"] = asdict(step_diagnostics)
    if transfer_diagnostics is not None:
        thinfilm_diag["geometry_transfer"] = asdict(transfer_diagnostics)
    out.setdefault("diagnostics", {})["thinfilm"] = thinfilm_diag

    details = out.setdefault("transient_sharp_interface", {})
    limitations = details.get("limitations")
    if isinstance(limitations, list):
        details["limitations"] = [
            (
                "geometry remains a zero-thickness tracked sheet; finite liquid "
                "thickness is a lower-dimensional MODELED field, not a volumetric resolution"
                if item == "zero-thickness soap-film sheet; no finite liquid thickness"
                else item
            )
            for item in limitations
        ]
    details["thinfilm_operator_split"] = [
        "advance transient bulk flow and tracked geometry",
        "transfer conserved liquid/surfactant areal amounts to updated geometry",
        "advance reduced-order thickness and surfactant transport",
        "apply mean modeled surface tension to the next transient step",
    ]
    return out


def _inline_matrix(
    ref: Mapping[str, Any],
    *,
    width: int,
    cast: Any,
    name: str,
) -> list[tuple[Any, ...]]:
    if ref.get("storage") != "INLINE":
        raise ValueError(f"{name} must use INLINE storage in this runtime slice")
    shape = ref.get("shape")
    values = ref.get("values")
    if (
        not isinstance(shape, Sequence)
        or len(shape) != 2
        or int(shape[1]) != width
        or not isinstance(values, Sequence)
    ):
        raise ValueError(f"{name} has invalid shape")
    rows = int(shape[0])
    if len(values) != rows * width:
        raise ValueError(f"{name} value count does not match shape")
    return [
        tuple(cast(values[row * width + col]) for col in range(width))
        for row in range(rows)
    ]


def _shared_surface(scenario: Mapping[str, Any]) -> tuple[SurfaceMesh, dict[str, Any]]:
    meshes = scenario.get("initial_surface_meshes") or []
    films = scenario.get("initial_film_regions") or []
    if len(meshes) != 1 or len(films) != 1:
        raise ValueError(
            "thinfilm gas-diffusion mode requires exactly one shared surface mesh and one film region"
        )
    mesh_raw = _mapping(meshes[0], "initial_surface_meshes[0]")
    film_raw = _mapping(films[0], "initial_film_regions[0]")
    if mesh_raw.get("geometry_role") != "SHARED_FILM":
        raise ValueError("thinfilm gas-diffusion mesh must have geometry_role SHARED_FILM")
    if film_raw.get("kind") != "SHARED":
        raise ValueError("thinfilm gas-diffusion film region must have kind SHARED")
    if film_raw.get("mesh_id") != mesh_raw.get("id"):
        raise ValueError("shared film mesh_id does not match the supplied mesh")
    adjacent = film_raw.get("adjacent")
    bubble_ids = {str(item["id"]) for item in scenario["initial_bubbles"]}
    if (
        not isinstance(adjacent, Sequence)
        or len(adjacent) != 2
        or set(str(value) for value in adjacent) != bubble_ids
    ):
        raise ValueError("shared film adjacency must name exactly the two gas regions")
    vertices = _inline_matrix(
        _mapping(mesh_raw["vertices"], "vertices"),
        width=3,
        cast=float,
        name="shared-film vertices",
    )
    faces = _inline_matrix(
        _mapping(mesh_raw["faces"], "faces"),
        width=3,
        cast=int,
        name="shared-film faces",
    )
    surface = SurfaceMesh(
        vertices_m=tuple(vertices),
        faces=tuple(faces),
        mesh_id=str(mesh_raw["id"]),
        film_id=str(film_raw["id"]),
    )
    return surface, copy.deepcopy(dict(film_raw))


def _validate_radius_volume(bubble: Mapping[str, Any]) -> None:
    radius = float(bubble["equivalent_radius_m"])
    volume = float(bubble["volume_m3"])
    expected = 4.0 * math.pi * radius ** 3 / 3.0
    if abs(volume - expected) / max(volume, expected) > 1.0e-6:
        raise ValueError(
            f"bubble {bubble['id']!r} has inconsistent equivalent_radius_m and volume_m3"
        )


def _gas_frame(
    scenario: Mapping[str, Any],
    surface: SurfaceMesh,
    film_region: Mapping[str, Any],
    film_state: SurfaceTransportState,
    gas_states: Sequence[GasRegionState],
    *,
    frame_index: int,
    time_s: float,
    cadence_s: float,
    initial_total_mol: float,
    cumulative_transfer_a_to_b_mol: float,
    last_gas_step: Any | None,
    pair: GasTransferPair,
) -> dict[str, Any]:
    sigma = list(film_state.surface_tension_n_m())
    flat_vertices = [coord for vertex in surface.vertices_m for coord in vertex]
    flat_faces = [index for face in surface.faces for index in face]
    mesh_raw = copy.deepcopy(scenario["initial_surface_meshes"][0])
    mesh_raw["vertices"] = _array(
        "float64", [len(surface.vertices_m), 3], flat_vertices
    )
    mesh_raw["faces"] = _array("uint32", [len(surface.faces), 3], flat_faces)
    mesh_raw["vertex_count"] = len(surface.vertices_m)
    mesh_raw["face_count"] = len(surface.faces)
    mesh_raw.setdefault("fields", {})
    mesh_raw["fields"]["film_thickness_m"] = _array(
        "float64", [len(surface.faces)], film_state.thickness_m
    )
    mesh_raw["fields"]["surfactant_mol_m2"] = _array(
        "float64", [len(surface.faces)], film_state.surfactant_mol_m2
    )
    mesh_raw["fields"]["surface_tension_n_m"] = _array(
        "float64", [len(surface.faces)], sigma
    )

    mean_sigma = math.fsum(sigma) / len(sigma)
    film = copy.deepcopy(dict(film_region))
    film["surface_tension_n_m"] = mean_sigma
    film["thickness"] = {
        "representation": "FACE_FIELD",
        "field": "film_thickness_m",
        "units": "m",
        "fidelity": "MODELED",
    }

    by_id = {state.id: state for state in gas_states}
    bubbles: list[dict[str, Any]] = []
    for source in scenario["initial_bubbles"]:
        state = by_id[str(source["id"])]
        bubble = copy.deepcopy(dict(source))
        bubble["pressure_pa"] = state.pressure_pa
        bubble["temperature_k"] = state.temperature_k
        bubble["gas_amount_mol"] = state.amount_mol
        bubbles.append(bubble)

    pressure_a = by_id[pair.region_a].pressure_pa
    pressure_b = by_id[pair.region_b].pressure_pa
    if pressure_a > pressure_b:
        direction: dict[str, Any] = {"from": pair.region_a, "to": pair.region_b}
    elif pressure_b > pressure_a:
        direction = {"from": pair.region_b, "to": pair.region_a}
    else:
        direction = {"from": None, "to": None}
    total = math.fsum(state.amount_mol for state in gas_states)
    gas_diag: dict[str, Any] = {
        "gas_total_mol": total,
        "gas_total_relative_drift": abs(total - initial_total_mol)
        / max(abs(initial_total_mol), 1.0e-300),
        "gas_amounts_mol": {state.id: state.amount_mol for state in gas_states},
        "pressures_pa": {state.id: state.pressure_pa for state in gas_states},
        "cumulative_transfer_a_to_b_mol": cumulative_transfer_a_to_b_mol,
        "coarsening_direction": direction,
        "geometry_evolution": "fixed in this integration slice",
        "liquid_amount_m3": film_state.liquid_amount_m3(),
        "surfactant_amount_mol": film_state.surfactant_amount_mol(),
        "min_thickness_m": min(film_state.thickness_m),
        "max_thickness_m": max(film_state.thickness_m),
    }
    if last_gas_step is not None:
        gas_diag["step"] = asdict(last_gas_step)

    return {
        "contract_version": "1.0.0",
        "kind": "FRAME",
        "frame_id": f"thinfilm-{frame_index:06d}",
        "simulation_time_s": time_s,
        "manifest": {
            "contract_version": "1.0.0",
            "units": {
                "system": "SI",
                "length": "m",
                "time": "s",
                "mass": "kg",
                "pressure": "Pa",
                "temperature": "K",
                "amount": "mol",
            },
            "solver": {
                "backend": "bubblelab-thinfilm-runtime",
                "version": "1",
                "adapter": "fixed-shared-film/pairwise-ideal-gas-diffusion",
            },
            "fidelity_tier": "HIGH_FIDELITY",
            "feature_disclosures": {
                "film_thickness": "MODELED",
                "film_drainage": "NOT_IMPLEMENTED",
                "surfactant_transport": "NOT_IMPLEMENTED",
                "surface_tension": "MODELED",
                "shared_film_topology": "MODELED",
                "gas_diffusion": "MODELED",
                "coarsening": "MODELED",
                "geometry_evolution": "NOT_IMPLEMENTED",
                "topology_change": "NOT_IMPLEMENTED",
                "coalescence": "NOT_IMPLEMENTED",
                "rupture": "NOT_IMPLEMENTED",
            },
            "random_seed": int(scenario["random_seed"]),
            "provenance": {
                "producer": "bubblelab.runtime.thinfilm_runtime",
                "source_scenario": scenario["scenario_id"],
                "tolerances": {"gas_conservation_relative": 1.0e-12},
            },
        },
        "environment": copy.deepcopy(scenario["environment"]),
        "bubbles": bubbles,
        "surface_meshes": [mesh_raw],
        "film_regions": [film],
        "junctions": [],
        "topology": {
            "adjacency": [
                {
                    "a": str(film["adjacent"][0]),
                    "b": str(film["adjacent"][1]),
                    "film_id": str(film["id"]),
                }
            ],
            "events": [],
        },
        "diagnostics": {
            "timestep_s": cadence_s,
            "thinfilm": gas_diag,
        },
        "thinfilm_runtime": {
            "operator": "accepted pairwise gas diffusion on a fixed shared film",
            "geometry_limitation": (
                "bubble and shared-film geometry are held fixed while gas amounts "
                "and pressures evolve; no topology changes are performed"
            ),
        },
    }


def run_pairwise_gas_frames(
    scenario: Mapping[str, Any],
    frames: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if frames < 1:
        raise ValueError("--frames must be >= 1")
    config = thinfilm_config(scenario)
    if config is None:
        raise ValueError("thinfilm backend requires user_editable.thinfilm")
    flags = feature_flags(config)
    if not flags["gas_diffusion"]:
        raise ValueError("thinfilm backend requires enable_gas_diffusion=true")
    if flags["drainage"] or flags["surfactant_diffusion"]:
        raise ValueError(
            "standalone thinfilm gas-diffusion mode does not advance drainage or surfactant diffusion"
        )
    bubbles = scenario["initial_bubbles"]
    if len(bubbles) != 2:
        raise ValueError("thinfilm gas-diffusion mode requires exactly two bubbles")
    if scenario.get("initial_junctions"):
        raise ValueError("multi-junction transport is not supported by thinfilm gas-diffusion mode")
    for bubble in bubbles:
        _validate_radius_volume(bubble)

    surface, film_region = _shared_surface(scenario)
    params = surface_parameters(scenario, config)
    h = _field_values(
        config.get("initial_thickness_m", 8.0e-6),
        len(surface.faces),
        "initial_thickness_m",
    )
    gamma = _field_values(
        config.get("initial_surfactant_mol_m2", 0.0),
        len(surface.faces),
        "initial_surfactant_mol_m2",
    )
    film_state = SurfaceTransportState(surface, h, gamma, parameters=params)

    gas_states: list[GasRegionState] = []
    for bubble in bubbles:
        amount = bubble.get("gas_amount_mol")
        if amount is None:
            raise ValueError("two-bubble gas diffusion requires gas_amount_mol on each bubble")
        temperature = bubble.get("temperature_k")
        gas_states.append(
            GasRegionState(
                id=str(bubble["id"]),
                volume_m3=float(bubble["volume_m3"]),
                amount_mol=float(amount),
                temperature_k=298.15 if temperature is None else float(temperature),
            )
        )
    by_id = {state.id: state for state in gas_states}
    adjacent = [str(value) for value in film_region["adjacent"]]
    area = math.fsum(surface.face_areas_m2())
    mean_thickness = film_state.liquid_amount_m3() / area
    pair = GasTransferPair(
        adjacent[0],
        adjacent[1],
        shared_area_m2=area,
        film_thickness_m=mean_thickness,
        permeability_mol_m_per_m2_s_pa=_positive_float(
            config,
            "gas_permeability_mol_m_per_m2_s_pa",
            1.0e-16,
            allow_zero=True,
        ),
        positivity_safety=_positive_float(config, "positivity_safety", 0.45),
        max_substeps=_positive_int(config, "max_substeps", 10000),
    )
    cadence = output_cadence_s(scenario)
    if cadence is None:
        raise ValueError(
            "thinfilm gas-diffusion mode requires user_editable.runtime.output_cadence_s"
        )

    initial_total = math.fsum(state.amount_mol for state in gas_states)
    output: list[dict[str, Any]] = []
    cumulative = 0.0
    last = None
    for index in range(frames):
        if index > 0:
            last = pair.advance(
                by_id[pair.region_a],
                by_id[pair.region_b],
                cadence,
            )
            cumulative += last.amount_transferred_a_to_b_mol
        output.append(
            _gas_frame(
                scenario,
                surface,
                film_region,
                film_state,
                gas_states,
                frame_index=index,
                time_s=index * cadence,
                cadence_s=cadence,
                initial_total_mol=initial_total,
                cumulative_transfer_a_to_b_mol=cumulative,
                last_gas_step=last,
                pair=pair,
            )
        )
    return output, {
        "identity": "bubblelab-thinfilm-runtime",
        "version": "1",
        "mode": "fixed-shared-film pairwise gas diffusion/coarsening",
    }
