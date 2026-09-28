"""Transient continuation from an accepted coalescence restart mesh."""
from __future__ import annotations

import copy
import math
from typing import Any, Mapping

from bubblelab.solvers.events.engine import TopologyTransition
from bubblelab.solvers.transient import (
    FilmFront,
    GridConfig,
    RemeshConfig,
    TransientConfig,
    TransientSoapFilmSolver,
    frame_dict as transient_frame,
)


POST_EVENT_PHASE = "POST_EVENT_TRANSIENT_RELAXATION"


def _wind_velocity(scenario: Mapping[str, Any]) -> tuple[float, float, float]:
    environment = scenario["environment"]
    raw = (environment.get("wind") or {}).get("velocity_m_s") or (0.0, 0.0, 0.0)
    values = tuple(float(value) for value in raw)
    if len(values) != 3 or any(not math.isfinite(value) for value in values):
        raise ValueError("environment.wind.velocity_m_s must contain three finite values")
    return values  # type: ignore[return-value]


def _restart_film_tension(event_frame: Mapping[str, Any], child_id: str) -> float:
    expected = f"restart-outer-{child_id}"
    matches = [
        film for film in event_frame.get("film_regions", [])
        if str(film.get("id")) == expected
    ]
    if len(matches) != 1:
        raise RuntimeError(f"post-event restart film {expected!r} is missing or ambiguous")
    tension = float(matches[0]["surface_tension_n_m"])
    if tension <= 0.0 or not math.isfinite(tension):
        raise RuntimeError("post-event restart film has invalid sheet tension")
    return tension


def _build_solver(
    transition: TopologyTransition,
    event_frame: Mapping[str, Any],
    scenario: Mapping[str, Any],
    *,
    deterministic_seed: int,
    event_time_s: float,
) -> tuple[TransientSoapFilmSolver, Any]:
    active = list(transition.state.active_bubbles().values())
    if len(active) != 1:
        raise RuntimeError(
            "post-event transient continuation requires exactly one active coalesced child"
        )
    child = active[0]
    restart = child.restart_geometry
    if restart is None:
        raise RuntimeError("coalesced child has no conservative restart geometry")
    if not restart.requires_relaxation:
        raise RuntimeError("coalesced child restart geometry is not marked for relaxation")

    tension = _restart_film_tension(event_frame, child.id)
    source_vertices = tuple(tuple(float(value) for value in vertex) for vertex in restart.vertices_m)
    source_faces = tuple(tuple(int(index) for index in face) for face in restart.faces)
    front = FilmFront(
        bubble_id=child.id,
        mesh_id=f"restart-mesh-{child.id}",
        film_id=f"restart-outer-{child.id}",
        vertices=list(source_vertices),
        faces=list(source_faces),
        surface_tension_n_m=tension,
        target_volume_m3=float(restart.target_volume_m3),
    )
    if tuple(front.vertices) != source_vertices:
        raise RuntimeError("transient FilmFront initialization changed restart vertices")
    if sorted(tuple(sorted(face)) for face in front.faces) != sorted(
        tuple(sorted(face)) for face in source_faces
    ):
        raise RuntimeError("transient FilmFront initialization changed restart connectivity")
    relative_volume_error = abs(front.volume() - float(restart.target_volume_m3)) / float(
        restart.target_volume_m3
    )
    if relative_volume_error > 1.0e-12:
        raise RuntimeError(
            "transient FilmFront does not preserve the conservative restart volume"
        )

    environment = scenario["environment"]
    grid = GridConfig(
        density_kg_m3=float(environment["ambient_density_kg_m3"]),
        dynamic_viscosity_pa_s=float(environment["ambient_dynamic_viscosity_pa_s"]),
        background_velocity_m_s=_wind_velocity(scenario),
    )
    transient_config = TransientConfig(
        grid=grid,
        gravity_m_s2=tuple(float(value) for value in environment["gravity_m_s2"]),
        deterministic_seed=int(deterministic_seed),
        preserve_closed_bubble_volume=True,
        sharp_pressure_jump=False,
        remeshing=RemeshConfig(mode="quality"),
    )
    solver = TransientSoapFilmSolver([front], transient_config)
    solver.time_s = float(event_time_s)
    return solver, child


