from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class ConservativeSplit:
    parent_before_m3: float
    detached_m3: float
    parent_after_m3: float
    relative_error: float


def conservative_split(parent_volume_m3: float, detached_volume_m3: float) -> ConservativeSplit:
    if parent_volume_m3 <= 0.0:
        raise ValueError("parent_volume_m3 must be positive")
    if detached_volume_m3 <= 0.0 or detached_volume_m3 >= parent_volume_m3:
        raise ValueError("detached_volume_m3 must lie strictly inside parent volume")
    parent_after = parent_volume_m3 - detached_volume_m3
    error = abs(parent_volume_m3 - (parent_after + detached_volume_m3)) / parent_volume_m3
    return ConservativeSplit(parent_volume_m3, detached_volume_m3, parent_after, error)


def child_lineage(parent_id: str, event_index: int, piece_index: int = 0) -> str:
    if not parent_id:
        raise ValueError("parent_id must be non-empty")
    if event_index < 1 or piece_index < 0:
        raise ValueError("invalid lineage index")
    return f"{parent_id}/detach-{event_index:03d}/piece-{piece_index:02d}"
