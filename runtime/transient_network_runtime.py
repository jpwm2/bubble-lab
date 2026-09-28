"""Canonical runtime adapter for the accepted transient shared-film network solver."""
from __future__ import annotations

import math
from typing import Any, Mapping

from bubblelab.solvers.equilibrium.network import EXTERIOR, junction_geometry_diagnostics
from bubblelab.solvers.equilibrium.plateau_benchmarks import plateau_three_result
from bubblelab.solvers.equilibrium.shared_benchmarks import unequal_pressure_result
from bubblelab.solvers.transient.network.core import (
    ConstantForcing,
    NetworkStepperSettings,
    TransientNetworkState,
    advance,
    diagnostics,
)

VERSION = "0.1.0"
SHARED_INITIALIZER = "accepted-b05-unequal-pressure"
PLATEAU_INITIALIZER = "accepted-b06-plateau-three"


class TransientNetworkRuntimeConfigurationError(ValueError):
    """Raised when a canonical scenario cannot map exactly to the network solver."""


def _array(values: list[Any], dtype: str, shape: list[int]) -> dict[str, Any]:
    return {"storage": "INLINE", "dtype": dtype, "shape": shape, "values": values}


def _features(scenario: Mapping[str, Any]) -> dict[str, Any]:
    features: dict[str, Any] = {}
    requested = scenario.get("requested_solver") or {}
    editable = scenario.get("user_editable") or {}
    if isinstance(requested, Mapping) and isinstance(requested.get("features"), Mapping):
        features.update(requested["features"])
    if isinstance(editable, Mapping) and isinstance(editable.get("features"), Mapping):
        features.update(editable["features"])
    return features


def _config(scenario: Mapping[str, Any]) -> Mapping[str, Any]:
    editable = scenario.get("user_editable") or {}
    config = editable.get("transient_network") if isinstance(editable, Mapping) else None
    if not isinstance(config, Mapping):
        raise TransientNetworkRuntimeConfigurationError(
            "transient-network backend requires user_editable.transient_network"
        )
    return config


def _initializer(scenario: Mapping[str, Any]) -> str:
    initializer = _config(scenario).get("initializer")
    if initializer not in (SHARED_INITIALIZER, PLATEAU_INITIALIZER):
        raise TransientNetworkRuntimeConfigurationError(
            "unsupported transient network initializer: " + repr(initializer)
        )
    return str(initializer)


def _require_unique(items: list[Mapping[str, Any]], label: str) -> None:
    ids = [str(item["id"]) for item in items]
    if len(ids) != len(set(ids)):
        raise TransientNetworkRuntimeConfigurationError(f"duplicate {label} ID")


