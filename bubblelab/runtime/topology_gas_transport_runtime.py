"""Runtime for conservative many-bubble gas transport through one real T1 event."""
from __future__ import annotations

import copy
import math
from typing import Any, Mapping

from bubblelab.solvers.gas_network.topology import (
    TopologyGasEventDiagnostics,
    supported_t1_gas_transport_state,
)

VERSION = "0.1.0"
FIXTURE = "accepted-four-region-extruded-t1"


class TopologyGasTransportRuntimeConfigurationError(ValueError):
    """Raised when a scenario is outside the bounded topology-changing class."""


def _features(scenario: Mapping[str, Any]) -> Mapping[str, Any]:
    requested = scenario.get("requested_solver") or {}
    features = requested.get("features") if isinstance(requested, Mapping) else None
    return features if isinstance(features, Mapping) else {}


def _config(scenario: Mapping[str, Any]) -> Mapping[str, Any]:
    editable = scenario.get("user_editable") or {}
    config = editable.get("topology_gas_transport") if isinstance(editable, Mapping) else None
    if not isinstance(config, Mapping):
        raise TopologyGasTransportRuntimeConfigurationError(
            "topology-changing gas transport requires user_editable.topology_gas_transport"
        )
    return config


def _validate_supported_scenario(scenario: Mapping[str, Any]) -> None:
    if scenario.get("requested_fidelity_tier") != "HIGH_FIDELITY":
        raise TopologyGasTransportRuntimeConfigurationError(
            "topology-changing gas transport requires HIGH_FIDELITY"
        )
    features = _features(scenario)
    required = ("shared_films", "gas_diffusion", "t1", "t1_topology_surgery")
    missing = [name for name in required if not bool(features.get(name))]
    if missing:
        raise TopologyGasTransportRuntimeConfigurationError(
            "required feature disclosure is missing: " + ", ".join(missing)
        )
    unsupported = ("rupture", "coalescence", "vanishing_region_remap")
    bad = [name for name in unsupported if bool(features.get(name))]
    if bad:
        raise TopologyGasTransportRuntimeConfigurationError(
            "unsupported topology-changing gas transport feature(s): " + ", ".join(bad)
        )
    if str(_config(scenario).get("fixture", "")) != FIXTURE:
        raise TopologyGasTransportRuntimeConfigurationError(
            "runtime supports only the accepted isolated four-region extruded T1 fixture"
        )


