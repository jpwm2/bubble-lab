"""Deterministic R1-R39 completion audit assembly and honesty checks."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
from typing import Any

from .wave15_catalog import CATALOG as WAVE15_CATALOG
from .wave17_catalog import CATALOG

ROOT = Path(__file__).resolve().parents[3]
REQUIREMENTS = ROOT / "orchestra" / "REQUIREMENTS.md"
STATUS_VOCABULARY = ("SATISFIED", "PARTIAL", "DEFERRED", "UNVERIFIED", "NOT_IMPLEMENTED")
FEATURE_VOCABULARY = ("RESOLVED", "MODELED", "VISUAL_ONLY", "NOT_IMPLEMENTED")
_REQUIRED_IDS = tuple(f"R{i}" for i in range(1, 40))
_TITLE_RE = re.compile(r"^## (R\d+)\.\s+(.+?)\s*$")


class AuditIntegrityError(ValueError):
    """Raised when the completion audit overclaims or loses traceability."""


def _requirement_titles() -> dict[str, str]:
    titles: dict[str, str] = {}
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        match = _TITLE_RE.match(line)
        if match:
            titles[match.group(1)] = match.group(2)
    return titles


def _validate_catalog(titles: dict[str, str]) -> list[str]:
    issues: list[str] = []
    if tuple(CATALOG.keys()) != _REQUIRED_IDS:
        issues.append("catalog must contain ordered R1-R39 exactly once")
    if tuple(titles.keys()) != _REQUIRED_IDS:
        issues.append("requirements baseline must contain ordered R1-R39 exactly once")

    for requirement_id in _REQUIRED_IDS:
        item = CATALOG.get(requirement_id)
        if item is None:
            continue
        status = item.get("status")
        if status not in STATUS_VOCABULARY:
            issues.append(f"{requirement_id}: invalid status {status!r}")
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            issues.append(f"{requirement_id}: evidence must be a non-empty list")
        else:
            for relative in evidence:
                if not isinstance(relative, str) or not relative:
                    issues.append(f"{requirement_id}: invalid evidence path {relative!r}")
                    continue
                if not (ROOT / relative).is_file():
                    issues.append(f"{requirement_id}: evidence path does not exist: {relative}")
        for field in ("gap", "closure"):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                issues.append(f"{requirement_id}: {field} must be non-empty")
        benchmarks = item.get("benchmarks")
        if not isinstance(benchmarks, list) or any(not isinstance(value, str) for value in benchmarks):
            issues.append(f"{requirement_id}: benchmarks must be a list of strings")
        features = item.get("features")
        if not isinstance(features, dict):
            issues.append(f"{requirement_id}: features must be a mapping")
        else:
            for name, classification in features.items():
                if not isinstance(name, str) or not name:
                    issues.append(f"{requirement_id}: feature names must be non-empty strings")
                if classification not in FEATURE_VOCABULARY:
                    issues.append(f"{requirement_id}: invalid feature classification {classification!r}")
        if status == "SATISFIED" and isinstance(features, dict) and "NOT_IMPLEMENTED" in features.values():
            issues.append(f"{requirement_id}: SATISFIED row cannot contain NOT_IMPLEMENTED feature evidence")
    return issues


def _delivery(task_id: str) -> dict[str, Any]:
    path = ROOT / "tasks" / task_id / "deliverable.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _delivery_issues(task_id: str, required_checks: tuple[str, ...]) -> list[str]:
    issues: list[str] = []
    try:
        delivery = _delivery(task_id)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{task_id}: delivery evidence unreadable: {exc}"]
    if delivery.get("status") != "DELIVERED":
        issues.append(f"{task_id}: delivery status is not DELIVERED")
    checks = {
        str(item.get("name")): str(item.get("result"))
        for item in delivery.get("validation", [])
        if isinstance(item, dict)
    }
    for name in required_checks:
        if checks.get(name) != "PASS":
            issues.append(f"{task_id}: required validation {name!r} is not PASS")
    return issues


def _honesty_issues() -> list[str]:
    issues: list[str] = []

    def status(requirement_id: str) -> str:
        return str(CATALOG[requirement_id]["status"])

    def feature(requirement_id: str, name: str) -> str | None:
        features = CATALOG[requirement_id]["features"]
        assert isinstance(features, dict)
        value = features.get(name)
        return str(value) if value is not None else None

    for requirement_id in ("R6", "R7", "R18", "R32"):
        if status(requirement_id) != "SATISFIED":
            issues.append(f"{requirement_id} must consume accepted exact transient release qualification")
    issues.extend(
        _delivery_issues(
            "bubble-transient-release-acceleration",
            ("B03-exact", "B07-exact", "B08-exact", "B12-exact"),
        )
    )

    if status("R28") != "UNVERIFIED":
        issues.append("R28 must remain UNVERIFIED until physical iPhone Safari evidence is archived")
    if feature("R28", "webkit_mobile_engine") != "RESOLVED":
        issues.append("R28 must consume Playwright WebKit mobile-engine evidence")
    if feature("R28", "physical_iphone_safari") != "NOT_IMPLEMENTED":
        issues.append("R28 must preserve the missing physical iPhone Safari qualification")
    if feature("R28", "native_hardware_multitouch") != "NOT_IMPLEMENTED":
        issues.append("R28 must preserve the missing native hardware multi-touch qualification")
    issues.extend(_delivery_issues("bubble-mobile-webkit-verification", ("real-webkit-mobile-e2e",)))

    if status("R8") != "SATISFIED" or feature("R8", "shared_film_transient_runtime") != "RESOLVED":
        issues.append("R8 must consume accepted canonical shared-film transient runtime evidence")
    if status("R9") != "SATISFIED" or feature("R9", "dynamic_multi_junction_runtime") != "RESOLVED":
        issues.append("R9 must consume accepted dynamic Plateau-network runtime evidence")
    issues.extend(
        _delivery_issues(
            "bubble-transient-network-runtime-integration",
            ("runtime-tests", "shared-film-e2e", "plateau-e2e", "forced-network-e2e"),
        )
    )
    issues.extend(
        _delivery_issues(
            "bubble-contact-runtime-integration",
            ("contact-runtime-tests", "contact-transition-e2e", "deterministic-repeat"),
        )
    )

    if status("R14") != "SATISFIED" or feature("R14", "contact_to_thinfilm_identity_handoff") != "RESOLVED":
        issues.append("R14 must consume accepted contact-to-thin-film integration evidence")
    if status("R15") != "SATISFIED" or feature("R15", "conservative_coalescence") != "RESOLVED":
        issues.append("R15 must consume accepted contact-created rupture/coalescence evidence")
    issues.extend(
        _delivery_issues(
            "bubble-contact-thinfilm-event-integration",
            ("integration unit tests", "drainage scenario CLI", "rupture scenario CLI", "runtime regression"),
        )
    )

    if status("R16") != "SATISFIED":
        issues.append("R16 must consume the accepted supported single-neck pinch-off foundation")
    if feature("R16", "production_fragmentation") != "RESOLVED":
        issues.append("R16 must consume accepted supported-class production fragmentation evidence")
    if feature("R16", "supported_axisymmetric_slender_neck_pinchoff") != "MODELED":
        issues.append("R16 supported axisymmetric slender-neck pinch-off must remain MODELED")
    if feature("R16", "deterministic_pinchoff_fragmentation_restart") != "RESOLVED":
        issues.append("R16 must consume the exact pinch-off to fragmentation/restart handoff")
    issues.extend(
        _delivery_issues(
            "bubble-fragmentation-production",
            ("fragmentation-unit-tests", "neck-split", "conservation", "refinement", "runtime-contract-export"),
        )
    )
    issues.extend(
        _delivery_issues(
            "bubble-postfragmentation-relaxation",
            ("postfragment-tests", "postfragment-e2e", "determinism", "runtime-regression"),
        )
    )
    issues.extend(
        _delivery_issues(
            "bubble-singular-breakup-cfd-foundation",
            ("neck-evolution", "pinchoff-refinement", "pinchoff-conservation", "runtime-handoff"),
        )
    )

    if status("R19") != "SATISFIED":
        issues.append("R19 must consume accepted live authoritative session transport")
    if feature("R19", "browser_live_solver_transport") != "RESOLVED":
        issues.append("R19 must classify the accepted loopback live transport as RESOLVED")
    issues.extend(
        _delivery_issues(
            "bubble-live-session-transport",
            ("server-unit", "transport-e2e", "viewer-typecheck-and-regression", "build", "security-goal-check"),
        )
    )

    if feature("R30", "same_build_checkpoint_restart") != "RESOLVED":
        issues.append("R30 must consume accepted same-build checkpoint/restart evidence")
    if feature("R30", "cross_version_checkpoint_portability") != "NOT_IMPLEMENTED":
        issues.append("R30 must not claim cross-version checkpoint portability")
    issues.extend(
        _delivery_issues(
            "bubble-checkpoint-restart",
            ("fresh-process-transient", "fresh-process-thinfilm"),
        )
    )

    if status("R4") != "SATISFIED" or feature("R4", "arbitrary_live_runtime_creation") != "RESOLVED":
        issues.append("R4 must consume accepted authoritative PAUSED-state live creation evidence")
    if status("R27") != "SATISFIED" or feature("R27", "live_runtime_bubble_editing") != "RESOLVED":
        issues.append("R27 must consume accepted ADD/DELETE/MOVE/RESIZE/SET-velocity live-edit evidence")
    issues.extend(
        _delivery_issues(
            "bubble-live-runtime-editing",
            ("final-declared-acceptance", "authoritative-continuation", "loopback-transport"),
        )
    )

    if status("R17") != "SATISFIED":
        issues.append("R17 must consume accepted canonical resolved no-slip wall runtime integration")
    if feature("R17", "resolved_no_slip_wall_cfd") != "RESOLVED":
        issues.append("R17 resolved no-slip wall CFD must be RESOLVED within the fixed-SDF supported class")
    if feature("R11", "resolved_bulk_wall_cfd") != "RESOLVED":
        issues.append("R11 must consume accepted resolved bulk fixed-SDF wall CFD evidence")
    issues.extend(
        _delivery_issues(
            "bubble-noslip-wall-runtime-integration",
            (
                "no-slip runtime unit tests",
                "no-slip runtime end-to-end probe",
                "boundary runtime regression",
                "runtime full regression",
            ),
        )
    )

    if feature("R11", "local_resolved_precontact_thin_gap_cfd") != "MODELED":
        issues.append("R11 must consume the supported-class local pre-contact CFD path as MODELED")
    if feature("R38", "local_resolved_precontact_thin_gap_cfd") != "MODELED":
        issues.append("R38 must expose local resolved pre-contact CFD without promoting it to a general solver")
    issues.extend(
        _delivery_issues(
            "bubble-precontact-multiregion-cfd-foundation",
            (
                "precontact-cfd-unit-tests",
                "squeeze-benchmark",
                "refinement-benchmark",
                "feedback-benchmark",
                "precontact-cfd-runtime-e2e",
                "full-runtime-regression",
            ),
        )
    )

    if feature("R11", "supported_global_two_bubble_single_gap_multiregion_cfd") != "MODELED":
        issues.append("R11 must consume Wave-17 supported global two-bubble/single-gap CFD as MODELED")
    if feature("R38", "supported_global_two_bubble_single_gap_multiregion_cfd") != "MODELED":
        issues.append("R38 must consume Wave-17 supported global two-bubble/single-gap CFD as MODELED")
    if feature("R38", "global_full_domain_multiregion_cfd") != "NOT_IMPLEMENTED":
        issues.append("R38 must not promote supported two-bubble CFD to universal full-domain multiphase CFD")
    if feature("R38", "arbitrary_multigap_manybubble_t1_cfd") != "NOT_IMPLEMENTED":
        issues.append("R38 must preserve the arbitrary simultaneous multi-gap/many-bubble/T1 CFD limitation")
    issues.extend(
        _delivery_issues(
            "bubble-global-multiregion-cfd-coupling",
            ("field-refinement", "mass-momentum-balance", "front-feedback", "runtime-e2e"),
        )
    )

    issues.extend(
        _delivery_issues(
            "bubble-t1-production-foundation",
            ("t1-unit", "t1-switch", "t1-conservation", "t1-refinement", "network-regression"),
        )
    )
    if feature("R9", "bounded_genuine_non_coplanar_3d_t1") != "RESOLVED":
        issues.append("R9 must consume the accepted bounded genuinely non-coplanar 3D T1 foundation")
    if feature("R38", "bounded_genuine_non_coplanar_3d_t1") != "RESOLVED":
        issues.append("R38 must consume the accepted bounded genuinely non-coplanar 3D T1 foundation")
    if feature("R38", "general_3d_t1") != "NOT_IMPLEMENTED":
        issues.append("R38 must preserve the unrestricted arbitrary-admissible 3D T1 limitation")
    issues.extend(
        _delivery_issues(
            "bubble-general-3d-t1-foundation",
            ("t1-3d-switch", "t1-3d-conservation", "t1-3d-refinement", "t1-3d-runtime-transition"),
        )
    )

    if feature("R38", "supported_axisymmetric_slender_neck_pinchoff") != "MODELED":
        issues.append("R38 must consume supported axisymmetric slender-neck pinch-off as MODELED")
    if feature("R38", "deterministic_pinchoff_fragmentation_restart") != "RESOLVED":
        issues.append("R38 must consume deterministic pinch-off fragmentation/restart handoff")
    if feature("R38", "retracting_rim_ligament_droplet_spray") != "NOT_IMPLEMENTED":
        issues.append("R38 must preserve retracting-rim/ligament/droplet-spray limitations")
    if feature("R38", "unrestricted_3d_multineck_pinchoff") != "NOT_IMPLEMENTED":
        issues.append("R38 must preserve unrestricted 3D/multi-neck singular breakup limitations")

    if status("R38") == "SATISFIED":
        issues.append("R38 cannot be SATISFIED while physical iPhone hardware qualification remains missing")
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
        if feature("R38", name) != "RESOLVED":
            issues.append(f"R38 must consume accepted resolved feature {name}")
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
        if feature("R38", name) != "NOT_IMPLEMENTED":
            issues.append(f"R38 must preserve unresolved feature {name}")

    return issues


def integrity_issues(*, assert_honest: bool = False) -> list[str]:
    titles = _requirement_titles()
    issues = _validate_catalog(titles)
    if assert_honest:
        issues.extend(_honesty_issues())
    return issues


def _status_counts(catalog: dict[str, dict[str, object]]) -> dict[str, int]:
    counts = Counter(str(catalog[requirement_id]["status"]) for requirement_id in _REQUIRED_IDS)
    return {name: counts.get(name, 0) for name in STATUS_VOCABULARY}


def _status_changes() -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for requirement_id in _REQUIRED_IDS:
        previous = WAVE15_CATALOG[requirement_id]
        current = CATALOG[requirement_id]
        old_status = str(previous["status"])
        new_status = str(current["status"])
        if old_status == new_status:
            continue
        previous_evidence = set(str(path) for path in previous["evidence"])
        evidence_added = [str(path) for path in current["evidence"] if str(path) not in previous_evidence]
        changes.append(
            {
                "requirement_id": requirement_id,
                "from": old_status,
                "to": new_status,
                "evidence_added": evidence_added,
                "new_gap_statement": str(current["gap"]),
            }
        )
    return changes


def build_audit(*, assert_honest: bool = False) -> dict[str, Any]:
    issues = integrity_issues(assert_honest=assert_honest)
    if issues:
        raise AuditIntegrityError("; ".join(issues))

    titles = _requirement_titles()
    rows: list[dict[str, Any]] = []
    for requirement_id in _REQUIRED_IDS:
        source = CATALOG[requirement_id]
        rows.append(
            {
                "requirement_id": requirement_id,
                "title": titles[requirement_id],
                "status": source["status"],
                "evidence": list(source["evidence"]),
                "benchmarks": list(source["benchmarks"]),
                "features": dict(sorted(dict(source["features"]).items())),
                "gap": source["gap"],
                "closure": source["closure"],
            }
        )

    counts = Counter(row["status"] for row in rows)
    incomplete = [row["requirement_id"] for row in rows if row["status"] != "SATISFIED"]
    status_changes = _status_changes()
    return {
        "schema_version": 4,
        "audit": "bubble-lab-r1-r39-completion-gap-audit",
        "source_requirements": "orchestra/REQUIREMENTS.md",
        "baseline": "post-wave-17 accepted main",
        "previous_baseline": "post-wave-15 accepted main / Wave-15 completion audit",
        "status_vocabulary": list(STATUS_VOCABULARY),
        "feature_vocabulary": list(FEATURE_VOCABULARY),
        "rows": rows,
        "summary": {
            "requirement_count": len(rows),
            "previous_status_counts": _status_counts(WAVE15_CATALOG),
            "status_counts": {name: counts.get(name, 0) for name in STATUS_VOCABULARY},
            "satisfied_count": counts.get("SATISFIED", 0),
            "status_changes": status_changes,
            "incomplete_requirement_ids": incomplete,
            "final_acceptance_ready": not incomplete,
            "final_acceptance_reason": (
                "All R1-R39 requirements are satisfied."
                if not incomplete
                else "Incomplete requirements remain: " + ", ".join(incomplete) + "."
            ),
            "known_blockers": [
                "physical iPhone Safari/device-GPU/native hardware multi-touch qualification",
                "arbitrary simultaneous multi-gap/many-bubble/T1 CFD and universal full-domain multiphase Navier-Stokes beyond the supported global two-bubble/single-gap class",
                "unrestricted arbitrary-admissible 3D T1 beyond the bounded genuinely non-coplanar supported subclass",
                "retracting-rim/ligament/droplet-spray and unrestricted fully resolved 3D or arbitrary multi-neck breakup beyond the supported axisymmetric slender-neck path",
                "arbitrary live-edit surgery through pre-existing shared-film/network/T1/thin-film/event states",
                "complete reusable many-bubble/network scenario family and remaining high-end runtime-control combinations",
            ],
        },
    }


def render_markdown(audit: dict[str, Any]) -> str:
    summary = audit["summary"]
    lines = [
        "# Bubble Lab R1-R39 Completion Gap Audit",
        "",
        "This report is generated deterministically from the accepted post-Wave-17 repository evidence. Accepted task labels or visual appearance alone are not treated as proof of physical completion.",
        "",
        f"Requirements audited: **{summary['requirement_count']}**",
        f"Satisfied: **{summary['satisfied_count']}**",
        f"Final acceptance ready: **{'yes' if summary['final_acceptance_ready'] else 'no'}**",
        f"Reason: {summary['final_acceptance_reason']}",
        "",
        "## Old vs new status counts",
        "",
        "| Status | Post-Wave-15 | Post-Wave-17 |",
        "|---|---:|---:|",
    ]
    for name in STATUS_VOCABULARY:
        lines.append(
            f"| {name} | {summary['previous_status_counts'][name]} | {summary['status_counts'][name]} |"
        )

    lines.extend(["", "## Status changes", ""])
    if not summary["status_changes"]:
        lines.append("- None.")
    for change in summary["status_changes"]:
        evidence = ", ".join(f"`{path}`" for path in change["evidence_added"]) or "no new path"
        lines.append(
            f"- **{change['requirement_id']}**: {change['from']} -> {change['to']}; new evidence: {evidence}"
        )

    lines.extend(["", "## Known blockers", ""])
    for blocker in summary["known_blockers"]:
        lines.append(f"- {blocker}")

    lines.extend([
        "",
        "## Requirement matrix",
        "",
        "| ID | Requirement | Status | Benchmarks |",
        "|---|---|---|---|",
    ])
    for item in audit["rows"]:
        benchmarks = ", ".join(item["benchmarks"]) or "—"
        lines.append(f"| {item['requirement_id']} | {item['title']} | {item['status']} | {benchmarks} |")

    lines.extend(["", "## Evidence and closure detail", ""])
    for item in audit["rows"]:
        lines.append(f"### {item['requirement_id']} — {item['title']} — {item['status']}")
        lines.append("")
        lines.append("Evidence:")
        for path in item["evidence"]:
            lines.append(f"- `{path}`")
        if item["features"]:
            lines.append("")
            lines.append("Feature classification:")
            for name, classification in item["features"].items():
                lines.append(f"- `{name}`: **{classification}**")
        lines.extend([
            "",
            f"Gap: {item['gap']}",
            "",
            f"Closure: {item['closure']}",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"
