"""Canonical runtime for the supported two-front contact-formation transition."""
from __future__ import annotations

from dataclasses import replace
import math
from typing import Any, Mapping

from bubblelab.solvers.transient import (
    GridConfig,
    RegionProperties,
    TimeStepPolicy,
    TransientConfig,
    TransientSoapFilmSolver,
    frame_dict as transient_frame,
)
from bubblelab.solvers.transient.contact import (
    ContactFormationError,
    ContactObservation,
    ContactSettings,
    form_contact,
    observe_contact,
)
from bubblelab.solvers.transient.geometry import FilmFront, icosphere
from bubblelab.solvers.transient.network.core import (
    ConstantForcing,
    NetworkStepperSettings,
    advance as advance_network,
    diagnostics as network_diagnostics,
)
from bubblelab.runtime.transient_network_runtime import _frame as transient_network_frame

VERSION = "0.1.0"
BACKEND_ID = "bubblelab-contact-runtime"


class ContactRuntimeConfigurationError(ValueError):
    """Raised when a scenario lies outside the supported two-bubble transition slice."""


def _config(scenario: Mapping[str, Any]) -> Mapping[str, Any]:
    editable = scenario.get("user_editable") or {}
    config = editable.get("contact_runtime") if isinstance(editable, Mapping) else None
    if not isinstance(config, Mapping):
        raise ContactRuntimeConfigurationError(
            "contact-transition backend requires user_editable.contact_runtime"
        )
    return config


def _features(scenario: Mapping[str, Any]) -> dict[str, Any]:
    features: dict[str, Any] = {}
    requested = scenario.get("requested_solver") or {}
    editable = scenario.get("user_editable") or {}
    if isinstance(requested, Mapping) and isinstance(requested.get("features"), Mapping):
        features.update(requested["features"])
    if isinstance(editable, Mapping) and isinstance(editable.get("features"), Mapping):
        features.update(editable["features"])
    return features


def _tension(bubble: Mapping[str, Any]) -> float:
    material = bubble.get("film_material") or {}
    if not isinstance(material, Mapping):
        raise ContactRuntimeConfigurationError("bubble film_material must be an object")
    for key in ("effective_sheet_tension_n_m", "surface_tension_n_m"):
        if key in material:
            value = float(material[key])
            if value <= 0.0:
                raise ContactRuntimeConfigurationError("surface tension must be positive")
            return value
    raise ContactRuntimeConfigurationError(
        "film_material.effective_sheet_tension_n_m is required"
    )


