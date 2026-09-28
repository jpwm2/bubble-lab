"""Bubble Lab deterministic rupture and coalescence event layer."""

from .adapters import state_from_film_network, state_from_thinfilm_pair
from .criteria import (
    RuptureConfig,
    RuptureDecision,
    RuptureHooks,
    RuptureObservation,
    RuptureTracker,
)
from .engine import TopologyEventEngine, TopologyTransition
from .export import canonical_demo_frame, canonical_frame_from_state
from .model import (
    EXTERIOR,
    BubbleState,
    EventState,
    RestartGeometry,
    SharedFilmState,
    TopologyEvent,
    stable_id,
)

__all__ = [
    "EXTERIOR",
    "BubbleState",
    "EventState",
    "RestartGeometry",
    "SharedFilmState",
    "TopologyEvent",
    "RuptureConfig",
    "RuptureDecision",
    "RuptureHooks",
    "RuptureObservation",
    "RuptureTracker",
    "TopologyEventEngine",
    "TopologyTransition",
    "state_from_film_network",
    "state_from_thinfilm_pair",
    "canonical_demo_frame",
    "canonical_frame_from_state",
    "stable_id",
]
