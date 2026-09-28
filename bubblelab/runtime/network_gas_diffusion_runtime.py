"""Runtime adapter for conservative many-bubble gas diffusion.

This backend owns an authoritative no-topology-change gas/shared-film network.
Gas amount is transported on actual declared shared-film edges, and each amount
update is immediately closed back to bubble volume and pressure.
"""
from __future__ import annotations

from dataclasses import asdict
import copy
import math
from typing import Any, Mapping

from bubblelab.solvers.gas_network import (
    GasNetworkState,
    GasRegionState,
    SharedFilmEdge,
    TopologyChangeRequired,
    advance_gas_network,
    equilibrium_amount_mol,
    sphere_volume_m3,
)

VERSION = "0.1.0"


class NetworkGasDiffusionRuntimeConfigurationError(ValueError):
    """Raised when a scenario is outside the supported network class."""


def _features(scenario: Mapping[str, Any]) -> Mapping[str, Any]:
    requested = scenario.get("requested_solver") or {}
    features = requested.get("features") if isinstance(requested, Mapping) else None
    return features if isinstance(features, Mapping) else {}


def _config(scenario: Mapping[str, Any]) -> Mapping[str, Any]:
    editable = scenario.get("user_editable") or {}
    config = editable.get("gas_diffusion") if isinstance(editable, Mapping) else None
    if not isinstance(config, Mapping):
        raise NetworkGasDiffusionRuntimeConfigurationError(
            "many-bubble gas diffusion requires user_editable.gas_diffusion"
        )
    return config


def _validate_supported_features(scenario: Mapping[str, Any]) -> None:
    if scenario.get("requested_fidelity_tier") != "HIGH_FIDELITY":
        raise NetworkGasDiffusionRuntimeConfigurationError(
            "many-bubble gas diffusion runtime requires HIGH_FIDELITY"
        )
    features = _features(scenario)
    if not bool(features.get("shared_films")):
        raise NetworkGasDiffusionRuntimeConfigurationError(
            "shared_films feature disclosure is required"
        )
    if not bool(features.get("gas_diffusion")):
        raise NetworkGasDiffusionRuntimeConfigurationError(
            "gas_diffusion feature disclosure is required"
        )
    unsupported = (
        "dynamic_shared_films",
        "t1",
        "t1_topology_surgery",
        "rupture",
        "coalescence",
    )
    bad = sorted(name for name in unsupported if bool(features.get(name)))
    if bad:
        raise NetworkGasDiffusionRuntimeConfigurationError(
            "topology-changing feature(s) are outside the fixed-topology gas interval: "
            + ", ".join(bad)
        )


def state_from_scenario(scenario: Mapping[str, Any]) -> GasNetworkState:
    _validate_supported_features(scenario)
    config = _config(scenario)
    environment = scenario.get("environment") or {}
    ambient = float(environment.get("ambient_pressure_pa", 101325.0))
    default_temperature = float(config.get("temperature_k", 298.15))
    default_tension = float(config.get("surface_tension_n_m", 0.03))
    default_permeability = float(
        config.get("permeability_mol_m_per_m2_s_pa", 1.0e-11)
    )

    bubbles = list(scenario.get("initial_bubbles") or [])
    films = list(scenario.get("initial_film_regions") or [])
    if len(bubbles) < 3:
        raise NetworkGasDiffusionRuntimeConfigurationError(
            "many-bubble gas diffusion requires at least three gas regions"
        )

    regions: list[GasRegionState] = []
    bubble_ids: list[str] = []
    for bubble in bubbles:
        region_id = str(bubble.get("id", ""))
        if not region_id:
            raise NetworkGasDiffusionRuntimeConfigurationError(
                "every initial bubble requires a stable id"
            )
        if region_id in bubble_ids:
            raise NetworkGasDiffusionRuntimeConfigurationError(
                "initial bubble ids must be unique"
            )
        bubble_ids.append(region_id)
        volume = float(bubble["volume_m3"])
        radius = float(bubble["equivalent_radius_m"])
        radius_volume = sphere_volume_m3(radius)
        if abs(radius_volume - volume) / max(abs(volume), abs(radius_volume)) > 1.0e-9:
            raise NetworkGasDiffusionRuntimeConfigurationError(
                f"bubble {region_id} radius and volume are inconsistent"
            )
        temperature = float(bubble.get("temperature_k", default_temperature))
        tension = float(bubble.get("surface_tension_n_m", default_tension))
        amount = bubble.get("amount_mol")
        if amount is None:
            amount_value = equilibrium_amount_mol(
                volume, ambient, tension, temperature
            )
        else:
            amount_value = float(amount)
        regions.append(
            GasRegionState(
                id=region_id,
                amount_mol=amount_value,
                volume_m3=volume,
                temperature_k=temperature,
                surface_tension_n_m=tension,
            )
        )

    edges: list[SharedFilmEdge] = []
    for film in films:
        if str(film.get("kind")) != "SHARED":
            continue
        adjacent = tuple(str(value) for value in (film.get("adjacent") or ()))
        if len(adjacent) != 2:
            raise NetworkGasDiffusionRuntimeConfigurationError(
                "each shared film must declare exactly two adjacent gas regions"
            )
        edges.append(
            SharedFilmEdge(
                id=str(film["id"]),
                region_a=adjacent[0],
                region_b=adjacent[1],
                shared_area_m2=float(film["shared_area_m2"]),
                film_thickness_m=float(film["film_thickness_m"]),
                permeability_mol_m_per_m2_s_pa=float(
                    film.get(
                        "permeability_mol_m_per_m2_s_pa",
                        default_permeability,
                    )
                ),
            )
        )
    if len(edges) < 2:
        raise NetworkGasDiffusionRuntimeConfigurationError(
            "many-bubble gas diffusion requires at least two shared-film transfer edges"
        )

    state = GasNetworkState(
        regions=regions,
        edges=tuple(edges),
        ambient_pressure_pa=ambient,
        diffusion_enabled=bool(config.get("enabled", True)),
        positivity_safety=float(config.get("positivity_safety", 0.45)),
    )
    state.validate()
    try:
        state.assert_constitutive_consistency()
    except ValueError as exc:
        raise NetworkGasDiffusionRuntimeConfigurationError(str(exc)) from exc
    return state