def _validate_declared_network(scenario: Mapping[str, Any], network: Any) -> None:
    if scenario.get("requested_fidelity_tier") != "HIGH_FIDELITY":
        raise TransientNetworkRuntimeConfigurationError(
            "transient-network backend requires HIGH_FIDELITY"
        )
    if scenario.get("initial_surface_meshes"):
        raise TransientNetworkRuntimeConfigurationError(
            "accepted transient network initializers own their triangulated solver mesh; "
            "initial_surface_meshes is unsupported"
        )

    bubbles = list(scenario.get("initial_bubbles") or [])
    films = list(scenario.get("initial_film_regions") or [])
    junctions = list(scenario.get("initial_junctions") or [])
    if not bubbles or not films:
        raise TransientNetworkRuntimeConfigurationError(
            "transient-network backend requires initial_bubbles and initial_film_regions"
        )
    _require_unique(bubbles, "bubble")
    _require_unique(films, "film")
    _require_unique(junctions, "junction")

    expected_regions = tuple(region.id for region in network.regions)
    actual_regions = tuple(str(item["id"]) for item in bubbles)
    if actual_regions != expected_regions:
        raise TransientNetworkRuntimeConfigurationError(
            f"bubble IDs/order {actual_regions!r} do not match accepted initializer {expected_regions!r}"
        )

    expected_films = tuple(patch.id for patch in network.patches)
    actual_films = tuple(str(item["id"]) for item in films)
    if actual_films != expected_films:
        raise TransientNetworkRuntimeConfigurationError(
            f"film IDs/order {actual_films!r} do not match accepted initializer {expected_films!r}"
        )

    expected_junctions = tuple(junction.id for junction in network.junctions)
    actual_junctions = tuple(str(item["id"]) for item in junctions)
    if actual_junctions != expected_junctions:
        raise TransientNetworkRuntimeConfigurationError(
            f"junction IDs/order {actual_junctions!r} do not match accepted initializer {expected_junctions!r}"
        )

    region_by_id = {region.id: region for region in network.regions}
    patch_by_id = {patch.id: patch for patch in network.patches}
    junction_by_id = {junction.id: junction for junction in network.junctions}

    for bubble in bubbles:
        bubble_id = str(bubble["id"])
        target = float(region_by_id[bubble_id].target_volume_m3)
        declared = float(bubble["volume_m3"])
        if not math.isclose(declared, target, rel_tol=1.0e-12, abs_tol=1.0e-18):
            raise TransientNetworkRuntimeConfigurationError(
                f"bubble {bubble_id} target volume does not match accepted initializer"
            )
        radius = float(bubble["equivalent_radius_m"])
        expected_volume = 4.0 * math.pi * radius ** 3 / 3.0
        if abs(declared - expected_volume) / max(declared, expected_volume) > 1.0e-6:
            raise TransientNetworkRuntimeConfigurationError(
                f"equivalent_radius_m and volume_m3 are inconsistent for {bubble_id}"
            )
        if any(abs(float(value)) > 0.0 for value in bubble["velocity_m_s"]):
            raise TransientNetworkRuntimeConfigurationError(
                "transient-network backend does not support independent initial bubble velocity; "
                "use environment.wind"
            )

    for film in films:
        film_id = str(film["id"])
        patch = patch_by_id[film_id]
        adjacent = tuple(str(value) for value in film["adjacent"])
        if adjacent != tuple(patch.adjacent):
            raise TransientNetworkRuntimeConfigurationError(
                f"film {film_id} adjacency/order {adjacent!r} does not match accepted initializer {patch.adjacent!r}"
            )
        expected_kind = "SHARED" if EXTERIOR not in patch.adjacent else "OUTER"
        if str(film["kind"]) != expected_kind:
            raise TransientNetworkRuntimeConfigurationError(
                f"film {film_id} kind does not match accepted initializer"
            )
        if not math.isclose(
            float(film["surface_tension_n_m"]),
            float(patch.sheet_tension_n_m),
            rel_tol=1.0e-12,
            abs_tol=1.0e-15,
        ):
            raise TransientNetworkRuntimeConfigurationError(
                f"film {film_id} tension does not match accepted initializer"
            )

    for item in junctions:
        junction_id = str(item["id"])
        solved = junction_by_id[junction_id]
        incident = tuple(str(value) for value in item["incident_film_ids"])
        if incident != tuple(solved.incident_film_ids):
            raise TransientNetworkRuntimeConfigurationError(
                f"junction {junction_id} incident film order does not match accepted initializer"
            )

    features = _features(scenario)
    if not bool(features.get("shared_films") or features.get("shared_film_topology")):
        raise TransientNetworkRuntimeConfigurationError(
            "transient-network backend requires explicit shared_films feature disclosure"
        )
    if network.junctions and not bool(features.get("plateau_junctions")):
        raise TransientNetworkRuntimeConfigurationError(
            "Plateau initializer requires plateau_junctions feature disclosure"
        )
    if not network.junctions and bool(features.get("plateau_junctions")):
        raise TransientNetworkRuntimeConfigurationError(
            "two-bubble shared-film initializer cannot request plateau_junctions"
        )

    unsupported = (
        "automatic_contact_detection",
        "transient_contact_detection",
        "dynamic_shared_films",
        "t1",
        "t1_topology_surgery",
        "rupture",
        "coalescence",
        "drainage",
        "surfactant_diffusion",
        "variable_surface_tension",
        "gas_diffusion",
        "coarsening",
        "fully_coupled_multi_region_eulerian_cfd",
    )
    bad = sorted(name for name in unsupported if bool(features.get(name)))
    if bad:
        raise TransientNetworkRuntimeConfigurationError(
            "unsupported transient-network feature(s): " + ", ".join(bad)
        )


