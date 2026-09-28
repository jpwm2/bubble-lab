"""Post-Wave-23 R1-R39 completion audit preserving the historical Wave-21 audit."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from . import audit as legacy
from .wave21_catalog import CATALOG as WAVE21_CATALOG
from .wave23_catalog import CATALOG as WAVE23_CATALOG

AuditIntegrityError = legacy.AuditIntegrityError
ROOT = legacy.ROOT
STATUS_VOCABULARY = legacy.STATUS_VOCABULARY
FEATURE_VOCABULARY = legacy.FEATURE_VOCABULARY


@contextmanager
def _wave23_catalog_context() -> Iterator[None]:
    previous_catalog = legacy.CATALOG
    previous_baseline = legacy.WAVE15_CATALOG
    legacy.CATALOG = WAVE23_CATALOG
    legacy.WAVE15_CATALOG = WAVE21_CATALOG
    try:
        yield
    finally:
        legacy.CATALOG = previous_catalog
        legacy.WAVE15_CATALOG = previous_baseline


def _wave23_honesty_issues() -> list[str]:
    issues: list[str] = []

    def status(requirement_id: str) -> str:
        return str(WAVE23_CATALOG[requirement_id]["status"])

    def feature(requirement_id: str, name: str) -> str | None:
        features = WAVE23_CATALOG[requirement_id]["features"]
        assert isinstance(features, dict)
        value = features.get(name)
        return str(value) if value is not None else None

    for requirement_id in ("R16", "R38"):
        if feature(requirement_id, "bounded_asymmetric_multimode_rim_breakup") != "MODELED":
            issues.append(f"{requirement_id} must consume asymmetric multimode rim breakup only as MODELED")
    if feature("R16", "state_derived_multimode_droplet_handoff") != "RESOLVED":
        issues.append("R16 must retain the deterministic state-derived multimode droplet handoff")
    issues.extend(
        legacy._delivery_issues(
            "bubble-asymmetric-multimode-rim-breakup-foundation",
            (
                "rim-breakup-unit",
                "asymmetric-retraction",
                "mode-competition",
                "liquid-conservation",
                "constitutive-response",
                "breakup-refinement",
                "deterministic-replay",
                "runtime-handoff",
            ),
        )
    )

    for requirement_id in ("R9", "R10", "R11", "R38"):
        if feature(requirement_id, "bounded_dynamic_plateau_border_hydrodynamics") != "MODELED":
            issues.append(f"{requirement_id} must consume dynamic Plateau-border hydrodynamics only as MODELED")
    issues.extend(
        legacy._delivery_issues(
            "bubble-plateau-border-hydrodynamics-foundation",
            (
                "plateau-border-unit",
                "border-force-balance",
                "border-conservation",
                "border-response",
                "border-refinement",
                "t1-coupling",
                "runtime-e2e",
            ),
        )
    )

    for requirement_id in ("R10", "R11", "R20", "R38"):
        if feature(requirement_id, "bounded_strongly_coupled_t1_global_cfd") != "MODELED":
            issues.append(f"{requirement_id} must consume strong T1/global-CFD only as MODELED")
    for requirement_id in ("R11", "R38"):
        if feature(requirement_id, "bounded_causal_cfd_t1_timing_feedback") != "MODELED":
            issues.append(f"{requirement_id} must retain bounded causal CFD timing feedback as MODELED")
    issues.extend(
        legacy._delivery_issues(
            "bubble-strongly-coupled-t1-global-cfd-foundation",
            (
                "multiregion-unit",
                "strong-feedback",
                "strong-conservation",
                "strong-refinement",
                "strong-symmetry",
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
            issues.append(f"R38 must preserve unrestricted Wave-23 boundary: {name}")

    if status("R28") != "UNVERIFIED":
        issues.append("R28 must remain UNVERIFIED without physical iPhone Safari evidence")
    if status("R38") != "PARTIAL":
        issues.append("R38 must remain PARTIAL while direct physical-device qualification is absent")
    return issues


def integrity_issues(*, assert_honest: bool = False) -> list[str]:
    with _wave23_catalog_context():
        issues = legacy.integrity_issues(assert_honest=assert_honest)
    if assert_honest:
        issues.extend(_wave23_honesty_issues())
    return issues


def build_audit(*, assert_honest: bool = False) -> dict[str, Any]:
    issues = integrity_issues(assert_honest=assert_honest)
    if issues:
        raise AuditIntegrityError("; ".join(issues))
    with _wave23_catalog_context():
        result = legacy.build_audit(assert_honest=False)
    result["schema_version"] = 7
    result["baseline"] = "post-wave-23 accepted main"
    result["previous_baseline"] = "post-wave-21 accepted main / Wave-21 completion audit"
    result["summary"]["known_blockers"] = [
        "physical iPhone Safari/device-GPU/native hardware multi-touch qualification",
        "unrestricted repeated/arbitrary topology-changing gas transport beyond the accepted isolated four-region class",
        "arbitrary-contact/global multiphase Navier-Stokes and singular Plateau-border/liquid-border CFD beyond accepted bounded shared-field/reduced-order classes",
        "unrestricted arbitrary-admissible or continuum/singular 3D T1 liquid-border hydrodynamics beyond accepted bounded direct-geometry/shared-field/reduced-order closures",
        "arbitrary 3D multi-hole/multi-neck rupture, fully resolved singular ligament pinch-off, broad spray distributions, turbulent atomization, secondary breakup and general droplet CFD",
        "arbitrary/deforming moving-wall CFD beyond fixed SDF stationary/uniform wall velocity",
        "arbitrary live-edit surgery through pre-existing shared-film/network/T1/thin-film/event states",
        "complete reusable many-bubble/network scenario family and remaining high-end runtime-control combinations",
    ]
    return result


def render_markdown(audit: dict[str, Any]) -> str:
    summary = audit["summary"]
    lines = [
        "# Bubble Lab R1-R39 Completion Gap Audit",
        "",
        "This report is generated deterministically from the accepted post-Wave-23 repository evidence. "
        "Accepted task labels, visual appearance, or bounded subclass evidence are not promoted beyond their measured scope.",
        "",
        f"Requirements audited: **{summary['requirement_count']}**",
        f"Satisfied: **{summary['satisfied_count']}**",
        f"Final acceptance ready: **{'yes' if summary['final_acceptance_ready'] else 'no'}**",
        f"Reason: {summary['final_acceptance_reason']}",
        "",
        "## Old vs new status counts",
        "",
        "| Status | Post-Wave-21 | Post-Wave-23 |",
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
