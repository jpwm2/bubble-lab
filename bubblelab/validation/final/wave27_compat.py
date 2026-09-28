"""Compatibility adapter for accepted Wave-27 delivery schemas.

The 3D multi-neck Worker predates the list-shaped validation records consumed by the
historical final-validation helper.  Its accepted deliverable stores one canonical
AI Runner validation object instead.  Validate that object explicitly rather than
weakening or rewriting accepted evidence.
"""
from __future__ import annotations
import json
from typing import Any
from . import suite as runner
from . import wave27_suite

_ORIGINAL_HISTORICAL_RECORD = runner._historical_record
_MULTINECK_TASK = "bubble-3d-multineck-breakup-foundation"
_ACCEPTANCE = "all assignment acceptance steps submitted by the canonical AI Runner request passed"


def _historical_record(spec: dict[str, Any]) -> dict[str, Any]:
    if str(spec.get("task_id")) != _MULTINECK_TASK:
        return _ORIGINAL_HISTORICAL_RECORD(spec)
    path = runner.ROOT / "tasks" / _MULTINECK_TASK / "deliverable.json"
    try:
        delivery = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"name": spec["name"], "execution": "ACCEPTED_HISTORICAL", "source": path.relative_to(runner.ROOT).as_posix(), "result": "FAIL", "reason": spec["reason"], "diagnostic": str(exc)}
    validation = delivery.get("validation")
    passed = (
        delivery.get("outcome") == "DELIVERED"
        and isinstance(validation, dict)
        and validation.get("conclusion") == "success"
        and validation.get("acceptance") == _ACCEPTANCE
        and isinstance(validation.get("workflow_run_id"), int)
        and validation.get("head_sha") == delivery.get("implementation_validation_head")
    )
    return {
        "name": spec["name"],
        "execution": "ACCEPTED_HISTORICAL",
        "source": path.relative_to(runner.ROOT).as_posix(),
        "result": "PASS" if passed else "FAIL",
        "reason": spec["reason"],
        "checks": [{"name": _ACCEPTANCE, "result": "PASS" if passed else "FAIL", "run_id": validation.get("workflow_run_id") if isinstance(validation, dict) else None}],
    }


def build_final_validation(*, execute: bool = True, assert_honest: bool = False) -> dict[str, Any]:
    original = runner._historical_record
    runner._historical_record = _historical_record
    try:
        return wave27_suite.build_final_validation(execute=execute, assert_honest=assert_honest)
    finally:
        runner._historical_record = original


FinalValidationError = wave27_suite.FinalValidationError
render_markdown = wave27_suite.render_markdown
