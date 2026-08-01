from __future__ import annotations

import struct
import sys

import pytest

from instructional_evidence_intake import (
    HANDWRITING_ENGINE_ID,
    WHOLE_PAGE_ENGINE_ID,
    OcrAdapterError,
    RawDetection,
    extract_page_evidence,
    sniff_image_info,
)
from instructional_evidence_intake.models import CONTRACT_ID
from instructional_workflow_contracts import ValidationStatus

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_bytes(width: int, height: int, *, padding: int = 32) -> bytes:
    header = _PNG_SIGNATURE + struct.pack(">I4s", 13, b"IHDR") + struct.pack(">II", width, height)
    return header + b"\x00" * padding


def _jpeg_bytes(width: int, height: int) -> bytes:
    body = bytes([8]) + struct.pack(">HH", height, width) + bytes([1]) + bytes([1, 0x11, 0])
    sof = b"\xff\xc0" + struct.pack(">H", 2 + len(body)) + body
    return b"\xff\xd8" + sof + b"\xff\xd9"


def _detection(bbox=(10, 10, 100, 40), text="hello", confidence=0.95) -> RawDetection:
    return RawDetection(bbox=bbox, text=text, confidence=confidence)


class _StaticWholePageEngine:
    def __init__(self, by_image: dict[bytes, list[RawDetection]]) -> None:
        self._by_image = by_image

    def predict(self, image_bytes: bytes) -> list[RawDetection]:
        return self._by_image[image_bytes]


class _StaticHandwritingEngine:
    def __init__(self, result: RawDetection | None) -> None:
        self._result = result

    def predict_region(self, image_bytes: bytes, bbox) -> RawDetection | None:
        return self._result


class _RaisingEngine:
    def predict(self, image_bytes: bytes):
        raise RuntimeError("boom")


class _SlowEngine:
    def __init__(self, delay: float) -> None:
        self._delay = delay

    def predict(self, image_bytes: bytes):
        import time

        time.sleep(self._delay)
        return []


class _WrongTypeEngine:
    def predict(self, image_bytes: bytes):
        return "not-a-sequence"


class _WrongItemEngine:
    def predict(self, image_bytes: bytes):
        return [{"bbox": (0, 0, 1, 1), "text": "x", "confidence": 0.9}]


# ---------------------------------------------------------------------------
# sniff_image_info
# ---------------------------------------------------------------------------


def test_sniff_png_returns_dimensions() -> None:
    info = sniff_image_info(_png_bytes(120, 80))
    assert info.format == "png"
    assert info.width == 120
    assert info.height == 80


def test_sniff_jpeg_returns_dimensions() -> None:
    info = sniff_image_info(_jpeg_bytes(200, 150))
    assert info.format == "jpeg"
    assert info.width == 200
    assert info.height == 150


def test_sniff_rejects_wrong_type() -> None:
    with pytest.raises(OcrAdapterError) as exc:
        sniff_image_info("not-bytes")
    assert exc.value.reason_code == "handoff-wrong-type"


def test_sniff_rejects_empty_bytes() -> None:
    with pytest.raises(OcrAdapterError) as exc:
        sniff_image_info(b"")
    assert exc.value.reason_code == "quality-malformed-image"


def test_sniff_rejects_oversized_file() -> None:
    huge = _png_bytes(10, 10, padding=9 * 1024 * 1024)
    with pytest.raises(OcrAdapterError) as exc:
        sniff_image_info(huge)
    assert exc.value.reason_code == "quality-oversized-file"


def test_sniff_rejects_archive_magic() -> None:
    with pytest.raises(OcrAdapterError) as exc:
        sniff_image_info(b"PK\x03\x04" + b"\x00" * 40)
    assert exc.value.reason_code == "quality-unsupported-format"


def test_sniff_rejects_pdf_magic() -> None:
    with pytest.raises(OcrAdapterError) as exc:
        sniff_image_info(b"%PDF-1.4\n" + b"\x00" * 40)
    assert exc.value.reason_code == "quality-unsupported-format"


def test_sniff_rejects_unsupported_format() -> None:
    with pytest.raises(OcrAdapterError) as exc:
        sniff_image_info(b"GIF89a" + b"\x00" * 40)
    assert exc.value.reason_code == "quality-unsupported-format"


def test_sniff_rejects_malformed_png_ihdr() -> None:
    malformed = _PNG_SIGNATURE + struct.pack(">I4s", 13, b"IDAT") + b"\x00" * 20
    with pytest.raises(OcrAdapterError) as exc:
        sniff_image_info(malformed)
    assert exc.value.reason_code == "quality-malformed-image"


