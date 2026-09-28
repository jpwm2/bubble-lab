"""Load and deterministically serialize Bubble Lab contract documents."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Mapping
from .models import Checkpoint, Frame, Scenario
from .validation import assert_valid

def canonical_json(data: Mapping[str,Any]) -> str:
    return json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2,separators=(",",": "))+"\n"

def parse_document(data: Mapping[str,Any]) -> Frame | Checkpoint | Scenario:
    assert_valid(data)
    if data["kind"]=="SCENARIO": return Scenario.from_dict(data)
    if data["kind"]=="CHECKPOINT":
        frame=Frame.from_dict(data)
        return Checkpoint(**{**frame.__dict__,"kind":"CHECKPOINT"})
    return Frame.from_dict(data)

def load_document(path: str | Path) -> Frame | Checkpoint | Scenario:
    raw=json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw,dict): raise ValueError("contract document root must be an object")
    return parse_document(raw)

def dump_document(document: Frame | Checkpoint | Scenario, path: str | Path) -> None:
    Path(path).write_text(canonical_json(document.to_dict()),encoding="utf-8")