def _settings(scenario: Mapping[str, Any]) -> NetworkStepperSettings:
    config = _config(scenario)
    settings = NetworkStepperSettings(
        dt_s=float(config.get("dt_s", 2.0e-4)),
        mobility_m_per_n_s=float(config.get("mobility_m_per_n_s", 1.0e-2)),
        max_displacement_edge_fraction=float(
            config.get("max_displacement_edge_fraction", 0.025)
        ),
        volume_relative_tolerance=float(
            config.get("volume_relative_tolerance", 2.0e-10)
        ),
        volume_projection_iterations=int(
            config.get("volume_projection_iterations", 20)
        ),
        max_backtracks=int(config.get("max_backtracks", 18)),
        energy_roundoff_relative=float(
            config.get("energy_roundoff_relative", 2.0e-12)
        ),
    )
    settings.validate()
    return settings


def _forcing(scenario: Mapping[str, Any]) -> ConstantForcing | None:
    environment = scenario.get("environment") or {}
    wind = environment.get("wind") or {}
    velocity = tuple(float(value) for value in (wind.get("velocity_m_s") or (0.0, 0.0, 0.0)))
    gravity = tuple(float(value) for value in (environment.get("gravity_m_s2") or (0.0, 0.0, 0.0)))
    response = float(_config(scenario).get("acceleration_response_time_s", 0.0))
    if len(velocity) != 3 or len(gravity) != 3:
        raise TransientNetworkRuntimeConfigurationError(
            "environment wind and gravity vectors must have length three"
        )
    if not any(abs(value) > 0.0 for value in (*velocity, *gravity)):
        return None
    return ConstantForcing(
        velocity_m_s=velocity,
        acceleration_m_s2=gravity,
        response_time_s=response,
    )


def _initializer_network(scenario: Mapping[str, Any]) -> Any:
    initializer = _initializer(scenario)
    result = unequal_pressure_result() if initializer == SHARED_INITIALIZER else plateau_three_result()
    _validate_declared_network(scenario, result.network)
    return result.network


def _junction_records(network: Any) -> list[dict[str, Any]]:
    patch_by_id = {patch.id: patch for patch in network.patches}
    records = []
    for junction in network.junctions:
        diag = junction_geometry_diagnostics(network, junction.id)
        indices = junction.vertex_indices_by_film[0]
        vertices = patch_by_id[junction.incident_film_ids[0]].mesh.vertices
        geometry = [list(vertices[index]) for index in indices]
        angle_rows = diag["pairwise_angles_deg"]
        measured_angles = [
            sum(row[pair] for row in angle_rows) / len(angle_rows)
            for pair in range(3)
        ]
        records.append({
            "id": junction.id,
            "incident_film_ids": list(junction.incident_film_ids),
            "geometry": _array(geometry, "float64", [len(geometry), 3]),
            "measured_angles_deg": measured_angles,
            "measurement_provenance": {
                "producer": "bubblelab.solvers.equilibrium.network.junction_geometry_diagnostics",
                "method": diag["measurement"],
                "junction_force_residual": float(diag["max_force_residual"]),
                "geometry_source": "authoritative transient shared-DOF network",
            },
        })
    return records