def test_sniff_rejects_truncated_jpeg() -> None:
    with pytest.raises(OcrAdapterError) as exc:
        sniff_image_info(b"\xff\xd8\xff\xd9")
    assert exc.value.reason_code == "quality-malformed-image"


def test_sniff_rejects_oversized_dimensions() -> None:
    with pytest.raises(OcrAdapterError) as exc:
        sniff_image_info(_png_bytes(5000, 5000))
    assert exc.value.reason_code == "quality-oversized-file"


def test_sniff_rejects_zero_dimensions() -> None:
    with pytest.raises(OcrAdapterError) as exc:
        sniff_image_info(_png_bytes(0, 100))
    assert exc.value.reason_code == "quality-malformed-image"


# ---------------------------------------------------------------------------
# extract_page_evidence - happy paths
# ---------------------------------------------------------------------------


def test_valid_page_returns_deterministic_normalized_evidence() -> None:
    image = _png_bytes(300, 200)
    engine = _StaticWholePageEngine({image: [_detection()]})
    result = extract_page_evidence(
        image,
        source_ref="worksheet-1",
        record_id="page-1",
        whole_page_engine=engine,
    )
    assert result.status == ValidationStatus.VALID
    payload = result.record.to_dict()
    assert payload["contract_version"] == CONTRACT_ID
    assert payload["regions"][0]["text"] == "hello"
    assert payload["report_only"] is True
    assert payload["grading_authorized"] is False
    assert payload["external_write_authorized"] is False


def test_repeated_runs_produce_identical_fingerprint() -> None:
    image = _png_bytes(300, 200)
    engine = _StaticWholePageEngine({image: [_detection()]})
    first = extract_page_evidence(
        image, source_ref="worksheet-1", record_id="page-1", whole_page_engine=engine
    )
    second = extract_page_evidence(
        image, source_ref="worksheet-1", record_id="page-1", whole_page_engine=engine
    )
    assert first.record.fingerprint == second.record.fingerprint


def test_multiple_regions_are_sorted_deterministically_regardless_of_engine_order() -> None:
    image = _png_bytes(300, 200)
    bottom = RawDetection(bbox=(0, 100, 50, 130), text="bottom", confidence=0.9)
    top = RawDetection(bbox=(0, 0, 50, 30), text="top", confidence=0.9)
    engine = _StaticWholePageEngine({image: [bottom, top]})
    result = extract_page_evidence(
        image, source_ref="worksheet-1", record_id="page-1", whole_page_engine=engine
    )
    payload = result.record.to_dict()
    assert [r["text"] for r in payload["regions"]] == ["top", "bottom"]


def test_no_text_detected_marks_image_unusable_and_blocked() -> None:
    image = _png_bytes(300, 200)
    engine = _StaticWholePageEngine({image: []})
    result = extract_page_evidence(
        image, source_ref="worksheet-1", record_id="page-1", whole_page_engine=engine
    )
    assert result.status == ValidationStatus.BLOCKED
    assert result.record.to_dict()["image_quality_disposition"] == "unusable"


# ---------------------------------------------------------------------------
# handwriting fallback and disagreement
# ---------------------------------------------------------------------------


def test_low_confidence_region_triggers_bounded_handwriting_fallback() -> None:
    image = _png_bytes(300, 200)
    low_conf = RawDetection(bbox=(0, 0, 50, 30), text="ansver", confidence=0.4)
    engine = _StaticWholePageEngine({image: [low_conf]})
    fallback = RawDetection(bbox=(0, 0, 50, 30), text="answer", confidence=0.85)
    handwriting = _StaticHandwritingEngine(fallback)
    result = extract_page_evidence(
        image,
        source_ref="worksheet-1",
        record_id="page-1",
        whole_page_engine=engine,
        handwriting_engine=handwriting,
    )
    region = result.record.to_dict()["regions"][0]
    assert region["recognition_path"] == "handwriting-fallback"
    assert region["text"] == "answer"


def test_high_confidence_region_never_calls_handwriting_fallback() -> None:
    image = _png_bytes(300, 200)
    engine = _StaticWholePageEngine({image: [_detection(confidence=0.98)]})

    class _FailIfCalled:
        def predict_region(self, image_bytes, bbox):
            raise AssertionError("handwriting fallback must not run for high-confidence regions")

    result = extract_page_evidence(
        image,
        source_ref="worksheet-1",
        record_id="page-1",
        whole_page_engine=engine,
        handwriting_engine=_FailIfCalled(),
    )
    assert result.status == ValidationStatus.VALID


