"""Canonical runtime adapter for accepted equilibrium film-network benchmarks."""
from __future__ import annotations

import math
from typing import Any, Mapping

from bubblelab.solvers.equilibrium.plateau_benchmarks import plateau_three, plateau_three_result
from bubblelab.solvers.equilibrium.plateau_export import canonical_plateau_frame
from bubblelab.solvers.equilibrium.shared_benchmarks import (
    b05_unequal_pressure_curvature,
    unequal_pressure_result,
)
from bubblelab.solvers.equilibrium.shared_export import canonical_shared_film_frame

EXTERIOR = "EXTERIOR"
SHARED_INITIALIZER = "accepted-b05-unequal-pressure"
PLATEAU_INITIALIZER = "accepted-b06-plateau-three"


class NetworkRuntimeConfigurationError(ValueError):
    """Raised when a scenario cannot map exactly to an accepted network case."""


def _requested_features(scenario: Mapping[str, Any]) -> dict[str, Any]:
    features: dict[str, Any] = {}
    requested = scenario.get("requested_solver") or {}
    editable = scenario.get("user_editable") or {}
    if isinstance(requested, Mapping) and isinstance(requested.get("features"), Mapping):
        features.update(requested["features"])
    if isinstance(editable, Mapping) and isinstance(editable.get("features"), Mapping):
        features.update(editable["features"])
    return features


def _initializer(scenario: Mapping[str, Any]) -> str:
    editable = scenario.get("user_editable") or {}
    config = editable.get("equilibrium_network") if isinstance(editable, Mapping) else None
    if not isinstance(config, Mapping):
        raise NetworkRuntimeConfigurationError(
            "network equilibrium requires user_editable.equilibrium_network"
        )
    initializer = config.get("initializer")
    if initializer not in (SHARED_INITIALIZER, PLATEAU_INITIALIZER):
        raise NetworkRuntimeConfigurationError(
            "unsupported equilibrium network initializer: " + repr(initializer)
        )
    return str(initializer)


def is_network_equilibrium_scenario(scenario: Mapping[str, Any]) -> bool:
    editable = scenario.get("user_editable") or {}
    network_config = editable.get("equilibrium_network") if isinstance(editable, Mapping) else None
    return bool(
        scenario.get("initial_film_regions")
        or scenario.get("initial_junctions")
        or isinstance(network_config, Mapping)
    )


def _require_unique(items: list[Mapping[str, Any]], label: str) -> None:
    ids = [str(item["id"]) for item in items]
    if len(ids) != len(set(ids)):
        raise NetworkRuntimeConfigurationError(f"duplicate {label} ID")


def _validate_static_contract(scenario: Mapping[str, Any]) -> None:
    if scenario.get("requested_fidelity_tier") != "HIGH_FIDELITY":
        raise NetworkRuntimeConfigurationError(
            "equilibrium network runtime requires HIGH_FIDELITY"
        )
    if scenario.get("initial_surface_meshes"):
        raise NetworkRuntimeConfigurationError(
            "accepted network initializers generate their solver mesh; initial_surface_meshes is unsupported"
        )
    gravity = (scenario.get("environment") or {}).get("gravity_m_s2") or ()
    if any(abs(float(value)) > 0.0 for value in gravity):
        raise NetworkRuntimeConfigurationError(
            "equilibrium network runtime supports only zero gravity"
        )

    bubbles = list(scenario.get("initial_bubbles") or [])
    films = list(scenario.get("initial_film_regions") or [])
    junctions = list(scenario.get("initial_junctions") or [])
    if not bubbles or not films:
        raise NetworkRuntimeConfigurationError(
            "network equilibrium requires initial_bubbles and initial_film_regions"
        )
    _require_unique(bubbles, "bubble")
    _require_unique(films, "film")
    _require_unique(junctions, "junction")

    region_ids = {str(bubble["id"]) for bubble in bubbles}
    film_ids = {str(film["id"]) for film in films}
    for bubble in bubbles:
        if any(abs(float(value)) > 0.0 for value in bubble["velocity_m_s"]):
            raise NetworkRuntimeConfigurationError(
                "equilibrium network runtime does not support initial bubble velocity"
            )
        radius = float(bubble["equivalent_radius_m"])
        volume = float(bubble["volume_m3"])
        expected = 4.0 * math.pi * radius ** 3 / 3.0
        if abs(volume - expected) / max(volume, expected) > 1.0e-6:
            raise NetworkRuntimeConfigurationError(
                f"equivalent_radius_m and volume_m3 are inconsistent for {bubble['id']}"
            )

    for film in films:
        adjacent = tuple(str(value) for value in film["adjacent"])
        if len(set(adjacent)) != 2:
            raise NetworkRuntimeConfigurationError(
                f"film {film['id']} has duplicate adjacent regions"
            )
        unknown = [
            value for value in adjacent if value != EXTERIOR and value not in region_ids
        ]
        if unknown:
            raise NetworkRuntimeConfigurationError(
                f"film {film['id']} references unknown region(s): {', '.join(unknown)}"
            )
        exterior_count = adjacent.count(EXTERIOR)
        if film["kind"] == "OUTER" and exterior_count != 1:
            raise NetworkRuntimeConfigurationError(
                f"outer film {film['id']} must have exactly one EXTERIOR adjacency"
            )
        if film["kind"] == "SHARED" and exterior_count != 0:
            raise NetworkRuntimeConfigurationError(
                f"shared film {film['id']} cannot reference EXTERIOR"
            )

    for junction in junctions:
        incident = [str(value) for value in junction["incident_film_ids"]]
        if len(incident) != 3 or len(set(incident)) != 3:
            raise NetworkRuntimeConfigurationError(
                f"junction {junction['id']} must reference exactly three unique films"
            )
        missing = [film_id for film_id in incident if film_id not in film_ids]
        if missing:
            raise NetworkRuntimeConfigurationError(
                f"junction {junction['id']} references missing film(s): {', '.join(missing)}"
            )

    features = _requested_features(scenario)
    forbidden = (
        "drainage",
        "surfactant_diffusion",
        "variable_surface_tension",
        "gas_diffusion",
        "coarsening",
        "transient_contact_detection",
        "dynamic_shared_films",
        "dynamic_multi_junction_transport",
    )
    bad = sorted(name for name in forbidden if bool(features.get(name)))
    if bad:
        raise NetworkRuntimeConfigurationError(
            "equilibrium network runtime does not provide dynamic transport/contact features: "
            + ", ".join(bad)
        )


