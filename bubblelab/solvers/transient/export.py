"""Canonical contract-v1 export for the sharp transient/AMR backend."""
from __future__ import annotations

import math
from typing import Any

from .grid import RegionProperties
from .amr import AdaptiveEulerianGasGrid
from .solver import TransientSoapFilmSolver


def _array_ref(values, dtype: str, shape: list[int]) -> dict[str, Any]:
    return {"storage": "INLINE", "dtype": dtype, "shape": shape, "values": values}


def _mesh_quality(front) -> dict[str, float]:
    lo, hi = front.edge_length_bounds()
    mean = front.mean_edge_length()
    return {
        "mean_edge_length_m": mean,
        "min_edge_length_m": lo,
        "max_edge_length_m": hi,
        "max_to_min_edge_ratio": hi / lo if lo > 0.0 else float("inf"),
    }


def _region_properties(solver: TransientSoapFilmSolver, bubble_id: str) -> RegionProperties:
    return solver.config.region_properties.get(
        bubble_id,
        RegionProperties(
            solver.config.grid.density_kg_m3,
            solver.config.grid.dynamic_viscosity_pa_s,
        ),
    )


def _boundary_diagnostics(solver: TransientSoapFilmSolver, latest) -> dict[str, Any]:
    configured = solver.boundaries.metadata()
    if latest is None:
        return {
            "enabled": bool(configured),
            "model": "tracked-front-sdf-contact" if configured else "disabled",
            "geometric_tolerance_m": solver.config.boundary_tolerance_m,
            "contact_vertex_count": 0,
            "contact_face_count": 0,
            "max_penetration_pre_m": 0.0,
            "max_penetration_post_m": 0.0,
            "position_correction_l1_m": 0.0,
            "velocity_correction_proxy_l1_m_s": 0.0,
            "active_boundary_ids": [],
            "configured_boundaries": configured,
            "reports": [],
            "tracked_front_condition": "NO_PENETRATION_FREE_SLIP",
            "bulk_eulerian_wall_coupling": "NOT_IMPLEMENTED_PERIODIC_GRID",
        }
    return {
        "enabled": bool(configured),
        "model": "tracked-front-sdf-contact" if configured else "disabled",
        "geometric_tolerance_m": solver.config.boundary_tolerance_m,
        "contact_vertex_count": latest.boundary_contact_vertex_count,
        "contact_face_count": latest.boundary_contact_face_count,
        "max_penetration_pre_m": latest.boundary_max_penetration_pre_m,
        "max_penetration_post_m": latest.boundary_max_penetration_post_m,
        "position_correction_l1_m": latest.boundary_position_correction_l1_m,
        "velocity_correction_proxy_l1_m_s": latest.boundary_velocity_correction_proxy_l1_m_s,
        "active_boundary_ids": list(latest.boundary_ids),
        "configured_boundaries": configured,
        "reports": list(latest.boundary_reports),
        "tracked_front_condition": "NO_PENETRATION_FREE_SLIP",
        "bulk_eulerian_wall_coupling": "NOT_IMPLEMENTED_PERIODIC_GRID",
    }


