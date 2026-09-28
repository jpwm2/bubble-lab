"""Canonical contract-v1 export for rupture/coalescence event history."""
from __future__ import annotations

from typing import Any

from .benchmarks import demo_transition
from .model import EXTERIOR, BubbleState, EventState


def _array(dtype: str, shape: list[int], values: list[object]) -> dict[str, object]:
    return {"storage": "INLINE", "dtype": dtype, "shape": shape, "values": values}


def _bubble_contract(bubble: BubbleState) -> dict[str, object]:
    return {
        "id": bubble.id,
        "volume_m3": bubble.volume_m3,
        "equivalent_radius_m": bubble.equivalent_radius_m,
        "centroid_m": list(bubble.centroid_m),
        "velocity_m_s": list(bubble.velocity_m_s),
        "status": bubble.status,
        "pressure_pa": bubble.pressure_pa,
        "temperature_k": bubble.temperature_k,
        "gas_amount_mol": bubble.gas_amount_mol,
        "gas_species": bubble.gas_species,
        "lineage": list(bubble.lineage),
        "mass_kg": bubble.mass_kg,
    }


def canonical_frame_from_state(state: EventState, *, frame_time_s: float) -> dict[str, Any]:
    if state.events and max(event.time_s for event in state.events) > frame_time_s:
        raise ValueError("frame time must not precede the latest topology event")
    bubbles = [_bubble_contract(state.bubbles[key]) for key in sorted(state.bubbles)]
    surface_meshes: list[dict[str, Any]] = []
    film_regions: list[dict[str, Any]] = []
    adjacency: list[dict[str, Any]] = []

    for bubble in sorted(state.active_bubbles().values(), key=lambda item: item.id):
        geometry = bubble.restart_geometry
        if geometry is None:
            continue
        mesh_id = f"restart-mesh-{bubble.id}"
        film_id = f"restart-outer-{bubble.id}"
        flat_vertices = [component for vertex in geometry.vertices_m for component in vertex]
        flat_faces = [index for face in geometry.faces for index in face]
        surface_meshes.append({
            "id": mesh_id,
            "geometry_role": "OUTER_FILM",
            "owner_bubble_ids": [bubble.id],
            "region_labels": [bubble.id, EXTERIOR],
            "vertex_count": len(geometry.vertices_m),
            "face_count": len(geometry.faces),
            "vertices": _array("float64", [len(geometry.vertices_m), 3], flat_vertices),
            "faces": _array("uint32", [len(geometry.faces), 3], flat_faces),
            "fields": {},
            "restart_geometry": {
                "kind": geometry.kind,
                "target_volume_m3": geometry.target_volume_m3,
                "represented_volume_m3": geometry.volume_m3(),
                "volume_relative_error": geometry.volume_relative_error(),
                "requires_relaxation": geometry.requires_relaxation,
            },
        })
        film_regions.append({
            "id": film_id,
            "kind": "OUTER",
            "adjacent": [bubble.id, EXTERIOR],
            "mesh_id": mesh_id,
            "surface_tension_n_m": 0.050,
            "thickness": None,
            "restart_only": True,
        })
        adjacency.append({"a": bubble.id, "b": EXTERIOR, "film_id": film_id})

    events = [event.to_contract() for event in state.events]
    latest_conservation = next(
        (event.conservation for event in reversed(state.events) if event.type == "COALESCENCE"),
        None,
    )
    return {
        "contract_version": "1.0.0",
        "kind": "FRAME",
        "frame_id": "events-demo-0001",
        "simulation_time_s": frame_time_s,
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
                "backend": "bubblelab-topology-events",
                "version": "1",
                "adapter": "rupture-coalescence-event-engine",
            },
            "fidelity_tier": "HIGH_FIDELITY",
            "feature_disclosures": {
                "rupture": "MODELED",
                "coalescence": "MODELED",
                "film_thickness": "MODELED",
                "event_time_localization": "MODELED",
                "post_event_restart_geometry": "MODELED",
                "post_event_cfd_relaxation": "NOT_IMPLEMENTED",
                "rim_retraction": "NOT_IMPLEMENTED",
                "spray_droplets": "NOT_IMPLEMENTED",
                "splitting": "NOT_IMPLEMENTED",
            },
            "random_seed": state.seed,
            "provenance": {
                "producer": "bubblelab.solvers.events",
                "source_scenario": "coalescence-rupture-demo",
                "created_at": None,
                "tolerances": {
                    "gas_amount_relative": 1.0e-12,
                    "restart_geometry_volume_relative": 1.0e-12,
                    "rupture_time_fine_finer_relative_shift": 0.02,
                },
            },
        },
        "environment": {
            "gravity_m_s2": [0.0, -9.81, 0.0],
            "ambient_density_kg_m3": 1.225,
            "ambient_dynamic_viscosity_pa_s": 1.81e-5,
        },
        "bubbles": bubbles,
        "surface_meshes": surface_meshes,
        "film_regions": film_regions,
        "junctions": [],
        "topology": {
            "adjacency": adjacency,
            "events": events,
            "retired_film_ids": sorted(state.retired_films),
            "post_event_active_bubble_ids": sorted(state.active_bubbles()),
        },
        "diagnostics": {
            "timestep_s": 0.05,
            "event_engine": {
                "event_count": len(events),
                "state_ref": state.digest(),
                "latest_coalescence_conservation": latest_conservation,
            },
        },
    }


def canonical_demo_frame() -> dict[str, Any]:
    state = demo_transition()
    return canonical_frame_from_state(state, frame_time_s=0.05)
