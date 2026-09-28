"""Rupture and two-bubble coalescence topology surgery."""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any

from .criteria import RuptureConfig, RuptureDecision, RuptureHooks, RuptureObservation, RuptureTracker
from .model import (
    EXTERIOR,
    BubbleState,
    EventState,
    RestartGeometry,
    SharedFilmState,
    TopologyEvent,
    merge_centroid_and_velocity,
    merged_temperature_k,
    stable_id,
)


@dataclass(frozen=True)
class TopologyTransition:
    state: EventState
    emitted_events: tuple[TopologyEvent, ...]


def _relative_error(reference: float, value: float) -> float:
    return abs(value - reference) / max(abs(reference), 1.0e-300)


def _vector_norm(value: tuple[float, float, float]) -> float:
    return math.sqrt(math.fsum(component * component for component in value))


def _momentum(bubble: BubbleState) -> tuple[float, float, float] | None:
    mass = bubble.inferred_mass_kg
    if mass is None:
        return None
    return tuple(mass * component for component in bubble.velocity_m_s)  # type: ignore[return-value]


class TopologyEventEngine:
    """Deterministic explicit event engine layered above accepted solver state."""

    def __init__(
        self,
        config: RuptureConfig,
        *,
        seed: int = 0,
        hooks: RuptureHooks | None = None,
        restart_geometry_relative_budget: float = 1.0e-12,
    ) -> None:
        if seed < 0:
            raise ValueError("seed must be non-negative")
        if restart_geometry_relative_budget <= 0.0:
            raise ValueError("restart geometry budget must be positive")
        self.config = config
        self.seed = seed
        self.hooks = hooks or RuptureHooks()
        self.restart_geometry_relative_budget = restart_geometry_relative_budget
        self._trackers: dict[str, RuptureTracker] = {}

    def _tracker(self, film_id: str) -> RuptureTracker:
        if film_id not in self._trackers:
            self._trackers[film_id] = RuptureTracker(
                self.config,
                hooks=self.hooks,
                seed=self.seed,
                film_id=film_id,
            )
        return self._trackers[film_id]

    def observe_film(
        self,
        state: EventState,
        film_id: str,
        observation: RuptureObservation,
    ) -> TopologyTransition:
        if film_id not in state.active_films:
            raise KeyError(film_id)
        film = state.active_films[film_id]
        mean_thickness = min(film.mean_thickness_m, max(observation.min_thickness_m, 0.0))
        state = state.with_film(replace(
            film,
            min_thickness_m=observation.min_thickness_m,
            mean_thickness_m=mean_thickness,
        ))
        decision = self._tracker(film_id).observe(observation)
        if decision is None:
            return TopologyTransition(state=state, emitted_events=())
        source = "USER" if decision.criterion == "USER_TRIGGER" else "SOLVER"
        return self._apply_rupture(state, film_id, decision, source=source)

    def trigger_user_rupture(
        self,
        state: EventState,
        film_id: str,
        *,
        time_s: float,
        detail: str = "deterministic user-triggered rupture",
    ) -> TopologyTransition:
        if not self.config.allow_user_trigger:
            raise ValueError("user-triggered rupture is disabled")
        film = state.active_films.get(film_id)
        if film is None:
            raise KeyError(film_id)
        decision = RuptureDecision(
            rupture_time_s=time_s,
            criterion="USER_TRIGGER",
            threshold_m=None,
            detail=detail,
            bracket_start_s=time_s,
            bracket_end_s=time_s,
            interpolation_fraction=None,
            thickness_start_m=film.min_thickness_m,
            thickness_end_m=film.min_thickness_m,
        )
        tracker = self._tracker(film_id)
        tracker.fired = True
        return self._apply_rupture(state, film_id, decision, source="USER")

    def _rupture_event(
        self,
        state: EventState,
        film: SharedFilmState,
        decision: RuptureDecision,
        *,
        source: str,
    ) -> TopologyEvent:
        bubble_ids = tuple(sorted(region for region in film.adjacent if region != EXTERIOR))
        state_ref = state.digest()
        event_id = stable_id(
            "event",
            "RUPTURE",
            film.id,
            bubble_ids,
            float(decision.rupture_time_s).hex(),
            decision.criterion,
        )
        return TopologyEvent(
            id=event_id,
            type="RUPTURE",
            time_s=decision.rupture_time_s,
            bubble_ids_before=bubble_ids,
            bubble_ids_after=bubble_ids if len(bubble_ids) == 2 else (),
            film_ids=(film.id,),
            provenance={
                "source": source,
                "detail": decision.detail,
                "criterion": decision.criterion,
                "threshold_m": decision.threshold_m,
                "event_time_localization": {
                    "method": "PIECEWISE_LINEAR_ACCEPTED_STATE_BRACKET",
                    "bracket_start_s": decision.bracket_start_s,
                    "bracket_end_s": decision.bracket_end_s,
                    "interpolation_fraction": decision.interpolation_fraction,
                    "thickness_start_m": decision.thickness_start_m,
                    "thickness_end_m": decision.thickness_end_m,
                },
                "seed": state.seed,
            },
            pre_event_state_ref=state_ref,
            criterion=decision.criterion,
            threshold_m=decision.threshold_m,
        )

    def _apply_rupture(
        self,
        state: EventState,
        film_id: str,
        decision: RuptureDecision,
        *,
        source: str,
    ) -> TopologyTransition:
        if film_id not in state.active_films:
            raise KeyError(film_id)
        film = state.active_films[film_id]
        rupture_event = self._rupture_event(state, film, decision, source=source)

        active_films = dict(state.active_films)
        active_films.pop(film_id)
        retired_films = dict(state.retired_films)
        retired_films[film_id] = replace(film, status="RUPTURED", rupture_time_s=decision.rupture_time_s)
        after_rupture = replace(
            state,
            active_films=active_films,
            retired_films=retired_films,
            events=state.events + (rupture_event,),
        )

        gas_regions = tuple(sorted(region for region in film.adjacent if region != EXTERIOR))
        if len(gas_regions) == 2:
            after_coalescence, coalescence_event = self._coalesce(
                after_rupture,
                parent_ids=(gas_regions[0], gas_regions[1]),
                failed_film=film,
                event_time_s=decision.rupture_time_s,
            )
            return TopologyTransition(
                state=after_coalescence,
                emitted_events=(rupture_event, coalescence_event),
            )

        bubbles = dict(after_rupture.bubbles)
        if len(gas_regions) == 1 and gas_regions[0] in bubbles:
            bubbles[gas_regions[0]] = replace(bubbles[gas_regions[0]], status="RUPTURED")
            after_rupture = replace(after_rupture, bubbles=bubbles)
        return TopologyTransition(state=after_rupture, emitted_events=(rupture_event,))

    def _coalesce(
        self,
        state: EventState,
        *,
        parent_ids: tuple[str, str],
        failed_film: SharedFilmState,
        event_time_s: float,
    ) -> tuple[EventState, TopologyEvent]:
        a = state.bubbles.get(parent_ids[0])
        b = state.bubbles.get(parent_ids[1])
        if a is None or b is None:
            raise KeyError("coalescence references a missing parent bubble")
        if a.status != "ALIVE" or b.status != "ALIVE":
            raise ValueError("coalescence parents must both be ALIVE")

        child_id = stable_id("bubble", "COALESCENCE", tuple(sorted(parent_ids)), failed_film.id)
        target_volume = math.fsum((a.volume_m3, b.volume_m3))
        amount = None
        if a.gas_amount_mol is not None and b.gas_amount_mol is not None:
            amount = math.fsum((a.gas_amount_mol, b.gas_amount_mol))
        centroid, velocity, merged_mass, center_method = merge_centroid_and_velocity(a, b)
        temperature = merged_temperature_k(a, b)
        species = a.gas_species if a.gas_species == b.gas_species else "mixture"
        molar_mass = a.molar_mass_kg_mol if a.molar_mass_kg_mol == b.molar_mass_kg_mol else None
        geometry = RestartGeometry.volume_matched_octahedron(target_volume, centroid)
        geometry_error = geometry.volume_relative_error()
        if geometry_error > self.restart_geometry_relative_budget * (1.0 + 1.0e-12):
            raise RuntimeError("post-event restart geometry exceeded its volume budget")

        child = BubbleState(
            id=child_id,
            volume_m3=target_volume,
            gas_amount_mol=amount,
            centroid_m=centroid,
            velocity_m_s=velocity,
            temperature_k=temperature,
            mass_kg=merged_mass,
            gas_species=species,
            molar_mass_kg_mol=molar_mass,
            status="ALIVE",
            lineage=tuple(sorted(parent_ids)),
            restart_geometry=geometry,
        )

        amount_before = None
        amount_error = None
        if amount is not None:
            amount_before = math.fsum((a.gas_amount_mol or 0.0, b.gas_amount_mol or 0.0))
            amount_error = _relative_error(amount_before, child.gas_amount_mol or 0.0)

        momentum_a = _momentum(a)
        momentum_b = _momentum(b)
        momentum_child = _momentum(child)
        momentum_error = None
        momentum_before = None
        momentum_after = None
        if momentum_a is not None and momentum_b is not None and momentum_child is not None:
            momentum_before = tuple(math.fsum((momentum_a[axis], momentum_b[axis])) for axis in range(3))
            momentum_after = momentum_child
            delta = tuple(momentum_after[axis] - momentum_before[axis] for axis in range(3))
            momentum_error = _vector_norm(delta) / max(_vector_norm(momentum_before), 1.0e-300)

        failed_film_energy_j = failed_film.area_m2 * failed_film.surface_tension_n_m
        conservation: dict[str, Any] = {
            "gas_amount_mol_before": amount_before,
            "gas_amount_mol_after": child.gas_amount_mol,
            "gas_amount_relative_error": amount_error,
            "target_volume_m3_before": target_volume,
            "target_volume_m3_after": child.volume_m3,
            "target_volume_relative_error": _relative_error(target_volume, child.volume_m3),
            "center_method": center_method,
            "center_m_after": list(child.centroid_m),
            "momentum_kg_m_s_before": None if momentum_before is None else list(momentum_before),
            "momentum_kg_m_s_after": None if momentum_after is None else list(momentum_after),
            "momentum_relative_error": momentum_error,
            "restart_geometry_kind": geometry.kind,
            "restart_geometry_volume_relative_error": geometry_error,
            "restart_geometry_volume_budget": self.restart_geometry_relative_budget,
            "requires_post_event_relaxation": geometry.requires_relaxation,
            "removed_shared_film_surface_energy_j": failed_film_energy_j,
            "bookkeeping_surface_energy_change_j": -failed_film_energy_j,
            "full_surface_energy_change_j": None,
            "surface_energy_accounting": (
                "failed shared-film sheet is accounted exactly; full outer-surface energy "
                "change is deferred because parent outer geometry is not owned by this layer"
            ),
        }

        pre_ref = state.digest()
        bubbles = dict(state.bubbles)
        bubbles[a.id] = replace(a, status="MERGED")
        bubbles[b.id] = replace(b, status="MERGED")
        if child.id in bubbles:
            raise ValueError("deterministic child id collides with an existing bubble")
        bubbles[child.id] = child

        active_films: dict[str, SharedFilmState] = {}
        retired_films = dict(state.retired_films)
        remapped_film_ids: list[str] = []
        degenerate_film_ids: list[str] = []
        parent_set = set(parent_ids)
        for film_id, film in sorted(state.active_films.items()):
            adjacent = tuple(child.id if region in parent_set else region for region in film.adjacent)
            if adjacent[0] == adjacent[1]:
                retired_films[film_id] = replace(film, status="REMOVED")
                degenerate_film_ids.append(film_id)
                continue
            if adjacent != film.adjacent:
                film = replace(film, adjacent=(adjacent[0], adjacent[1]))
                remapped_film_ids.append(film_id)
            active_films[film_id] = film
        conservation["remapped_film_ids"] = remapped_film_ids
        conservation["retired_degenerate_film_ids"] = degenerate_film_ids

        event_id = stable_id(
            "event",
            "COALESCENCE",
            failed_film.id,
            tuple(sorted(parent_ids)),
            child.id,
            float(event_time_s).hex(),
        )
        event = TopologyEvent(
            id=event_id,
            type="COALESCENCE",
            time_s=event_time_s,
            bubble_ids_before=tuple(sorted(parent_ids)),
            bubble_ids_after=(child.id,),
            film_ids=(failed_film.id,),
            provenance={
                "source": "SOLVER",
                "detail": "two gas regions merged immediately after explicit shared-film rupture",
                "trigger_event_type": "RUPTURE",
                "failed_film_id": failed_film.id,
                "post_event_geometry": geometry.kind,
                "post_event_relaxation": "REQUIRED",
                "seed": state.seed,
            },
            pre_event_state_ref=pre_ref,
            criterion="SHARED_FILM_RUPTURE",
            lineage={child.id: tuple(sorted(parent_ids))},
            conservation=conservation,
        )
        result = replace(
            state,
            bubbles=bubbles,
            active_films=active_films,
            retired_films=retired_films,
            events=state.events + (event,),
        )
        return result, event
