"""Runtime for one continuous gas history crossing a causal multi-event topology sequence."""
from __future__ import annotations

import copy
import math
from typing import Any, Mapping

from bubblelab.solvers.gas_network.multievent_topology import (
    supported_multievent_topology_gas_state,
)

VERSION = "0.1.0"
FIXTURE = "accepted-causal-four-t1-plus-rupture-coalescence"


class MultiEventTopologyGasRuntimeConfigurationError(ValueError):
    pass


def _features(scenario: Mapping[str, Any]) -> Mapping[str, Any]:
    requested = scenario.get("requested_solver") or {}
    features = requested.get("features") if isinstance(requested, Mapping) else None
    return features if isinstance(features, Mapping) else {}


def _config(scenario: Mapping[str, Any]) -> Mapping[str, Any]:
    editable = scenario.get("user_editable") or {}
    config = editable.get("multievent_topology_gas") if isinstance(editable, Mapping) else None
    if not isinstance(config, Mapping):
        raise MultiEventTopologyGasRuntimeConfigurationError(
            "multi-event topology gas runtime requires user_editable.multievent_topology_gas"
        )
    return config


def _validate_supported_scenario(scenario: Mapping[str, Any]) -> None:
    if scenario.get("requested_fidelity_tier") != "HIGH_FIDELITY":
        raise MultiEventTopologyGasRuntimeConfigurationError(
            "multi-event topology gas runtime requires HIGH_FIDELITY"
        )
    features = _features(scenario)
    required = (
        "shared_films",
        "gas_diffusion",
        "t1",
        "t1_topology_surgery",
        "rupture",
        "coalescence",
    )
    missing = [name for name in required if not bool(features.get(name))]
    if missing:
        raise MultiEventTopologyGasRuntimeConfigurationError(
            "required feature disclosure is missing: " + ", ".join(missing)
        )
    if str(_config(scenario).get("fixture", "")) != FIXTURE:
        raise MultiEventTopologyGasRuntimeConfigurationError(
            "runtime supports only the accepted causal multi-event fixture"
        )


