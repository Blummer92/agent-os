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


def test_extensionless_raster_uses_decoded_format(tmp_path: Path):
    source = tmp_path / "raster"
    _save(source, "PNG")

    result = intake_visual_asset(source, output_dir=tmp_path / "out")

    assert result.detected_format == "PNG"
    assert result.warnings == ()
    assert result.normalized_path.is_file()


def test_multiframe_png_is_rejected_before_output(tmp_path: Path):
    source = tmp_path / "animated.png"
    with Image.new("RGB", (4, 4), "white") as first, Image.new("RGB", (4, 4), "black") as second:
        first.save(source, format="PNG", save_all=True, append_images=[second])
    output = tmp_path / "out"

    with pytest.raises(IntakeError) as exc:
        intake_visual_asset(source, output_dir=output)

    assert exc.value.code is IntakeErrorCode.UNSUPPORTED_MULTIFRAME_IMAGE
    assert not output.exists()


@pytest.mark.parametrize("limit", ["max_source_bytes", "max_decoded_pixels"])
def test_policy_requires_positive_limits(limit: str):
    with pytest.raises(ValueError, match="intake limits must be positive"):
        IntakePolicy(**{limit: 0})


def test_failed_derivative_write_cleans_up_partial_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.png"
    _save(source, "PNG")
    original = source.read_bytes()
    output = tmp_path / "out"

    def fail_save(self, stream, *args, **kwargs):
        stream.write(b"partial")
        raise OSError("synthetic derivative write failure")

    monkeypatch.setattr(Image.Image, "save", fail_save)
    with pytest.raises(IntakeError) as exc:
        intake_visual_asset(source, output_dir=output)

    assert exc.value.code is IntakeErrorCode.NORMALIZATION_FAILED
    assert output.is_dir()
    assert list(output.iterdir()) == []
    assert source.read_bytes() == original


def test_decoder_pixel_warning_is_classified_as_pixel_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "image.png"
    _save(source, "PNG", size=(12, 8))
    output = tmp_path / "out"
    # 96 pixels is above the warning threshold, but below Pillow's error threshold.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 80)

    with pytest.raises(IntakeError, match="decoder safety limits") as exc:
        intake_visual_asset(source, output_dir=output)

    assert exc.value.code is IntakeErrorCode.PIXEL_LIMIT_EXCEEDED
    assert not output.exists()


def test_source_read_error_is_invalid_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "image.png"
    _save(source, "PNG")
    output = tmp_path / "out"
    real_open = Path.open

    def fail_source_open(path, *args, **kwargs):
        if path == source:
            raise PermissionError("synthetic source read failure")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_source_open)
    with pytest.raises(IntakeError, match="readable file") as exc:
        intake_visual_asset(source, output_dir=output)

    assert exc.value.code is IntakeErrorCode.INVALID_PATH
    assert not output.exists()


def test_non_file_source_is_rejected_before_read(tmp_path: Path):
    source = tmp_path / "directory.png"
    source.mkdir()
    output = tmp_path / "out"

    with pytest.raises(IntakeError, match="existing file") as exc:
        intake_visual_asset(source, output_dir=output)

    assert exc.value.code is IntakeErrorCode.INVALID_PATH
    assert not output.exists()


def test_palette_transparency_survives_normalization(tmp_path: Path):
    source = tmp_path / "palette.png"
    with Image.new("P", (2, 1)) as palette:
        palette.putpalette([0, 0, 0, 255, 0, 0])
        palette.putdata([0, 1])
        palette.save(source, format="PNG", transparency=0)

    result = intake_visual_asset(source, output_dir=tmp_path / "out")

    assert result.has_alpha
    with Image.open(result.normalized_path) as derivative:
        assert derivative.mode == "RGBA"
        assert derivative.getpixel((0, 0)) == (0, 0, 0, 0)
        assert derivative.getpixel((1, 0)) == (255, 0, 0, 255)


def test_source_cannot_be_its_own_derivative(tmp_path: Path):
    source = tmp_path / "image.png"
    _save(source, "PNG")
    original = source.read_bytes()
    source = source.rename(tmp_path / f"intake-{hashlib.sha256(original).hexdigest()[:24]}.png")

    with pytest.raises(IntakeError, match="cannot overwrite source") as exc:
        intake_visual_asset(source, output_dir=tmp_path)

    assert exc.value.code is IntakeErrorCode.NORMALIZATION_FAILED
    assert source.read_bytes() == original
    assert list(tmp_path.iterdir()) == [source]


def test_nonregular_reservation_is_closed_and_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import errno
    import os
    from types import SimpleNamespace

    from visual_asset_intake import intake

    source = tmp_path / "image.png"
    _save(source, "PNG")
    output = tmp_path / "out"
    opened = []
    real_os = intake.os

    class Recorder:
        def __getattr__(self, name):
            return getattr(real_os, name)

        def open(self, *args):
            descriptor = real_os.open(*args)
            opened.append(descriptor)
            return descriptor

    # Exercise the rejection path without creating a special file on the host.
    monkeypatch.setattr(intake, "os", Recorder())
    monkeypatch.setattr(intake, "stat", SimpleNamespace(S_ISREG=lambda mode: False))
    with pytest.raises(IntakeError, match="not a regular file") as exc:
        intake_visual_asset(source, output_dir=output)

    assert exc.value.code is IntakeErrorCode.NORMALIZATION_FAILED
    assert list(output.iterdir()) == []
    assert len(opened) == 1
    with pytest.raises(OSError) as closed:
        os.fstat(opened[0])
    assert closed.value.errno == errno.EBADF