def _frame(
    scenario: Mapping[str, Any],
    state: TransientNetworkState,
    step_diag: Any,
    settings: NetworkStepperSettings,
    frame_index: int,
    previous_centroids: Mapping[str, tuple[float, float, float]] | None,
) -> tuple[dict[str, Any], dict[str, tuple[float, float, float]]]:
    network = state.to_network()
    environment = scenario["environment"]
    ambient_pressure = float(environment.get("ambient_pressure_pa", 101325.0))
    pressure_by_id = dict(step_diag.pressures_pa)

    surface_meshes = []
    film_regions = []
    adjacency = []
    for patch in network.patches:
        mesh = patch.mesh
        shared = EXTERIOR not in patch.adjacent
        surface_meshes.append({
            "id": f"mesh-{patch.id}",
            "geometry_role": "SHARED_FILM" if shared else "OUTER_FILM",
            "owner_bubble_ids": [value for value in patch.adjacent if value != EXTERIOR],
            "region_labels": list(patch.adjacent),
            "vertex_count": len(mesh.vertices),
            "face_count": len(mesh.faces),
            "vertices": _array(
                [[x, y, z] for x, y, z in mesh.vertices],
                "float64",
                [len(mesh.vertices), 3],
            ),
            "faces": _array(
                [[a, b, c] for a, b, c in mesh.faces],
                "uint32",
                [len(mesh.faces), 3],
            ),
            "fields": {
                "face_normals": _array(
                    [[x, y, z] for x, y, z in mesh.face_normals()],
                    "float64",
                    [len(mesh.faces), 3],
                )
            },
        })
        film_regions.append({
            "id": patch.id,
            "kind": "SHARED" if shared else "OUTER",
            "adjacent": list(patch.adjacent),
            "surface_tension_n_m": patch.sheet_tension_n_m,
            "mesh_id": f"mesh-{patch.id}",
        })
        adjacency.append({
            "a": patch.adjacent[0],
            "b": patch.adjacent[1],
            "film_id": patch.id,
        })

    centroids = {
        region.id: tuple(float(value) for value in network.region_centroid(region.id))
        for region in network.regions
    }
    bubbles = []
    for region in network.regions:
        volume = float(network.region_volume(region.id))
        centroid = centroids[region.id]
        if previous_centroids is None:
            velocity = (0.0, 0.0, 0.0)
        else:
            before = previous_centroids[region.id]
            velocity = tuple((after - prior) / settings.dt_s for after, prior in zip(centroid, before))
        tensions = sorted({
            patch.sheet_tension_n_m
            for patch in network.patches
            if region.id in patch.adjacent
        })
        bubbles.append({
            "id": region.id,
            "volume_m3": volume,
            "equivalent_radius_m": (3.0 * volume / (4.0 * math.pi)) ** (1.0 / 3.0),
            "centroid_m": list(centroid),
            "velocity_m_s": list(velocity),
            "status": "ALIVE",
            "pressure_pa": ambient_pressure + float(pressure_by_id[region.id]),
            "film_material": {
                "effective_sheet_tension_n_m": tensions[0] if len(tensions) == 1 else None,
                "tension_convention": "effective_collapsed_soap_film_sheet",
            },
        })

    residuals = {
        f"relative_volume_{region_id}": float(value)
        for region_id, value in step_diag.relative_volume_errors
    }
    residuals["junction_force_max"] = float(step_diag.max_junction_force_residual)
    for region_id, value in step_diag.pressures_pa:
        residuals[f"pressure_jump_{region_id}_pa"] = float(value)

    feature_disclosures = {
        "surface_energy": "RESOLVED",
        "prescribed_volume": "RESOLVED",
        "young_laplace_pressure": "MODELED",
        "triangulated_geometry": "RESOLVED",
        "shared_films": "RESOLVED",
        "plateau_junctions": "RESOLVED" if network.junctions else "NOT_IMPLEMENTED",
        "transient_flow": "MODELED",
        "network_forcing": "MODELED",
        "fully_coupled_multi_region_eulerian_cfd": "NOT_IMPLEMENTED",
        "automatic_contact_detection": "NOT_IMPLEMENTED",
        "t1_topology_surgery": "NOT_IMPLEMENTED",
        "film_thickness": "NOT_IMPLEMENTED",
        "drainage": "NOT_IMPLEMENTED",
        "gas_diffusion": "NOT_IMPLEMENTED",
        "coalescence": "NOT_IMPLEMENTED",
        "rupture": "NOT_IMPLEMENTED",
    }

    frame = {
        "contract_version": "1.0.0",
        "kind": "FRAME",
        "frame_id": f"transient-network-{frame_index:06d}",
        "simulation_time_s": float(state.time_s),
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
                "backend": "bubblelab-transient-network",
                "version": VERSION,
                "adapter": "bubblelab.runtime/transient-network",
            },
            "fidelity_tier": "HIGH_FIDELITY",
            "feature_disclosures": feature_disclosures,
            "random_seed": int(scenario["random_seed"]),
            "provenance": {
                "producer": "bubblelab.runtime.transient_network_runtime",
                "source_scenario": scenario["scenario_id"],
                "created_at": None,
                "tolerances": {
                    "relative_volume": settings.volume_relative_tolerance,
                    "max_displacement_edge_fraction": settings.max_displacement_edge_fraction,
                },
                "model_class": "reduced-order overdamped shared-DOF transient film network",
            },
        },
        "environment": {
            key: value
            for key, value in environment.items()
            if key in (
                "gravity_m_s2",
                "ambient_density_kg_m3",
                "ambient_dynamic_viscosity_pa_s",
                "ambient_pressure_pa",
                "wind",
                "flow_metadata",
            )
        },
        "bubbles": bubbles,
        "surface_meshes": surface_meshes,
        "film_regions": film_regions,
        "junctions": _junction_records(network),
        "topology": {"adjacency": adjacency, "events": []},
        "diagnostics": {
            "timestep_s": settings.dt_s,
            "residuals": residuals,
            "max_relative_volume_error": max(
                (float(value) for _, value in step_diag.relative_volume_errors),
                default=0.0,
            ),
            "surface_energy_j": float(step_diag.surface_energy_j),
            "junction_force_residual": float(step_diag.max_junction_force_residual),
            "accepted_scale": float(step_diag.accepted_scale),
            "max_displacement_m": float(step_diag.max_displacement_m),
            "step_index": int(state.step_index),
            "shared_dof_count": int(state.shared_dof_count()),
            "region_ids": list(state.topology.region_ids),
            "film_ids": list(state.topology.film_ids),
            "junction_ids": list(state.topology.junction_ids),
        },
    }
    return frame, centroids


