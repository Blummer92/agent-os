"""Public LP4 deterministic lesson-pacing surface."""

from .comparability import filter_comparable_runs
from .diagnosis import DIMENSIONS, diagnose_dimensions
from .evaluator import evaluate_lesson_pacing
from .packet import CONTRACT_VERSION, NON_AUTHORITY_FIELDS, validate_pacing_packet

__all__ = [
    "CONTRACT_VERSION",
    "DIMENSIONS",
    "NON_AUTHORITY_FIELDS",
    "diagnose_dimensions",
    "evaluate_lesson_pacing",
    "filter_comparable_runs",
    "validate_pacing_packet",
]
