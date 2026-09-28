"""Deterministic replay bundle validation."""
from __future__ import annotations
import json, sys
from pathlib import Path
from typing import Any
ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIB = ROOT / "bubblelab" / "python"
if str(PYTHON_LIB) not in sys.path: sys.path.insert(0, str(PYTHON_LIB))
from bubblelab_contract import assert_valid

class ReplayBundleValidationError(ValueError): pass

def _inside(root: Path, rel: str) -> Path:
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute():
        raise ReplayBundleValidationError(f"invalid relative bundle path: {rel!r}")
    root_resolved = root.resolve()
    target = (root / rel).resolve()
    try: target.relative_to(root_resolved)
    except ValueError as exc: raise ReplayBundleValidationError(f"path escapes bundle: {rel}") from exc
    return target

def _load(path: Path) -> Any:
    try: return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc: raise ReplayBundleValidationError(f"missing file: {path.name}") from exc
    except json.JSONDecodeError as exc: raise ReplayBundleValidationError(f"corrupt JSON: {path}") from exc

def validate_replay_bundle(bundle_dir: str | Path) -> dict[str, Any]:
    root = Path(bundle_dir)
    replay = _load(root / "replay.json")
    if not isinstance(replay, dict) or replay.get("bundle_version") != "1.0.0":
        raise ReplayBundleValidationError("unsupported or invalid replay bundle")
    if replay.get("contract_version") != "1.0.0": raise ReplayBundleValidationError("contract version mismatch")
    frames = replay.get("frames")
    if not isinstance(frames, list) or not frames: raise ReplayBundleValidationError("frames must be a non-empty array")
    seen, last_time = set(), -1.0
    scenario = replay.get("scenario") or {}
    backend = replay.get("backend") or {}
    for ref in frames:
        if not isinstance(ref, dict): raise ReplayBundleValidationError("frame reference must be an object")
        frame_id, rel = ref.get("frame_id"), ref.get("path")
        if frame_id in seen: raise ReplayBundleValidationError(f"duplicate frame ID: {frame_id}")
        seen.add(frame_id)
        frame = _load(_inside(root, rel))
        assert_valid(frame)
        if frame.get("kind") != "FRAME": raise ReplayBundleValidationError("replay frame reference must point to FRAME")
        if frame.get("frame_id") != frame_id: raise ReplayBundleValidationError("frame ID/reference mismatch")
        t = float(frame["simulation_time_s"])
        if t < last_time: raise ReplayBundleValidationError("simulation time must be nondecreasing")
        if float(ref.get("simulation_time_s")) != t: raise ReplayBundleValidationError("replay/frame time mismatch")
        last_time = t
        manifest = frame["manifest"]
        prov = manifest["provenance"]
        if prov.get("source_scenario") != scenario.get("id"): raise ReplayBundleValidationError("scenario provenance mismatch")
        if manifest["random_seed"] != replay.get("random_seed"): raise ReplayBundleValidationError("seed mismatch")
        if manifest["solver"].get("backend") != backend.get("identity"): raise ReplayBundleValidationError("backend identity mismatch")
    checkpoints = replay.get("checkpoints", [])
    if not isinstance(checkpoints, list): raise ReplayBundleValidationError("checkpoints must be an array")
    for ref in checkpoints:
        checkpoint = _load(_inside(root, ref["path"]))
        assert_valid(checkpoint)
        if checkpoint.get("kind") != "CHECKPOINT": raise ReplayBundleValidationError("checkpoint reference is not restart-capable CHECKPOINT")
    return replay