def run_transient_network(
    scenario: Mapping[str, Any],
    frames: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Advance a canonical pre-existing film network through physical timesteps."""
    if frames < 1:
        raise ValueError("--frames must be >= 1")
    network = _initializer_network(scenario)
    settings = _settings(scenario)
    forcing = _forcing(scenario)
    state = TransientNetworkState.from_network(network)
    topology_signature = state.topology_signature()

    initial_diag = diagnostics(state)
    first, centroids = _frame(
        scenario,
        state,
        initial_diag,
        settings,
        0,
        previous_centroids=None,
    )
    output = [first]
    for index in range(1, frames):
        state, step_diag = advance(state, settings=settings, forcing=forcing)
        if state.topology_signature() != topology_signature:
            raise RuntimeError("transient network topology changed without an explicit topology event")
        frame, centroids = _frame(
            scenario,
            state,
            step_diag,
            settings,
            index,
            previous_centroids=centroids,
        )
        output.append(frame)

    return output, {
        "identity": "bubblelab-transient-network",
        "version": VERSION,
        "network_initializer": _initializer(scenario),
        "model_class": "reduced-order overdamped shared-DOF transient film network",
        "timestep_s": settings.dt_s,
        "shared_dof_count": state.shared_dof_count(),
        "topology_events": "none; pre-existing topology is preserved",
        "fully_coupled_multi_region_eulerian_cfd": False,
    }
