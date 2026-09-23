"""Per-asset visual classification gate for Icon System routing."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

MAX_REFERENCE = 512


class AssetType(str, Enum):
    ICON = "ICON"
    PHOTOGRAPH = "PHOTOGRAPH"
    ILLUSTRATION = "ILLUSTRATION"
    DIAGRAM = "DIAGRAM"
    OTHER_VISUAL = "OTHER_VISUAL"
    AMBIGUOUS = "AMBIGUOUS"


class ClassificationEvidenceSource(str, Enum):
    VISUAL_INSPECTION = "VISUAL_INSPECTION"
    TEACHER_CONFIRMED_VISUAL = "TEACHER_CONFIRMED_VISUAL"
    FOLDER_NAME = "FOLDER_NAME"
    FILENAME = "FILENAME"
    FILE_EXTENSION = "FILE_EXTENSION"
    BATCH_CONTEXT = "BATCH_CONTEXT"
    TEACHER_BATCH_LANGUAGE = "TEACHER_BATCH_LANGUAGE"


_POSITIVE_ICON_SOURCES = frozenset({
    ClassificationEvidenceSource.VISUAL_INSPECTION,
    ClassificationEvidenceSource.TEACHER_CONFIRMED_VISUAL,
})


@dataclass(frozen=True, slots=True)
class PerAssetClassification:
    asset_reference: str
    asset_type: AssetType
    evidence_source: ClassificationEvidenceSource
    evidence_note: str = ""


@dataclass(frozen=True, slots=True)
class IconSystemGateDecision:
    classification: PerAssetClassification
    icon_path_eligible: bool
    review_required: bool
    reason_codes: tuple[str, ...]
    external_write_authorized: bool = False
    approval_authorized: bool = False
    classroom_readiness_authorized: bool = False
    rights_authorized: bool = False
    privacy_authorized: bool = False
    source_authority_granted: bool = False
    production_authorized: bool = False


def evaluate_icon_system_gate(classification: PerAssetClassification) -> IconSystemGateDecision:
    """Evaluate one asset independently before any Icon System mutation decision."""
    if type(classification) is not PerAssetClassification or not _valid_ref(classification.asset_reference):
        return _decision(_safe_classification(classification), False, True, "classification-invalid-evidence")
    if type(classification.asset_type) is not AssetType or type(classification.evidence_source) is not ClassificationEvidenceSource:
        return _decision(_safe_classification(classification), False, True, "classification-invalid-evidence")
    if classification.asset_type is AssetType.AMBIGUOUS:
        return _decision(classification, False, True, "classification-ambiguous")
    if classification.asset_type is AssetType.ICON:
        if classification.evidence_source not in _POSITIVE_ICON_SOURCES:
            return _decision(classification, False, True, "classification-icon-evidence-insufficient")
        return _decision(classification, True, False, "classification-icon-confirmed-per-asset")
    return _decision(classification, False, False, "classification-non-icon")


def evaluate_icon_system_batch(classifications: tuple[PerAssetClassification, ...]) -> tuple[IconSystemGateDecision, ...]:
    """Evaluate a batch without allowing one asset's evidence to affect another."""
    return tuple(evaluate_icon_system_gate(item) for item in classifications)


def _decision(classification, eligible, review, reason):
    return IconSystemGateDecision(classification, eligible, review, (reason,))


def _valid_ref(value: object) -> bool:
    return type(value) is str and bool(value.strip()) and len(value) <= MAX_REFERENCE


def _safe_classification(value: object) -> PerAssetClassification:
    if type(value) is PerAssetClassification:
        ref = value.asset_reference if _valid_ref(value.asset_reference) else "invalid-asset"
        asset_type = value.asset_type if type(value.asset_type) is AssetType else AssetType.AMBIGUOUS
        source = value.evidence_source if type(value.evidence_source) is ClassificationEvidenceSource else ClassificationEvidenceSource.BATCH_CONTEXT
        return PerAssetClassification(ref, asset_type, source)
    return PerAssetClassification("invalid-asset", AssetType.AMBIGUOUS, ClassificationEvidenceSource.BATCH_CONTEXT)