def _child_history_bubbles(
    event_frame: Mapping[str, Any], raw_frame: Mapping[str, Any], child_id: str, lineage: tuple[str, ...]
) -> list[dict[str, Any]]:
    historical = copy.deepcopy(list(event_frame["bubbles"]))
    dynamic = next(
        (bubble for bubble in raw_frame["bubbles"] if str(bubble["id"]) == child_id),
        None,
    )
    if dynamic is None:
        raise RuntimeError("transient export lost the coalesced child bubble")
    for bubble in historical:
        if str(bubble["id"]) != child_id:
            continue
        for key in (
            "volume_m3",
            "equivalent_radius_m",
            "centroid_m",
            "velocity_m_s",
            "pressure_pa",
            "status",
            "film_material",
            "gas_properties",
        ):
            if key in dynamic:
                bubble[key] = copy.deepcopy(dynamic[key])
        bubble["lineage"] = list(lineage)
        return historical
    raise RuntimeError("event frame does not contain the coalesced child bubble")


def _relaxation_metrics(
    solver: TransientSoapFilmSolver,
    target_volume_m3: float,
    seed_excess_energy_j: float | None,
) -> dict[str, float]:
    if len(solver.fronts) != 1:
        raise RuntimeError("post-event relaxation currently requires one tracked child front")
    front = solver.fronts[0]
    area = front.area()
    sphere_area = (36.0 * math.pi * target_volume_m3 * target_volume_m3) ** (1.0 / 3.0)
    surface_energy = solver.surface_energy()
    sphere_energy = front.surface_tension_n_m * sphere_area
    excess = max(0.0, surface_energy - sphere_energy)
    kinetic = solver.grid.kinetic_energy()
    ratio = 1.0
    if seed_excess_energy_j is not None and seed_excess_energy_j > 0.0:
        ratio = excess / seed_excess_energy_j
    return {
        "surface_area_m2": area,
        "minimum_sphere_area_m2": sphere_area,
        "surface_energy_j": surface_energy,
        "minimum_sphere_surface_energy_j": sphere_energy,
        "capillary_excess_energy_j": excess,
        "capillary_excess_ratio_to_seed": ratio,
        "bulk_kinetic_energy_j": kinetic,
        "mechanical_energy_j": surface_energy + kinetic,
        "volume_m3": front.volume(),
        "target_volume_m3": target_volume_m3,
        "volume_relative_error": abs(front.volume() - target_volume_m3) / target_volume_m3,
    }


