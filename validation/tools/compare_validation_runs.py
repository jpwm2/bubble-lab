#!/usr/bin/env python3
"""Compare validation results for exact deterministic equality."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def first_difference(left: Any, right: Any, path: str = "$") -> str | None:
    if type(left) is not type(right):
        return f"{path}: type {type(left).__name__} != {type(right).__name__}"
    if isinstance(left, dict):
        left_keys = set(left)
        right_keys = set(right)
        if left_keys != right_keys:
            return f"{path}: keys differ: {sorted(left_keys ^ right_keys)}"
        for key in sorted(left):
            difference = first_difference(left[key], right[key], f"{path}.{key}")
            if difference:
                return difference
        return None
    if isinstance(left, list):
        if len(left) != len(right):
            return f"{path}: length {len(left)} != {len(right)}"
        for index, (left_value, right_value) in enumerate(zip(left, right)):
            difference = first_difference(left_value, right_value, f"{path}[{index}]")
            if difference:
                return difference
        return None
    if left != right:
        return f"{path}: {left!r} != {right!r}"
    return None


def compare_results(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    difference = first_difference(left, right)
    return {
        "same": difference is None,
        "difference": difference,
        "left_replay_payload_sha256": left.get("replay_payload_sha256"),
        "right_replay_payload_sha256": right.get("replay_payload_sha256"),
        "left_passed": bool(left.get("summary", {}).get("passed")),
        "right_passed": bool(right.get("summary", {}).get("passed")),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("left")
    parser.add_argument("right")
    parser.add_argument("--assert", "--assert-exact", dest="assert_mode", action="store_true")
    args = parser.parse_args()

    left = json.loads(Path(args.left).read_text(encoding="utf-8"))
    right = json.loads(Path(args.right).read_text(encoding="utf-8"))
    comparison = compare_results(left, right)
    print(json.dumps(comparison, indent=2, sort_keys=True))

    failed = (
        not comparison["same"]
        or not comparison["left_passed"]
        or not comparison["right_passed"]
    )
    if args.assert_mode and failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
