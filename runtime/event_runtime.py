"""Runtime orchestration for accepted thin-film rupture/coalescence physics."""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from bubblelab.solvers.events.adapters import state_from_thinfilm_pair
from bubblelab.solvers.events.criteria import RuptureConfig, RuptureObservation
from bubblelab.solvers.events.engine import TopologyEventEngine, TopologyTransition
from bubblelab.solvers.events.export import canonical_frame_from_state
from bubblelab.solvers.thinfilm import GasRegionState, GasTransferPair, SurfaceTransportState

from .runner import UnsupportedScenarioFeature, _canonical_bytes, _decorate, scenario_hash
from .thinfilm_runtime import (
    _field_values,
    _gas_frame,
    _positive_float,
    _positive_int,
    _shared_surface,
    _validate_radius_volume,
    feature_flags,
    output_cadence_s,
    surface_parameters,
    thinfilm_config,
)

BACKEND_IDENTITY = "bubblelab-thinfilm-events-runtime"
BACKEND_VERSION = "1"
_EVENT_KEYS = {
    "enable_rupture",
    "coalesce_on_shared_film_rupture",
    "thickness_threshold_m",
    "dwell_time_s",
    "allow_user_trigger",
    "deterministic_seed",
    "user_trigger_time_s",
}
_UNSUPPORTED = {
    "adaptive_mesh_refinement", "amr", "cfd", "vof", "level_set",
    "boundary_geometry", "fragmentation", "splitting", "split", "t1",
    "dynamic_t1", "rim_retraction", "spray_droplets",
}


@dataclass(frozen=True)
class EventRuntimeConfig:
    enable_rupture: bool
    coalesce_on_shared_film_rupture: bool
    thickness_threshold_m: float
    dwell_time_s: float
    allow_user_trigger: bool
    deterministic_seed: int
    user_trigger_time_s: float | None


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _bool(mapping: Mapping[str, Any], key: str, default: bool) -> bool:
    value = mapping.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"user_editable.events.{key} must be boolean")
    return value


def event_runtime_config(scenario: Mapping[str, Any]) -> EventRuntimeConfig:
    editable = _mapping(scenario.get("user_editable") or {}, "user_editable")
    events = _mapping(editable.get("events"), "user_editable.events")
    unknown = sorted(set(events) - _EVENT_KEYS)
    if unknown:
        raise UnsupportedScenarioFeature(
            "unsupported event runtime setting(s): " + ", ".join(unknown)
        )
    enable = _bool(events, "enable_rupture", True)
    coalesce = _bool(events, "coalesce_on_shared_film_rupture", True)
    allow_user = _bool(events, "allow_user_trigger", False)
    threshold = float(events.get("thickness_threshold_m", 5.0e-8))
    dwell = float(events.get("dwell_time_s", 0.0))
    seed_raw = events.get("deterministic_seed", scenario["random_seed"])
    trigger_raw = events.get("user_trigger_time_s")
    trigger = None if trigger_raw is None else float(trigger_raw)
    if threshold <= 0.0 or not math.isfinite(threshold):
        raise ValueError("thickness_threshold_m must be finite and positive")
    if dwell < 0.0 or not math.isfinite(dwell):
        raise ValueError("dwell_time_s must be finite and non-negative")
    if isinstance(seed_raw, bool) or int(seed_raw) != seed_raw or int(seed_raw) < 0:
        raise ValueError("deterministic_seed must be a non-negative integer")
    if trigger is not None and (trigger < 0.0 or not math.isfinite(trigger)):
        raise ValueError("user_trigger_time_s must be finite and non-negative")
    if trigger is not None and not allow_user:
        raise ValueError("user_trigger_time_s requires allow_user_trigger=true")
    if trigger is not None and not enable:
        raise ValueError("user_trigger_time_s requires enable_rupture=true")
    if not coalesce:
        raise UnsupportedScenarioFeature(
            "coalesce_on_shared_film_rupture=false is unsupported because the accepted "
            "two-region event engine coalesces immediately after shared-film rupture"
        )
    return EventRuntimeConfig(
        enable, coalesce, threshold, dwell, allow_user, int(seed_raw), trigger
    )


