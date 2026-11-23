"""#3509: Notion-first A/B slide generation must not substitute invented lessons.

Regression coverage for the 2026-10-09 and 2026-10-20 incidents: the host
searched historical Drive decks first, then invented a synthetic lesson, and
treated a disabled native Notion plugin as proof that no governed Notion
route existed. The repository repair is the offline A/B slides preview in
``slides_ab_preview``: it consumes only the existing governed #3580
lesson-content route (the pinned historical run-38462963519 result, used
here strictly as a read-only fixture -- never as live production
authorization), preserves the exact Candy Branding Day 3 lesson identity
through both variants, fails closed on synthetic or mismatched content, and
refuses evaluation until both source-matched variants exist.

Authored slide text here is fixture text only, used to prove preservation
and variant separation; all lesson facts come from the governed result.
"""
from __future__ import annotations

import contextlib
import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from instructional_materials_coach import cli
from instructional_materials_coach.content_spec import content_from_dict
from instructional_materials_coach.lesson_content_result import LessonContentSelection
from instructional_materials_coach.slides_ab_preview import (
    PREVIEW_CONTRACT,
    evaluate_slides_ab_preview,
    preview_lesson_slides,
    preview_lesson_slides_ab,
)
from instructional_materials_coach.worksheet_preview import preview_lesson_worksheet

FIXTURE = Path(__file__).parent / "fixtures" / "lesson_content_run_38462963519.json"
UNIT_PAGE_ID = "3907ac78-3131-8132-8f84-f9fd633acba5"
DAY3_TARGET = "I can use font pairing and hierarchy so my candy text is clear and intentional."
DAY3_FOCUS = "Choose font pairing and hierarchy so candy name, flavor, and tagline have clear importance."
DAY1_TARGET = "I can choose colors on purpose and explain how they match the candy mood and audience."
SELECTION_DAY3 = LessonContentSelection(
    request_id="candy-branding-lesson-content",
    canonical_unit_page_id=UNIT_PAGE_ID,
    day_lesson_number="Day 3",
    generated_at="38462963519:1",
)
AUTHORED_A = {
    "title": "Fixture A title",
    "objectives": [],
    "lesson_identity": {"day_lesson_number": "Day 3"},
    "slides": [
        {"index": 1, "heading": "A opening heading", "bullets": ["A bullet one"]},
        {"index": 2, "heading": "A second heading", "bullets": ["A bullet two"]},
    ],
    "worksheet_questions": ["Fixture question one?", "Fixture question two?"],
}
AUTHORED_B = {
    "title": "Fixture B title",
    "objectives": [],
    "lesson_identity": {"day_lesson_number": "Day 3"},
    "slides": [
        {"index": 1, "heading": "B opening heading", "bullets": ["B bullet one"]},
        {"index": 2, "heading": "B second heading", "bullets": ["B bullet two"]},
    ],
    "worksheet_questions": ["Fixture question one?", "Fixture question two?"],
}
CLIENT_BOUNDARY = (
    "get_credentials",
    "build_drive_service",
    "build_slides_service",
    "build_docs_service",
    "build_live_materials",
    "build_placement_transport",
    "get_file_metadata",
    "record_lesson",
)


def _evidence() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _content(authored: dict):
    return content_from_dict(copy.deepcopy(authored))


def _ab(authored_a=AUTHORED_A, authored_b=AUTHORED_B, evidence=None, selection=SELECTION_DAY3):
    return preview_lesson_slides_ab(
        _content(authored_a), _content(authored_b),
        _evidence() if evidence is None else evidence, selection,
    )