def frame_dict(solver: TransientSoapFilmSolver, frame_id: str | None = None) -> dict[str, Any]:
    """Export represented physics only; unavailable film/topology physics stays absent."""
    config = solver.config
    latest = solver.history[-1] if solver.history else None
    has_boundaries = bool(solver.boundaries)
    has_wetting = any(
        boundary.wetting.target_contact_angle_deg is not None
        for boundary in solver.boundaries
    )
    feature_disclosures = {
        "film_sheet_geometry": "RESOLVED",
        "surface_tension": "RESOLVED",
        "bulk_incompressible_flow": "RESOLVED",
        "bulk_viscosity": "RESOLVED",
        "gravity_body_force": "RESOLVED",
        "uniform_background_wind": "MODELED",
        "front_volume_projection": "MODELED",
        "pressure_jump": "MODELED",
        "sharp_pressure_jump": "MODELED",
        "region_specific_bulk_properties": "RESOLVED",
        "region_specific_gas_properties": "RESOLVED",
        "buoyancy/density_contrast": "MODELED",
        "buoyancy_density_contrast": "MODELED",
        "adaptive_mesh_refinement": ("RESOLVED" if isinstance(solver.grid, AdaptiveEulerianGasGrid) else "NOT_IMPLEMENTED"),
        "front_remeshing": ("RESOLVED" if config.remeshing.mode != "disabled" else "NOT_IMPLEMENTED"),
        "solid_boundary_sdf_geometry": ("RESOLVED" if has_boundaries else "NOT_IMPLEMENTED"),
        "tracked_film_solid_no_penetration": ("RESOLVED" if has_boundaries else "NOT_IMPLEMENTED"),
        "tracked_film_wall_tangential_motion": ("MODELED" if has_boundaries else "NOT_IMPLEMENTED"),
        "film_wall_contact_angle": ("MODELED" if has_wetting else "NOT_IMPLEMENTED"),
        "bulk_solid_wall_no_slip": "NOT_IMPLEMENTED",
        "bulk_solid_fluid_wall_coupling": "NOT_IMPLEMENTED",
        "film_thickness": "NOT_IMPLEMENTED",
        "drainage": "NOT_IMPLEMENTED",
        "surfactant_transport": "NOT_IMPLEMENTED",
        "shared_film_topology": "NOT_IMPLEMENTED",
        "topology_change": "NOT_IMPLEMENTED",
        "coalescence": "NOT_IMPLEMENTED",
        "rupture": "NOT_IMPLEMENTED",
    }
    manifest = {
        "contract_version": "1.0.0",
        "units": {"system": "SI", "length": "m", "time": "s", "mass": "kg", "pressure": "Pa"},
        "solver": {
            "backend": "bubblelab-transient-reference",
            "version": solver.VERSION,
            "adapter": (
                "front-tracked-sheet/sharp-region-nested-amr"
                if isinstance(solver.grid, AdaptiveEulerianGasGrid)
                else "front-tracked-sheet/sharp-region-uniform-periodic-grid"
            ),
        },
        "fidelity_tier": "MAXIMUM_REALISM",
        "feature_disclosures": feature_disclosures,
        "random_seed": config.deterministic_seed,
        "provenance": {
            "producer": "bubblelab/solvers/transient",
            "tolerances": {
                "pressure_projection_s_inv": config.grid.pressure_tolerance_s_inv,
                "volume_projection_relative": 5.0e-13,
                "tracked_front_solid_penetration_m": config.boundary_tolerance_m,
            },
        },
    }
    wind = config.grid.background_velocity_m_s
    environment = {
        "gravity_m_s2": list(config.gravity_m_s2),
        "ambient_density_kg_m3": config.grid.density_kg_m3,
        "ambient_dynamic_viscosity_pa_s": config.grid.dynamic_viscosity_pa_s,
        "wind": {
            "velocity_m_s": list(wind),
            "description": "uniform imposed background flow; dynamic perturbation is solved on the Eulerian grid",
        },
        "flow_metadata": {
            "grid": (
                "nested-block-amr-collocated-reference"
                if isinstance(solver.grid, AdaptiveEulerianGasGrid)
                else "uniform-periodic-collocated-reference"
            ),
            "cells": list(config.grid.cells),
            "cell_size_m": solver.grid.h,
            "amr": (solver.grid.diagnostics() if isinstance(solver.grid, AdaptiveEulerianGasGrid) else {"enabled": False}),
            "region_classification": "closed oriented triangle solid-angle test at cell centers",
            "density_face_interpolation": "arithmetic mean of inverse density (harmonic density)",
            "viscosity_face_interpolation": "harmonic dynamic viscosity",
            "pressure_projection": "variable-density paired backward-divergence/forward-gradient projection",
            "capillary_coupling": "balanced cell pressure potential from geometry-derived discrete mean curvature",
            "hydrostatic_split": (
                "exterior-density reference for density-contrast buoyancy"
                if solver.grid.hydrostatic_reference_density_kg_m3 is not None
                else "none"
            ),
            "bulk_boundary_condition": "periodic reference box",
            "tracked_front_solid_boundary_model": (
                "SDF no-penetration + free-slip + optional local wetting law"
                if has_boundaries
                else "disabled"
            ),
            "solid_fluid_bulk_wall_coupling": "not implemented on periodic Eulerian operator",
        },
    }

    bubbles = []
    meshes = []
    films = []
    for front in solver.fronts:
        volume = front.volume()
        radius = (3.0 * volume / (4.0 * math.pi)) ** (1.0 / 3.0)
        props = _region_properties(solver, front.bubble_id)
        try:
            pressure = solver.grid.mean_pressure(front.bubble_id, physical=True)
        except ValueError:
            pressure = None
        bubbles.append({
            "id": front.bubble_id,
            "volume_m3": volume,
            "equivalent_radius_m": radius,
            "centroid_m": list(front.centroid()),
            "velocity_m_s": list(solver.bubble_velocity(front.bubble_id)),
            "pressure_pa": pressure,
            "status": "ALIVE",
            "gas_properties": {
                "density_kg_m3": props.density_kg_m3,
                "dynamic_viscosity_pa_s": props.dynamic_viscosity_pa_s,
            },
            "film_material": {
                "effective_sheet_tension_n_m": front.surface_tension_n_m,
                "tension_convention": "collapsed two-interface sheet sigma_f",
            },
        })
        flat_vertices = [coord for v in front.vertices for coord in v]
        flat_faces = [index for face in front.faces for index in face]
        curvature = front.normal_curvature_vectors()
        flat_curvature = [coord for v in curvature for coord in v]
        meshes.append({
            "id": front.mesh_id,
            "geometry_role": "OUTER_FILM",
            "owner_bubble_ids": [front.bubble_id],
            "region_labels": [front.bubble_id, "EXTERIOR"],
            "vertex_count": len(front.vertices),
            "face_count": len(front.faces),
            "vertices": _array_ref(flat_vertices, "float64", [len(front.vertices), 3]),
            "faces": _array_ref(flat_faces, "uint32", [len(front.faces), 3]),
            "fields": {
                "mean_curvature_vector_1_m": _array_ref(
                    flat_curvature, "float64", [len(front.vertices), 3]
                )
            },
        })
        films.append({
            "id": front.film_id,
            "kind": "OUTER",
            "adjacent": [front.bubble_id, "EXTERIOR"],
            "mesh_id": front.mesh_id,
            "surface_tension_n_m": front.surface_tension_n_m,
        })

    if isinstance(solver.grid, AdaptiveEulerianGasGrid):
        region_counts = solver.grid.composite_region_counts()
        amr_diagnostics = solver.grid.diagnostics()
    else:
        region_counts: dict[str, int] = {}
        for label in solver.grid.region_labels:
            region_counts[label] = region_counts.get(label, 0) + 1
        amr_diagnostics = {"enabled": False}

    boundary_diag = _boundary_diagnostics(solver, latest)
    if latest is None:
        timestep = solver.select_timestep()
        diagnostics = {
            "timestep_s": timestep,
            "linear_iterations": 0,
            "residuals": {
                "divergence_linf_s_inv": solver.grid.divergence_linf(),
                "pressure_projection_s_inv": 0.0,
                "pressure_jump_relative_error": 0.0,
            },
            "max_relative_volume_error": max(solver.volume_errors().values(), default=0.0),
            "mesh_quality": {f.bubble_id: _mesh_quality(f) for f in solver.fronts},
            "region_cell_counts": region_counts,
            "adaptive_mesh_refinement": amr_diagnostics,
            "front_remeshing": {"mode": config.remeshing.mode, "reports": []},
            "solid_boundary_contact": boundary_diag,
        }
    else:
        diagnostics = {
            "timestep_s": latest.timestep_s,
            "linear_iterations": latest.pressure_iterations,
            "residuals": {
                "divergence_linf_s_inv": latest.divergence_linf_s_inv,
                "pressure_projection_s_inv": latest.projection_residual_s_inv,
                "pressure_jump_relative_error": latest.max_pressure_jump_relative_error,
            },
            "max_relative_volume_error": latest.max_relative_volume_error,
            "max_relative_volume_error_pre_projection": latest.max_relative_volume_error_pre_projection,
            "mesh_quality": {f.bubble_id: _mesh_quality(f) for f in solver.fronts},
            "region_cell_counts": region_counts,
            "adaptive_mesh_refinement": amr_diagnostics,
            "front_remeshing": {
                "mode": config.remeshing.mode,
                "operation_count": latest.remesh_operation_count,
                "max_relative_volume_change_pre_projection": latest.remesh_max_relative_volume_change,
                "max_field_conservation_relative_error": latest.remesh_max_field_conservation_error,
                "reports": list(latest.remesh_reports),
            },
            "solid_boundary_contact": boundary_diag,
        }

    return {
        "contract_version": "1.0.0",
        "kind": "FRAME",
        "frame_id": frame_id or f"transient-{solver.step_index:06d}",
        "simulation_time_s": solver.time_s,
        "manifest": manifest,
        "environment": environment,
        "bubbles": bubbles,
        "surface_meshes": meshes,
        "film_regions": films,
        "junctions": [],
        "topology": {"adjacency": [], "events": []},
        "diagnostics": diagnostics,
        "transient_sharp_interface": {
            "front_advection": (
                "midpoint interpolation, optional deterministic remeshing, global closed-volume projection, "
                "and optional SDF tracked-front contact projection"
            ),
            "momentum": "semi-Lagrangian advection + variable viscosity + buoyancy/body forcing + variable-density projection",
            "pressure_jump": "balanced one-cell region pressure potential using tracked-mesh curvature",
            "boundary_condition": (
                "periodic Eulerian bulk; tracked front additionally obeys configured SDF solid no-penetration/free-slip"
                if has_boundaries
                else "periodic reference box"
            ),
            "limitations": [
                ("nested AMR enabled; fine patches use parent-filled local correction boundaries"
                 if isinstance(solver.grid, AdaptiveEulerianGasGrid)
                 else "uniform grid; AMR disabled for this run"),
                "zero-thickness soap-film sheet; no finite liquid thickness",
                "isolated closed-region sharp jump; no shared-film topology changes",
                "solid SDFs constrain tracked-film geometry only; the periodic Eulerian gas operator does not resolve a no-slip solid wall",
                "contact-angle law is a local geometric model on the closed front; no finite wetted meniscus or open-film topology is represented",
            ],
        },
    }
