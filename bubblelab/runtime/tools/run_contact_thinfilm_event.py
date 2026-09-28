#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.runtime.bundle import validate_replay_bundle
from bubblelab.runtime.contact_thinfilm_event_runtime import (
    run_contact_thinfilm_event_scenario,
)


def _load_frames(root: Path, replay: dict) -> list[dict]:
    return [
        json.loads((root / item["path"]).read_text(encoding="utf-8"))
        for item in replay["frames"]
    ]


def _assert_transport(frames: list[dict]) -> dict[str, float]:
    thinfilm = [
        frame["diagnostics"]["thinfilm"]
        for frame in frames
        if isinstance(frame.get("diagnostics", {}).get("thinfilm"), dict)
        and "min_thickness_m" in frame["diagnostics"]["thinfilm"]
    ]
    if len(thinfilm) < 2:
        raise AssertionError("expected at least two accepted thin-film states after contact")
    initial_min = float(thinfilm[0]["min_thickness_m"])
    evolved = [float(item["min_thickness_m"]) for item in thinfilm[1:]]
    if not any(not math.isclose(value, initial_min, rel_tol=0.0, abs_tol=1.0e-15) for value in evolved):
        raise AssertionError("accepted drainage did not evolve the shared-film thickness field")
    for item in thinfilm:
        drift = item.get("gas_total_relative_drift")
        if drift is not None and float(drift) > 1.0e-12:
            raise AssertionError("gas transfer exceeded conservation tolerance")
        step = item.get("surface_step")
        if isinstance(step, dict):
            if float(step["liquid_relative_drift"]) > 1.0e-12:
                raise AssertionError("liquid transport exceeded conservation tolerance")
            if float(step["surfactant_relative_drift"]) > 1.0e-12:
                raise AssertionError("surfactant transport exceeded conservation tolerance")
    return {"initial_min_thickness_m": initial_min, "minimum_observed_thickness_m": min(evolved)}


def _unique_events(frames: list[dict]) -> list[dict]:
    output, seen = [], set()
    for frame in frames:
        for event in frame.get("topology", {}).get("events", []):
            identifier = str(event["id"])
            if identifier not in seen:
                seen.add(identifier)
                output.append(event)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run contact-created shared-film drainage and accepted topology events."
    )
    parser.add_argument("scenario")
    parser.add_argument("--output", required=True)
    parser.add_argument("--contact-frames", type=int, default=12)
    parser.add_argument("--thinfilm-frames", type=int, default=8)
    parser.add_argument("--assert", dest="assert_transport", action="store_true")
    parser.add_argument("--assert-event", action="store_true")
    args = parser.parse_args()

    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    root = Path(args.output)
    replay = run_contact_thinfilm_event_scenario(
        scenario,
        root,
        contact_frames=args.contact_frames,
        thinfilm_frames=args.thinfilm_frames,
    )
    validate_replay_bundle(root)
    frames = _load_frames(root, replay)
    transport = _assert_transport(frames) if (args.assert_transport or args.assert_event) else {}

    events = _unique_events(frames)
    types = [str(event["type"]) for event in events]
    if args.assert_event:
        if "RUPTURE" not in types or "COALESCENCE" not in types:
            raise AssertionError("accepted RUPTURE/COALESCENCE path was not reached")
        rupture = next(event for event in events if event["type"] == "RUPTURE")
        if rupture.get("provenance", {}).get("source") != "SOLVER":
            raise AssertionError("rupture must be produced by the accepted solver criterion")
        if rupture.get("criterion") not in ("THICKNESS_THRESHOLD", "THICKNESS_DWELL"):
            raise AssertionError("rupture must be produced by accepted thickness physics")

    print(json.dumps({
        "valid": True,
        "frames": len(frames),
        "event_types": types,
        "shared_film_id": replay["backend"]["shared_film_id"],
        "shared_film_geometry_digest": replay["backend"]["shared_film_geometry_digest"],
        **transport,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