# 1. Teacher requests slides from existing Notion lessons: both A/B variants
#    preview from the governed Day 3 lesson, with exact identity preserved.
def test_ab_preview_from_governed_notion_lesson_day3():
    receipt = _ab()
    assert receipt["contract_version"] == PREVIEW_CONTRACT
    assert receipt["status"] == "preview"
    assert receipt["lesson"]["day_lesson_number"] == "Day 3"
    assert receipt["lesson"]["canonical_unit_page_id"] == UNIT_PAGE_ID
    assert receipt["lesson"]["request_id"] == "candy-branding-lesson-content"
    assert receipt["lesson"]["generated_at"] == "38462963519:1"
    for variant in receipt["variants"].values():
        assert variant["slides"]["learning_target"] == DAY3_TARGET
        assert variant["slides"]["daily_focus"] == DAY3_FOCUS
        assert variant["slides"]["slide_indexes"] == [1, 2]
        assert variant["rendered"] is False
        assert variant["native_artifact"] is None
    assert receipt["evaluation"]["ready"] is True
    assert receipt["evaluation"]["performed"] is False
    assert receipt["evaluation"]["winner"] is None


# 2. Native Notion plugin unavailable, governed route exists: the preview is
#    enforceably offline -- no credential/client/live-build seam is touched
#    when the CLI runs it from the governed result alone.
@contextlib.contextmanager
def _no_client_boundary():
    with contextlib.ExitStack() as stack:
        for name in CLIENT_BOUNDARY:
            stack.enter_context(
                patch(f"instructional_materials_coach.cli.{name}", side_effect=AssertionError(f"{name} reached"))
            )
        yield


def _cli_args(tmp_path: Path, *, authored_a=None, authored_b=None, evidence=None, lesson="Day 3") -> list[str]:
    path_a = tmp_path / "a.yaml"
    path_a.write_text(yaml.safe_dump(authored_a or AUTHORED_A), encoding="utf-8")
    path_b = tmp_path / "b.yaml"
    path_b.write_text(yaml.safe_dump(authored_b or AUTHORED_B), encoding="utf-8")
    result = tmp_path / "result.json"
    result.write_text(json.dumps(_evidence() if evidence is None else evidence), encoding="utf-8")
    out = tmp_path / "preview.json"
    return [
        "preview-slides-ab",
        "--content-a", str(path_a),
        "--content-b", str(path_b),
        "--lesson-content-result", str(result),
        "--request-id", "candy-branding-lesson-content",
        "--canonical-unit-page-id", UNIT_PAGE_ID,
        "--lesson", lesson,
        "--generated-at", "38462963519:1",
        "--preview-out", str(out),
    ], out


def test_cli_preview_slides_ab_runs_offline_without_any_client(tmp_path):
    args, out = _cli_args(tmp_path)
    with _no_client_boundary():
        assert cli.main(args) == 0
    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert receipt["status"] == "preview"
    assert receipt["side_effects"]["drive_writes_performed"] is False
    assert receipt["side_effects"]["notion_writes_performed"] is False
    assert receipt["side_effects"]["credentials_initialized"] is False


# 3. Historical GitHub evidence is not current production authorization: the
#    fixture previews as a read-only offline prototype and never upgrades.
def test_historical_fixture_is_not_production_authorization():
    receipt = _ab()
    assert receipt["authority"]["production_authorized"] is False
    assert receipt["classroom_ready"] is False
    assert receipt["live_notion_read_claimed"] is False
    assert receipt["native_artifact"] is None


def test_widened_authority_evidence_fails_closed():
    evidence = _evidence()
    evidence["result"]["authority"]["production_authorized"] = True
    receipt = _ab(evidence=evidence)
    assert receipt["status"] == "blocked"
    assert receipt["reason_code"] == "authority-not-fail-closed"
    assert receipt["variants"]["A"]["slides"] is None
    assert receipt["evaluation"]["ready"] is False


# 4. Teacher corrects an invented lesson: synthetic authored objectives that
#    carry an invented target (the "Visual Hierarchy" substitution) or another
#    lesson's real target are refused, in either variant.
@pytest.mark.parametrize("invented", [
    "I can use visual hierarchy so my poster looks professional.",
    DAY1_TARGET,
])
def test_invented_or_foreign_lesson_objectives_blocked(invented):
    authored = {**AUTHORED_A, "objectives": [invented]}
    receipt = _ab(authored_a=authored)
    assert receipt["status"] == "blocked"
    assert receipt["reason_code"] == "objective-conflict"
    assert receipt["evaluation"]["ready"] is False


