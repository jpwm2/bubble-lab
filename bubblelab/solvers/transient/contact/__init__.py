"""Automatic supported-class transient contact formation."""

from .core import (
    ContactFormationError,
    ContactFormationResult,
    ContactObservation,
    ContactSettings,
    form_contact,
    observe_contact,
)

__all__ = [
    "ContactFormationError",
    "ContactFormationResult",
    "ContactObservation",
    "ContactSettings",
    "form_contact",
    "observe_contact",
]
