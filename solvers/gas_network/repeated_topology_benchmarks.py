"""Acceptance benchmarks for two topologically distinct dependent production T1s."""
from __future__ import annotations

from .repeated_topology import supported_repeated_t1_gas_transport_state


def _signature(state) -> tuple[object, ...]:
    return (
        state.gas_state.region_ids(),
        state.gas_state.edge_ids(),
        state.gas_state.topology_revision,
        state.gas_state.time_s,
        tuple((r.id, r.amount_mol, r.volume_m3, r.pressure_pa()) for r in state.gas_state.regions),
        tuple((e.id, e.region_a, e.region_b, e.shared_area_m2) for e in state.gas_state.edges),
        state.topology_state.topology_signature(),
    )


def _advance_and_measure_created(state, created_id: str, dt_s: float = 0.05):
    pressures = {r.id: r.pressure_pa() for r in state.gas_state.regions}
    edge = next(e for e in state.gas_state.edges if e.id == created_id)
    dp = pressures[edge.region_a] - pressures[edge.region_b]
    diag = state.advance(dt_s)
    edge_diag = next(item for item in diag.edges if item.edge_id == created_id)
    return dp, edge_diag, diag


def repeated_t1_switch_benchmark() -> dict:
    state = supported_repeated_t1_gas_transport_state()
    initial_ids = state.gas_state.region_ids()
    initial_edges = state.gas_state.edge_ids()
    second_before = state.event_eligibility(2)
    state.advance(0.05)
    first = state.perform_t1()
    second_after = state.event_eligibility(2)
    first_edges = state.gas_state.edge_ids()
    state.advance(0.05)
    second = state.perform_t1()
    final_edges = state.gas_state.edge_ids()
    distinct = first.retired_film_ids != second.retired_film_ids and first.created_film_ids != second.created_film_ids
    dependent = (
        not second_before.eligible
        and second_after.eligible
        and first.adjacency_after == second.adjacency_before
        and first.event_id == "t1:000001"
        and second.event_id == "t1:000002"
    )
    return {
        "benchmark": "repeated-t1-switch",
        "region_ids": initial_ids,
        "event_ids": (first.event_id, second.event_id),
        "initial_edge_ids": initial_edges,
        "after_first_edge_ids": first_edges,
        "after_second_edge_ids": final_edges,
        "first_retired_film_ids": first.retired_film_ids,
        "first_created_film_ids": first.created_film_ids,
        "second_retired_film_ids": second.retired_film_ids,
        "second_created_film_ids": second.created_film_ids,
        "second_eligible_before_first": second_before.eligible,
        "second_eligible_after_first": second_after.eligible,
        "events_topologically_distinct": distinct,
        "stable_region_ids": initial_ids == state.gas_state.region_ids(),
        "topology_revision": state.gas_state.topology_revision,
        "passed": (
            len(initial_ids) == 6
            and dependent
            and distinct
            and initial_edges != first_edges
            and first_edges != final_edges
            and not set(second.retired_film_ids).intersection(final_edges)
            and set(first.created_film_ids).issubset(set(final_edges))
            and set(second.created_film_ids).issubset(set(final_edges))
            and initial_ids == state.gas_state.region_ids()
            and state.gas_state.topology_revision == 2
        ),
    }


def repeated_topology_conservation_benchmark() -> dict:
    state = supported_repeated_t1_gas_transport_state()
    initial_total = state.gas_state.total_amount_mol()
    initial_ids = state.gas_state.region_ids()
    worst_step_drift = 0.0
    for _ in range(3):
        worst_step_drift = max(worst_step_drift, state.advance(0.05).total_relative_drift)
    first = state.perform_t1()
    for _ in range(3):
        worst_step_drift = max(worst_step_drift, state.advance(0.05).total_relative_drift)
    second = state.perform_t1()
    for _ in range(3):
        worst_step_drift = max(worst_step_drift, state.advance(0.05).total_relative_drift)
    final_total = state.gas_state.total_amount_mol()
    total_drift = abs(final_total - initial_total) / max(abs(initial_total), 1.0e-300)
    surgery_exact = all(
        event.amount_before_mol == event.amount_after_mol
        and event.volume_before_m3 == event.volume_after_m3
        and event.pressure_before_pa == event.pressure_after_pa
        for event in (first, second)
    )
    return {
        "benchmark": "repeated-topology-conservation",
        "initial_total_mol": initial_total,
        "final_total_mol": final_total,
        "total_relative_drift": total_drift,
        "worst_transport_step_relative_drift": worst_step_drift,
        "event_relative_drifts": (first.total_relative_drift, second.total_relative_drift),
        "surgery_state_exact": surgery_exact,
        "stable_region_ids": initial_ids == state.gas_state.region_ids(),
        "topology_revision": state.gas_state.topology_revision,
        "passed": (
            total_drift <= 1.0e-12
            and worst_step_drift <= 1.0e-12
            and first.total_relative_drift <= 1.0e-12
            and second.total_relative_drift <= 1.0e-12
            and surgery_exact
            and initial_ids == state.gas_state.region_ids()
            and state.gas_state.topology_revision == 2
        ),
    }