def test_engine_disagreement_requires_review_and_preserves_alternatives() -> None:
    image = _png_bytes(300, 200)
    low_conf = RawDetection(bbox=(0, 0, 50, 30), text="6", confidence=0.3)
    engine = _StaticWholePageEngine({image: [low_conf]})
    fallback = RawDetection(bbox=(0, 0, 50, 30), text="b", confidence=0.6)
    handwriting = _StaticHandwritingEngine(fallback)
    result = extract_page_evidence(
        image,
        source_ref="worksheet-1",
        record_id="page-1",
        whole_page_engine=engine,
        handwriting_engine=handwriting,
    )
    assert result.status == ValidationStatus.MANUAL_REVIEW_REQUIRED
    region = result.record.to_dict()["regions"][0]
    assert region["disagreement"] is True
    assert region["alternate_text"] == "6"
    assert region["manual_review_required"] is True


def test_low_confidence_without_fallback_engine_stays_manual_review() -> None:
    image = _png_bytes(300, 200)
    engine = _StaticWholePageEngine({image: [_detection(confidence=0.2)]})
    result = extract_page_evidence(
        image, source_ref="worksheet-1", record_id="page-1", whole_page_engine=engine
    )
    assert result.status == ValidationStatus.MANUAL_REVIEW_REQUIRED


def test_unreadable_region_becomes_unknown_not_invented() -> None:
    image = _png_bytes(300, 200)
    engine = _StaticWholePageEngine({image: [_detection(text="", confidence=0.9)]})
    result = extract_page_evidence(
        image, source_ref="worksheet-1", record_id="page-1", whole_page_engine=engine
    )
    region = result.record.to_dict()["regions"][0]
    assert region["text"] is None
    assert "unreadable-region" in region["findings"]


# ---------------------------------------------------------------------------
# template alignment
# ---------------------------------------------------------------------------


def test_missing_template_is_supported_with_explicit_limitation() -> None:
    image = _png_bytes(300, 200)
    engine = _StaticWholePageEngine({image: [_detection()]})
    result = extract_page_evidence(
        image, source_ref="worksheet-1", record_id="page-1", whole_page_engine=engine
    )
    payload = result.record.to_dict()
    assert payload["template_supplied"] is False
    assert payload["template_alignment_status"] == "not-supplied"
    assert payload["regions"][0]["template_pairing_confidence"] is None


def test_matching_template_produces_aligned_pairing_confidence() -> None:
    image = _png_bytes(300, 200)
    template = _png_bytes(300, 200, padding=64)
    detection = _detection(bbox=(10, 10, 100, 40))
    template_detection = RawDetection(bbox=(10, 10, 100, 40), text="", confidence=0.5)
    engine = _StaticWholePageEngine({image: [detection], template: [template_detection]})
    result = extract_page_evidence(
        image,
        source_ref="worksheet-1",
        record_id="page-1",
        whole_page_engine=engine,
        template_image_bytes=template,
    )
    payload = result.record.to_dict()
    assert payload["template_alignment_status"] == "aligned"
    assert payload["regions"][0]["template_pairing_confidence"] == pytest.approx(1.0)


def test_template_mismatch_downgrades_pairing() -> None:
    image = _png_bytes(300, 200)
    template = _png_bytes(300, 200, padding=64)
    detection = _detection(bbox=(10, 10, 100, 40))
    template_detection = RawDetection(bbox=(200, 150, 260, 190), text="", confidence=0.5)
    engine = _StaticWholePageEngine({image: [detection], template: [template_detection]})
    result = extract_page_evidence(
        image,
        source_ref="worksheet-1",
        record_id="page-1",
        whole_page_engine=engine,
        template_image_bytes=template,
    )
    payload = result.record.to_dict()
    assert payload["template_alignment_status"] == "mismatched"
    assert payload["regions"][0]["template_pairing_confidence"] is None
    assert "template-pairing-unmatched" in payload["regions"][0]["findings"]


# ---------------------------------------------------------------------------
# malformed / hostile / bounded inputs fail closed
# ---------------------------------------------------------------------------


def test_malformed_image_fails_closed_with_invalid_status() -> None:
    engine = _StaticWholePageEngine({})
    result = extract_page_evidence(
        b"not-an-image", source_ref="worksheet-1", record_id="page-1", whole_page_engine=engine
    )
    assert result.status == ValidationStatus.INVALID
    assert result.record is None
    assert result.reason_codes == ("quality-unsupported-format",)


def test_engine_exception_fails_closed() -> None:
    image = _png_bytes(300, 200)
    result = extract_page_evidence(
        image, source_ref="worksheet-1", record_id="page-1", whole_page_engine=_RaisingEngine()
    )
    assert result.status == ValidationStatus.INVALID
    assert result.reason_codes == ("quality-engine-failure",)