def test_teacher_correction_to_a_different_day_requires_new_binding():
    # After correction, the bound selection is Day 3; authored material bound
    # to Day 1 identity cannot silently stand in for it.
    authored = {**AUTHORED_A, "lesson_identity": {"day_lesson_number": "Day 1"}}
    receipt = _ab(authored_a=authored)
    assert receipt["status"] == "blocked"
    assert receipt["reason_code"] == "authored-identity-missing"


# 5. Both A/B variants preserve identical lesson content while differing as
#    authored variants.
def test_both_variants_preserve_identical_lesson_content():
    receipt = _ab()
    a, b = receipt["variants"]["A"], receipt["variants"]["B"]
    assert a["lesson"] == b["lesson"]
    assert a["slides"]["learning_target"] == b["slides"]["learning_target"] == DAY3_TARGET
    assert a["slides"]["daily_focus"] == b["slides"]["daily_focus"] == DAY3_FOCUS
    assert a["slides"]["objectives"] == b["slides"]["objectives"]
    assert a["slides"]["planned_content_sha256"] != b["slides"]["planned_content_sha256"]
    assert receipt["checks"]["same_lesson_identity"] is True
    assert receipt["checks"]["same_lesson_content"] is True


def test_identical_variants_are_not_an_ab_test():
    receipt = _ab(authored_b=AUTHORED_A)
    assert receipt["status"] == "blocked"
    assert receipt["evaluation"]["ready"] is False


# 6. Missing source or missing exact binding fails closed.
@pytest.mark.parametrize("evidence,selection,reason", [
    (None, SELECTION_DAY3, "result-malformed"),
    ({}, SELECTION_DAY3, "result-malformed"),
])
def test_missing_source_evidence_fails_closed(evidence, selection, reason):
    receipt = preview_lesson_slides_ab(_content(AUTHORED_A), _content(AUTHORED_B), evidence, selection)
    assert receipt["status"] == "blocked"
    assert receipt["reason_code"] == reason
    assert receipt["lesson"] is None


def test_wrong_day_selection_fails_closed():
    selection = LessonContentSelection(
        request_id="candy-branding-lesson-content",
        canonical_unit_page_id=UNIT_PAGE_ID,
        day_lesson_number="Day 9",
        generated_at="38462963519:1",
    )
    receipt = _ab(selection=selection)
    assert receipt["status"] == "blocked"
    assert receipt["reason_code"] == "lesson-not-found"


def test_missing_result_file_blocks_cli(tmp_path):
    args, out = _cli_args(tmp_path)
    args[args.index("--lesson-content-result") + 1] = str(tmp_path / "absent.json")
    assert cli.main(args) == 1
    assert not out.exists()


# 7. Both slide artifacts must exist before visual evaluation.
def test_evaluation_gate_requires_both_variants():
    complete = _ab()
    gate = evaluate_slides_ab_preview(complete, _evidence(), SELECTION_DAY3)
    assert gate["status"] == "ready-for-evaluation"
    assert gate["performed"] is False
    assert gate["winner"] is None

    one_sided = copy.deepcopy(complete)
    one_sided["variants"]["B"] = {**one_sided["variants"]["B"], "status": "blocked", "slides": None}
    one_sided["status"] = "blocked"
    assert evaluate_slides_ab_preview(one_sided, _evidence(), SELECTION_DAY3)["status"] == "blocked"
    assert evaluate_slides_ab_preview(one_sided, _evidence(), SELECTION_DAY3)["reason_code"] == "evaluation-artifacts-missing"
    assert evaluate_slides_ab_preview({"status": "preview"}, _evidence(), SELECTION_DAY3)["status"] == "blocked"
    assert evaluate_slides_ab_preview(None, _evidence(), SELECTION_DAY3)["status"] == "blocked"


