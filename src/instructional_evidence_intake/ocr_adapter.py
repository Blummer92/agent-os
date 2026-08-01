"""Pure-local, deterministic PP-OCRv6/PP-OCRv5 worksheet extraction adapter.

Design boundary
----------------
This module never imports an image or ML library at module load time, and
it never decodes image pixels itself. It validates raw file bytes against
bounded, dependency-free structural checks (``sniff_image_info``) and then
delegates all pixel-level work to a caller-supplied engine object that
implements the small ``WholePageEngine`` / ``HandwritingEngine`` protocols
below. Confidence policy, disagreement handling, template-candidate
pairing, and bounds enforcement all live here in pure Python and are fully
testable with fake engines.

A reference engine backed by the real, pinned PaddleOCR/PaddleX models from
Issue #716's candidate profile (``PP-OCRv6_small_det`` + ``PP-OCRv6_small_rec``
for whole-page recognition, ``en_PP-OCRv5_mobile_rec`` for the bounded
handwriting fallback) is provided in ``PaddleOcrEngine`` below. Its
constructor imports ``paddleocr`` lazily -- only when a caller actually
constructs it -- so importing this module, or exercising it with a fake
engine, never touches paddleocr, an image library, the network, or the
filesystem. ``paddleocr``/``paddlepaddle`` are not yet declared as
repository dependencies (see EIA5 / Issue #716); constructing
``PaddleOcrEngine`` without them installed raises ``ModuleNotFoundError``.

Only single-page PNG or JPEG byte input is supported. PDF, archive, and
other container formats are rejected as unsupported rather than parsed.
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable

from instructional_workflow_contracts import (
    FINGERPRINT_ALGORITHM,
    ContractValidationError,
    ValidatedRecord,
    ValidationResult,
    ValidationStatus,
    canonical_size,
    freeze_json,
    sha256_hex,
    validate_revision,
    validate_stable_id,
)
from instructional_workflow_contracts.common import validate_text

from .models import (
    CONTRACT_ID,
    BBox,
    EngineIdentifier,
    ExtractionRegion,
    PageExtractionEvidence,
    RawDetection,
)

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_DIMENSION_PX = 4096
MAX_PIXELS = MAX_DIMENSION_PX * MAX_DIMENSION_PX
MAX_REGIONS = 256
MAX_TEXT_LENGTH = 500
PROCESSING_TIMEOUT_SECONDS = 30.0
LOW_CONFIDENCE_THRESHOLD = 0.80
TEMPLATE_PAIRING_MIN_IOU = 0.30

WHOLE_PAGE_ENGINE_ID = EngineIdentifier(
    family="PP-OCRv6",
    model_name="PP-OCRv6_small_det+PP-OCRv6_small_rec",
    mode="whole-page",
)
HANDWRITING_ENGINE_ID = EngineIdentifier(
    family="PP-OCRv5",
    model_name="en_PP-OCRv5_mobile_rec",
    mode="handwriting-fallback",
)

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SOI = b"\xff\xd8"
_ZIP_MAGIC = b"PK\x03\x04"
_PDF_MAGIC = b"%PDF-"
_SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)
_MAX_JPEG_MARKERS_SCANNED = 512


class OcrAdapterError(ContractValidationError):
    """Bounded, fail-closed extraction error with a governed reason code."""


@dataclass(frozen=True, slots=True)
class ImageInfo:
    format: str
    width: int
    height: int


@runtime_checkable
class WholePageEngine(Protocol):
    def predict(self, image_bytes: bytes) -> Sequence[RawDetection]: ...


@runtime_checkable
class HandwritingEngine(Protocol):
    def predict_region(self, image_bytes: bytes, bbox: BBox) -> RawDetection | None: ...


def _reject(reason: str, detail: str) -> "OcrAdapterError":
    return OcrAdapterError(reason, detail)


def _sniff_png(data: bytes) -> ImageInfo:
    if len(data) < 24 or data[:8] != _PNG_SIGNATURE:
        raise _reject("quality-malformed-image", "PNG signature is invalid")
    length, chunk_type = struct.unpack(">I4s", data[8:16])
    if chunk_type != b"IHDR" or length != 13:
        raise _reject("quality-malformed-image", "PNG is missing a leading IHDR chunk")
    width, height = struct.unpack(">II", data[16:24])
    return ImageInfo(format="png", width=width, height=height)


def _sniff_jpeg(data: bytes) -> ImageInfo:
    if len(data) < 4 or data[:2] != _JPEG_SOI:
        raise _reject("quality-malformed-image", "JPEG SOI marker is invalid")
    offset = 2
    markers_scanned = 0
    while offset + 1 < len(data) and markers_scanned < _MAX_JPEG_MARKERS_SCANNED:
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        if marker == 0x00 or marker == 0xFF:
            offset += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            offset += 2
            continue
        if marker == 0xD9:
            break
        if offset + 4 > len(data):
            break
        seg_len = struct.unpack(">H", data[offset + 2 : offset + 4])[0]
        if seg_len < 2:
            raise _reject("quality-malformed-image", "JPEG segment length is invalid")
        if marker in _SOF_MARKERS:
            if offset + 9 > len(data):
                raise _reject("quality-malformed-image", "JPEG SOF segment is truncated")
            height, width = struct.unpack(">HH", data[offset + 5 : offset + 9])
            return ImageInfo(format="jpeg", width=width, height=height)
        offset += 2 + seg_len
        markers_scanned += 1
    raise _reject(
        "quality-malformed-image", "JPEG has no recognizable start-of-frame segment"
    )


def sniff_image_info(data: object) -> ImageInfo:
    """Return bounded structural image info without decoding pixel data.

    Fails closed on empty, oversized, malformed, archive, PDF, or
    unsupported-format input before any bytes beyond a small header prefix
    are inspected.
    """
    if type(data) is not bytes:
        raise _reject("handoff-wrong-type", "image data must be built-in bytes")
    if not data:
        raise _reject("quality-malformed-image", "image data is empty")
    if len(data) > MAX_FILE_BYTES:
        raise _reject("quality-oversized-file", "image exceeds the maximum supported file size")
    if data.startswith(_ZIP_MAGIC):
        raise _reject("quality-unsupported-format", "archive files are not supported images")
    if data.startswith(_PDF_MAGIC):
        raise _reject(
            "quality-unsupported-format", "PDF input is out of scope for this adapter"
        )
    if data[:8] == _PNG_SIGNATURE:
        info = _sniff_png(data)
    elif data[:2] == _JPEG_SOI:
        info = _sniff_jpeg(data)
    else:
        raise _reject(
            "quality-unsupported-format", "only PNG and JPEG page images are supported"
        )
    if info.width <= 0 or info.height <= 0:
        raise _reject("quality-malformed-image", "image dimensions must be positive")
    if info.width > MAX_DIMENSION_PX or info.height > MAX_DIMENSION_PX:
        raise _reject(
            "quality-oversized-file", "image dimensions exceed the maximum supported bound"
        )
    if info.width * info.height > MAX_PIXELS:
        raise _reject(
            "quality-oversized-file",
            "decoded pixel count exceeds the decompression-bomb bound",
        )
    return info


def _normalize_detections(raw: object, *, name: str) -> tuple[RawDetection, ...]:
    if type(raw) is not list and type(raw) is not tuple:
        raise _reject("handoff-wrong-type", f"{name} must return a built-in sequence")
    if len(raw) > MAX_REGIONS:
        raise _reject("quality-oversized-file", f"{name} exceeds the region-count bound")
    checked: list[RawDetection] = []
    for item in raw:
        if type(item) is not RawDetection:
            raise _reject(
                "handoff-wrong-type", f"{name} entries must be exact RawDetection instances"
            )
        if len(item.text) > MAX_TEXT_LENGTH:
            raise _reject("quality-oversized-file", f"{name} text exceeds the length bound")
        checked.append(item)
    checked.sort(key=lambda d: (d.bbox[1], d.bbox[0], d.bbox[3], d.bbox[2]))
    return tuple(checked)


def _run_engine(
    engine: WholePageEngine, image_bytes: bytes, *, timeout_seconds: float
) -> tuple[RawDetection, ...]:
    started = time.monotonic()
    try:
        raw = engine.predict(image_bytes)
    except OcrAdapterError:
        raise
    except Exception as exc:  # noqa: BLE001 - engine failures fail closed
        raise _reject("quality-engine-failure", "whole-page engine raised an exception") from exc
    elapsed = time.monotonic() - started
    if elapsed > timeout_seconds:
        raise _reject(
            "quality-processing-timeout", "whole-page engine exceeded the processing timeout"
        )
    return _normalize_detections(raw, name="whole-page engine result")


def _iou(left: BBox, right: BBox) -> float:
    lx1, ly1, lx2, ly2 = left
    rx1, ry1, rx2, ry2 = right
    ix1, iy1 = max(lx1, rx1), max(ly1, ry1)
    ix2, iy2 = min(lx2, rx2), min(ly2, ry2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    intersection = (ix2 - ix1) * (iy2 - iy1)
    left_area = (lx2 - lx1) * (ly2 - ly1)
    right_area = (rx2 - rx1) * (ry2 - ry1)
    union = left_area + right_area - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def _best_template_match(
    detection: RawDetection, template_detections: Sequence[RawDetection]
) -> float | None:
    best = 0.0
    for candidate in template_detections:
        score = _iou(detection.bbox, candidate.bbox)
        if score > best:
            best = score
    if best <= 0.0:
        return None
    return round(best, 4)


def _resolve_handwriting_fallback(
    handwriting_engine: HandwritingEngine | None,
    image_bytes: bytes,
    detection: RawDetection,
    *,
    timeout_seconds: float,
) -> RawDetection | None:
    if handwriting_engine is None:
        return None
    started = time.monotonic()
    try:
        result = handwriting_engine.predict_region(image_bytes, detection.bbox)
    except OcrAdapterError:
        raise
    except Exception as exc:  # noqa: BLE001 - engine failures fail closed
        raise _reject(
            "quality-engine-failure", "handwriting fallback engine raised an exception"
        ) from exc
    elapsed = time.monotonic() - started
    if elapsed > timeout_seconds:
        raise _reject(
            "quality-processing-timeout",
            "handwriting fallback engine exceeded the processing timeout",
        )
    if result is None:
        return None
    if type(result) is not RawDetection:
        raise _reject(
            "handoff-wrong-type",
            "handwriting fallback engine must return a RawDetection or None",
        )
    if len(result.text) > MAX_TEXT_LENGTH:
        raise _reject(
            "quality-oversized-file", "handwriting fallback text exceeds the length bound"
        )
    return result


def _normalize_text_for_comparison(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _build_region(
    index: int,
    detection: RawDetection,
    *,
    template_detections: Sequence[RawDetection] | None,
    handwriting_engine: HandwritingEngine | None,
    image_bytes: bytes,
    low_confidence_threshold: float,
    timeout_seconds: float,
) -> tuple[ExtractionRegion, bool]:
    findings: list[str] = []
    text: str | None = detection.text
    confidence = detection.confidence
    recognition_path: str = "primary"
    alternate_text: str | None = None
    alternate_confidence: float | None = None
    disagreement = False
    manual_review_required = False

    if not detection.text:
        text = None
        findings.append("unreadable-region")
        manual_review_required = True

    if confidence < low_confidence_threshold:
        findings.append("low-confidence")
        fallback = _resolve_handwriting_fallback(
            handwriting_engine,
            image_bytes,
            detection,
            timeout_seconds=timeout_seconds,
        )
        if fallback is not None:
            recognition_path = "handwriting-fallback"
            same_text = _normalize_text_for_comparison(
                detection.text
            ) == _normalize_text_for_comparison(fallback.text)
            if same_text:
                text = fallback.text
                confidence = max(detection.confidence, fallback.confidence)
            else:
                disagreement = True
                findings.append("engine-disagreement")
                alternate_text = detection.text
                alternate_confidence = detection.confidence
                text = fallback.text
                confidence = fallback.confidence
                manual_review_required = True
        else:
            manual_review_required = True

    template_pairing_confidence: float | None = None
    if template_detections is not None:
        template_pairing_confidence = _best_template_match(detection, template_detections)
        if template_pairing_confidence is None:
            findings.append("template-pairing-unmatched")
        elif template_pairing_confidence < TEMPLATE_PAIRING_MIN_IOU:
            findings.append("template-pairing-weak")

    if confidence < low_confidence_threshold and not manual_review_required:
        manual_review_required = True

    region = ExtractionRegion(
        region_id=f"region-{index:04d}",
        bbox=detection.bbox,
        text=text,
        confidence=confidence,
        recognition_path=recognition_path,  # type: ignore[arg-type]
        alternate_text=alternate_text,
        alternate_confidence=alternate_confidence,
        disagreement=disagreement,
        template_pairing_confidence=template_pairing_confidence,
        manual_review_required=manual_review_required,
        findings=tuple(findings),
    )
    return region, manual_review_required


def extract_page_evidence(
    image_bytes: object,
    *,
    source_ref: object,
    record_id: object,
    whole_page_engine: WholePageEngine,
    record_revision: int = 1,
    page_index: int = 0,
    template_image_bytes: object = None,
    handwriting_engine: HandwritingEngine | None = None,
    low_confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD,
    timeout_seconds: float = PROCESSING_TIMEOUT_SECONDS,
) -> ValidationResult:
    """Extract bounded, EIA1-compatible document-reading evidence for one page.

    ``whole_page_engine`` and, optionally, ``handwriting_engine`` are
    caller-supplied and never constructed by this function. The adapter
    performs no network, filesystem, subprocess, or model-loading side
    effects of its own; any such behavior belongs entirely to the injected
    engine implementation.
    """
    try:
        record_id = validate_stable_id(record_id, "record_id")
        validate_revision(record_revision)
        source_ref = validate_text(source_ref, "source_ref")
        if type(page_index) is not int or page_index < 0:
            raise _reject("handoff-invalid", "page_index must be a non-negative built-in integer")
        if type(low_confidence_threshold) is not float or not (
            0.0 <= low_confidence_threshold <= 1.0
        ):
            raise _reject(
                "handoff-invalid",
                "low_confidence_threshold must be a built-in float in [0.0, 1.0]",
            )
        if type(timeout_seconds) is not float or timeout_seconds <= 0.0:
            raise _reject("handoff-invalid", "timeout_seconds must be a positive built-in float")

        sniff_image_info(image_bytes)
        detections = _run_engine(whole_page_engine, image_bytes, timeout_seconds=timeout_seconds)

        template_supplied = template_image_bytes is not None
        template_detections: tuple[RawDetection, ...] | None = None
        if template_supplied:
            sniff_image_info(template_image_bytes)
            template_detections = _run_engine(
                whole_page_engine, template_image_bytes, timeout_seconds=timeout_seconds
            )

        regions: list[ExtractionRegion] = []
        any_manual_review = False
        for index, detection in enumerate(detections):
            region, manual_review = _build_region(
                index,
                detection,
                template_detections=template_detections,
                handwriting_engine=handwriting_engine,
                image_bytes=image_bytes,
                low_confidence_threshold=low_confidence_threshold,
                timeout_seconds=timeout_seconds,
            )
            regions.append(region)
            any_manual_review = any_manual_review or manual_review

        quality_findings: list[str] = []
        if not regions:
            quality_findings.append("no-text-detected")
        low_conf_ratio = (
            sum(1 for r in regions if r.confidence < low_confidence_threshold) / len(regions)
            if regions
            else 0.0
        )
        if low_conf_ratio >= 0.5 and regions:
            quality_findings.append("low-overall-confidence")

        if not regions:
            image_quality_disposition = "unusable"
        elif quality_findings:
            image_quality_disposition = "degraded"
        else:
            image_quality_disposition = "acceptable"

        template_alignment_status: str
        if not template_supplied:
            template_alignment_status = "not-supplied"
        else:
            paired = sum(1 for r in regions if r.template_pairing_confidence is not None)
            if not regions or paired == 0:
                template_alignment_status = "mismatched"
            elif paired == len(regions):
                template_alignment_status = "aligned"
            else:
                template_alignment_status = "partial"

        manual_review_required = any_manual_review or image_quality_disposition == "unusable"
        if regions:
            confidence_level = (
                "high"
                if not manual_review_required and low_conf_ratio == 0.0
                else "medium"
                if low_conf_ratio < 0.5
                else "low"
            )
        else:
            confidence_level = "low"

        confidence_basis = tuple(
            sorted(
                {
                    f"regions-detected:{len(regions)}",
                    f"low-confidence-ratio:{low_conf_ratio:.2f}",
                    f"template-supplied:{template_supplied}",
                }
            )
        )

        engine_provenance = (WHOLE_PAGE_ENGINE_ID,)
        if any(region.recognition_path == "handwriting-fallback" for region in regions):
            engine_provenance = (WHOLE_PAGE_ENGINE_ID, HANDWRITING_ENGINE_ID)

        evidence = PageExtractionEvidence(
            contract_version=CONTRACT_ID,
            record_id=record_id,
            record_revision=record_revision,
            source_ref=source_ref,
            page_index=page_index,
            template_supplied=template_supplied,
            template_alignment_status=template_alignment_status,  # type: ignore[arg-type]
            image_quality_disposition=image_quality_disposition,  # type: ignore[arg-type]
            image_quality_findings=tuple(quality_findings),
            regions=tuple(regions),
            engine_provenance=engine_provenance,
            confidence=confidence_level,  # type: ignore[arg-type]
            confidence_basis=confidence_basis,
            manual_review_required=manual_review_required,
        )

        output = _evidence_to_dict(evidence)
        if canonical_size(output) > 32 * 1024:
            raise _reject(
                "quality-oversized-file", "normalized extraction evidence exceeds its byte bound"
            )

        record = ValidatedRecord(
            contract_version=CONTRACT_ID,
            record_id=record_id,
            record_revision=record_revision,
            fingerprint_algorithm=FINGERPRINT_ALGORITHM,
            fingerprint=sha256_hex(output),
            payload=freeze_json(output),
        )

        if image_quality_disposition == "unusable":
            return ValidationResult(
                status=ValidationStatus.BLOCKED,
                record=record,
                blockers=("quality-unusable-image",),
                reason_codes=(),
                details=(),
            )
        if manual_review_required:
            return ValidationResult(
                status=ValidationStatus.MANUAL_REVIEW_REQUIRED,
                record=record,
                reason_codes=("manual-review-inspection",),
                details=(),
            )
        return ValidationResult(status=ValidationStatus.VALID, record=record)
    except ContractValidationError as exc:
        return ValidationResult(
            status=ValidationStatus.INVALID,
            record=None,
            reason_codes=(exc.reason_code,),
            details=(exc.detail,),
        )
    except (TypeError, ValueError):
        return ValidationResult(
            status=ValidationStatus.INVALID,
            record=None,
            reason_codes=("handoff-invalid",),
            details=("page extraction validation failed",),
        )


def _evidence_to_dict(evidence: PageExtractionEvidence) -> dict[str, object]:
    return {
        "contract_version": evidence.contract_version,
        "record_id": evidence.record_id,
        "record_revision": evidence.record_revision,
        "source_ref": evidence.source_ref,
        "page_index": evidence.page_index,
        "template_supplied": evidence.template_supplied,
        "template_alignment_status": evidence.template_alignment_status,
        "image_quality_disposition": evidence.image_quality_disposition,
        "image_quality_findings": list(evidence.image_quality_findings),
        "regions": [
            {
                "region_id": region.region_id,
                "bbox": list(region.bbox),
                "text": region.text,
                "confidence": region.confidence,
                "recognition_path": region.recognition_path,
                "alternate_text": region.alternate_text,
                "alternate_confidence": region.alternate_confidence,
                "disagreement": region.disagreement,
                "template_pairing_confidence": region.template_pairing_confidence,
                "manual_review_required": region.manual_review_required,
                "findings": list(region.findings),
            }
            for region in evidence.regions
        ],
        "engine_provenance": [
            {"family": e.family, "model_name": e.model_name, "mode": e.mode}
            for e in evidence.engine_provenance
        ],
        "confidence": evidence.confidence,
        "confidence_basis": list(evidence.confidence_basis),
        "manual_review_required": evidence.manual_review_required,
        "report_only": evidence.report_only,
        "grading_authorized": evidence.grading_authorized,
        "readiness_authorized": evidence.readiness_authorized,
        "student_classification_authorized": evidence.student_classification_authorized,
        "route_assignment_authorized": evidence.route_assignment_authorized,
        "production_authorized": evidence.production_authorized,
        "external_write_authorized": evidence.external_write_authorized,
    }


class PaddleOcrEngine:
    """Reference engine backed by the real, pinned PaddleOCR/PaddleX models.

    Not exercised by this repository's tests or by module import: importing
    ``paddleocr`` happens lazily inside ``__init__`` only when a caller
    explicitly constructs this class. ``paddleocr``/``paddlepaddle`` are not
    yet declared as repository dependencies -- see EIA5 / Issue #716 for the
    exact pinned versions, checksums, and license disposition. Constructing
    this class without them installed raises ``ModuleNotFoundError``, and
    running it additionally requires the exact pinned model weights to be
    reachable, which EIA5 could not obtain in a sandboxed evaluation
    environment (see the EIA5 report for the network-policy evidence).
    """

    def __init__(self) -> None:
        import paddleocr  # noqa: PLC0415 - intentionally deferred, see class docstring

        self._whole_page = paddleocr.PaddleOCR(
            text_detection_model_name="PP-OCRv6_small_det",
            text_recognition_model_name="PP-OCRv6_small_rec",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            device="cpu",
        )
        self._handwriting = paddleocr.TextRecognition(
            model_name="en_PP-OCRv5_mobile_rec", device="cpu"
        )
        self._paddleocr = paddleocr

    def predict(self, image_bytes: bytes) -> list[RawDetection]:
        import io

        from PIL import Image  # noqa: PLC0415 - intentionally deferred
        import numpy as np  # noqa: PLC0415 - intentionally deferred

        image = np.array(Image.open(io.BytesIO(image_bytes)).convert("RGB"))
        results = self._whole_page.predict(image)
        detections: list[RawDetection] = []
        for page in results:
            texts = page["rec_texts"]
            scores = page["rec_scores"]
            boxes = page["rec_boxes"]
            for text, score, box in zip(texts, scores, boxes):
                x1, y1, x2, y2 = (int(v) for v in box)
                detections.append(
                    RawDetection(bbox=(x1, y1, x2, y2), text=str(text), confidence=float(score))
                )
        return detections

    def predict_region(self, image_bytes: bytes, bbox: BBox) -> RawDetection | None:
        import io

        from PIL import Image  # noqa: PLC0415 - intentionally deferred
        import numpy as np  # noqa: PLC0415 - intentionally deferred

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        x1, y1, x2, y2 = bbox
        crop = np.array(image.crop((x1, y1, x2, y2)))
        results = self._handwriting.predict(crop)
        for result in results:
            return RawDetection(
                bbox=bbox, text=str(result["rec_text"]), confidence=float(result["rec_score"])
            )
        return None
