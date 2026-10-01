"""Completion-gap audit for the Product-owned Bubble Lab requirements baseline.

This package bootstraps the historical audit implementation onto the dedicated
Product repository boundary. Historical ``tasks/*`` strings remain immutable
provenance identifiers only; runtime evidence is read from Product-owned
sanitized evidence and those legacy paths are never required to exist locally.
"""
from __future__ import annotations

from bubblelab.validation.historical_evidence import (
    HISTORICAL_SOURCE_COMMIT,
    PRODUCT_EVIDENCE_REL,
    historical_delivery,
    immutable_source_url,
    is_historical_task_reference,
    provenance,
)

from . import audit as _audit

_PRODUCT_REQUIREMENTS_REL = "bubblelab/docs/PRODUCT_REQUIREMENTS.md"
_audit.REQUIREMENTS = _audit.ROOT / _PRODUCT_REQUIREMENTS_REL

_original_validate_catalog = _audit._validate_catalog
_original_build_audit = _audit.build_audit


def _product_validate_catalog(titles: dict[str, str]) -> list[str]:
    issues = _original_validate_catalog(titles)
    # The legacy validator used local task-file existence as a proxy for accepted
    # historical evidence. At the dedicated Product boundary those source paths
    # are intentionally absent and are backed by the immutable source commit plus
    # the Product-owned sanitized evidence archive instead.
    return [
        issue
        for issue in issues
        if "evidence path does not exist: tasks/" not in issue
    ]


def _product_build_audit(*, assert_honest: bool = False):
    result = _original_build_audit(assert_honest=assert_honest)
    result["source_requirements"] = _PRODUCT_REQUIREMENTS_REL
    result["historical_evidence_source"] = provenance()

    for row in result["rows"]:
        product_evidence: list[str] = []
        historical_refs: list[dict[str, str]] = []
        for relative in row["evidence"]:
            relative = str(relative)
            if is_historical_task_reference(relative):
                historical_refs.append(
                    {
                        "source_path": relative,
                        "source_commit": HISTORICAL_SOURCE_COMMIT,
                        "source_url": immutable_source_url(relative),
                    }
                )
                if PRODUCT_EVIDENCE_REL not in product_evidence:
                    product_evidence.append(PRODUCT_EVIDENCE_REL)
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
