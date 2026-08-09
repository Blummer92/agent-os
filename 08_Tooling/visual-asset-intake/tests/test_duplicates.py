from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PIL import Image

from visual_asset_intake import (
    DuplicateCandidate,
    DuplicateDisposition,
    intake_visual_asset,
    reconcile_duplicate,
)


def _intake(tmp_path: Path, *, name: str = "source.png", size=(12, 8), color=(10, 20, 30)):
    source = tmp_path / name
    image = Image.new("RGB", size, color)
    image.save(source, format="PNG")
    image.close()
    return intake_visual_asset(source, output_dir=tmp_path / f"out-{name}")


def _intake_path(tmp_path: Path, source: Path):
    return intake_visual_asset(source, output_dir=tmp_path / f"out-{source.name}")


def test_exact_original_match_is_deterministic_and_filename_independent(tmp_path: Path):
    intake = _intake(tmp_path)
    candidate = DuplicateCandidate("asset-a", original_sha256=intake.original_sha256)
    first = reconcile_duplicate(intake, [candidate])
    second = reconcile_duplicate(intake, [candidate])
    assert first == second
    assert first.disposition is DuplicateDisposition.EXACT_EXISTING
    assert first.matched_identity == "asset-a"
    renamed = replace(intake, original_filename="renamed.png")
    assert reconcile_duplicate(renamed, [candidate]) == first


def test_original_match_precedes_normalized_match():
    intake = _fake_intake("a" * 64, "b" * 64)
    result = reconcile_duplicate(
        intake,
        [
            DuplicateCandidate("asset-normalized", normalized_sha256="b" * 64),
            DuplicateCandidate("asset-original", original_sha256="a" * 64),
        ],
    )
    assert result.disposition is DuplicateDisposition.EXACT_EXISTING
    assert result.matched_identity == "asset-original"


def test_normalized_match_reconciles_metadata_variant():
    intake = _fake_intake("a" * 64, "b" * 64)
    candidate = DuplicateCandidate("asset-a", original_sha256="c" * 64, normalized_sha256="b" * 64)
    result = reconcile_duplicate(intake, [candidate])
    assert result.disposition is DuplicateDisposition.NORMALIZED_EXISTING
    assert result.matched_identity == "asset-a"


def test_candidate_order_does_not_change_result():
    intake = _fake_intake("a" * 64, "b" * 64)
    one = DuplicateCandidate("asset-a", original_sha256="a" * 64)
    two = DuplicateCandidate("asset-a", original_sha256="a" * 64)
    assert reconcile_duplicate(intake, [one, two]) == reconcile_duplicate(intake, [two, one])


def test_conflicting_exact_identities_require_manual_review():
    intake = _fake_intake("a" * 64, "b" * 64)
    result = reconcile_duplicate(
        intake,
        [
            DuplicateCandidate("asset-a", original_sha256="a" * 64),
            DuplicateCandidate("asset-b", original_sha256="a" * 64),
        ],
    )
    assert result.disposition is DuplicateDisposition.MANUAL_REVIEW_REQUIRED
    assert result.matched_identity is None


def test_conflicting_normalized_identities_require_manual_review():
    intake = _fake_intake("a" * 64, "b" * 64)
    result = reconcile_duplicate(
        intake,
        [
            DuplicateCandidate("asset-a", normalized_sha256="b" * 64),
            DuplicateCandidate("asset-b", normalized_sha256="b" * 64),
        ],
    )
    assert result.disposition is DuplicateDisposition.MANUAL_REVIEW_REQUIRED


