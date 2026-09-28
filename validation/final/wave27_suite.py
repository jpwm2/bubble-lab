"""Post-Wave-27 final validation preserving bounded accepted claims."""
from __future__ import annotations
from typing import Any
from bubblelab.validation.completion.wave27_audit import build_audit
from . import suite as runner
from . import wave25_suite as previous

FinalValidationError = runner.FinalValidationError
CURRENT_PROBES = previous.CURRENT_PROBES
HISTORICAL_EVIDENCE = previous.HISTORICAL_EVIDENCE + (
    {"name":"wave27-multievent-topology-gas-network","task_id":"bubble-multievent-topology-gas-network-foundation","checks":("gas-network-unit","multievent-sequence","multievent-dependence","multievent-conservation","multievent-transport-rebuild","multievent-replay","runtime-e2e","runtime-regression","no-placeholders"),"reason":"Bounded ten-to-nine-region continuous history with four causally dependent production T1 transactions plus one topology-enabled rupture/coalescence transaction; unrestricted topology surgery is not inferred."},
    {"name":"wave27-3d-multineck-breakup","task_id":"bubble-3d-multineck-breakup-foundation","checks":("all assignment acceptance steps submitted by the canonical AI Runner request passed",),"reason":"Bounded genuinely non-coplanar interacting multi-neck class with conservative production detachments and deterministic replay; unrestricted singular/turbulent spray physics is not inferred."},
    {"name":"wave27-liquid-border-global-cfd","task_id":"bubble-liquid-border-global-cfd-foundation","checks":("canonical-revalidation",),"reason":"Bounded field-coupled 3D liquid-border state with redistribution, Eulerian pressure/viscous feedback and real T1 surgery; universal singular Plateau-border CFD and arbitrary fluids/scales are not inferred."},
)
CLAIM_BOUNDARIES = (
    "Wave-27 multi-event topology/gas evidence is limited to one continuous ten-to-nine-region history with four causally dependent production T1 transactions plus one topology-enabled rupture/coalescence transaction, exact graph rebuild, <=1e-12 conservation and deterministic replay; unrestricted topology surgery and universal multiphase CFD are not claimed.",
    "Wave-27 3D breakup evidence is limited to the accepted genuinely non-coplanar interacting multi-neck class with conservative production detachments, lineage and replay; unrestricted singular ligament pinch-off, turbulence, secondary aerodynamic breakup and universal spray CFD are not claimed.",
    "Wave-27 liquid-border/global-CFD evidence is limited to the accepted field-coupled 3D liquid-border state with redistribution, Eulerian pressure/viscous feedback and real T1 surgery; universal singular Plateau-border CFD and arbitrary fluids/scales are not claimed.",
    *previous.CLAIM_BOUNDARIES,
)
SMALLEST_BLOCKING_GAPS = (
    {"priority":"physical validity","requirement_ids":["R1","R10","R11","R35","R38","R39"],"gap":"Wave 27 materially strengthens bounded topology/gas, non-coplanar breakup and liquid-border/global-CFD evidence, but arbitrary topology/contact classes, unrestricted singular breakup/spray, universal multiphase/singular-border CFD, deforming walls and arbitrary coupled live surgery remain outside accepted evidence.","recommended_task_boundary":"Advance one unrestricted physical class at a time with causality, conservation, constitutive-response, refinement and replay evidence."},
    {"priority":"numerical stability","requirement_ids":["R10","R11","R35","R39"],"gap":"Accepted bounded Wave-27 classes carry conservation/refinement/replay gates, while unrestricted topology/contact/singular-CFD/general-breakup classes lack production stability qualification.","recommended_task_boundary":"Require convergence/refinement, bounded conservation/traction error, causal sensitivity and deterministic replay for every broader class."},
    {"priority":"state/conservation/reproducibility","requirement_ids":["R30","R38","R39"],"gap":"Wave-27 bounded histories preserve identity, conservation and replay, but cross-version checkpoint portability, complete reusable scenario breadth and arbitrary surgery through coupled topology states remain unsupported.","recommended_task_boundary":"Extend state schemas and transactions only with exact conservation, stable identity and deterministic restart evidence."},
    {"priority":"runtime control","requirement_ids":["R20","R30"],"gap":"Additional qualified high-end slices exist, but every requested high-end solver-control/runtime combination and complete reusable scenario family are not exposed.","recommended_task_boundary":"Map only runnable controls and scenarios into the authoritative runtime with executable capability evidence."},
    {"priority":"visualization","requirement_ids":["R28","R38"],"gap":"Physical iPhone Safari/device-GPU/native multi-touch qualification is not archived; engine-level mobile evidence does not satisfy the direct real-device requirement.","recommended_task_boundary":"Run the documented viewer/control flow on physical iPhone Safari and archive render, input and device metadata."},
    {"priority":"performance","requirement_ids":["R28","R35","R39"],"gap":"Physical-iPhone GPU/thermal behavior and unrestricted Maximum-Realism throughput remain unqualified because those device/general physics scopes are not evidenced.","recommended_task_boundary":"Benchmark only after the corresponding real-device or unrestricted high-fidelity path exists."},
)