def second_event_dependence_benchmark() -> dict:
    state = supported_repeated_t1_gas_transport_state()
    blocked = state.event_eligibility(2)
    gas_initial = tuple((r.id, r.amount_mol) for r in state.gas_state.regions)
    first = state.perform_t1()
    enabled = state.event_eligibility(2)
    canonical_between = state.topology_state.topology_signature()
    gas_between = tuple((r.id, r.amount_mol, r.volume_m3, r.pressure_pa()) for r in state.gas_state.regions)
    state.advance(0.05)
    gas_before_second = tuple((r.id, r.amount_mol, r.volume_m3, r.pressure_pa()) for r in state.gas_state.regions)
    topology_before_second = state.topology_state.topology_signature()
    second = state.perform_t1()
    dependency = (
        not blocked.eligible
        and "adjacency already exists" in blocked.reason
        and enabled.eligible
        and canonical_between == topology_before_second
        and first.adjacency_after == second.adjacency_before
        and second.event_id == "t1:000002"
    )
    continued_gas = (
        gas_between != gas_before_second
        and gas_initial != tuple((rid, amount) for rid, amount, _, _ in gas_before_second)
        and second.amount_before_mol == tuple((rid, amount) for rid, amount, _, _ in gas_before_second)
    )
    return {
        "benchmark": "second-event-dependence",
        "blocked_before_first_reason": blocked.reason,
        "eligible_after_first": enabled.eligible,
        "first_event_id": first.event_id,
        "second_event_id": second.event_id,
        "canonical_topology_continued": dependency,
        "gas_history_continued_before_second_event": continued_gas,
        "passed": dependency and continued_gas,
    }


def repeated_post_event_transfer_benchmark() -> dict:
    state = supported_repeated_t1_gas_transport_state()
    for _ in range(2):
        state.advance(0.05)
    first = state.perform_t1()
    first_created = first.created_film_ids[0]
    first_dp, first_edge_diag, first_diag = _advance_and_measure_created(state, first_created)
    second = state.perform_t1()
    second_created = second.created_film_ids[0]
    second_dp, second_edge_diag, second_diag = _advance_and_measure_created(state, second_created)
    final_edges = state.gas_state.edge_ids()
    return {
        "benchmark": "repeated-post-event-transfer",
        "first_created_edge_id": first_created,
        "first_pressure_difference_pa": first_dp,
        "first_integrated_transfer_mol": first_edge_diag.integrated_a_to_b_mol,
        "second_created_edge_id": second_created,
        "second_pressure_difference_pa": second_dp,
        "second_integrated_transfer_mol": second_edge_diag.integrated_a_to_b_mol,
        "first_created_edge_survives_second": first_created in final_edges,
        "second_created_edge_active": second_created in final_edges,
        "max_simultaneous_active_edges": max(first_diag.max_simultaneous_active_edges, second_diag.max_simultaneous_active_edges),
        "passed": (
            first_dp != 0.0
            and second_dp != 0.0
            and first_edge_diag.integrated_a_to_b_mol != 0.0
            and second_edge_diag.integrated_a_to_b_mol != 0.0
            and first_created in final_edges
            and second_created in final_edges
            and first_diag.max_simultaneous_active_edges >= 2
            and second_diag.max_simultaneous_active_edges >= 2
            and first_diag.total_relative_drift <= 1.0e-12
            and second_diag.total_relative_drift <= 1.0e-12
        ),
    }


def _repeated_record() -> tuple[object, ...]:
    state = supported_repeated_t1_gas_transport_state()
    records: list[object] = [(_signature(state), state.event_eligibility(2))]
    for _ in range(2):
        diag = state.advance(0.05)
        records.append((diag.final_amount_mol, _signature(state)))
    first = state.perform_t1()
    records.append((first.event_id, first.retired_film_ids, first.created_film_ids, state.event_eligibility(2), _signature(state)))
    diag = state.advance(0.05)
    records.append((tuple((e.edge_id, e.integrated_a_to_b_mol) for e in diag.edges), _signature(state)))
    second = state.perform_t1()
    records.append((second.event_id, second.retired_film_ids, second.created_film_ids, _signature(state)))
    for _ in range(2):
        diag = state.advance(0.05)
        records.append((diag.final_amount_mol, tuple((e.edge_id, e.integrated_a_to_b_mol) for e in diag.edges), _signature(state)))
    return tuple(records)


def repeated_topology_replay_benchmark() -> dict:
    first = _repeated_record()
    second = _repeated_record()
    return {
        "benchmark": "repeated-topology-replay",
        "record_count": len(first),
        "exact_repeat": first == second,
        "passed": first == second,
    }


REPEATED_TOPOLOGY_BENCHMARKS = {
    "repeated-t1-switch": repeated_t1_switch_benchmark,
    "repeated-topology-conservation": repeated_topology_conservation_benchmark,
    "second-event-dependence": second_event_dependence_benchmark,
    "repeated-post-event-transfer": repeated_post_event_transfer_benchmark,
    "repeated-topology-replay": repeated_topology_replay_benchmark,
}
