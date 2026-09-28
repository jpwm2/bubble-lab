"""Post-Wave-23 final validation suite preserving the historical Wave-21 suite."""
from __future__ import annotations

from typing import Any

from bubblelab.validation.completion.wave23_audit import build_audit
from . import suite as runner
from . import wave21_suite as previous

FinalValidationError = runner.FinalValidationError

CURRENT_PROBES: tuple[dict[str, Any], ...] = previous.CURRENT_PROBES + (
    {
        "name": "asymmetric-multimode-rim-breakup",
        "coverage": "bounded asymmetric single-hole reduced rim with simultaneous modes and state-derived conservative droplet handoff",
        "command": "python3 bubblelab/runtime/tools/run_rim_multimode_breakup.py --assert",
        "timeout": 900,
    },
    {
        "name": "dynamic-plateau-border-t1",
        "coverage": "bounded dynamic reduced-order Plateau-border/liquid-border state coupled into one four-region T1",
        "command": "python3 bubblelab/runtime/tools/run_plateau_border_t1.py --assert",
        "timeout": 900,
    },
    {
        "name": "strong-t1-through-global-cfd",
        "coverage": "bounded strongly coupled four-region T1 on one authoritative Eulerian field with material resolved-traction timing feedback",
        "command": "python3 bubblelab/runtime/tools/run_t1_strong_global_cfd.py --assert",
        "timeout": 1200,
    },
)

HISTORICAL_EVIDENCE: tuple[dict[str, Any], ...] = previous.HISTORICAL_EVIDENCE + (
    {
        "name": "wave23-asymmetric-multimode-rim-breakup",
        "task_id": "bubble-asymmetric-multimode-rim-breakup-foundation",
        "checks": (
            "asymmetric-retraction",
            "mode-competition",
            "liquid-conservation",
            "constitutive-response",
            "breakup-refinement",
            "deterministic-replay",
            "runtime-handoff",
        ),
        "reason": "Consumed only for one scaled polar-asymmetric thin-film hole with a conservative reduced rim carrying simultaneous modes 7 and 10; arbitrary 3D multi-hole/singular/broad-spray physics is not inferred.",
    },
    {
        "name": "wave23-dynamic-plateau-border-t1",
        "task_id": "bubble-plateau-border-hydrodynamics-foundation",
        "checks": (
            "border-force-balance",
            "border-conservation",
            "border-response",
            "border-refinement",
            "t1-coupling",
            "runtime-e2e",
        ),
        "reason": "Consumed only for the isolated four-region reduced-order liquid-border class with two conserved control volumes; it is not singular Plateau-border Navier-Stokes CFD.",
    },
    {
        "name": "wave23-strong-t1-global-cfd",
        "task_id": "bubble-strongly-coupled-t1-global-cfd-foundation",
        "checks": (
            "strong-feedback",
            "strong-conservation",
            "strong-refinement",
            "strong-symmetry",
            "runtime-e2e",
        ),
        "reason": "Consumed only for the declared non-coplanar four-region high-viscosity exterior-liquid regime with one authoritative Eulerian field, resolved traction timing feedback and same-field continuation.",
    },
)

CLAIM_BOUNDARIES = (
    "Wave-23 asymmetric breakup is accepted only for one polar-asymmetric thin-film hole with one conservative reduced rim and simultaneous modes 7 and 10; arbitrary 3D multi-hole interaction, singular ligament pinch-off, broadband spray statistics, turbulent atomization, secondary breakup and deforming post-detachment droplet CFD are unsupported.",
    "Wave-23 dynamic Plateau-border hydrodynamics is accepted only as a reduced-order local two-control-volume liquid-border model for one isolated four-region curvilinear 3D T1; it is not resolved singular Plateau-border Navier-Stokes CFD or unrestricted arbitrary 3D T1 hydrodynamics.",
    "Wave-23 strong T1/global-CFD coupling is accepted only for the declared isolated four-region non-coplanar high-viscosity exterior-liquid regime; the measured >=5% timing feedback is not a universal multiphase-CFD claim.",
    *previous.CLAIM_BOUNDARIES,
)

