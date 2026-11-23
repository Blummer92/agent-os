"""Read-only independent adversarial tests for #3257/#3258.

Run with the repository's IMC `src` and `tests` directories on PYTHONPATH.
The fixtures are existing in-repo fake Google services; only pytest tmp_path
receives writes. Two cases intentionally fail on the reviewed patch.
"""
from __future__ import annotations

import json

import pytest

from instructional_materials_coach.artifact_content_qa import QA_STATE_VERIFIED
from instructional_materials_coach.placement_receipts import placement_record_path
from test_3258_terminal_content_qa import (
    KEY,
    FakeSlidesService,
    _expectations,
    _run,
    _store_receipt,
    _visual,
)


@pytest.mark.parametrize(
    "case",
    ["image-control", "shape-substitution", "wrong-slide"],
)
def test_required_slides_visual_proves_image_type_and_exact_container(tmp_path, case):
    """Matching objectId is not proof of an image in the required slide."""
    slides = FakeSlidesService()
    actual_image = case != "shape-substitution"
    actual_slide = "slide-2" if case == "wrong-slide" else "slide-1"
    deck = [
        {"objectId": "slide-1", "elements": []},
        {"objectId": "slide-2", "elements": []},
    ]
    for slide in deck:
        if slide["objectId"] == actual_slide:
            slide["elements"].append({
                "objectId": "img-1",
                "image": actual_image,
                "text": "unrelated shape",
            })
    slides.add("slides-1", deck, revision="r1")
    receipts_dir = tmp_path / "receipts"
    _store_receipt(
        receipts_dir,
        artifact_type="slides",
        artifact_id="slides-1",
        revision="r1",
        inserted="img-1",
    )
    # Ensure the receipt claims the *correct* expected target slide.
    path = placement_record_path(receipts_dir, KEY)
    ledger = json.loads(path.read_text(encoding="utf-8"))
    ledger["records"][0]["container_id"] = "slide-1"
    path.write_text(json.dumps(ledger), encoding="utf-8")

    report = _run(
        slides=slides,
        receipts_dir=receipts_dir,
        expectations=_expectations(visuals=(_visual(),)),
    )
    if case == "image-control":
        assert report.state == QA_STATE_VERIFIED
    else:
        assert report.state != QA_STATE_VERIFIED, (
            f"FALSE POSITIVE ({case}): expected image on slide-1 absent "
            f"but terminal QA verified; report={report.to_dict()}"
        )