def _validate_scenario(scenario: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    if scenario.get("requested_fidelity_tier") not in ("HIGH_FIDELITY", "MAXIMUM_REALISM"):
        raise ContactRuntimeConfigurationError(
            "contact-transition backend requires HIGH_FIDELITY or MAXIMUM_REALISM"
        )
    if scenario.get("initial_surface_meshes") or scenario.get("initial_film_regions") or scenario.get("initial_junctions"):
        raise ContactRuntimeConfigurationError(
            "contact-transition starts from exactly two independent closed fronts; "
            "pre-existing surface meshes, shared films, or junctions are unsupported"
        )
    if (scenario.get("environment") or {}).get("boundary_refs"):
        raise ContactRuntimeConfigurationError(
            "solid-boundary contact is outside the supported two-bubble transition slice"
        )

    bubbles = list(scenario.get("initial_bubbles") or [])
    if len(bubbles) != 2:
        raise ContactRuntimeConfigurationError(
            "contact-transition supports exactly two independent bubbles"
        )
    ids = [str(item["id"]) for item in bubbles]
    if len(set(ids)) != 2:
        raise ContactRuntimeConfigurationError("contact parents require distinct bubble IDs")
    for bubble in bubbles:
        velocity = tuple(float(value) for value in bubble["velocity_m_s"])
        if any(abs(value) > 0.0 for value in velocity):
            raise ContactRuntimeConfigurationError(
                "independent scripted bubble velocity is unsupported; use contact_runtime.initial_flow"
            )
        radius = float(bubble["equivalent_radius_m"])
        volume = float(bubble["volume_m3"])
        expected = 4.0 * math.pi * radius ** 3 / 3.0
        if abs(volume - expected) / max(volume, expected) > 1.0e-6:
            raise ContactRuntimeConfigurationError(
                f"equivalent_radius_m and volume_m3 are inconsistent for {bubble['id']}"
            )

    tensions = [_tension(item) for item in bubbles]
    if not math.isclose(tensions[0], tensions[1], rel_tol=1.0e-12, abs_tol=1.0e-15):
        raise ContactRuntimeConfigurationError(
            "supported contact formation requires matching parent sheet tensions"
        )

    features = _features(scenario)
    if not bool(features.get("automatic_contact_detection")):
        raise ContactRuntimeConfigurationError(
            "contact-transition requires automatic_contact_detection feature disclosure"
        )
    if not bool(features.get("shared_films") or features.get("shared_film_topology")):
        raise ContactRuntimeConfigurationError(
            "contact-transition requires shared_films/shared_film_topology feature disclosure"
        )
    if not bool(features.get("topology_change")):
        raise ContactRuntimeConfigurationError(
            "contact-transition requires topology_change feature disclosure"
        )

    unsupported = (
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
        raise ContactRuntimeConfigurationError(
            "unsupported contact-transition feature(s): " + ", ".join(bad)
        )
    return bubbles[0], bubbles[1]


def _contact_settings(config: Mapping[str, Any]) -> ContactSettings:
    raw = config.get("contact") or {}
    if not isinstance(raw, Mapping):
        raise ContactRuntimeConfigurationError("contact_runtime.contact must be an object")
    settings = ContactSettings(
        threshold_edge_fraction=float(raw.get("threshold_edge_fraction", 0.45)),
        max_interpenetration_edge_fraction=float(
            raw.get("max_interpenetration_edge_fraction", 0.35)
        ),
        projection_relative_tolerance=float(
            raw.get("projection_relative_tolerance", 5.0e-10)
        ),
        projection_iterations=int(raw.get("projection_iterations", 24)),
        local_volume_budget_fraction=float(
            raw.get("local_volume_budget_fraction", 0.12)
        ),
        candidate_vertex_limit=int(raw.get("candidate_vertex_limit", 24)),
    )
    settings.validate()
    return settings


def _network_settings(config: Mapping[str, Any]) -> NetworkStepperSettings:
    raw = config.get("network") or {}
    if not isinstance(raw, Mapping):
        raise ContactRuntimeConfigurationError("contact_runtime.network must be an object")
    settings = NetworkStepperSettings(
        dt_s=float(raw.get("dt_s", 2.0e-4)),
        mobility_m_per_n_s=float(raw.get("mobility_m_per_n_s", 2.0e-2)),
        max_displacement_edge_fraction=float(
            raw.get("max_displacement_edge_fraction", 0.025)
        ),
        volume_relative_tolerance=float(raw.get("volume_relative_tolerance", 2.0e-10)),
        volume_projection_iterations=int(raw.get("volume_projection_iterations", 20)),
        max_backtracks=int(raw.get("max_backtracks", 18)),
        energy_roundoff_relative=float(raw.get("energy_roundoff_relative", 2.0e-12)),
    )
    settings.validate()
    return settings


def _region_properties(
    config: Mapping[str, Any],
    bubble_ids: tuple[str, str],
    ambient_density: float,
    ambient_viscosity: float,
) -> dict[str, RegionProperties]:
    raw = config.get("region_properties") or {}
    if not isinstance(raw, Mapping):
        raise ContactRuntimeConfigurationError(
            "contact_runtime.region_properties must be an object"
        )
    unknown = set(str(key) for key in raw) - set(bubble_ids)
    if unknown:
        raise ContactRuntimeConfigurationError(
            "region_properties references unknown bubble IDs: " + ", ".join(sorted(unknown))
        )
    result: dict[str, RegionProperties] = {}
    for bubble_id in bubble_ids:
        item = raw.get(bubble_id) or {}
        if not isinstance(item, Mapping):
            raise ContactRuntimeConfigurationError(
                f"region_properties.{bubble_id} must be an object"
            )
        result[bubble_id] = RegionProperties(
            density_kg_m3=float(item.get("density_kg_m3", ambient_density)),
            dynamic_viscosity_pa_s=float(
                item.get("dynamic_viscosity_pa_s", ambient_viscosity)
            ),
        )
    return result


def _build_solver(
    scenario: Mapping[str, Any],
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> tuple[TransientSoapFilmSolver, ContactSettings, NetworkStepperSettings]:
    config = _config(scenario)
    subdivisions = int(config.get("subdivisions", 2))
    if subdivisions < 1 or subdivisions > 3:
        raise ContactRuntimeConfigurationError(
            "contact_runtime.subdivisions must lie in [1, 3]"
        )
    fronts: list[FilmFront] = []
    for bubble in (first, second):
        fronts.append(
            icosphere(
                radius_m=float(bubble["equivalent_radius_m"]),
                center_m=tuple(float(value) for value in bubble["centroid_m"]),
                subdivisions=subdivisions,
                bubble_id=str(bubble["id"]),
                surface_tension_n_m=_tension(bubble),
            )
        )

    environment = scenario["environment"]
    ambient_density = float(environment["ambient_density_kg_m3"])
    ambient_viscosity = float(environment["ambient_dynamic_viscosity_pa_s"])
    grid_raw = config.get("grid") or {}
    if not isinstance(grid_raw, Mapping):
        raise ContactRuntimeConfigurationError("contact_runtime.grid must be an object")
    cells_raw = tuple(int(value) for value in grid_raw.get("cells", (10, 10, 10)))
    origin_raw = tuple(float(value) for value in grid_raw.get("origin_m", (-0.03, -0.03, -0.03)))
    extent_raw = tuple(float(value) for value in grid_raw.get("extent_m", (0.06, 0.06, 0.06)))
    if len(cells_raw) != 3 or len(origin_raw) != 3 or len(extent_raw) != 3:
        raise ContactRuntimeConfigurationError("contact runtime grid vectors must have length three")
    wind = tuple(
        float(value)
        for value in ((environment.get("wind") or {}).get("velocity_m_s") or (0.0, 0.0, 0.0))
    )
    if len(wind) != 3:
        raise ContactRuntimeConfigurationError("environment.wind.velocity_m_s must have length three")
    grid = GridConfig(
        cells=cells_raw,
        origin_m=origin_raw,
        extent_m=extent_raw,
        density_kg_m3=ambient_density,
        dynamic_viscosity_pa_s=ambient_viscosity,
        background_velocity_m_s=wind,
        pressure_iterations=int(grid_raw.get("pressure_iterations", 160)),
        pressure_tolerance_s_inv=float(grid_raw.get("pressure_tolerance_s_inv", 2.0e-7)),
    )
    policy = TimeStepPolicy(
        max_dt_s=float(config.get("max_dt_s", 5.0e-4)),
        advective_cfl=float(config.get("advective_cfl", 0.45)),
        viscous_safety=float(config.get("viscous_safety", 0.20)),
        capillary_safety=float(config.get("capillary_safety", 0.20)),
        min_dt_s=float(config.get("min_dt_s", 1.0e-8)),
    )
    region_props = _region_properties(
        config,
        (fronts[0].bubble_id, fronts[1].bubble_id),
        ambient_density,
        ambient_viscosity,
    )
    solver = TransientSoapFilmSolver(
        fronts,
        TransientConfig(
            grid=grid,
            gravity_m_s2=tuple(float(value) for value in environment["gravity_m_s2"]),
            timestep=policy,
            deterministic_seed=int(scenario["random_seed"]),
            region_properties=region_props,
        ),
    )
    _seed_initial_flow(solver, config)
    return solver, _contact_settings(config), _network_settings(config)


def _seed_initial_flow(solver: TransientSoapFilmSolver, config: Mapping[str, Any]) -> None:
    raw = config.get("initial_flow") or {"model": "none"}
    if not isinstance(raw, Mapping):
        raise ContactRuntimeConfigurationError("contact_runtime.initial_flow must be an object")
    model = str(raw.get("model", "none"))
    if model == "none":
        return
    if model != "periodic_divergence_free_contact_strain_z":
        raise ContactRuntimeConfigurationError("unsupported contact_runtime.initial_flow model")
    amplitude = float(raw.get("amplitude_m_s", 0.0))
    if amplitude <= 0.0:
        raise ContactRuntimeConfigurationError("initial contact strain amplitude must be positive")
    grid = solver.grid
    if not hasattr(grid, "u") or not hasattr(grid, "v") or not hasattr(grid, "w"):
        raise ContactRuntimeConfigurationError(
            "supported initial contact strain requires the uniform Eulerian reference grid"
        )
    extent_x = float(grid.config.extent_m[0])
    extent_z = float(grid.config.extent_m[2])
    if not math.isclose(extent_x, extent_z, rel_tol=1.0e-12, abs_tol=1.0e-15):
        raise ContactRuntimeConfigurationError(
            "periodic contact strain requires equal x/z grid extents"
        )
    wave = 2.0 * math.pi / extent_x
    ox, _, oz = grid.config.origin_m
    for q in range(len(grid.u)):
        i, _, k = grid._ijk(q)
        x_center = ox + (i + 0.5) * grid.h
        z_center = oz + (k + 0.5) * grid.h
        x_face = ox + (i + 1.0) * grid.h
        z_face = oz + (k + 1.0) * grid.h
        grid.u[q] = amplitude * math.sin(wave * x_face) * math.cos(wave * z_center)
        grid.v[q] = 0.0
        grid.w[q] = -amplitude * math.cos(wave * x_center) * math.sin(wave * z_face)


def _observation_dict(observation: ContactObservation) -> dict[str, Any]:
    return {
        "parent_ids": list(observation.parent_ids),
        "closest_vertex_indices": list(observation.closest_vertex_indices),
        "closest_surface_locations_m": [list(point) for point in observation.closest_surface_locations_m],
        "nearest_vertex_distance_m": float(observation.nearest_vertex_distance_m),
        "axial_gap_m": float(observation.axial_gap_m),
        "separation_metric_m": float(observation.separation_metric_m),
        "mesh_resolution_m": float(observation.resolution_m),
        "threshold_m": float(observation.threshold_m),
        "contact": bool(observation.contact),
        "anchor_vertex_indices": list(observation.anchor_vertex_indices),
        "contact_ring_seed_indices": [list(values) for values in observation.contact_ring_seed_indices],
        "producer": "bubblelab.solvers.transient.contact.observe_contact",
        "geometry_source": "authoritative triangulated tracked fronts",
    }


def _capability_disclosures(frame: dict[str, Any]) -> None:
    disclosures = frame["manifest"]["feature_disclosures"]
    disclosures.update({
        "automatic_contact_detection": "RESOLVED",
        "transient_contact_detection": "RESOLVED",
        "shared_films": "RESOLVED",
        "shared_film_topology": "RESOLVED",
        "dynamic_shared_films": "RESOLVED",
        "topology_change": "RESOLVED",
        "supported_two_front_contact_surgery": "RESOLVED",
        "pre_contact_lubrication_drainage": "NOT_IMPLEMENTED",
        "t1_topology_surgery": "NOT_IMPLEMENTED",
        "rupture": "NOT_IMPLEMENTED",
        "coalescence": "NOT_IMPLEMENTED",
        "fully_coupled_multi_region_eulerian_cfd": "NOT_IMPLEMENTED",
    })


def _normalize_manifest(frame: dict[str, Any], phase: str) -> None:
    frame["manifest"]["solver"] = {
        "backend": BACKEND_ID,
        "version": VERSION,
        "adapter": "bubblelab.runtime/contact-transition",
    }
    frame["manifest"]["fidelity_tier"] = "HIGH_FIDELITY"
    frame["manifest"]["provenance"].update({
        "producer": "bubblelab.runtime.contact_runtime",
        "model_class": (
            "front-tracked sharp-interface pre-contact"
            if phase == "PRE_CONTACT"
            else "shared-DOF transient film network post-contact"
        ),
        "contact_transition": "supported isolated two-front local surgery",
    })
    _capability_disclosures(frame)


def _pre_frame(
    solver: TransientSoapFilmSolver,
    observation: ContactObservation,
    frame_index: int,
) -> dict[str, Any]:
    frame = transient_frame(solver, f"contact-transition-{frame_index:06d}")
    _normalize_manifest(frame, "PRE_CONTACT")
    frame["topology"]["adjacency"] = [
        {"a": front.bubble_id, "b": "EXTERIOR", "film_id": front.film_id}
        for front in sorted(solver.fronts, key=lambda item: item.bubble_id)
    ]
    frame["topology"]["events"] = []
    frame["diagnostics"]["contact_transition"] = {
        "phase": "PRE_CONTACT",
        "formation_count": 0,
        "observation": _observation_dict(observation),
        "pre_contact_step_index": int(solver.step_index),
    }
    return frame


def _contact_event(
    observation: ContactObservation,
    time_s: float,
    shared_film_id: str,
    junction_id: str,
) -> dict[str, Any]:
    return {
        "id": "contact-formation-000001",
        "type": "FILM_FORMED",
        "transition_kind": "CONTACT_FORMATION",
        "time_s": float(time_s),
        "bubble_ids_before": list(observation.parent_ids),
        "bubble_ids_after": list(observation.parent_ids),
        "film_ids": [shared_film_id],
        "junction_ids": [junction_id],
        "trigger": _observation_dict(observation),
        "provenance": {
            "source": "SOLVER",
            "detail": "mesh-observed first supported contact followed by local shared-film surgery",
            "producer": "bubblelab.solvers.transient.contact.form_contact",
        },
    }


def _post_frame(
    scenario: Mapping[str, Any],
    state: Any,
    step_diag: Any,
    settings: NetworkStepperSettings,
    frame_index: int,
    previous_centroids: Mapping[str, tuple[float, float, float]] | None,
    trigger: ContactObservation,
    event_time_s: float,
    raw_volume_errors: tuple[tuple[str, float], ...],
    projected_volume_errors: tuple[tuple[str, float], ...],
    post_contact_steps: int,
    emit_event: bool,
) -> tuple[dict[str, Any], dict[str, tuple[float, float, float]]]:
    frame, centroids = transient_network_frame(
        scenario,
        state,
        step_diag,
        settings,
        frame_index,
        previous_centroids,
    )
    frame["frame_id"] = f"contact-transition-{frame_index:06d}"
    _normalize_manifest(frame, "POST_CONTACT")
    shared_film_ids = [
        item["id"] for item in frame["film_regions"] if item["kind"] == "SHARED"
    ]
    junction_ids = [item["id"] for item in frame["junctions"]]
    if len(shared_film_ids) != 1 or len(junction_ids) != 1:
        raise RuntimeError("supported contact transition lost its single shared film/contact ring")
    frame["topology"]["events"] = (
        [_contact_event(trigger, event_time_s, shared_film_ids[0], junction_ids[0])]
        if emit_event
        else []
    )
    frame["diagnostics"]["contact_transition"] = {
        "phase": "POST_CONTACT",
        "formation_count": 1,
        "event_time_s": float(event_time_s),
        "trigger": _observation_dict(trigger),
        "post_contact_network_steps": int(post_contact_steps),
        "first_post_transition_geometry": (
            "exact form_contact surgery output before network advance"
            if post_contact_steps == 0
            else "authoritative shared-DOF network evolution"
        ),
        "raw_relative_volume_errors": {
            region_id: float(value) for region_id, value in raw_volume_errors
        },
        "projected_relative_volume_errors": {
            region_id: float(value) for region_id, value in projected_volume_errors
        },
    }
    return frame, centroids


def _network_forcing(
    scenario: Mapping[str, Any],
    config: Mapping[str, Any],
) -> ConstantForcing | None:
    network = config.get("network") or {}
    assert isinstance(network, Mapping)
    environment = scenario["environment"]
    wind = tuple(
        float(value)
        for value in ((environment.get("wind") or {}).get("velocity_m_s") or (0.0, 0.0, 0.0))
    )
    gravity = tuple(float(value) for value in environment.get("gravity_m_s2", (0.0, 0.0, 0.0)))
    response = float(network.get("acceleration_response_time_s", 0.0))
    if not any(abs(value) > 0.0 for value in (*wind, *gravity)):
        return None
    return ConstantForcing(
        velocity_m_s=wind,
        acceleration_m_s2=gravity,
        response_time_s=response,
    )


def run_contact_transition(
    scenario: Mapping[str, Any],
    frames: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run separated fronts through one mesh-observed contact into shared DOFs."""
    if frames < 2:
        raise ContactRuntimeConfigurationError(
            "contact-transition requires at least two frames to show separated and post-contact states"
        )
    first, second = _validate_scenario(scenario)
    config = _config(scenario)
    solver, contact_settings, network_settings = _build_solver(
        scenario,
        first,
        second,
    )
    ordered = sorted(solver.fronts, key=lambda item: item.bubble_id)
    try:
        observation = observe_contact(ordered[0], ordered[1], contact_settings)
    except ContactFormationError as exc:
        raise ContactRuntimeConfigurationError(str(exc)) from exc
    if observation.contact:
        raise ContactRuntimeConfigurationError(
            "contact-transition initial condition must begin with two separated fronts"
        )

    output = [_pre_frame(solver, observation, 0)]
    transition = None
    network_state = None
    network_centroids = None
    trigger = None
    event_time_s = None
    post_steps = 0
    forcing = _network_forcing(scenario, config)

    for frame_index in range(1, frames):
        if network_state is None:
            solver.step()
            ordered = sorted(solver.fronts, key=lambda item: item.bubble_id)
            try:
                observation = observe_contact(ordered[0], ordered[1], contact_settings)
            except ContactFormationError as exc:
                raise ContactRuntimeConfigurationError(str(exc)) from exc
            if not observation.contact:
                output.append(_pre_frame(solver, observation, frame_index))
                continue

            transition = form_contact(ordered[0], ordered[1], contact_settings)
            trigger = transition.observation
            event_time_s = float(solver.time_s)
            network_state = replace(
                transition.state,
                time_s=event_time_s,
                step_index=solver.step_index,
            )
            diag = network_diagnostics(network_state)
            frame, network_centroids = _post_frame(
                scenario,
                network_state,
                diag,
                network_settings,
                frame_index,
                None,
                trigger,
                event_time_s,
                transition.raw_relative_volume_errors,
                transition.projected_relative_volume_errors,
                post_steps,
                True,
            )
            output.append(frame)
            continue

        assert transition is not None and trigger is not None and event_time_s is not None
        network_state, diag = advance_network(
            network_state,
            settings=network_settings,
            forcing=forcing,
        )
        post_steps += 1
        frame, network_centroids = _post_frame(
            scenario,
            network_state,
            diag,
            network_settings,
            frame_index,
            network_centroids,
            trigger,
            event_time_s,
            transition.raw_relative_volume_errors,
            transition.projected_relative_volume_errors,
            post_steps,
            False,
        )
        output.append(frame)

    if network_state is None or transition is None or trigger is None or event_time_s is None:
        raise ContactRuntimeConfigurationError(
            "supported contact was not reached within the requested physical frames"
        )

    event_count = sum(
        1
        for frame in output
        for event in frame["topology"]["events"]
        if event.get("transition_kind") == "CONTACT_FORMATION"
    )
    if event_count != 1:
        raise RuntimeError("contact-transition replay must contain exactly one contact formation event")

    return output, {
        "identity": BACKEND_ID,
        "version": VERSION,
        "model_class": (
            "front-tracked sharp-interface approach -> local mesh contact surgery -> "
            "shared-DOF transient film network"
        ),
        "pre_contact_solver": {
            "identity": "bubblelab-transient-reference",
            "version": solver.VERSION,
            "geometry": "tracked triangulated FilmFront",
            "contact_observer": "bubblelab.solvers.transient.contact.observe_contact",
        },
        "contact_surgery": "bubblelab.solvers.transient.contact.form_contact",
        "post_contact_solver": "bubblelab.solvers.transient.network.core.advance",
        "post_contact_timestep_s": network_settings.dt_s,
        "contact_event_time_s": event_time_s,
        "contact_events": 1,
        "contract_event_type": "FILM_FORMED",
        "transition_kind": "CONTACT_FORMATION",
        "topology_guarantee": "one shared film and one authoritative shared contact-ring DOF set",
        "unsupported": [
            "general multi-contact/T1",
            "pre-contact lubrication/drainage",
            "rupture/coalescence in this transition slice",
            "fully coupled multi-region Eulerian CFD",
        ],
    }
