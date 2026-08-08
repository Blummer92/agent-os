"""Immutable models for local visual-asset intake."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

_SUPPORTED_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})


class IntakeState(str, Enum):
    READY_FOR_EXACT_DUPLICATE_LOOKUP = "READY_FOR_EXACT_DUPLICATE_LOOKUP"


class IntakeErrorCode(str, Enum):
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    CORRUPT_IMAGE = "CORRUPT_IMAGE"
    INPUT_TOO_LARGE = "INPUT_TOO_LARGE"
    PIXEL_LIMIT_EXCEEDED = "PIXEL_LIMIT_EXCEEDED"
    UNSUPPORTED_MULTIFRAME_IMAGE = "UNSUPPORTED_MULTIFRAME_IMAGE"
    NORMALIZATION_FAILED = "NORMALIZATION_FAILED"
    INVALID_PATH = "INVALID_PATH"


class IntakeError(ValueError):
    """Finite, sanitized intake failure."""

    def __init__(self, code: IntakeErrorCode, detail: str) -> None:
        self.code = code
        super().__init__(f"{code.value}: {detail}")


@dataclass(frozen=True, slots=True)
class IntakePolicy:
    max_source_bytes: int = 25 * 1024 * 1024
    max_decoded_pixels: int = 40_000_000
    allowed_formats: tuple[str, ...] = ("JPEG", "PNG", "WEBP")

    def __post_init__(self) -> None:
        if self.max_source_bytes <= 0 or self.max_decoded_pixels <= 0:
            raise ValueError("intake limits must be positive")
        if not self.allowed_formats or any(value not in _SUPPORTED_FORMATS for value in self.allowed_formats):
            raise ValueError("allowed_formats contains an unsupported raster format")


@dataclass(frozen=True, slots=True)
class AssetIntakeResult:
    intake_id: str
    original_filename: str
    original_size_bytes: int
    detected_format: str
    mime_type: str
    width: int
    height: int
    frame_count: int
    color_mode: str
    has_alpha: bool
    original_sha256: str
    normalized_sha256: str
    normalized_path: Path
    normalized_format: str
    orientation_normalized: bool
    color_normalized: bool
    gps_metadata_present: bool
    exif_present: bool
    icc_profile_present: bool
    warnings: tuple[str, ...]
    state: IntakeState = IntakeState.READY_FOR_EXACT_DUPLICATE_LOOKUP
    external_write_authorized: bool = False
    approval_authorized: bool = False
    classroom_readiness_authorized: bool = False
    production_authorized: bool = False