def test_blocked_variant_blocks_ab_and_evaluation():
    authored_b = {
        **AUTHORED_B,
        "slides": [
            {"index": 1, "heading": "B one", "bullets": ["x"]},
            {"index": 1, "heading": "B duplicate", "bullets": ["y"]},
        ],
    }
    with pytest.raises(ValueError):
        _content(authored_b)
    # Direct construction bypassing the parser still fails closed in preview.
    import dataclasses
    content_b = dataclasses.replace(_content(AUTHORED_B), slides=authored_b["slides"])
    receipt = preview_lesson_slides_ab(_content(AUTHORED_A), content_b, _evidence(), SELECTION_DAY3)
    assert receipt["status"] == "blocked"
    assert receipt["variants"]["B"]["slides"] is None
    assert receipt["evaluation"]["ready"] is False
    assert evaluate_slides_ab_preview(receipt, _evidence(), SELECTION_DAY3)["status"] == "blocked"


# 8. Existing behavior remains intact: worksheet preview and governed slide
#    request composition still work against the same Day 3 evidence.
def test_existing_worksheet_preview_still_works_on_day3():
    receipt = preview_lesson_worksheet(_content(AUTHORED_A), _evidence(), SELECTION_DAY3)
    assert receipt["status"] == "preview"
    assert receipt["worksheet"]["learning_target"] == DAY3_TARGET


def test_single_variant_preview_blocks_duplicate_slide_indexes():
    import dataclasses
    slides = [
        {"index": 1, "heading": "one", "bullets": ["x"]},
        {"index": "1", "heading": "dup", "bullets": ["y"]},
    ]
    content = dataclasses.replace(_content(AUTHORED_A), slides=slides)
    receipt = preview_lesson_slides(content, _evidence(), SELECTION_DAY3)
    assert receipt["status"] == "blocked"
    assert receipt["slides"] is None


# F1 (independent QA): the evaluation gate must not be satisfiable by a
# hand-built or hand-edited receipt -- only by real planned artifacts whose
# recorded content hashes recompute.
def test_evaluation_gate_rejects_forged_minimal_receipt():
    forged = {
        "contract_version": PREVIEW_CONTRACT,
        "status": "preview",
        "checks": {"same_lesson_identity": True},
        "evaluation": {"ready": True, "performed": False, "winner": None},
        "rendered": False,
        "classroom_ready": False,
        "native_artifact": None,
        "authority": {"production_authorized": False},
        "side_effects": {"drive_writes_performed": False},
        "variants": {
            label: {
                "contract_version": PREVIEW_CONTRACT,
                "status": "preview",
                "rendered": False,
                "classroom_ready": False,
                "native_artifact": None,
                "authority": {"production_authorized": False},
                "side_effects": {"drive_writes_performed": False},
                "checks": {"authored_slides_preserved": True},
                "lesson": {"request_id": "x"},
                "slides": {"x": 1},
            }
            for label in ("A", "B")
        },
    }
    gate = evaluate_slides_ab_preview(forged, _evidence(), SELECTION_DAY3)
    assert gate["status"] == "blocked"
    assert gate["reason_code"] == "evaluation-artifacts-missing"


