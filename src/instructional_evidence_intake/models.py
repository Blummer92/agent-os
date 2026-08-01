"""Frozen data contracts for the pure-local EIA2 OCR extraction adapter.

These types describe engine-reported detections and the normalized,
EIA1-compatible page-extraction evidence produced by ``ocr_adapter``. They
hold no image pixels and import no image or ML library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

CONTRACT_ID = "instructional-evidence-ocr-extraction-v1"

# (x1, y1, x2, y2) in source-image pixel coordinates, x1 < x2 and y1 < y2.
BBox = tuple[int, int, int, int]

RecognitionPath = Literal["primary", "handwriting-fallback"]
TemplateAlignmentStatus = Literal["not-supplied", "aligned", "mismatched", "partial"]
ImageQualityDisposition = Literal["acceptable", "degraded", "unusable"]
ConfidenceLevel = Literal["high", "medium", "low"]


def _require_bbox(value: object, name: str) -> BBox:
    if type(value) is not tuple or len(value) != 4:
        raise TypeError(f"{name} must be an exact 4-item built-in tuple")
    if any(type(item) is not int for item in value):
        raise TypeError(f"{name} coordinates must be built-in integers")
    x1, y1, x2, y2 = value
    if x1 < 0 or y1 < 0 or x2 <= x1 or y2 <= y1:
        raise ValueError(f"{name} must describe a normalized, non-empty region")
    return value  # type: ignore[return-value]


def _require_confidence(value: object, name: str) -> float:
    if type(value) is not float or not (0.0 <= value <= 1.0):
        raise ValueError(f"{name} must be a built-in float in [0.0, 1.0]")
    return value


@dataclass(frozen=True, slots=True)
class EngineIdentifier:
    """Immutable provenance for one recognition engine invocation path."""

    family: str
    model_name: str
    mode: Literal["whole-page", "handwriting-fallback"]

    def __post_init__(self) -> None:
        for name, value in (("family", self.family), ("model_name", self.model_name)):
            if type(value) is not str or not value:
                raise TypeError(f"{name} must be a non-empty built-in string")
        if self.mode not in ("whole-page", "handwriting-fallback"):
            raise ValueError("mode must be 'whole-page' or 'handwriting-fallback'")


@dataclass(frozen=True, slots=True)
class RawDetection:
    """One engine-reported text detection, before adapter policy is applied.

    This is the exact shape a caller-supplied engine must return: a bounded
    box, recognized text, and a calibration-agnostic confidence score. It
    carries no notion of correctness, mastery, or authority.
    """

    bbox: BBox
    text: str
    confidence: float

    def __post_init__(self) -> None:
        _require_bbox(self.bbox, "bbox")
        if type(self.text) is not str:
            raise TypeError("text must be a built-in string")
        _require_confidence(self.confidence, "confidence")


@dataclass(frozen=True, slots=True)
class ExtractionRegion:
    """One normalized region result within a page's extraction evidence."""

    region_id: str
    bbox: BBox
    text: str | None
    confidence: float
    recognition_path: RecognitionPath
    alternate_text: str | None
    alternate_confidence: float | None
    disagreement: bool
    template_pairing_confidence: float | None
    manual_review_required: bool
    findings: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.region_id) is not str or not self.region_id:
            raise TypeError("region_id must be a non-empty built-in string")
        _require_bbox(self.bbox, "bbox")
        if self.text is not None and type(self.text) is not str:
            raise TypeError("text must be a built-in string or None")
        _require_confidence(self.confidence, "confidence")
        if self.recognition_path not in ("primary", "handwriting-fallback"):
            raise ValueError("recognition_path is unsupported")
        if self.alternate_text is not None and type(self.alternate_text) is not str:
            raise TypeError("alternate_text must be a built-in string or None")
        if self.alternate_confidence is not None:
            _require_confidence(self.alternate_confidence, "alternate_confidence")
        if type(self.disagreement) is not bool:
            raise TypeError("disagreement must be a built-in Boolean")
        if self.template_pairing_confidence is not None:
            _require_confidence(
                self.template_pairing_confidence, "template_pairing_confidence"
            )
        if type(self.manual_review_required) is not bool:
            raise TypeError("manual_review_required must be a built-in Boolean")
        if type(self.findings) is not tuple:
            raise TypeError("findings must be a built-in tuple")
        for item in self.findings:
            if type(item) is not str or not item:
                raise TypeError("findings entries must be non-empty built-in strings")


@dataclass(frozen=True, slots=True)
class PageExtractionEvidence:
    """Normalized, EIA1-compatible document-reading evidence for one page."""

    contract_version: str
    record_id: str
    record_revision: int
    source_ref: str
    page_index: int
    template_supplied: bool
    template_alignment_status: TemplateAlignmentStatus
    image_quality_disposition: ImageQualityDisposition
    image_quality_findings: tuple[str, ...]
    regions: tuple[ExtractionRegion, ...]
    engine_provenance: tuple[EngineIdentifier, ...]
    confidence: ConfidenceLevel
    confidence_basis: tuple[str, ...]
    manual_review_required: bool
    report_only: Literal[True] = field(default=True, init=False)
    grading_authorized: Literal[False] = field(default=False, init=False)
    readiness_authorized: Literal[False] = field(default=False, init=False)
    student_classification_authorized: Literal[False] = field(default=False, init=False)
    route_assignment_authorized: Literal[False] = field(default=False, init=False)
    production_authorized: Literal[False] = field(default=False, init=False)
    external_write_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.contract_version) is not str or self.contract_version != CONTRACT_ID:
            raise ValueError("contract_version must equal the OCR extraction CONTRACT_ID")
        if type(self.record_id) is not str or not self.record_id:
            raise TypeError("record_id must be a non-empty built-in string")
        if type(self.record_revision) is not int or self.record_revision < 1:
            raise ValueError("record_revision must be a positive built-in integer")
        if type(self.source_ref) is not str or not self.source_ref:
            raise TypeError("source_ref must be a non-empty built-in string")
        if type(self.page_index) is not int or self.page_index < 0:
            raise ValueError("page_index must be a non-negative built-in integer")
        if type(self.template_supplied) is not bool:
            raise TypeError("template_supplied must be a built-in Boolean")
        if self.template_alignment_status not in (
            "not-supplied",
            "aligned",
            "mismatched",
            "partial",
        ):
            raise ValueError("template_alignment_status is unsupported")
        if self.image_quality_disposition not in ("acceptable", "degraded", "unusable"):
            raise ValueError("image_quality_disposition is unsupported")
        for name, value in (
            ("image_quality_findings", self.image_quality_findings),
            ("regions", self.regions),
            ("engine_provenance", self.engine_provenance),
            ("confidence_basis", self.confidence_basis),
        ):
            if type(value) is not tuple:
                raise TypeError(f"{name} must be a built-in tuple")
        for region in self.regions:
            if type(region) is not ExtractionRegion:
                raise TypeError("regions entries must be ExtractionRegion instances")
        for engine in self.engine_provenance:
            if type(engine) is not EngineIdentifier:
                raise TypeError("engine_provenance entries must be EngineIdentifier instances")
        if self.confidence not in ("high", "medium", "low"):
            raise ValueError("confidence is unsupported")
        if type(self.manual_review_required) is not bool:
            raise TypeError("manual_review_required must be a built-in Boolean")
