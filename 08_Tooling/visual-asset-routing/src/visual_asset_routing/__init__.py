"""Public API for deterministic provider-neutral visual asset routing."""

from .classification import (
    AssetType,
    ClassificationEvidenceSource,
    IconSystemGateDecision,
    PerAssetClassification,
    evaluate_icon_system_batch,
    evaluate_icon_system_gate,
)
from .routing import (
    AssetRoutingPlan,
    DestinationContext,
    RoutingState,
    SemanticObservation,
    TeacherAction,
    apply_teacher_action,
    recommend_route,
)

__all__ = [
    "AssetRoutingPlan",
    "AssetType",
    "ClassificationEvidenceSource",
    "DestinationContext",
    "IconSystemGateDecision",
    "PerAssetClassification",
    "RoutingState",
    "SemanticObservation",
    "TeacherAction",
    "apply_teacher_action",
    "evaluate_icon_system_batch",
    "evaluate_icon_system_gate",
    "recommend_route",
]
