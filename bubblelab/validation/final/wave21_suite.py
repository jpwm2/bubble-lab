"""Post-Wave-21 final validation suite preserving the historical Wave-19 suite."""
from __future__ import annotations

from typing import Any

from bubblelab.validation.completion.wave21_audit import build_audit
from . import suite as runner
from . import wave19_suite as previous

FinalValidationError = runner.FinalValidationError

CURRENT_PROBES: tuple[dict[str, Any], ...] = previous.CURRENT_PROBES + (
    {
        "name": "topology-changing-gas-transport",
        "coverage": "bounded conservative gas transport through one real four-region T1 with post-event FilmNetwork rebuild",
        "command": "python3 bubblelab/runtime/tools/run_topology_gas_transport.py --assert",
        "timeout": 300,
    },
    {
        "name": "t1-through-global-cfd",
        "coverage": "bounded four-region T1 through one authoritative Eulerian field with measured overlapping-support partition",
        "command": "python3 bubblelab/runtime/tools/run_t1_global_cfd.py --assert",
        "timeout": 900,
    },
    {
        "name": "retracting-rim-ligament-droplet",
        "coverage": "bounded circular-hole rim retraction, single-mode ligament onset and deterministic droplet handoff",
        "command": "python3 bubblelab/runtime/tools/run_rim_breakup_transition.py --assert",
        "timeout": 900,
    },
)

HISTORICAL_EVIDENCE: tuple[dict[str, Any], ...] = previous.HISTORICAL_EVIDENCE + (
    {
        "name": "wave21-topology-changing-gas-transport",
        "task_id": "bubble-topology-changing-gas-transport",
        "checks": ("t1-graph-switch", "topology-conservation", "post-t1-transfer", "deterministic-replay", "runtime-e2e"),
        "reason": "Consumed only for one supported isolated four-region T1 with canonical FilmNetwork-derived pre/post edges, stable gas identities and conservative post-event transfer.",
    },
    {
        "name": "wave21-t1-through-global-cfd",
        "task_id": "bubble-t1-through-global-cfd-foundation",
        "checks": ("overlap-support", "t1-field-transition", "t1-cfd-conservation", "t1-cfd-refinement", "t1-cfd-symmetry", "runtime-e2e"),
        "reason": "Consumed only for the bounded isolated four-region non-coplanar T1 with four quasi-spherical supports on one Eulerian field and measured partition-of-unity overlap treatment.",
    },
    {
        "name": "wave21-rim-ligament-droplet",
        "task_id": "bubble-retracting-rim-ligament-droplet-foundation",
        "checks": ("rim-retraction", "ligament-growth", "liquid-conservation", "breakup-refinement", "deterministic-replay", "runtime-handoff"),
        "reason": "Consumed only for one circular thin-film hole, one evolved toroidal rim and one resolved azimuthal mode with deterministic conservative droplet detachment.",
    },
)

CLAIM_BOUNDARIES = (
    "Topology-changing gas transport is accepted only for one isolated four-region quasi-2D/extruded production T1; rupture/coalescence/vanishing-region remap, unrestricted repeated surgery and continuously deforming fully coupled 3D gas-film transport are unsupported.",
    "T1-through-global-CFD is accepted only for one isolated genuinely non-coplanar four-region T1 with four closed quasi-spherical supports, measured partition-of-unity overlap treatment and one authoritative Eulerian field; arbitrary-contact multiphase Navier-Stokes, singular Plateau-border CFD and strongly hydrodynamically delayed T1 remain unsupported.",
    "Post-rupture breakup is accepted only for one circular thin-film hole with a dynamically evolved reduced toroidal rim and one resolved azimuthal mode; arbitrary 3D multi-hole rupture, fully resolved singular ligament pinch-off, broad spray distributions, turbulent atomization, secondary aerodynamic breakup and general post-detachment droplet CFD are unsupported.",
    "The direct-geometry 3D T1 result remains bounded to its accepted isolated four-region piecewise-linear class; conforming subdivision does not establish unrestricted curved-surface continuum convergence or singular liquid-border CFD.",
    "Resolved bulk no-slip wall CFD is accepted only for fixed SDF geometry with stationary or spatially uniform declared wall velocity; arbitrary/deforming moving-wall CFD is unsupported.",
    "Playwright WebKit mobile-engine evidence is not physical iPhone Safari/device-GPU/native-hardware multi-touch or thermal qualification.",
    "Authoritative live editing is accepted for its declared bounded state classes; arbitrary surgery through existing shared-film/network/T1/thin-film/event states is unsupported.",
)

