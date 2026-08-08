"""Bounded local raster-image inspection and normalization."""

from __future__ import annotations

import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .hashing import sha256_file
from .models import AssetIntakeResult, IntakeError, IntakeErrorCode, IntakePolicy

_MIME_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
_EXTENSIONS = {"JPEG": {".jpg", ".jpeg"}, "PNG": {".png"}, "WEBP": {".webp"}}
_ALPHA_MODES = {"RGBA", "LA", "PA"}
_GPS_IFD_TAG = 34853


def _open_checked(path: Path) -> Image.Image:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            return Image.open(path)
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise IntakeError(IntakeErrorCode.PIXEL_LIMIT_EXCEEDED, "image exceeds decoder safety limits") from None
    except (UnidentifiedImageError, OSError, ValueError):
        raise IntakeError(IntakeErrorCode.CORRUPT_IMAGE, "image cannot be decoded") from None


def _gps_present(exif: Image.Exif) -> bool:
    try:
        return bool(exif.get_ifd(_GPS_IFD_TAG))
    except (KeyError, TypeError, ValueError, AttributeError):
        return bool(exif.get(_GPS_IFD_TAG))


def _has_alpha(image: Image.Image) -> bool:
    return image.mode in _ALPHA_MODES or "transparency" in image.info


def intake_visual_asset(
    source_path: str | Path,
    *,
    output_dir: str | Path,
    policy: IntakePolicy = IntakePolicy(),
) -> AssetIntakeResult:
    """Inspect one local raster and emit a metadata-stripped normalized PNG."""
    source = Path(source_path)
    destination = Path(output_dir)
    if not source.is_file():
        raise IntakeError(IntakeErrorCode.INVALID_PATH, "source must be an existing file")
    source_size = source.stat().st_size
    if source_size > policy.max_source_bytes:
        raise IntakeError(IntakeErrorCode.INPUT_TOO_LARGE, "source exceeds configured byte limit")

    original_sha = sha256_file(source)
    intake_id = f"intake-{original_sha[:24]}"
    warnings_out: list[str] = []

    probe = _open_checked(source)
    try:
        detected_format = (probe.format or "").upper()
        if detected_format not in policy.allowed_formats:
            raise IntakeError(IntakeErrorCode.UNSUPPORTED_FORMAT, "decoded image format is not allowed")
        frame_count = int(getattr(probe, "n_frames", 1))
        if frame_count != 1:
            raise IntakeError(IntakeErrorCode.UNSUPPORTED_MULTIFRAME_IMAGE, "multi-frame images are not supported")
        width, height = probe.size
        if width <= 0 or height <= 0 or width * height > policy.max_decoded_pixels:
            raise IntakeError(IntakeErrorCode.PIXEL_LIMIT_EXCEEDED, "decoded image exceeds configured pixel limit")
        color_mode = probe.mode
        has_alpha = _has_alpha(probe)
        exif = probe.getexif()
        exif_present = bool(exif)
        gps_present = _gps_present(exif) if exif_present else False
        icc_present = bool(probe.info.get("icc_profile"))
        suffix = source.suffix.lower()
        if suffix and suffix not in _EXTENSIONS[detected_format]:
            warnings_out.append("extension-content-mismatch")
        orientation = exif.get(274, 1) if exif_present else 1
    finally:
        probe.close()

    try:
        image = _open_checked(source)
        try:
            image.load()
            normalized = ImageOps.exif_transpose(image)
            target_mode = "RGBA" if has_alpha else "RGB"
            color_normalized = normalized.mode != target_mode
            if color_normalized:
                normalized = normalized.convert(target_mode)
            destination.mkdir(parents=True, exist_ok=True)
            normalized_path = destination / f"{intake_id}.png"
            if normalized_path.resolve() == source.resolve():
                raise IntakeError(IntakeErrorCode.NORMALIZATION_FAILED, "normalized output cannot overwrite source")
            normalized.save(normalized_path, format="PNG", optimize=False, compress_level=9)
        finally:
            image.close()
    except IntakeError:
        raise
    except (OSError, ValueError):
        raise IntakeError(IntakeErrorCode.NORMALIZATION_FAILED, "normalized derivative could not be written") from None

    return AssetIntakeResult(
        intake_id=intake_id,
        original_filename=source.name,
        original_size_bytes=source_size,
        detected_format=detected_format,
        mime_type=_MIME_TYPES[detected_format],
        width=width,
        height=height,
        frame_count=frame_count,
        color_mode=color_mode,
        has_alpha=has_alpha,
        original_sha256=original_sha,
        normalized_sha256=sha256_file(normalized_path),
        normalized_path=normalized_path,
        normalized_format="PNG",
        orientation_normalized=orientation not in (None, 1),
        color_normalized=color_normalized,
        gps_metadata_present=gps_present,
        exif_present=exif_present,
        icc_profile_present=icc_present,
        warnings=tuple(sorted(warnings_out)),
    )