class MultiEventTopologyGasRuntime:
    def __init__(self, scenario: Mapping[str, Any]):
        self.scenario = copy.deepcopy(dict(scenario))
        _validate_supported_scenario(self.scenario)
        config = _config(self.scenario)
        self.dt_s = float(config.get("dt_s", 0.05))
        self.steps_per_frame = int(config.get("steps_per_frame", 1))
        if self.dt_s <= 0.0 or self.steps_per_frame < 1:
            raise MultiEventTopologyGasRuntimeConfigurationError(
                "dt_s must be positive and steps_per_frame must be >= 1"
            )
        self.state = supported_multievent_topology_gas_state(
            diffusion_enabled=bool(config.get("enabled", True)),
            permeability_mol_m_per_m2_s_pa=float(
                config.get("permeability_mol_m_per_m2_s_pa", 1.0e-8)
            ),
            film_thickness_m=float(config.get("film_thickness_m", 8.0e-7)),
        )
        self.initial_region_ids = self.state.gas_state.region_ids()
        self.initial_total_mol = self.state.gas_state.total_amount_mol()
        self.initial_blocked = {
            number: self.state.event_eligibility(number).reason
            for number in (2, 3, 4)
        }
        self.initial_rupture_reason = self.state.rupture_coalescence_eligibility().reason
        self.events: list[dict[str, Any]] = []
        self.transaction_count = 0
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

    def _record_t1(self, frame_index: int, event: Any) -> None:
        self.events.append(
            {
                "frame_index": frame_index,
                "transaction_index": self.transaction_count,
                "event_id": event.event_id,
                "type": "T1",
                "retired_film_ids": list(event.retired_film_ids),
                "created_film_ids": list(event.created_film_ids),
                "region_ids_before": list(event.region_ids_before),
                "region_ids_after": list(event.region_ids_after),
                "gas_amount_relative_drift": event.total_relative_drift,
                "unaffected_state_exact": (
                    event.amount_before_mol == event.amount_after_mol
                    and event.volume_before_m3 == event.volume_after_m3
                    and event.pressure_before_pa == event.pressure_after_pa
                ),
                "topology_revision_before": event.topology_revision_before,
                "topology_revision_after": event.topology_revision_after,
            }
        )

    def _record_rc(self, frame_index: int, diag: Any) -> None:
        for event in diag.emitted_events:
            self.events.append(
                {
                    "frame_index": frame_index,
                    "transaction_index": self.transaction_count,
                    "event_id": event.id,
                    "type": event.type,
                    "retired_film_ids": list(diag.retired_film_ids),
                    "created_film_ids": [],
                    "region_ids_before": list(diag.region_ids_before),
                    "region_ids_after": list(diag.region_ids_after),
                    "gas_amount_relative_drift": diag.total_relative_drift,
                    "unaffected_state_exact": diag.unaffected_state_exact,
                    "topology_revision_before": diag.topology_revision_before,
                    "topology_revision_after": diag.topology_revision_after,
                    "parent_region_ids": list(diag.parent_region_ids),
                    "child_region_id": diag.child_region_id,
                    "lineage": list(diag.lineage),
                    "criterion": event.criterion,
                }
            )

    def _execute_next_eligible_transaction(self, frame_index: int) -> None:
        revision = self.state.gas_state.topology_revision
        if revision < 4:
            event_number = revision + 1
            eligibility = self.state.event_eligibility(event_number)
            if not eligibility.eligible:
                raise RuntimeError(
                    f"causal T1 event {event_number} did not become eligible: {eligibility.reason}"
                )
            self.transaction_count += 1
            event = self.state.perform_next_t1()
            self._record_t1(frame_index, event)
        elif revision == 4:
            eligibility = self.state.rupture_coalescence_eligibility()
            if not eligibility.eligible:
                raise RuntimeError(
                    "event-4 topology did not enable rupture/coalescence: "
                    + eligibility.reason
                )
            self.transaction_count += 1
            diag = self.state.perform_rupture_coalescence()
            self._record_rc(frame_index, diag)
        elif revision != 6:
            raise RuntimeError("unexpected topology revision")
        for edge in self.state.gas_state.edges:
            self.cumulative_edge_transfer_mol.setdefault(edge.id, 0.0)

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
            "backend": "multievent-topology-changing-gas-network",
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
            "topology_events": copy.deepcopy(self.events),
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
                "transaction_count": self.transaction_count,
                "topology_event_count": len(self.events),
                "initial_blocked_t1_reasons": dict(self.initial_blocked),
                "initial_rupture_block_reason": self.initial_rupture_reason,
                "edge_transfer_history_mol": dict(sorted(self.cumulative_edge_transfer_mol.items())),
            },
            "provenance": {
                "gas_state": "one continuous coupled ideal-gas/Young-Laplace history",
                "topology_source": "one canonical ten-region FilmNetwork, never reset between events",
                "event_schedule": "eligibility checked from evolved canonical topology after each transport interval; no event timestamps or frame indices are configured",
                "causal_chain": "AB->CD enables EF->AB, which enables GH->EF, which enables IJ->GH; the event-4-created GH film alone enables rupture/coalescence",
                "post_event_graph": "rebuilt from real internal films after every topology transaction",
                "claim_boundary": "bounded four-dependent-T1 plus one rupture/coalescence transaction",
            },
        }

    def initial_frame(self) -> dict[str, Any]:
        return self._frame(0)

    def advance_frame(self, frame_index: int) -> dict[str, Any]:
        for _ in range(self.steps_per_frame):
            self._accumulate(self.state.advance(self.dt_s))
        self._execute_next_eligible_transaction(frame_index)
        return self._frame(frame_index)


def run_frames(
    scenario: Mapping[str, Any], frame_count: int = 8
) -> list[dict[str, Any]]:
    if frame_count < 1:
        raise ValueError("frame_count must be at least one")
    runtime = MultiEventTopologyGasRuntime(scenario)
    frames = [runtime.initial_frame()]
    for frame_index in range(1, frame_count):
        frames.append(runtime.advance_frame(frame_index))
    return frames