SMALLEST_BLOCKING_GAPS = (
    {
        "priority": "physical validity",
        "requirement_ids": ["R1", "R10", "R11", "R35", "R38", "R39"],
        "gap": "Wave 21 closes three bounded foundations but unrestricted repeated topology-changing gas-film coupling, arbitrary-contact/singular-border global CFD, unrestricted continuous/singular 3D T1 and arbitrary 3D multi-hole/multi-neck breakup with broad spray physics remain outside accepted evidence.",
        "recommended_task_boundary": "Advance one remaining unrestricted physical class at a time with independent field, conservation, reference, refinement and runtime evidence; do not promote bounded Wave-21 subclasses to universal physics.",
    },
    {
        "priority": "numerical stability",
        "requirement_ids": ["R10", "R11", "R35", "R39"],
        "gap": "Accepted Wave-21 classes carry conservation/refinement, invariance or deterministic evidence, but the still-unimplemented unrestricted topology, arbitrary-contact CFD and general 3D breakup classes necessarily lack production stability qualification.",
        "recommended_task_boundary": "For any broader class, require convergence/refinement, bounded conservation error, deterministic replay and stability gates before integration claims move.",
    },
    {
        "priority": "state/conservation/reproducibility",
        "requirement_ids": ["R30", "R38", "R39"],
        "gap": "Supported Wave-21 event handoffs preserve stable identities and deterministic state, but cross-version checkpoint portability, the complete reusable scenario family and arbitrary live surgery through already-coupled topology states remain unsupported.",
        "recommended_task_boundary": "Extend state schemas and topology transactions only where exact conservation, stable identity and deterministic restart can be demonstrated.",
    },
    {
        "priority": "runtime control",
        "requirement_ids": ["R20", "R30"],
        "gap": "The canonical product still does not expose every high-end solver-control/runtime combination, and the reusable many-bubble/network scenario family remains incomplete.",
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

    r13 = rows["R13"]["features"]
    if r13.get("bounded_topology_changing_gas_transport") != "MODELED":
        issues.append("Wave-21 topology-changing gas transport must remain a bounded MODELED class")
    if r13.get("t1_gas_state_preservation") != "RESOLVED":
        issues.append("Wave-21 gas state preservation across the accepted T1 must remain RESOLVED")

    r38 = rows["R38"]["features"]
    for name in (
        "bounded_topology_changing_gas_transport",
        "bounded_t1_through_global_cfd",
        "bounded_overlapping_immersed_supports",
        "bounded_retracting_rim_ligament_droplet_detachment",
    ):
        if r38.get(name) != "MODELED":
            issues.append(f"R38 Wave-21 supported physical model must remain MODELED: {name}")
    for name in (
        "unrestricted_topology_changing_gas_diffusion",
        "t1_through_global_cfd",
        "overlapping_immersed_supports",
        "retracting_rim_ligament_droplet_spray",
        "unrestricted_3d_multineck_pinchoff",
    ):
        if r38.get(name) != "NOT_IMPLEMENTED":
            issues.append(f"R38 Wave-21 unrestricted limitation was overclaimed: {name}")

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
        "schema_version": 5,
        "validation": "bubble-lab-final-validation",
        "baseline": "post-wave-21 accepted main",
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
        f"- Post-Wave-19 SATISFIED/PARTIAL/UNVERIFIED: {completion['previous_status_counts']['SATISFIED']}/{completion['previous_status_counts']['PARTIAL']}/{completion['previous_status_counts']['UNVERIFIED']}",
        f"- Post-Wave-21 SATISFIED/PARTIAL/UNVERIFIED: {completion['status_counts']['SATISFIED']}/{completion['status_counts']['PARTIAL']}/{completion['status_counts']['UNVERIFIED']}",
        f"- Status changes: {', '.join(item['requirement_id'] for item in completion['status_changes']) or 'none'}",
        f"- Final acceptance ready from R1-R39 matrix: {'yes' if completion['final_acceptance_ready'] else 'no'}",
    ])
    return "\n".join(lines).rstrip() + "\n"