SMALLEST_BLOCKING_GAPS = (
    {
        "priority": "physical validity",
        "requirement_ids": ["R1", "R10", "R11", "R35", "R38", "R39"],
        "gap": "Wave 23 materially strengthens bounded breakup, liquid-border and strong-CFD coupling evidence, but unrestricted repeated topology-changing gas-film coupling, arbitrary-contact universal multiphase/singular-border CFD, unrestricted continuum/singular 3D T1, arbitrary 3D multi-hole/multi-neck breakup with broad spray physics, deforming walls and arbitrary coupled live surgery remain outside accepted evidence.",
        "recommended_task_boundary": "Advance one remaining unrestricted physical class at a time with independent field, conservation, constitutive-response, reference, refinement and runtime evidence; do not promote bounded Wave-23 subclasses to universal physics.",
    },
    {
        "priority": "numerical stability",
        "requirement_ids": ["R10", "R11", "R35", "R39"],
        "gap": "Wave-23 bounded classes carry conservation/refinement, symmetry or deterministic evidence, but the still-unimplemented unrestricted topology/contact/singular-CFD/general-breakup classes necessarily lack production stability qualification.",
        "recommended_task_boundary": "For any broader class, require convergence/refinement, bounded conservation error, deterministic replay and stability gates before integration claims move.",
    },
    {
        "priority": "state/conservation/reproducibility",
        "requirement_ids": ["R30", "R38", "R39"],
        "gap": "Supported Wave-23 handoffs preserve deterministic state and conservation, but cross-version checkpoint portability, the complete reusable many-bubble/network scenario family and arbitrary live surgery through already-coupled topology states remain unsupported.",
        "recommended_task_boundary": "Extend state schemas and topology transactions only where exact conservation, stable identity and deterministic restart can be demonstrated.",
    },
    {
        "priority": "runtime control",
        "requirement_ids": ["R20", "R30"],
        "gap": "The canonical product now has another qualified high-end strong-CFD runtime slice, but it still does not expose every requested high-end solver-control/runtime combination and the reusable many-bubble/network scenario family remains incomplete.",
        "recommended_task_boundary": "Map only runnable high-end controls and scenarios into the authoritative runtime, with capability declarations tied to executable backend combinations.",
    },
    {
        "priority": "visualization",
        "requirement_ids": ["R28", "R38"],
        "gap": "Physical iPhone Safari/device-GPU/native multi-touch qualification is not archived; current mobile evidence remains engine-level rather than real-device qualification.",
        "recommended_task_boundary": "Run the documented viewer/control flow on physical iPhone Safari or equivalent credible real-device evidence and archive render, input and device metadata.",
    },
    {
        "priority": "performance",
        "requirement_ids": ["R28", "R35", "R39"],
        "gap": "No accepted-class performance blocker is established by this audit, but physical-iPhone GPU/thermal behavior and unrestricted Maximum-Realism throughput remain unqualified because those device/general physics scopes are not yet evidenced.",
        "recommended_task_boundary": "Benchmark only after the corresponding real-device or unrestricted high-fidelity path exists, preserving physics and stability gates ahead of optimization.",
    },
)


def honesty_issues(completion: dict[str, Any] | None = None) -> list[str]:
    audit = completion or build_audit(assert_honest=True)
    issues = previous.honesty_issues(audit)
    rows = {row["requirement_id"]: row for row in audit["rows"]}

    r16 = rows["R16"]["features"]
    if r16.get("bounded_asymmetric_multimode_rim_breakup") != "MODELED":
        issues.append("Wave-23 asymmetric multimode rim breakup must remain a bounded MODELED class")
    if r16.get("state_derived_multimode_droplet_handoff") != "RESOLVED":
        issues.append("Wave-23 state-derived multimode droplet handoff must remain RESOLVED")

    r11 = rows["R11"]["features"]
    if r11.get("bounded_dynamic_plateau_border_hydrodynamics") != "MODELED":
        issues.append("Wave-23 dynamic Plateau-border hydrodynamics must remain a bounded MODELED class")
    if r11.get("bounded_strongly_coupled_t1_global_cfd") != "MODELED":
        issues.append("Wave-23 strong T1/global-CFD coupling must remain a bounded MODELED class")
    if r11.get("bounded_causal_cfd_t1_timing_feedback") != "MODELED":
        issues.append("Wave-23 causal CFD timing feedback must remain bounded MODELED evidence")

    r38 = rows["R38"]["features"]
    for name in (
        "bounded_asymmetric_multimode_rim_breakup",
        "bounded_dynamic_plateau_border_hydrodynamics",
        "bounded_strongly_coupled_t1_global_cfd",
        "bounded_causal_cfd_t1_timing_feedback",
    ):
        if r38.get(name) != "MODELED":
            issues.append(f"R38 Wave-23 supported physical model must remain MODELED: {name}")
    for name in (
        "global_full_domain_multiregion_cfd",
        "arbitrary_multigap_manybubble_t1_cfd",
        "t1_through_global_cfd",
        "overlapping_immersed_supports",
        "general_3d_t1",
        "unrestricted_topology_changing_gas_diffusion",
        "singular_pinchoff_rim_spray",
        "retracting_rim_ligament_droplet_spray",
        "unrestricted_3d_multineck_pinchoff",
        "arbitrary_deforming_moving_wall_cfd",
        "arbitrary_coupled_topology_live_surgery",
    ):
        if r38.get(name) != "NOT_IMPLEMENTED":
            issues.append(f"R38 Wave-23 unrestricted limitation was overclaimed: {name}")

    if rows["R28"]["status"] != "UNVERIFIED":
        issues.append("R28 physical iPhone qualification must remain UNVERIFIED")
    if rows["R38"]["status"] != "PARTIAL":
        issues.append("R38 must remain PARTIAL while direct physical iPhone qualification is absent")
    return issues


