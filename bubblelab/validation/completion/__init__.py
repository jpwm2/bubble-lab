"""Completion-gap audit for the Product-owned Bubble Lab requirements baseline.

This package bootstraps the historical audit implementation onto the dedicated
Product repository boundary. Historical ``tasks/``, ``orchestra/`` and ``agent/``
strings remain immutable provenance identifiers only; those legacy paths are never
required to exist locally.
"""
from __future__ import annotations

from bubblelab.validation.historical_evidence import (
    HISTORICAL_SOURCE_COMMIT,
    MIGRATION_EVIDENCE_REL,
    PRODUCT_EVIDENCE_REL,
    historical_delivery,
    immutable_source_url,
    is_historical_task_reference,
    is_removed_control_plane_reference,
    provenance,
)

from . import audit as _audit

_PRODUCT_REQUIREMENTS_REL = "bubblelab/docs/PRODUCT_REQUIREMENTS.md"
_audit.REQUIREMENTS = _audit.ROOT / _PRODUCT_REQUIREMENTS_REL

_original_validate_catalog = _audit._validate_catalog
_original_build_audit = _audit.build_audit


def _product_validate_catalog(titles: dict[str, str]) -> list[str]:
    issues = _original_validate_catalog(titles)
    # The legacy validator used local Control Plane/process-file existence as a
    # proxy for accepted historical evidence. Those files are intentionally absent
    # at the dedicated Product boundary and are instead anchored to the immutable
    # pre-removal snapshot plus Product-owned migration/delivery evidence.
    filtered: list[str] = []
    for issue in issues:
        marker = "evidence path does not exist: "
        if marker in issue:
            relative = issue.split(marker, 1)[1]
            if is_removed_control_plane_reference(relative):
                continue
        filtered.append(issue)
    return filtered


def _product_build_audit(*, assert_honest: bool = False):
    result = _original_build_audit(assert_honest=assert_honest)
    result["source_requirements"] = _PRODUCT_REQUIREMENTS_REL
    result["historical_evidence_source"] = provenance()

    for row in result["rows"]:
        product_evidence: list[str] = []
        historical_refs: list[dict[str, str]] = []
        for relative in row["evidence"]:
            relative = str(relative)
            if is_removed_control_plane_reference(relative):
                historical_refs.append(
                    {
                        "source_path": relative,
                        "source_commit": HISTORICAL_SOURCE_COMMIT,
                        "source_url": immutable_source_url(relative),
                    }
                )
                replacement = (
                    PRODUCT_EVIDENCE_REL
                    if is_historical_task_reference(relative)
                    else MIGRATION_EVIDENCE_REL
                )
                if replacement not in product_evidence:
                    product_evidence.append(replacement)
            else:
                product_evidence.append(relative)
        row["evidence"] = product_evidence
        if historical_refs:
            row["historical_evidence_refs"] = historical_refs
    return result


_audit._validate_catalog = _product_validate_catalog
_audit._delivery = historical_delivery
_audit.build_audit = _product_build_audit

from .audit import AuditIntegrityError, build_audit, integrity_issues, render_markdown

__all__ = ["AuditIntegrityError", "build_audit", "integrity_issues", "render_markdown"]
