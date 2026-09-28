"""Post-Wave-25 final validation suite preserving the historical Wave-23 suite."""
from __future__ import annotations

from typing import Any

from bubblelab.validation.completion.wave25_audit import build_audit
from . import suite as runner
from . import wave23_suite as previous

FinalValidationError = runner.FinalValidationError

CURRENT_PROBES: tuple[dict[str, Any], ...] = previous.CURRENT_PROBES + (
    {
        "name": "repeated-t1-gas-transport",
        "coverage": "bounded six-region continuous gas/network history through two dependent production T1 transactions",
        "command": "python3 bubblelab/runtime/tools/run_repeated_topology_gas_transport.py --assert",
        "timeout": 900,
    },
    {
        "name": "interacting-multihole-rim-breakup",
        "coverage": "bounded two interacting thin-film holes in one conservative reduced film/rim state with state-derived fragments",
        "command": "python3 bubblelab/runtime/tools/run_multihole_rim_breakup.py --assert",
        "timeout": 900,
    },
    {
        "name": "manycontact-t1-through-global-cfd",
        "coverage": "bounded five-region many-contact T1 on one authoritative partitioned Eulerian field with causal non-event-contact resistance",
        "command": "python3 bubblelab/runtime/tools/run_manycontact_t1_global_cfd.py --assert",
        "timeout": 1200,
    },
)

HISTORICAL_EVIDENCE: tuple[dict[str, Any], ...] = previous.HISTORICAL_EVIDENCE + (
    {
        "name": "wave25-repeated-t1-gas-transport",
        "task_id": "bubble-repeated-t1-gas-transport-foundation",
        "checks": (
            "repeated-t1-switch",
            "repeated-topology-conservation",
            "second-event-dependence",
            "repeated-post-event-transfer",
            "repeated-topology-replay",
            "runtime-e2e",
        ),
        "reason": "Consumed only for one six-region canonical FilmNetwork/gas history containing two dependent production T1 events; arbitrary repeated surgery and other topology-event types are not inferred.",
    },
    {
        "name": "wave25-interacting-multihole-breakup",
        "task_id": "bubble-interacting-multihole-breakup-foundation",
        "checks": (
            "multihole-interaction",
            "multihole-mode-coupling",
            "multihole-conservation",
            "multihole-response",
            "multihole-refinement",
            "multihole-replay",
            "runtime-handoff",
        ),
        "reason": "Consumed only for two interacting thin-film holes with reduced conservative rim states; unrestricted 3D multi-hole hydrodynamics, singular ligament pinch-off and universal spray physics are not inferred.",
    },
    {
        "name": "wave25-manycontact-t1-global-cfd",
        "task_id": "bubble-manycontact-t1-global-cfd-foundation",
        "checks": (
            "manycontact-feedback",
            "manycontact-causality",
            "manycontact-conservation",
            "manycontact-refinement",
            "manycontact-symmetry",
            "runtime-e2e",
        ),
        "reason": "Consumed only for the declared five-region/high-viscosity class with one embedded non-coplanar T1 plus one additional active contact on one authoritative Eulerian field.",
    },
)

CLAIM_BOUNDARIES = (
    "Wave-25 repeated topology-changing gas transport is accepted only for one continuous six-region canonical network/gas history with two dependent production T1 transactions; arbitrary repeated surgery, rupture/coalescence/vanishing-region remap and fully coupled deforming 3D gas-film transport remain unsupported.",
    "Wave-25 interacting multi-hole breakup is accepted only for two thin-film holes in one conservative reduced film/rim state with shared-web coupling and state-derived necking/fragments; unrestricted 3D multi-hole hydrodynamics, singular ligament pinch-off, turbulent atomization, secondary aerodynamic breakup and universal spray CFD remain unsupported.",
    "Wave-25 many-contact T1/global-CFD is accepted only for the declared five-region class, 50 Pa s / 970 kg/m^3 exterior liquid and validated 0.0005 m/s non-event relative speed; arbitrary contact graphs, fluids/scales, singular Plateau-border CFD and universal multiphase Navier-Stokes remain unsupported.",
    *previous.CLAIM_BOUNDARIES,
)

