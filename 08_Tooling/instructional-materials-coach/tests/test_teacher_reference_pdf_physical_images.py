"""Physical verification of the one local image-embedding artifact pipeline.

``test_teacher_reference_pdf.py`` asserts only that the output starts with ``%PDF-`` and is
larger than 1 KB, which cannot tell a page with three images from a page with none. These
cases generate a real PDF from three distinct governed images, then inspect the file itself:
embedded image objects (``pdfimages``) and the rendered page (``pdftoppm``). A successful
renderer call is not proof of a successful artifact; this checks the artifact.

Scope: the teacher-reference PDF only. Student Google Docs/Slides output exists solely through
Google APIs, so its physical rendering remains a live acceptance condition (not mocked here).
"""
from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from instructional_materials_coach.teacher_reference import build_worked_examples_reference
from instructional_materials_coach.teacher_reference_pdf import render_teacher_reference_pdf

# Two groups. The structural tests below (raw PDF image-object count) need no external tool and
# always run, so "images are embedded" is checked wherever the suite runs. The render tests need
# Poppler and are skipped, with this explicit reason, where it is absent. A skipped render test is
# NOT evidence: label PDF render results as verified only where the skip did not occur.
needs_poppler = pytest.mark.skipif(
    shutil.which("pdfimages") is None or shutil.which("pdftoppm") is None,
    reason="poppler-utils (pdfimages, pdftoppm) not installed; rendered-page inspection unavailable",
)

COLORS = {"asset-red": (230, 20, 20), "asset-green": (20, 200, 20), "asset-blue": (20, 20, 230)}


def _png(color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (60, 60), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _assignment(role_id: str, asset_id: str):
    return {
        "role_id": role_id,
        "role_type": "worked-example",
        "selected_candidate": {
            "asset_reference": {"asset_id": asset_id, "stable_ref": f"stable-{asset_id}", "content_fingerprint": "c" * 64},
            "manifest_reference": {
                "external_file_id": f"drive-{asset_id}", "manifest_id": f"manifest-{asset_id}",
                "record_revision": 1, "fingerprint": "d" * 64, "verified_at": "2026-08-28T12:00:00Z",
            },
        },
        "compatibility_evidence": {
            "approved_use": {"state": "approved", "material_types": ["teacher-reference"], "role_types": ["worked-example"]}
        },
    }


def _reference():
    rows = [
        {
            "day_lesson": f"Day {index + 1}", "skill_learning_purpose": f"Skill {index}.",
            "example_role": "comparison", "teacher_modeling_purpose": f"Model {index}.",
            "artifact_location": "teacher reference", "visual_role_id": f"role-{index}",
            "expected_visual_description": f"Visual {index}.",
        }
        for index in range(3)
    ]
    assignments = [_assignment(f"role-{index}", asset) for index, asset in enumerate(COLORS)]
    return build_worked_examples_reference(
        unit_title="Three visual lesson", modeling_rows=rows, governed_visual_assignments=assignments,
    )


def _image_objects(pdf: Path) -> int:
    """Image XObjects in the raw PDF bytes; no external tool (always-running structural oracle)."""
    return pdf.read_bytes().count(b"/Subtype /Image")


def _embedded_images(pdf: Path) -> int:
    listing = subprocess.run(["pdfimages", "-list", str(pdf)], capture_output=True, text=True, check=True).stdout
    return len([line for line in listing.splitlines()[2:] if line.strip()])


def _visible_colors(pdf: Path, tmp_path: Path) -> set[str]:
    prefix = tmp_path / "page"
    subprocess.run(["pdftoppm", "-r", "60", "-png", str(pdf), str(prefix)], check=True, capture_output=True)
    seen: set[str] = set()
    for png in sorted(tmp_path.glob("page*.png")):
        with Image.open(png) as page:
            pixels = page.convert("RGB").getdata()
            for name, (r, g, b) in COLORS.items():
                hits = sum(1 for p in pixels if abs(p[0] - r) < 25 and abs(p[1] - g) < 25 and abs(p[2] - b) < 25)
                if hits > 150:  # a visible block, not anti-aliasing noise
                    seen.add(name)
    return seen


def _render(tmp_path: Path, assets: dict[str, bytes]) -> Path:
    return render_teacher_reference_pdf(_reference(), tmp_path / "three.pdf", asset_content=assets)


@needs_poppler
def test_three_governed_images_are_physically_embedded_and_visible(tmp_path):
    pdf = _render(tmp_path, {f"drive-{asset}": _png(color) for asset, color in COLORS.items()})
    assert _embedded_images(pdf) == 3
    assert _visible_colors(pdf, tmp_path) == set(COLORS)


@needs_poppler
def test_a_missing_asset_changes_the_physical_artifact_not_just_the_receipt(tmp_path):
    """Negative control: with one asset's bytes absent the file really holds two images."""
    available = {f"drive-{asset}": _png(color) for asset, color in COLORS.items() if asset != "asset-green"}
    pdf = _render(tmp_path, available)
    assert pdf.read_bytes().startswith(b"%PDF-")  # the old oracle still passes...
    assert _embedded_images(pdf) == 2  # ...while the artifact is incomplete
    assert _visible_colors(pdf, tmp_path) == {"asset-red", "asset-blue"}


@needs_poppler
def test_a_wrong_image_for_one_role_is_visible_as_the_wrong_colour(tmp_path):
    """The red role is given green bytes: the page shows green twice and no red at all.

    Also kills a renderer that uses one asset's bytes for every preview (all three would be
    green, so blue would vanish) -- which the missing-asset case alone cannot tell apart.
    """
    wrong = {
        "drive-asset-red": _png(COLORS["asset-green"]),
        "drive-asset-green": _png(COLORS["asset-green"]),
        "drive-asset-blue": _png(COLORS["asset-blue"]),
    }
    pdf = _render(tmp_path, wrong)
    assert _embedded_images(pdf) == 3
    assert _visible_colors(pdf, tmp_path) == {"asset-green", "asset-blue"}


def test_structural_three_governed_images_are_image_objects_in_the_file(tmp_path):
    pdf = _render(tmp_path, {f"drive-{asset}": _png(color) for asset, color in COLORS.items()})
    assert _image_objects(pdf) == 3


def test_structural_a_withheld_asset_leaves_two_image_objects_while_the_header_oracle_passes(tmp_path):
    available = {f"drive-{asset}": _png(color) for asset, color in COLORS.items() if asset != "asset-green"}
    pdf = _render(tmp_path, available)
    assert pdf.read_bytes().startswith(b"%PDF-")  # what the pre-existing test checked
    assert _image_objects(pdf) == 2


def test_structural_a_renderer_that_reuses_one_assets_bytes_does_not_yield_three_distinct_images(tmp_path):
    # Identical bytes collapse to one XObject, so reuse of a single asset cannot look like three.
    one = _png(COLORS["asset-red"])
    pdf = _render(tmp_path, {f"drive-{asset}": one for asset in COLORS})
    assert _image_objects(pdf) == 1
