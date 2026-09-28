"""Reduced-order dynamic Plateau-border foundation for a bounded four-region T1.

This module is intentionally not a claim of resolved singular multiphase CFD.  It
solves a local liquid-border control-volume model coupled to the already-qualified
curvilinear four-region T1 geometry.  The supported generalized coordinate is the
separation of the two resolved Plateau curves.  Surrounding-film traction is
measured from the resolved mesh as a boundary load, while liquid-border
Young-Laplace pressure, redistribution pressure and Stokes resistance evolve
from the control-volume state.  A connected liquid reservoir exchanges volume
through a Poiseuille throat; total liquid volume is conserved exactly by the
discrete update.

The T1 event is triggered only when the evolved separation reaches twice the
declared liquid-border core radius.  Topology surgery is then applied at that
physical event geometry without using the legacy frozen-traction event-time
forecast.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math

from bubblelab.solvers.equilibrium.network import FilmNetwork, FilmPatch, PlateauJunction
from bubblelab.solvers.transient.network.core import TransientNetworkState
from bubblelab.solvers.transient.network.t1 import T1Lineage, internal_adjacency_pairs
from bubblelab.solvers.transient.network.t1_hydrodynamics import (
    DirectT1Error,
    DirectT1Settings,
    _canonical_indices,
    _contracted_network,
    _curve_strip,
    _direct_gap_capillary_force,
    _event_switch_curves,
    _junction_map,
    _next_event_serial,
    _ordered_curves,
    _patch_map,
    _replace_patch_vertices,
    _volume_errors,
    detect_direct_t1_eligibility,
)

SUPPORTED_CLASS = "isolated-four-region-curvilinear-3d-dynamic-liquid-border-reduced-order"


@dataclass(frozen=True)
class PlateauBorderSettings:
    """Physical and numerical parameters for the bounded local border model."""

    surface_tension_n_m: float = 1.0
    liquid_viscosity_pa_s: float = 0.12
    core_radius_m: float = 0.010
    total_liquid_volume_m3: float = 2.4e-5
    initial_core_volume_fraction: float = 0.50
    reservoir_length_factor: float = 1.0
    redistribution_length_m: float = 0.050
    redistribution_radius_m: float = 0.004
    viscous_shape_factor: float = 12.0
    pressure_force_factor: float = 1.0
    time_step_s: float = 2.0e-4
    maximum_time_s: float = 3.0
    maximum_fractional_gap_step: float = 0.02
    minimum_driving_force_n: float = 1.0e-8
    volume_relative_tolerance: float = 1.0e-12
    post_event_seed_factor: float = 1.25

    def validate(self) -> None:
        if self.surface_tension_n_m <= 0.0:
            raise ValueError("surface tension must be positive")
        if self.liquid_viscosity_pa_s <= 0.0:
            raise ValueError("liquid viscosity must be positive")
        if self.core_radius_m <= 0.0:
            raise ValueError("liquid-border core radius must be positive")
        if self.total_liquid_volume_m3 <= 0.0:
            raise ValueError("total liquid volume must be positive")
        if not 0.0 < self.initial_core_volume_fraction < 1.0:
            raise ValueError("initial core volume fraction must lie in (0, 1)")
        if self.reservoir_length_factor <= 0.0:
            raise ValueError("reservoir length factor must be positive")
        if self.redistribution_length_m <= 0.0 or self.redistribution_radius_m <= 0.0:
            raise ValueError("redistribution throat dimensions must be positive")
        if self.viscous_shape_factor <= 0.0 or self.pressure_force_factor < 0.0:
            raise ValueError("force coefficients are invalid")
        if self.time_step_s <= 0.0 or self.maximum_time_s <= 0.0:
            raise ValueError("time scales must be positive")
        if not 0.0 < self.maximum_fractional_gap_step < 0.25:
            raise ValueError("maximum fractional gap step must lie in (0, 0.25)")
        if self.minimum_driving_force_n <= 0.0:
            raise ValueError("minimum driving force must be positive")
        if self.volume_relative_tolerance <= 0.0:
            raise ValueError("volume tolerance must be positive")
        if self.post_event_seed_factor <= 0.0:
            raise ValueError("post-event seed factor must be positive")


@dataclass(frozen=True)
class PlateauBorderState:
    time_s: float
    gap_m: float
    core_liquid_volume_m3: float
    reservoir_liquid_volume_m3: float

    @property
    def total_liquid_volume_m3(self) -> float:
        return self.core_liquid_volume_m3 + self.reservoir_liquid_volume_m3


@dataclass(frozen=True)
class PlateauBorderForces:
    sheet_traction_n: float
    border_capillary_force_n: float
    capillary_force_n: float
    pressure_force_n: float
    viscous_force_n: float
    net_driving_force_n: float
    gap_rate_m_s: float
    core_pressure_pa: float
    reservoir_pressure_pa: float
    core_radius_m: float
    reservoir_radius_m: float
    redistribution_flow_m3_s: float
    force_balance_residual_n: float


@dataclass(frozen=True)
class PlateauBorderSample:
    state: PlateauBorderState
    forces: PlateauBorderForces


@dataclass(frozen=True)
class PlateauBorderEvolution:
    samples: tuple[PlateauBorderSample, ...]
    event_time_s: float
    initial_gap_m: float
    event_gap_m: float
    initial_liquid_volume_m3: float
    final_liquid_volume_m3: float
    maximum_liquid_relative_error: float

    @property
    def final(self) -> PlateauBorderSample:
        return self.samples[-1]


@dataclass(frozen=True)
class PlateauBorderT1Result:
    before: TransientNetworkState
    after: TransientNetworkState
    evolution: PlateauBorderEvolution
    lineage: T1Lineage
    adjacency_before: tuple[tuple[str, str], ...]
    adjacency_after: tuple[tuple[str, str], ...]
    volume_errors_before: tuple[tuple[str, float], ...]
    volume_errors_after: tuple[tuple[str, float], ...]
    energy_before_j: float
    energy_after_j: float
    supported_class: str = SUPPORTED_CLASS


def _polyline_length(points: tuple[tuple[float, float, float], ...]) -> float:
    return sum(
        math.dist(left, right)
        for left, right in zip(points, points[1:])
    )


class PlateauBorderModel:
    """Evolve one qualified local liquid-border state to core contact."""

    def __init__(
        self,
        state: TransientNetworkState,
        settings: PlateauBorderSettings | None = None,
    ) -> None:
        self.settings = settings or PlateauBorderSettings()
        self.settings.validate()
        self.before = state
        self.network = state.to_network()
        direct = DirectT1Settings(
            plateau_border_core_radius_m=self.settings.core_radius_m,
            post_event_seed_factor=self.settings.post_event_seed_factor,
            volume_relative_tolerance=self.settings.volume_relative_tolerance,
        )
        eligibility = detect_direct_t1_eligibility(self.network, direct)
        if not eligibility.eligible or eligibility.neighborhood is None:
            raise DirectT1Error(
                f"network is outside the dynamic Plateau-border class: {eligibility.reason}"
            )
        self.eligibility = eligibility
        self.neighborhood = eligibility.neighborhood
        first, second, _, _, _ = _ordered_curves(self.network, self.neighborhood)
        line_length = 0.5 * (_polyline_length(first) + _polyline_length(second))
        if line_length <= 0.0:
            raise DirectT1Error("resolved Plateau curves have zero arclength")
        self.line_length_m = line_length
        self.initial_gap_m = eligibility.initial_gap_m
        self.event_gap_m = 2.0 * self.settings.core_radius_m
        if self.event_gap_m >= self.initial_gap_m:
            raise DirectT1Error("liquid-border core contact must lie below the initial gap")
        # Surrounding-film traction is a boundary load measured from the actual
        # resolved mesh.  It is not used as a frozen event-time predictor: the
        # liquid-border capillary pressure, pressure resistance and viscous
        # mobility below evolve from the control-volume state.
        self.sheet_traction_n = _direct_gap_capillary_force(
            self.network, self.neighborhood
        )
        if self.sheet_traction_n <= self.settings.minimum_driving_force_n:
            raise DirectT1Error(
                "resolved surrounding-film traction does not drive the supported collapse"
            )

    def initial_state(self) -> PlateauBorderState:
        core = (
            self.settings.total_liquid_volume_m3
            * self.settings.initial_core_volume_fraction
        )
        return PlateauBorderState(
            time_s=self.before.time_s,
            gap_m=self.initial_gap_m,
            core_liquid_volume_m3=core,
            reservoir_liquid_volume_m3=self.settings.total_liquid_volume_m3 - core,
        )

    def network_at_gap(self, gap_m: float) -> FilmNetwork:
        scale = gap_m / self.initial_gap_m
        if not 0.0 < scale <= 1.0:
            raise DirectT1Error("dynamic border gap left the supported contraction interval")
        return _contracted_network(
            self.network,
            self.neighborhood,
            scale,
            self.eligibility.second_curve_reversed,
        )

    def forces(self, state: PlateauBorderState) -> PlateauBorderForces:
        cfg = self.settings
        if state.gap_m <= 0.0:
            raise DirectT1Error("dynamic border gap must remain positive")
        # The core control-volume length follows the evolved gap coordinate.
        # Exact discrete liquid conservation then turns gap change into evolving
        # cross-section, curvature and liquid pressure.
        core_length = self.line_length_m * state.gap_m / self.initial_gap_m
        reservoir_length = self.line_length_m * cfg.reservoir_length_factor
        core_area = state.core_liquid_volume_m3 / core_length
        reservoir_area = state.reservoir_liquid_volume_m3 / reservoir_length
        if core_area <= 0.0 or reservoir_area <= 0.0:
            raise DirectT1Error("liquid control-volume area became non-positive")
        core_radius = math.sqrt(core_area / math.pi)
        reservoir_radius = math.sqrt(reservoir_area / math.pi)

        # Young-Laplace pressure relative to the common gas pressure.  Only the
        # pressure difference enters the model, so the absolute gas pressure
        # cancels.
        core_pressure = -cfg.surface_tension_n_m / core_radius
        reservoir_pressure = -cfg.surface_tension_n_m / reservoir_radius
        delta_pressure = core_pressure - reservoir_pressure

        # The liquid-border meniscus contributes a state-dependent capillary
        # generalized force through its Young-Laplace pressure and swept area.
        swept_area = state.core_liquid_volume_m3 / state.gap_m
        border_capillary_force = (
            cfg.surface_tension_n_m / core_radius
        ) * swept_area
        capillary = self.sheet_traction_n + border_capillary_force

        # Redistribution raises core pressure during compression and therefore
        # resists additional collapse.  This pressure term is separate from the
        # capillary driving term above.
        pressure_force = (
            cfg.pressure_force_factor
            * max(delta_pressure, 0.0)
            * swept_area
        )

        # The border translation uses a Stokes resistance.  The area/r^2 ratio
        # is pi for the circular equivalent section, so mu*L gives the required
        # N*s/m scaling; the radius correction retains sensitivity as the border
        # redistributes liquid.
        reference_radius = math.sqrt(
            (cfg.total_liquid_volume_m3 * cfg.initial_core_volume_fraction)
            / (self.line_length_m * math.pi)
        )
        drag_ns_m = (
            cfg.viscous_shape_factor
            * cfg.liquid_viscosity_pa_s
            * self.line_length_m
            * max(0.25, (reference_radius / core_radius) ** 2)
        )
        net = capillary - pressure_force
        if net <= cfg.minimum_driving_force_n:
            raise DirectT1Error(
                f"pressure resistance stalls the supported collapse: {net:.6e} N"
            )
        gap_rate = -net / drag_ns_m
        viscous_force = -drag_ns_m * gap_rate
        residual = capillary - pressure_force - viscous_force

        # Poiseuille redistribution from higher-pressure core toward reservoir.
        throat_resistance = (
            8.0
            * cfg.liquid_viscosity_pa_s
            * cfg.redistribution_length_m
            / (math.pi * cfg.redistribution_radius_m ** 4)
        )
        flow = delta_pressure / throat_resistance
        return PlateauBorderForces(
            sheet_traction_n=self.sheet_traction_n,
            border_capillary_force_n=border_capillary_force,
            capillary_force_n=capillary,
            pressure_force_n=pressure_force,
            viscous_force_n=viscous_force,
            net_driving_force_n=net,
            gap_rate_m_s=gap_rate,
            core_pressure_pa=core_pressure,
            reservoir_pressure_pa=reservoir_pressure,
            core_radius_m=core_radius,
            reservoir_radius_m=reservoir_radius,
            redistribution_flow_m3_s=flow,
            force_balance_residual_n=residual,
        )

    def _advance_with_derivative(
        self,
        state: PlateauBorderState,
        forces: PlateauBorderForces,
        dt_s: float,
    ) -> PlateauBorderState:
        total = state.total_liquid_volume_m3
        core = state.core_liquid_volume_m3 - forces.redistribution_flow_m3_s * dt_s
        # A finite control volume cannot transfer more liquid than it contains.
        floor = 1.0e-12 * total
        core = min(max(core, floor), total - floor)
        return PlateauBorderState(
            time_s=state.time_s + dt_s,
            gap_m=state.gap_m + forces.gap_rate_m_s * dt_s,
            core_liquid_volume_m3=core,
            reservoir_liquid_volume_m3=total - core,
        )

    def step(self, state: PlateauBorderState, dt_s: float | None = None) -> PlateauBorderState:
        """Second-order midpoint update with exact total-liquid conservation."""
        requested = dt_s if dt_s is not None else self.settings.time_step_s
        if requested <= 0.0:
            raise ValueError("time step must be positive")
        first = self.forces(state)
        adaptive = (
            self.settings.maximum_fractional_gap_step
            * state.gap_m
            / max(abs(first.gap_rate_m_s), 1.0e-30)
        )
        dt = min(requested, adaptive)
        midpoint = self._advance_with_derivative(state, first, 0.5 * dt)
        mid_forces = self.forces(midpoint)
        return self._advance_with_derivative(state, mid_forces, dt)

    def evolve_to_event(self) -> PlateauBorderEvolution:
        cfg = self.settings
        initial = self.initial_state()
        total0 = initial.total_liquid_volume_m3
        state = initial
        samples = [PlateauBorderSample(state, self.forces(state))]
        max_error = 0.0
        while state.gap_m > self.event_gap_m:
            if state.time_s - initial.time_s >= cfg.maximum_time_s:
                raise DirectT1Error("dynamic Plateau-border evolution exceeded maximum time")
            next_state = self.step(state)
            if next_state.gap_m >= state.gap_m:
                raise DirectT1Error("dynamic Plateau-border gap failed to contract")
            if next_state.gap_m <= self.event_gap_m:
                fraction = (
                    (state.gap_m - self.event_gap_m)
                    / (state.gap_m - next_state.gap_m)
                )
                core = state.core_liquid_volume_m3 + fraction * (
                    next_state.core_liquid_volume_m3 - state.core_liquid_volume_m3
                )
                state = PlateauBorderState(
                    time_s=state.time_s + fraction * (next_state.time_s - state.time_s),
                    gap_m=self.event_gap_m,
                    core_liquid_volume_m3=core,
                    reservoir_liquid_volume_m3=total0 - core,
                )
            else:
                state = next_state
            rel = abs(state.total_liquid_volume_m3 - total0) / total0
            max_error = max(max_error, rel)
            if rel > cfg.volume_relative_tolerance:
                raise DirectT1Error(
                    f"liquid-volume conservation failed: {rel:.6e}"
                )
            samples.append(PlateauBorderSample(state, self.forces(state)))

        return PlateauBorderEvolution(
            samples=tuple(samples),
            event_time_s=state.time_s - initial.time_s,
            initial_gap_m=self.initial_gap_m,
            event_gap_m=self.event_gap_m,
            initial_liquid_volume_m3=total0,
            final_liquid_volume_m3=state.total_liquid_volume_m3,
            maximum_liquid_relative_error=max_error,
        )


def _perform_event_geometry_switch(
    state: TransientNetworkState,
    model: PlateauBorderModel,
    evolution: PlateauBorderEvolution,
) -> PlateauBorderT1Result:
    """Apply direct 3D topology surgery at the border-evolved contact geometry."""
    cfg = model.settings
    n = model.neighborhood
    before_network = state.to_network()
    event_network = model.network_at_gap(evolution.event_gap_m)
    by_id = _patch_map(event_network)
    junctions = _junction_map(event_network)
    first_j = junctions[n.old_junction_ids[0]]
    second_j = junctions[n.old_junction_ids[1]]
    seed_length = cfg.post_event_seed_factor * evolution.event_gap_m
    side0_curve, side1_curve, side_ids = _event_switch_curves(
        event_network,
        n,
        model.eligibility.second_curve_reversed,
        seed_length,
    )
    region_outer = dict(n.region_outer_films)
    updates_by_film: dict[str, dict[int, tuple[float, float, float]]] = {}
    junction_indices_by_side: dict[str, list[tuple[str, tuple[int, ...]]]] = {
        side_ids[0]: [],
        side_ids[1]: [],
    }
    for side_index, side_id in enumerate(side_ids):
        target_curve = side0_curve if side_index == 0 else side1_curve
        for film_id in region_outer[side_id]:
            old_junction = first_j if film_id in first_j.incident_film_ids else second_j
            reverse = (
                model.eligibility.second_curve_reversed
                if old_junction.id == second_j.id
                else False
            )
            ordered = _canonical_indices(old_junction, film_id, reverse)
            if any(index in set(by_id[film_id].fixed_vertex_indices) for index in ordered):
                raise DirectT1Error("a collapsing Plateau curve contains a fixed outer-film vertex")
            updates_by_film.setdefault(film_id, {}).update(dict(zip(ordered, target_curve)))
            junction_indices_by_side[side_id].append((film_id, ordered))

    central_old = by_id[n.collapsing_film_id]
    serial = _next_event_serial(before_network)
    event_id = f"t1h:{serial:06d}"
    new_film_id = f"film:{n.opposite_regions[0]}{n.opposite_regions[1]}:{event_id}"
    if new_film_id in by_id:
        raise DirectT1Error("deterministic border-driven T1 film ID collides with existing topology")
    new_central = _curve_strip(
        new_film_id,
        n.opposite_regions,
        side0_curve,
        side1_curve,
        central_old.sheet_tension_n_m,
        central_old.contributes_to_volume,
    )
    patches: list[FilmPatch] = []
    for patch in event_network.patches:
        if patch.id == n.collapsing_film_id:
            continue
        patches.append(_replace_patch_vertices(patch, updates_by_film.get(patch.id, {})))
    patches.append(new_central)
    patches.sort(key=lambda patch: patch.id)

    new_junctions: list[PlateauJunction] = []
    new_junction_ids: list[str] = []
    count = len(side0_curve)
    for side_index, side_id in enumerate(side_ids):
        entries = sorted(junction_indices_by_side[side_id], key=lambda item: item[0])
        if len(entries) != 2:
            raise DirectT1Error("each post-T1 side must own exactly two outer films")
        central_indices = tuple(
            (0 if side_index == 0 else count) + sample for sample in range(count)
        )
        junction_id = f"junction:{side_id}:{event_id}"
        new_junction_ids.append(junction_id)
        new_junctions.append(
            PlateauJunction(
                id=junction_id,
                incident_film_ids=(new_film_id, entries[0][0], entries[1][0]),
                vertex_indices_by_film=(central_indices, entries[0][1], entries[1][1]),
            )
        )

    retained_junctions = [
        junction
        for junction in event_network.junctions
        if junction.id not in set(n.old_junction_ids)
    ]
    after_network = FilmNetwork(
        event_network.regions,
        tuple(patches),
        tuple(sorted((*retained_junctions, *new_junctions), key=lambda item: item.id)),
    )
    after_network.validate()

    after_errors = _volume_errors(after_network)
    max_error = max((value for _, value in after_errors), default=0.0)
    if max_error > cfg.volume_relative_tolerance:
        raise DirectT1Error(
            f"border-driven T1 gas-volume conservation failed: {max_error:.6e}"
        )
    if tuple(region.id for region in before_network.regions) != tuple(
        region.id for region in after_network.regions
    ):
        raise DirectT1Error("border-driven T1 changed stable gas-region identities")

    old_pair = tuple(sorted(n.old_adjacent_regions))
    new_pair = tuple(sorted(n.opposite_regions))
    before_pairs = set(internal_adjacency_pairs(before_network))
    after_pairs = set(internal_adjacency_pairs(after_network))
    if (
        old_pair not in before_pairs
        or old_pair in after_pairs
        or new_pair in before_pairs
        or new_pair not in after_pairs
    ):
        raise DirectT1Error("border-driven T1 did not perform the required adjacency switch")

    after_raw = TransientNetworkState.from_network(after_network)
    after_state = replace(
        after_raw,
        time_s=state.time_s + evolution.event_time_s,
        step_index=state.step_index,
    )
    lineage = T1Lineage(
        event_id=event_id,
        retired_film_ids=(n.collapsing_film_id,),
        created_film_ids=(new_film_id,),
        retired_junction_ids=n.old_junction_ids,
        created_junction_ids=tuple(new_junction_ids),
        preserved_region_ids=tuple(region.id for region in before_network.regions),
        preserved_film_ids=tuple(
            sorted(
                patch.id
                for patch in before_network.patches
                if patch.id != n.collapsing_film_id
            )
        ),
    )
    return PlateauBorderT1Result(
        before=state,
        after=after_state,
        evolution=evolution,
        lineage=lineage,
        adjacency_before=internal_adjacency_pairs(before_network),
        adjacency_after=internal_adjacency_pairs(after_network),
        volume_errors_before=_volume_errors(before_network),
        volume_errors_after=after_errors,
        energy_before_j=before_network.surface_energy_j(),
        energy_after_j=after_network.surface_energy_j(),
    )


def evolve_and_switch(
    state: TransientNetworkState,
    settings: PlateauBorderSettings | None = None,
) -> PlateauBorderT1Result:
    """Evolve the liquid-border model and execute the physical core-contact T1."""
    model = PlateauBorderModel(state, settings)
    evolution = model.evolve_to_event()
    return _perform_event_geometry_switch(state, model, evolution)
