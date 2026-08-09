from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PIL import Image

from visual_asset_intake import IntakeError, IntakeErrorCode, IntakePolicy, intake_visual_asset


def _save(path: Path, fmt: str, *, mode: str = "RGB", size=(12, 8), exif=None, icc_profile=None):
    colors = {"RGB": (10, 20, 30), "RGBA": (10, 20, 30, 128), "CMYK": (10, 20, 30, 40)}
    image = Image.new(mode, size, colors[mode])
    kwargs = {}
    if exif is not None:
        kwargs["exif"] = exif
    if icc_profile is not None:
        kwargs["icc_profile"] = icc_profile
    image.save(path, format=fmt, **kwargs)
    image.close()


@pytest.mark.parametrize(("fmt", "suffix"), [("JPEG", ".jpg"), ("PNG", ".png"), ("WEBP", ".webp")])
def test_supported_formats_are_normalized(tmp_path: Path, fmt: str, suffix: str):
    source = tmp_path / f"source{suffix}"
    _save(source, fmt)
    before = source.read_bytes()
    result = intake_visual_asset(source, output_dir=tmp_path / "out")
    assert result.detected_format == fmt
    assert result.frame_count == 1
    assert result.normalized_path.name.startswith("intake-")
    assert result.normalized_path.suffix == ".png"
    assert source.read_bytes() == before
    assert not result.external_write_authorized
    assert not result.approval_authorized
    assert not result.classroom_readiness_authorized
    assert not result.production_authorized
    assert not hasattr(result, "asset_id")


def test_exact_hash_uses_bytes_not_filename(tmp_path: Path):
    first = tmp_path / "one.png"
    second = tmp_path / "unicodé copy.png"
    _save(first, "PNG")
    second.write_bytes(first.read_bytes())
    a = intake_visual_asset(first, output_dir=tmp_path / "a")
    b = intake_visual_asset(second, output_dir=tmp_path / "b")
    expected = hashlib.sha256(first.read_bytes()).hexdigest()
    assert a.original_sha256 == b.original_sha256 == expected
    assert a.intake_id == b.intake_id
    assert a.normalized_sha256 == b.normalized_sha256
    changed = bytearray(first.read_bytes())
    changed[-1] ^= 1
    second.write_bytes(changed)
    changed_result = intake_visual_asset(second, output_dir=tmp_path / "changed")
    assert hashlib.sha256(second.read_bytes()).hexdigest() != expected
    assert changed_result.original_sha256 != a.original_sha256
    assert changed_result.intake_id != a.intake_id


def test_extension_content_mismatch_is_observed(tmp_path: Path):
    source = tmp_path / "looks-like-jpeg.jpg"
    _save(source, "PNG")
    result = intake_visual_asset(source, output_dir=tmp_path / "out")
    assert result.detected_format == "PNG"
    assert result.warnings == ("extension-content-mismatch",)


def test_corrupt_and_unsupported_fail_closed(tmp_path: Path):
    corrupt = tmp_path / "bad.jpg"
    corrupt.write_bytes(b"not an image")
    with pytest.raises(IntakeError) as exc:
        intake_visual_asset(corrupt, output_dir=tmp_path / "out")
    assert exc.value.code is IntakeErrorCode.CORRUPT_IMAGE

    svg = tmp_path / "bad.svg"
    svg.write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>")
    with pytest.raises(IntakeError):
        intake_visual_asset(svg, output_dir=tmp_path / "out")


def test_source_byte_and_pixel_limits(tmp_path: Path):
    source = tmp_path / "small.png"
    _save(source, "PNG", size=(20, 20))
    with pytest.raises(IntakeError) as exc:
        intake_visual_asset(source, output_dir=tmp_path / "out", policy=IntakePolicy(max_source_bytes=1))
    assert exc.value.code is IntakeErrorCode.INPUT_TOO_LARGE
    with pytest.raises(IntakeError) as exc:
        intake_visual_asset(source, output_dir=tmp_path / "out", policy=IntakePolicy(max_decoded_pixels=399))
    assert exc.value.code is IntakeErrorCode.PIXEL_LIMIT_EXCEEDED


