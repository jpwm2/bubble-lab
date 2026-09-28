#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

PHASE = "POST_EVENT_TRANSIENT_RELAXATION"


def _load_frames(root: Path, replay: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        json.loads((root / item["path"]).read_text(encoding="utf-8"))
        for item in replay["frames"]
    ]


def _mesh(frame: dict[str, Any], mesh_id: str | None = None) -> dict[str, Any]:
    meshes = frame.get("surface_meshes", [])
    if mesh_id is None:
        if len(meshes) != 1:
            raise AssertionError("expected exactly one post-event surface mesh")
        return meshes[0]
    matches = [mesh for mesh in meshes if str(mesh.get("id")) == mesh_id]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one surface mesh {mesh_id!r}")
    return matches[0]


def _events(frame: dict[str, Any]) -> list[dict[str, Any]]:
    return list((frame.get("topology") or {}).get("events") or [])


def _event_ids(frame: dict[str, Any]) -> list[str]:
    return [str(event["id"]) for event in _events(frame)]


def _assert_event_history(event_frame: dict[str, Any], post: list[dict[str, Any]]) -> None:
    expected = _events(event_frame)
    expected_ids = [str(event["id"]) for event in expected]
    if [event["type"] for event in expected] != ["RUPTURE", "COALESCENCE"]:
        raise AssertionError("event frame must contain accepted RUPTURE then COALESCENCE history")
    if not event_frame.get("event_runtime", {}).get("requires_post_event_relaxation"):
        raise AssertionError("event frame lost requires_post_event_relaxation evidence")
    for frame in post:
        if _events(frame) != expected:
            raise AssertionError("post-event frame rewrote prior topology-event history")
        if frame.get("event_runtime", {}).get("event_ids") != expected_ids:
            raise AssertionError("post-event event ID list does not match topology history")


def _assert_post_frames(event_frame: dict[str, Any], post: list[dict[str, Any]]) -> None:
    if len(post) < 3:
        raise AssertionError("expected at least three post-event transient frames")
    event_time = float(event_frame["simulation_time_s"])
    times = [float(frame["simulation_time_s"]) for frame in post]
    if times[0] != event_time:
        raise AssertionError("first transient continuation frame must start at the event time")
    if any(b <= a for a, b in zip(times, times[1:])):
        raise AssertionError("post-event transient times must increase strictly after the seed frame")
    first_runtime = post[0].get("event_runtime", {})
    if first_runtime.get("post_event_relaxation") != "INITIALIZED_FROM_CONSERVATIVE_RESTART":
        raise AssertionError("first post-event frame is not labeled as the restart seed")
    if first_runtime.get("physical_advancement_after_event"):
        raise AssertionError("restart seed must precede physical advancement")
    for frame in post[1:]:
        runtime = frame.get("event_runtime", {})
        if runtime.get("post_event_relaxation") != "PHYSICALLY_ADVANCED":
            raise AssertionError("later post-event frames must be physically advanced")
        if not runtime.get("physical_advancement_after_event"):
            raise AssertionError("later post-event frame is missing physical advancement evidence")
        provenance = frame.get("manifest", {}).get("provenance", {})
        if provenance.get("post_event_continuation") != PHASE:
            raise AssertionError("post-event transient provenance is missing")


def _assert_geometry_evolves(event_frame: dict[str, Any], post: list[dict[str, Any]]) -> None:
    event_meshes = [
        mesh for mesh in event_frame.get("surface_meshes", [])
        if isinstance(mesh.get("restart_geometry"), dict)
    ]
    if len(event_meshes) != 1:
        raise AssertionError("event frame must expose exactly one conservative restart mesh")
    event_mesh = event_meshes[0]
    seed_mesh = _mesh(post[0], str(event_mesh["id"]))
    if seed_mesh["vertices"] != event_mesh["vertices"]:
        raise AssertionError("first transient frame changed authoritative restart vertices")
    if seed_mesh["faces"] != event_mesh["faces"]:
        raise AssertionError("first transient frame changed authoritative restart faces")
    if post[0].get("diagnostics", {}).get("post_event_relaxation", {}).get(
        "seed_geometry_preserved"
    ) is not True:
        raise AssertionError("restart seed preservation diagnostic is missing")

    initial_signature = (
        seed_mesh["vertex_count"],
        seed_mesh["face_count"],
        tuple(seed_mesh["vertices"]["values"]),
        tuple(seed_mesh["faces"]["values"]),
    )
    changed = False
    for frame in post[1:]:
        mesh = _mesh(frame, str(seed_mesh["id"]))
        signature = (
            mesh["vertex_count"],
            mesh["face_count"],
            tuple(mesh["vertices"]["values"]),
            tuple(mesh["faces"]["values"]),
        )
        if signature != initial_signature:
            changed = True
            break
    if not changed:
        raise AssertionError("transient solver did not evolve the conservative restart geometry")

    metrics = [frame.get("diagnostics", {}).get("post_event_relaxation", {}) for frame in post]
    required = (
        "surface_area_m2",
        "surface_energy_j",
        "bulk_kinetic_energy_j",
        "capillary_excess_energy_j",
        "capillary_excess_ratio_to_seed",
    )
    for metric in metrics:
        for key in required:
            value = metric.get(key)
            if value is None or not math.isfinite(float(value)):
                raise AssertionError(f"missing or non-finite relaxation diagnostic {key}")
    if abs(float(metrics[0]["capillary_excess_ratio_to_seed"]) - 1.0) > 1.0e-12:
        raise AssertionError("restart seed damping metric must be normalized to one")


