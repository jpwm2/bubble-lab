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
from bubblelab.runtime.precontact_cfd_runtime import (
    run_precontact_cfd_transition,
)

DEFAULT_SCENARIO = (
    ROOT
    / "bubblelab"
    / "scenarios"
    / "runtime"
    / "precontact-cfd-two-bubble.scenario.json"
)


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _disabled_copy(scenario: dict[str, object]) -> dict[str, object]:
    out = copy.deepcopy(scenario)
    contact = out["user_editable"]["contact_runtime"]
    assert isinstance(contact, dict)
    cfd = contact["precontact_cfd"]
    assert isinstance(cfd, dict)
    cfd["enabled"] = False
    lubrication = contact.get("lubrication")
    if isinstance(lubrication, dict):
        lubrication["enabled"] = False
    return out


def _reduced_copy(scenario: dict[str, object]) -> dict[str, object]:
    out = copy.deepcopy(scenario)
    contact = out["user_editable"]["contact_runtime"]
    assert isinstance(contact, dict)
    cfd = contact["precontact_cfd"]
    assert isinstance(cfd, dict)
    cfd["enabled"] = False
    lubrication = contact["lubrication"]
    assert isinstance(lubrication, dict)
    lubrication["enabled"] = True
    return out


def _event_frame(
    frames: list[dict[str, object]],
) -> tuple[dict[str, object], dict[str, object]]:
    matches: list[tuple[dict[str, object], dict[str, object]]] = []
    for frame in frames:
        topology = frame.get("topology") or {}
        if not isinstance(topology, dict):
            continue
        for event in topology.get("events", []):
            if (
                isinstance(event, dict)
                and event.get("transition_kind") == "CONTACT_FORMATION"
            ):
                matches.append((frame, event))
    if len(matches) != 1:
        raise RuntimeError(
            f"expected exactly one contact formation frame, got {len(matches)}"
        )
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run resolved local pre-contact gap CFD and compare contact timing "
            "against both disabled and reduced Reynolds/Taylor modes."
        )
    )
    parser.add_argument(
        "scenario",
        nargs="?",
        default=str(DEFAULT_SCENARIO),
    )
    parser.add_argument("--frames", type=int, default=12)
    parser.add_argument("--output", default="/tmp/bubble-precontact-cfd")
    parser.add_argument("--assert", dest="assert_valid", action="store_true")
    args = parser.parse_args()

    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    cfd_frames, cfd_meta = run_precontact_cfd_transition(
        scenario,
        args.frames,
    )
    disabled_frames, disabled_meta = run_precontact_cfd_transition(
        _disabled_copy(scenario),
        args.frames,
    )
    reduced_frames, reduced_meta = run_contact_lubrication_transition(
        _reduced_copy(scenario),
        args.frames,
    )
    repeat_frames, repeat_meta = run_precontact_cfd_transition(
        scenario,
        args.frames,
    )

    model = cfd_meta["pre_contact_cfd"]
    cfd_time = float(cfd_meta["contact_event_time_s"])
    disabled_time = float(disabled_meta["contact_event_time_s"])
    reduced_time = float(reduced_meta["contact_event_time_s"])
    deterministic = (
        _canonical(cfd_frames) == _canonical(repeat_frames)
        and _canonical(cfd_meta) == _canonical(repeat_meta)
    )
    event_frame, event = _event_frame(cfd_frames)
    provenance = event.get("provenance") or {}
    films = event_frame.get("film_regions") or []
    shared_films = [
        item
        for item in films
        if isinstance(item, dict) and item.get("kind") == "SHARED"
    ]
    reduced_ratio = cfd_time / max(reduced_time, 1.0e-300)
    valid = all((
        model["status"] == "SUPPORTED_CLASS_RESOLVED",
        int(model["activation_count"]) > 0,
        float(model["max_center_pressure_pa"]) > 0.0,
        float(model["max_cfd_traction_force_n"]) > 0.0,
        float(model["max_closed_bubble_volume_relative_change"])
        <= 5.0e-12,
        float(model["max_local_mass_balance_relative_residual"])
        < 1.0e-10,
        float(model["max_wall_slip_m_s"]) <= 1.0e-15,
        cfd_time > disabled_time,
        reduced_time > disabled_time,
        0.75 <= reduced_ratio <= 1.25,
        deterministic,
        provenance.get("pre_contact_cfd_status")
        == "SUPPORTED_CLASS_RESOLVED",
        len(shared_films) == 1,
        cfd_meta.get("contact_surgery")
        == "bubblelab.solvers.transient.contact.form_contact",
        "global full-domain multi-region Eulerian/Navier-Stokes gap coupling"
        in cfd_meta.get("unsupported", []),
    ))

    summary = {
        "valid": valid,
        "frames": len(cfd_frames),
        "resolved_local_cfd_contact_event_time_s": cfd_time,
        "reduced_order_contact_event_time_s": reduced_time,
        "disabled_contact_event_time_s": disabled_time,
        "cfd_delay_vs_disabled_s": cfd_time - disabled_time,
        "reduced_delay_vs_disabled_s": reduced_time - disabled_time,
        "cfd_to_reduced_contact_time_ratio": reduced_ratio,
        "deterministic_repeat": deterministic,
        "pre_contact_cfd": model,
        "handoff": {
            "shared_film_count": len(shared_films),
            "contact_event_provenance_status": provenance.get(
                "pre_contact_cfd_status"
            ),
            "contact_surgery": cfd_meta.get("contact_surgery"),
            "post_contact_solver": cfd_meta.get("post_contact_solver"),
        },
        "claim_boundary": {
            "supported": (
                "isolated two-front local thin-gap pressure/velocity/traction patch"
            ),
            "global_full_domain_multi_region_cfd": "NOT_IMPLEMENTED",
        },
    }

    destination = Path(args.output)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "cfd.json").write_text(
        json.dumps(
            {"frames": cfd_frames, "backend": cfd_meta},
            sort_keys=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    (destination / "disabled.json").write_text(
        json.dumps(
            {"frames": disabled_frames, "backend": disabled_meta},
            sort_keys=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    (destination / "reduced.json").write_text(
        json.dumps(
            {"frames": reduced_frames, "backend": reduced_meta},
            sort_keys=True,
            indent=2,
        ),
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