def _features(scenario: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for source in (scenario.get("requested_solver") or {}, scenario.get("user_editable") or {}):
        if isinstance(source, Mapping) and isinstance(source.get("features"), Mapping):
            result.update(source["features"])
    return result


def _validate(scenario: Mapping[str, Any]) -> tuple[Mapping[str, Any], EventRuntimeConfig]:
    requested = scenario.get("requested_solver") or {}
    declared = requested.get("backend") if isinstance(requested, Mapping) else None
    if declared not in (None, "thinfilm-events"):
        raise ValueError(f"scenario requested backend {declared!r}, CLI selected 'thinfilm-events'")
    features = _features(scenario)
    bad = sorted(name for name in _UNSUPPORTED if bool(features.get(name)))
    if bad:
        raise UnsupportedScenarioFeature("unsupported thinfilm-events feature(s): " + ", ".join(bad))
    if not bool(features.get("shared_film_topology")):
        raise UnsupportedScenarioFeature("thinfilm-events requires shared_film_topology=true")
    if scenario.get("initial_junctions"):
        raise UnsupportedScenarioFeature("multi-junction dynamic T1 transitions are unsupported")
    if (scenario.get("environment") or {}).get("boundary_refs"):
        raise UnsupportedScenarioFeature("boundary geometry is unsupported by thinfilm-events")
    bubbles = scenario.get("initial_bubbles") or []
    if len(bubbles) != 2:
        raise UnsupportedScenarioFeature("thinfilm-events supports exactly two bubbles sharing one film")
    for bubble in bubbles:
        _validate_radius_volume(bubble)
    film_config = thinfilm_config(scenario)
    if film_config is None:
        raise ValueError("thinfilm-events requires user_editable.thinfilm")
    if not feature_flags(film_config)["gas_diffusion"]:
        raise UnsupportedScenarioFeature("thinfilm-events requires enable_gas_diffusion=true")
    if output_cadence_s(scenario) is None:
        raise ValueError("thinfilm-events requires user_editable.runtime.output_cadence_s")
    return film_config, event_runtime_config(scenario)


def _gas_states(scenario: Mapping[str, Any]) -> list[GasRegionState]:
    result: list[GasRegionState] = []
    for bubble in scenario["initial_bubbles"]:
        if bubble.get("gas_amount_mol") is None:
            raise ValueError("thinfilm-events requires gas_amount_mol on each bubble")
        result.append(GasRegionState(
            id=str(bubble["id"]),
            volume_m3=float(bubble["volume_m3"]),
            amount_mol=float(bubble["gas_amount_mol"]),
            temperature_k=float(bubble.get("temperature_k") or 298.15),
        ))
    return result


def _pair(surface: Any, film: Mapping[str, Any], state: SurfaceTransportState, config: Mapping[str, Any]) -> GasTransferPair:
    area = math.fsum(surface.face_areas_m2())
    adjacent = [str(value) for value in film["adjacent"]]
    return GasTransferPair(
        adjacent[0], adjacent[1],
        shared_area_m2=area,
        film_thickness_m=state.liquid_amount_m3() / area,
        permeability_mol_m_per_m2_s_pa=_positive_float(
            config, "gas_permeability_mol_m_per_m2_s_pa", 1.0e-16, allow_zero=True
        ),
        positivity_safety=_positive_float(config, "positivity_safety", 0.45),
        max_substeps=_positive_int(config, "max_substeps", 10000),
    )


def _event_state(
    scenario: Mapping[str, Any], film: Mapping[str, Any], surface_state: SurfaceTransportState,
    gases: Sequence[GasRegionState], config: EventRuntimeConfig,
):
    centroids, velocities, masses, molar_masses = {}, {}, {}, []
    for bubble in scenario["initial_bubbles"]:
        identifier = str(bubble["id"])
        centroids[identifier] = tuple(float(x) for x in bubble["centroid_m"])
        velocities[identifier] = tuple(float(x) for x in bubble["velocity_m_s"])
        if bubble.get("mass_kg") is not None:
            masses[identifier] = float(bubble["mass_kg"])
        if bubble.get("molar_mass_kg_mol") is not None:
            molar_masses.append(float(bubble["molar_mass_kg_mol"]))
    molar_mass = None
    if len(molar_masses) == 2 and molar_masses[0] == molar_masses[1]:
        molar_mass = molar_masses[0]
    by_id = {gas.id: gas for gas in gases}
    adjacent = [str(value) for value in film["adjacent"]]
    return state_from_thinfilm_pair(
        surface_state, by_id[adjacent[0]], by_id[adjacent[1]],
        film_id=str(film["id"]), centroids_m=centroids, velocities_m_s=velocities,
        masses_kg=masses, molar_mass_kg_mol=molar_mass, seed=config.deterministic_seed,
    )


def _disclosures(film_config: Mapping[str, Any], config: EventRuntimeConfig) -> dict[str, str]:
    flags = feature_flags(film_config)
    modeled_event = "MODELED" if config.enable_rupture else "NOT_IMPLEMENTED"
    return {
        "film_thickness": "MODELED",
        "film_drainage": "MODELED" if flags["drainage"] else "NOT_IMPLEMENTED",
        "drainage": "MODELED" if flags["drainage"] else "NOT_IMPLEMENTED",
        "surfactant_transport": "MODELED" if flags["surfactant_diffusion"] else "NOT_IMPLEMENTED",
        "surfactant_diffusion": "MODELED" if flags["surfactant_diffusion"] else "NOT_IMPLEMENTED",
        "surface_tension": "MODELED", "shared_film_topology": "MODELED",
        "gas_diffusion": "MODELED", "coarsening": "MODELED",
        "geometry_evolution": "NOT_IMPLEMENTED", "topology_change": modeled_event,
        "rupture": modeled_event, "coalescence": modeled_event,
        "event_time_localization": modeled_event,
        "post_event_restart_geometry": modeled_event,
        "post_event_cfd_relaxation": "NOT_IMPLEMENTED",
        "rim_retraction": "NOT_IMPLEMENTED", "spray_droplets": "NOT_IMPLEMENTED",
        "splitting": "NOT_IMPLEMENTED",
    }


def _normalize(
    frame: dict[str, Any], scenario: Mapping[str, Any], film_config: Mapping[str, Any],
    config: EventRuntimeConfig, *, frame_id: str, phase: str,
    surface_step: Any | None = None, event_ids: Sequence[str] = (),
) -> dict[str, Any]:
    out = copy.deepcopy(frame)
    out["frame_id"] = frame_id
    out["environment"] = copy.deepcopy(scenario["environment"])
    out["manifest"]["solver"] = {
        "backend": BACKEND_IDENTITY, "version": BACKEND_VERSION,
        "adapter": "accepted-thinfilm-gas-plus-topology-events",
    }
    out["manifest"]["feature_disclosures"] = _disclosures(film_config, config)
    out["manifest"].setdefault("provenance", {}).update({
        "producer": "bubblelab.runtime.event_runtime", "source_scenario": scenario["scenario_id"],
        "event_seed": config.deterministic_seed, "event_engine": "bubblelab.solvers.events",
        "thinfilm_engine": "bubblelab.solvers.thinfilm",
    })
    diagnostics = out.setdefault("diagnostics", {})
    if surface_step is not None:
        diagnostics.setdefault("thinfilm", {})["surface_step"] = asdict(surface_step)
    diagnostics["event_runtime"] = {
        "phase": phase, "shared_film_id": str(scenario["initial_film_regions"][0]["id"]),
        "event_ids": list(event_ids), "event_seed": config.deterministic_seed,
    }
    out["event_runtime"] = {
        "phase": phase, "shared_film_id": str(scenario["initial_film_regions"][0]["id"]),
        "event_ids": list(event_ids),
        "post_event_relaxation": "REQUIRED_BUT_NOT_ADVANCED" if phase == "POST_EVENT" else "NOT_APPLICABLE",
    }
    return out


def _event_frames(
    transition: TopologyTransition, scenario: Mapping[str, Any], film_config: Mapping[str, Any],
    config: EventRuntimeConfig, film_state: SurfaceTransportState, gases: Sequence[GasRegionState],
    *, observation_time_s: float, cadence_s: float, cumulative_transfer: float,
    surface_step: Any | None, gas_step: Any | None, serial: int,
) -> list[dict[str, Any]]:
    emitted = tuple(transition.emitted_events)
    event_time = min(event.time_s for event in emitted)
    base = canonical_frame_from_state(transition.state, frame_time_s=event_time)
    base.setdefault("diagnostics", {})["timestep_s"] = cadence_s
    base["diagnostics"]["thinfilm"] = {
        "accepted_observation_time_s": observation_time_s,
        "min_thickness_m": min(film_state.thickness_m),
        "max_thickness_m": max(film_state.thickness_m),
        "liquid_amount_m3": film_state.liquid_amount_m3(),
        "surfactant_amount_mol": film_state.surfactant_amount_mol(),
        "gas_amounts_mol": {gas.id: gas.amount_mol for gas in gases},
        "pressures_pa": {gas.id: gas.pressure_pa for gas in gases},
        "cumulative_transfer_a_to_b_mol": cumulative_transfer,
    }
    if surface_step is not None:
        base["diagnostics"]["thinfilm"]["surface_step"] = asdict(surface_step)
    if gas_step is not None:
        base["diagnostics"]["thinfilm"]["gas_step"] = asdict(gas_step)
    ids = [event.id for event in emitted]
    event_frame = _normalize(
        base, scenario, film_config, config,
        frame_id=f"thinfilm-events-{serial:06d}-event", phase="EVENT", event_ids=ids,
    )
    requires_relaxation = any(
        bool((event.conservation or {}).get("requires_post_event_relaxation")) for event in emitted
    )
    event_frame["event_runtime"].update({
        "localized_event_time_s": event_time,
        "event_order": [event.type for event in emitted],
        "physical_advancement_after_event": False,
        "requires_post_event_relaxation": requires_relaxation,
    })
    post = copy.deepcopy(event_frame)
    post["frame_id"] = f"thinfilm-events-{serial + 1:06d}-post"
    post["event_runtime"].update({
        "phase": "POST_EVENT", "post_event_relaxation": "REQUIRED_BUT_NOT_ADVANCED",
        "requires_post_event_relaxation": requires_relaxation,
        "terminal_reason": "conservative restart surface emitted; post-event transient relaxation is not connected",
    })
    post["diagnostics"]["event_runtime"].update({"phase": "POST_EVENT", "terminal": True})
    post["manifest"]["provenance"]["post_event_continuation"] = (
        "terminal conservative restart only; geometry requires later relaxation"
    )
    return [event_frame, post]


def run_event_frames(scenario: Mapping[str, Any], frames: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if frames < 1:
        raise ValueError("--frames must be >= 1")
    film_config, config = _validate(scenario)
    cadence = output_cadence_s(scenario)
    assert cadence is not None
    surface, film = _shared_surface(scenario)
    film_state = SurfaceTransportState(
        surface,
        _field_values(film_config.get("initial_thickness_m", 8.0e-6), len(surface.faces), "initial_thickness_m"),
        _field_values(film_config.get("initial_surfactant_mol_m2", 0.0), len(surface.faces), "initial_surfactant_mol_m2"),
        parameters=surface_parameters(scenario, film_config),
    )
    gases = _gas_states(scenario)
    by_id = {gas.id: gas for gas in gases}
    pair = _pair(surface, film, film_state, film_config)
    initial_total = math.fsum(gas.amount_mol for gas in gases)
    engine = TopologyEventEngine(RuptureConfig(
        thickness_threshold_m=config.thickness_threshold_m,
        dwell_time_s=config.dwell_time_s,
        allow_user_trigger=config.allow_user_trigger,
    ), seed=config.deterministic_seed)
    physical: list[dict[str, Any]] = []
    current_time = 0.0
    cumulative = 0.0
    trigger = config.user_trigger_time_s
    epsilon = 16.0 * math.ulp(max(cadence, 1.0))

    def pre_frame(index: int, dt: float, gas_step: Any | None, surface_step: Any | None) -> dict[str, Any]:
        pair_now = _pair(surface, film, film_state, film_config)
        raw = _gas_frame(
            scenario, surface, film, film_state, gases, frame_index=index,
            time_s=current_time, cadence_s=dt, initial_total_mol=initial_total,
            cumulative_transfer_a_to_b_mol=cumulative, last_gas_step=gas_step, pair=pair_now,
        )
        return _normalize(
            raw, scenario, film_config, config,
            frame_id=f"thinfilm-events-{len(physical):06d}-pre", phase="PRE_EVENT",
            surface_step=surface_step,
        )

    physical.append(pre_frame(0, cadence, None, None))
    state = _event_state(scenario, film, film_state, gases, config)
    transition: TopologyTransition | None = None
    if trigger is not None and abs(trigger) <= epsilon:
        transition = engine.trigger_user_rupture(
            state, str(film["id"]), time_s=0.0, detail="deterministic runtime user burst"
        )
    elif config.enable_rupture:
        transition = engine.observe_film(
            state, str(film["id"]),
            RuptureObservation(time_s=0.0, min_thickness_m=min(film_state.thickness_m)),
        )
    if transition is not None and transition.emitted_events:
        physical.extend(_event_frames(
            transition, scenario, film_config, config, film_state, gases,
            observation_time_s=0.0, cadence_s=cadence, cumulative_transfer=cumulative,
            surface_step=None, gas_step=None, serial=len(physical),
        ))
    else:
        for index in range(1, frames):
            dt = cadence
            if trigger is not None and current_time + epsilon < trigger < current_time + cadence - epsilon:
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
                    state, str(film["id"]), time_s=trigger, detail="deterministic runtime user burst"
                )
            elif config.enable_rupture:
                transition = engine.observe_film(
                    state, str(film["id"]),
                    RuptureObservation(time_s=current_time, min_thickness_m=min(film_state.thickness_m)),
                )
            if transition is not None and transition.emitted_events:
                physical.extend(_event_frames(
                    transition, scenario, film_config, config, film_state, gases,
                    observation_time_s=current_time, cadence_s=dt, cumulative_transfer=cumulative,
                    surface_step=surface_step, gas_step=gas_step, serial=len(physical),
                ))
                break
            physical.append(pre_frame(index, dt, gas_step, surface_step))

    if trigger is not None and not any(
        frame.get("event_runtime", {}).get("phase") == "EVENT" for frame in physical
    ):
        raise UnsupportedScenarioFeature("user_trigger_time_s lies beyond the requested frame horizon")
    flags = feature_flags(film_config)
    return physical, {
        "identity": BACKEND_IDENTITY, "version": BACKEND_VERSION,
        "mode": "accepted thin-film/gas runtime with deterministic rupture/coalescence events",
        "post_event_continuation": "TERMINAL_RESTART_ONLY",
        "drainage_enabled": flags["drainage"],
        "surfactant_diffusion_enabled": flags["surfactant_diffusion"],
    }


def run_event_scenario(scenario: Mapping[str, Any], output_dir: str | Path, frames: int = 4) -> dict[str, Any]:
    """Run thinfilm-events and write a byte-deterministic canonical replay bundle."""
    from bubblelab_contract import assert_valid

    scenario_copy = copy.deepcopy(dict(scenario))
    assert_valid(scenario_copy)
    physical, backend_meta = run_event_frames(scenario_copy, frames)
    decorated = [_decorate(frame, scenario_copy, "thinfilm-events") for frame in physical]
    out = Path(output_dir)
    (out / "frames").mkdir(parents=True, exist_ok=True)
    refs = []
    for index, frame in enumerate(decorated):
        rel = f"frames/{index:06d}.json"
        (out / rel).write_bytes(_canonical_bytes(frame) + b"\n")
        refs.append({"frame_id": frame["frame_id"], "path": rel, "simulation_time_s": frame["simulation_time_s"]})
    event_ids, seen = [], set()
    for frame in decorated:
        for event in frame.get("topology", {}).get("events", []):
            identifier = str(event["id"])
            if identifier not in seen:
                seen.add(identifier)
                event_ids.append(identifier)
    replay = {
        "bundle_version": "1.0.0", "contract_version": "1.0.0",
        "scenario": {"id": scenario_copy["scenario_id"], "sha256": scenario_hash(scenario_copy)},
        "backend": backend_meta, "random_seed": scenario_copy["random_seed"],
        "run_settings": {
            "backend": "thinfilm-events", "requested_frames": frames,
            "output_cadence_s": output_cadence_s(scenario_copy),
        },
        "frames": refs, "checkpoints": [],
        "provenance": {"producer": "bubblelab.runtime.event_runtime", "source_scenario": scenario_copy["scenario_id"]},
        "fidelity": {
            "requested": scenario_copy["requested_fidelity_tier"],
            "produced": decorated[-1]["manifest"]["fidelity_tier"],
            "feature_disclosures": decorated[-1]["manifest"]["feature_disclosures"],
            "checkpoint_continuation": "NOT_IMPLEMENTED",
        },
        "event_runtime": {
            "event_ids": event_ids, "event_count": len(event_ids),
            "terminal_phase": decorated[-1].get("event_runtime", {}).get("phase"),
        },
    }
    (out / "replay.json").write_bytes(_canonical_bytes(replay) + b"\n")
    return replay