def _assert_volume(post: list[dict[str, Any]]) -> None:
    target = None
    for frame in post:
        metric = frame.get("diagnostics", {}).get("post_event_relaxation", {})
        current_target = float(metric["target_volume_m3"])
        if target is None:
            target = current_target
        elif current_target != target:
            raise AssertionError("post-event target volume changed across frames")
        if float(metric["volume_relative_error"]) > 5.0e-10:
            raise AssertionError("post-event child volume exceeded transient projection budget")
        if float(frame.get("diagnostics", {}).get("max_relative_volume_error", 0.0)) > 5.0e-10:
            raise AssertionError("transient export reports excessive relative volume error")


def _assert_lineage(event_frame: dict[str, Any], post: list[dict[str, Any]]) -> None:
    coalescence = next(
        (event for event in _events(event_frame) if event.get("type") == "COALESCENCE"),
        None,
    )
    if coalescence is None:
        raise AssertionError("coalescence event is missing")
    lineage = coalescence.get("lineage") or {}
    if len(lineage) != 1:
        raise AssertionError("coalescence must define exactly one child lineage")
    child_id, parents = next(iter(lineage.items()))
    for frame in post:
        runtime = frame.get("event_runtime", {})
        if runtime.get("child_bubble_id") != child_id:
            raise AssertionError("post-event child ID changed")
        if runtime.get("parent_lineage") != parents:
            raise AssertionError("post-event runtime lineage changed")
        child = next((bubble for bubble in frame["bubbles"] if bubble["id"] == child_id), None)
        if child is None or child.get("lineage") != parents:
            raise AssertionError("post-event bubble lineage is not preserved")
        if child.get("status") != "ALIVE":
            raise AssertionError("coalesced child must remain ALIVE during relaxation")


def validate(root: Path, args: argparse.Namespace) -> dict[str, Any]:
    replay = json.loads((root / "replay.json").read_text(encoding="utf-8"))
    frames = _load_frames(root, replay)
    event_frames = [
        frame for frame in frames
        if frame.get("event_runtime", {}).get("phase") == "EVENT"
    ]
    if len(event_frames) != 1:
        raise AssertionError("expected exactly one topology event frame")
    event_frame = event_frames[0]
    post = [
        frame for frame in frames
        if frame.get("event_runtime", {}).get("phase") == PHASE
    ]
    if args.assert_event_history:
        _assert_event_history(event_frame, post)
    if args.assert_post_event_frames:
        _assert_post_frames(event_frame, post)
    if args.assert_geometry_evolves:
        _assert_geometry_evolves(event_frame, post)
    if args.assert_volume:
        _assert_volume(post)
    if args.assert_lineage:
        _assert_lineage(event_frame, post)
    return {
        "event_ids": _event_ids(event_frame),
        "post_event_frames": len(post),
        "first_post_time_s": post[0]["simulation_time_s"] if post else None,
        "last_post_time_s": post[-1]["simulation_time_s"] if post else None,
        "status": "ok",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle")
    parser.add_argument("--assert-event-history", action="store_true")
    parser.add_argument("--assert-post-event-frames", action="store_true")
    parser.add_argument("--assert-geometry-evolves", action="store_true")
    parser.add_argument("--assert-volume", action="store_true")
    parser.add_argument("--assert-lineage", action="store_true")
    args = parser.parse_args()
    result = validate(Path(args.bundle), args)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
