"""Benchmarks for conservative gas transport through one real T1 switch."""
from __future__ import annotations

import math

from .topology import supported_t1_gas_transport_state


def _gas_signature(state) -> tuple[object, ...]:
    return (
        state.gas_state.region_ids(),
        state.gas_state.edge_ids(),
        state.gas_state.topology_revision,
        state.gas_state.time_s,
        tuple(
            (region.id, region.amount_mol, region.volume_m3, region.pressure_pa())
            for region in state.gas_state.regions
        ),
        tuple(
            (
                edge.id,
                edge.region_a,
                edge.region_b,
                edge.shared_area_m2,
                edge.film_thickness_m,
                edge.permeability_mol_m_per_m2_s_pa,
            )
            for edge in state.gas_state.edges
        ),
        state.topology_state.topology_signature(),
    )


def t1_switch_benchmark() -> dict:
    state = supported_t1_gas_transport_state()
    pre_diag = state.advance(0.05)
    before_edges = state.gas_state.edge_ids()
    event = state.perform_t1()
    after_edges = state.gas_state.edge_ids()
    canonical_after = tuple(
        sorted(
            patch.id
            for patch in state.topology_state.to_network().patches
            if "EXTERIOR" not in patch.adjacent
        )
    )
    created_present = set(event.created_film_ids).issubset(set(after_edges))
    retired_absent = not set(event.retired_film_ids).intersection(after_edges)
    changed = before_edges != after_edges and event.adjacency_before != event.adjacency_after
    return {
        "benchmark": "t1-switch",
        "region_count": len(state.gas_state.regions),
        "pre_shared_film_edge_count": len(before_edges),
        "pre_max_simultaneous_active_edges": pre_diag.max_simultaneous_active_edges,
        "pre_edge_ids": before_edges,
        "post_edge_ids": after_edges,
        "canonical_post_edge_ids": canonical_after,
        "retired_film_ids": event.retired_film_ids,
        "created_film_ids": event.created_film_ids,
        "adjacency_before": event.adjacency_before,
        "adjacency_after": event.adjacency_after,
        "created_edge_present": created_present,
        "retired_edge_absent": retired_absent,
        "topology_revision": state.gas_state.topology_revision,
        "passed": (
            len(state.gas_state.regions) >= 4
            and len(before_edges) >= 2
            and pre_diag.max_simultaneous_active_edges >= 2
            and changed
            and created_present
            and retired_absent
            and tuple(sorted(after_edges)) == canonical_after
            and state.gas_state.topology_revision == 1
        ),
    }


def topology_conservation_benchmark() -> dict:
    state = supported_t1_gas_transport_state()
    initial_total = state.gas_state.total_amount_mol()
    initial_ids = state.gas_state.region_ids()
    worst_transport_drift = 0.0
    for _ in range(5):
        diag = state.advance(0.05)
        worst_transport_drift = max(worst_transport_drift, diag.total_relative_drift)
    event = state.perform_t1()
    for _ in range(5):
        diag = state.advance(0.05)
        worst_transport_drift = max(worst_transport_drift, diag.total_relative_drift)
    final_total = state.gas_state.total_amount_mol()
    total_drift = abs(final_total - initial_total) / initial_total
    event_state_unchanged = (
        event.amount_before_mol == event.amount_after_mol
        and event.volume_before_m3 == event.volume_after_m3
        and event.pressure_before_pa == event.pressure_after_pa
    )
    return {
        "benchmark": "topology-conservation",
        "initial_total_mol": initial_total,
        "final_total_mol": final_total,
        "total_relative_drift": total_drift,
        "worst_transport_step_relative_drift": worst_transport_drift,
        "event_relative_drift": event.total_relative_drift,
        "event_state_unchanged": event_state_unchanged,
        "stable_region_ids": initial_ids == state.gas_state.region_ids(),
        "topology_revision": state.gas_state.topology_revision,
        "passed": (
            total_drift <= 1.0e-12
            and worst_transport_drift <= 1.0e-12
            and event.total_relative_drift <= 1.0e-12
            and event_state_unchanged
            and initial_ids == state.gas_state.region_ids()
            and state.gas_state.topology_revision == 1
        ),
    }


