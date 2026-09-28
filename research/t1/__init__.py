"""Research-only T1 topology evidence; not a production solver capability."""

from .model import LocalFilmNetwork, build_pre_t1_network
from .prototype import detect_eligibility, perform_neighbor_switch

__all__ = [
    "LocalFilmNetwork",
    "build_pre_t1_network",
    "detect_eligibility",
    "perform_neighbor_switch",
]