SMALLEST_BLOCKING_GAPS = (
    {
        "priority": "physical validity",
        "requirement_ids": ["R1", "R10", "R11", "R35", "R38", "R39"],
        "gap": "Wave 25 materially strengthens repeated topology-changing gas transport, interacting breakup and many-contact shared-field T1 evidence, but arbitrary topology/contact graphs, unrestricted multiphase/singular-border CFD, unrestricted 3D multi-hole/singular breakup with broad spray physics, deforming walls and arbitrary coupled live surgery remain outside accepted evidence.",
        "recommended_task_boundary": "Advance one remaining unrestricted physical class at a time with independent causality, conservation, constitutive-response, refinement, symmetry/replay and runtime evidence; do not promote bounded Wave-25 subclasses to universal physics.",
    },
    {
        "priority": "numerical stability",
        "requirement_ids": ["R10", "R11", "R35", "R39"],
        "gap": "Wave-25 bounded classes carry conservation/refinement and deterministic gates, including >=5% many-contact feedback at 8/10/12 cells, but still-unimplemented unrestricted topology/contact/singular-CFD/general-breakup classes necessarily lack production stability qualification.",
        "recommended_task_boundary": "For every broader class, require convergence/refinement, bounded conservation/traction error, causal sensitivity and deterministic replay before integration claims move.",
    },
    {
        "priority": "state/conservation/reproducibility",
        "requirement_ids": ["R30", "R38", "R39"],
        "gap": "The two dependent T1 gas events preserve stable identities and conservative post-topology transfer, and all Wave-25 slices replay deterministically. Cross-version checkpoint portability, complete reusable many-bubble/network scenario breadth and arbitrary surgery through already-coupled topology states remain unsupported.",
        "recommended_task_boundary": "Extend state schemas and topology transactions only where exact conservation, stable identity and deterministic restart can be demonstrated across the missing event classes.",
    },
    {
        "priority": "runtime control",
        "requirement_ids": ["R20", "R30"],
        "gap": "The canonical product gains another qualified many-contact high-end slice and three reusable Wave-25 scenarios, but it still does not expose every requested high-end solver-control/runtime combination or the complete reusable scenario family.",
        "recommended_task_boundary": "Map only runnable high-end controls and scenarios into the authoritative runtime with capability declarations tied to executable backend combinations.",
    },
    {
        "priority": "visualization",
        "requirement_ids": ["R28", "R38"],
        "gap": "Physical iPhone Safari/device-GPU/native multi-touch qualification is still not archived; engine-level mobile evidence does not satisfy the direct real-device requirement.",
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
    if r13.get("bounded_repeated_t1_gas_transport") != "MODELED":
        issues.append("Wave-25 repeated T1 gas transport must remain a bounded MODELED class")
    if r13.get("repeated_post_topology_transport_rebuild") != "RESOLVED":
        issues.append("Wave-25 post-topology gas transport rebuild must remain RESOLVED")

    r16 = rows["R16"]["features"]
    if r16.get("bounded_interacting_multihole_breakup") != "MODELED":
        issues.append("Wave-25 interacting multi-hole breakup must remain a bounded MODELED class")
    if r16.get("state_derived_interacting_multihole_fragments") != "RESOLVED":
        issues.append("Wave-25 state-derived interacting multi-hole fragments must remain RESOLVED")

    r11 = rows["R11"]["features"]
    if r11.get("bounded_manycontact_t1_global_cfd") != "MODELED":
        issues.append("Wave-25 many-contact T1/global-CFD must remain a bounded MODELED class")
    if r11.get("bounded_non_event_contact_causality") != "MODELED":
        issues.append("Wave-25 non-event-contact causality must remain bounded MODELED evidence")

    r38 = rows["R38"]["features"]
    for name in (
        "bounded_repeated_t1_gas_transport",
        "bounded_interacting_multihole_breakup",
        "bounded_manycontact_t1_global_cfd",
        "bounded_non_event_contact_causality",
    ):
        if r38.get(name) != "MODELED":
            issues.append(f"R38 Wave-25 supported physical model must remain MODELED: {name}")
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
            issues.append(f"R38 Wave-25 unrestricted limitation was overclaimed: {name}")

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
        "schema_version": 7,
        "validation": "bubble-lab-final-validation",
        "baseline": "post-wave-25 accepted main",
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
        f"- Post-Wave-23 SATISFIED/PARTIAL/UNVERIFIED: {completion['previous_status_counts']['SATISFIED']}/{completion['previous_status_counts']['PARTIAL']}/{completion['previous_status_counts']['UNVERIFIED']}",
        f"- Post-Wave-25 SATISFIED/PARTIAL/UNVERIFIED: {completion['status_counts']['SATISFIED']}/{completion['status_counts']['PARTIAL']}/{completion['status_counts']['UNVERIFIED']}",
        f"- Status changes: {', '.join(item['requirement_id'] for item in completion['status_changes']) or 'none'}",
        f"- Final acceptance ready from R1-R39 matrix: {'yes' if completion['final_acceptance_ready'] else 'no'}",
    ])
    return "\n".join(lines).rstrip() + "\n"
