#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.runtime.bundle import validate_replay_bundle


class BoundaryReplayValidationError(ValueError):
    pass


def _frame(root: Path, ref: dict) -> dict:
    return json.loads((root / ref["path"]).read_text(encoding="utf-8"))


def validate_boundary_replay(
    bundle_dir: str | Path,
    *,
    assert_contact: bool = False,
    assert_no_penetration: bool = False,
    assert_disclosure: bool = False,
) -> dict[str, object]:
    root = Path(bundle_dir)
    replay = validate_replay_bundle(root)
    frames = [_frame(root, ref) for ref in replay["frames"]]
    contacts = []
    configured_ids: set[str] = set()
    active_ids: set[str] = set()
    max_post = 0.0
    max_contact_vertices = 0

    for frame in frames:
        environment = frame.get("environment") or {}
        configured_ids.update(str(value) for value in environment.get("boundary_refs", []))
        diagnostics = (frame.get("diagnostics") or {}).get("solid_boundary_contact")
        if not isinstance(diagnostics, dict):
            raise BoundaryReplayValidationError("frame is missing diagnostics.solid_boundary_contact")
        contacts.append(diagnostics)
        active_ids.update(str(value) for value in diagnostics.get("active_boundary_ids", []))
        max_contact_vertices = max(max_contact_vertices, int(diagnostics.get("contact_vertex_count", 0)))
        max_post = max(max_post, float(diagnostics.get("max_penetration_post_m", 0.0)))

    if assert_contact:
        if max_contact_vertices <= 0:
            raise BoundaryReplayValidationError("no tracked-film solid contact was observed")
        if configured_ids and not active_ids.intersection(configured_ids):
            raise BoundaryReplayValidationError("active contact IDs do not match configured boundary refs")

    if assert_no_penetration:
        tolerance = max(
            (float(entry.get("geometric_tolerance_m", 0.0)) for entry in contacts),
            default=0.0,
        )
        allowed = max(1.0e-12, tolerance * 1.0e-3)
        if max_post > allowed:
            raise BoundaryReplayValidationError(
                f"post-correction solid penetration {max_post:g} m exceeds allowed {allowed:g} m"
            )

    if assert_disclosure:
        disclosures = frames[-1]["manifest"]["feature_disclosures"]
        expected = {
            "solid_boundary_sdf_geometry": "RESOLVED",
            "tracked_film_solid_no_penetration": "RESOLVED",
            "tracked_film_wall_tangential_motion": "MODELED",
            "bulk_solid_wall_no_slip": "NOT_IMPLEMENTED",
            "bulk_solid_fluid_wall_coupling": "NOT_IMPLEMENTED",
        }
        mismatches = {
            key: (disclosures.get(key), value)
            for key, value in expected.items()
            if disclosures.get(key) != value
        }
        if mismatches:
            raise BoundaryReplayValidationError(f"boundary disclosure mismatch: {mismatches}")
        for entry in contacts:
            if entry.get("bulk_eulerian_wall_coupling") != "NOT_IMPLEMENTED_PERIODIC_GRID":
                raise BoundaryReplayValidationError(
                    "bulk Eulerian wall coupling must remain explicitly NOT_IMPLEMENTED_PERIODIC_GRID"
                )

    return {
        "frames": len(frames),
        "configured_boundary_ids": sorted(configured_ids),
        "active_boundary_ids": sorted(active_ids),
        "max_contact_vertex_count": max_contact_vertices,
        "max_penetration_post_m": max_post,
        "disclosure": "validated" if assert_disclosure else "not-requested",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle_dir")
    parser.add_argument("--assert-contact", action="store_true")
    parser.add_argument("--assert-no-penetration", action="store_true")
    parser.add_argument("--assert-disclosure", action="store_true")
    args = parser.parse_args()
    result = validate_boundary_replay(
        args.bundle_dir,
        assert_contact=args.assert_contact,
        assert_no_penetration=args.assert_no_penetration,
        assert_disclosure=args.assert_disclosure,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