class TopologyGasTransportRuntime:
    def __init__(self, scenario: Mapping[str, Any]):
        self.scenario = copy.deepcopy(dict(scenario))
        _validate_supported_scenario(self.scenario)
        config = _config(self.scenario)
        self.dt_s = float(config.get("dt_s", 0.05))
        self.steps_per_frame = int(config.get("steps_per_frame", 2))
        self.t1_frame_index = int(config.get("t1_frame_index", 3))
        if self.dt_s <= 0.0 or self.steps_per_frame < 1 or self.t1_frame_index < 1:
            raise TopologyGasTransportRuntimeConfigurationError(
                "dt_s must be positive, steps_per_frame >= 1 and t1_frame_index >= 1"
            )
        self.state = supported_t1_gas_transport_state(
            diffusion_enabled=bool(config.get("enabled", True)),
            permeability_mol_m_per_m2_s_pa=float(
                config.get("permeability_mol_m_per_m2_s_pa", 1.0e-8)
            ),
            film_thickness_m=float(config.get("film_thickness_m", 8.0e-7)),
        )
        self.initial_region_ids = self.state.gas_state.region_ids()
        self.initial_total_mol = self.state.gas_state.total_amount_mol()
        self.event: TopologyGasEventDiagnostics | None = None
        self.worst_total_moles_relative_drift = 0.0
        self.worst_edge_antisymmetry_residual_mol = 0.0
        self.max_simultaneous_active_edges = 0
        self.cumulative_edge_transfer_mol: dict[str, float] = {
            edge.id: 0.0 for edge in self.state.gas_state.edges
        }

    def _accumulate(self, diag: Any) -> None:
        self.worst_total_moles_relative_drift = max(
            self.worst_total_moles_relative_drift,
            diag.total_relative_drift,
        )
        self.worst_edge_antisymmetry_residual_mol = max(
            self.worst_edge_antisymmetry_residual_mol,
            diag.max_edge_antisymmetry_residual_mol,
        )
        self.max_simultaneous_active_edges = max(
            self.max_simultaneous_active_edges,
            diag.max_simultaneous_active_edges,
        )
        for item in diag.edges:
            self.cumulative_edge_transfer_mol[item.edge_id] = math.fsum(
                (
                    self.cumulative_edge_transfer_mol.get(item.edge_id, 0.0),
                    item.integrated_a_to_b_mol,
                )
            )

    def _event_record(self) -> dict[str, Any] | None:
        if self.event is None:
            return None
        return {
            "event_id": self.event.event_id,
            "retired_film_ids": list(self.event.retired_film_ids),
            "created_film_ids": list(self.event.created_film_ids),
            "adjacency_before": [list(item) for item in self.event.adjacency_before],
            "adjacency_after": [list(item) for item in self.event.adjacency_after],
            "gas_amount_relative_drift": self.event.total_relative_drift,
            "gas_state_unchanged_during_surgery": (
                self.event.amount_before_mol == self.event.amount_after_mol
                and self.event.volume_before_m3 == self.event.volume_after_m3
                and self.event.pressure_before_pa == self.event.pressure_after_pa
            ),
        }

    def _frame(self, frame_index: int) -> dict[str, Any]:
        gas = self.state.gas_state
        topology = self.state.topology_state.to_network()
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
            for region in gas.regions
        ]
        film_regions = [
            {
                "id": edge.id,
                "kind": "SHARED",
                "adjacent": [edge.region_a, edge.region_b],
                "shared_area_m2": edge.shared_area_m2,
                "film_thickness_m": edge.film_thickness_m,
                "conductance_mol_s_pa": edge.conductance_mol_s_pa,
                "cumulative_transfer_a_to_b_mol": self.cumulative_edge_transfer_mol.get(
                    edge.id, 0.0
                ),
            }
            for edge in gas.edges
        ]
        junctions = [
            {
                "id": junction.id,
                "incident_film_ids": list(junction.incident_film_ids),
            }
            for junction in topology.junctions
        ]
        total = gas.total_amount_mol()
        total_drift = abs(total - self.initial_total_mol) / self.initial_total_mol
        return {
            "kind": "FRAME",
            "frame_index": frame_index,
            "time_s": gas.time_s,
            "backend": "topology-changing-gas-transport",
            "backend_version": VERSION,
            "bubbles": bubbles,
            "film_regions": film_regions,
            "junctions": junctions,
            "adjacency": [
                {"a": edge.region_a, "b": edge.region_b, "film_id": edge.id}
                for edge in gas.edges
            ],
            "topology_event": self._event_record(),
            "diagnostics": {
                "gas_diffusion_enabled": gas.diffusion_enabled,
                "total_amount_mol": total,
                "total_amount_relative_drift_from_initial": total_drift,
                "worst_transport_step_relative_drift": self.worst_total_moles_relative_drift,
                "worst_edge_antisymmetry_residual_mol": (
                    self.worst_edge_antisymmetry_residual_mol
                ),
                "max_simultaneous_active_edges": self.max_simultaneous_active_edges,
                "topology_revision": gas.topology_revision,
                "region_ids": list(gas.region_ids()),
                "edge_ids": list(gas.edge_ids()),
                "event_performed": self.event is not None,
            },
            "provenance": {
                "gas_state": "coupled ideal-gas/Young-Laplace amount-pressure-volume state",
                "transport_update": "simultaneous conservative shared-film edge accumulation",
                "topology_source": "authoritative FilmNetwork production T1 transaction",
                "post_event_graph": "rebuilt from real internal films in canonical post-T1 topology",
                "claim_boundary": "one isolated supported four-region T1; rupture/coalescence/vanishing remap unsupported",
            },
        }

    def initial_frame(self) -> dict[str, Any]:
        return self._frame(0)

    def advance_frame(self, frame_index: int) -> dict[str, Any]:
        if self.event is None and frame_index == self.t1_frame_index:
            self.event = self.state.perform_t1()
            for edge in self.state.gas_state.edges:
                self.cumulative_edge_transfer_mol.setdefault(edge.id, 0.0)
        for _ in range(self.steps_per_frame):
            self._accumulate(self.state.advance(self.dt_s))
        if self.state.gas_state.region_ids() != self.initial_region_ids:
            raise RuntimeError("stable gas-region identities changed during runtime")
        if self.state.gas_state.topology_revision > 1:
            raise RuntimeError("bounded runtime supports exactly one T1 transaction")
        return self._frame(frame_index)


def run_frames(
    scenario: Mapping[str, Any],
    frame_count: int = 7,
) -> list[dict[str, Any]]:
    if frame_count < 1:
        raise ValueError("frame_count must be at least one")
    runtime = TopologyGasTransportRuntime(scenario)
    frames = [runtime.initial_frame()]
    for frame_index in range(1, frame_count):
        frames.append(runtime.advance_frame(frame_index))
    return frames
