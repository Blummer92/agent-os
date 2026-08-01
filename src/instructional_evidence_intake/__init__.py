"""Public surface for pure teacher-summary evidence interpretation and OCR extraction."""

from .alignment import DIMENSION_ORDER, build_alignment
from .interpreter import CONTRACT_ID, interpret_teacher_summary
from .models import CONTRACT_ID as OCR_CONTRACT_ID
from .models import EngineIdentifier, ExtractionRegion, PageExtractionEvidence, RawDetection
from .ocr_adapter import (
    HANDWRITING_ENGINE_ID,
    WHOLE_PAGE_ENGINE_ID,
    HandwritingEngine,
    OcrAdapterError,
    WholePageEngine,
    extract_page_evidence,
    sniff_image_info,
)

__all__ = [
    "CONTRACT_ID",
    "DIMENSION_ORDER",
    "HANDWRITING_ENGINE_ID",
    "OCR_CONTRACT_ID",
    "WHOLE_PAGE_ENGINE_ID",
    "EngineIdentifier",
    "ExtractionRegion",
    "HandwritingEngine",
    "OcrAdapterError",
    "PageExtractionEvidence",
    "RawDetection",
    "WholePageEngine",
    "build_alignment",
    "extract_page_evidence",
    "interpret_teacher_summary",
    "sniff_image_info",
]