def _validate_against_result(
    scenario: Mapping[str, Any],
    result: Any,
    *,
    require_junction: bool,
) -> None:
    network = result.network
    declared_bubbles = list(scenario["initial_bubbles"])
    declared_films = list(scenario.get("initial_film_regions") or [])
    declared_junctions = list(scenario.get("initial_junctions") or [])

    expected_region_ids = tuple(region.id for region in network.regions)
    actual_region_ids = tuple(str(bubble["id"]) for bubble in declared_bubbles)
    if actual_region_ids != expected_region_ids:
        raise NetworkRuntimeConfigurationError(
            f"bubble IDs/order {actual_region_ids!r} do not match accepted initializer {expected_region_ids!r}"
        )

    expected_film_ids = tuple(patch.id for patch in network.patches)
    actual_film_ids = tuple(str(film["id"]) for film in declared_films)
    if actual_film_ids != expected_film_ids:
        raise NetworkRuntimeConfigurationError(
            f"film IDs/order {actual_film_ids!r} do not match accepted initializer {expected_film_ids!r}"
        )

    region_by_id = {region.id: region for region in network.regions}
    patch_by_id = {patch.id: patch for patch in network.patches}
    for bubble in declared_bubbles:
        region = region_by_id[str(bubble["id"])]
        if not math.isclose(
            float(bubble["volume_m3"]),
            float(region.target_volume_m3),
            rel_tol=1.0e-12,
            abs_tol=1.0e-18,
        ):
            raise NetworkRuntimeConfigurationError(
                f"bubble {bubble['id']} target volume does not match accepted initializer"
            )

    for film in declared_films:
        patch = patch_by_id[str(film["id"])]
        adjacent = tuple(str(value) for value in film["adjacent"])
        if adjacent != tuple(patch.adjacent):
            raise NetworkRuntimeConfigurationError(
                f"film {film['id']} adjacency/order {adjacent!r} does not match accepted initializer {patch.adjacent!r}"
            )
        if not math.isclose(
            float(film["surface_tension_n_m"]),
            float(patch.sheet_tension_n_m),
            rel_tol=1.0e-12,
            abs_tol=1.0e-15,
        ):
            raise NetworkRuntimeConfigurationError(
                f"film {film['id']} tension does not match accepted initializer"
            )

    expected_junction_ids = tuple(junction.id for junction in network.junctions)
    actual_junction_ids = tuple(str(junction["id"]) for junction in declared_junctions)
    if actual_junction_ids != expected_junction_ids:
        raise NetworkRuntimeConfigurationError(
            f"junction IDs/order {actual_junction_ids!r} do not match accepted initializer {expected_junction_ids!r}"
        )
    if require_junction and len(declared_junctions) != 1:
        raise NetworkRuntimeConfigurationError(
            "accepted Plateau initializer requires exactly one junction"
        )
    for declared, solved in zip(declared_junctions, network.junctions):
        incident = tuple(str(value) for value in declared["incident_film_ids"])
        if incident != tuple(solved.incident_film_ids):
            raise NetworkRuntimeConfigurationError(
                f"junction {declared['id']} incident film order does not match accepted initializer"
            )


