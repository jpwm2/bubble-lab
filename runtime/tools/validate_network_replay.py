#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.runtime.bundle import validate_replay_bundle


class NetworkReplayValidationError(ValueError):
    pass


def _load_frame(bundle: Path, replay: dict[str, Any]) -> dict[str, Any]:
    if len(replay["frames"]) != 1:
        raise NetworkReplayValidationError(
            "quasi-static equilibrium network replay must contain exactly one frame"
        )
    ref = replay["frames"][0]
    return json.loads((bundle / ref["path"]).read_text(encoding="utf-8"))


def _mesh_by_id(frame: dict[str, Any]) -> dict[str, dict[str, Any]]:
    meshes = frame.get("surface_meshes") or []
    result: dict[str, dict[str, Any]] = {}
    for mesh in meshes:
        mesh_id = str(mesh["id"])
        if mesh_id in result:
            raise NetworkReplayValidationError(f"duplicate surface mesh ID: {mesh_id}")
        result[mesh_id] = mesh
    return result


def _assert_solver_geometry(frame: dict[str, Any], mesh: dict[str, Any]) -> None:
    if int(mesh.get("vertex_count", 0)) <= 0 or int(mesh.get("face_count", 0)) <= 0:
        raise NetworkReplayValidationError("network film mesh is empty")
    vertices = mesh.get("vertices") or {}
    faces = mesh.get("faces") or {}
    if vertices.get("storage") != "INLINE" or faces.get("storage") != "INLINE":
        raise NetworkReplayValidationError("network geometry must be canonical solver-exported mesh data")
    if not vertices.get("values") or not faces.get("values"):
        raise NetworkReplayValidationError("network geometry has no solver-generated vertices/faces")
    producer = ((frame.get("manifest") or {}).get("provenance") or {}).get("producer")
    if producer not in {
        "bubblelab.solvers.equilibrium.shared_export",
        "bubblelab.solvers.equilibrium.plateau_export",
    }:
        raise NetworkReplayValidationError(
            "network geometry provenance is not an accepted equilibrium solver export"
        )


def assert_shared_film(frame: dict[str, Any]) -> dict[str, Any]:
    disclosures = ((frame.get("manifest") or {}).get("feature_disclosures") or {})
    if disclosures.get("shared_films") != "RESOLVED":
        raise NetworkReplayValidationError("shared_films is not disclosed as RESOLVED")
    if (frame.get("manifest") or {}).get("fidelity_tier") != "HIGH_FIDELITY":
        raise NetworkReplayValidationError("network replay is not HIGH_FIDELITY")

    shared = [film for film in frame.get("film_regions", []) if film.get("kind") == "SHARED"]
    if len(shared) != 1:
        raise NetworkReplayValidationError(
            f"expected exactly one shared film, found {len(shared)}"
        )
    film = shared[0]
    adjacent = film.get("adjacent") or []
    if len(adjacent) != 2 or "EXTERIOR" in adjacent or len(set(adjacent)) != 2:
        raise NetworkReplayValidationError("shared film adjacency is malformed")
    bubble_ids = {str(bubble["id"]) for bubble in frame.get("bubbles", [])}
    if any(str(region_id) not in bubble_ids for region_id in adjacent):
        raise NetworkReplayValidationError("shared film references a missing gas region")

    meshes = _mesh_by_id(frame)
    mesh_id = film.get("mesh_id")
    if mesh_id not in meshes:
        raise NetworkReplayValidationError("shared film has no canonical surface mesh")
    mesh = meshes[mesh_id]
    if mesh.get("geometry_role") != "SHARED_FILM":
        raise NetworkReplayValidationError("shared film mesh has the wrong geometry role")
    _assert_solver_geometry(frame, mesh)

    pressures = [bubble.get("pressure_pa") for bubble in frame.get("bubbles", [])]
    if len(pressures) != 2 or any(value is None for value in pressures):
        raise NetworkReplayValidationError("shared-film replay is missing solved region pressures")
    return {"shared_film_id": film["id"], "adjacent": adjacent}


def assert_pressure_curvature(frame: dict[str, Any]) -> dict[str, Any]:
    diagnostic = ((frame.get("diagnostics") or {}).get("pressure_curvature") or {})
    if diagnostic.get("producer") != (
        "bubblelab.solvers.equilibrium.shared_benchmarks.b05_unequal_pressure_curvature"
    ):
        raise NetworkReplayValidationError(
            "pressure/curvature diagnostic is not from the accepted B05 measurement"
        )
    if not bool(diagnostic.get("sign_consistent")):
        raise NetworkReplayValidationError("shared-film curvature sign disagrees with pressure ordering")
    residual = float(diagnostic.get("pressure_curvature_residual", math.inf))
    normalized = float(diagnostic.get("normalized_curvature_error", math.inf))
    if not math.isfinite(residual) or residual > 1.0e-2:
        raise NetworkReplayValidationError(
            f"shared-film pressure/curvature residual {residual:.6g} exceeds 1e-2"
        )
    if not math.isfinite(normalized) or normalized > 1.0e-2:
        raise NetworkReplayValidationError(
            f"shared-film normalized curvature error {normalized:.6g} exceeds 1e-2"
        )
    if not math.isfinite(float(diagnostic.get("fitted_curvature_1_m", math.nan))):
        raise NetworkReplayValidationError("shared-film fitted curvature is not finite")
    return {
        "pressure_curvature_residual": residual,
        "normalized_curvature_error": normalized,
    }


