"""Post-Wave-19 final validation suite preserving the historical Wave-17 suite."""
from __future__ import annotations

from typing import Any

from bubblelab.validation.completion.wave19_audit import build_audit
from . import suite as legacy

FinalValidationError = legacy.FinalValidationError

CURRENT_PROBES: tuple[dict[str, Any], ...] = legacy.CURRENT_PROBES + (
    {
        "name": "manybubble-gas-diffusion-network",
        "coverage": "fixed-topology many-bubble pressure-driven gas diffusion with simultaneous real shared-film transfer",
        "command": "python3 bubblelab/runtime/tools/run_network_gas_diffusion.py --assert",
        "timeout": 300,
    },
    {
        "name": "multigap-manybubble-global-cfd",
        "coverage": "bounded three-bubble/two-simultaneous-gap global CFD with one authoritative Eulerian field",
        "command": "python3 bubblelab/runtime/tools/run_multigap_cfd.py --assert",
        "timeout": 600,
    },
    {
        "name": "direct-geometry-3d-t1-hydrodynamics",
        "coverage": "bounded direct-geometry genuinely non-coplanar 3D T1 hydrodynamics and authoritative topology continuation",
        "command": "python3 bubblelab/runtime/tools/run_t1_hydrodynamics_transition.py --assert",
        "timeout": 300,
    },
)

HISTORICAL_EVIDENCE: tuple[dict[str, Any], ...] = legacy.HISTORICAL_EVIDENCE + (
    {
        "name": "wave19-manybubble-gas-diffusion-network",
        "task_id": "bubble-manybubble-gas-diffusion-network",
        "checks": ("conservation", "coarsening", "refinement", "runtime-e2e"),
        "reason": "Wave-19 fixed-topology many-bubble gas diffusion is consumed only for its measured three-or-more-region, two-or-more-simultaneous-real-shared-film-edge class with conservative pressure/amount/volume feedback.",
    },
    {
        "name": "wave19-multigap-manybubble-cfd",
        "task_id": "bubble-multigap-manybubble-cfd-foundation",
        "checks": ("multigap-refinement", "multigap-mass-momentum", "multifront-feedback", "permutation-symmetry", "runtime-e2e"),
        "reason": "Wave-19 global CFD is consumed only for the bounded three-separated-bubble/two-simultaneous-gap shared-field class with measured refinement, conservation and multi-front feedback.",
    },
    {
        "name": "wave19-direct-3d-t1-hydrodynamics",
        "task_id": "bubble-direct-3d-t1-hydrodynamics",
        "checks": ("direct-t1-switch", "direct-t1-conservation", "direct-t1-refinement", "direct-t1-rotation", "direct-t1-runtime-transition"),
        "reason": "Wave-19 direct 3D T1 is consumed only for the isolated four-region curvilinear genuinely non-coplanar piecewise-linear class using current-mesh traction and the bounded frozen-traction closure.",
    },
)

CLAIM_BOUNDARIES = (
    "Contact-created rupture/coalescence proves integrated solver-driven reachability and conservation, not independent high-accuracy rupture-time physics.",
    "The many-bubble gas-diffusion result is limited to a fixed-topology shared-film network with at least three gas regions and at least two simultaneously active real transfer edges; dynamic T1/rupture/coalescence/vanishing-region topology-changing gas transport is unsupported.",
    "The global multi-gap CFD result is limited to exactly three separated quasi-spherical tracked bubbles in the validated two-simultaneous-gap class sharing one authoritative Eulerian field; overlapping immersed supports, arbitrary contact graphs, T1-through-global-CFD and universal sharp moving-interface multiphase Navier-Stokes are unsupported.",
    "The direct-geometry 3D T1 result is limited to an isolated four-region curvilinear genuinely non-coplanar piecewise-linear neighborhood with current-mesh capillary traction and an overdamped frozen-traction closure; conforming subdivision of the same physical geometry proves discretization invariance, not unrestricted curved-surface continuum convergence or resolved evolving/singular liquid-border CFD.",
    "The pinch-off result is limited to one smooth axisymmetric slender neck with dynamically evolved hydrodynamics and inferred singular time; retracting rims, ligaments, droplets/spray, arbitrary multi-neck and unrestricted fully resolved 3D singular breakup remain unsupported.",
    "Resolved bulk no-slip wall CFD is accepted only for fixed SDF geometry with stationary or spatially uniform declared wall velocity; arbitrary/deforming moving-wall CFD is unsupported.",
    "Playwright WebKit mobile-engine evidence is not physical iPhone Safari/device-GPU/native-hardware multi-touch or thermal qualification.",
    "Authoritative live editing is accepted for PAUSED base-transient continuation; arbitrary surgery through existing shared-film/network/T1/thin-film/event states is unsupported.",
)

