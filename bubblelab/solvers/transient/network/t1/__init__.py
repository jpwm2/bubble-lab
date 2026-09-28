"""Production T1 topology surgery for the research-qualified extruded class."""

from .fixtures import (
    build_pre_t1_network,
    build_pre_t1_state,
    build_supported_pre_t1_network,
    build_supported_pre_t1_state,
    combine_disjoint_networks,
    combine_disjoint_states,
)
from .transaction import (
    EligibilityResult,
    T1EligibilitySettings,
    T1Lineage,
    T1Neighborhood,
    T1TransactionError,
    T1TransactionResult,
    T1TransactionSettings,
    apply_t1_transaction,
    detect_eligibility,
    detect_t1_eligibility,
    internal_adjacency_pairs,
    perform_neighbor_switch,
    perform_t1_transaction,
)

__all__ = [
    "EligibilityResult",
    "T1EligibilitySettings",
    "T1Lineage",
    "T1Neighborhood",
    "T1TransactionError",
    "T1TransactionResult",
    "T1TransactionSettings",
    "apply_t1_transaction",
    "build_pre_t1_network",
    "build_pre_t1_state",
    "build_supported_pre_t1_network",
    "build_supported_pre_t1_state",
    "combine_disjoint_networks",
    "combine_disjoint_states",
    "detect_eligibility",
    "detect_t1_eligibility",
    "internal_adjacency_pairs",
    "perform_neighbor_switch",
    "perform_t1_transaction",
]
