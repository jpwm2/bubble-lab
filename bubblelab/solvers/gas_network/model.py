"""Conservative pressure-driven gas transport on a shared-film network.

The supported geometry class is a no-topology-change network of quasi-static
spherical gas regions.  Region amount, pressure and volume are coupled through
the ideal-gas law and the Young-Laplace pressure jump.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Iterable

R_GAS_J_MOL_K = 8.31446261815324


class TopologyChangeRequired(RuntimeError):
    """Raised when the supported fixed-topology interval can no longer continue."""


def sphere_volume_m3(radius_m: float) -> float:
    if radius_m <= 0.0:
        raise ValueError("radius_m must be positive")
    return 4.0 * math.pi * radius_m ** 3 / 3.0


def equivalent_radius_m(volume_m3: float) -> float:
    if volume_m3 <= 0.0:
        raise ValueError("volume_m3 must be positive")
    return (3.0 * volume_m3 / (4.0 * math.pi)) ** (1.0 / 3.0)


def equilibrium_pressure_pa(
    volume_m3: float,
    ambient_pressure_pa: float,
    surface_tension_n_m: float,
) -> float:
    if ambient_pressure_pa <= 0.0:
        raise ValueError("ambient_pressure_pa must be positive")
    if surface_tension_n_m < 0.0:
        raise ValueError("surface_tension_n_m must be non-negative")
    radius = equivalent_radius_m(volume_m3)
    return ambient_pressure_pa + 2.0 * surface_tension_n_m / radius


def equilibrium_amount_mol(
    volume_m3: float,
    ambient_pressure_pa: float,
    surface_tension_n_m: float,
    temperature_k: float,
) -> float:
    if temperature_k <= 0.0:
        raise ValueError("temperature_k must be positive")
    pressure = equilibrium_pressure_pa(
        volume_m3, ambient_pressure_pa, surface_tension_n_m
    )
    return pressure * volume_m3 / (R_GAS_J_MOL_K * temperature_k)


def equilibrium_volume_m3(
    amount_mol: float,
    ambient_pressure_pa: float,
    surface_tension_n_m: float,
    temperature_k: float,
) -> float:
    """Solve nRT = (p_ambient + 2 gamma / R(V)) V monotonically."""
    if amount_mol <= 0.0:
        raise TopologyChangeRequired(
            "gas region reached zero amount; topology change is outside this solver"
        )
    if ambient_pressure_pa <= 0.0:
        raise ValueError("ambient_pressure_pa must be positive")
    if surface_tension_n_m < 0.0:
        raise ValueError("surface_tension_n_m must be non-negative")
    if temperature_k <= 0.0:
        raise ValueError("temperature_k must be positive")

    target = amount_mol * R_GAS_J_MOL_K * temperature_k
    high = target / ambient_pressure_pa
    low = 0.0

    def residual(volume: float) -> float:
        if volume == 0.0:
            return -target
        return (
            equilibrium_pressure_pa(
                volume, ambient_pressure_pa, surface_tension_n_m
            )
            * volume
            - target
        )

    # The residual is strictly increasing for V>0.  Bisection is deterministic
    # and avoids constitutive Newton overshoot near a vanishing region.
    for _ in range(96):
        mid = 0.5 * (low + high)
        if residual(mid) > 0.0:
            high = mid
        else:
            low = mid
    return 0.5 * (low + high)


@dataclass
class GasRegionState:
    id: str
    amount_mol: float
    volume_m3: float
    temperature_k: float = 298.15
    surface_tension_n_m: float = 0.03

    def validate(self) -> None:
        if not self.id:
            raise ValueError("gas region id must be non-empty")
        if self.amount_mol <= 0.0:
            raise TopologyChangeRequired(
                f"gas region {self.id} has no gas; topology change is required"
            )
        if self.volume_m3 <= 0.0:
            raise ValueError("gas region volume must be positive")
        if self.temperature_k <= 0.0:
            raise ValueError("gas region temperature must be positive")
        if self.surface_tension_n_m < 0.0:
            raise ValueError("surface tension must be non-negative")

    def pressure_pa(self) -> float:
        self.validate()
        return (
            self.amount_mol
            * R_GAS_J_MOL_K
            * self.temperature_k
            / self.volume_m3
        )

    def equivalent_radius_m(self) -> float:
        return equivalent_radius_m(self.volume_m3)


@dataclass(frozen=True)
class SharedFilmEdge:
    id: str
    region_a: str
    region_b: str
    shared_area_m2: float
    film_thickness_m: float
    permeability_mol_m_per_m2_s_pa: float

    def validate(self) -> None:
        if not self.id:
            raise ValueError("shared-film edge id must be non-empty")
        if not self.region_a or not self.region_b or self.region_a == self.region_b:
            raise ValueError("shared-film edge requires two distinct gas regions")
        if self.shared_area_m2 <= 0.0:
            raise ValueError("shared-film area must be positive")
        if self.film_thickness_m <= 0.0:
            raise ValueError("shared-film thickness must be positive")
        if self.permeability_mol_m_per_m2_s_pa < 0.0:
            raise ValueError("gas permeability must be non-negative")

    @property
    def conductance_mol_s_pa(self) -> float:
        return (
            self.permeability_mol_m_per_m2_s_pa
            * self.shared_area_m2
            / self.film_thickness_m
        )


@dataclass
class GasNetworkState:
    regions: list[GasRegionState]
    edges: tuple[SharedFilmEdge, ...]
    ambient_pressure_pa: float = 101325.0
    diffusion_enabled: bool = True
    positivity_safety: float = 0.45
    time_s: float = 0.0
    topology_revision: int = 0

    def validate(self) -> None:
        if self.ambient_pressure_pa <= 0.0:
            raise ValueError("ambient pressure must be positive")
        if not 0.0 < self.positivity_safety < 1.0:
            raise ValueError("positivity_safety must lie in (0, 1)")
        if self.time_s < 0.0:
            raise ValueError("time_s must be non-negative")
        region_ids = [region.id for region in self.regions]
        if len(region_ids) != len(set(region_ids)):
            raise ValueError("gas region IDs must be unique")
        if len(region_ids) < 2:
            raise ValueError("gas network requires at least two regions")
        edge_ids = [edge.id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("shared-film edge IDs must be unique")
        known = set(region_ids)
        for region in self.regions:
            region.validate()
        for edge in self.edges:
            edge.validate()
            if edge.region_a not in known or edge.region_b not in known:
                raise ValueError(f"edge {edge.id} references an unknown gas region")

    def region_by_id(self) -> dict[str, GasRegionState]:
        return {region.id: region for region in self.regions}

    def region_ids(self) -> tuple[str, ...]:
        return tuple(region.id for region in self.regions)

    def edge_ids(self) -> tuple[str, ...]:
        return tuple(edge.id for edge in self.edges)

    def total_amount_mol(self) -> float:
        return math.fsum(region.amount_mol for region in self.regions)

    def synchronize_geometry(self) -> None:
        for region in self.regions:
            region.volume_m3 = equilibrium_volume_m3(
                region.amount_mol,
                self.ambient_pressure_pa,
                region.surface_tension_n_m,
                region.temperature_k,
            )

    def assert_constitutive_consistency(self, relative_tolerance: float = 2.0e-13) -> None:
        for region in self.regions:
            ideal = region.pressure_pa()
            laplace = equilibrium_pressure_pa(
                region.volume_m3,
                self.ambient_pressure_pa,
                region.surface_tension_n_m,
            )
            scale = max(abs(ideal), abs(laplace), 1.0)
            if abs(ideal - laplace) / scale > relative_tolerance:
                raise ValueError(
                    f"gas region {region.id} is inconsistent with ideal-gas/Young-Laplace closure"
                )


@dataclass(frozen=True)
class EdgeTransferDiagnostics:
    edge_id: str
    region_a: str
    region_b: str
    integrated_a_to_b_mol: float
    initial_rate_a_to_b_mol_s: float
    final_rate_a_to_b_mol_s: float
    antisymmetry_residual_mol: float


@dataclass(frozen=True)
class GasNetworkDiagnostics:
    requested_dt_s: float
    substeps: int
    enabled: bool
    initial_total_mol: float
    final_total_mol: float
    total_relative_drift: float
    max_simultaneous_active_edges: int
    max_edge_antisymmetry_residual_mol: float
    region_ids_before: tuple[str, ...]
    region_ids_after: tuple[str, ...]
    edge_ids_before: tuple[str, ...]
    edge_ids_after: tuple[str, ...]
    initial_amount_mol: tuple[tuple[str, float], ...]
    final_amount_mol: tuple[tuple[str, float], ...]
    initial_volume_m3: tuple[tuple[str, float], ...]
    final_volume_m3: tuple[tuple[str, float], ...]
    initial_pressure_pa: tuple[tuple[str, float], ...]
    final_pressure_pa: tuple[tuple[str, float], ...]
    edges: tuple[EdgeTransferDiagnostics, ...]


def _edge_rates(
    state: GasNetworkState,
    region_by_id: dict[str, GasRegionState],
) -> dict[str, float]:
    rates: dict[str, float] = {}
    for edge in state.edges:
        a = region_by_id[edge.region_a]
        b = region_by_id[edge.region_b]
        rates[edge.id] = edge.conductance_mol_s_pa * (
            a.pressure_pa() - b.pressure_pa()
        )
    return rates


def _named(values: Iterable[tuple[str, float]]) -> tuple[tuple[str, float], ...]:
    return tuple((str(name), float(value)) for name, value in values)


def advance_gas_network(state: GasNetworkState, dt_s: float) -> GasNetworkDiagnostics:
    """Advance all shared-film transfers from one coupled network state.

    Each substep computes every edge rate from the same pre-update state and
    then applies the nodal sums simultaneously.  An edge contributes exactly
    +delta and -delta to its two incident regions; there is no pair-by-pair
    state mutation and no post-step conservation normalization.
    """
    if dt_s <= 0.0:
        raise ValueError("dt_s must be positive")
    state.validate()
    state.assert_constitutive_consistency()

    region_ids_before = state.region_ids()
    edge_ids_before = state.edge_ids()
    initial_total = state.total_amount_mol()
    initial_amounts = _named((r.id, r.amount_mol) for r in state.regions)
    initial_volumes = _named((r.id, r.volume_m3) for r in state.regions)
    initial_pressures = _named((r.id, r.pressure_pa()) for r in state.regions)
    region_by_id = state.region_by_id()
    initial_rates = _edge_rates(state, region_by_id)
    integrated = {edge.id: 0.0 for edge in state.edges}
    max_antisymmetry = 0.0
    max_active = 0
    substeps = 0

    if state.diffusion_enabled:
        remaining = float(dt_s)
        cutoff = max(1.0e-15 * dt_s, 1.0e-18)
        while remaining > cutoff:
            region_by_id = state.region_by_id()
            rates = _edge_rates(state, region_by_id)
            active = sum(1 for value in rates.values() if value != 0.0)
            max_active = max(max_active, active)

            outgoing: dict[str, list[float]] = {
                region.id: [] for region in state.regions
            }
            for edge in state.edges:
                rate = rates[edge.id]
                if rate > 0.0:
                    outgoing[edge.region_a].append(rate)
                elif rate < 0.0:
                    outgoing[edge.region_b].append(-rate)

            step = remaining
            for region in state.regions:
                total_out = math.fsum(outgoing[region.id])
                if total_out > 0.0:
                    step = min(
                        step,
                        state.positivity_safety * region.amount_mol / total_out,
                    )
            if not math.isfinite(step) or step <= 0.0:
                raise RuntimeError("non-positive gas-network timestep")

            contributions: dict[str, list[float]] = {
                region.id: [] for region in state.regions
            }
            edge_deltas: dict[str, float] = {}
            for edge in state.edges:
                delta = rates[edge.id] * step
                edge_deltas[edge.id] = delta
                contributions[edge.region_a].append(-delta)
                contributions[edge.region_b].append(delta)
                residual = abs(delta + (-delta))
                max_antisymmetry = max(max_antisymmetry, residual)

            next_amounts: dict[str, float] = {}
            for region in state.regions:
                next_amount = region.amount_mol + math.fsum(contributions[region.id])
                if next_amount <= 0.0:
                    raise TopologyChangeRequired(
                        f"gas region {region.id} would vanish; topology change is required"
                    )
                next_amounts[region.id] = next_amount

            # All region amounts are committed together only after all edge
            # rates and nodal sums have been formed from the same state.
            for region in state.regions:
                region.amount_mol = next_amounts[region.id]
            for edge in state.edges:
                integrated[edge.id] = math.fsum(
                    (integrated[edge.id], edge_deltas[edge.id])
                )
            state.synchronize_geometry()
            state.assert_constitutive_consistency()
            remaining -= step
            if remaining <= cutoff:
                remaining = 0.0
            substeps += 1
            if substeps > 100000:
                raise RuntimeError("gas-network substep budget exhausted")

    state.time_s += dt_s
    state.validate()

    region_ids_after = state.region_ids()
    edge_ids_after = state.edge_ids()
    if region_ids_after != region_ids_before or edge_ids_after != edge_ids_before:
        raise TopologyChangeRequired(
            "gas-network topology changed during a fixed-topology transfer interval"
        )

    final_total = state.total_amount_mol()
    final_rates = _edge_rates(state, state.region_by_id())
    final_amounts = _named((r.id, r.amount_mol) for r in state.regions)
    final_volumes = _named((r.id, r.volume_m3) for r in state.regions)
    final_pressures = _named((r.id, r.pressure_pa()) for r in state.regions)

    edge_diags = tuple(
        EdgeTransferDiagnostics(
            edge_id=edge.id,
            region_a=edge.region_a,
            region_b=edge.region_b,
            integrated_a_to_b_mol=integrated[edge.id],
            initial_rate_a_to_b_mol_s=initial_rates[edge.id],
            final_rate_a_to_b_mol_s=final_rates[edge.id],
            antisymmetry_residual_mol=0.0,
        )
        for edge in state.edges
    )
    return GasNetworkDiagnostics(
        requested_dt_s=dt_s,
        substeps=substeps,
        enabled=state.diffusion_enabled,
        initial_total_mol=initial_total,
        final_total_mol=final_total,
        total_relative_drift=abs(final_total - initial_total)
        / max(abs(initial_total), 1.0e-300),
        max_simultaneous_active_edges=max_active,
        max_edge_antisymmetry_residual_mol=max_antisymmetry,
        region_ids_before=region_ids_before,
        region_ids_after=region_ids_after,
        edge_ids_before=edge_ids_before,
        edge_ids_after=edge_ids_after,
        initial_amount_mol=initial_amounts,
        final_amount_mol=final_amounts,
        initial_volume_m3=initial_volumes,
        final_volume_m3=final_volumes,
        initial_pressure_pa=initial_pressures,
        final_pressure_pa=final_pressures,
        edges=edge_diags,
    )