def post_t1_transfer_benchmark() -> dict:
    state = supported_t1_gas_transport_state()
    for _ in range(3):
        state.advance(0.05)
    event = state.perform_t1()
    created_id = event.created_film_ids[0]
    before_pressure = {
        region.id: region.pressure_pa() for region in state.gas_state.regions
    }
    diag = state.advance(0.05)
    edge_diag = next(item for item in diag.edges if item.edge_id == created_id)
    edge = next(item for item in state.gas_state.edges if item.id == created_id)
    pressure_difference = before_pressure[edge.region_a] - before_pressure[edge.region_b]
    direction_consistent = (
        pressure_difference == 0.0
        and edge_diag.initial_rate_a_to_b_mol_s == 0.0
    ) or (
        pressure_difference * edge_diag.initial_rate_a_to_b_mol_s > 0.0
    )
    nonzero_transfer = abs(edge_diag.integrated_a_to_b_mol) > 0.0
    retired_absent = not set(event.retired_film_ids).intersection(
        state.gas_state.edge_ids()
    )
    return {
        "benchmark": "post-t1-transfer",
        "created_edge_id": created_id,
        "created_edge_regions": (edge.region_a, edge.region_b),
        "created_edge_initial_pressure_difference_pa": pressure_difference,
        "created_edge_initial_rate_a_to_b_mol_s": edge_diag.initial_rate_a_to_b_mol_s,
        "created_edge_integrated_a_to_b_mol": edge_diag.integrated_a_to_b_mol,
        "direction_consistent": direction_consistent,
        "nonzero_transfer": nonzero_transfer,
        "retired_edge_absent": retired_absent,
        "post_event_max_simultaneous_active_edges": diag.max_simultaneous_active_edges,
        "post_event_relative_drift": diag.total_relative_drift,
        "passed": (
            created_id in state.gas_state.edge_ids()
            and retired_absent
            and not math.isclose(pressure_difference, 0.0, rel_tol=0.0, abs_tol=1.0e-15)
            and direction_consistent
            and nonzero_transfer
            and diag.max_simultaneous_active_edges >= 2
            and diag.total_relative_drift <= 1.0e-12
        ),
    }


def _replay_record() -> tuple[object, ...]:
    state = supported_t1_gas_transport_state()
    records: list[object] = [_gas_signature(state)]
    for _ in range(3):
        diag = state.advance(0.05)
        records.append(
            (
                diag.requested_dt_s,
                diag.substeps,
                diag.final_amount_mol,
                tuple((item.edge_id, item.integrated_a_to_b_mol) for item in diag.edges),
                _gas_signature(state),
            )
        )
    event = state.perform_t1()
    records.append(
        (
            event.event_id,
            event.retired_film_ids,
            event.created_film_ids,
            event.adjacency_before,
            event.adjacency_after,
            event.amount_after_mol,
            event.volume_after_m3,
            event.pressure_after_pa,
            _gas_signature(state),
        )
    )
    for _ in range(4):
        diag = state.advance(0.05)
        records.append(
            (
                diag.requested_dt_s,
                diag.substeps,
                diag.final_amount_mol,
                tuple((item.edge_id, item.integrated_a_to_b_mol) for item in diag.edges),
                _gas_signature(state),
            )
        )
    return tuple(records)


def topology_replay_benchmark() -> dict:
    first = _replay_record()
    second = _replay_record()
    return {
        "benchmark": "topology-replay",
        "record_count": len(first),
        "exact_repeat": first == second,
        "passed": first == second,
    }


TOPOLOGY_BENCHMARKS = {
    "t1-switch": t1_switch_benchmark,
    "topology-conservation": topology_conservation_benchmark,
    "post-t1-transfer": post_t1_transfer_benchmark,
    "topology-replay": topology_replay_benchmark,
}
