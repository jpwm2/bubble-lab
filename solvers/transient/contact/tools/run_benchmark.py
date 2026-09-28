#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.solvers.transient.contact import form_contact, observe_contact
from bubblelab.solvers.transient.geometry import FilmFront, icosphere


def make_pair(*, subdivisions: int = 2, gap_m: float = 8.0e-4) -> tuple[FilmFront, FilmFront]:
    radius = 1.0e-2
    half_distance = radius + 0.5 * gap_m
    return (
        icosphere(
            radius_m=radius,
            center_m=(-half_distance, 0.0, 0.0),
            subdivisions=subdivisions,
            bubble_id="bubble-a",
            surface_tension_n_m=0.05,
        ),
        icosphere(
            radius_m=radius,
            center_m=(half_distance, 0.0, 0.0),
            subdivisions=subdivisions,
            bubble_id="bubble-b",
            surface_tension_n_m=0.05,
        ),
    )


def translated(front: FilmFront, dx: float) -> FilmFront:
    clone = front.clone()
    clone.vertices = [(x + dx, y, z) for x, y, z in clone.vertices]
    return clone


def approach_contact() -> dict[str, object]:
    initial_gap = 4.5e-3
    step_translation = 2.5e-4
    a0, b0 = make_pair(subdivisions=2, gap_m=initial_gap)
    before_shared = 0
    event = None
    for step in range(20):
        a = translated(a0, step * step_translation)
        b = translated(b0, -step * step_translation)
        observation = observe_contact(a, b)
        if observation.contact:
            formed = form_contact(a, b)
            event = {
                "step": step,
                "time_s": step * 1.0e-3,
                "separation_m": observation.separation_metric_m,
                "threshold_m": observation.threshold_m,
                "shared_films": sum(
                    patch.adjacent == ("bubble-a", "bubble-b")
                    for patch in formed.network.patches
                ),
                "shared_dofs": formed.state.shared_dof_count(),
                "ring_points": len(formed.contact_ring_points_m),
                "topology_signature": repr(formed.state.topology_signature()),
            }
            break
    if event is None:
        raise AssertionError("approach driver did not reach the contact criterion")
    a = translated(a0, event["step"] * step_translation)
    b = translated(b0, -event["step"] * step_translation)
    repeated = form_contact(a, b)
    repeat = {
        "step": event["step"],
        "topology_signature": repr(repeated.state.topology_signature()),
        "ring_points": len(repeated.contact_ring_points_m),
    }
    return {
        "benchmark": "approach-contact",
        "before_shared_films": before_shared,
        "event": event,
        "repeat": repeat,
    }


def shared_film_seed() -> dict[str, object]:
    a, b = make_pair()
    result = form_contact(a, b)
    shared = [
        patch.id
        for patch in result.network.patches
        if patch.adjacent == ("bubble-a", "bubble-b")
    ]
    return {
        "benchmark": "shared-film-seed",
        "parent_ids": list(result.observation.parent_ids),
        "shared_film_ids": shared,
        "junction_ids": [junction.id for junction in result.network.junctions],
        "ring_points": len(result.contact_ring_points_m),
        "shared_dofs": result.state.shared_dof_count(),
        "film_ids": list(result.state.topology.film_ids),
    }


def conservation() -> dict[str, object]:
    a, b = make_pair()
    result = form_contact(a, b)
    return {
        "benchmark": "conservation",
        "raw_relative_volume_errors": dict(result.raw_relative_volume_errors),
        "projected_relative_volume_errors": dict(result.projected_relative_volume_errors),
        "budget": result.local_volume_budget_fraction,
        "target_volumes": {
            region.id: region.target_volume_m3 for region in result.network.regions
        },
        "projected_volumes": {
            region.id: result.network.region_volume(region.id)
            for region in result.network.regions
        },
    }


def replay() -> dict[str, object]:
    a, b = make_pair()
    first = form_contact(a, b)
    second = form_contact(a, b)
    thresholds = []
    resolutions = []
    for subdivisions in (1, 2, 3):
        ra, rb = make_pair(subdivisions=subdivisions, gap_m=5.0e-3)
        observation = observe_contact(ra, rb)
        thresholds.append(observation.threshold_m)
        resolutions.append(observation.resolution_m)
    return {
        "benchmark": "replay",
        "identical": first.signature() == second.signature(),
        "signature": repr(first.signature()),
        "refinement_thresholds_m": thresholds,
        "refinement_resolution_m": resolutions,
    }


def assert_result(name: str, result: dict[str, object]) -> None:
    if name == "approach-contact":
        event = result["event"]
        repeat = result["repeat"]
        assert result["before_shared_films"] == 0
        assert event["step"] > 0
        assert event["shared_films"] == 1
        assert event["shared_dofs"] == event["ring_points"]
        assert event["topology_signature"] == repeat["topology_signature"]
        assert event["ring_points"] == repeat["ring_points"]
    elif name == "shared-film-seed":
        assert len(result["shared_film_ids"]) == 1
        assert len(result["junction_ids"]) == 1
        assert result["shared_dofs"] == result["ring_points"]
        assert result["ring_points"] >= 5
    elif name == "conservation":
        assert max(result["raw_relative_volume_errors"].values()) <= result["budget"]
        assert max(result["projected_relative_volume_errors"].values()) < 3.0e-9
    elif name == "replay":
        assert result["identical"]
        thresholds = result["refinement_thresholds_m"]
        assert thresholds[0] > thresholds[1] > thresholds[2]
        ratios = [thresholds[i + 1] / thresholds[i] for i in range(2)]
        assert all(0.35 < ratio < 0.75 for ratio in ratios)
    else:
        raise AssertionError(name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "benchmark",
        choices=("approach-contact", "shared-film-seed", "conservation", "replay"),
    )
    parser.add_argument("--assert", dest="do_assert", action="store_true")
    args = parser.parse_args()
    functions = {
        "approach-contact": approach_contact,
        "shared-film-seed": shared_film_seed,
        "conservation": conservation,
        "replay": replay,
    }
    result = functions[args.benchmark]()
    if args.do_assert:
        assert_result(args.benchmark, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
