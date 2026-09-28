"""Canonical contract-v1 frame export for the isolated equilibrium backend."""
from __future__ import annotations

import math
from typing import Any

from .solver import EquilibriumResult
from .vector import mean

SOLVER_VERSION = "0.1.0"


def _array(values: list[Any], dtype: str, shape: list[int]) -> dict[str, Any]:
    return {"storage": "INLINE", "dtype": dtype, "shape": shape, "values": values}


def canonical_frame(
    result: EquilibriumResult,
    *,
    target_volume_m3: float,
    sheet_tension_n_m: float,
    bubble_id: str = "bubble-1",
    frame_id: str = "equilibrium-0",
    ambient_pressure_pa: float = 101325.0,
    random_seed: int = 0,
) -> dict[str, Any]:
    if target_volume_m3 <= 0.0:
        raise ValueError("target volume must be positive")
    mesh = result.mesh
    centroid = mean(mesh.vertices)
    radius = (3.0 * target_volume_m3 / (4.0 * math.pi)) ** (1.0 / 3.0)
    quality = mesh.quality()
    vertex_values = [[x, y, z] for x, y, z in mesh.vertices]
    face_values = [[a, b, c] for a, b, c in mesh.faces]
    normal_values = [[x, y, z] for x, y, z in mesh.face_normals()]
    return {
        "contract_version": "1.0.0",
        "kind": "FRAME",
        "frame_id": frame_id,
        "simulation_time_s": 0.0,
        "manifest": {
            "contract_version": "1.0.0",
            "units": {
                "system": "SI", "length": "m", "time": "s", "mass": "kg",
                "pressure": "Pa", "temperature": "K", "amount": "mol",
            },
            "solver": {"backend": "bubblelab-equilibrium", "version": SOLVER_VERSION, "adapter": None},
            "fidelity_tier": "HIGH_FIDELITY",
            "feature_disclosures": {
                "surface_energy": "RESOLVED",
                "prescribed_volume": "RESOLVED",
                "young_laplace_pressure": "RESOLVED",
                "triangulated_geometry": "RESOLVED",
                "shared_films": "NOT_IMPLEMENTED",
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
                "producer": "bubblelab.solvers.equilibrium",
                "source_scenario": None,
                "created_at": None,
                "tolerances": {
                    "relative_volume": 1.0e-10,
                    "normalized_force": 1.0e-3,
                },
            },
        },
        "environment": {
            "gravity_m_s2": [0.0, 0.0, 0.0],
            "ambient_density_kg_m3": 1.2041,
            "ambient_dynamic_viscosity_pa_s": 1.825e-5,
            "ambient_pressure_pa": ambient_pressure_pa,
        },
        "bubbles": [{
            "id": bubble_id,
            "volume_m3": mesh.signed_volume(),
            "equivalent_radius_m": radius,
            "centroid_m": list(centroid),
            "velocity_m_s": [0.0, 0.0, 0.0],
            "status": "ALIVE",
            "pressure_pa": ambient_pressure_pa + result.pressure_jump_pa,
            "film_material": {
                "effective_sheet_tension_n_m": sheet_tension_n_m,
                "tension_convention": "effective_collapsed_soap_film_sheet",
            },
            "surface_area_m2": mesh.area(),
            "surface_energy_j": result.surface_energy_j,
        }],
        "surface_meshes": [{
            "id": "outer-film-mesh-1",
            "geometry_role": "OUTER_FILM",
            "owner_bubble_ids": [bubble_id],
            "region_labels": [bubble_id, "EXTERIOR"],
            "vertex_count": len(mesh.vertices),
            "face_count": len(mesh.faces),
            "vertices": _array(vertex_values, "float64", [len(mesh.vertices), 3]),
            "faces": _array(face_values, "uint32", [len(mesh.faces), 3]),
            "fields": {"face_normals": _array(normal_values, "float64", [len(mesh.faces), 3])},
        }],
        "film_regions": [{
            "id": "outer-film-1",
            "kind": "OUTER",
            "adjacent": [bubble_id, "EXTERIOR"],
            "surface_tension_n_m": sheet_tension_n_m,
            "mesh_id": "outer-film-mesh-1",
        }],
        "junctions": [],
        "topology": {"adjacency": [{"a": bubble_id, "b": "EXTERIOR", "film_id": "outer-film-1"}], "events": []},
        "diagnostics": {
            "nonlinear_iterations": result.iterations,
            "residuals": {
                "relative_volume": result.relative_volume_error,
                "normalized_projected_force": result.normalized_force_residual,
                "pressure_jump_pa": result.pressure_jump_pa,
            },
            "max_relative_volume_error": result.relative_volume_error,
            "mesh_quality": quality,
            "converged": result.converged,
            "termination_reason": result.termination_reason,
            "energy_history_j": list(result.energy_history_j),
        },
    }
