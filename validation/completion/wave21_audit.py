"""Post-Wave-21 R1-R39 completion audit preserving the historical Wave-19 audit."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from . import audit as legacy
from .wave19_catalog import CATALOG as WAVE19_CATALOG
from .wave21_catalog import CATALOG as WAVE21_CATALOG

AuditIntegrityError = legacy.AuditIntegrityError
ROOT = legacy.ROOT
STATUS_VOCABULARY = legacy.STATUS_VOCABULARY
FEATURE_VOCABULARY = legacy.FEATURE_VOCABULARY


@contextmanager
def _wave21_catalog_context() -> Iterator[None]:
    previous_catalog = legacy.CATALOG
    previous_baseline = legacy.WAVE15_CATALOG
    legacy.CATALOG = WAVE21_CATALOG
    legacy.WAVE15_CATALOG = WAVE19_CATALOG
    try:
        yield
    finally:
        legacy.CATALOG = previous_catalog
        legacy.WAVE15_CATALOG = previous_baseline


def _wave21_honesty_issues() -> list[str]:
    issues: list[str] = []

    def status(requirement_id: str) -> str:
        return str(WAVE21_CATALOG[requirement_id]["status"])

    def feature(requirement_id: str, name: str) -> str | None:
        features = WAVE21_CATALOG[requirement_id]["features"]
        assert isinstance(features, dict)
        value = features.get(name)
        return str(value) if value is not None else None

    if feature("R13", "bounded_topology_changing_gas_transport") != "MODELED":
        issues.append("R13 must consume the bounded topology-changing gas-transport T1 as MODELED")
    if feature("R13", "t1_gas_state_preservation") != "RESOLVED":
        issues.append("R13 must preserve gas state across the accepted T1 transaction")
    issues.extend(
        legacy._delivery_issues(
            "bubble-topology-changing-gas-transport",
            (
                "gas-network-unit",
                "t1-graph-switch",
                "topology-conservation",
                "post-t1-transfer",
                "deterministic-replay",
                "runtime-e2e",
            ),
        )
    )

    for requirement_id in ("R11", "R38"):
        if feature(requirement_id, "bounded_t1_through_global_cfd") != "MODELED":
            issues.append(f"{requirement_id} must consume bounded T1-through-global-CFD as MODELED")
        if feature(requirement_id, "bounded_overlapping_immersed_supports") != "MODELED":
            issues.append(f"{requirement_id} must consume measured overlapping-support treatment as MODELED")
    for name in ("t1_through_global_cfd", "overlapping_immersed_supports"):
        if feature("R38", name) != "NOT_IMPLEMENTED":
            issues.append(f"R38 must preserve the unrestricted Wave-21 global-CFD boundary {name}")
    issues.extend(
        legacy._delivery_issues(
            "bubble-t1-through-global-cfd-foundation",
            (
                "multiregion-unit",
                "overlap-support",
                "t1-field-transition",
                "t1-cfd-conservation",
                "t1-cfd-refinement",
                "t1-cfd-symmetry",
                "runtime-e2e",
            ),
        )
    )

    for requirement_id in ("R16", "R38"):
        if feature(requirement_id, "bounded_retracting_rim_ligament_droplet_detachment") != "MODELED":
            issues.append(f"{requirement_id} must consume bounded rim/ligament/droplet detachment as MODELED")
    if feature("R16", "deterministic_rim_breakup_runtime_handoff") != "RESOLVED":
        issues.append("R16 must consume the deterministic evolved-state droplet runtime handoff")
    for name in ("retracting_rim_ligament_droplet_spray", "unrestricted_3d_multineck_pinchoff"):
        if feature("R38", name) != "NOT_IMPLEMENTED":
            issues.append(f"R38 must preserve the unrestricted breakup boundary {name}")
    issues.extend(
        legacy._delivery_issues(
            "bubble-retracting-rim-ligament-droplet-foundation",
            (
                "rim-breakup-unit",
                "rim-retraction",
                "ligament-growth",
                "liquid-conservation",
                "breakup-refinement",
                "deterministic-replay",
                "runtime-handoff",
            ),
        )
    )

    if status("R28") != "UNVERIFIED":
        issues.append("R28 must remain UNVERIFIED without physical iPhone Safari evidence")
    if status("R38") != "PARTIAL":
        issues.append("R38 must remain PARTIAL while direct physical-device qualification is absent")
    return issues


def integrity_issues(*, assert_honest: bool = False) -> list[str]:
    with _wave21_catalog_context():
        issues = legacy.integrity_issues(assert_honest=assert_honest)
    if assert_honest:
        issues.extend(_wave21_honesty_issues())
    return issues


def build_audit(*, assert_honest: bool = False) -> dict[str, Any]:
    issues = integrity_issues(assert_honest=assert_honest)
    if issues:
        raise AuditIntegrityError("; ".join(issues))
    with _wave21_catalog_context():
        result = legacy.build_audit(assert_honest=False)
    result["schema_version"] = 6
    result["baseline"] = "post-wave-21 accepted main"
    result["previous_baseline"] = "post-wave-19 accepted main / Wave-19 completion audit"
    result["summary"]["known_blockers"] = [
        "physical iPhone Safari/device-GPU/native hardware multi-touch qualification",
        "unrestricted repeated/arbitrary topology-changing gas transport beyond the accepted isolated four-region T1",
        "arbitrary-contact/global multiphase Navier-Stokes, singular Plateau-border/liquid-border CFD and strongly hydrodynamically delayed T1 beyond the accepted bounded four-region shared-field class",
        "unrestricted arbitrary-admissible or continuum/singular 3D T1 liquid-border hydrodynamics beyond accepted bounded direct-geometry/shared-field closures",
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
        "This report is generated deterministically from the accepted post-Wave-21 repository evidence. Accepted task labels, visual appearance, or bounded subclass evidence are not promoted beyond their measured scope.",
        "",
        f"Requirements audited: **{summary['requirement_count']}**",
        f"Satisfied: **{summary['satisfied_count']}**",
        f"Final acceptance ready: **{'yes' if summary['final_acceptance_ready'] else 'no'}**",
        f"Reason: {summary['final_acceptance_reason']}",
        "",
        "## Old vs new status counts",
        "",
        "| Status | Post-Wave-19 | Post-Wave-21 |",
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
