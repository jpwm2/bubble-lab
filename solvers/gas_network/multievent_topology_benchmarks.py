"""Acceptance benchmarks for bounded multi-event topology-changing gas transport."""
from __future__ import annotations

from .multievent_topology import supported_multievent_topology_gas_state


def _signature(state) -> tuple[object, ...]:
    return (
        state.gas_state.region_ids(),
        state.gas_state.edge_ids(),
        state.gas_state.topology_revision,
        state.gas_state.time_s,
        tuple(
            (r.id, r.amount_mol, r.volume_m3, r.temperature_k, r.surface_tension_n_m)
            for r in state.gas_state.regions
        ),
        tuple(
            (e.id, e.region_a, e.region_b, e.shared_area_m2)
            for e in state.gas_state.edges
        ),
        state.topology_state.topology_signature(),
        tuple(event.to_contract() for event in state.topology_events),
    )


def _run_four_t1s(state, *, advance=True):
    events = []
    dependencies = []
    for number in range(1, 5):
        eligibility = state.event_eligibility(number)
        if number == 1:
            dependencies.append(("event1-initial", eligibility.eligible, eligibility.reason))
        else:
            dependencies.append((f"event{number}-enabled", eligibility.eligible, eligibility.reason))
        if not eligibility.eligible:
            raise AssertionError(f"T1 {number} unexpectedly ineligible: {eligibility.reason}")
        if advance:
            state.advance(0.05)
        events.append(state.perform_next_t1())
        if number < 4:
            next_eligibility = state.event_eligibility(number + 1)
            dependencies.append(
                (f"event{number + 1}-after-event{number}", next_eligibility.eligible, next_eligibility.reason)
            )
    return tuple(events), tuple(dependencies)


def multievent_topology_sequence_benchmark() -> dict:
    state = supported_multievent_topology_gas_state()
    initial_ids = state.gas_state.region_ids()
    initial_edges = state.gas_state.edge_ids()
    initially_blocked = {
        number: state.event_eligibility(number).reason for number in (2, 3, 4)
    }
    rupture_before = state.rupture_coalescence_eligibility()
    t1_events, _ = _run_four_t1s(state)
    rupture_ready = state.rupture_coalescence_eligibility()
    rc = state.perform_rupture_coalescence()
    event_types = ("T1",) * len(t1_events) + rc.event_types
    topology_changed_each_t1 = all(
        event.adjacency_before != event.adjacency_after
        and event.edge_ids_before != event.edge_ids_after
        for event in t1_events
    )
    return {
        "benchmark": "multievent-topology-sequence",
        "initial_region_ids": initial_ids,
        "final_region_ids": state.gas_state.region_ids(),
        "initial_edge_ids": initial_edges,
        "event_types": event_types,
        "t1_event_ids": tuple(event.event_id for event in t1_events),
        "rupture_coalescence_event_ids": rc.event_ids,
        "initially_blocked_reasons": initially_blocked,
        "rupture_eligible_before_fourth_t1": rupture_before.eligible,
        "rupture_eligible_after_fourth_t1": rupture_ready.eligible,
        "ruptured_film_ids": rc.retired_film_ids,
        "coalescence_lineage": rc.lineage,
        "topology_revision": state.gas_state.topology_revision,
        "transaction_count": 5,
        "topology_event_count": len(event_types),
        "topology_changed_each_t1": topology_changed_each_t1,
        "passed": (
            len(initial_ids) == 10
            and len(state.gas_state.region_ids()) == 9
            and topology_changed_each_t1
            and all("adjacency already exists" in reason for reason in initially_blocked.values())
            and not rupture_before.eligible
            and rupture_ready.eligible
            and set(event_types) >= {"T1", "RUPTURE", "COALESCENCE"}
            and rc.lineage == ("G", "H")
            and state.gas_state.topology_revision == 6
            and len(event_types) >= 6
        ),
    }


def multievent_topology_dependence_benchmark() -> dict:
    state = supported_multievent_topology_gas_state()
    checks = []
    for number in range(2, 5):
        pre = state.event_eligibility(number)
        checks.append({
            "event_number": number,
            "eligible_before_predecessor": pre.eligible,
            "blocked_reason": pre.reason,
        })
        predecessor = number - 1
        while state.gas_state.topology_revision < predecessor:
            state.perform_next_t1()
        post = state.event_eligibility(number)
        checks[-1]["eligible_after_predecessor"] = post.eligible
        checks[-1]["enabled_reason"] = post.reason
    while state.gas_state.topology_revision < 3:
        state.perform_next_t1()
    rupture_before = state.rupture_coalescence_eligibility()
    fourth = state.perform_next_t1()
    rupture_after = state.rupture_coalescence_eligibility()
    causal_t1s = all(
        not item["eligible_before_predecessor"]
        and "adjacency already exists" in item["blocked_reason"]
        and item["eligible_after_predecessor"]
        for item in checks
    )
    causal_rupture = (
        not rupture_before.eligible
        and rupture_after.eligible
        and rupture_after.film_id in fourth.created_film_ids
    )
    return {
        "benchmark": "multievent-topology-dependence",
        "t1_dependencies": checks,
        "rupture_before_event4": rupture_before.reason,
        "rupture_after_event4": rupture_after.reason,
        "event4_created_film_ids": fourth.created_film_ids,
        "rupture_target_film_id": rupture_after.film_id,
        "passed": causal_t1s and causal_rupture,
    }


