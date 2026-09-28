"""Post-Wave-27 R1-R39 completion audit."""
from __future__ import annotations
from contextlib import contextmanager
from typing import Any, Iterator
from . import audit as legacy
from .wave25_catalog import CATALOG as WAVE25_CATALOG
from .wave27_catalog import CATALOG as WAVE27_CATALOG
AuditIntegrityError=legacy.AuditIntegrityError
STATUS_VOCABULARY=legacy.STATUS_VOCABULARY

@contextmanager
def _ctx()->Iterator[None]:
    old,base=legacy.CATALOG,legacy.WAVE15_CATALOG
    legacy.CATALOG,legacy.WAVE15_CATALOG=WAVE27_CATALOG,WAVE25_CATALOG
    try: yield
    finally: legacy.CATALOG,legacy.WAVE15_CATALOG=old,base

def _honesty()->list[str]:
    issues=[]
    status=lambda r:str(WAVE27_CATALOG[r]["status"])
    feature=lambda r,n:str(WAVE27_CATALOG[r]["features"].get(n))
    for r in ("R1","R13","R35","R38","R39"):
        if feature(r,"bounded_multievent_topology_gas_network")!="MODELED": issues.append(f"{r} must keep Wave-27 multi-event topology/gas evidence bounded MODELED")
    for r in ("R1","R10","R16","R35","R38","R39"):
        if feature(r,"bounded_3d_interacting_multineck_breakup")!="MODELED": issues.append(f"{r} must keep Wave-27 3D multi-neck evidence bounded MODELED")
    for r in ("R1","R10","R11","R20","R35","R38","R39"):
        if feature(r,"bounded_field_coupled_liquid_border_global_cfd")!="MODELED": issues.append(f"{r} must keep Wave-27 liquid-border/global-CFD evidence bounded MODELED")
    for r in ("R1","R10","R11","R20","R30","R35","R38","R39"):
        if status(r)!="PARTIAL": issues.append(f"{r} must remain PARTIAL unless broader evidence closes its full requirement")
    if status("R28")!="UNVERIFIED": issues.append("R28 must remain UNVERIFIED without physical iPhone Safari evidence")
    return issues

def integrity_issues(*,assert_honest:bool=False)->list[str]:
    with _ctx(): issues=legacy.integrity_issues(assert_honest=assert_honest)
    if assert_honest: issues.extend(_honesty())
    return issues

def build_audit(*,assert_honest:bool=False)->dict[str,Any]:
    issues=integrity_issues(assert_honest=assert_honest)
    if issues: raise AuditIntegrityError("; ".join(issues))
    with _ctx(): result=legacy.build_audit(assert_honest=False)
    result["schema_version"]=9
    result["baseline"]="post-wave-27 accepted main"
    result["previous_baseline"]="post-wave-25 accepted main / Wave-25 completion audit"
    result["summary"]["known_blockers"]=[
      "physical iPhone Safari/device-GPU/native hardware multi-touch qualification",
      "arbitrary/unlimited topology surgery beyond the accepted bounded multi-event history",
      "unrestricted singular 3D breakup, broad spray, turbulence and secondary breakup",
      "universal arbitrary-fluid/scale multiphase Navier-Stokes and singular Plateau-border CFD",
      "arbitrary/deforming moving-wall CFD and arbitrary coupled live topology surgery",
      "cross-version checkpoint portability, complete reusable scenario breadth and remaining high-end runtime-control combinations",
    ]
    return result

def render_markdown(audit:dict[str,Any])->str:
    s=audit["summary"]
    lines=["# Bubble Lab R1-R39 Completion Gap Audit","","Deterministic post-Wave-27 evidence-only re-audit; bounded foundations are not generalized beyond measured scope.","",f"Requirements audited: **{s['requirement_count']}**",f"Satisfied: **{s['satisfied_count']}**",f"Final acceptance ready: **{'yes' if s['final_acceptance_ready'] else 'no'}**",f"Reason: {s['final_acceptance_reason']}","","## Status changes from post-Wave-25",""]
    if not s["status_changes"]: lines.append("- None.")
    for c in s["status_changes"]: lines.append(f"- **{c['requirement_id']}**: {c['from']} -> {c['to']}")
    lines += ["","## Remaining PARTIAL / UNVERIFIED",""]
    for row in audit["rows"]:
        if row["status"]!="SATISFIED": lines.append(f"- **{row['requirement_id']} — {row['status']}**: {row['gap']}")
    lines += ["","## Known blockers",""]+[f"- {x}" for x in s["known_blockers"]]
    return "\n".join(lines).rstrip()+"\n"
