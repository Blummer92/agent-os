"""Public surface for pure teacher-summary evidence interpretation."""

from .alignment import DIMENSION_ORDER, build_alignment
from .interpreter import CONTRACT_ID, interpret_teacher_summary

__all__ = [
    "CONTRACT_ID",
    "DIMENSION_ORDER",
    "build_alignment",
    "interpret_teacher_summary",
]