class NetworkGasDiffusionRuntime:
    def __init__(self, scenario: Mapping[str, Any]):
        self.scenario = copy.deepcopy(dict(scenario))
        self.state = state_from_scenario(self.scenario)
        config = _config(self.scenario)
        self.dt_s = float(config.get("dt_s", 0.025))
        self.steps_per_frame = int(config.get("steps_per_frame", 4))
        if self.dt_s <= 0.0 or self.steps_per_frame < 1:
            raise NetworkGasDiffusionRuntimeConfigurationError(
                "dt_s must be positive and steps_per_frame must be at least one"
            )
        self.initial_region_ids = self.state.region_ids()
        self.initial_edge_ids = self.state.edge_ids()
        self.worst_total_moles_drift = 0.0
        self.worst_edge_antisymmetry_residual_mol = 0.0
        self.max_simultaneous_active_edges = 0
        self.cumulative_edge_transfer_mol = {
            edge.id: 0.0 for edge in self.state.edges
        }

    def _frame(self, frame_index: int) -> dict[str, Any]:
        bubbles = [
            {
                "id": region.id,
                "amount_mol": region.amount_mol,
                "volume_m3": region.volume_m3,
                "equivalent_radius_m": region.equivalent_radius_m(),
                "pressure_pa": region.pressure_pa(),
                "temperature_k": region.temperature_k,
                "surface_tension_n_m": region.surface_tension_n_m,
                "status": "ALIVE",
            }
            for region in self.state.regions
        ]
        film_regions = [
            {
                "id": edge.id,
                "kind": "SHARED",
                "adjacent": [edge.region_a, edge.region_b],
                "shared_area_m2": edge.shared_area_m2,
                "film_thickness_m": edge.film_thickness_m,
                "conductance_mol_s_pa": edge.conductance_mol_s_pa,
                "cumulative_transfer_a_to_b_mol": self.cumulative_edge_transfer_mol[
                    edge.id
                ],
            }
            for edge in self.state.edges
        ]
        return {
            "kind": "FRAME",
            "frame_index": frame_index,
            "time_s": self.state.time_s,
            "backend": "manybubble-gas-diffusion-network",
            "backend_version": VERSION,
            "bubbles": bubbles,
            "film_regions": film_regions,
            "adjacency": [
                {"a": edge.region_a, "b": edge.region_b, "film_id": edge.id}
                for edge in self.state.edges
            ],
            "diagnostics": {
                "gas_diffusion_enabled": self.state.diffusion_enabled,
                "total_amount_mol": self.state.total_amount_mol(),
                "worst_total_moles_relative_drift": self.worst_total_moles_drift,
                "worst_edge_antisymmetry_residual_mol": (
                    self.worst_edge_antisymmetry_residual_mol
                ),
                "max_simultaneous_active_edges": (
                    self.max_simultaneous_active_edges
                ),
                "fixed_topology_interval": True,
                "region_ids": list(self.state.region_ids()),
                "edge_ids": list(self.state.edge_ids()),
            },
            "provenance": {
                "authoritative_state": (
                    "coupled ideal-gas/Young-Laplace volumes on declared shared-film network"
                ),
                "transport_update": (
                    "simultaneous conservative edge flux accumulation"
                ),
                "topology_change_support": "REJECTED",
            },
        }

    def initial_frame(self) -> dict[str, Any]:
        return self._frame(0)

    def advance_frame(self, frame_index: int) -> dict[str, Any]:
        for _ in range(self.steps_per_frame):
            diag = advance_gas_network(self.state, self.dt_s)
            self.worst_total_moles_drift = max(
                self.worst_total_moles_drift, diag.total_relative_drift
            )
            self.worst_edge_antisymmetry_residual_mol = max(
                self.worst_edge_antisymmetry_residual_mol,
                diag.max_edge_antisymmetry_residual_mol,
            )
            self.max_simultaneous_active_edges = max(
                self.max_simultaneous_active_edges,
                diag.max_simultaneous_active_edges,
            )
            for edge_diag in diag.edges:
                edge_id = edge_diag.edge_id
                self.cumulative_edge_transfer_mol[edge_id] = math.fsum(
                    (
                        self.cumulative_edge_transfer_mol[edge_id],
                        edge_diag.integrated_a_to_b_mol,
                    )
                )

        if self.state.region_ids() != self.initial_region_ids:
            raise TopologyChangeRequired("gas region identity changed during runtime")
        if self.state.edge_ids() != self.initial_edge_ids:
            raise TopologyChangeRequired("shared-film identity changed during runtime")
        return self._frame(frame_index)


def run_frames(scenario: Mapping[str, Any], frame_count: int = 9) -> list[dict[str, Any]]:
    if frame_count < 1:
        raise ValueError("frame_count must be at least one")
    runtime = NetworkGasDiffusionRuntime(scenario)
    frames = [runtime.initial_frame()]
    for frame_index in range(1, frame_count):
        frames.append(runtime.advance_frame(frame_index))
    return frames
