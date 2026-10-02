"""Deterministic end-to-end final validation harness for Bubble Lab."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from bubblelab.validation.completion.audit import build_audit
from bubblelab.validation.completion.historical_evidence import historical_delivery, historical_delivery_source

ROOT = Path(__file__).resolve().parents[3]

CURRENT_PROBES: tuple[dict[str, Any], ...] = (
    {
        "name": "equilibrium-validation",
        "coverage": "equilibrium/Young-Laplace/volume-energy",
        "command": "python3 bubblelab/validation/tools/run_equilibrium_validation.py --output /tmp/bubble-final-equilibrium.json --assert",
        "output": "/tmp/bubble-final-equilibrium.json",
        "timeout": 300,
    },
    {
        "name": "transient-validation",
        "coverage": "sharp-interface/AMR/remeshing/boundary/event integration",
        "command": "python3 bubblelab/validation/tools/run_transient_validation.py --output /tmp/bubble-final-transient.json --assert",
        "output": "/tmp/bubble-final-transient.json",
        "timeout": 600,
    },
    {
        "name": "transient-network-shared-film",
        "coverage": "canonical shared-film transient network",
        "command": "rm -rf /tmp/bubble-final-network-shared && python3 bubblelab/runtime/tools/run_scenario.py bubblelab/scenarios/runtime/transient-network-shared-film.scenario.json --backend transient-network --frames 6 --output /tmp/bubble-final-network-shared && python3 bubblelab/runtime/tools/validate_replay_bundle.py /tmp/bubble-final-network-shared",
        "timeout": 300,
    },
    {
        "name": "transient-network-plateau",
        "coverage": "canonical Plateau-junction transient network",
        "command": "rm -rf /tmp/bubble-final-network-plateau && python3 bubblelab/runtime/tools/run_scenario.py bubblelab/scenarios/runtime/transient-network-plateau.scenario.json --backend transient-network --frames 6 --output /tmp/bubble-final-network-plateau && python3 bubblelab/runtime/tools/validate_replay_bundle.py /tmp/bubble-final-network-plateau",
        "timeout": 300,
    },
    {
        "name": "contact-transition",
        "coverage": "separated-front contact formation and shared-network handoff",
        "command": "rm -rf /tmp/bubble-final-contact && python3 bubblelab/runtime/tools/run_contact_transition.py bubblelab/scenarios/runtime/contact-transition-two-bubble.scenario.json --frames 12 --output /tmp/bubble-final-contact && python3 bubblelab/runtime/tools/validate_replay_bundle.py /tmp/bubble-final-contact",
        "timeout": 600,
    },
    {
        "name": "contact-thinfilm-drainage",
        "coverage": "contact-created finite-thickness drainage/surfactant/gas path",
        "command": "rm -rf /tmp/bubble-final-contact-thinfilm && python3 bubblelab/runtime/tools/run_contact_thinfilm_event.py bubblelab/scenarios/runtime/contact-thinfilm-event-drainage.scenario.json --assert --output /tmp/bubble-final-contact-thinfilm",
        "timeout": 600,
    },
    {
        "name": "contact-thinfilm-rupture",
        "coverage": "solver-driven rupture/coalescence reachability and conservation",
        "command": "rm -rf /tmp/bubble-final-contact-event && python3 bubblelab/runtime/tools/run_contact_thinfilm_event.py bubblelab/scenarios/runtime/contact-thinfilm-event-rupture.scenario.json --assert-event --output /tmp/bubble-final-contact-event",
        "timeout": 600,
    },
    {
        "name": "fragmentation-conservation",
        "coverage": "supported-class production split/conservation/determinism",
        "command": "python3 bubblelab/solvers/events/fragmentation/tools/run_benchmark.py conservation --assert",
        "timeout": 300,
    },
    {
        "name": "postfragment-relaxation-smoke",
        "coverage": "exact child-mesh restart and short physical relaxation",
        "command": "rm -rf /tmp/bubble-final-postfragment && python3 bubblelab/runtime/tools/run_postfragmentation_relaxation.py bubblelab/scenarios/runtime/postfragmentation-necked.scenario.json --frames 4 --output /tmp/bubble-final-postfragment && python3 bubblelab/runtime/tools/validate_replay_bundle.py /tmp/bubble-final-postfragment",
        "timeout": 300,
    },
    {
        "name": "t1-supported-switch",
        "coverage": "isolated four-region quasi-2D/extruded production T1",
        "command": "python3 bubblelab/solvers/transient/network/tools/run_t1_benchmark.py switch --assert",
        "timeout": 300,
    },
    {
        "name": "live-session-transport",
        "coverage": "authoritative loopback viewer-to-runtime session transport",
        "command": "python3 bubblelab/runtime/server/tools/run_transport_e2e.py --assert",
        "timeout": 300,
    },
    {
        "name": "live-runtime-editing",
        "coverage": "authoritative PAUSED-state live bubble add/delete/move/resize/velocity editing and continuation",
        "command": "python3 bubblelab/runtime/server/tools/run_live_edit_e2e.py --assert",
        "timeout": 300,
    },
    {
        "name": "resolved-noslip-wall-runtime",
        "coverage": "canonical fixed-SDF resolved bulk no-slip wall CFD and Eulerian diagnostics",
        "command": "python3 bubblelab/runtime/tools/run_noslip_wall_runtime.py --assert",
        "timeout": 300,
    },
    {
        "name": "precontact-thin-gap-cfd",
        "coverage": "supported-class local isolated pre-contact thin-gap CFD pressure/velocity/traction feedback",
        "command": "python3 bubblelab/runtime/tools/run_precontact_cfd.py --assert",
        "timeout": 300,
    },
    {
        "name": "global-multiregion-precontact-cfd",
        "coverage": "supported global-domain 3D two-bubble/single-gap multi-region CFD with field-derived traction and local handoff",
        "command": "python3 bubblelab/runtime/tools/run_multiregion_precontact_cfd.py --assert",
        "timeout": 600,
    },
    {
        "name": "genuine-3d-t1-transition",
        "coverage": "bounded genuinely non-coplanar 3D T1 adjacency/incidence switch and continuation",
        "command": "python3 bubblelab/runtime/tools/run_t1_3d_transition.py --assert",
        "timeout": 300,
    },
    {
        "name": "axisymmetric-pinchoff-transition",
        "coverage": "single smooth axisymmetric slender-neck pinch-off hydrodynamics and deterministic fragmentation restart",
        "command": "python3 bubblelab/runtime/tools/run_pinchoff_transition.py --assert",
        "timeout": 300,
    },
)

HISTORICAL_EVIDENCE: tuple[dict[str, Any], ...] = (
    {
        "name": "exact-transient-release",
        "task_id": "bubble-transient-release-acceleration",
        "checks": ("B03-exact", "B07-exact", "B08-exact", "B12-exact"),
        "reason": "Exact long-window/refinement release qualification is expensive and is consumed from accepted executable evidence.",
    },
    {
        "name": "postfragment-16-frame-e2e",
        "task_id": "bubble-postfragmentation-relaxation",
        "checks": ("postfragment-e2e",),
        "reason": "The accepted unchanged 16-frame post-fragmentation E2E takes about 29 minutes on GitHub-hosted execution; final validation reruns a representative smoke while preserving the full accepted qualification.",
    },
    {
        "name": "mobile-webkit-engine",
        "task_id": "bubble-mobile-webkit-verification",
        "checks": ("real-webkit-mobile-e2e",),
        "reason": "Playwright WebKit/iPhone-class engine evidence is accepted; physical iPhone hardware remains separately unverified.",
    },
    {
        "name": "checkpoint-restart",
        "task_id": "bubble-checkpoint-restart",
        "checks": ("fresh-process-transient", "fresh-process-thinfilm"),
        "reason": "Exact same-build fresh-process continuation is consumed from accepted checkpoint evidence.",
    },
    {
        "name": "wave15-live-runtime-editing",
        "task_id": "bubble-live-runtime-editing",
        "checks": ("final-declared-acceptance", "authoritative-continuation", "loopback-transport"),
        "reason": "Wave-15 authoritative live editing was accepted with atomic rollback, deterministic provenance, same-session continuation and checkpoint coverage.",
    },
    {
        "name": "wave15-noslip-wall-runtime",
        "task_id": "bubble-noslip-wall-runtime-integration",
        "checks": ("no-slip runtime end-to-end probe", "runtime full regression"),
        "reason": "Wave-15 fixed-SDF no-slip wall runtime integration was accepted with measured authoritative Eulerian diagnostics and full runtime regression.",
    },
    {
        "name": "wave15-precontact-thin-gap-cfd",
        "task_id": "bubble-precontact-multiregion-cfd-foundation",
        "checks": ("refinement-benchmark", "precontact-cfd-runtime-e2e", "full-runtime-regression"),
        "reason": "Wave-15 local isolated thin-gap CFD was accepted with numerical field solves, refinement, conservation/no-slip evidence and runtime traction feedback.",
    },
    {
        "name": "wave17-global-multiregion-cfd",
        "task_id": "bubble-global-multiregion-cfd-coupling",
        "checks": ("field-refinement", "mass-momentum-balance", "front-feedback", "runtime-e2e"),
        "reason": "Wave-17 supported global two-bubble/single-gap CFD is consumed with asymptotic 10^3/12^3/14^3 refinement, closed-control-volume traction and runtime feedback evidence; 8^3 remains pre-asymptotic.",
    },
    {
        "name": "wave17-bounded-genuine-3d-t1",
        "task_id": "bubble-general-3d-t1-foundation",
        "checks": ("t1-3d-switch", "t1-3d-conservation", "t1-3d-refinement", "t1-3d-runtime-transition"),
        "reason": "Wave-17 bounded genuinely non-coplanar 3D T1 is consumed with adjacency/incidence, conservation, replay, refinement and continuation evidence.",
    },
    {
        "name": "wave17-axisymmetric-pinchoff",
        "task_id": "bubble-singular-breakup-cfd-foundation",
        "checks": ("neck-evolution", "pinchoff-refinement", "pinchoff-conservation", "runtime-handoff"),
        "reason": "Wave-17 single smooth axisymmetric slender-neck pinch-off is consumed with dynamically evolved hydrodynamics, inferred event time, conservation/refinement and exact fragmentation restart evidence.",
    },
)

CLAIM_BOUNDARIES = (
    "Contact-created rupture/coalescence proves integrated solver-driven reachability and conservation, not independent high-accuracy rupture-time physics.",
    "The genuinely non-coplanar 3D T1 result is limited to the accepted mathematically bounded bilinear-shear subclass; arbitrary admissible 3D T1 and fully resolved T1 hydrodynamics remain unsupported.",
    "The global multi-region CFD result is limited to the supported global-domain two-bubble/single-gap class with local resolved thin-gap handoff; arbitrary simultaneous multi-gap/many-bubble/T1 CFD and universal full-domain multiphase Navier-Stokes are unsupported.",
    "The pinch-off result is limited to one smooth axisymmetric slender neck with dynamically evolved hydrodynamics and inferred singular time; retracting rims, ligaments, droplets/spray, arbitrary multi-neck and unrestricted fully resolved 3D singular breakup remain unsupported.",
    "Resolved bulk no-slip wall CFD is accepted only for fixed SDF geometry with stationary or spatially uniform declared wall velocity; arbitrary/deforming moving-wall CFD is unsupported.",
    "Playwright WebKit mobile-engine evidence is not physical iPhone Safari/device-GPU/native-hardware multi-touch or thermal qualification.",
    "Authoritative live editing is accepted for PAUSED base-transient continuation; arbitrary surgery through existing shared-film/network/T1/thin-film/event states is unsupported.",
)

SMALLEST_BLOCKING_GAPS = (
    {
        "priority": "physical validity",
        "requirement_ids": ["R1", "R10", "R11", "R13", "R35", "R38", "R39"],
        "gap": "Supported Wave-17 global CFD, bounded genuine 3D T1 and single-neck axisymmetric pinch-off are accepted, but arbitrary simultaneous multi-gap/many-bubble/T1 CFD, general many-bubble gas diffusion, unrestricted admissible 3D T1, retracting-rim/ligament/droplet-spray physics and unrestricted 3D multi-neck breakup remain outside accepted evidence.",
        "recommended_task_boundary": "Advance one remaining physical class at a time with independent field/conservation/reference evidence; do not promote bounded Wave-17 subclasses to universal physics.",
    },
    {
        "priority": "numerical stability",
        "requirement_ids": ["R10", "R11", "R35", "R39"],
        "gap": "The accepted Wave-17 classes carry refinement and conservation evidence, but the unimplemented arbitrary multi-gap/many-bubble CFD, unrestricted 3D T1 and general singular breakup classes necessarily lack production stability qualification.",
        "recommended_task_boundary": "For any newly implemented unrestricted class, require convergence/refinement, bounded conservation error and deterministic stability gates before integration claims move.",
    },
    {
        "priority": "state/conservation/reproducibility",
        "requirement_ids": ["R13", "R30", "R38", "R39"],
        "gap": "Same-build checkpointing, base-transient live edits and the accepted Wave-17 topology/event handoffs are deterministic, but cross-version checkpoint portability, the complete reusable scenario family, general network gas-transfer state and arbitrary live surgery through already-coupled topology states remain unsupported.",
        "recommended_task_boundary": "Extend state schemas/transactions only where exact conservation, stable identity and deterministic restart can be demonstrated.",
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
        "recommended_task_boundary": "Benchmark only after the corresponding real-device or unrestricted high-fidelity path exists, preserving physics/stability gates ahead of optimization.",
    },
)


class FinalValidationError(RuntimeError):
    """Raised when executable final-validation evidence fails or honesty is violated."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_probe(spec: dict[str, Any]) -> dict[str, Any]:
    env = os.environ.copy()
    env.update({"PYTHONHASHSEED": "0", "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"})
    try:
        process = subprocess.run(
            ["bash", "-lc", str(spec["command"])],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=int(spec.get("timeout", 600)),
            check=False,
        )
        result = "PASS" if process.returncode == 0 else "FAIL"
        record: dict[str, Any] = {
            "name": spec["name"],
            "coverage": spec["coverage"],
            "execution": "CURRENT",
            "command": spec["command"],
            "result": result,
        }
        output = spec.get("output")
        if output and result == "PASS":
            output_path = Path(str(output))
            if output_path.is_file():
                record["output_sha256"] = _sha256(output_path)
        if result != "PASS":
            record["diagnostic_tail"] = process.stdout.splitlines()[-40:]
            record["returncode"] = process.returncode
        return record
    except subprocess.TimeoutExpired as exc:
        return {
            "name": spec["name"],
            "coverage": spec["coverage"],
            "execution": "CURRENT",
            "command": spec["command"],
            "result": "FAIL",
            "diagnostic_tail": [f"timeout after {exc.timeout} seconds"],
        }