def multievent_topology_conservation_benchmark() -> dict:
    state = supported_multievent_topology_gas_state()
    initial_total = state.gas_state.total_amount_mol()
    worst_transport = 0.0
    t1_events = []
    for _ in range(4):
        diag = state.advance(0.05)
        worst_transport = max(worst_transport, diag.total_relative_drift)
        event = state.perform_next_t1()
        t1_events.append(event)
    rc = state.perform_rupture_coalescence()
    for _ in range(2):
        diag = state.advance(0.05)
        worst_transport = max(worst_transport, diag.total_relative_drift)
    final_total = state.gas_state.total_amount_mol()
    total_drift = abs(final_total - initial_total) / max(abs(initial_total), 1.0e-300)
    t1_exact = all(
        event.amount_before_mol == event.amount_after_mol
        and event.volume_before_m3 == event.volume_after_m3
        and event.pressure_before_pa == event.pressure_after_pa
        and event.total_relative_drift <= 1.0e-12
        for event in t1_events
    )
    return {
        "benchmark": "multievent-topology-conservation",
        "initial_total_mol": initial_total,
        "final_total_mol": final_total,
        "total_relative_drift": total_drift,
        "worst_transport_step_relative_drift": worst_transport,
        "t1_relative_drifts": tuple(event.total_relative_drift for event in t1_events),
        "rupture_coalescence_relative_drift": rc.total_relative_drift,
        "unaffected_state_exact": rc.unaffected_state_exact,
        "final_region_count": len(state.gas_state.regions),
        "passed": (
            total_drift <= 1.0e-12
            and worst_transport <= 1.0e-12
            and t1_exact
            and rc.total_relative_drift <= 1.0e-12
            and rc.unaffected_state_exact
            and len(state.gas_state.regions) >= 8
        ),
    }


def multievent_topology_transport_benchmark() -> dict:
    state = supported_multievent_topology_gas_state()
    created_measurements = []
    retired_ids = []
    for _ in range(4):
        state.advance(0.05)
        event = state.perform_next_t1()
        created = event.created_film_ids[0]
        retired_ids.extend(event.retired_film_ids)
        pressures = {r.id: r.pressure_pa() for r in state.gas_state.regions}
        edge = next(e for e in state.gas_state.edges if e.id == created)
        dp = pressures[edge.region_a] - pressures[edge.region_b]
        diag = state.advance(0.05)
        edge_diag = next(item for item in diag.edges if item.edge_id == created)
        created_measurements.append(
            (created, dp, edge_diag.integrated_a_to_b_mol, diag.total_relative_drift)
        )
    target = state.rupture_coalescence_eligibility().film_id
    rc = state.perform_rupture_coalescence()
    post = state.advance(0.05)
    final_edges = set(state.gas_state.edge_ids())
    created_active_before_rc = all(
        measurement[0] in rc.edge_ids_before for measurement in created_measurements
    )
    retired_absent = not set(retired_ids).intersection(final_edges)
    return {
        "benchmark": "multievent-topology-transport",
        "created_edge_measurements": created_measurements,
        "rupture_target": target,
        "rupture_target_absent_after": target not in final_edges,
        "created_active_before_rupture_coalescence": created_active_before_rc,
        "retired_t1_edges_absent_final": retired_absent,
        "post_event_active_edge_count": len(final_edges),
        "post_event_max_simultaneous_active_edges": post.max_simultaneous_active_edges,
        "post_event_relative_drift": post.total_relative_drift,
        "passed": (
            all(
                dp != 0.0 and transfer != 0.0 and drift <= 1.0e-12
                for _, dp, transfer, drift in created_measurements
            )
            and target is not None
            and target not in final_edges
            and created_active_before_rc
            and retired_absent
            and len(final_edges) >= 1
            and post.max_simultaneous_active_edges >= 1
            and post.total_relative_drift <= 1.0e-12
        ),
    }


def _record() -> tuple[object, ...]:
    state = supported_multievent_topology_gas_state()
    records: list[object] = [(_signature(state), tuple(state.event_eligibility(n) for n in (2, 3, 4)))]
    for number in range(1, 5):
        diag = state.advance(0.05)
        records.append((diag.final_amount_mol, _signature(state)))
        event = state.perform_next_t1()
        records.append(
            (
                number,
                event.event_id,
                event.retired_film_ids,
                event.created_film_ids,
                _signature(state),
            )
        )
    records.append((state.rupture_coalescence_eligibility(), _signature(state)))
    rc = state.perform_rupture_coalescence()
    records.append(
        (
            rc.event_ids,
            rc.event_types,
            rc.child_region_id,
            rc.lineage,
            _signature(state),
        )
    )
    for _ in range(2):
        diag = state.advance(0.05)
        records.append((diag.final_amount_mol, _signature(state)))
    return tuple(records)


def multievent_topology_replay_benchmark() -> dict:
    first = _record()
    second = _record()
    return {
        "benchmark": "multievent-topology-replay",
        "record_count": len(first),
        "exact_repeat": first == second,
        "passed": first == second,
    }


MULTIEVENT_TOPOLOGY_BENCHMARKS = {
    "multievent-topology-sequence": multievent_topology_sequence_benchmark,
    "multievent-topology-dependence": multievent_topology_dependence_benchmark,
    "multievent-topology-conservation": multievent_topology_conservation_benchmark,
    "multievent-topology-transport": multievent_topology_transport_benchmark,
    "multievent-topology-replay": multievent_topology_replay_benchmark,
}
