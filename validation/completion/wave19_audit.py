"""Post-Wave-19 R1-R39 completion audit without mutating the historical Wave-17 audit."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from . import audit as legacy
from .wave17_catalog import CATALOG as WAVE17_CATALOG
from .wave19_catalog import CATALOG as WAVE19_CATALOG

AuditIntegrityError = legacy.AuditIntegrityError
ROOT = legacy.ROOT
STATUS_VOCABULARY = legacy.STATUS_VOCABULARY
FEATURE_VOCABULARY = legacy.FEATURE_VOCABULARY


@contextmanager
def _wave19_catalog_context() -> Iterator[None]:
    previous_catalog = legacy.CATALOG
    previous_baseline = legacy.WAVE15_CATALOG
    legacy.CATALOG = WAVE19_CATALOG
    legacy.WAVE15_CATALOG = WAVE17_CATALOG
    try:
        yield
    finally:
        legacy.CATALOG = previous_catalog
        legacy.WAVE15_CATALOG = previous_baseline


def _wave19_honesty_issues() -> list[str]:
    issues: list[str] = []

    def status(requirement_id: str) -> str:
        return str(WAVE19_CATALOG[requirement_id]["status"])

    def feature(requirement_id: str, name: str) -> str | None:
        features = WAVE19_CATALOG[requirement_id]["features"]
        assert isinstance(features, dict)
        value = features.get(name)
        return str(value) if value is not None else None

    if status("R13") != "SATISFIED":
        issues.append("R13 must consume the accepted many-bubble pressure-driven gas-diffusion network")
    for name, expected in (
        ("supported_manybubble_pressure_driven_gas_network", "MODELED"),
        ("network_pressure_amount_volume_feedback", "MODELED"),
        ("deterministic_conservative_network_runtime", "RESOLVED"),
        ("gas_transfer_enable_disable", "RESOLVED"),
    ):
        if feature("R13", name) != expected:
            issues.append(f"R13 Wave-19 gas-network feature {name} must be {expected}")
    issues.extend(
        legacy._delivery_issues(
            "bubble-manybubble-gas-diffusion-network",
            ("gas-network-unit-tests", "conservation", "coarsening", "refinement", "runtime-e2e"),
        )
    )

    for requirement_id in ("R11", "R38"):
        if feature(requirement_id, "bounded_three_bubble_two_gap_global_cfd") != "MODELED":
            issues.append(f"{requirement_id} must consume the bounded three-bubble/two-gap global CFD foundation as MODELED")
    for name in ("global_full_domain_multiregion_cfd", "arbitrary_multigap_manybubble_t1_cfd"):
        if feature("R38", name) != "NOT_IMPLEMENTED":
            issues.append(f"R38 must preserve the unrestricted global-CFD limitation {name}")
    for name in ("t1_through_global_cfd", "overlapping_immersed_supports"):
        if feature("R38", name) != "NOT_IMPLEMENTED":
            issues.append(f"R38 must preserve the Wave-19 multigap-CFD boundary {name}")
    issues.extend(
        legacy._delivery_issues(
            "bubble-multigap-manybubble-cfd-foundation",
            (
                "multigap-cfd-unit",
                "multigap-refinement",
                "multigap-mass-momentum",
                "multifront-feedback",
                "permutation-symmetry",
                "runtime-e2e",
            ),
        )
    )

    for requirement_id in ("R9", "R38"):
        if feature(requirement_id, "bounded_direct_geometry_3d_t1_hydrodynamics") != "MODELED":
            issues.append(f"{requirement_id} must consume bounded direct-geometry 3D T1 hydrodynamics as MODELED")
    if feature("R38", "general_3d_t1") != "NOT_IMPLEMENTED":
        issues.append("R38 must not promote bounded direct-geometry 3D T1 to unrestricted arbitrary-admissible 3D T1")
    if feature("R38", "unrestricted_topology_changing_gas_diffusion") != "NOT_IMPLEMENTED":
        issues.append("R38 must preserve the unsupported topology-changing gas-diffusion boundary")
    issues.extend(
        legacy._delivery_issues(
            "bubble-direct-3d-t1-hydrodynamics",
            (
                "direct-t1-unit",
                "direct-t1-switch",
                "direct-t1-conservation",
                "direct-t1-refinement",
                "direct-t1-rotation",
                "direct-t1-runtime-transition",
            ),
        )
    )
    return issues


def integrity_issues(*, assert_honest: bool = False) -> list[str]:
    with _wave19_catalog_context():
        issues = legacy.integrity_issues(assert_honest=assert_honest)
    if assert_honest:
        issues.extend(_wave19_honesty_issues())
    return issues


def build_audit(*, assert_honest: bool = False) -> dict[str, Any]:
    issues = integrity_issues(assert_honest=assert_honest)
    if issues:
        raise AuditIntegrityError("; ".join(issues))
    with _wave19_catalog_context():
        result = legacy.build_audit(assert_honest=False)
    result["schema_version"] = 5
    result["baseline"] = "post-wave-19 accepted main"
    result["previous_baseline"] = "post-wave-17 accepted main / Wave-17 completion audit"
    result["summary"]["known_blockers"] = [
        "physical iPhone Safari/device-GPU/native hardware multi-touch qualification",
        "T1-through-global-CFD, overlapping immersed supports and universal sharp moving-interface multiphase CFD beyond the bounded separated-support three-bubble/two-gap class",
        "unrestricted topology-changing gas diffusion beyond the accepted fixed-topology many-bubble shared-film network",
        "unrestricted arbitrary-admissible or continuum/singular 3D T1 liquid-border hydrodynamics beyond the bounded direct-geometry closure",
        "retracting-rim/ligament/droplet-spray and unrestricted fully resolved 3D or arbitrary multi-neck breakup beyond the supported axisymmetric slender-neck path",
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
        "This report is generated deterministically from the accepted post-Wave-19 repository evidence. Accepted task labels, visual appearance, or bounded subclass evidence are not promoted beyond their measured scope.",
        "",
        f"Requirements audited: **{summary['requirement_count']}**",
        f"Satisfied: **{summary['satisfied_count']}**",
        f"Final acceptance ready: **{'yes' if summary['final_acceptance_ready'] else 'no'}**",
        f"Reason: {summary['final_acceptance_reason']}",
        "",
        "## Old vs new status counts",
        "",
        "| Status | Post-Wave-17 | Post-Wave-19 |",
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
