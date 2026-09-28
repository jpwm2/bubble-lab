"""Canonical contract-v1 export for a solved two-bubble shared-film network."""
from __future__ import annotations

import math
from typing import Any

from .network import EXTERIOR, NetworkEquilibriumResult

SOLVER_VERSION = "0.2.0"


def _array(values: list[Any], dtype: str, shape: list[int]) -> dict[str, Any]:
    return {"storage": "INLINE", "dtype": dtype, "shape": shape, "values": values}


def canonical_shared_film_frame(
    result: NetworkEquilibriumResult,
    *,
    ambient_pressure_pa: float = 101325.0,
    frame_id: str = "shared-equilibrium-0",
    random_seed: int = 0,
) -> dict[str, Any]:
    network = result.network
    network.validate()
    surface_meshes = []
    film_regions = []
    adjacency = []

    for patch in network.patches:
        mesh = patch.mesh
        is_shared = EXTERIOR not in patch.adjacent
        surface_meshes.append({
            "id": f"mesh-{patch.id}",
            "geometry_role": "SHARED_FILM" if is_shared else "OUTER_FILM",
            "owner_bubble_ids": [region for region in patch.adjacent if region != EXTERIOR],
            "region_labels": list(patch.adjacent),
            "vertex_count": len(mesh.vertices),
            "face_count": len(mesh.faces),
            "vertices": _array([[x, y, z] for x, y, z in mesh.vertices], "float64", [len(mesh.vertices), 3]),
            "faces": _array([[a, b, c] for a, b, c in mesh.faces], "uint32", [len(mesh.faces), 3]),
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
            "kind": "SHARED" if is_shared else "OUTER",
            "adjacent": list(patch.adjacent),
            "surface_tension_n_m": patch.sheet_tension_n_m,
            "mesh_id": f"mesh-{patch.id}",
        })
        adjacency.append({"a": patch.adjacent[0], "b": patch.adjacent[1], "film_id": patch.id})

    bubbles = []
    for region in network.regions:
        volume = network.region_volume(region.id)
        equivalent_radius = (3.0 * volume / (4.0 * math.pi)) ** (1.0 / 3.0)
        tensions = sorted({
            patch.sheet_tension_n_m
            for patch in network.patches
            if region.id in patch.adjacent
        })
        bubbles.append({
            "id": region.id,
            "volume_m3": volume,
            "equivalent_radius_m": equivalent_radius,
            "centroid_m": list(network.region_centroid(region.id)),
            "velocity_m_s": [0.0, 0.0, 0.0],
            "status": "ALIVE",
            "pressure_pa": ambient_pressure_pa + result.pressures_pa[region.id],
            "film_material": {
                "effective_sheet_tension_n_m": tensions[0] if len(tensions) == 1 else None,
                "tension_convention": "effective_collapsed_soap_film_sheet",
            },
        })

    residuals: dict[str, float] = {
        "normalized_projected_force": result.normalized_force_residual,
    }
    for region in network.regions:
        residuals[f"relative_volume_{region.id}"] = result.relative_volume_residuals[region.id]
        residuals[f"pressure_jump_{region.id}_pa"] = result.pressures_pa[region.id]

    return {
        "contract_version": "1.0.0",
        "kind": "FRAME",
        "frame_id": frame_id,
        "simulation_time_s": 0.0,
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
            "solver": {"backend": "bubblelab-equilibrium", "version": SOLVER_VERSION, "adapter": None},
            "fidelity_tier": "HIGH_FIDELITY",
            "feature_disclosures": {
                "surface_energy": "RESOLVED",
                "prescribed_volume": "RESOLVED",
                "young_laplace_pressure": "RESOLVED",
                "triangulated_geometry": "RESOLVED",
                "shared_films": "RESOLVED",
                "plateau_junctions": "NOT_IMPLEMENTED",
                "film_thickness": "NOT_IMPLEMENTED",
                "transient_flow": "NOT_IMPLEMENTED",
                "drainage": "NOT_IMPLEMENTED",
                "gas_diffusion": "NOT_IMPLEMENTED",
                "coalescence": "NOT_IMPLEMENTED",
                "rupture": "NOT_IMPLEMENTED",
            },
            "random_seed": random_seed,
            "provenance": {
                "producer": "bubblelab.solvers.equilibrium.shared_export",
                "source_scenario": None,
                "created_at": None,
                "tolerances": {
                    "relative_volume": 1.0e-10,
                    "normalized_projected_force": 8.0e-3,
                },
            },
        },
        "environment": {
            "gravity_m_s2": [0.0, 0.0, 0.0],
            "ambient_density_kg_m3": 1.2041,
            "ambient_dynamic_viscosity_pa_s": 1.825e-5,
            "ambient_pressure_pa": ambient_pressure_pa,
        },
        "bubbles": bubbles,
        "surface_meshes": surface_meshes,
        "film_regions": film_regions,
        "junctions": [],
        "topology": {"adjacency": adjacency, "events": []},
        "diagnostics": {
            "nonlinear_iterations": result.iterations,
            "residuals": residuals,
            "max_relative_volume_error": max(result.relative_volume_residuals.values()),
            "converged": result.converged,
            "termination_reason": result.termination_reason,
            "energy_history_j": list(result.energy_history_j),
        },
    }
