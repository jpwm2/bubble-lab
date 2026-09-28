#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from bubblelab.runtime.fragmentation_runtime import (
    _bubble_contract,
    _film,
    _fragmentation_config,
    _frame,
    _mesh_contract,
    _parent_mesh,
)
from bubblelab.runtime.postfragmentation_relaxation import _build_solver
from bubblelab.solvers.events.fragmentation import ParentState, split_parent
from bubblelab.solvers.events.pinchoff import PinchOffConfig, deform_x_axisymmetric_mesh, evolve_neck

DEFAULT_SCENARIO = ROOT / "bubblelab" / "scenarios" / "runtime" / "pinchoff-necked.scenario.json"


def _pinchoff_config(scenario: Mapping[str, Any]) -> PinchOffConfig:
    editable = scenario.get("user_editable")
    if not isinstance(editable, Mapping):
        raise ValueError("user_editable must be an object")
    raw = editable.get("pinchoff")
    if not isinstance(raw, Mapping):
        raise ValueError("user_editable.pinchoff is required")
    if raw.get("model") != "AXISYMMETRIC_SLENDER_NECK_V1":
        raise ValueError("unsupported pinch-off model")
    fields = {
        "cell_count", "patch_half_length_m", "parent_half_length_m", "base_radius_m",
        "neck_depth", "neck_width_m", "density_kg_m3", "dynamic_viscosity_pa_s",
        "surface_tension_n_m", "capillary_cfl", "advection_cfl", "viscous_cfl",
        "positivity_cfl", "resolution_stop_radius_cells", "minimum_evolution_time_s",
        "max_time_s", "fit_samples",
    }
    kwargs = {key: raw[key] for key in fields if key in raw}
    return PinchOffConfig(**kwargs)


def _assert_generator_matches_solver(scenario: Mapping[str, Any], config: PinchOffConfig) -> None:
    fragmentation = _fragmentation_config(scenario)
    generator = fragmentation.get("generator")
    if not isinstance(generator, Mapping) or generator.get("type") != "NECKED_SURFACE_OF_REVOLUTION":
        raise ValueError("pinch-off handoff requires the supported necked surface-of-revolution generator")
    comparisons = {
        "half_length_m": config.parent_half_length_m,
        "minor_radius_m": config.base_radius_m,
        "neck_depth": config.neck_depth,
        "neck_width_m": config.neck_width_m,
        "asymmetry": 0.0,
    }
    for key, expected in comparisons.items():
        actual = float(generator.get(key, math.nan))
        if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1.0e-14):
            raise ValueError(f"fragmentation generator {key} does not match pinch-off initial state")
    if int(generator.get("axial_segments", 0)) < 48 or int(generator.get("circum_segments", 0)) < 48:
        raise ValueError("pinch-off handoff mesh is under-resolved for the supported class")


def _dynamic_event_contract(fragmentation: Any, pinchoff: Any) -> dict[str, Any]:
    event = copy.deepcopy(fragmentation.event_contract())
    event["criterion"] = "DYNAMIC_AXISYMMETRIC_NECK_COLLAPSE_PLUS_RESOLVED_SEPARATING_CUT"
    event["provenance"].update({
        "detail": "time-evolved axisymmetric slender-neck hydrodynamics followed by deterministic cut/cap topology surgery",
        "pinchoff_solver": pinchoff.provenance["solver"],
        "pinchoff_solver_version": pinchoff.provenance["version"],
        "pinchoff_solver_digest": pinchoff.solver_digest,
        "pinchoff_last_resolved_time_s": pinchoff.last_resolved_time_s,
        "pinchoff_time_s": pinchoff.pinch_time_s,
        "pinchoff_time_method": "terminal zero-radius fit of dynamically evolved neck trajectory",
    })
    event["fidelity_boundary"]["singular_pinch_off_cfd"] = "MODELED_SUPPORTED_AXISYMMETRIC_SLENDER_NECK"
    event["fidelity_boundary"]["retracting_liquid_rim"] = "NOT_RESOLVED"
    event["fidelity_boundary"]["droplet_spray"] = "NOT_RESOLVED"
    event["pinchoff_diagnostics"] = {
        "initial_minimum_radius_m": pinchoff.initial_minimum_radius_m,
        "last_resolved_minimum_radius_m": pinchoff.final_minimum_radius_m,
        "cell_width_m": pinchoff.cell_width_m,
        "resolution_stop_radius_m": pinchoff.resolution_stop_radius_m,
        "terminal_fit_slope_m_s": pinchoff.terminal_fit_slope_m_s,
        "volume_relative_error": pinchoff.volume_relative_error,
    }
    return event


