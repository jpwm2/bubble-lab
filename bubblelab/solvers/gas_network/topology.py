"""Conservative gas transport across one supported canonical T1 topology change."""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Mapping

from bubblelab.solvers.equilibrium.network import EXTERIOR, FilmNetwork, GasRegion
from bubblelab.solvers.transient.network.core import TransientNetworkState
from bubblelab.solvers.transient.network.t1 import (
    T1TransactionResult,
    T1TransactionSettings,
    build_supported_pre_t1_state,
    internal_adjacency_pairs,
    perform_t1_transaction,
)

from .model import (
    GasNetworkDiagnostics,
    GasNetworkState,
    GasRegionState,
    SharedFilmEdge,
    advance_gas_network,
    equilibrium_amount_mol,
)


@dataclass(frozen=True)
class TopologyGasEventDiagnostics:
    event_id: str
    retired_film_ids: tuple[str, ...]
    created_film_ids: tuple[str, ...]
    region_ids_before: tuple[str, ...]
    region_ids_after: tuple[str, ...]
    edge_ids_before: tuple[str, ...]
    edge_ids_after: tuple[str, ...]
    adjacency_before: tuple[tuple[str, str], ...]
    adjacency_after: tuple[tuple[str, str], ...]
    amount_before_mol: tuple[tuple[str, float], ...]
    amount_after_mol: tuple[tuple[str, float], ...]
    volume_before_m3: tuple[tuple[str, float], ...]
    volume_after_m3: tuple[tuple[str, float], ...]
    pressure_before_pa: tuple[tuple[str, float], ...]
    pressure_after_pa: tuple[tuple[str, float], ...]
    total_amount_before_mol: float
    total_amount_after_mol: float
    total_relative_drift: float
    topology_revision_before: int
    topology_revision_after: int
    transaction: T1TransactionResult


def _region_snapshot(state: GasNetworkState) -> tuple[
    tuple[tuple[str, float], ...],
    tuple[tuple[str, float], ...],
    tuple[tuple[str, float], ...],
]:
    amounts = tuple((item.id, item.amount_mol) for item in state.regions)
    volumes = tuple((item.id, item.volume_m3) for item in state.regions)
    pressures = tuple((item.id, item.pressure_pa()) for item in state.regions)
    return amounts, volumes, pressures


def shared_film_edges_from_topology(
    network: FilmNetwork,
    *,
    film_thickness_m: float,
    permeability_mol_m_per_m2_s_pa: float,
) -> tuple[SharedFilmEdge, ...]:
    """Build transport edges only from real internal films in canonical topology."""
    if film_thickness_m <= 0.0:
        raise ValueError("film_thickness_m must be positive")
    if permeability_mol_m_per_m2_s_pa < 0.0:
        raise ValueError("permeability must be non-negative")
    network.validate()
    region_ids = {region.id for region in network.regions}
    edges = []
    for patch in sorted(network.patches, key=lambda item: item.id):
        if EXTERIOR in patch.adjacent:
            continue
        if not set(patch.adjacent).issubset(region_ids):
            continue
        area = patch.mesh.area()
        if area <= 0.0:
            raise ValueError(f"internal film {patch.id} has zero area")
        edges.append(
            SharedFilmEdge(
                id=patch.id,
                region_a=patch.adjacent[0],
                region_b=patch.adjacent[1],
                shared_area_m2=area,
                film_thickness_m=film_thickness_m,
                permeability_mol_m_per_m2_s_pa=permeability_mol_m_per_m2_s_pa,
            )
        )
    if len(edges) < 2:
        raise ValueError("supported topology gas transport requires at least two real shared films")
    return tuple(edges)


def gas_state_from_topology(
    network: FilmNetwork,
    *,
    ambient_pressure_pa: float = 101325.0,
    temperature_k: float = 298.15,
    surface_tension_n_m: float = 0.03,
    surface_tension_by_region: Mapping[str, float] | None = None,
    diffusion_enabled: bool = True,
    positivity_safety: float = 0.45,
    film_thickness_m: float = 8.0e-7,
    permeability_mol_m_per_m2_s_pa: float = 1.0e-8,
) -> GasNetworkState:
    """Initialize gas amount/pressure/volume from the canonical region volumes."""
    network.validate()
    tensions = dict(surface_tension_by_region or {})
    regions: list[GasRegionState] = []
    for region in network.regions:
        volume = float(network.region_volume(region.id))
        tension = float(tensions.get(region.id, surface_tension_n_m))
        amount = equilibrium_amount_mol(
            volume,
            ambient_pressure_pa,
            tension,
            temperature_k,
        )
        regions.append(
            GasRegionState(
                id=region.id,
                amount_mol=amount,
                volume_m3=volume,
                temperature_k=temperature_k,
                surface_tension_n_m=tension,
            )
        )
    state = GasNetworkState(
        regions=regions,
        edges=shared_film_edges_from_topology(
            network,
            film_thickness_m=film_thickness_m,
            permeability_mol_m_per_m2_s_pa=permeability_mol_m_per_m2_s_pa,
        ),
        ambient_pressure_pa=ambient_pressure_pa,
        diffusion_enabled=diffusion_enabled,
        positivity_safety=positivity_safety,
    )
    state.validate()
    state.assert_constitutive_consistency()
    return state


