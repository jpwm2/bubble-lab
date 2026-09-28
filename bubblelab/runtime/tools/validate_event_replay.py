#!/usr/bin/env python3
"""Validate deterministic rupture/coalescence semantics in a runtime replay bundle."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.runtime.bundle import validate_replay_bundle


class EventReplayValidationError(ValueError):
    pass


def _load_frames(root: Path, replay: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        json.loads((root / ref["path"]).read_text(encoding="utf-8"))
        for ref in replay["frames"]
    ]


def _distinct_events(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    events: list[dict[str, Any]] = []
    for frame in frames:
        for event in (frame.get("topology") or {}).get("events", []):
            event_id = str(event.get("id", ""))
            if event_id and event_id not in seen:
                seen.add(event_id)
                events.append(event)
    return events


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EventReplayValidationError(message)


def _event(events: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    matches = [item for item in events if item.get("type") == kind]
    _require(len(matches) == 1, f"expected exactly one {kind} event")
    return matches[0]


def _assert_sequence(frames: list[dict[str, Any]], events: list[dict[str, Any]]) -> None:
    phases = [(frame.get("event_runtime") or {}).get("phase") for frame in frames]
    _require("PRE_EVENT" in phases and "EVENT" in phases and "POST_EVENT" in phases,
             "replay must contain pre-event, event, and post-event frames")
    pre = max(i for i, phase in enumerate(phases) if phase == "PRE_EVENT")
    event = phases.index("EVENT")
    post = phases.index("POST_EVENT")
    _require(pre < event < post, "frame ordering must be pre-event, event, post-event")
    times = [float(frame["simulation_time_s"]) for frame in frames]
    _require(times[pre] <= times[event] <= times[post], "event frame times are not ordered")
    types = [item.get("type") for item in events]
    if "RUPTURE" in types and "COALESCENCE" in types:
        _require(types.index("RUPTURE") < types.index("COALESCENCE"),
                 "RUPTURE must precede COALESCENCE")


def _assert_lineage(frames: list[dict[str, Any]], events: list[dict[str, Any]]) -> None:
    coalescence = _event(events, "COALESCENCE")
    lineage = coalescence.get("lineage")
    _require(isinstance(lineage, dict) and len(lineage) == 1, "coalescence lineage is missing")
    child, raw_parents = next(iter(lineage.items()))
    parents = sorted(str(value) for value in raw_parents)
    _require(parents == sorted(str(value) for value in coalescence.get("bubble_ids_before", [])),
             "lineage parents do not match coalescence parents")
    _require(coalescence.get("bubble_ids_after") == [child], "coalescence child does not match lineage")
    post = next(frame for frame in frames if (frame.get("event_runtime") or {}).get("phase") == "POST_EVENT")
    bubbles = {str(item["id"]): item for item in post.get("bubbles", [])}
    _require(child in bubbles and bubbles[child].get("status") == "ALIVE", "child is not alive post-event")
    _require(sorted(str(value) for value in bubbles[child].get("lineage", [])) == parents,
             "child lineage is not preserved")
    for parent in parents:
        _require(parent in bubbles and bubbles[parent].get("status") == "MERGED",
                 "coalescence parent is not retired as MERGED")


def _assert_conservation(events: list[dict[str, Any]]) -> None:
    values = _event(events, "COALESCENCE").get("conservation")
    _require(isinstance(values, dict), "coalescence conservation diagnostics are missing")
    for key in ("gas_amount_relative_error", "target_volume_relative_error",
                "restart_geometry_volume_relative_error"):
        value = values.get(key)
        _require(value is not None and math.isfinite(float(value)), f"{key} is missing")
        _require(float(value) <= 1.0e-12 * (1.0 + 1.0e-9), f"{key} exceeds tolerance")
    _require(values.get("requires_post_event_relaxation") is True,
             "restart geometry must disclose required relaxation")
    before, after = values.get("momentum_kg_m_s_before"), values.get("momentum_kg_m_s_after")
    error = values.get("momentum_relative_error")
    if before is not None or after is not None or error is not None:
        _require(before is not None and after is not None and error is not None,
                 "partial momentum conservation diagnostics")
        _require(float(error) <= 1.0e-12 * (1.0 + 1.0e-9), "momentum conservation tolerance exceeded")


def validate(bundle_dir: str | Path, *, assert_rupture: bool = False,
             assert_coalescence: bool = False, assert_lineage: bool = False,
             assert_conservation: bool = False, assert_user_rupture: bool = False) -> dict[str, Any]:
    root = Path(bundle_dir)
    replay = validate_replay_bundle(root)
    frames = _load_frames(root, replay)
    events = _distinct_events(frames)
    _assert_sequence(frames, events)
    if assert_rupture:
        rupture = _event(events, "RUPTURE")
        _require((rupture.get("provenance") or {}).get("source") == "SOLVER",
                 "expected solver-originated rupture")
        _require(rupture.get("criterion") in {"THICKNESS_THRESHOLD", "THICKNESS_DWELL"},
                 "expected thickness-based rupture criterion")
    if assert_coalescence:
        _event(events, "COALESCENCE")
    if assert_lineage:
        _assert_lineage(frames, events)
    if assert_conservation:
        _assert_conservation(events)
    if assert_user_rupture:
        rupture = _event(events, "RUPTURE")
        _require((rupture.get("provenance") or {}).get("source") == "USER",
                 "user rupture provenance is not USER")
        _require(rupture.get("criterion") == "USER_TRIGGER", "user rupture criterion is not USER_TRIGGER")
    return {"frames": len(frames), "events": [item["type"] for item in events],
            "event_ids": [item["id"] for item in events]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle_dir")
    parser.add_argument("--assert-rupture", action="store_true")
    parser.add_argument("--assert-coalescence", action="store_true")
    parser.add_argument("--assert-lineage", action="store_true")
    parser.add_argument("--assert-conservation", action="store_true")
    parser.add_argument("--assert-user-rupture", action="store_true")
    args = parser.parse_args()
    print(json.dumps(validate(
        args.bundle_dir, assert_rupture=args.assert_rupture,
        assert_coalescence=args.assert_coalescence, assert_lineage=args.assert_lineage,
        assert_conservation=args.assert_conservation, assert_user_rupture=args.assert_user_rupture,
    ), sort_keys=True))


if __name__ == "__main__":
    main()