def test_evaluation_gate_rejects_hand_edited_receipts():
    genuine = _ab()
    assert evaluate_slides_ab_preview(genuine, _evidence(), SELECTION_DAY3)["status"] == "ready-for-evaluation"

    # Identical-variants receipt with only the top status hand-edited.
    identical = _ab(authored_b=AUTHORED_A)
    assert identical["status"] == "blocked"
    identical["status"] = "preview"
    identical["evaluation"]["ready"] = True
    assert evaluate_slides_ab_preview(identical, _evidence(), SELECTION_DAY3)["status"] == "blocked"

    # Variant hashes forced equal and all AB checks forced false.
    tampered = copy.deepcopy(genuine)
    sha = tampered["variants"]["A"]["slides"]["planned_content_sha256"]
    tampered["variants"]["B"]["slides"]["planned_content_sha256"] = sha
    assert evaluate_slides_ab_preview(tampered, _evidence(), SELECTION_DAY3)["status"] == "blocked"

    # AB checks falsified.
    tampered = copy.deepcopy(genuine)
    tampered["checks"]["same_lesson_identity"] = False
    assert evaluate_slides_ab_preview(tampered, _evidence(), SELECTION_DAY3)["status"] == "blocked"

    # Variant slides stripped of their planned replacements.
    tampered = copy.deepcopy(genuine)
    tampered["variants"]["A"]["slides"] = {"learning_target": DAY3_TARGET}
    assert evaluate_slides_ab_preview(tampered, _evidence(), SELECTION_DAY3)["status"] == "blocked"

    # Variant lesson content diverged while lesson identity dicts still match.
    tampered = copy.deepcopy(genuine)
    tampered["variants"]["B"]["slides"]["learning_target"] = "Invented target."
    assert evaluate_slides_ab_preview(tampered, _evidence(), SELECTION_DAY3)["status"] == "blocked"

    # Authority / completion claims flipped on.
    for field, value in (("production_authorized", True),):
        tampered = copy.deepcopy(genuine)
        tampered["authority"][field] = value
        assert evaluate_slides_ab_preview(tampered, _evidence(), SELECTION_DAY3)["status"] == "blocked"
    tampered = copy.deepcopy(genuine)
    tampered["classroom_ready"] = True
    assert evaluate_slides_ab_preview(tampered, _evidence(), SELECTION_DAY3)["status"] == "blocked"
    tampered = copy.deepcopy(genuine)
    tampered["rendered"] = True
    assert evaluate_slides_ab_preview(tampered, _evidence(), SELECTION_DAY3)["status"] == "blocked"

    # Planned replacements edited without recomputing the recorded hash.
    tampered = copy.deepcopy(genuine)
    tampered["variants"]["A"]["slides"]["planned_replacements"][0]["text"] = "Edited after the fact."
    assert evaluate_slides_ab_preview(tampered, _evidence(), SELECTION_DAY3)["status"] == "blocked"


# Re-QA NEW-1..NEW-5: the gate is caller-bound -- it re-verifies the governed
# evidence against the selection held outside the receipt, so a fully
# synthetic receipt with correctly recomputed hashes still cannot certify
# itself, and vacuous or live-read claims are refused.
def _synthetic_receipt():
    from instructional_materials_coach.slides_ab_preview import _sha256

    lesson = {
        "request_id": "candy-branding-lesson-content",
        "generated_at": "38462963519:1",
        "logical_source": "daily-generation-packet",
        "verification_state": "verified-current",
        "canonical_unit_page_id": "00000000-0000-0000-0000-000000000000",
        "day_lesson_number": "Day 99",
        "record_url": "https://www.notion.so/invented",
        "source_evidence": "invented evidence",
    }

    def variant(label: str) -> dict:
        planned = [
            {"token": "title", "text": f"Invented {label}"},
            {"token": "slide_1_heading", "text": f"Invented heading {label}", "slide_index": 1},
        ]
        return {
            "contract_version": PREVIEW_CONTRACT,
            "status": "preview",
            "rendered": False,
            "classroom_ready": False,
            "live_notion_read_claimed": False,
            "native_artifact": None,
            "authority": {
                "execution_authorized": False,
                "external_write_authorized": False,
                "production_authorized": False,
                "publication_authorized": False,
            },
            "side_effects": {
                "notion_writes_performed": False,
                "drive_writes_performed": False,
                "credentials_initialized": False,
                "native_artifact_created": False,
                "classroom_publication_performed": False,
            },
            "checks": {"authored_slides_preserved": True},
            "lesson": dict(lesson),
            "slides": {
                "learning_target": "Invented target.",
                "daily_focus": "Invented focus.",
                "objectives": ["Invented target."],
                "slide_indexes": [1],
                "planned_replacements": planned,
                "planned_content_sha256": _sha256(planned),
            },
        }

    return {
        "contract_version": PREVIEW_CONTRACT,
        "status": "preview",
        "rendered": False,
        "classroom_ready": False,
        "live_notion_read_claimed": False,
        "native_artifact": None,
        "authority": {
            "execution_authorized": False,
            "external_write_authorized": False,
            "production_authorized": False,
            "publication_authorized": False,
        },
        "side_effects": {
            "notion_writes_performed": False,
            "drive_writes_performed": False,
            "credentials_initialized": False,
            "native_artifact_created": False,
            "classroom_publication_performed": False,
        },
        "checks": {"same_lesson_identity": True},
        "evaluation": {"ready": True, "performed": False, "winner": None},
        "variants": {"A": variant("A"), "B": variant("B")},
    }