def _network_with_current_gas_volumes(
    network: FilmNetwork,
    gas_state: GasNetworkState,
) -> FilmNetwork:
    gas_by_id = gas_state.region_by_id()
    if tuple(region.id for region in network.regions) != gas_state.region_ids():
        raise ValueError("canonical topology and gas region identities differ")
    regions = tuple(
        GasRegion(region.id, gas_by_id[region.id].volume_m3)
        for region in network.regions
    )
    updated = FilmNetwork(regions, network.patches, network.junctions)
    updated.validate()
    return updated


@dataclass
class TopologyGasTransportState:
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
        actual = self.gas_state.edges
        if tuple((e.id, e.region_a, e.region_b) for e in actual) != tuple(
            (e.id, e.region_a, e.region_b) for e in expected
        ):
            raise ValueError("gas transport graph is stale relative to canonical topology")

    def advance(self, dt_s: float) -> GasNetworkDiagnostics:
        self.validate()
        result = advance_gas_network(self.gas_state, dt_s)
        self.validate()
        return result

    def perform_t1(self) -> TopologyGasEventDiagnostics:
        """Perform one real T1 and rebuild transport edges from its resulting topology."""
        self.validate()
        region_ids_before = self.gas_state.region_ids()
        edge_ids_before = self.gas_state.edge_ids()
        adjacency_before = internal_adjacency_pairs(self.topology_state)
        amounts_before, volumes_before, pressures_before = _region_snapshot(self.gas_state)
        total_before = self.gas_state.total_amount_mol()
        revision_before = self.gas_state.topology_revision

        event_network = _network_with_current_gas_volumes(
            self.topology_state.to_network(),
            self.gas_state,
        )
        event_state = TransientNetworkState.from_network(event_network)
        event_state = replace(
            event_state,
            time_s=self.topology_state.time_s,
            step_index=self.topology_state.step_index,
        )
        transaction = perform_t1_transaction(event_state, self.t1_settings)
        self.topology_state = transaction.after
        self.gas_state.edges = shared_film_edges_from_topology(
            transaction.after_network,
            film_thickness_m=self.film_thickness_m,
            permeability_mol_m_per_m2_s_pa=self.permeability_mol_m_per_m2_s_pa,
        )
        self.gas_state.topology_revision += 1

        region_ids_after = self.gas_state.region_ids()
        edge_ids_after = self.gas_state.edge_ids()
        adjacency_after = internal_adjacency_pairs(self.topology_state)
        amounts_after, volumes_after, pressures_after = _region_snapshot(self.gas_state)
        total_after = self.gas_state.total_amount_mol()
        drift = abs(total_after - total_before) / max(abs(total_before), 1.0e-300)

        if region_ids_after != region_ids_before:
            raise RuntimeError("T1 changed stable gas-region identities")
        if amounts_after != amounts_before:
            raise RuntimeError("T1 reset gas amount")
        if volumes_after != volumes_before:
            raise RuntimeError("T1 reset gas volume")
        if pressures_after != pressures_before:
            raise RuntimeError("T1 reset gas pressure")
        if drift > 1.0e-12:
            raise RuntimeError("T1 gas amount conservation tolerance was exceeded")
        retired = set(transaction.lineage.retired_film_ids)
        if retired.intersection(edge_ids_after):
            raise RuntimeError("retired T1 film remained in the gas transport graph")
        created = set(transaction.lineage.created_film_ids)
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


def supported_t1_gas_transport_state(
    *,
    diffusion_enabled: bool = True,
    permeability_mol_m_per_m2_s_pa: float = 1.0e-8,
    film_thickness_m: float = 8.0e-7,
) -> TopologyGasTransportState:
    """Deterministic bounded fixture with four stable regions and a real T1 event."""
    topology_state = build_supported_pre_t1_state(
        resolution_m=0.12,
        collapse_fraction=0.35,
        half_extent_m=1.0,
        depth_m=0.6,
        sheet_tension_n_m=1.0,
    )
    gas_state = gas_state_from_topology(
        topology_state.to_network(),
        diffusion_enabled=diffusion_enabled,
        film_thickness_m=film_thickness_m,
        permeability_mol_m_per_m2_s_pa=permeability_mol_m_per_m2_s_pa,
        surface_tension_by_region={
            "A": 0.030,
            "B": 0.030,
            "C": 0.032,
            "D": 0.028,
        },
    )
    combined = TopologyGasTransportState(
        topology_state=topology_state,
        gas_state=gas_state,
        film_thickness_m=film_thickness_m,
        permeability_mol_m_per_m2_s_pa=permeability_mol_m_per_m2_s_pa,
    )
    combined.validate()
    if len(combined.gas_state.regions) < 4 or len(combined.gas_state.edges) < 2:
        raise AssertionError("supported topology gas fixture is under-connected")
    if math.isclose(
        combined.gas_state.region_by_id()["C"].pressure_pa(),
        combined.gas_state.region_by_id()["D"].pressure_pa(),
        rel_tol=0.0,
        abs_tol=1.0e-15,
    ):
        raise AssertionError("post-T1 opposite regions must have a pressure gradient")
    return combined
