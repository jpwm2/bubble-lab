"""Canonical contract-v1 export for reduced-order thin-film physics."""
from __future__ import annotations

import math

from .benchmarks import inclined_patch
from .gas import GasRegionState, GasTransferPair
from .surface import SurfaceTransportParameters, SurfaceTransportState


def _array(dtype: str, shape: list[int], values: list[object]) -> dict[str, object]:
    return {"storage": "INLINE", "dtype": dtype, "shape": shape, "values": values}


def canonical_demo_frame() -> dict[str, object]:
    mesh = inclined_patch()
    params = SurfaceTransportParameters(
        gravity_m_s2=(0.0, -9.81, 0.0),
        surfactant_diffusivity_m2_s=2.0e-8,
    )
    film = SurfaceTransportState(
        mesh,
        [8.0e-6, 11.0e-6],
        [1.0e-6, 3.0e-6],
        parameters=params,
    )
    initial_liquid = film.liquid_amount_m3()
    initial_surfactant = film.surfactant_amount_mol()
    film_diag = film.advance(0.02)
    sigma = film.surface_tension_n_m()

    gas_a = GasRegionState("bubble-a", 1.0e-6, 1.0e-5)
    gas_b = GasRegionState("bubble-b", 2.0e-6, 1.0e-5)
    gas_pair = GasTransferPair(
        "bubble-a",
        "bubble-b",
        shared_area_m2=math.fsum(mesh.face_areas_m2()),
        film_thickness_m=sum(film.thickness_m) / len(film.thickness_m),
        permeability_mol_m_per_m2_s_pa=1.0e-12,
    )
    gas_diag = gas_pair.advance(gas_a, gas_b, 0.05)

    flat_vertices = [value for vertex in mesh.vertices_m for value in vertex]
    flat_faces = [value for face in mesh.faces for value in face]
    centroid = (
        sum(vertex[0] for vertex in mesh.vertices_m) / len(mesh.vertices_m),
        sum(vertex[1] for vertex in mesh.vertices_m) / len(mesh.vertices_m),
        sum(vertex[2] for vertex in mesh.vertices_m) / len(mesh.vertices_m),
    )

    return {
        "contract_version": "1.0.0",
        "kind": "FRAME",
        "frame_id": "thinfilm-demo-0001",
        "simulation_time_s": 0.05,
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
                "backend": "bubblelab-reduced-thinfilm",
                "version": "1",
                "adapter": "surface-finite-volume",
            },
            "fidelity_tier": "HIGH_FIDELITY",
            "feature_disclosures": {
                "film_thickness": "MODELED",
                "film_drainage": "MODELED",
                "surfactant_transport": "MODELED",
                "marangoni_response": "MODELED",
                "gas_diffusion": "MODELED",
                "coarsening": "MODELED",
                "rupture": "NOT_IMPLEMENTED",
                "coalescence": "NOT_IMPLEMENTED",
            },
            "random_seed": 0,
            "provenance": {
                "producer": "bubblelab.solvers.thinfilm",
                "source_scenario": "thinfilm-demo",
                "created_at": None,
                "tolerances": {
                    "conservation_relative": 1.0e-10,
                },
            },
        },
        "environment": {
            "gravity_m_s2": list(params.gravity_m_s2),
            "ambient_density_kg_m3": 1.225,
            "ambient_dynamic_viscosity_pa_s": 1.81e-5,
        },
        "bubbles": [
            {
                "id": gas_a.id,
                "volume_m3": gas_a.volume_m3,
                "equivalent_radius_m": (3.0 * gas_a.volume_m3 / (4.0 * math.pi)) ** (1.0 / 3.0),
                "centroid_m": list(centroid),
                "velocity_m_s": [0.0, 0.0, 0.0],
                "status": "ALIVE",
                "pressure_pa": gas_a.pressure_pa,
                "temperature_k": gas_a.temperature_k,
                "gas_amount_mol": gas_a.amount_mol,
                "gas_species": "air",
            },
            {
                "id": gas_b.id,
                "volume_m3": gas_b.volume_m3,
                "equivalent_radius_m": (3.0 * gas_b.volume_m3 / (4.0 * math.pi)) ** (1.0 / 3.0),
                "centroid_m": list(centroid),
                "velocity_m_s": [0.0, 0.0, 0.0],
                "status": "ALIVE",
                "pressure_pa": gas_b.pressure_pa,
                "temperature_k": gas_b.temperature_k,
                "gas_amount_mol": gas_b.amount_mol,
                "gas_species": "air",
            },
        ],
        "surface_meshes": [
            {
                "id": mesh.mesh_id,
                "geometry_role": "SHARED_FILM",
                "owner_bubble_ids": ["bubble-a", "bubble-b"],
                "region_labels": ["bubble-a", "bubble-b"],
                "vertex_count": len(mesh.vertices_m),
                "face_count": len(mesh.faces),
                "vertices": _array("float64", [len(mesh.vertices_m), 3], flat_vertices),
                "faces": _array("uint32", [len(mesh.faces), 3], flat_faces),
                "fields": {
                    "film_thickness_m": _array("float64", [len(mesh.faces)], list(film.thickness_m)),
                    "surfactant_mol_m2": _array("float64", [len(mesh.faces)], list(film.surfactant_mol_m2)),
                    "surface_tension_n_m": _array("float64", [len(mesh.faces)], list(sigma)),
                },
            }
        ],
        "film_regions": [
            {
                "id": mesh.film_id,
                "kind": "SHARED",
                "adjacent": ["bubble-a", "bubble-b"],
                "mesh_id": mesh.mesh_id,
                "surface_tension_n_m": sum(sigma) / len(sigma),
                "thickness": {
                    "representation": "FACE_FIELD",
                    "field": "film_thickness_m",
                    "units": "m",
                    "fidelity": "MODELED",
                },
            }
        ],
        "junctions": [],
        "topology": {
            "adjacency": [
                {"a": "bubble-a", "b": "bubble-b", "film_id": mesh.film_id}
            ],
            "events": [],
        },
        "diagnostics": {
            "timestep_s": 0.02,
            "thinfilm": {
                "min_thickness_m": min(film.thickness_m),
                "max_thickness_m": max(film.thickness_m),
                "liquid_amount_m3": film.liquid_amount_m3(),
                "liquid_relative_drift": abs(film.liquid_amount_m3() - initial_liquid) / initial_liquid,
                "surfactant_amount_mol": film.surfactant_amount_mol(),
                "surfactant_relative_drift": abs(film.surfactant_amount_mol() - initial_surfactant) / initial_surfactant,
                "positivity_limited_steps": film_diag.positivity_limited_steps,
                "gas_total_relative_drift": gas_diag.total_relative_drift,
            },
        },
    }