def _ambient_pressure(scenario: Mapping[str, Any]) -> float:
    environment = scenario.get("environment") or {}
    return float(environment.get("ambient_pressure_pa", 101325.0))


def _shared_frame(scenario: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    features = _requested_features(scenario)
    if not bool(features.get("shared_films") or features.get("shared_film_topology")):
        raise NetworkRuntimeConfigurationError(
            "accepted shared-film initializer requires shared_films feature disclosure"
        )
    if bool(features.get("plateau_junctions")):
        raise NetworkRuntimeConfigurationError(
            "two-bubble shared-film initializer cannot request plateau_junctions"
        )

    result = unequal_pressure_result()
    _validate_against_result(scenario, result, require_junction=False)
    frame = canonical_shared_film_frame(
        result,
        ambient_pressure_pa=_ambient_pressure(scenario),
        frame_id="equilibrium-network-final",
        random_seed=int(scenario["random_seed"]),
    )
    metrics = b05_unequal_pressure_curvature()
    if not metrics["converged"] or not metrics["deterministic_repeat"]:
        raise RuntimeError("accepted B05 shared-film benchmark is not in an accepted state")
    frame.setdefault("diagnostics", {})["pressure_curvature"] = {
        "benchmark": metrics["benchmark"],
        "producer": "bubblelab.solvers.equilibrium.shared_benchmarks.b05_unequal_pressure_curvature",
        "measurement": metrics["measurement"],
        "pressure_a_pa": metrics["pressure_a_pa"],
        "pressure_b_pa": metrics["pressure_b_pa"],
        "pressure_difference_pa": metrics["pressure_difference_pa"],
        "fitted_curvature_1_m": metrics["fitted_curvature_1_m"],
        "normalized_curvature_error": metrics["normalized_curvature_error"],
        "pressure_curvature_residual": metrics["pressure_curvature_residual"],
        "curvature_fit_rms_m": metrics["curvature_fit_rms_m"],
        "sign_consistent": metrics["sign_consistent"],
    }
    return frame, {
        "identity": "bubblelab-equilibrium",
        "version": frame["manifest"]["solver"]["version"],
        "network_initializer": SHARED_INITIALIZER,
        "quasi_static": "accepted shared-film equilibrium; no transient contact or film formation",
    }


def _plateau_frame(scenario: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    features = _requested_features(scenario)
    if not bool(features.get("shared_films") or features.get("shared_film_topology")):
        raise NetworkRuntimeConfigurationError(
            "accepted Plateau initializer requires shared_films feature disclosure"
        )
    if not bool(features.get("plateau_junctions")):
        raise NetworkRuntimeConfigurationError(
            "accepted Plateau initializer requires plateau_junctions feature disclosure"
        )

    result = plateau_three_result()
    _validate_against_result(scenario, result, require_junction=True)
    frame = canonical_plateau_frame(
        result,
        ambient_pressure_pa=_ambient_pressure(scenario),
        frame_id="equilibrium-network-final",
        random_seed=int(scenario["random_seed"]),
    )
    metrics = plateau_three()
    if not metrics["converged"]:
        raise RuntimeError("accepted B06 Plateau benchmark is not in an accepted state")
    frame.setdefault("diagnostics", {})["plateau_balance"] = {
        "benchmark": metrics["benchmark"],
        "producer": "bubblelab.solvers.equilibrium.plateau_benchmarks.plateau_three",
        "measurement": metrics["measurement"],
        "analytical_reference_deg": metrics["analytical_reference_deg"],
        "angle_rms_error_deg": metrics["angle_rms_error_deg"],
        "angle_max_error_deg": metrics["angle_max_error_deg"],
        "junction_force_residual": metrics["junction_force_residual"],
        "sample_count": len(metrics["measured_angles_deg"]),
    }
    return frame, {
        "identity": "bubblelab-equilibrium",
        "version": frame["manifest"]["solver"]["version"],
        "network_initializer": PLATEAU_INITIALIZER,
        "quasi_static": "accepted Plateau equilibrium; no transient junction transport or contact dynamics",
    }


def run_network_equilibrium(
    scenario: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Map one legal contract-v1 network declaration onto an accepted solver case."""
    _validate_static_contract(scenario)
    initializer = _initializer(scenario)
    if initializer == SHARED_INITIALIZER:
        return _shared_frame(scenario)
    if initializer == PLATEAU_INITIALIZER:
        return _plateau_frame(scenario)
    raise NetworkRuntimeConfigurationError(
        f"unsupported equilibrium network initializer: {initializer}"
    )