def honesty_issues(completion:dict[str,Any]|None=None)->list[str]:
    audit=completion or build_audit(assert_honest=True)
    issues=[]
    rows={r["requirement_id"]:r for r in audit["rows"]}
    for rid in ("R1","R10","R11","R20","R30","R35","R38","R39"):
        if rows[rid]["status"]!="PARTIAL": issues.append(f"{rid} must remain PARTIAL after bounded Wave-27 evidence")
    if rows["R28"]["status"]!="UNVERIFIED": issues.append("R28 physical iPhone qualification must remain UNVERIFIED")
    return issues

def build_final_validation(*,execute:bool=True,assert_honest:bool=False)->dict[str,Any]:
    completion=build_audit(assert_honest=True); static_issues=honesty_issues(completion)
    historical=[runner._historical_record(s) for s in HISTORICAL_EVIDENCE]
    if execute:
        current=[runner._run_probe(s) for s in CURRENT_PROBES]; executable_passed=all(x["result"]=="PASS" for x in current); qualification_status="PASS_WITH_DECLARED_GAPS" if executable_passed else "FAIL"
    else:
        current=[{"name":s["name"],"coverage":s["coverage"],"execution":"CURRENT","command":s["command"],"result":"NOT_RUN"} for s in CURRENT_PROBES]; executable_passed=False; qualification_status="NOT_RUN"
    historical_passed=all(x["result"]=="PASS" for x in historical); validation_passed=execute and executable_passed and historical_passed and not static_issues
    ready=bool(completion["summary"]["final_acceptance_ready"]) and validation_passed
    result={"schema_version":8,"validation":"bubble-lab-final-validation","baseline":"post-wave-27 accepted main","qualification_status":qualification_status,"current_execution":current,"accepted_historical_evidence":historical,"completion_audit_summary":completion["summary"],"claim_boundaries":list(CLAIM_BOUNDARIES),"smallest_blocking_gaps":list(SMALLEST_BLOCKING_GAPS),"honesty_issues":static_issues,"summary":{"current_probe_count":len(current),"current_pass_count":sum(x["result"]=="PASS" for x in current),"historical_evidence_count":len(historical),"historical_pass_count":sum(x["result"]=="PASS" for x in historical),"validation_passed":validation_passed,"final_acceptance_ready":ready,"final_acceptance_reason":completion["summary"]["final_acceptance_reason"]}}
    if assert_honest:
        failures=[x["name"] for x in current if x["result"]=="FAIL"]; historical_failures=[x["name"] for x in historical if x["result"]!="PASS"]; messages=list(static_issues)
        if failures: messages.append("current executable failures: "+", ".join(failures))
        if historical_failures: messages.append("accepted evidence failures: "+", ".join(historical_failures))
        if messages: raise FinalValidationError("; ".join(messages))
    return result

def render_markdown(result:dict[str,Any])->str:
    s=result["summary"]; lines=["# Bubble Lab Final Validation","",f"Qualification status: **{result['qualification_status']}**",f"Current probes passed: **{s['current_pass_count']}/{s['current_probe_count']}**",f"Accepted historical evidence passed: **{s['historical_pass_count']}/{s['historical_evidence_count']}**",f"Final acceptance ready: **{'yes' if s['final_acceptance_ready'] else 'no'}**",f"Reason: {s['final_acceptance_reason']}","","## Current execution","","| Probe | Coverage | Result |","|---|---|---|"]
    lines += [f"| {x['name']} | {x['coverage']} | {x['result']} |" for x in result["current_execution"]]
    lines += ["","## Accepted historical executable evidence","","| Evidence | Source | Result |","|---|---|---|"]+[f"| {x['name']} | `{x['source']}` | {x['result']} |" for x in result["accepted_historical_evidence"]]
    lines += ["","## Smallest blocking gaps",""]+[f"- **{x['priority']} — {', '.join(x['requirement_ids'])}** — {x['gap']} Recommended boundary: {x['recommended_task_boundary']}" for x in result["smallest_blocking_gaps"]]
    lines += ["","## Claim boundaries retained",""]+[f"- {x}" for x in result["claim_boundaries"]]
    c=result["completion_audit_summary"]; lines += ["","## Completion audit summary","",f"- Requirements: {c['requirement_count']}",f"- Post-Wave-25 SATISFIED/PARTIAL/UNVERIFIED: {c['previous_status_counts']['SATISFIED']}/{c['previous_status_counts']['PARTIAL']}/{c['previous_status_counts']['UNVERIFIED']}",f"- Post-Wave-27 SATISFIED/PARTIAL/UNVERIFIED: {c['status_counts']['SATISFIED']}/{c['status_counts']['PARTIAL']}/{c['status_counts']['UNVERIFIED']}",f"- Status changes: {', '.join(x['requirement_id'] for x in c['status_changes']) or 'none'}",f"- Final acceptance ready from R1-R39 matrix: {'yes' if c['final_acceptance_ready'] else 'no'}"]
    return "\n".join(lines).rstrip()+"\n"