def run_transition(scenario: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(scenario.get("initial_bubbles"), list) or len(scenario["initial_bubbles"]) != 1:
        raise ValueError("pinch-off transition supports exactly one parent bubble")
    config = _pinchoff_config(scenario)
    _assert_generator_matches_solver(scenario, config)
    fragmentation_config = _fragmentation_config(scenario)
    initial_mesh = _parent_mesh(fragmentation_config)
    pinchoff = evolve_neck(config)
    projection = deform_x_axisymmetric_mesh(
        initial_mesh, pinchoff, patch_half_length_m=config.patch_half_length_m
    )
    source = scenario["initial_bubbles"][0]
    target_volume = float(source["volume_m3"])
    represented_initial = initial_mesh.volume()
    initial_geometry_error = abs(represented_initial - target_volume) / target_volume
    velocity = tuple(float(value) for value in source.get("velocity_m_s", (0.0, 0.0, 0.0)))
    if len(velocity) != 3:
        raise ValueError("velocity_m_s must contain three values")
    gas_amount = None if source.get("gas_amount_mol") is None else float(source["gas_amount_mol"])
    mass_kg = None if source.get("mass_kg") is None else float(source["mass_kg"])
    temperature = float(source.get("temperature_k") or 298.15)
    gas_species = source.get("gas_species")
    parent = ParentState(
        id=str(source["id"]),
        mesh=projection.mesh,
        target_volume_m3=target_volume,
        gas_amount_mol=gas_amount,
        velocity_m_s=velocity,  # type: ignore[arg-type]
        mass_kg=mass_kg,
        temperature_k=temperature,
        gas_species=gas_species,
    )
    fragmentation = split_parent(parent, event_time_s=pinchoff.pinch_time_s)
    event = _dynamic_event_contract(fragmentation, pinchoff)
    parent_centroid = projection.mesh.volume_centroid()
    bubbles = [
        _bubble_contract(
            parent.id, target_volume, parent_centroid, velocity, "SPLIT",
            gas_amount=gas_amount, temperature=temperature, gas_species=gas_species,
        )
    ]
    meshes: list[dict[str, Any]] = []
    films: list[dict[str, Any]] = []
    surface_tension = float(fragmentation_config.get("surface_tension_n_m", config.surface_tension_n_m))
    for child in fragmentation.children:
        bubbles.append(_bubble_contract(
            child.id, child.target_volume_m3, child.centroid_m, child.velocity_m_s, child.status,
            gas_amount=child.gas_amount_mol, temperature=child.temperature_k,
            gas_species=child.gas_species, lineage=list(child.lineage), geometry_status=child.geometry_status,
        ))
        mesh_id = f"mesh-{child.id}"
        meshes.append(_mesh_contract(
            mesh_id, child.id, child.mesh, parent_mesh_digest=projection.mesh.digest()
        ))
        films.append(_film(f"film-{child.id}", child.id, mesh_id, surface_tension))
    split_frame = _frame(
        scenario,
        frame_id=f"{scenario['scenario_id']}-pinchoff-split",
        time_s=pinchoff.pinch_time_s,
        bubbles=bubbles,
        meshes=meshes,
        films=films,
        events=[event],
        phase="POST_DYNAMIC_PINCHOFF_SPLIT_RESTART",
        diagnostics={
            "max_relative_volume_error": max(
                pinchoff.volume_relative_error,
                projection.corrected_volume_relative_error,
                float(fragmentation.conservation["target_volume_relative_error"] or 0.0),
                float(fragmentation.conservation["geometric_volume_relative_error"] or 0.0),
            ),
            "pinchoff": {
                "last_resolved_time_s": pinchoff.last_resolved_time_s,
                "pinch_time_s": pinchoff.pinch_time_s,
                "initial_minimum_radius_m": pinchoff.initial_minimum_radius_m,
                "last_resolved_minimum_radius_m": pinchoff.final_minimum_radius_m,
                "solver_digest": pinchoff.solver_digest,
            },
        },
    )
    split_frame["manifest"]["feature_disclosures"]["singular_pinch_off_cfd"] = "MODELED"
    split_frame["manifest"]["feature_disclosures"]["retracting_liquid_rim"] = "NOT_IMPLEMENTED"
    split_frame["manifest"]["feature_disclosures"]["droplet_spray"] = "NOT_IMPLEMENTED"
    split_frame["manifest"]["provenance"].update({
        "pinchoff_solver": pinchoff.provenance,
        "pinchoff_solver_digest": pinchoff.solver_digest,
        "pinchoff_time_s": pinchoff.pinch_time_s,
        "pinchoff_supported_class": "SINGLE_SMOOTH_AXISYMMETRIC_NECK",
    })
    transient_solver, transient_source = _build_solver(split_frame, scenario)
    exact_mesh_handoff = all(
        tuple(front.vertices) == transient_source[front.bubble_id]["vertices"]
        and tuple(front.faces) == transient_source[front.bubble_id]["faces"]
        for front in transient_solver.fronts
    )
    payload = {
        "status": "PASS",
        "supported_class": "SINGLE_SMOOTH_AXISYMMETRIC_NECK",
        "pinchoff": {
            "last_resolved_time_s": pinchoff.last_resolved_time_s,
            "pinch_time_s": pinchoff.pinch_time_s,
            "initial_minimum_radius_m": pinchoff.initial_minimum_radius_m,
            "last_resolved_minimum_radius_m": pinchoff.final_minimum_radius_m,
            "terminal_fit_slope_m_s": pinchoff.terminal_fit_slope_m_s,
            "volume_relative_error": pinchoff.volume_relative_error,
            "solver_digest": pinchoff.solver_digest,
            "provenance": pinchoff.provenance,
        },
        "mesh_projection": {
            "initial_geometry_target_relative_error": initial_geometry_error,
            "raw_volume_relative_error": projection.raw_volume_relative_error,
            "radial_volume_correction": projection.radial_volume_correction,
            "corrected_volume_relative_error": projection.corrected_volume_relative_error,
            "closed_manifold": projection.mesh.is_closed_manifold(),
        },
        "fragmentation": {
            "event_id": fragmentation.event_id,
            "event_time_s": fragmentation.event_time_s,
            "child_ids": [child.id for child in fragmentation.children],
            "children_closed_manifold": [child.mesh.is_closed_manifold() for child in fragmentation.children],
            "conservation": dict(fragmentation.conservation),
            "fidelity_boundary": event["fidelity_boundary"],
            "manifest_disclosure": split_frame["manifest"]["feature_disclosures"]["singular_pinch_off_cfd"],
        },
        "postfragmentation_handoff": {
            "front_count": len(transient_solver.fronts),
            "exact_child_mesh_seed": exact_mesh_handoff,
            "transient_time_s": transient_solver.time_s,
            "child_ids": [front.bubble_id for front in transient_solver.fronts],
        },
    }
    return payload


def assert_transition(payload: Mapping[str, Any]) -> None:
    pinchoff = payload["pinchoff"]
    projection = payload["mesh_projection"]
    fragmentation = payload["fragmentation"]
    handoff = payload["postfragmentation_handoff"]
    if not float(pinchoff["pinch_time_s"]) > float(pinchoff["last_resolved_time_s"]):
        raise AssertionError("pinch time must be dynamically extrapolated beyond the last resolved state")
    if float(pinchoff["volume_relative_error"]) > 2.0e-12:
        raise AssertionError("pinch-off solver volume error exceeds the gate")
    if float(projection["initial_geometry_target_relative_error"]) > 2.0e-12:
        raise AssertionError("scenario target volume does not match generated parent geometry")
    if float(projection["corrected_volume_relative_error"]) > 2.0e-12:
        raise AssertionError("parent mesh projection failed volume conservation")
    if not bool(projection["closed_manifold"]):
        raise AssertionError("evolved parent mesh is not closed")
    conservation = fragmentation["conservation"]
    for key in ("target_volume_relative_error", "geometric_volume_relative_error"):
        if float(conservation[key] or 0.0) > 5.0e-11:
            raise AssertionError(f"fragmentation {key} exceeds the gate")
    if not all(fragmentation["children_closed_manifold"]):
        raise AssertionError("fragmentation produced an open child mesh")
    boundary = fragmentation["fidelity_boundary"]
    if boundary["singular_pinch_off_cfd"] != "MODELED_SUPPORTED_AXISYMMETRIC_SLENDER_NECK":
        raise AssertionError("dynamic pinch-off provenance was not carried into the split event")
    if fragmentation["manifest_disclosure"] != "MODELED":
        raise AssertionError("canonical feature disclosure must use the contract-v1 MODELED value")
    if boundary["retracting_liquid_rim"] != "NOT_RESOLVED" or boundary["droplet_spray"] != "NOT_RESOLVED":
        raise AssertionError("unsupported post-singular physics was overclaimed")
    if int(handoff["front_count"]) != 2 or not bool(handoff["exact_child_mesh_seed"]):
        raise AssertionError("post-fragmentation transient did not accept exact child restart meshes")
    if not math.isclose(float(handoff["transient_time_s"]), float(fragmentation["event_time_s"]), rel_tol=0.0, abs_tol=1.0e-14):
        raise AssertionError("post-fragmentation transient time does not match the dynamic split time")


def main() -> int:
    parser = argparse.ArgumentParser(description="Exercise dynamic pinch-off through fragmentation and transient handoff")
    parser.add_argument("scenario", nargs="?", default=str(DEFAULT_SCENARIO))
    parser.add_argument("--assert", dest="assert_result", action="store_true")
    args = parser.parse_args()
    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    payload = run_transition(scenario)
    if args.assert_result:
        assert_transition(payload)
    print(json.dumps(payload, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
