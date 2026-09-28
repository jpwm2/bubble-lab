#!/usr/bin/env python3
"""Validate every deterministic Bubble Lab contract fixture."""
from __future__ import annotations
import json
import sys
from pathlib import Path

PYTHON_ROOT=Path(__file__).resolve().parents[1]
REPO_ROOT=Path(__file__).resolve().parents[3]
FIXTURE_ROOT=REPO_ROOT/"bubblelab"/"scenarios"/"fixtures"
sys.path.insert(0,str(PYTHON_ROOT))

from bubblelab_contract import ContractValidationError,canonical_json,parse_document

def main() -> int:
    paths=sorted(FIXTURE_ROOT.glob("*.json"))
    if not paths:
        print("No contract fixtures found.",file=sys.stderr)
        return 2
    failed=False
    for path in paths:
        try:
            raw=json.loads(path.read_text(encoding="utf-8"))
            document=parse_document(raw)
            round_trip=json.loads(canonical_json(document.to_dict()))
            if round_trip!=raw:
                raise ContractValidationError("round-trip changed serialized meaning")
            print(f"PASS {path.relative_to(REPO_ROOT)}")
        except (ValueError,KeyError,TypeError,json.JSONDecodeError) as exc:
            failed=True
            print(f"FAIL {path.relative_to(REPO_ROOT)}: {exc}",file=sys.stderr)
    return 1 if failed else 0

if __name__=="__main__":
    raise SystemExit(main())
