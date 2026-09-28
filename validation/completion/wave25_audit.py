"""Post-Wave-25 R1-R39 completion audit preserving the historical Wave-23 audit."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from . import audit as legacy
from .wave23_catalog import CATALOG as WAVE23_CATALOG
from .wave25_catalog import CATALOG as WAVE25_CATALOG

AuditIntegrityError = legacy.AuditIntegrityError
ROOT = legacy.ROOT
STATUS_VOCABULARY = legacy.STATUS_VOCABULARY
FEATURE_VOCABULARY = legacy.FEATURE_VOCABULARY


@contextmanager
def _wave25_catalog_context() -> Iterator[None]:
    previous_catalog = legacy.CATALOG
    previous_baseline = legacy.WAVE15_CATALOG
    legacy.CATALOG = WAVE25_CATALOG
    legacy.WAVE15_CATALOG = WAVE23_CATALOG
    try:
        yield
    finally:
        legacy.CATALOG = previous_catalog
        legacy.WAVE15_CATALOG = previous_baseline


def _wave25_honesty_issues() -> list[str]:
    issues: list[str] = []

    def status(requirement_id: str) -> str:
        return str(WAVE25_CATALOG[requirement_id]["status"])

    def feature(requirement_id: str, name: str) -> str | None:
        features = WAVE25_CATALOG[requirement_id]["features"]
        assert isinstance(features, dict)
        value = features.get(name)
        return str(value) if value is not None else None

    for requirement_id in ("R1", "R13", "R35", "R38", "R39"):
        if feature(requirement_id, "bounded_repeated_t1_gas_transport") != "MODELED":
            issues.append(f"{requirement_id} must consume repeated-T1 gas transport only as MODELED")
    if feature("R12", "repeated_t1_stable_gas_identity") != "RESOLVED":
        issues.append("R12 must retain stable gas identity through the accepted repeated T1 sequence")
    if feature("R13", "repeated_post_topology_transport_rebuild") != "RESOLVED":
        issues.append("R13 must retain transport-edge rebuild from each accepted post-T1 topology")
    issues.extend(
        legacy._delivery_issues(
            "bubble-repeated-t1-gas-transport-foundation",
            (
                "gas-network-unit",
                "repeated-t1-switch",
                "repeated-topology-conservation",
                "second-event-dependence",
                "repeated-post-event-transfer",
                "repeated-topology-replay",
                "runtime-e2e",
            ),
        )
    )

    for requirement_id in ("R1", "R10", "R16", "R35", "R38", "R39"):
        if feature(requirement_id, "bounded_interacting_multihole_breakup") != "MODELED":
            issues.append(f"{requirement_id} must consume interacting multi-hole breakup only as MODELED")
    if feature("R16", "state_derived_interacting_multihole_fragments") != "RESOLVED":
        issues.append("R16 must retain state-derived interacting multi-hole fragment handoff")
    issues.extend(
        legacy._delivery_issues(
            "bubble-interacting-multihole-breakup-foundation",
            (
                "rim-breakup-unit",
                "multihole-interaction",
                "multihole-mode-coupling",
                "multihole-conservation",
                "multihole-response",
                "multihole-refinement",
                "multihole-replay",
                "runtime-handoff",
            ),
        )
    )

    for requirement_id in ("R1", "R10", "R11", "R20", "R35", "R38", "R39"):
        if feature(requirement_id, "bounded_manycontact_t1_global_cfd") != "MODELED":
            issues.append(f"{requirement_id} must consume many-contact T1/global-CFD only as MODELED")
    for requirement_id in ("R11", "R38"):
        if feature(requirement_id, "bounded_non_event_contact_causality") != "MODELED":
            issues.append(f"{requirement_id} must retain bounded non-event-contact causality as MODELED")
    if feature("R20", "manycontact_refinement_feedback_gates") != "RESOLVED":
        issues.append("R20 must retain the accepted many-contact refinement/feedback gates")
    issues.extend(
        legacy._delivery_issues(
            "bubble-manycontact-t1-global-cfd-foundation",
            (
                "multiregion-unit",
                "manycontact-feedback",
                "manycontact-causality",
                "manycontact-conservation",
                "manycontact-refinement",
                "manycontact-symmetry",
                "runtime-e2e",
            ),
        )
    )

    r38_unrestricted = (
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
    )
    for name in r38_unrestricted:
        if feature("R38", name) != "NOT_IMPLEMENTED":
            issues.append(f"R38 must preserve unrestricted Wave-25 boundary: {name}")

    expected_partial = ("R1", "R10", "R11", "R20", "R30", "R35", "R38", "R39")
    for requirement_id in expected_partial:
        if status(requirement_id) != "PARTIAL":
            issues.append(f"{requirement_id} must remain PARTIAL unless broader evidence closes its full requirement")
    if status("R28") != "UNVERIFIED":
        issues.append("R28 must remain UNVERIFIED without physical iPhone Safari evidence")
    return issues


def integrity_issues(*, assert_honest: bool = False) -> list[str]:
    with _wave25_catalog_context():
        issues = legacy.integrity_issues(assert_honest=assert_honest)
    if assert_honest:
        issues.extend(_wave25_honesty_issues())
    return issues


def build_audit(*, assert_honest: bool = False) -> dict[str, Any]:
    issues = integrity_issues(assert_honest=assert_honest)
    if issues:
        raise AuditIntegrityError("; ".join(issues))
    with _wave25_catalog_context():
        result = legacy.build_audit(assert_honest=False)
    result["schema_version"] = 8
    result["baseline"] = "post-wave-25 accepted main"
    result["previous_baseline"] = "post-wave-23 accepted main / Wave-23 completion audit"
    result["summary"]["known_blockers"] = [
        "physical iPhone Safari/device-GPU/native hardware multi-touch qualification",
        "arbitrary repeated topology surgery and topology classes beyond the accepted two-dependent-T1 six-region gas history",
        "arbitrary-contact/universal multiphase Navier-Stokes and singular Plateau-border/liquid-border CFD beyond accepted bounded shared-field/reduced-order classes",
        "unrestricted 3D multi-hole/multi-neck breakup, grid-resolved singular ligament pinch-off, broad spray distributions, turbulent atomization, secondary breakup and general droplet CFD",
        "arbitrary/deforming moving-wall CFD beyond accepted fixed-SDF/stationary-or-uniform wall classes",
        "arbitrary live-edit surgery through pre-existing shared-film/network/T1/thin-film/event states",
        "cross-version checkpoint portability, complete reusable many-bubble/network scenario breadth and remaining high-end runtime-control combinations",
    ]
    return result


def render_markdown(audit: dict[str, Any]) -> str:
    summary = audit["summary"]
    lines = [
        "# Bubble Lab R1-R39 Completion Gap Audit",
        "",
        "This report is generated deterministically from accepted post-Wave-25 repository evidence. "
        "Bounded Wave-25 subclasses are not promoted beyond their measured scope.",
        "",
        f"Requirements audited: **{summary['requirement_count']}**",
        f"Satisfied: **{summary['satisfied_count']}**",
        f"Final acceptance ready: **{'yes' if summary['final_acceptance_ready'] else 'no'}**",
        f"Reason: {summary['final_acceptance_reason']}",
        "",
        "## Old vs new status counts",
        "",
        "| Status | Post-Wave-23 | Post-Wave-25 |",
        "|---|---:|---:|",
    ]
    for name in STATUS_VOCABULARY:
        lines.append(f"| {name} | {summary['previous_status_counts'][name]} | {summary['status_counts'][name]} |")

    lines.extend(["", "## Status changes", ""])
    if not summary["status_changes"]:
        lines.append("- None.")
    for change in summary["status_changes"]:
        evidence = ", ".join(f"`{path}`" for path in change["evidence_added"]) or "no new path"
        lines.append(f"- **{change['requirement_id']}**: {change['from']} -> {change['to']}; new evidence: {evidence}")

    lines.extend(["", "## Known blockers", ""])
    for blocker in summary["known_blockers"]:
        lines.append(f"- {blocker}")

    lines.extend(["", "## Requirement matrix", "", "| ID | Requirement | Status | Benchmarks |", "|---|---|---|---|"])
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
        lines.extend(["", f"Gap: {item['gap']}", "", f"Closure: {item['closure']}", ""])
    return "\n".join(lines).rstrip() + "\n"
