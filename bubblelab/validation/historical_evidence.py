"""Resolve accepted historical validation evidence without restoring Control Plane paths.

The immutable pre-removal repository snapshot remains the provenance source. Runtime
completion/final validation consumes Product-owned sanitized evidence instead of
requiring removed ``tasks/``, ``orchestra/`` or ``agent/`` paths locally.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PRODUCT_EVIDENCE_REL = "bubblelab/validation/completion/historical_delivery_evidence.json"
PRODUCT_EVIDENCE = ROOT / PRODUCT_EVIDENCE_REL
HISTORICAL_SOURCE_REPOSITORY = "jpwm2/bubble-lab"
HISTORICAL_SOURCE_COMMIT = "be27cbe8e0c03f27f9cb019d04658e72968a74f1"
MIGRATION_EVIDENCE_REL = "docs/migration/criteria-5-validation-evidence.md"
MIGRATION_VALIDATION_RUN_ID = 36682100918
REMOVED_CONTROL_PLANE_PREFIXES = ("tasks/", "orchestra/", "agent/")


def _manifest() -> dict[str, Any]:
    return json.loads(PRODUCT_EVIDENCE.read_text(encoding="utf-8"))


def historical_delivery(task_id: str) -> dict[str, Any]:
    """Return one sanitized accepted delivery record from Product-owned evidence."""
    deliveries = _manifest().get("deliveries", {})
    if not isinstance(deliveries, dict) or task_id not in deliveries:
        raise KeyError(f"historical delivery evidence is not archived for {task_id}")
    delivery = deliveries[task_id]
    if not isinstance(delivery, dict):
        raise ValueError(f"invalid historical delivery evidence for {task_id}")
    return delivery


def is_historical_task_reference(relative: str) -> bool:
    parts = Path(relative).parts
    return len(parts) == 3 and parts[0] == "tasks" and parts[2] == "deliverable.json"


def is_removed_control_plane_reference(relative: str) -> bool:
    normalized = str(relative).replace("\\", "/")
    return normalized.startswith(REMOVED_CONTROL_PLANE_PREFIXES)


def immutable_source_url(relative: str) -> str:
    return (
        f"https://github.com/{HISTORICAL_SOURCE_REPOSITORY}/blob/"
        f"{HISTORICAL_SOURCE_COMMIT}/{relative}"
    )


def provenance() -> dict[str, Any]:
    return {
        "product_evidence": PRODUCT_EVIDENCE_REL,
        "source_repository": HISTORICAL_SOURCE_REPOSITORY,
        "source_commit": HISTORICAL_SOURCE_COMMIT,
        "migration_evidence": MIGRATION_EVIDENCE_REL,
        "migration_validation_run_id": MIGRATION_VALIDATION_RUN_ID,
    }
