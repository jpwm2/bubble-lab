#!/usr/bin/env python3
"""Run Bubble Lab final validation and emit deterministic JSON/Markdown reports."""
from __future__ import annotations
import argparse,json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from bubblelab.validation.final.wave27_compat import FinalValidationError,build_final_validation,render_markdown
DEFAULT_OUTPUT=ROOT/"bubblelab"/"validation"/"final"/"artifacts"/"final-validation.json"
DEFAULT_REPORT=ROOT/"bubblelab"/"validation"/"final"/"artifacts"/"final-validation.md"

def canonical_json(value:object)->str: return json.dumps(value,indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False)+"\n"
def main()->int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--output",type=Path,default=DEFAULT_OUTPUT); p.add_argument("--report",type=Path,default=DEFAULT_REPORT); p.add_argument("--assert-honest",action="store_true"); p.add_argument("--no-execute",action="store_true",help="assemble static/historical evidence without running current probes"); a=p.parse_args()
    try: result=build_final_validation(execute=not a.no_execute,assert_honest=a.assert_honest)
    except FinalValidationError as exc: print(f"final validation failure: {exc}",file=sys.stderr); return 2
    a.output.parent.mkdir(parents=True,exist_ok=True); a.report.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(canonical_json(result),encoding="utf-8"); a.report.write_text(render_markdown(result),encoding="utf-8")
    print(f"final validation: {result['qualification_status']}; current={result['summary']['current_pass_count']}/{result['summary']['current_probe_count']}; final_acceptance_ready={result['summary']['final_acceptance_ready']}"); return 0
if __name__=="__main__": raise SystemExit(main())
