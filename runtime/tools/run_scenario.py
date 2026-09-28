#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from bubblelab.runtime import run_scenario

def main():
    p=argparse.ArgumentParser()
    p.add_argument("scenario")
    p.add_argument("--backend",required=True,choices=["equilibrium","transient","thinfilm","thinfilm-events","transient-network"])
    p.add_argument("--output",required=True)
    p.add_argument("--frames",type=int,default=4)
    a=p.parse_args()
    scenario=json.loads(Path(a.scenario).read_text(encoding="utf-8"))
    replay=run_scenario(scenario,a.backend,a.output,a.frames)
    print(json.dumps({"output":a.output,"frames":len(replay["frames"]),"backend":a.backend},sort_keys=True))

if __name__=="__main__": main()