def _combined_frame(
    solver: TransientSoapFilmSolver,
    event_frame: Mapping[str, Any],
    scenario: Mapping[str, Any],
    child: Any,
    *,
    serial: int,
    relaxation_index: int,
    event_seed: int,
    seed_excess_energy_j: float | None,
) -> tuple[dict[str, Any], float]:
    raw = transient_frame(solver, f"thinfilm-events-{serial:06d}-relax")
    out = copy.deepcopy(raw)
    event_ids = [str(event["id"]) for event in event_frame["topology"]["events"]]
    out["bubbles"] = _child_history_bubbles(event_frame, raw, child.id, child.lineage)
    out["topology"] = copy.deepcopy(event_frame["topology"])
    out["junctions"] = copy.deepcopy(event_frame.get("junctions", []))

    disclosures = copy.deepcopy(raw["manifest"].get("feature_disclosures", {}))
    disclosures.update(copy.deepcopy(event_frame["manifest"].get("feature_disclosures", {})))
    disclosures.update({
        "geometry_evolution": "MODELED",
        "post_event_cfd_relaxation": "MODELED",
        "post_event_restart_geometry": "MODELED",
        "topology_change": "MODELED",
        "rupture": "MODELED",
        "coalescence": "MODELED",
        "event_time_localization": "MODELED",
        "rim_retraction": "NOT_IMPLEMENTED",
        "spray_droplets": "NOT_IMPLEMENTED",
        "splitting": "NOT_IMPLEMENTED",
    })
    out["manifest"]["feature_disclosures"] = disclosures
    out["manifest"]["solver"] = {
        "backend": "bubblelab-thinfilm-events-runtime",
        "version": "1",
        "adapter": "topology-event-restart-to-accepted-transient-front-tracking",
    }
    provenance = out["manifest"].setdefault("provenance", {})
    provenance.update(copy.deepcopy(event_frame["manifest"].get("provenance", {})))
    provenance.update({
        "producer": "bubblelab.runtime.post_event_relaxation",
        "source_scenario": scenario["scenario_id"],
        "event_seed": int(event_seed),
        "event_engine": "bubblelab.solvers.events",
        "transient_engine": "bubblelab.solvers.transient",
        "post_event_continuation": POST_EVENT_PHASE,
        "restart_seed_geometry": "authoritative conservative event-engine mesh",
        "capillary_coupling": "accepted transient discrete capillary force with sharp tracked FilmFront",
    })

    metrics = _relaxation_metrics(
        solver,
        float(child.restart_geometry.target_volume_m3),
        seed_excess_energy_j,
    )
    if seed_excess_energy_j is None:
        seed_excess_energy_j = metrics["capillary_excess_energy_j"]
        metrics["capillary_excess_ratio_to_seed"] = 1.0
    out.setdefault("diagnostics", {})["post_event_relaxation"] = {
        **metrics,
        "relaxation_frame_index": relaxation_index,
        "solver_step_index": solver.step_index,
        "seed_geometry_preserved": relaxation_index == 0,
        "damping_metric": "capillary_excess_energy relative to equal-volume sphere, normalized by restart seed",
    }
    out["diagnostics"]["event_runtime"] = {
        "phase": POST_EVENT_PHASE,
        "event_ids": event_ids,
        "event_seed": int(event_seed),
        "shared_film_id": str(scenario["initial_film_regions"][0]["id"]),
        "terminal": False,
    }
    out["event_runtime"] = {
        "phase": POST_EVENT_PHASE,
        "shared_film_id": str(scenario["initial_film_regions"][0]["id"]),
        "event_ids": event_ids,
        "post_event_relaxation": (
            "INITIALIZED_FROM_CONSERVATIVE_RESTART" if relaxation_index == 0 else "PHYSICALLY_ADVANCED"
        ),
        "requires_post_event_relaxation": True,
        "physical_advancement_after_event": relaxation_index > 0,
        "child_bubble_id": child.id,
        "parent_lineage": list(child.lineage),
        "restart_mesh_authoritative": True,
        "solver_step_index": solver.step_index,
    }
    return out, seed_excess_energy_j


def build_post_event_relaxation_frames(
    transition: TopologyTransition,
    event_frame: Mapping[str, Any],
    scenario: Mapping[str, Any],
    *,
    cadence_s: float,
    count: int,
    serial: int,
    deterministic_seed: int,
) -> list[dict[str, Any]]:
    """Continue the event-engine child mesh through accepted transient dynamics."""
    if count <= 0:
        return []
    if cadence_s <= 0.0 or not math.isfinite(cadence_s):
        raise ValueError("post-event output cadence must be finite and positive")
    event_times = [float(event["time_s"]) for event in event_frame["topology"]["events"]]
    if not event_times:
        raise RuntimeError("post-event continuation requires prior topology-event history")
    event_time = max(event_times)
    solver, child = _build_solver(
        transition,
        event_frame,
        scenario,
        deterministic_seed=deterministic_seed,
        event_time_s=event_time,
    )

    output: list[dict[str, Any]] = []
    seed_excess: float | None = None
    for index in range(count):
        if index > 0:
            solver.run_to_time(event_time + index * cadence_s)
        frame, seed_excess = _combined_frame(
            solver,
            event_frame,
            scenario,
            child,
            serial=serial + index,
            relaxation_index=index,
            event_seed=deterministic_seed,
            seed_excess_energy_j=seed_excess,
        )
        output.append(frame)
    return output