def assert_junction(frame: dict[str, Any]) -> dict[str, Any]:
    disclosures = ((frame.get("manifest") or {}).get("feature_disclosures") or {})
    if disclosures.get("plateau_junctions") != "RESOLVED":
        raise NetworkReplayValidationError("plateau_junctions is not disclosed as RESOLVED")
    junctions = frame.get("junctions") or []
    if len(junctions) != 1:
        raise NetworkReplayValidationError(
            f"expected exactly one Plateau junction, found {len(junctions)}"
        )
    junction = junctions[0]
    incident = [str(value) for value in junction.get("incident_film_ids") or []]
    if len(incident) != 3 or len(set(incident)) != 3:
        raise NetworkReplayValidationError(
            "benchmark Plateau junction must reference exactly three unique films"
        )
    films = {str(film["id"]): film for film in frame.get("film_regions", [])}
    meshes = _mesh_by_id(frame)
    for film_id in incident:
        film = films.get(film_id)
        if film is None:
            raise NetworkReplayValidationError(
                f"Plateau junction references missing film: {film_id}"
            )
        if film.get("kind") != "SHARED":
            raise NetworkReplayValidationError(
                f"Plateau junction incident film is not SHARED: {film_id}"
            )
        mesh_id = film.get("mesh_id")
        if mesh_id not in meshes:
            raise NetworkReplayValidationError(
                f"Plateau incident film has no mesh: {film_id}"
            )
        _assert_solver_geometry(frame, meshes[mesh_id])

    geometry = junction.get("geometry") or {}
    if geometry.get("storage") != "INLINE" or not geometry.get("values"):
        raise NetworkReplayValidationError("Plateau junction is missing measured geometry")
    angles = junction.get("measured_angles_deg") or []
    if len(angles) != 3 or any(not math.isfinite(float(value)) for value in angles):
        raise NetworkReplayValidationError("Plateau junction measured angles are malformed")
    provenance = junction.get("measurement_provenance") or {}
    if provenance.get("producer") != (
        "bubblelab.solvers.equilibrium.network.junction_geometry_diagnostics"
    ):
        raise NetworkReplayValidationError(
            "Plateau angles are not from accepted numerical geometry diagnostics"
        )
    if provenance.get("geometry_source") != "solved triangulated film network":
        raise NetworkReplayValidationError("Plateau geometry provenance is not solver-generated")
    return {"junction_id": junction["id"], "incident_film_ids": incident}


def assert_plateau_balance(frame: dict[str, Any]) -> dict[str, Any]:
    diagnostic = ((frame.get("diagnostics") or {}).get("plateau_balance") or {})
    if diagnostic.get("producer") != (
        "bubblelab.solvers.equilibrium.plateau_benchmarks.plateau_three"
    ):
        raise NetworkReplayValidationError(
            "Plateau balance diagnostic is not from the accepted B06 measurement"
        )
    rms = float(diagnostic.get("angle_rms_error_deg", math.inf))
    force_residual = float(diagnostic.get("junction_force_residual", math.inf))
    if not math.isfinite(rms) or rms > 1.0:
        raise NetworkReplayValidationError(
            f"Plateau RMS angle error {rms:.6g} deg exceeds 1 degree"
        )
    if not math.isfinite(force_residual) or force_residual > 5.0e-3:
        raise NetworkReplayValidationError(
            f"Plateau junction force residual {force_residual:.6g} exceeds 5e-3"
        )
    if int(diagnostic.get("sample_count", 0)) <= 3:
        raise NetworkReplayValidationError(
            "Plateau balance diagnostic does not contain the resolved junction samples"
        )
    diagnostics = frame.get("diagnostics") or {}
    if float(diagnostics.get("max_relative_volume_error", math.inf)) > 1.0e-8:
        raise NetworkReplayValidationError("Plateau gas-volume residual exceeds 1e-8")
    return {
        "angle_rms_error_deg": rms,
        "junction_force_residual": force_residual,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle")
    parser.add_argument("--assert-shared-film", action="store_true")
    parser.add_argument("--assert-pressure-curvature", action="store_true")
    parser.add_argument("--assert-junction", action="store_true")
    parser.add_argument("--assert-plateau-balance", action="store_true")
    args = parser.parse_args()

    bundle = Path(args.bundle)
    replay = validate_replay_bundle(bundle)
    frame = _load_frame(bundle, replay)
    summary: dict[str, Any] = {"valid": True, "frame_id": frame["frame_id"]}
    if args.assert_shared_film:
        summary.update(assert_shared_film(frame))
    if args.assert_pressure_curvature:
        summary.update(assert_pressure_curvature(frame))
    if args.assert_junction:
        summary.update(assert_junction(frame))
    if args.assert_plateau_balance:
        summary.update(assert_plateau_balance(frame))
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
