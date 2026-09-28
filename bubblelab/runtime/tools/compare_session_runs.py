#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _snapshot(root: Path) -> dict[str, str]:
    if not root.is_dir():
        raise ValueError(f"not a session bundle directory: {root}")
    result: dict[str, str] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        result[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_a")
    parser.add_argument("run_b")
    parser.add_argument("--assert-exact", action="store_true")
    args = parser.parse_args()

    a = _snapshot(Path(args.run_a))
    b = _snapshot(Path(args.run_b))
    exact = a == b
    changed = sorted(set(a) | set(b))
    changed = [path for path in changed if a.get(path) != b.get(path)]
    result = {"exact": exact, "different_files": changed}
    print(json.dumps(result, sort_keys=True))
    if args.assert_exact and not exact:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
