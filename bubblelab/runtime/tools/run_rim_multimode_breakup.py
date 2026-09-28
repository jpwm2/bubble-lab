#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from bubblelab.runtime.rim_multimode_breakup_runtime import run_rim_multimode_breakup_runtime

DEFAULT_SCENARIO = ROOT / "bubblelab" / "scenarios" / "runtime" / "rim-multimode-breakup.scenario.json"


def assert_payload(payload):
    events=payload["event_sequence"]
    if [e["type"] for e in events] != ["ASYMMETRIC_RIM_RETRACTION","MULTIMODE_LIGAMENT_ONSET","STATE_DERIVED_DROPLET_DETACHMENT"]: raise AssertionError("runtime did not preserve multimode event sequence")
    if not events[0]["time_s"] < events[1]["time_s"] < events[2]["time_s"]: raise AssertionError("event times are not ordered")
    if float(payload["budgets"]["liquid_volume_relative_error"]) > 1e-12: raise AssertionError("runtime liquid conservation failed")
    if abs(float(payload["budgets"]["radial_momentum_residual_kg_m_s"])) > 1e-12: raise AssertionError("runtime momentum accounting failed")
    seed_modes=payload["rim"]["seed_modes"]
    if len(seed_modes) < 2 or len(payload["droplets"]) in seed_modes: raise AssertionError("runtime did not expose state-derived multimode detachment")
    if len(payload["droplets"]) != len(payload["rim"]["evolved_neck_cells"]): raise AssertionError("droplets are not partitioned from evolved necks")
    if not payload["continuation"]["exact_evolved_velocity_seed"]: raise AssertionError("continuation did not consume evolved velocity")
    ids=[d["id"] for d in payload["droplets"]]
    if len(ids)!=len(set(ids)): raise AssertionError("droplet identities are not unique")
    for drop in payload["droplets"]:
        if float(drop["volume_m3"]) <= 0.0 or not all(math.isfinite(float(v)) for v in drop["velocity_m_s"]): raise AssertionError("invalid detached droplet state")


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("scenario",nargs="?",default=str(DEFAULT_SCENARIO)); parser.add_argument("--assert",dest="assert_result",action="store_true")
    args=parser.parse_args(); scenario=json.loads(Path(args.scenario).read_text(encoding="utf-8")); payload=run_rim_multimode_breakup_runtime(scenario)
    if args.assert_result: assert_payload(payload)
    print(json.dumps(payload,sort_keys=True,indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
