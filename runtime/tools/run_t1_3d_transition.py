#!/usr/bin/env python3
"""Exercise a genuine-3D T1 event and continue the authoritative transient state."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bubblelab.solvers.transient.network.t1_3d import runtime_transition_evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assert", dest="assert_pass", action="store_true")
    args = parser.parse_args()
    result = runtime_transition_evidence()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if args.assert_pass and not bool(result.get("pass")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