SMALLEST_BLOCKING_GAPS = (
    {
        "priority": "physical validity",
        "requirement_ids": ["R1", "R10", "R11", "R35", "R38", "R39"],
        "gap": "Wave 19 closes the baseline many-bubble gas-diffusion requirement and advances simultaneous global CFD and direct 3D T1, but T1-through-global-CFD/overlapping immersed supports, unrestricted topology-changing gas transport, unrestricted curved/singular 3D T1 liquid-border hydrodynamics, retracting-rim/ligament/droplet-spray physics and unrestricted 3D multi-neck breakup remain outside accepted evidence.",
        "recommended_task_boundary": "Advance one remaining physical class at a time with independent field, conservation, reference and refinement evidence; do not promote bounded Wave-19 subclasses to universal physics.",
    },
    {
        "priority": "numerical stability",
        "requirement_ids": ["R10", "R11", "R35", "R39"],
        "gap": "The accepted Wave-19 gas-network, separated-support multi-gap CFD and direct-T1 classes carry conservation/refinement or invariance evidence, but unimplemented overlap/T1-through-CFD, unrestricted 3D T1 and general singular-breakup classes necessarily lack production stability qualification.",
        "recommended_task_boundary": "For any newly implemented unrestricted class, require convergence/refinement, bounded conservation error, deterministic replay and stability gates before integration claims move.",
    },
    {
        "priority": "state/conservation/reproducibility",
        "requirement_ids": ["R30", "R38", "R39"],
        "gap": "Same-build checkpointing, supported gas-network evolution and accepted topology/event handoffs are deterministic, but cross-version checkpoint portability, the complete reusable scenario family and arbitrary live surgery through already-coupled topology states remain unsupported.",
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
        "gap": "Physical iPhone Safari/device-GPU/native multi-touch qualification is not archived; current mobile evidence remains Playwright WebKit engine-level only.",
        "recommended_task_boundary": "Run the documented viewer/control flow on physical iPhone Safari or equivalent credible real-device evidence and archive render, input and device metadata.",
    },
    {
        "priority": "performance",
        "requirement_ids": ["R28", "R35", "R39"],
        "gap": "No accepted-class performance regression is established by this audit, but physical-iPhone GPU/thermal behavior and unrestricted Maximum-Realism throughput remain unqualified because those device/general physics scopes are not yet evidenced.",
        "recommended_task_boundary": "Benchmark only after the corresponding real-device or unrestricted high-fidelity path exists, preserving physics and stability gates ahead of optimization.",
    },
)


def honesty_issues(completion: dict[str, Any] | None = None) -> list[str]:
    audit = completion or build_audit(assert_honest=True)
    issues = legacy.honesty_issues(audit)
    rows = {row["requirement_id"]: row for row in audit["rows"]}

    if rows["R13"]["status"] != "SATISFIED":
        issues.append("Wave-19 many-bubble gas diffusion must close the R13 baseline requirement")
    r38 = rows["R38"]["features"]
    for name in (
        "supported_manybubble_pressure_driven_gas_network",
        "bounded_three_bubble_two_gap_global_cfd",
        "bounded_direct_geometry_3d_t1_hydrodynamics",
    ):
        if r38.get(name) != "MODELED":
            issues.append(f"R38 Wave-19 supported physical model must remain MODELED: {name}")
    for name in (
        "unrestricted_topology_changing_gas_diffusion",
        "t1_through_global_cfd",
        "overlapping_immersed_supports",
    ):
        if r38.get(name) != "NOT_IMPLEMENTED":
            issues.append(f"R38 Wave-19 limitation was overclaimed: {name}")
    if rows["R28"]["status"] != "UNVERIFIED":
        issues.append("R28 physical iPhone qualification must remain UNVERIFIED")
    if rows["R38"]["status"] != "PARTIAL":
        issues.append("R38 must remain PARTIAL while direct physical iPhone qualification is absent")
    return issues


def build_final_validation(*, execute: bool = True, assert_honest: bool = False) -> dict[str, Any]:
    completion = build_audit(assert_honest=True)
    static_issues = honesty_issues(completion)
    historical = [legacy._historical_record(spec) for spec in HISTORICAL_EVIDENCE]
    if execute:
        current = [legacy._run_probe(spec) for spec in CURRENT_PROBES]
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
        "schema_version": 4,
        "validation": "bubble-lab-final-validation",
        "baseline": "post-wave-19 accepted main",
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
        f"- Post-Wave-17 SATISFIED/PARTIAL/UNVERIFIED: {completion['previous_status_counts']['SATISFIED']}/{completion['previous_status_counts']['PARTIAL']}/{completion['previous_status_counts']['UNVERIFIED']}",
        f"- Post-Wave-19 SATISFIED/PARTIAL/UNVERIFIED: {completion['status_counts']['SATISFIED']}/{completion['status_counts']['PARTIAL']}/{completion['status_counts']['UNVERIFIED']}",
        f"- Status changes: {', '.join(item['requirement_id'] for item in completion['status_changes']) or 'none'}",
        f"- Final acceptance ready from R1-R39 matrix: {'yes' if completion['final_acceptance_ready'] else 'no'}",
    ])
    return "\n".join(lines).rstrip() + "\n"
