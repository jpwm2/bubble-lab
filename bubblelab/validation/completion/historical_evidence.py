"""Product-owned access to immutable accepted historical validation evidence."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_ROOT = ROOT / "bubblelab" / "validation" / "completion" / "evidence" / "historical-deliveries"
_TASK_ID_RE = re.compile(r"^[a-z0-9-]+$")


def historical_delivery_path(task_id: str) -> Path:
    if not _TASK_ID_RE.fullmatch(task_id):
        raise ValueError(f"invalid historical task id: {task_id!r}")
    return EVIDENCE_ROOT / f"{task_id}.json"


def historical_delivery_source(task_id: str) -> str:
    return historical_delivery_path(task_id).relative_to(ROOT).as_posix()


def historical_delivery(task_id: str) -> dict[str, Any]:
    path = historical_delivery_path(task_id)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{historical_delivery_source(task_id)} must contain a JSON object")
    if str(value.get("task_id")) != task_id:
        raise ValueError(f"{historical_delivery_source(task_id)} task_id mismatch")
    return value
