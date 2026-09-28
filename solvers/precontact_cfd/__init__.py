"""Resolved local pre-contact thin-gap CFD foundation."""
from .core import (
    PrecontactCFDResponse,
    PrecontactCFDSettings,
    ThinGapField,
    coupled_cfd_response,
    solve_thin_gap_field,
    taylor_reference_force_n,
)

__all__ = [
    "PrecontactCFDResponse",
    "PrecontactCFDSettings",
    "ThinGapField",
    "coupled_cfd_response",
    "solve_thin_gap_field",
    "taylor_reference_force_n",
]
