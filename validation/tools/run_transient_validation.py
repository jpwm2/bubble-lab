#!/usr/bin/env python3
"""Run integrated transient validation and emit deterministic JSON."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from bubblelab.validation.transient_suite import failed_gate_messages, run_validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--assert", dest="assert_mode", action="store_true")
    args = parser.parse_args()

    result = run_validation()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    print(f"transient validation: {'PASS' if result['summary']['passed'] else 'FAIL'}")
    print(f"output: {output}")
    print(f"replay payload sha256: {result['replay_payload_sha256']}")
    for message in failed_gate_messages(result):
        print(f"FAILED GATE: {message}", file=sys.stderr)

    if args.assert_mode and not result["summary"]["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
