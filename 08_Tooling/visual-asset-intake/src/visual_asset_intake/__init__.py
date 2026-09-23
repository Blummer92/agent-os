"""Public API for bounded local visual-asset intake."""

from .duplicates import (
    DuplicateCandidate,
    DuplicateDisposition,
    DuplicateReconciliationResult,
    reconcile_duplicate,
)
from .intake import intake_visual_asset
from .models import (
    AssetIntakeResult,
    IntakeError,
    IntakeErrorCode,
    IntakePolicy,
    IntakeState,
)

__all__ = [
    "AssetIntakeResult",
    "DuplicateCandidate",
    "DuplicateDisposition",
    "DuplicateReconciliationResult",
    "IntakeError",
    "IntakeErrorCode",
    "IntakePolicy",
    "IntakeState",
    "intake_visual_asset",
    "reconcile_duplicate",
]
