#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from bubblelab.runtime.bundle import validate_replay_bundle
def main():
    p=argparse.ArgumentParser(); p.add_argument("bundle"); a=p.parse_args()
    replay=validate_replay_bundle(a.bundle)
    print(json.dumps({"valid":True,"frames":len(replay["frames"])},sort_keys=True))
if __name__=="__main__": main()
