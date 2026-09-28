"""Bounded repeated-T1 gas transport on one six-region canonical FilmNetwork.

The qualified path contains two spatially separate local production T1 cells that
share gas regions A/B.  Event 1 switches A-B -> C-D.  Event 2 switches E-F ->
A-B, and is intentionally *ineligible* before event 1 because the A-B adjacency
already exists.  Event 1 removes that blocking adjacency, so the second real
production transaction is valid only on the canonical post-event topology.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from bubblelab.solvers.equilibrium.network import (
    EXTERIOR,
    FilmNetwork,
    FilmPatch,
    GasRegion,
    PlateauJunction,
)
from bubblelab.solvers.transient.network.core import TransientNetworkState
from bubblelab.solvers.transient.network.t1 import (
    EligibilityResult,
    T1TransactionResult,
    T1TransactionSettings,
    build_supported_pre_t1_network,
    detect_t1_eligibility,
    internal_adjacency_pairs,
    perform_t1_transaction,
)

from .model import GasNetworkDiagnostics, GasNetworkState, advance_gas_network
from .topology import (
    TopologyGasEventDiagnostics,
    gas_state_from_topology,
    shared_film_edges_from_topology,
)


EVENT1_PREFIX = "event1:"
EVENT2_PREFIX = "event2:"
EVENT1_BLOCKING_FILM_ID = f"{EVENT1_PREFIX}film:AB:central"
REPEATED_SURFACE_TENSION_N_M = {
    "A": 0.031,
    "B": 0.029,
    "C": 0.032,
    "D": 0.028,
    "E": 0.033,
    "F": 0.027,
}


def _renamed_fixture(
    network: FilmNetwork,
    *,
    region_map: Mapping[str, str],
    id_prefix: str,
) -> FilmNetwork:
    """Rename one accepted local fixture without changing its geometry."""
    patch_ids = {patch.id: f"{id_prefix}{patch.id}" for patch in network.patches}

    def region_id(value: str) -> str:
        return value if value == EXTERIOR else region_map[value]

    regions = tuple(
        GasRegion(region_map[region.id], region.target_volume_m3)
        for region in network.regions
    )
    patches = tuple(
        FilmPatch(
            id=patch_ids[patch.id],
            mesh=patch.mesh,
            adjacent=(region_id(patch.adjacent[0]), region_id(patch.adjacent[1])),
            sheet_tension_n_m=patch.sheet_tension_n_m,
            fixed_vertex_indices=patch.fixed_vertex_indices,
            contributes_to_volume=patch.contributes_to_volume,
        )
        for patch in network.patches
    )
    junctions = tuple(
        PlateauJunction(
            id=f"{id_prefix}{junction.id}",
            incident_film_ids=tuple(patch_ids[item] for item in junction.incident_film_ids),
            vertex_indices_by_film=junction.vertex_indices_by_film,
            normal_plane_only=junction.normal_plane_only,
            rigid_normal_translation=junction.rigid_normal_translation,
        )
        for junction in network.junctions
    )
    renamed = FilmNetwork(regions, patches, junctions)
    renamed.validate()
    return renamed


def _combine_overlapping_regions(*networks: FilmNetwork) -> FilmNetwork:
    """Combine local cells while summing volume support for shared gas IDs."""
    targets: dict[str, float] = {}
    patches: list[FilmPatch] = []
    junctions: list[PlateauJunction] = []
    for network in networks:
        for region in network.regions:
            targets[region.id] = targets.get(region.id, 0.0) + region.target_volume_m3
        patches.extend(network.patches)
        junctions.extend(network.junctions)
    combined = FilmNetwork(
        regions=tuple(GasRegion(region_id, targets[region_id]) for region_id in sorted(targets)),
        patches=tuple(sorted(patches, key=lambda item: item.id)),
        junctions=tuple(sorted(junctions, key=lambda item: item.id)),
    )
    combined.validate()
    for region in combined.regions:
        actual = combined.region_volume(region.id)
        error = abs(actual - region.target_volume_m3) / region.target_volume_m3
        if error > 1.0e-12:
            raise AssertionError("combined repeated-T1 volume support is inconsistent")
    return combined


def build_supported_repeated_t1_network() -> FilmNetwork:
    """Build the six-region canonical topology for two dependent T1 switches."""
    first = _renamed_fixture(
        build_supported_pre_t1_network(
            resolution_m=0.12,
            collapse_fraction=0.35,
            half_extent_m=1.0,
            depth_m=0.6,
            sheet_tension_n_m=1.0,
            origin_xy=(-2.5, 0.0),
        ),
        region_map={"A": "A", "B": "B", "C": "C", "D": "D"},
        id_prefix=EVENT1_PREFIX,
    )
    second = _renamed_fixture(
        build_supported_pre_t1_network(
            resolution_m=0.12,
            collapse_fraction=0.35,
            half_extent_m=1.0,
            depth_m=0.6,
            sheet_tension_n_m=1.0,
            origin_xy=(2.5, 0.0),
        ),
        # The second old pair is E/F and its future pair is A/B.  The latter is
        # blocked by event 1's central film until the first switch removes it.
        region_map={"A": "E", "B": "F", "C": "A", "D": "B"},
        id_prefix=EVENT2_PREFIX,
    )
    network = _combine_overlapping_regions(first, second)
    if tuple(region.id for region in network.regions) != ("A", "B", "C", "D", "E", "F"):
        raise AssertionError("repeated-T1 fixture must expose six stable gas regions")
    return network


def _region_snapshot(state: GasNetworkState) -> tuple[
    tuple[tuple[str, float], ...],
    tuple[tuple[str, float], ...],
    tuple[tuple[str, float], ...],
]:
    return (
        tuple((item.id, item.amount_mol) for item in state.regions),
        tuple((item.id, item.volume_m3) for item in state.regions),
        tuple((item.id, item.pressure_pa()) for item in state.regions),
    )


def _with_current_targets(network: FilmNetwork, gas_state: GasNetworkState) -> FilmNetwork:
    gas = gas_state.region_by_id()
    return FilmNetwork(
        tuple(GasRegion(region.id, gas[region.id].volume_m3) for region in network.regions),
        network.patches,
        network.junctions,
    )


def _event1_patch(patch: FilmPatch) -> bool:
    return patch.id.startswith(EVENT1_PREFIX) and not patch.contributes_to_volume


def _event2_patch(patch: FilmPatch) -> bool:
    return patch.id.startswith(EVENT2_PREFIX) and not patch.contributes_to_volume


def _event1_lineage_marker(patch: FilmPatch) -> bool:
    return patch.id == EVENT1_BLOCKING_FILM_ID or (
        ":t1:" in patch.id and tuple(sorted(patch.adjacent)) == ("C", "D")
    )


def _local_event_network(
    global_network: FilmNetwork,
    gas_state: GasNetworkState,
    event_number: int,
) -> FilmNetwork:
    """Take a canonical local production-T1 view from the evolving full network.

    All volume-support shells are retained so the production projection operates
    on the complete six-region gas volumes.  For event 2, the current event-1
    lineage film is included without its remote junctions.  Before event 1 this
    is the A/B central blocker; afterwards it is the created C/D film, which both
    proves dependency and carries the production serial into event 2.
    """
    if event_number not in (1, 2):
        raise ValueError("event_number must be 1 or 2")
    if event_number == 1:
        patches = tuple(
            patch
            for patch in global_network.patches
            if patch.contributes_to_volume or _event1_patch(patch)
        )
        junctions = tuple(
            junction for junction in global_network.junctions if junction.id.startswith(EVENT1_PREFIX)
        )
    else:
        patches = tuple(
            patch
            for patch in global_network.patches
            if patch.contributes_to_volume or _event2_patch(patch) or _event1_lineage_marker(patch)
        )
        junctions = tuple(
            junction for junction in global_network.junctions if junction.id.startswith(EVENT2_PREFIX)
        )
    local = FilmNetwork(global_network.regions, patches, junctions)
    local = _with_current_targets(local, gas_state)
    local.validate()
    return local


def _merge_transaction(
    global_before: FilmNetwork,
    local_before: FilmNetwork,
    local_after: FilmNetwork,
) -> FilmNetwork:
    local_patch_ids = {patch.id for patch in local_before.patches}
    local_junction_ids = {junction.id for junction in local_before.junctions}
    patches = [patch for patch in global_before.patches if patch.id not in local_patch_ids]
    patches.extend(local_after.patches)
    junctions = [
        junction for junction in global_before.junctions if junction.id not in local_junction_ids
    ]
    junctions.extend(local_after.junctions)
    merged = FilmNetwork(
        local_after.regions,
        tuple(sorted(patches, key=lambda item: item.id)),
        tuple(sorted(junctions, key=lambda item: item.id)),
    )
    merged.validate()
    return merged


@dataclass
class RepeatedTopologyGasTransportState:
    topology_state: TransientNetworkState
    gas_state: GasNetworkState
    film_thickness_m: float = 8.0e-7
    permeability_mol_m_per_m2_s_pa: float = 1.0e-8
    t1_settings: T1TransactionSettings = T1TransactionSettings()

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
        if tuple((e.id, e.region_a, e.region_b) for e in self.gas_state.edges) != tuple(
            (e.id, e.region_a, e.region_b) for e in expected
        ):
            raise ValueError("gas transport graph is stale relative to canonical topology")
        if self.gas_state.topology_revision not in (0, 1, 2):
            raise ValueError("bounded repeated-T1 state supports revisions 0..2")

    def advance(self, dt_s: float) -> GasNetworkDiagnostics:
        self.validate()
        diagnostics = advance_gas_network(self.gas_state, dt_s)
        self.validate()
        return diagnostics

    def event_eligibility(self, event_number: int) -> EligibilityResult:
        local = _local_event_network(self.topology_state.to_network(), self.gas_state, event_number)
        return detect_t1_eligibility(local, self.t1_settings.eligibility)

    def perform_t1(self) -> TopologyGasEventDiagnostics:
        """Execute the next distinct production T1 on a canonical local view."""
        self.validate()
        event_number = self.gas_state.topology_revision + 1
        if event_number not in (1, 2):
            raise RuntimeError("bounded repeated-T1 state has already completed both events")
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
        amounts_before, volumes_before, pressures_before = _region_snapshot(self.gas_state)
        total_before = self.gas_state.total_amount_mol()
        revision_before = self.gas_state.topology_revision

        event_state = TransientNetworkState.from_network(local_before)
        event_state = replace(
            event_state,
            time_s=self.topology_state.time_s,
            step_index=self.topology_state.step_index,
        )
        transaction = perform_t1_transaction(event_state, self.t1_settings)
        global_after = _merge_transaction(global_before, local_before, transaction.after_network)
        next_topology = TransientNetworkState.from_network(global_after)
        self.topology_state = replace(
            next_topology,
            time_s=self.topology_state.time_s,
            step_index=self.topology_state.step_index,
        )
        self.gas_state.edges = shared_film_edges_from_topology(
            global_after,
            film_thickness_m=self.film_thickness_m,
            permeability_mol_m_per_m2_s_pa=self.permeability_mol_m_per_m2_s_pa,
        )
        self.gas_state.topology_revision += 1

        region_ids_after = self.gas_state.region_ids()
        edge_ids_after = self.gas_state.edge_ids()
        adjacency_after = internal_adjacency_pairs(global_after)
        amounts_after, volumes_after, pressures_after = _region_snapshot(self.gas_state)
        total_after = self.gas_state.total_amount_mol()
        drift = abs(total_after - total_before) / max(abs(total_before), 1.0e-300)
        if region_ids_after != region_ids_before:
            raise RuntimeError("T1 changed stable gas-region identities")
        if amounts_after != amounts_before or volumes_after != volumes_before or pressures_after != pressures_before:
            raise RuntimeError("T1 reset continuous gas state")
        if drift > 1.0e-12:
            raise RuntimeError("T1 gas amount conservation tolerance was exceeded")
        retired = set(transaction.lineage.retired_film_ids)
        created = set(transaction.lineage.created_film_ids)
        if retired.intersection(edge_ids_after):
            raise RuntimeError("retired T1 film remained in the rebuilt transport graph")
        if not created.issubset(set(edge_ids_after)):
            raise RuntimeError("created T1 film is absent from the rebuilt transport graph")
        self.validate()

        return TopologyGasEventDiagnostics(
            event_id=transaction.lineage.event_id,
            retired_film_ids=transaction.lineage.retired_film_ids,
            created_film_ids=transaction.lineage.created_film_ids,
            region_ids_before=region_ids_before,
            region_ids_after=region_ids_after,
            edge_ids_before=edge_ids_before,
            edge_ids_after=edge_ids_after,
            adjacency_before=adjacency_before,
            adjacency_after=adjacency_after,
            amount_before_mol=amounts_before,
            amount_after_mol=amounts_after,
            volume_before_m3=volumes_before,
            volume_after_m3=volumes_after,
            pressure_before_pa=pressures_before,
            pressure_after_pa=pressures_after,
            total_amount_before_mol=total_before,
            total_amount_after_mol=total_after,
            total_relative_drift=drift,
            topology_revision_before=revision_before,
            topology_revision_after=self.gas_state.topology_revision,
            transaction=transaction,
        )


def supported_repeated_t1_gas_transport_state(
    *,
    diffusion_enabled: bool = True,
    permeability_mol_m_per_m2_s_pa: float = 1.0e-8,
    film_thickness_m: float = 8.0e-7,
) -> RepeatedTopologyGasTransportState:
    """Return the accepted six-region, two-event dependent gas-transport state."""
    network = build_supported_repeated_t1_network()
    topology_state = TransientNetworkState.from_network(network)
    gas_state = gas_state_from_topology(
        network,
        diffusion_enabled=diffusion_enabled,
        film_thickness_m=film_thickness_m,
        permeability_mol_m_per_m2_s_pa=permeability_mol_m_per_m2_s_pa,
        surface_tension_by_region=REPEATED_SURFACE_TENSION_N_M,
    )
    state = RepeatedTopologyGasTransportState(
        topology_state=topology_state,
        gas_state=gas_state,
        film_thickness_m=film_thickness_m,
        permeability_mol_m_per_m2_s_pa=permeability_mol_m_per_m2_s_pa,
    )
    state.validate()
    first = state.event_eligibility(1)
    second_before_first = state.event_eligibility(2)
    if not first.eligible:
        raise AssertionError(f"first repeated-T1 event is not eligible: {first.reason}")
    if second_before_first.eligible or "adjacency already exists" not in second_before_first.reason:
        raise AssertionError(
            "second repeated-T1 event must be blocked by the pre-first-event A/B adjacency"
        )
    return state