def _historical_record(spec: dict[str, Any]) -> dict[str, Any]:
    task_id = str(spec["task_id"])
    source = historical_delivery_source(task_id)
    try:
        delivery = historical_delivery(task_id)
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        return {
            "name": spec["name"],
            "execution": "ACCEPTED_HISTORICAL",
            "source": source,
            "result": "FAIL",
            "reason": spec["reason"],
            "diagnostic": str(exc),
        }
    checks = {
        str(item.get("name")): item
        for item in delivery.get("validation", [])
        if isinstance(item, dict)
    }
    selected = []
    passed = delivery.get("status") == "DELIVERED"
    for name in spec["checks"]:
        item = checks.get(str(name))
        selected.append(
            {
                "name": name,
                "result": item.get("result") if item else "MISSING",
                "run_id": item.get("run_id") if item else None,
            }
        )
        passed = passed and item is not None and item.get("result") == "PASS"
    return {
        "name": spec["name"],
        "execution": "ACCEPTED_HISTORICAL",
        "source": source,
        "result": "PASS" if passed else "FAIL",
        "reason": spec["reason"],
        "checks": selected,
    }

def honesty_issues(completion: dict[str, Any] | None = None) -> list[str]:
    audit = completion or build_audit(assert_honest=True)
    rows = {row["requirement_id"]: row for row in audit["rows"]}
    issues: list[str] = []

    r38 = rows["R38"]["features"]
    for name in (
        "multi_bubble_canonical_runtime",
        "contact_thinfilm_event_chain",
        "browser_live_solver_transport",
        "production_fragmentation",
        "supported_t1_transaction",
        "arbitrary_live_runtime_creation",
        "live_runtime_bubble_editing",
        "resolved_no_slip_wall_cfd",
        "bounded_genuine_non_coplanar_3d_t1",
        "deterministic_pinchoff_fragmentation_restart",
    ):
        if r38.get(name) != "RESOLVED":
            issues.append(f"R38 accepted capability not consumed: {name}")
    for name in (
        "local_resolved_precontact_thin_gap_cfd",
        "supported_global_two_bubble_single_gap_multiregion_cfd",
        "supported_axisymmetric_slender_neck_pinchoff",
    ):
        if r38.get(name) != "MODELED":
            issues.append(f"R38 supported physical model must remain MODELED: {name}")
    for name in (
        "physical_iphone_safari",
        "native_hardware_multitouch",
        "global_full_domain_multiregion_cfd",
        "arbitrary_multigap_manybubble_t1_cfd",
        "general_3d_t1",
        "retracting_rim_ligament_droplet_spray",
        "unrestricted_3d_multineck_pinchoff",
        "arbitrary_deforming_moving_wall_cfd",
        "arbitrary_coupled_topology_live_surgery",
    ):
        if r38.get(name) != "NOT_IMPLEMENTED":
            issues.append(f"R38 limitation was overclaimed: {name}")

    if rows["R16"]["status"] != "SATISFIED":
        issues.append("Wave-17 supported single-neck pinch-off must close the R16 baseline gap")
    if rows["R28"]["status"] != "UNVERIFIED":
        issues.append("R28 physical iPhone qualification must remain UNVERIFIED")
    if rows["R38"]["status"] != "PARTIAL":
        issues.append("R38 must remain PARTIAL while direct physical iPhone qualification is absent")
    return issues


