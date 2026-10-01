"""Final end-to-end qualification for the accepted Bubble Lab baseline.

Historical qualification records are resolved from the Product-owned sanitized
archive. The removed ``tasks/`` Control Plane/process tree is provenance only and
is not a runtime dependency of final validation.
"""
from __future__ import annotations

from typing import Any

from bubblelab.validation.historical_evidence import (
    HISTORICAL_SOURCE_COMMIT,
    PRODUCT_EVIDENCE_REL,
    historical_delivery,
)

from . import suite as _suite


def _product_historical_record(spec: dict[str, Any]) -> dict[str, Any]:
    task_id = str(spec["task_id"])
    source = f"{PRODUCT_EVIDENCE_REL}#deliveries.{task_id}"
    try:
        delivery = historical_delivery(task_id)
    except (OSError, ValueError, KeyError) as exc:
        return {
            "name": spec["name"],
            "execution": "ACCEPTED_HISTORICAL",
            "source": source,
            "source_commit": HISTORICAL_SOURCE_COMMIT,
            "result": "FAIL",
            "reason": spec["reason"],
            "diagnostic": str(exc),
        }

    validation = delivery.get("validation")
    selected: list[dict[str, Any]] = []

    if isinstance(validation, list):
        checks = {
            str(item.get("name")): item
            for item in validation
            if isinstance(item, dict)
        }
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
    elif isinstance(validation, dict):
        # One accepted Wave-27 Worker predates list-shaped validation records.
        acceptance = str(validation.get("acceptance", ""))
        expected = tuple(str(name) for name in spec["checks"])
        passed = (
            delivery.get("outcome") == "DELIVERED"
            and validation.get("conclusion") == "success"
            and len(expected) == 1
            and acceptance == expected[0]
            and isinstance(validation.get("workflow_run_id"), int)
            and validation.get("head_sha") == delivery.get("implementation_validation_head")
        )
        selected.append(
            {
                "name": expected[0] if expected else acceptance,
                "result": "PASS" if passed else "FAIL",
                "run_id": validation.get("workflow_run_id"),
            }
        )
    else:
        passed = False

    return {
        "name": spec["name"],
        "execution": "ACCEPTED_HISTORICAL",
        "source": source,
        "source_commit": HISTORICAL_SOURCE_COMMIT,
        "result": "PASS" if passed else "FAIL",
        "reason": spec["reason"],
        "checks": selected,
    }


_suite._historical_record = _product_historical_record

from .suite import FinalValidationError, build_final_validation, render_markdown

__all__ = ["FinalValidationError", "build_final_validation", "render_markdown"]