def test_policy_rejects_unsupported_formats():
    with pytest.raises(ValueError):
        IntakePolicy(allowed_formats=("BMP",))


def test_multiframe_gif_rejected(tmp_path: Path):
    source = tmp_path / "animated.gif"
    one = Image.new("RGB", (4, 4), "white")
    two = Image.new("RGB", (4, 4), "black")
    one.save(source, save_all=True, append_images=[two], format="GIF")
    one.close()
    two.close()
    with pytest.raises(IntakeError) as exc:
        intake_visual_asset(source, output_dir=tmp_path / "out")
    assert exc.value.code is IntakeErrorCode.UNSUPPORTED_FORMAT


def test_exif_orientation_is_baked_and_removed(tmp_path: Path):
    source = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[274] = 6
    _save(source, "JPEG", size=(12, 8), exif=exif)
    result = intake_visual_asset(source, output_dir=tmp_path / "out")
    assert result.orientation_normalized
    with Image.open(result.normalized_path) as normalized:
        assert normalized.size == (8, 12)
        assert not normalized.getexif()


def test_gps_presence_is_flagged_but_not_copied(tmp_path: Path):
    source = tmp_path / "gps.jpg"
    exif = Image.Exif()
    exif[34853] = {1: "N", 2: (1, 2, 3)}
    _save(source, "JPEG", exif=exif)
    result = intake_visual_asset(source, output_dir=tmp_path / "out")
    assert result.gps_metadata_present
    with Image.open(result.normalized_path) as normalized:
        assert not normalized.getexif()


def test_cmyk_and_transparency_normalization(tmp_path: Path):
    cmyk = tmp_path / "cmyk.jpg"
    _save(cmyk, "JPEG", mode="CMYK")
    cmyk_result = intake_visual_asset(cmyk, output_dir=tmp_path / "cmyk-out")
    with Image.open(cmyk_result.normalized_path) as normalized:
        assert normalized.mode == "RGB"

    alpha = tmp_path / "alpha.png"
    _save(alpha, "PNG", mode="RGBA")
    alpha_result = intake_visual_asset(alpha, output_dir=tmp_path / "alpha-out")
    assert alpha_result.has_alpha
    with Image.open(alpha_result.normalized_path) as normalized:
        assert normalized.mode == "RGBA"


def test_existing_derivative_and_symlink_are_rejected(tmp_path: Path):
    source = tmp_path / "source.png"
    _save(source, "PNG")
    original_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    intake_id = f"intake-{original_sha[:24]}"

    regular_out = tmp_path / "regular"
    regular_out.mkdir()
    existing = regular_out / f"{intake_id}.png"
    existing.write_bytes(b"keep-me")
    with pytest.raises(IntakeError) as exc:
        intake_visual_asset(source, output_dir=regular_out)
    assert exc.value.code is IntakeErrorCode.NORMALIZATION_FAILED
    assert existing.read_bytes() == b"keep-me"

    if hasattr(Path, "symlink_to"):
        symlink_out = tmp_path / "symlink"
        symlink_out.mkdir()
        target = tmp_path / "target.txt"
        target.write_bytes(b"keep-target")
        link = symlink_out / f"{intake_id}.png"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            return
        with pytest.raises(IntakeError) as exc:
            intake_visual_asset(source, output_dir=symlink_out)
        assert exc.value.code is IntakeErrorCode.NORMALIZATION_FAILED
        assert target.read_bytes() == b"keep-target"


def test_icc_presence_and_generated_output_name(tmp_path: Path):
    source = tmp_path / "teacher file.png"
    _save(source, "PNG", icc_profile=b"synthetic-profile")
    result = intake_visual_asset(source, output_dir=tmp_path / "safe")
    assert result.icc_profile_present
    assert result.normalized_path.parent == tmp_path / "safe"
    assert "teacher file" not in result.normalized_path.name
