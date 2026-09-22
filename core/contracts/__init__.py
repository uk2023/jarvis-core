"""Stable contracts shared by JARVIS layers.

This package owns boundary definitions and their central enforcement point;
it does not implement cognition or business logic.
"""

from .schemas import CONTRACTS, ContractError, LayerPayload
from .validator import (
    validate,
    validate_input,
    validate_output,
    validate_transition,
    begin_validation_trace,
    get_validation_trace,
)
from .extraction import ExtractionAttempt, ExtractionResult, run_extraction_cascade

__all__ = [
    "CONTRACTS",
    "ContractError",
    "LayerPayload",
    "validate",
    "validate_input",
    "validate_output",
    "validate_transition",
    "begin_validation_trace",
    "get_validation_trace",
    "ExtractionAttempt",
    "ExtractionResult",
    "run_extraction_cascade",
]