def build_final_validation(*, execute: bool = True, assert_honest: bool = False) -> dict[str, Any]:
    completion = build_audit(assert_honest=True)
    static_issues = honesty_issues(completion)
    historical = [runner._historical_record(spec) for spec in HISTORICAL_EVIDENCE]
    if execute:
        current = [runner._run_probe(spec) for spec in CURRENT_PROBES]
        executable_passed = all(item["result"] == "PASS" for item in current)
        qualification_status = "PASS_WITH_DECLARED_GAPS" if executable_passed else "FAIL"
    else:
        current = [
            {
                "name": spec["name"],
                "coverage": spec["coverage"],
                "execution": "CURRENT",
                "command": spec["command"],
                "result": "NOT_RUN",
            }
            for spec in CURRENT_PROBES
        ]
        executable_passed = False
        qualification_status = "NOT_RUN"

    historical_passed = all(item["result"] == "PASS" for item in historical)
    validation_passed = execute and executable_passed and historical_passed and not static_issues
    final_acceptance_ready = bool(completion["summary"]["final_acceptance_ready"]) and validation_passed

    result = {
        "schema_version": 6,
        "validation": "bubble-lab-final-validation",
        "baseline": "post-wave-23 accepted main",
        "qualification_status": qualification_status,
        "current_execution": current,
        "accepted_historical_evidence": historical,
        "completion_audit_summary": completion["summary"],
        "claim_boundaries": list(CLAIM_BOUNDARIES),
        "smallest_blocking_gaps": list(SMALLEST_BLOCKING_GAPS),
        "honesty_issues": static_issues,
        "summary": {
            "current_probe_count": len(current),
            "current_pass_count": sum(item["result"] == "PASS" for item in current),
            "historical_evidence_count": len(historical),
            "historical_pass_count": sum(item["result"] == "PASS" for item in historical),
            "validation_passed": validation_passed,
            "final_acceptance_ready": final_acceptance_ready,
            "final_acceptance_reason": completion["summary"]["final_acceptance_reason"],
        },
    }

    if assert_honest:
        failures = [item["name"] for item in current if item["result"] == "FAIL"]
        historical_failures = [item["name"] for item in historical if item["result"] != "PASS"]
        messages: list[str] = []
        if static_issues:
            messages.extend(static_issues)
        if failures:
            messages.append("current executable failures: " + ", ".join(failures))
        if historical_failures:
            messages.append("accepted evidence failures: " + ", ".join(historical_failures))
        if messages:
            raise FinalValidationError("; ".join(messages))
    return result


def render_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# Bubble Lab Final Validation",
        "",
        f"Qualification status: **{result['qualification_status']}**",
        f"Current probes passed: **{summary['current_pass_count']}/{summary['current_probe_count']}**",
        f"Accepted historical evidence passed: **{summary['historical_pass_count']}/{summary['historical_evidence_count']}**",
        f"Final acceptance ready: **{'yes' if summary['final_acceptance_ready'] else 'no'}**",
        f"Reason: {summary['final_acceptance_reason']}",
        "",
        "## Current execution",
        "",
        "| Probe | Coverage | Result |",
        "|---|---|---|",
    ]
    for item in result["current_execution"]:
        lines.append(f"| {item['name']} | {item['coverage']} | {item['result']} |")

    lines.extend(["", "## Accepted historical executable evidence", "", "| Evidence | Source | Result |", "|---|---|---|"])
    for item in result["accepted_historical_evidence"]:
        lines.append(f"| {item['name']} | `{item['source']}` | {item['result']} |")

    lines.extend(["", "## Smallest blocking gaps", ""])
    for item in result["smallest_blocking_gaps"]:
        requirements = ", ".join(item["requirement_ids"])
        lines.append(f"- **{item['priority']} — {requirements}** — {item['gap']} Recommended boundary: {item['recommended_task_boundary']}")

    lines.extend(["", "## Claim boundaries retained", ""])
    for boundary in result["claim_boundaries"]:
        lines.append(f"- {boundary}")

    completion = result["completion_audit_summary"]
    lines.extend([
        "",
        "## Completion audit summary",
        "",
        f"- Requirements: {completion['requirement_count']}",
        f"- Post-Wave-21 SATISFIED/PARTIAL/UNVERIFIED: {completion['previous_status_counts']['SATISFIED']}/{completion['previous_status_counts']['PARTIAL']}/{completion['previous_status_counts']['UNVERIFIED']}",
        f"- Post-Wave-23 SATISFIED/PARTIAL/UNVERIFIED: {completion['status_counts']['SATISFIED']}/{completion['status_counts']['PARTIAL']}/{completion['status_counts']['UNVERIFIED']}",
        f"- Status changes: {', '.join(item['requirement_id'] for item in completion['status_changes']) or 'none'}",
        f"- Final acceptance ready from R1-R39 matrix: {'yes' if completion['final_acceptance_ready'] else 'no'}",
    ])
    return "\n".join(lines).rstrip() + "\n"
