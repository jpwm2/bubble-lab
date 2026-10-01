"""Compatibility entry point for the accepted Wave-27 final-validation schema.

The Product-owned historical-evidence resolver installed by this package now
handles both list-shaped delivery validations and the older Wave-27 single-object
record. No compatibility path reads the removed ``tasks/`` tree.
"""
from __future__ import annotations

from typing import Any

from . import wave27_suite


def build_final_validation(*, execute: bool = True, assert_honest: bool = False) -> dict[str, Any]:
    return wave27_suite.build_final_validation(execute=execute, assert_honest=assert_honest)


FinalValidationError = wave27_suite.FinalValidationError
render_markdown = wave27_suite.render_markdown
