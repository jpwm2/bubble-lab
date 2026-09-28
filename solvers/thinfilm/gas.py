"""Pairwise pressure-driven gas permeation through a shared soap film."""
from __future__ import annotations

from dataclasses import dataclass
import math

R_GAS_J_MOL_K = 8.31446261815324


@dataclass
class GasRegionState:
    """Ideal-gas region state in SI units."""

    id: str
    volume_m3: float
    amount_mol: float
    temperature_k: float = 298.15

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("gas region id must be non-empty")
        if self.volume_m3 <= 0.0:
            raise ValueError("gas volume must be positive")
        if self.amount_mol < 0.0:
            raise ValueError("gas amount must be non-negative")
        if self.temperature_k <= 0.0:
            raise ValueError("gas temperature must be positive")

    @property
    def pressure_pa(self) -> float:
        return self.amount_mol * R_GAS_J_MOL_K * self.temperature_k / self.volume_m3


@dataclass(frozen=True)
class GasTransferDiagnostics:
    requested_dt_s: float
    substeps: int
    amount_transferred_a_to_b_mol: float
    initial_total_mol: float
    final_total_mol: float
    total_relative_drift: float
    initial_pressure_difference_pa: float
    final_pressure_difference_pa: float


@dataclass(frozen=True)
class GasTransferPair:
    """One shared-film permeation connection.

    permeability_mol_m_per_m2_s_pa has units mol*m/(m^2*s*Pa).
    Conductance is permeability * area / thickness [mol/(s*Pa)].
    Positive transfer is from region_a to region_b when p_a > p_b.
    """

    region_a: str
    region_b: str
    shared_area_m2: float
    film_thickness_m: float
    permeability_mol_m_per_m2_s_pa: float = 1.0e-16
    positivity_safety: float = 0.45
    max_substeps: int = 10000

    def __post_init__(self) -> None:
        if self.region_a == self.region_b:
            raise ValueError("gas transfer requires two distinct regions")
        if self.shared_area_m2 <= 0.0 or self.film_thickness_m <= 0.0:
            raise ValueError("shared-film area and thickness must be positive")
        if self.permeability_mol_m_per_m2_s_pa < 0.0:
            raise ValueError("gas permeability must be non-negative")
        if not 0.0 < self.positivity_safety < 1.0:
            raise ValueError("positivity_safety must lie in (0, 1)")
        if self.max_substeps < 1:
            raise ValueError("max_substeps must be positive")

    @property
    def conductance_mol_s_pa(self) -> float:
        return (
            self.permeability_mol_m_per_m2_s_pa
            * self.shared_area_m2
            / self.film_thickness_m
        )

    def _rate_a_to_b_mol_s(
        self,
        a: GasRegionState,
        b: GasRegionState,
    ) -> float:
        return self.conductance_mol_s_pa * (a.pressure_pa - b.pressure_pa)

    def explicit_stability_limit_s(
        self,
        a: GasRegionState,
        b: GasRegionState,
    ) -> float:
        conductance = self.conductance_mol_s_pa
        if conductance == 0.0:
            return math.inf
        coefficient = conductance * R_GAS_J_MOL_K * (
            a.temperature_k / a.volume_m3 + b.temperature_k / b.volume_m3
        )
        return math.inf if coefficient <= 0.0 else 0.9 / coefficient

    def advance(
        self,
        a: GasRegionState,
        b: GasRegionState,
        dt_s: float,
    ) -> GasTransferDiagnostics:
        if {a.id, b.id} != {self.region_a, self.region_b}:
            raise ValueError("gas-region ids do not match transfer pair")
        if a.id != self.region_a:
            a, b = b, a
        if dt_s <= 0.0:
            raise ValueError("dt_s must be positive")

        initial_total = math.fsum((a.amount_mol, b.amount_mol))
        initial_dp = a.pressure_pa - b.pressure_pa
        remaining = float(dt_s)
        transferred = 0.0
        substeps = 0

        while remaining > max(1.0e-15 * dt_s, 1.0e-18):
            if substeps >= self.max_substeps:
                raise RuntimeError("gas-transfer substep budget exhausted")
            rate = self._rate_a_to_b_mol_s(a, b)
            step = min(remaining, self.explicit_stability_limit_s(a, b))
            if rate > 0.0:
                step = min(step, self.positivity_safety * a.amount_mol / rate)
            elif rate < 0.0:
                step = min(step, self.positivity_safety * b.amount_mol / (-rate))
            if not math.isfinite(step):
                step = remaining
            if step <= 0.0:
                raise RuntimeError("non-positive gas-transfer timestep")

            delta = rate * step
            a.amount_mol -= delta
            b.amount_mol += delta
            transferred += delta
            tiny = 2.0e-15 * max(initial_total, 1.0e-300)
            if a.amount_mol < -tiny or b.amount_mol < -tiny:
                raise RuntimeError("gas transfer violated positivity")
            if a.amount_mol < 0.0:
                b.amount_mol += a.amount_mol
                a.amount_mol = 0.0
            if b.amount_mol < 0.0:
                a.amount_mol += b.amount_mol
                b.amount_mol = 0.0
            remaining -= step
            if remaining < max(1.0e-15 * dt_s, 1.0e-18):
                remaining = 0.0
            substeps += 1

        final_total = math.fsum((a.amount_mol, b.amount_mol))
        return GasTransferDiagnostics(
            requested_dt_s=dt_s,
            substeps=substeps,
            amount_transferred_a_to_b_mol=transferred,
            initial_total_mol=initial_total,
            final_total_mol=final_total,
            total_relative_drift=abs(final_total - initial_total)
            / max(abs(initial_total), 1.0e-300),
            initial_pressure_difference_pa=initial_dp,
            final_pressure_difference_pa=a.pressure_pa - b.pressure_pa,
        )
