"""Bounded multi-event topology-changing gas transport.

The qualified class keeps one canonical FilmNetwork and one GasNetworkState while
four production T1 transactions form a causal chain.  A production rupture /
coalescence transaction then consumes the film created by the fourth T1.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
from typing import Mapping

from bubblelab.solvers.equilibrium.network import (
    EXTERIOR,
    FilmNetwork,
    FilmPatch,
    GasRegion,
    PlateauJunction,
)
from bubblelab.solvers.events.adapters import state_from_film_network
from bubblelab.solvers.events.criteria import RuptureConfig
from bubblelab.solvers.events.engine import TopologyEventEngine
from bubblelab.solvers.events.model import TopologyEvent
from bubblelab.solvers.transient.network.core import TransientNetworkState
from bubblelab.solvers.transient.network.t1 import (
    EligibilityResult,
    T1TransactionSettings,
    build_supported_pre_t1_network,
    detect_t1_eligibility,
    internal_adjacency_pairs,
    perform_t1_transaction,
)

from .model import (
    R_GAS_J_MOL_K,
    GasNetworkDiagnostics,
    GasNetworkState,
    GasRegionState,
    advance_gas_network,
    equivalent_radius_m,
)
from .topology import (
    TopologyGasEventDiagnostics,
    gas_state_from_topology,
    shared_film_edges_from_topology,
)

_EVENT_PREFIXES = tuple(f"event{index}:" for index in range(1, 5))
_OLD_PAIRS = (("A", "B"), ("E", "F"), ("G", "H"), ("I", "J"))
_FUTURE_PAIRS = (("C", "D"), ("A", "B"), ("E", "F"), ("G", "H"))
_REGION_MAPS = (
    {"A": "A", "B": "B", "C": "C", "D": "D"},
    {"A": "E", "B": "F", "C": "A", "D": "B"},
    {"A": "G", "B": "H", "C": "E", "D": "F"},
    {"A": "I", "B": "J", "C": "G", "D": "H"},
)
SURFACE_TENSION_N_M = {
    "A": 0.0310, "B": 0.0280, "C": 0.0330, "D": 0.0270, "E": 0.0340,
    "F": 0.0260, "G": 0.0350, "H": 0.0250, "I": 0.0360, "J": 0.0240,
}


@dataclass(frozen=True)
class EventEligibility:
    eligible: bool
    reason: str
    film_id: str | None = None


@dataclass(frozen=True)
class RuptureCoalescenceDiagnostics:
    event_ids: tuple[str, ...]
    event_types: tuple[str, ...]
    retired_film_ids: tuple[str, ...]
    parent_region_ids: tuple[str, str]
    child_region_id: str
    lineage: tuple[str, ...]
    region_ids_before: tuple[str, ...]
    region_ids_after: tuple[str, ...]
    edge_ids_before: tuple[str, ...]
    edge_ids_after: tuple[str, ...]
    total_amount_before_mol: float
    total_amount_after_mol: float
    total_relative_drift: float
    unaffected_state_exact: bool
    topology_revision_before: int
    topology_revision_after: int
    emitted_events: tuple[TopologyEvent, ...]


@dataclass(frozen=True)
class _ThicknessState:
    thickness_m: tuple[float, ...]


def _renamed_fixture(
    network: FilmNetwork, *, region_map: Mapping[str, str], id_prefix: str
) -> FilmNetwork:
    patch_ids = {patch.id: f"{id_prefix}{patch.id}" for patch in network.patches}

    def region_id(value: str) -> str:
        return value if value == EXTERIOR else region_map[value]

    renamed = FilmNetwork(
        regions=tuple(
            GasRegion(region_map[region.id], region.target_volume_m3)
            for region in network.regions
        ),
        patches=tuple(
            FilmPatch(
                id=patch_ids[patch.id],
                mesh=patch.mesh,
                adjacent=(region_id(patch.adjacent[0]), region_id(patch.adjacent[1])),
                sheet_tension_n_m=patch.sheet_tension_n_m,
                fixed_vertex_indices=patch.fixed_vertex_indices,
                contributes_to_volume=patch.contributes_to_volume,
            )
            for patch in network.patches
        ),
        junctions=tuple(
            PlateauJunction(
                id=f"{id_prefix}{junction.id}",
                incident_film_ids=tuple(patch_ids[item] for item in junction.incident_film_ids),
                vertex_indices_by_film=junction.vertex_indices_by_film,
                normal_plane_only=junction.normal_plane_only,
                rigid_normal_translation=junction.rigid_normal_translation,
            )
            for junction in network.junctions
        ),
    )
    renamed.validate()
    return renamed


def _combine_overlapping_regions(*networks: FilmNetwork) -> FilmNetwork:
    targets: dict[str, float] = {}
    patches: list[FilmPatch] = []
    junctions: list[PlateauJunction] = []
    for network in networks:
        for region in network.regions:
            targets[region.id] = targets.get(region.id, 0.0) + region.target_volume_m3
        patches.extend(network.patches)
        junctions.extend(network.junctions)
    combined = FilmNetwork(
        regions=tuple(GasRegion(key, targets[key]) for key in sorted(targets)),
        patches=tuple(sorted(patches, key=lambda item: item.id)),
        junctions=tuple(sorted(junctions, key=lambda item: item.id)),
    )
    combined.validate()
    return combined


def build_supported_multievent_network() -> FilmNetwork:
    cells = []
    for index, (prefix, region_map) in enumerate(zip(_EVENT_PREFIXES, _REGION_MAPS)):
        cells.append(
            _renamed_fixture(
                build_supported_pre_t1_network(
                    resolution_m=0.12,
                    collapse_fraction=0.35,
                    half_extent_m=1.0,
                    depth_m=0.6,
                    sheet_tension_n_m=1.0,
                    origin_xy=(-7.5 + 5.0 * index, 0.0),
                ),
                region_map=region_map,
                id_prefix=prefix,
            )
        )
    network = _combine_overlapping_regions(*cells)
    expected = tuple("ABCDEFGHIJ")
    if tuple(region.id for region in network.regions) != expected:
        raise AssertionError("multi-event fixture must expose ten stable gas regions")
    return network


def _region_snapshot(state: GasNetworkState) -> tuple[tuple[str, float, float, float, float], ...]:
    return tuple(
        (item.id, item.amount_mol, item.volume_m3, item.temperature_k, item.surface_tension_n_m)
        for item in state.regions
    )


def _with_current_targets(network: FilmNetwork, gas_state: GasNetworkState) -> FilmNetwork:
    gas = gas_state.region_by_id()
    return FilmNetwork(
        tuple(GasRegion(region.id, gas[region.id].volume_m3) for region in network.regions),
        network.patches,
        network.junctions,
    )


def _event_patch(patch: FilmPatch, event_number: int) -> bool:
    return patch.id.startswith(_EVENT_PREFIXES[event_number - 1]) and not patch.contributes_to_volume


def _previous_lineage_marker(patch: FilmPatch, event_number: int) -> bool:
    if event_number <= 1:
        return False
    previous = event_number - 1
    prefix = _EVENT_PREFIXES[previous - 1]
    future_pair = _FUTURE_PAIRS[previous - 1]
    old_central = f"{prefix}film:AB:central"
    return patch.id == old_central or (
        ":t1:" in patch.id and tuple(sorted(patch.adjacent)) == tuple(sorted(future_pair))
    )


def _local_event_network(
    global_network: FilmNetwork, gas_state: GasNetworkState, event_number: int
) -> FilmNetwork:
    if event_number not in (1, 2, 3, 4):
        raise ValueError("event_number must be in 1..4")
    patches = tuple(
        patch
        for patch in global_network.patches
        if patch.contributes_to_volume
        or _event_patch(patch, event_number)
        or _previous_lineage_marker(patch, event_number)
    )
    junctions = tuple(
        junction
        for junction in global_network.junctions
        if junction.id.startswith(_EVENT_PREFIXES[event_number - 1])
    )
    local = _with_current_targets(
        FilmNetwork(global_network.regions, patches, junctions), gas_state
    )
    local.validate()
    return local


def _merge_transaction(
    global_before: FilmNetwork, local_before: FilmNetwork, local_after: FilmNetwork
) -> FilmNetwork:
    local_patch_ids = {patch.id for patch in local_before.patches}
    local_junction_ids = {junction.id for junction in local_before.junctions}
    patches = [patch for patch in global_before.patches if patch.id not in local_patch_ids]
    patches.extend(local_after.patches)
    junctions = [
        junction for junction in global_before.junctions
        if junction.id not in local_junction_ids
    ]
    junctions.extend(local_after.junctions)
    merged = FilmNetwork(
        local_after.regions,
        tuple(sorted(patches, key=lambda item: item.id)),
        tuple(sorted(junctions, key=lambda item: item.id)),
    )
    merged.validate()
    return merged


def _surface_tension_for_merged_region(
    *, amount_mol: float, volume_m3: float, temperature_k: float, ambient_pressure_pa: float
) -> float:
    pressure = amount_mol * R_GAS_J_MOL_K * temperature_k / volume_m3
    radius = equivalent_radius_m(volume_m3)
    gamma = 0.5 * (pressure - ambient_pressure_pa) * radius
    if gamma < 0.0:
        raise RuntimeError("merged region pressure fell below ambient pressure")
    return gamma


@dataclass
class MultiEventTopologyGasTransportState:
    topology_state: TransientNetworkState
    gas_state: GasNetworkState
    film_thickness_m: float = 8.0e-7
    permeability_mol_m_per_m2_s_pa: float = 1.0e-8
    t1_settings: T1TransactionSettings = T1TransactionSettings()
    topology_events: list[TopologyEvent] = field(default_factory=list)

    def validate(self) -> None:
        self.gas_state.validate()
        self.gas_state.assert_constitutive_consistency()
        network = self.topology_state.to_network()
        if tuple(region.id for region in network.regions) != self.gas_state.region_ids():
            raise ValueError("topology and gas region identities must match exactly")
        expected = shared_film_edges_from_topology(
            network,
            film_thickness_m=self.film_thickness_m,
            permeability_mol_m_per_m2_s_pa=self.permeability_mol_m_per_m2_s_pa,
        )
        actual_signature = tuple((e.id, e.region_a, e.region_b) for e in self.gas_state.edges)
        expected_signature = tuple((e.id, e.region_a, e.region_b) for e in expected)
        if actual_signature != expected_signature:
            raise ValueError("gas transport graph is stale relative to canonical topology")
        if self.gas_state.topology_revision not in (0, 1, 2, 3, 4, 6):
            raise ValueError("bounded multi-event state supports T1 revisions 0..4 and final revision 6")

    def advance(self, dt_s: float) -> GasNetworkDiagnostics:
        self.validate()
        diagnostics = advance_gas_network(self.gas_state, dt_s)
        self.validate()
        return diagnostics

    def event_eligibility(self, event_number: int) -> EligibilityResult:
        local = _local_event_network(
            self.topology_state.to_network(), self.gas_state, event_number
        )
        return detect_t1_eligibility(local, self.t1_settings.eligibility)

    def perform_next_t1(self) -> TopologyGasEventDiagnostics:
        self.validate()
        event_number = self.gas_state.topology_revision + 1
        if event_number not in (1, 2, 3, 4):
            raise RuntimeError("the four-event T1 chain is complete")
        global_before = self.topology_state.to_network()
        local_before = _local_event_network(global_before, self.gas_state, event_number)
        eligibility = detect_t1_eligibility(local_before, self.t1_settings.eligibility)
        if not eligibility.eligible:
            raise RuntimeError(
                f"production T1 event {event_number} is not eligible: {eligibility.reason}"
            )

        region_ids_before = self.gas_state.region_ids()
        edge_ids_before = self.gas_state.edge_ids()
        adjacency_before = internal_adjacency_pairs(global_before)
        snapshot_before = _region_snapshot(self.gas_state)
        total_before = self.gas_state.total_amount_mol()
        revision_before = self.gas_state.topology_revision

        event_state = replace(
            TransientNetworkState.from_network(local_before),
            time_s=self.topology_state.time_s,
            step_index=self.topology_state.step_index,
        )
        transaction = perform_t1_transaction(event_state, self.t1_settings)
        global_after = _merge_transaction(
            global_before, local_before, transaction.after_network
        )
        self.topology_state = replace(
            TransientNetworkState.from_network(global_after),
            time_s=self.topology_state.time_s,
            step_index=self.topology_state.step_index,
        )
        self.gas_state.edges = shared_film_edges_from_topology(
            global_after,
            film_thickness_m=self.film_thickness_m,
            permeability_mol_m_per_m2_s_pa=self.permeability_mol_m_per_m2_s_pa,
        )
        self.gas_state.topology_revision += 1

        snapshot_after = _region_snapshot(self.gas_state)
        total_after = self.gas_state.total_amount_mol()
        drift = abs(total_after - total_before) / max(abs(total_before), 1.0e-300)
        if self.gas_state.region_ids() != region_ids_before:
            raise RuntimeError("T1 changed stable gas-region identities")
        if snapshot_after != snapshot_before:
            raise RuntimeError("T1 reset continuous gas state")
        if drift > 1.0e-12:
            raise RuntimeError("T1 gas amount conservation tolerance was exceeded")
        edge_ids_after = self.gas_state.edge_ids()
        retired = set(transaction.lineage.retired_film_ids)
        created = set(transaction.lineage.created_film_ids)
        if retired.intersection(edge_ids_after):
            raise RuntimeError("retired T1 film remained in rebuilt transport graph")
        if not created.issubset(set(edge_ids_after)):
            raise RuntimeError("created T1 film is absent from rebuilt transport graph")
        self.validate()

        amounts_before = tuple((rid, amount) for rid, amount, _, _, _ in snapshot_before)
        volumes_before = tuple((rid, volume) for rid, _, volume, _, _ in snapshot_before)
        pressures_before = tuple(
            (region.id, region.pressure_pa()) for region in self.gas_state.regions
        )
        return TopologyGasEventDiagnostics(
            event_id=transaction.lineage.event_id,
            retired_film_ids=transaction.lineage.retired_film_ids,
            created_film_ids=transaction.lineage.created_film_ids,
            region_ids_before=region_ids_before,
            region_ids_after=self.gas_state.region_ids(),
            edge_ids_before=edge_ids_before,
            edge_ids_after=edge_ids_after,
            adjacency_before=adjacency_before,
            adjacency_after=internal_adjacency_pairs(global_after),
            amount_before_mol=amounts_before,
            amount_after_mol=amounts_before,
            volume_before_m3=volumes_before,
            volume_after_m3=volumes_before,
            pressure_before_pa=pressures_before,
            pressure_after_pa=pressures_before,
            total_amount_before_mol=total_before,
            total_amount_after_mol=total_after,
            total_relative_drift=drift,
            topology_revision_before=revision_before,
            topology_revision_after=self.gas_state.topology_revision,
            transaction=transaction,
        )

    def rupture_coalescence_eligibility(self) -> EventEligibility:
        network = self.topology_state.to_network()
        candidates = [
            patch
            for patch in network.patches
            if not patch.contributes_to_volume
            and ":t1:" in patch.id
            and tuple(sorted(patch.adjacent)) == ("G", "H")
        ]
        if self.gas_state.topology_revision < 4:
            return EventEligibility(
                False,
                "G/H production T1 lineage film does not exist before event 4",
                candidates[0].id if candidates else None,
            )
        if len(candidates) != 1:
            return EventEligibility(False, "expected exactly one event-4 G/H lineage film")
        return EventEligibility(True, "event-4-created G/H film is present", candidates[0].id)

    def perform_rupture_coalescence(self) -> RuptureCoalescenceDiagnostics:
        self.validate()
        eligibility = self.rupture_coalescence_eligibility()
        if not eligibility.eligible or eligibility.film_id is None:
            raise RuntimeError(f"rupture/coalescence is not eligible: {eligibility.reason}")
        if self.gas_state.topology_revision != 4:
            raise RuntimeError("rupture/coalescence may execute exactly once after the four T1s")

        network_before = self.topology_state.to_network()
        region_ids_before = self.gas_state.region_ids()
        edge_ids_before = self.gas_state.edge_ids()
        total_before = self.gas_state.total_amount_mol()
        snapshot_before = {item.id: item for item in self.gas_state.regions}
        revision_before = self.gas_state.topology_revision

        thinfilm = {
            patch.id: _ThicknessState((self.film_thickness_m,))
            for patch in network_before.patches
            if EXTERIOR not in patch.adjacent
        }
        event_state = state_from_film_network(
            network_before,
            gas_regions=self.gas_state.regions,
            thinfilm_by_film=thinfilm,
            seed=0,
        )
        engine = TopologyEventEngine(
            RuptureConfig(
                thickness_threshold_m=0.5 * self.film_thickness_m,
                allow_user_trigger=True,
            ),
            seed=0,
        )
        transition = engine.trigger_user_rupture(
            event_state,
            eligibility.film_id,
            time_s=self.gas_state.time_s,
            detail="topology-enabled rupture of the film created by production T1 event 4",
        )
        if tuple(event.type for event in transition.emitted_events) != ("RUPTURE", "COALESCENCE"):
            raise RuntimeError("production event engine did not emit rupture plus coalescence")
        coalescence = transition.emitted_events[-1]
        if not coalescence.lineage or len(coalescence.bubble_ids_after) != 1:
            raise RuntimeError("coalescence did not provide explicit child lineage")
        child_id = coalescence.bubble_ids_after[0]
        parent_ids = tuple(coalescence.bubble_ids_before)
        if tuple(sorted(parent_ids)) != ("G", "H"):
            raise RuntimeError("unexpected coalescence parent set")

        alive = transition.state.active_bubbles()
        old_order = [rid for rid in region_ids_before if rid not in set(parent_ids)]
        new_order = old_order + [child_id]
        next_regions: list[GasRegionState] = []
        for region_id in new_order:
            bubble = alive[region_id]
            if region_id in snapshot_before:
                source = snapshot_before[region_id]
                next_regions.append(
                    GasRegionState(
                        id=source.id,
                        amount_mol=source.amount_mol,
                        volume_m3=source.volume_m3,
                        temperature_k=source.temperature_k,
                        surface_tension_n_m=source.surface_tension_n_m,
                    )
                )
            else:
                if bubble.gas_amount_mol is None:
                    raise RuntimeError("coalesced child lost gas amount")
                gamma = _surface_tension_for_merged_region(
                    amount_mol=bubble.gas_amount_mol,
                    volume_m3=bubble.volume_m3,
                    temperature_k=bubble.temperature_k,
                    ambient_pressure_pa=self.gas_state.ambient_pressure_pa,
                )
                next_regions.append(
                    GasRegionState(
                        id=child_id,
                        amount_mol=bubble.gas_amount_mol,
                        volume_m3=bubble.volume_m3,
                        temperature_k=bubble.temperature_k,
                        surface_tension_n_m=gamma,
                    )
                )

        active_films = transition.state.active_films
        parent_set = set(parent_ids)
        next_patches: list[FilmPatch] = []
        retained_patch_ids: set[str] = set()
        for patch in network_before.patches:
            if EXTERIOR in patch.adjacent:
                adjacent = tuple(
                    child_id if value in parent_set else value for value in patch.adjacent
                )
                next_patch = replace(patch, adjacent=(adjacent[0], adjacent[1]))
            else:
                film = active_films.get(patch.id)
                if film is None:
                    continue
                next_patch = replace(patch, adjacent=film.adjacent)
            next_patches.append(next_patch)
            retained_patch_ids.add(next_patch.id)

        next_junctions = tuple(
            junction
            for junction in network_before.junctions
            if set(junction.incident_film_ids).issubset(retained_patch_ids)
        )
        targets = {region.id: region.volume_m3 for region in next_regions}
        network_after = FilmNetwork(
            regions=tuple(GasRegion(rid, targets[rid]) for rid in new_order),
            patches=tuple(sorted(next_patches, key=lambda item: item.id)),
            junctions=tuple(sorted(next_junctions, key=lambda item: item.id)),
        )
        network_after.validate()

        self.gas_state.regions = next_regions
        self.gas_state.edges = shared_film_edges_from_topology(
            network_after,
            film_thickness_m=self.film_thickness_m,
            permeability_mol_m_per_m2_s_pa=self.permeability_mol_m_per_m2_s_pa,
        )
        self.gas_state.topology_revision += len(transition.emitted_events)
        self.topology_state = replace(
            TransientNetworkState.from_network(network_after),
            time_s=self.topology_state.time_s,
            step_index=self.topology_state.step_index,
        )
        self.topology_events.extend(transition.emitted_events)

        total_after = self.gas_state.total_amount_mol()
        drift = abs(total_after - total_before) / max(abs(total_before), 1.0e-300)
        if drift > 1.0e-12:
            raise RuntimeError("rupture/coalescence gas amount conservation tolerance was exceeded")
        unaffected = tuple(
            (
                rid,
                snapshot_before[rid].amount_mol,
                snapshot_before[rid].volume_m3,
                snapshot_before[rid].temperature_k,
                snapshot_before[rid].surface_tension_n_m,
            )
            for rid in old_order
        )
        after_by_id = self.gas_state.region_by_id()
        unaffected_after = tuple(
            (
                rid,
                after_by_id[rid].amount_mol,
                after_by_id[rid].volume_m3,
                after_by_id[rid].temperature_k,
                after_by_id[rid].surface_tension_n_m,
            )
            for rid in old_order
        )
        unaffected_exact = unaffected == unaffected_after
        if not unaffected_exact:
            raise RuntimeError("rupture/coalescence modified an unaffected stable gas region")
        if eligibility.film_id in self.gas_state.edge_ids():
            raise RuntimeError("ruptured film remained in rebuilt transport graph")
        self.validate()

        return RuptureCoalescenceDiagnostics(
            event_ids=tuple(event.id for event in transition.emitted_events),
            event_types=tuple(event.type for event in transition.emitted_events),
            retired_film_ids=(eligibility.film_id,),
            parent_region_ids=(parent_ids[0], parent_ids[1]),
            child_region_id=child_id,
            lineage=tuple(coalescence.lineage[child_id]),
            region_ids_before=region_ids_before,
            region_ids_after=self.gas_state.region_ids(),
            edge_ids_before=edge_ids_before,
            edge_ids_after=self.gas_state.edge_ids(),
            total_amount_before_mol=total_before,
            total_amount_after_mol=total_after,
            total_relative_drift=drift,
            unaffected_state_exact=unaffected_exact,
            topology_revision_before=revision_before,
            topology_revision_after=self.gas_state.topology_revision,
            emitted_events=transition.emitted_events,
        )


def supported_multievent_topology_gas_state(
    *,
    diffusion_enabled: bool = True,
    permeability_mol_m_per_m2_s_pa: float = 1.0e-8,
    film_thickness_m: float = 8.0e-7,
) -> MultiEventTopologyGasTransportState:
    network = build_supported_multievent_network()
    gas_state = gas_state_from_topology(
        network,
        diffusion_enabled=diffusion_enabled,
        film_thickness_m=film_thickness_m,
        permeability_mol_m_per_m2_s_pa=permeability_mol_m_per_m2_s_pa,
        surface_tension_by_region=SURFACE_TENSION_N_M,
    )
    state = MultiEventTopologyGasTransportState(
        topology_state=TransientNetworkState.from_network(network),
        gas_state=gas_state,
        film_thickness_m=film_thickness_m,
        permeability_mol_m_per_m2_s_pa=permeability_mol_m_per_m2_s_pa,
    )
    state.validate()
    if not state.event_eligibility(1).eligible:
        raise AssertionError("first T1 must be initially eligible")
    for event_number in (2, 3, 4):
        blocked = state.event_eligibility(event_number)
        if blocked.eligible or "adjacency already exists" not in blocked.reason:
            raise AssertionError(
                f"T1 event {event_number} must initially be blocked by prior-cell adjacency"
            )
    if state.rupture_coalescence_eligibility().eligible:
        raise AssertionError("rupture/coalescence must be ineligible before the fourth T1")
    return state