def test_evaluation_gate_rejects_fully_synthetic_receipt_with_recomputed_hashes():
    gate = evaluate_slides_ab_preview(_synthetic_receipt(), _evidence(), SELECTION_DAY3)
    assert gate["status"] == "blocked"
    assert gate["winner"] is None


def test_evaluation_gate_rejects_vacuous_authority_and_live_read_claims():
    genuine = _ab()
    tampered = copy.deepcopy(genuine)
    tampered["authority"] = {}
    tampered["variants"]["A"]["authority"] = {}
    assert evaluate_slides_ab_preview(tampered, _evidence(), SELECTION_DAY3)["status"] == "blocked"

    tampered = copy.deepcopy(genuine)
    tampered["live_notion_read_claimed"] = True
    assert evaluate_slides_ab_preview(tampered, _evidence(), SELECTION_DAY3)["status"] == "blocked"
    tampered = copy.deepcopy(genuine)
    tampered["variants"]["B"]["live_notion_read_claimed"] = True
    assert evaluate_slides_ab_preview(tampered, _evidence(), SELECTION_DAY3)["status"] == "blocked"


def test_evaluation_gate_rejects_variant_covering_fewer_slides():
    from instructional_materials_coach.slides_ab_preview import _sha256

    genuine = _ab()
    tampered = copy.deepcopy(genuine)
    slides_a = tampered["variants"]["A"]["slides"]
    slides_a["planned_replacements"] = [
        item for item in slides_a["planned_replacements"] if item.get("slide_index") != 2
    ]
    slides_a["slide_indexes"] = [1]
    slides_a["planned_content_sha256"] = _sha256(slides_a["planned_replacements"])
    gate = evaluate_slides_ab_preview(tampered, _evidence(), SELECTION_DAY3)
    assert gate["status"] == "blocked"


def test_evaluation_gate_rejects_unverifiable_evidence():
    genuine = _ab()
    gate = evaluate_slides_ab_preview(genuine, None, SELECTION_DAY3)
    assert gate["status"] == "blocked"
    assert gate["reason_code"] == "result-malformed"
    wrong_day = LessonContentSelection(
        request_id="candy-branding-lesson-content",
        canonical_unit_page_id=UNIT_PAGE_ID,
        day_lesson_number="Day 1",
        generated_at="38462963519:1",
    )
    gate = evaluate_slides_ab_preview(genuine, _evidence(), wrong_day)
    assert gate["status"] == "blocked"


# Re-QA #2 NEW-6/7/8/9: every governed token/field inside the planned content
# is bound to the verified lesson or its fixed value; recorded check sets are
# pinned; top-level lesson/selection cannot be restated.
def _tamper_tokens(receipt, token: str, value: str):
    from instructional_materials_coach.slides_ab_preview import _sha256

    tampered = copy.deepcopy(receipt)
    for variant in tampered["variants"].values():
        slides = variant["slides"]
        for item in slides["planned_replacements"]:
            if item["token"] == token:
                item["text"] = value
        slides["planned_content_sha256"] = _sha256(slides["planned_replacements"])
    return tampered


@pytest.mark.parametrize("token,value", [
    ("context_lesson_canonical_unit_page_id", "00000000-0000-0000-0000-000000000000"),
    ("context_lesson_request_id", "invented-request"),
    ("context_lesson_generated_at", "999:9"),
    ("context_lesson_logical_source", "invented-source"),
    ("context_lesson_source_verification_state", "unverified"),
    ("context_lesson_objective_source", "invented"),
    ("context_production_authorized", "true"),
    ("context_publication_authorized", "true"),
    ("context_external_write_authorized", "true"),
])
def test_evaluation_gate_binds_every_governed_context_token(token, value):
    tampered = _tamper_tokens(_ab(), token, value)
    gate = evaluate_slides_ab_preview(tampered, _evidence(), SELECTION_DAY3)
    assert gate["status"] == "blocked"


