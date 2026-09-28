"""Thin-film event runtime with accepted post-coalescence transient continuation."""
from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any, Mapping

from bubblelab.solvers.events.criteria import RuptureConfig, RuptureObservation
from bubblelab.solvers.events.engine import TopologyEventEngine, TopologyTransition
from bubblelab.solvers.thinfilm import SurfaceTransportState

from .event_runtime import (
    BACKEND_IDENTITY,
    BACKEND_VERSION,
    _event_frames,
    _event_state,
    _gas_states,
    _normalize,
    _pair,
    _validate,
)
from .post_event_relaxation import POST_EVENT_PHASE, build_post_event_relaxation_frames
from .runner import UnsupportedScenarioFeature, _canonical_bytes, _decorate, scenario_hash
from .thinfilm_runtime import (
    _field_values,
    _gas_frame,
    _shared_surface,
    feature_flags,
    output_cadence_s,
    surface_parameters,
)


def run_postcoalescence_frames(
    scenario: Mapping[str, Any], frames: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if frames < 3:
        raise ValueError("post_event_relaxation requires --frames >= 3")
    film_config, config = _validate(scenario)
    cadence = output_cadence_s(scenario)
    assert cadence is not None
    surface, film = _shared_surface(scenario)
    film_state = SurfaceTransportState(
        surface,
        _field_values(
            film_config.get("initial_thickness_m", 8.0e-6),
            len(surface.faces),
            "initial_thickness_m",
        ),
        _field_values(
            film_config.get("initial_surfactant_mol_m2", 0.0),
            len(surface.faces),
            "initial_surfactant_mol_m2",
        ),
        parameters=surface_parameters(scenario, film_config),
    )
    gases = _gas_states(scenario)
    by_id = {gas.id: gas for gas in gases}
    initial_total = math.fsum(gas.amount_mol for gas in gases)
    engine = TopologyEventEngine(
        RuptureConfig(
            thickness_threshold_m=config.thickness_threshold_m,
            dwell_time_s=config.dwell_time_s,
            allow_user_trigger=config.allow_user_trigger,
        ),
        seed=config.deterministic_seed,
    )
    physical: list[dict[str, Any]] = []
    current_time = 0.0
    cumulative = 0.0
    trigger = config.user_trigger_time_s
    epsilon = 16.0 * math.ulp(max(cadence, 1.0))

    def pre_frame(
        index: int, dt: float, gas_step: Any | None, surface_step: Any | None
    ) -> dict[str, Any]:
        pair_now = _pair(surface, film, film_state, film_config)
        raw = _gas_frame(
            scenario,
            surface,
            film,
            film_state,
            gases,
            frame_index=index,
            time_s=current_time,
            cadence_s=dt,
            initial_total_mol=initial_total,
            cumulative_transfer_a_to_b_mol=cumulative,
            last_gas_step=gas_step,
            pair=pair_now,
        )
        return _normalize(
            raw,
            scenario,
            film_config,
            config,
            frame_id=f"thinfilm-events-{len(physical):06d}-pre",
            phase="PRE_EVENT",
            surface_step=surface_step,
        )

    def continue_transition(
        transition: TopologyTransition,
        *,
        observation_time_s: float,
        event_cadence_s: float,
        surface_step: Any | None,
        gas_step: Any | None,
    ) -> None:
        event_frame = _event_frames(
            transition,
            scenario,
            film_config,
            config,
            film_state,
            gases,
            observation_time_s=observation_time_s,
            cadence_s=event_cadence_s,
            cumulative_transfer=cumulative,
            surface_step=surface_step,
            gas_step=gas_step,
            serial=len(physical),
        )[0]
        physical.append(event_frame)
        remaining = frames - len(physical)
        physical.extend(
            build_post_event_relaxation_frames(
                transition,
                event_frame,
                scenario,
                cadence_s=cadence,
                count=remaining,
                serial=len(physical),
                deterministic_seed=config.deterministic_seed,
            )
        )

    physical.append(pre_frame(0, cadence, None, None))
    state = _event_state(scenario, film, film_state, gases, config)
    transition: TopologyTransition | None = None
    if trigger is not None and abs(trigger) <= epsilon:
        transition = engine.trigger_user_rupture(
            state,
            str(film["id"]),
            time_s=0.0,
            detail="deterministic runtime user burst",
        )
    elif config.enable_rupture:
        transition = engine.observe_film(
            state,
            str(film["id"]),
            RuptureObservation(time_s=0.0, min_thickness_m=min(film_state.thickness_m)),
        )

    if transition is not None and transition.emitted_events:
        continue_transition(
            transition,
            observation_time_s=0.0,
            event_cadence_s=cadence,
            surface_step=None,
            gas_step=None,
        )
    else:
        for index in range(1, frames):
            dt = cadence
            if (
                trigger is not None
                and current_time + epsilon < trigger < current_time + cadence - epsilon
            ):
                dt = trigger - current_time
            surface_step = film_state.advance(dt)
            pair = _pair(surface, film, film_state, film_config)
            gas_step = pair.advance(by_id[pair.region_a], by_id[pair.region_b], dt)
            cumulative += gas_step.amount_transferred_a_to_b_mol
            current_time += dt
            state = _event_state(scenario, film, film_state, gases, config)
            transition = None
            if trigger is not None and abs(current_time - trigger) <= epsilon:
                transition = engine.trigger_user_rupture(
                    state,
                    str(film["id"]),
                    time_s=trigger,
                    detail="deterministic runtime user burst",
                )
            elif config.enable_rupture:
                transition = engine.observe_film(
                    state,
                    str(film["id"]),
                    RuptureObservation(
                        time_s=current_time,
                        min_thickness_m=min(film_state.thickness_m),
                    ),
                )
            if transition is not None and transition.emitted_events:
                continue_transition(
                    transition,
                    observation_time_s=current_time,
                    event_cadence_s=dt,
                    surface_step=surface_step,
                    gas_step=gas_step,
                )
                break
            physical.append(pre_frame(index, dt, gas_step, surface_step))

    if not any(
        frame.get("event_runtime", {}).get("phase") == POST_EVENT_PHASE
        for frame in physical
    ):
        raise UnsupportedScenarioFeature(
            "post_event_relaxation was requested but no coalescence occurred within the frame horizon"
        )
    flags = feature_flags(film_config)
    return physical, {
        "identity": BACKEND_IDENTITY,
        "version": BACKEND_VERSION,
        "mode": "accepted thin-film/gas events followed by transient sharp-front relaxation",
        "post_event_continuation": POST_EVENT_PHASE,
        "drainage_enabled": flags["drainage"],
        "surfactant_diffusion_enabled": flags["surfactant_diffusion"],
        "rim_retraction": "NOT_IMPLEMENTED",
        "spray_droplets": "NOT_IMPLEMENTED",
    }


def run_postcoalescence_scenario(
    scenario: Mapping[str, Any], output_dir: str | Path, frames: int = 16
) -> dict[str, Any]:
    """Write one deterministic pre-event/event/post-event relaxation replay."""
    from bubblelab_contract import assert_valid

    scenario_copy = copy.deepcopy(dict(scenario))
    assert_valid(scenario_copy)
    physical, backend_meta = run_postcoalescence_frames(scenario_copy, frames)
    decorated = [_decorate(frame, scenario_copy, "thinfilm-events") for frame in physical]
    out = Path(output_dir)
    (out / "frames").mkdir(parents=True, exist_ok=True)
    refs = []
    for index, frame in enumerate(decorated):
        rel = f"frames/{index:06d}.json"
        (out / rel).write_bytes(_canonical_bytes(frame) + b"\n")
        refs.append(
            {
                "frame_id": frame["frame_id"],
                "path": rel,
                "simulation_time_s": frame["simulation_time_s"],
            }
        )

    event_ids: list[str] = []
    seen: set[str] = set()
    for frame in decorated:
        for event in frame.get("topology", {}).get("events", []):
            identifier = str(event["id"])
            if identifier not in seen:
                seen.add(identifier)
                event_ids.append(identifier)
    replay = {
        "bundle_version": "1.0.0",
        "contract_version": "1.0.0",
        "scenario": {
            "id": scenario_copy["scenario_id"],
            "sha256": scenario_hash(scenario_copy),
        },
        "backend": backend_meta,
        "random_seed": scenario_copy["random_seed"],
        "run_settings": {
            "backend": "thinfilm-events",
            "requested_frames": frames,
            "output_cadence_s": output_cadence_s(scenario_copy),
        },
        "frames": refs,
        "checkpoints": [],
        "provenance": {
            "producer": "bubblelab.runtime.postcoalescence_runtime",
            "source_scenario": scenario_copy["scenario_id"],
        },
        "fidelity": {
            "requested": scenario_copy["requested_fidelity_tier"],
            "produced": decorated[-1]["manifest"]["fidelity_tier"],
            "feature_disclosures": decorated[-1]["manifest"]["feature_disclosures"],
            "checkpoint_continuation": "NOT_IMPLEMENTED",
        },
        "event_runtime": {
            "event_ids": event_ids,
            "event_count": len(event_ids),
            "terminal_phase": decorated[-1].get("event_runtime", {}).get("phase"),
            "post_event_frame_count": sum(
                1
                for frame in decorated
                if frame.get("event_runtime", {}).get("phase") == POST_EVENT_PHASE
            ),
        },
    }
    (out / "replay.json").write_bytes(_canonical_bytes(replay) + b"\n")
    return replay
