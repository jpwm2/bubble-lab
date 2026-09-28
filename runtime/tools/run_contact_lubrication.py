#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.runtime.contact_lubrication_runtime import (
    run_contact_lubrication_transition,
)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _disabled_copy(scenario: dict[str, object]) -> dict[str, object]:
    out = copy.deepcopy(scenario)
    editable = out.setdefault("user_editable", {})
    assert isinstance(editable, dict)
    contact = editable.setdefault("contact_runtime", {})
    assert isinstance(contact, dict)
    lubrication = contact.setdefault("lubrication", {})
    assert isinstance(lubrication, dict)
    lubrication["enabled"] = False
    return out


def _event_frame(frames: list[dict[str, object]]) -> dict[str, object]:
    matches = []
    for frame in frames:
        topology = frame.get("topology") or {}
        assert isinstance(topology, dict)
        for event in topology.get("events", []):
            if isinstance(event, dict) and event.get("transition_kind") == "CONTACT_FORMATION":
                matches.append(frame)
    if len(matches) != 1:
        raise RuntimeError("expected exactly one contact formation frame")
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run coupled pre-contact Reynolds/Taylor lubrication and compare to disabled approach."
    )
    parser.add_argument("scenario")
    parser.add_argument("--frames", type=int, default=12)
    parser.add_argument("--output", required=True)
    parser.add_argument("--assert", dest="assert_valid", action="store_true")
    args = parser.parse_args()

    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    enabled_frames, enabled_meta = run_contact_lubrication_transition(
        scenario,
        args.frames,
    )
    disabled_frames, disabled_meta = run_contact_lubrication_transition(
        _disabled_copy(scenario),
        args.frames,
    )
    repeat_frames, repeat_meta = run_contact_lubrication_transition(
        scenario,
        args.frames,
    )

    model = enabled_meta["pre_contact_lubrication"]
    enabled_time = float(enabled_meta["contact_event_time_s"])
    disabled_time = float(disabled_meta["contact_event_time_s"])
    deterministic = (
        _canonical(enabled_frames) == _canonical(repeat_frames)
        and _canonical(enabled_meta) == _canonical(repeat_meta)
    )
    event_frame = _event_frame(enabled_frames)
    topology = event_frame["topology"]
    assert isinstance(topology, dict)
    event = next(
        item
        for item in topology["events"]
        if item.get("transition_kind") == "CONTACT_FORMATION"
    )
    provenance = event.get("provenance") or {}
    films = event_frame.get("film_regions") or []
    shared_films = [item for item in films if isinstance(item, dict) and item.get("kind") == "SHARED"]

    valid = all((
        model["status"] == "MODELED",
        int(model["activation_count"]) > 0,
        float(model["max_center_pressure_pa"]) > 0.0,
        float(model["max_lubrication_force_n"]) > 0.0,
        float(model["max_closed_bubble_volume_relative_change"]) <= 5.0e-12,
        enabled_time > disabled_time,
        deterministic,
        provenance.get("pre_contact_lubrication_status") == "MODELED",
        len(shared_films) == 1,
        enabled_meta.get("contact_surgery") == "bubblelab.solvers.transient.contact.form_contact",
    ))

    summary = {
        "valid": valid,
        "frames": len(enabled_frames),
        "coupled_contact_event_time_s": enabled_time,
        "disabled_contact_event_time_s": disabled_time,
        "contact_delay_s": enabled_time - disabled_time,
        "deterministic_repeat": deterministic,
        "lubrication": model,
        "handoff": {
            "shared_film_count": len(shared_films),
            "contact_event_provenance_status": provenance.get(
                "pre_contact_lubrication_status"
            ),
            "contact_surgery": enabled_meta.get("contact_surgery"),
            "post_contact_solver": enabled_meta.get("post_contact_solver"),
        },
    }

    destination = Path(args.output)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "enabled.json").write_text(
        json.dumps({"frames": enabled_frames, "backend": enabled_meta}, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    (destination / "disabled.json").write_text(
        json.dumps({"frames": disabled_frames, "backend": disabled_meta}, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    (destination / "summary.json").write_text(
        json.dumps(summary, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True))
    if args.assert_valid and not valid:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