def test_variants_derive_from_base_and_remain_conservative(tmp_path: Path):
    base_path = tmp_path / "base.png"
    base_image = Image.new("RGB", (24, 16), (40, 50, 60))
    base_image.putpixel((0, 0), (200, 10, 10))
    base_image.save(base_path, format="PNG")
    base_image.close()
    intake = _intake_path(tmp_path, base_path)

    with Image.open(base_path) as image:
        lossless_path = tmp_path / "lossless.bmp"
        image.save(lossless_path, format="BMP")
        resized_path = tmp_path / "resized.png"
        image.resize((12, 8)).save(resized_path, format="PNG")
        cropped_path = tmp_path / "cropped.png"
        image.crop((0, 0, 12, 16)).save(cropped_path, format="PNG")
        lossy_path = tmp_path / "recompressed.jpg"
        image.save(lossy_path, format="JPEG", quality=65)
        similar_path = tmp_path / "similar.png"
        similar = image.copy()
        similar.putpixel((1, 1), (40, 51, 60))
        similar.save(similar_path, format="PNG")
        similar.close()

    # BMP is intentionally unsupported by intake, so use a PNG re-encode with changed metadata bytes.
    with Image.open(base_path) as image:
        lossless_path = tmp_path / "lossless.png"
        image.save(lossless_path, format="PNG", compress_level=1)

    lossless = _intake_path(tmp_path, lossless_path)
    lossless_result = reconcile_duplicate(
        intake,
        [DuplicateCandidate("asset-lossless", lossless.original_sha256, lossless.normalized_sha256)],
    )
    assert lossless_result.disposition is DuplicateDisposition.NORMALIZED_EXISTING

    for index, path in enumerate((resized_path, cropped_path, lossy_path, similar_path)):
        variant = _intake_path(tmp_path, path)
        result = reconcile_duplicate(
            intake,
            [DuplicateCandidate(f"asset-{index}", variant.original_sha256, variant.normalized_sha256)],
        )
        assert result.disposition is DuplicateDisposition.NO_DUPLICATE_FOUND


def test_unrelated_image_has_no_duplicate(tmp_path: Path):
    intake = _intake(tmp_path, name="one.png", color=(1, 2, 3))
    other = _intake(tmp_path, name="two.png", color=(200, 100, 50))
    result = reconcile_duplicate(
        intake,
        [DuplicateCandidate("asset-b", other.original_sha256, other.normalized_sha256)],
    )
    assert result.disposition is DuplicateDisposition.NO_DUPLICATE_FOUND


def test_empty_candidates_have_no_duplicate():
    result = reconcile_duplicate(_fake_intake("a" * 64, "b" * 64), [])
    assert result.disposition is DuplicateDisposition.NO_DUPLICATE_FOUND


def test_invalid_candidate_identity_is_bounded():
    intake = _fake_intake("a" * 64, "b" * 64)
    malformed = DuplicateCandidate(None, original_sha256="a" * 64)  # type: ignore[arg-type]
    result = reconcile_duplicate(intake, [DuplicateCandidate("asset-a"), malformed])
    assert result.disposition is DuplicateDisposition.INVALID
    assert result.matched_identity is None


def test_invalid_candidate_hash_is_bounded():
    intake = _fake_intake("a" * 64, "b" * 64)
    for malformed_hash in ("not-a-sha", "A" * 64, 123):
        candidate = DuplicateCandidate("asset-a", original_sha256=malformed_hash)  # type: ignore[arg-type]
        assert reconcile_duplicate(intake, [candidate]).disposition is DuplicateDisposition.INVALID


def test_non_candidate_input_is_bounded():
    intake = _fake_intake("a" * 64, "b" * 64)
    assert reconcile_duplicate(intake, [object()]).disposition is DuplicateDisposition.INVALID  # type: ignore[list-item]
    assert reconcile_duplicate(intake, None).disposition is DuplicateDisposition.INVALID  # type: ignore[arg-type]


def test_result_carries_no_authority():
    intake = _fake_intake("a" * 64, "b" * 64)
    result = reconcile_duplicate(intake, [])
    assert not result.execution_authorized
    assert not result.external_write_authorized
    assert not result.approval_authorized
    assert not result.classroom_readiness_authorized
    assert not result.production_authorized
    assert not hasattr(result, "asset_id")


def _fake_intake(original_sha: str, normalized_sha: str):
    from visual_asset_intake import AssetIntakeResult

    return AssetIntakeResult(
        intake_id="intake-test",
        original_filename="test.png",
        original_size_bytes=1,
        detected_format="PNG",
        mime_type="image/png",
        width=1,
        height=1,
        frame_count=1,
        color_mode="RGB",
        has_alpha=False,
        original_sha256=original_sha,
        normalized_sha256=normalized_sha,
        normalized_path=Path("normalized.png"),
        normalized_format="PNG",
        orientation_normalized=False,
        color_normalized=False,
        gps_metadata_present=False,
        exif_present=False,
        icc_profile_present=False,
        warnings=(),
    )
