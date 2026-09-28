"""Runtime for one continuous gas history crossing two dependent production T1s."""
from __future__ import annotations

import copy
import math
from typing import Any, Mapping

from bubblelab.solvers.gas_network.repeated_topology import (
    supported_repeated_t1_gas_transport_state,
)
from bubblelab.solvers.gas_network.topology import TopologyGasEventDiagnostics

VERSION = "0.2.0"
FIXTURE = "accepted-dependent-two-t1-extruded"


class RepeatedTopologyGasTransportRuntimeConfigurationError(ValueError):
    """Raised when a scenario lies outside the bounded repeated-T1 class."""


def _features(scenario: Mapping[str, Any]) -> Mapping[str, Any]:
    requested = scenario.get("requested_solver") or {}
    features = requested.get("features") if isinstance(requested, Mapping) else None
    return features if isinstance(features, Mapping) else {}


def _config(scenario: Mapping[str, Any]) -> Mapping[str, Any]:
    editable = scenario.get("user_editable") or {}
    config = editable.get("repeated_topology_gas_transport") if isinstance(editable, Mapping) else None
    if not isinstance(config, Mapping):
        raise RepeatedTopologyGasTransportRuntimeConfigurationError(
            "repeated topology gas transport requires user_editable.repeated_topology_gas_transport"
        )
    return config


def _validate_supported_scenario(scenario: Mapping[str, Any]) -> None:
    if scenario.get("requested_fidelity_tier") != "HIGH_FIDELITY":
        raise RepeatedTopologyGasTransportRuntimeConfigurationError(
            "repeated topology gas transport requires HIGH_FIDELITY"
        )
    features = _features(scenario)
    required = ("shared_films", "gas_diffusion", "t1", "t1_topology_surgery")
    missing = [name for name in required if not bool(features.get(name))]
    if missing:
        raise RepeatedTopologyGasTransportRuntimeConfigurationError(
            "required feature disclosure is missing: " + ", ".join(missing)
        )
    unsupported = ("rupture", "coalescence", "vanishing_region_remap")
    bad = [name for name in unsupported if bool(features.get(name))]
    if bad:
        raise RepeatedTopologyGasTransportRuntimeConfigurationError(
            "unsupported repeated topology feature(s): " + ", ".join(bad)
        )
    if str(_config(scenario).get("fixture", "")) != FIXTURE:
        raise RepeatedTopologyGasTransportRuntimeConfigurationError(
            "runtime supports only the accepted dependent two-T1 extruded fixture"
        )