def test_evaluation_gate_binds_objectives_and_title_to_planned_tokens():
    genuine = _ab()
    tampered = copy.deepcopy(genuine)
    for variant in tampered["variants"].values():
        variant["slides"]["objectives"] = ["Invented objective lacking the target."]
    assert evaluate_slides_ab_preview(tampered, _evidence(), SELECTION_DAY3)["status"] == "blocked"

    tampered = _tamper_tokens(genuine, "objective_1", "Invented objective.")
    assert evaluate_slides_ab_preview(tampered, _evidence(), SELECTION_DAY3)["status"] == "blocked"

    tampered = copy.deepcopy(genuine)
    for variant in tampered["variants"].values():
        variant["slides"]["key_vocabulary"] = "Invented vocabulary."
    assert evaluate_slides_ab_preview(tampered, _evidence(), SELECTION_DAY3)["status"] == "blocked"

    tampered = copy.deepcopy(genuine)
    for variant in tampered["variants"].values():
        variant["slides"]["title"] = "Invented title."
    assert evaluate_slides_ab_preview(tampered, _evidence(), SELECTION_DAY3)["status"] == "blocked"


def test_evaluation_gate_pins_check_sets_and_top_level_binding():
    genuine = _ab()
    tampered = copy.deepcopy(genuine)
    tampered["checks"] = {"anything": True}
    assert evaluate_slides_ab_preview(tampered, _evidence(), SELECTION_DAY3)["status"] == "blocked"

    tampered = copy.deepcopy(genuine)
    tampered["variants"]["A"]["checks"] = {"anything": True}
    assert evaluate_slides_ab_preview(tampered, _evidence(), SELECTION_DAY3)["status"] == "blocked"

    tampered = copy.deepcopy(genuine)
    tampered["lesson"] = {"day_lesson_number": "Day 99"}
    assert evaluate_slides_ab_preview(tampered, _evidence(), SELECTION_DAY3)["status"] == "blocked"

    tampered = copy.deepcopy(genuine)
    tampered["selection"] = {"request_id": "invented"}
    assert evaluate_slides_ab_preview(tampered, _evidence(), SELECTION_DAY3)["status"] == "blocked"


# Re-QA #3 NEW-10: duplicate token names in planned_replacements are a
# purely attacker shape (the producer builds from a token dict) and must
# fail closed -- a fake first entry must not hide behind the genuine one.
@pytest.mark.parametrize("token,value", [
    ("context_production_authorized", "true"),
    ("context_lesson_learning_target", "Invented target."),
    ("context_lesson_record_url", "https://www.notion.so/invented"),
    ("title", "Invented title."),
    ("objective_1", "Invented objective."),
])
def test_evaluation_gate_rejects_fake_first_duplicate_tokens(token, value):
    from instructional_materials_coach.slides_ab_preview import _sha256

    genuine = _ab()
    for scope in ("both", "A-only"):
        tampered = copy.deepcopy(genuine)
        labels = ("A", "B") if scope == "both" else ("A",)
        for label in labels:
            slides = tampered["variants"][label]["slides"]
            slides["planned_replacements"] = (
                [{"token": token, "text": value}] + slides["planned_replacements"]
            )
            slides["planned_content_sha256"] = _sha256(slides["planned_replacements"])
        gate = evaluate_slides_ab_preview(tampered, _evidence(), SELECTION_DAY3)
        assert gate["status"] == "blocked", scope


def test_evaluation_gate_blocks_unhashable_token_types_without_raising():
    genuine = _ab()
    tampered = copy.deepcopy(genuine)
    slides = tampered["variants"]["A"]["slides"]
    slides["planned_replacements"] = [{"token": ["not", "text"], "text": "x"}] + slides["planned_replacements"]
    from instructional_materials_coach.slides_ab_preview import _sha256
    slides["planned_content_sha256"] = _sha256(slides["planned_replacements"])
    gate = evaluate_slides_ab_preview(tampered, _evidence(), SELECTION_DAY3)
    assert gate["status"] == "blocked"