def test_engine_timeout_fails_closed() -> None:
    image = _png_bytes(300, 200)
    result = extract_page_evidence(
        image,
        source_ref="worksheet-1",
        record_id="page-1",
        whole_page_engine=_SlowEngine(0.05),
        timeout_seconds=0.01,
    )
    assert result.status == ValidationStatus.INVALID
    assert result.reason_codes == ("quality-processing-timeout",)


def test_engine_wrong_return_type_fails_closed() -> None:
    image = _png_bytes(300, 200)
    result = extract_page_evidence(
        image, source_ref="worksheet-1", record_id="page-1", whole_page_engine=_WrongTypeEngine()
    )
    assert result.status == ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-wrong-type",)


def test_engine_wrong_item_type_fails_closed() -> None:
    image = _png_bytes(300, 200)
    result = extract_page_evidence(
        image, source_ref="worksheet-1", record_id="page-1", whole_page_engine=_WrongItemEngine()
    )
    assert result.status == ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-wrong-type",)


def test_too_many_regions_fails_closed() -> None:
    image = _png_bytes(300, 200)
    many = [
        RawDetection(bbox=(i, i, i + 1, i + 1), text="x", confidence=0.9) for i in range(300)
    ]
    engine = _StaticWholePageEngine({image: many})
    result = extract_page_evidence(
        image, source_ref="worksheet-1", record_id="page-1", whole_page_engine=engine
    )
    assert result.status == ValidationStatus.INVALID
    assert result.reason_codes == ("quality-oversized-file",)


def test_invalid_record_id_fails_closed() -> None:
    image = _png_bytes(300, 200)
    engine = _StaticWholePageEngine({image: [_detection()]})
    result = extract_page_evidence(
        image, source_ref="worksheet-1", record_id="bad id!", whole_page_engine=engine
    )
    assert result.status == ValidationStatus.INVALID


def test_invalid_low_confidence_threshold_fails_closed() -> None:
    image = _png_bytes(300, 200)
    engine = _StaticWholePageEngine({image: [_detection()]})
    result = extract_page_evidence(
        image,
        source_ref="worksheet-1",
        record_id="page-1",
        whole_page_engine=engine,
        low_confidence_threshold=1.5,
    )
    assert result.status == ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-invalid",)


def test_hostile_bbox_type_is_rejected_by_raw_detection() -> None:
    with pytest.raises(TypeError):
        RawDetection(bbox=[0, 0, 1, 1], text="x", confidence=0.9)


def test_confidence_out_of_bounds_is_rejected_by_raw_detection() -> None:
    with pytest.raises(ValueError):
        RawDetection(bbox=(0, 0, 1, 1), text="x", confidence=1.5)


# ---------------------------------------------------------------------------
# provenance, authority, and import isolation
# ---------------------------------------------------------------------------


def test_engine_provenance_names_pinned_models() -> None:
    image = _png_bytes(300, 200)
    engine = _StaticWholePageEngine({image: [_detection()]})
    result = extract_page_evidence(
        image, source_ref="worksheet-1", record_id="page-1", whole_page_engine=engine
    )
    provenance = result.record.to_dict()["engine_provenance"]
    assert provenance[0]["model_name"] == "PP-OCRv6_small_det+PP-OCRv6_small_rec"
    assert WHOLE_PAGE_ENGINE_ID.family == "PP-OCRv6"
    assert HANDWRITING_ENGINE_ID.model_name == "en_PP-OCRv5_mobile_rec"


def test_authority_fields_are_immutably_false() -> None:
    image = _png_bytes(300, 200)
    engine = _StaticWholePageEngine({image: [_detection()]})
    result = extract_page_evidence(
        image, source_ref="worksheet-1", record_id="page-1", whole_page_engine=engine
    )
    payload = result.record.to_dict()
    for field_name in (
        "grading_authorized",
        "readiness_authorized",
        "student_classification_authorized",
        "route_assignment_authorized",
        "production_authorized",
        "external_write_authorized",
    ):
        assert payload[field_name] is False


def test_module_import_does_not_pull_in_image_or_ml_libraries() -> None:
    for forbidden in ("paddleocr", "paddle", "PIL", "numpy", "cv2"):
        assert forbidden not in sys.modules, f"{forbidden} must not be imported as a side effect"


def test_paddle_ocr_engine_import_is_lazy_and_unavailable_without_paddleocr() -> None:
    from instructional_evidence_intake.ocr_adapter import PaddleOcrEngine

    if "paddleocr" in sys.modules:
        pytest.skip("paddleocr happens to be installed in this environment")
    with pytest.raises(ModuleNotFoundError):
        PaddleOcrEngine()