class RepeatedTopologyGasTransportRuntime:
    def __init__(self, scenario: Mapping[str, Any]):
        self.scenario = copy.deepcopy(dict(scenario))
        _validate_supported_scenario(self.scenario)
        config = _config(self.scenario)
        self.dt_s = float(config.get("dt_s", 0.05))
        self.steps_per_frame = int(config.get("steps_per_frame", 2))
        raw_event_frames = config.get("t1_frame_indices", [2, 4])
        if not isinstance(raw_event_frames, list) or len(raw_event_frames) != 2:
            raise RepeatedTopologyGasTransportRuntimeConfigurationError(
                "t1_frame_indices must contain exactly two frame indices"
            )
        self.t1_frame_indices = tuple(int(value) for value in raw_event_frames)
        if (
            self.dt_s <= 0.0
            or self.steps_per_frame < 1
            or self.t1_frame_indices[0] < 1
            or self.t1_frame_indices[1] <= self.t1_frame_indices[0]
        ):
            raise RepeatedTopologyGasTransportRuntimeConfigurationError(
                "dt_s must be positive, steps_per_frame >= 1 and T1 frames strictly increasing"
            )
        self.state = supported_repeated_t1_gas_transport_state(
            diffusion_enabled=bool(config.get("enabled", True)),
            permeability_mol_m_per_m2_s_pa=float(
                config.get("permeability_mol_m_per_m2_s_pa", 1.0e-8)
            ),
            film_thickness_m=float(config.get("film_thickness_m", 8.0e-7)),
        )
        second_initial = self.state.event_eligibility(2)
        self.second_event_initially_blocked = not second_initial.eligible
        self.second_event_initial_block_reason = second_initial.reason
        if not self.second_event_initially_blocked:
            raise RuntimeError("second T1 must be topologically invalid before the first event")
        self.initial_region_ids = self.state.gas_state.region_ids()
        self.initial_total_mol = self.state.gas_state.total_amount_mol()
        self.events: list[tuple[int, TopologyGasEventDiagnostics]] = []
        self.worst_total_moles_relative_drift = 0.0
        self.worst_edge_antisymmetry_residual_mol = 0.0
        self.max_simultaneous_active_edges = 0
        self.cumulative_edge_transfer_mol: dict[str, float] = {
            edge.id: 0.0 for edge in self.state.gas_state.edges
        }

    def _accumulate(self, diag: Any) -> None:
        self.worst_total_moles_relative_drift = max(
            self.worst_total_moles_relative_drift, diag.total_relative_drift
        )
        self.worst_edge_antisymmetry_residual_mol = max(
            self.worst_edge_antisymmetry_residual_mol,
            diag.max_edge_antisymmetry_residual_mol,
        )
        self.max_simultaneous_active_edges = max(
            self.max_simultaneous_active_edges, diag.max_simultaneous_active_edges
        )
        for item in diag.edges:
            self.cumulative_edge_transfer_mol[item.edge_id] = math.fsum(
                (
                    self.cumulative_edge_transfer_mol.get(item.edge_id, 0.0),
                    item.integrated_a_to_b_mol,
                )
            )

    @staticmethod
    def _event_record(frame_index: int, event: TopologyGasEventDiagnostics) -> dict[str, Any]:
        return {
            "frame_index": frame_index,
            "event_id": event.event_id,
            "retired_film_ids": list(event.retired_film_ids),
            "created_film_ids": list(event.created_film_ids),
            "adjacency_before": [list(item) for item in event.adjacency_before],
            "adjacency_after": [list(item) for item in event.adjacency_after],
            "gas_amount_relative_drift": event.total_relative_drift,
            "gas_state_unchanged_during_surgery": (
                event.amount_before_mol == event.amount_after_mol
                and event.volume_before_m3 == event.volume_after_m3
                and event.pressure_before_pa == event.pressure_after_pa
            ),
            "topology_revision_before": event.topology_revision_before,
            "topology_revision_after": event.topology_revision_after,
        }

    def _frame(self, frame_index: int) -> dict[str, Any]:
        gas = self.state.gas_state
        topology = self.state.topology_state.to_network()
        total = gas.total_amount_mol()
        total_drift = abs(total - self.initial_total_mol) / max(
            abs(self.initial_total_mol), 1.0e-300
        )
        return {
            "kind": "FRAME",
            "frame_index": frame_index,
            "time_s": gas.time_s,
            "backend": "repeated-topology-changing-gas-transport",
            "backend_version": VERSION,
            "bubbles": [
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
            ],
            "film_regions": [
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
            ],
            "junctions": [
                {
                    "id": junction.id,
                    "incident_film_ids": list(junction.incident_film_ids),
                }
                for junction in topology.junctions
            ],
            "adjacency": [
                {"a": edge.region_a, "b": edge.region_b, "film_id": edge.id}
                for edge in gas.edges
            ],
            "topology_events": [
                self._event_record(index, event) for index, event in self.events
            ],
            "diagnostics": {
                "gas_diffusion_enabled": gas.diffusion_enabled,
                "total_amount_mol": total,
                "total_amount_relative_drift_from_initial": total_drift,
                "worst_transport_step_relative_drift": self.worst_total_moles_relative_drift,
                "worst_edge_antisymmetry_residual_mol": self.worst_edge_antisymmetry_residual_mol,
                "max_simultaneous_active_edges": self.max_simultaneous_active_edges,
                "topology_revision": gas.topology_revision,
                "region_ids": list(gas.region_ids()),
                "edge_ids": list(gas.edge_ids()),
                "event_count": len(self.events),
                "second_event_blocked_before_first": self.second_event_initially_blocked,
                "second_event_initial_block_reason": self.second_event_initial_block_reason,
                "edge_transfer_history_mol": dict(sorted(self.cumulative_edge_transfer_mol.items())),
            },
            "provenance": {
                "gas_state": "one continuous coupled ideal-gas/Young-Laplace history",
                "transport_update": "simultaneous conservative shared-film edge accumulation",
                "topology_source": "canonical six-region FilmNetwork with two production T1 transactions",
                "post_event_graph": "rebuilt from real internal films after each T1",
                "second_event_dependency": "event 2 E/F->A/B is blocked by the initial A/B film and becomes eligible only after event 1 removes that adjacency",
                "claim_boundary": "two distinct dependent supported T1s; rupture/coalescence/vanishing remap unsupported",
            },
        }

    def initial_frame(self) -> dict[str, Any]:
        return self._frame(0)

    def advance_frame(self, frame_index: int) -> dict[str, Any]:
        if frame_index in self.t1_frame_indices:
            expected_number = self.t1_frame_indices.index(frame_index) + 1
            if len(self.events) != expected_number - 1:
                raise RuntimeError("repeated T1 event ordering is inconsistent")
            if expected_number == 2 and not self.state.event_eligibility(2).eligible:
                raise RuntimeError("first canonical T1 did not enable the second distinct production T1")
            event = self.state.perform_t1()
            self.events.append((frame_index, event))
            for edge in self.state.gas_state.edges:
                self.cumulative_edge_transfer_mol.setdefault(edge.id, 0.0)
        for _ in range(self.steps_per_frame):
            self._accumulate(self.state.advance(self.dt_s))
        if self.state.gas_state.region_ids() != self.initial_region_ids:
            raise RuntimeError("stable gas-region identities changed during repeated runtime")
        if self.state.gas_state.topology_revision > 2:
            raise RuntimeError("bounded repeated runtime supports exactly two T1 transactions")
        return self._frame(frame_index)


def run_frames(
    scenario: Mapping[str, Any],
    frame_count: int = 7,
) -> list[dict[str, Any]]:
    if frame_count < 1:
        raise ValueError("frame_count must be at least one")
    runtime = RepeatedTopologyGasTransportRuntime(scenario)
    frames = [runtime.initial_frame()]
    for frame_index in range(1, frame_count):
        frames.append(runtime.advance_frame(frame_index))
    return frames
