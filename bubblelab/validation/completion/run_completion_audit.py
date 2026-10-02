#!/usr/bin/env python3
"""Generate deterministic JSON and Markdown completion-gap reports."""
from __future__ import annotations
import argparse,json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from bubblelab.validation.completion.wave27_audit import AuditIntegrityError,build_audit,render_markdown
DEFAULT_OUTPUT=ROOT/"bubblelab"/"validation"/"completion"/"artifacts"/"completion-audit.json"
DEFAULT_REPORT=ROOT/"bubblelab"/"validation"/"completion"/"artifacts"/"completion-audit.md"

def canonical_json(value:object)->str: return json.dumps(value,indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False)+"\n"
def main()->int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--output",type=Path,default=DEFAULT_OUTPUT); p.add_argument("--report",type=Path,default=DEFAULT_REPORT); p.add_argument("--assert-honest",action="store_true"); a=p.parse_args()
    try: audit=build_audit(assert_honest=a.assert_honest)
    except AuditIntegrityError as exc: print(f"completion audit integrity failure: {exc}",file=sys.stderr); return 2
    a.output.parent.mkdir(parents=True,exist_ok=True); a.report.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(canonical_json(audit),encoding="utf-8"); a.report.write_text(render_markdown(audit),encoding="utf-8")
    s=audit["summary"]; print(f"audited {s['requirement_count']} requirements: {s['satisfied_count']} satisfied, {len(s['incomplete_requirement_ids'])} incomplete; final_acceptance_ready={s['final_acceptance_ready']}"); return 0
if __name__=="__main__": raise SystemExit(main())