def build_final_validation(*, execute: bool = True, assert_honest: bool = False) -> dict[str, Any]:
    completion = build_audit(assert_honest=True)
    static_issues = honesty_issues(completion)
    historical = [_historical_record(spec) for spec in HISTORICAL_EVIDENCE]
    if execute:
        current = [_run_probe(spec) for spec in CURRENT_PROBES]
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
        "schema_version": 3,
        "validation": "bubble-lab-final-validation",
        "baseline": "post-wave-17 accepted main",
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
        messages = []
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
        lines.append(
            f"- **{item['priority']} — {requirements}** — {item['gap']} Recommended boundary: {item['recommended_task_boundary']}"
        )

    lines.extend(["", "## Claim boundaries retained", ""])
    for boundary in result["claim_boundaries"]:
        lines.append(f"- {boundary}")

    completion = result["completion_audit_summary"]
    lines.extend([
        "",
        "## Completion audit summary",
        "",
        f"- Requirements: {completion['requirement_count']}",
        f"- Post-Wave-15 SATISFIED/PARTIAL/UNVERIFIED: {completion['previous_status_counts']['SATISFIED']}/{completion['previous_status_counts']['PARTIAL']}/{completion['previous_status_counts']['UNVERIFIED']}",
        f"- Post-Wave-17 SATISFIED/PARTIAL/UNVERIFIED: {completion['status_counts']['SATISFIED']}/{completion['status_counts']['PARTIAL']}/{completion['status_counts']['UNVERIFIED']}",
        f"- Status changes: {', '.join(item['requirement_id'] for item in completion['status_changes']) or 'none'}",
        f"- Final acceptance ready from R1-R39 matrix: {'yes' if completion['final_acceptance_ready'] else 'no'}",
    ])
    return "\n".join(lines).rstrip() + "\n"
