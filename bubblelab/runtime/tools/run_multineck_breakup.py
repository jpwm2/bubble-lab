#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from bubblelab.runtime.multineck_breakup_runtime import run_multineck_breakup_runtime


DEFAULT_SCENARIO = REPO / "bubblelab/scenarios/runtime/multineck-breakup-3d.scenario.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument("--assert", dest="assert_mode", action="store_true")
    args = parser.parse_args()
    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    report = run_multineck_breakup_runtime(scenario)
    if args.assert_mode:
        assert report["status"] == "PASS"
        assert report["geometry"]["noncoplanarity"] > 0.15
        assert len(report["event_sequence"]) >= 2
        assert report["interaction"]["max_relative_event_time_shift"] >= 0.02
        assert report["budgets"]["liquid_volume_relative_error"] <= 1.0e-12
        assert report["budgets"]["max_transaction_relative_error"] <= 1.0e-12
        assert len(report["fragments"]) == len(report["event_sequence"])
        assert report["continuation"]["stable_lineage"]
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
