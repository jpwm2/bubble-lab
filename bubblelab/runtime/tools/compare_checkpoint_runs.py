#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _first_difference(a, b, path: str = "$") -> str | None:
    if type(a) is not type(b):
        return f"{path}: type {type(a).__name__} != {type(b).__name__}"
    if isinstance(a, dict):
        if set(a) != set(b):
            missing = sorted(set(a) - set(b))
            extra = sorted(set(b) - set(a))
            return f"{path}: keys differ missing={missing} extra={extra}"
        for key in sorted(a):
            diff = _first_difference(a[key], b[key], f"{path}.{key}")
            if diff is not None:
                return diff
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: length {len(a)} != {len(b)}"
        for index, (left, right) in enumerate(zip(a, b)):
            diff = _first_difference(left, right, f"{path}[{index}]")
            if diff is not None:
                return diff
        return None
    if a != b:
        return f"{path}: {a!r} != {b!r}"
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    parser.add_argument("--assert-exact", action="store_true")
    args = parser.parse_args()

    root = Path(args.output)
    uninterrupted = json.loads((root / "uninterrupted-state.json").read_text(encoding="utf-8"))
    restarted = json.loads((root / "restarted-state.json").read_text(encoding="utf-8"))
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    difference = _first_difference(uninterrupted, restarted)
    exact = difference is None and bool(summary.get("fresh_process_restart"))
    result = {
        "exact": exact,
        "fresh_process_restart": bool(summary.get("fresh_process_restart")),
        "parent_pid": summary.get("parent_pid"),
        "restart_pid": summary.get("restart_pid"),
        "difference": difference,
        "uninterrupted_digest": summary.get("uninterrupted_digest"),
        "restarted_digest": summary.get("restarted_digest"),
    }
    print(json.dumps(result, sort_keys=True))
    if args.assert_exact and not exact:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
