"""#4072: offline, deterministic, advisory evaluation of host-supplied lesson drafts.

The evaluator is exercised against the pinned live lesson-content run 38462963519
(Candy Branding, request ``candy-branding-lesson-content``). Authored draft text in
these tests is fixture text; it is not classroom material and CI cannot assert that
any draft is good writing. A ``no-deterministic-finding`` result is a statement about
the closed deterministic checks only.
"""
from __future__ import annotations

import ast
import contextlib
import copy
import dataclasses
import hashlib
import inspect
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from instructional_workflow_contracts.common import AuthorityEvidence, sha256_hex
from instructional_workflow_contracts.material_requirement import material_requirement_source_fingerprint

from instructional_materials_coach import cli, draft_evaluation
from instructional_materials_coach.draft_evaluation import (
    CODE_AI_NOT_PERMITTED,
    CODE_ARTIFACT_UNSUPPORTED,
    CODE_BELOW_MINIMUM,
    CODE_ITEMS_REMOVED,
    CODE_LONG_LINE,
    CODE_TEACHER_VOICE,
    CODE_UNCHANGED,
    CODE_UNGROUNDED_CLAIM,
    FINDING_CODES,
    FINDING_REMEDIATION,
    FINDING_SEVERITY,
    DraftEvaluationInputError,
    evaluate_draft,
    exit_code,
    status_line,
)
from instructional_materials_coach.lesson_content_result import (
    LessonContentResultError,
    LessonContentSelection,
    lesson_content_result_from_evidence,
    verify_lesson_content_result,
)
from instructional_materials_coach.student_voice import known_teacher_voice_phrases

COACH = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
LIVE_FIXTURE = FIXTURES / "lesson_content_run_38462963519.json"
REQUIREMENT_FIXTURE = Path(__file__).parents[3] / "tests" / "fixtures" / "instructional_workflow_contracts" / "valid_material_requirement_v2.json"
DRAFT_FIXTURES = FIXTURES / "draft_evaluation"

REQUEST_ID = "candy-branding-lesson-content"
UNIT_PAGE_ID = "3907ac78-3131-8132-8f84-f9fd633acba5"
GENERATED_AT = "38462963519:1"
SELECTION = LessonContentSelection(
    request_id=REQUEST_ID,
    canonical_unit_page_id=UNIT_PAGE_ID,
    day_lesson_number="Day 1",
    generated_at=GENERATED_AT,
)
CLI_IDENTITY = [
    "--lesson-content-result", str(LIVE_FIXTURE),
    "--request-id", REQUEST_ID,
    "--canonical-unit-page-id", UNIT_PAGE_ID,
    "--lesson", "Day 1",
    "--generated-at", GENERATED_AT,
]
BASE = {
    "title": "Fixture worksheet title",
    "objectives": [],
    "lesson_identity": {"day_lesson_number": "Day 1"},
    "slides": [{"index": 1, "heading": "Fixture slide heading", "bullets": ["Fixture bullet one", "Fixture bullet two"]}],
    "worksheet_questions": ["Fixture question one?", "Fixture question two?", "Fixture question three?"],
}
NOT_EVALUATED_FIXED = ["audience-fit", "factual-accuracy", "instructional-completeness"]
CLIENT_BOUNDARY = (
    "get_credentials", "build_drive_service", "build_slides_service", "build_docs_service",
    "build_live_materials", "build_placement_transport", "get_file_metadata", "record_lesson",
)


def _dump(draft: dict) -> bytes:
    return yaml.safe_dump(draft, sort_keys=False, allow_unicode=True).encode("utf-8")


def _draft(**overrides) -> dict:
    return {**copy.deepcopy(BASE), **overrides}


def _bytes(**overrides) -> bytes:
    return _dump(_draft(**overrides))


def _evidence_dict() -> dict:
    return json.loads(LIVE_FIXTURE.read_text(encoding="utf-8"))


def _evidence_bytes(evidence: dict | None = None) -> bytes:
    return LIVE_FIXTURE.read_bytes() if evidence is None else json.dumps(evidence).encode("utf-8")


def _lesson(evidence: dict, day: str) -> dict:
    return next(item for item in evidence["result"]["lessons"] if item["day_lesson_number"] == day)


def _verified(draft: bytes | None = None, **kwargs):
    kwargs.setdefault("lesson_content_evidence", _evidence_bytes())
    kwargs.setdefault("selection", SELECTION)
    return evaluate_draft(draft if draft is not None else _bytes(), **kwargs)


def _codes(receipt: dict) -> list[str]:
    return [item["code"] for item in receipt["findings"]]


def _finding(receipt: dict, code: str) -> dict:
    return next(item for item in receipt["findings"] if item["code"] == code)


def _requirement(**changes) -> bytes:
    requirement = json.loads(REQUIREMENT_FIXTURE.read_text(encoding="utf-8"))
    if "artifact_type" in changes:
        requirement["artifact"]["artifact_type"] = changes["artifact_type"]
    if "ai_permitted" in changes:
        requirement["ai_review"]["ai_assisted_generation_permitted"] = changes["ai_permitted"]
    requirement["identity"]["source_fingerprint"] = material_requirement_source_fingerprint(requirement)
    return json.dumps(requirement).encode("utf-8")


def _walk_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_strings(item)


def _walk_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


_ALLOWED_TOKENS = (
    "factual-accuracy", "classroom_ready", "audience-fit", "instructional-completeness",
    "not-evaluated-deterministically",
)
_CLAIM_WORDS = re.compile(
    r"\b(adequate|accurate|accuracy|suitable|suitability|quality|passed|passes|pass|approved|ready|readiness|"
    r"clean|good|excellent|correct|appropriate|sufficient|safe)\b",
    re.IGNORECASE,
)


def _assert_no_quality_claims(text: str) -> None:
    for token in _ALLOWED_TOKENS:
        text = text.replace(token, " ")
    assert not _CLAIM_WORDS.search(text), text


# --------------------------------------------------------------------------------------
# Identity: existing adapter and preview, codes passed through unchanged
# --------------------------------------------------------------------------------------


def test_pinned_fixture_adequate_draft_is_verified_with_no_finding_and_embeds_the_preview_projection():
    receipt = _verified()
    assert receipt["contract_version"] == "imc-draft-evaluation-v1"
    assert receipt["status"] == "no-deterministic-finding"
    assert receipt["lesson_identity"] == "verified"
    assert receipt["identity_reason_code"] is None
    assert receipt["findings"] == []
    preview = receipt["preview"]
    assert preview["contract_version"] == "imc-lesson-worksheet-preview-v1"
    assert preview["status"] == "preview"
    assert preview["classroom_ready"] is False and preview["rendered"] is False
    assert all(preview["checks"].values()) and len(preview["checks"]) == 8
    assert re.fullmatch(r"[0-9a-f]{64}", preview["planned_content_sha256"])
    assert preview["selection"]["day_lesson_number"] == "Day 1"
    # The projection carries identity ids only, never authored or governed text.
    assert set(preview["lesson"]) == {
        "request_id", "generated_at", "logical_source", "verification_state",
        "canonical_unit_page_id", "day_lesson_number",
    }
    assert receipt["inputs"]["lesson_content_result_sha256"] == hashlib.sha256(LIVE_FIXTURE.read_bytes()).hexdigest()


def test_identity_not_verified_mode_runs_identity_independent_checks_only():
    receipt = evaluate_draft(_bytes())
    assert receipt["lesson_identity"] == "not-verified"
    assert receipt["identity_reason_code"] is None
    assert receipt["preview"] is None
    assert receipt["status"] == "no-deterministic-finding"
    assert receipt["claim_grounding"] == "empty"
    assert receipt["inputs"]["lesson_content_result_sha256"] is None


def _selection_with(**changes):
    return dataclasses.replace(SELECTION, **changes)


@pytest.mark.parametrize(
    "case",
    [
        ("wrong request", {"selection": _selection_with(request_id="another-request")}),
        ("wrong unit", {"selection": _selection_with(canonical_unit_page_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")}),
        ("lesson not found", {"selection": _selection_with(day_lesson_number="Day 99")}),
        ("stale or other run", {"selection": _selection_with(generated_at="1:1")}),
        ("unverified source", {"mutate": lambda evidence: evidence["result"]["source"].update(verification_state="unverified")}),
        ("target omitted from authored objectives", {"draft": _bytes(objectives=["An unrelated objective."], lesson_identity=None)}),
    ],
    ids=lambda case: case[0],
)
def test_identity_and_freshness_failures_block_with_the_adapter_reason_code_unchanged(case):
    _label, spec = case
    evidence = _evidence_dict()
    if "mutate" in spec:
        spec["mutate"](evidence)
    selection = spec.get("selection", SELECTION)
    draft = spec.get("draft", _bytes())
    # The expected code is whatever the existing adapter / preview itself reports.
    from instructional_materials_coach.worksheet_preview import preview_lesson_worksheet
    from instructional_materials_coach.content_spec import content_from_dict

    expected = preview_lesson_worksheet(content_from_dict(yaml.safe_load(draft)), evidence, selection)["reason_code"]
    assert expected is not None
    receipt = evaluate_draft(draft, lesson_content_evidence=_evidence_bytes(evidence), selection=selection)
    assert receipt["status"] == "blocked"
    assert receipt["lesson_identity"] == "not-verified"
    assert receipt["identity_reason_code"] == expected
    assert receipt["preview"] is None
    assert exit_code(receipt) == 1


def test_wrong_unit_and_wrong_lesson_use_distinct_adapter_codes():
    wrong_unit = _verified(selection=_selection_with(canonical_unit_page_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"))
    wrong_day = _verified(selection=_selection_with(day_lesson_number="Day 99"))
    assert wrong_unit["identity_reason_code"] != wrong_day["identity_reason_code"]


def test_evidence_and_selection_must_be_supplied_together():
    with pytest.raises(DraftEvaluationInputError) as caught:
        evaluate_draft(_bytes(), lesson_content_evidence=_evidence_bytes())
    assert caught.value.reason_code == "identity-group-incomplete"
    with pytest.raises(DraftEvaluationInputError) as caught:
        evaluate_draft(_bytes(), selection=SELECTION)
    assert caught.value.reason_code == "identity-group-incomplete"


# --------------------------------------------------------------------------------------
# Closed findings
# --------------------------------------------------------------------------------------


def test_closed_vocabulary_severities_and_remediations_are_total_and_fixed():
    assert len(FINDING_CODES) == 8 and len(set(FINDING_CODES)) == 8
    assert set(FINDING_SEVERITY) == set(FINDING_CODES) == set(FINDING_REMEDIATION)
    assert set(FINDING_SEVERITY.values()) == {"blocked", "fail", "manual-review"}
    for code, remediation in FINDING_REMEDIATION.items():
        assert isinstance(remediation, str) and remediation.strip() and "\n" not in remediation, code
        assert len(remediation) <= 512, code
        assert not re.search(r"\b(delete|drop|discard)\b", remediation, re.IGNORECASE), code
        _assert_no_quality_claims(remediation)
    assert FINDING_REMEDIATION[CODE_UNCHANGED] == (
        "Revise the draft in place; unchanged resubmission does not resolve previous findings."
    )


def test_teacher_voice_is_a_fail_finding_located_by_token():
    phrase = sorted(known_teacher_voice_phrases())[0]
    receipt = evaluate_draft(_bytes(worksheet_questions=["Plain question?", f"Use the {phrase} approach here?"]))
    finding = _finding(receipt, CODE_TEACHER_VOICE)
    assert finding["severity"] == "fail" and finding["locations"] == ["question_2"]
    assert finding["remediation"] == FINDING_REMEDIATION[CODE_TEACHER_VOICE]
    assert receipt["status"] == "fail" and exit_code(receipt) == 1


def test_instruction_line_over_35_words_is_manual_review_with_an_exact_boundary():
    thirty_five = " ".join(["word"] * 35) + "?"
    thirty_six = " ".join(["word"] * 36) + "?"
    at_limit = evaluate_draft(_bytes(worksheet_questions=[thirty_five, "Short?"]))
    over = evaluate_draft(_bytes(worksheet_questions=["Short?", thirty_six], slides=[
        {"index": 1, "heading": " ".join(["long"] * 40), "bullets": [thirty_six]},
    ]))
    assert CODE_LONG_LINE not in _codes(at_limit)
    finding = _finding(over, CODE_LONG_LINE)
    assert finding["severity"] == "manual-review"
    # Applies to questions and slide bullets, not to headings.
    assert finding["locations"] == ["slide_1_bullet_1", "question_2"]
    assert over["status"] == "review" and exit_code(over) == 0


CLAIM_TEXTS = [
    "About 40% of people prefer red?",
    "Why do 40 percent of buyers choose this?",
    "Does this color sell 3 times more candy?",
    "Studies show bright colors sell?",
    "What does the statistic say?",
    "According to experts, blue is best?",
    "Why do candy colors always work?",
    "Why does nobody dislike red?",
    "Is this color guaranteed to sell?",
]


@pytest.mark.parametrize("text", CLAIM_TEXTS)
def test_claim_pattern_families_are_manual_review_and_never_fail(text):
    receipt = evaluate_draft(_bytes(worksheet_questions=["Plain question?", text]))
    finding = _finding(receipt, CODE_UNGROUNDED_CLAIM)
    assert finding["severity"] == "manual-review" and finding["locations"] == ["question_2"]
    assert receipt["status"] == "review"


def test_a_claim_present_in_the_verified_lesson_text_is_grounded_only_in_verified_mode():
    evidence = _evidence_dict()
    _lesson(evidence, "Day 1")["daily_focus"] = "Always plan 40% of the colors before software use."
    draft = _bytes(worksheet_questions=["Why plan 40% of the colors first?", "Why always plan first?"])
    grounded = evaluate_draft(draft, lesson_content_evidence=_evidence_bytes(evidence), selection=SELECTION)
    assert grounded["lesson_identity"] == "verified" and grounded["claim_grounding"] == "verified-lesson-fields"
    assert CODE_UNGROUNDED_CLAIM not in _codes(grounded)
    ungrounded = evaluate_draft(draft)
    assert _finding(ungrounded, CODE_UNGROUNDED_CLAIM)["locations"] == ["question_1", "question_2"]


def test_claim_grounding_is_case_insensitive_like_the_pattern_match():
    evidence = _evidence_dict()
    _lesson(evidence, "Day 1")["daily_focus"] = "Studies Show that planned colors help buyers notice candy."
    draft = _bytes(worksheet_questions=["Studies show that planned colors help; why?", "Plain?", "Plain two?"])
    receipt = evaluate_draft(draft, lesson_content_evidence=_evidence_bytes(evidence), selection=SELECTION)
    assert receipt["lesson_identity"] == "verified"
    assert CODE_UNGROUNDED_CLAIM not in _codes(receipt)
    assert CODE_UNGROUNDED_CLAIM in _codes(evaluate_draft(draft))


def test_no_argument_can_suppress_default_or_downgrade_a_finding():
    parameters = set(inspect.signature(evaluate_draft).parameters)
    assert parameters == {
        "draft", "prior_draft", "lesson_content_evidence", "selection", "material_requirement",
        "artifact_type", "min_questions", "min_slides",
    }
    assert not any(re.search(r"suppress|ignore|allow|downgrade|severity|threshold|default", name) for name in parameters)
    receipt = evaluate_draft(_bytes(worksheet_questions=["Studies show colors sell?"]))
    assert CODE_UNGROUNDED_CLAIM in _codes(receipt)


def test_declared_minimum_applies_only_when_supplied_and_is_never_defaulted():
    thin = _bytes(worksheet_questions=["Only one question?"])
    assert CODE_BELOW_MINIMUM not in _codes(evaluate_draft(thin))
    receipt = evaluate_draft(thin, min_questions=3)
    finding = _finding(receipt, CODE_BELOW_MINIMUM)
    assert finding["severity"] == "fail" and finding["locations"] == ["worksheet_questions"]
    assert receipt["status"] == "fail"
    both = evaluate_draft(thin, min_questions=3, min_slides=2)
    assert _finding(both, CODE_BELOW_MINIMUM)["locations"] == ["worksheet_questions", "slides"]
    meeting = evaluate_draft(_bytes(), min_questions=3, min_slides=1)
    assert CODE_BELOW_MINIMUM not in _codes(meeting)
    assert receipt["declared"] == {
        "artifact_types": [], "min_questions": 3, "min_slides": None, "verification": "request-declared-unverified",
    }


@pytest.mark.parametrize("value", [0, -1, True, 2.5, "3"])
def test_invalid_declared_minimum_is_an_input_error(value):
    with pytest.raises(DraftEvaluationInputError) as caught:
        evaluate_draft(_bytes(), min_questions=value)
    assert caught.value.reason_code == "declared-minimum-invalid"


def test_revision_that_drops_a_slide_or_question_is_flagged_and_not_displaced_by_the_unchanged_finding():
    prior = _bytes(slides=BASE["slides"] + [{"index": 2, "heading": "Second", "bullets": ["B"]}])
    receipt = evaluate_draft(_bytes(), prior_draft=prior)
    assert _finding(receipt, CODE_ITEMS_REMOVED)["locations"] == ["slides"]
    assert CODE_UNCHANGED not in _codes(receipt)
    prior_questions = _bytes(worksheet_questions=BASE["worksheet_questions"] + ["Fourth question?"])
    receipt = evaluate_draft(_bytes(), prior_draft=prior_questions)
    assert _finding(receipt, CODE_ITEMS_REMOVED)["locations"] == ["worksheet_questions"]
    both = evaluate_draft(
        _bytes(),
        prior_draft=_bytes(slides=BASE["slides"] * 1 + [{"index": 2, "heading": "S"}], worksheet_questions=["a?", "b?", "c?", "d?"]),
    )
    assert _finding(both, CODE_ITEMS_REMOVED)["locations"] == ["slides", "worksheet_questions"]
    # Adding or keeping items is not a removal.
    assert CODE_ITEMS_REMOVED not in _codes(evaluate_draft(prior, prior_draft=_bytes()))


def test_unchanged_resubmission_is_detected_by_identity_and_whitespace_equivalence_only():
    base = _bytes()
    identical = evaluate_draft(base, prior_draft=base)
    finding = _finding(identical, CODE_UNCHANGED)
    assert finding["severity"] == "manual-review" and finding["locations"] == ["draft"]
    assert finding["remediation"] == "Revise the draft in place; unchanged resubmission does not resolve previous findings."
    # Whitespace-only differences fold under the existing normalize_text rule.
    spaced = _bytes(
        title="Fixture   worksheet\ttitle",
        worksheet_questions=["Fixture  question one?", "Fixture question\ntwo?", " Fixture question three? "],
    )
    assert CODE_UNCHANGED in _codes(evaluate_draft(spaced, prior_draft=base))
    # No case folding, punctuation stripping or fuzzy matching: these are changes.
    cased = _bytes(worksheet_questions=["fixture question one?", "Fixture question two?", "Fixture question three?"])
    assert CODE_UNCHANGED not in _codes(evaluate_draft(cased, prior_draft=base))
    punctuated = _bytes(worksheet_questions=["Fixture question one!", "Fixture question two?", "Fixture question three?"])
    assert CODE_UNCHANGED not in _codes(evaluate_draft(punctuated, prior_draft=base))
    changed = _bytes(worksheet_questions=["A different first question?", "Fixture question two?", "Fixture question three?"])
    assert CODE_UNCHANGED not in _codes(evaluate_draft(changed, prior_draft=base))
    # Metadata-only changes do not count as substantive student-facing revisions.
    metadata_only = _bytes(prerequisite_tutorials=["tutorial-0-adobe-express-favorite-food-reference"])
    assert CODE_UNCHANGED in _codes(evaluate_draft(metadata_only, prior_draft=base))


def test_without_a_prior_draft_neither_prior_finding_applies_and_it_is_recorded():
    receipt = evaluate_draft(_bytes())
    assert CODE_ITEMS_REMOVED not in _codes(receipt) and CODE_UNCHANGED not in _codes(receipt)
    assert receipt["applicability"][CODE_ITEMS_REMOVED] == "not-applicable"
    assert receipt["applicability"][CODE_UNCHANGED] == "not-applicable"
    assert "revision-regression" in receipt["not_evaluated"]
    assert receipt["inputs"]["prior_draft_sha256"] is None


def test_ai_generation_not_permitted_blocks_and_an_absent_requirement_is_never_permission():
    blocked = evaluate_draft(_bytes(), material_requirement=_requirement(ai_permitted=False))
    assert _finding(blocked, CODE_AI_NOT_PERMITTED)["severity"] == "blocked"
    assert blocked["status"] == "blocked" and blocked["requirements"] == "present"
    permitted = evaluate_draft(_bytes(), material_requirement=_requirement(ai_permitted=True))
    assert CODE_AI_NOT_PERMITTED not in _codes(permitted) and permitted["requirements"] == "present"
    absent = evaluate_draft(_bytes())
    assert absent["requirements"] == "absent"
    assert absent["applicability"][CODE_AI_NOT_PERMITTED] == "not-applicable"
    assert CODE_AI_NOT_PERMITTED not in _codes(absent)


@pytest.mark.parametrize("kind", ["worksheet", "slide-deck"])
def test_supported_artifact_types_are_evaluated(kind):
    receipt = evaluate_draft(_bytes(), artifact_type=kind)
    assert CODE_ARTIFACT_UNSUPPORTED not in _codes(receipt)
    assert receipt["declared"]["artifact_types"] == [kind]
    assert receipt["applicability"][CODE_ARTIFACT_UNSUPPORTED] == "applicable"


@pytest.mark.parametrize("kind", ["teacher-guide", "teacher-modeling-package"])
def test_teacher_modeling_artifact_types_are_blocked_with_a_routing_note(kind):
    for receipt in (
        evaluate_draft(_bytes(), artifact_type=kind),
        evaluate_draft(_bytes(), material_requirement=_requirement(artifact_type=kind)),
    ):
        finding = _finding(receipt, CODE_ARTIFACT_UNSUPPORTED)
        assert finding["severity"] == "blocked" and "#3562" in finding["routing_note"]
        assert receipt["status"] == "blocked"


def test_other_artifact_types_are_blocked_without_a_routing_note_and_malformed_types_are_input_errors():
    receipt = evaluate_draft(_bytes(), artifact_type="rubric")
    assert "routing_note" not in _finding(receipt, CODE_ARTIFACT_UNSUPPORTED)
    for bad in ("Worksheet", "work sheet", "", "x" * 65, "-lead"):
        if bad == "":
            continue
        with pytest.raises(DraftEvaluationInputError) as caught:
            evaluate_draft(_bytes(), artifact_type=bad)
        assert caught.value.reason_code == "artifact-type-invalid"


def test_invalid_material_requirement_is_an_input_error_not_permission():
    with pytest.raises(DraftEvaluationInputError) as caught:
        evaluate_draft(_bytes(), material_requirement=b'{"identity": {}}')
    assert caught.value.reason_code == "requirement-invalid"
    with pytest.raises(DraftEvaluationInputError) as caught:
        evaluate_draft(_bytes(), material_requirement=b"not json")
    assert caught.value.reason_code == "input-unreadable"


def test_status_is_derived_in_blocked_fail_review_none_order():
    phrase = sorted(known_teacher_voice_phrases())[0]
    long_line = " ".join(["word"] * 40) + "?"
    voice = _bytes(worksheet_questions=[f"The {phrase}?", "B?", "C?"])
    both = _bytes(worksheet_questions=[f"The {phrase}?", long_line, "C?"])
    only_long = _bytes(worksheet_questions=[long_line, "B?", "C?"])
    assert evaluate_draft(_bytes())["status"] == "no-deterministic-finding"
    assert evaluate_draft(only_long)["status"] == "review"
    assert evaluate_draft(both)["status"] == "fail"
    assert evaluate_draft(voice, material_requirement=_requirement(ai_permitted=False))["status"] == "blocked"
    assert _verified(voice, selection=_selection_with(day_lesson_number="Day 99"))["status"] == "blocked"


# --------------------------------------------------------------------------------------
# Evaluation limits (A1) and the content-safe, authority-false receipt
# --------------------------------------------------------------------------------------


def test_every_status_discloses_semantic_review_and_the_not_evaluated_list():
    phrase = sorted(known_teacher_voice_phrases())[0]
    receipts = [
        evaluate_draft(_bytes()),
        evaluate_draft(_bytes(worksheet_questions=["Studies show colors sell?"])),
        evaluate_draft(_bytes(worksheet_questions=[f"The {phrase}?"])),
        evaluate_draft(_bytes(), artifact_type="teacher-guide"),
    ]
    assert [item["status"] for item in receipts] == ["no-deterministic-finding", "review", "fail", "blocked"]
    for receipt in receipts:
        assert receipt["semantic_review"] == "not-performed"
        assert receipt["not_evaluated"][:3] == NOT_EVALUATED_FIXED
        assert receipt["audience_fidelity"] == "not-evaluated-deterministically"
        assert receipt["classroom_ready"] is False and receipt["preview_only"] is True
        assert receipt["authority"] == dataclasses.asdict(AuthorityEvidence())
        assert not any(receipt["authority"].values()) and not any(receipt["side_effects"].values())


def test_thin_draft_without_flags_reports_all_five_limits_and_optional_inputs_remove_two():
    thin = _bytes(worksheet_questions=["Only one question?"])
    bare = evaluate_draft(thin)
    assert bare["status"] == "no-deterministic-finding"
    assert bare["not_evaluated"] == NOT_EVALUATED_FIXED + ["structure-minimum", "revision-regression"]
    declared = evaluate_draft(thin, min_slides=1)
    assert declared["not_evaluated"] == NOT_EVALUATED_FIXED + ["revision-regression"]
    prior = evaluate_draft(thin, prior_draft=_bytes())
    assert prior["not_evaluated"] == NOT_EVALUATED_FIXED + ["structure-minimum"]
    both = evaluate_draft(thin, prior_draft=_bytes(), min_questions=1)
    assert both["not_evaluated"] == NOT_EVALUATED_FIXED


def test_no_receipt_text_or_status_line_claims_quality_accuracy_grade_fit_or_readiness():
    phrase = sorted(known_teacher_voice_phrases())[0]
    drafts = [
        evaluate_draft(_bytes()),
        _verified(),
        evaluate_draft(_bytes(worksheet_questions=["Studies show colors sell?", f"The {phrase}?"]), prior_draft=_bytes()),
        evaluate_draft(_bytes(), material_requirement=_requirement(ai_permitted=False, artifact_type="teacher-guide"), artifact_type="teacher-guide"),
    ]
    for receipt in drafts:
        _assert_no_quality_claims(status_line(receipt))
        for text in _walk_strings(receipt):
            _assert_no_quality_claims(text)


def test_no_readability_grade_level_or_semantic_verdict_key_exists_in_any_receipt():
    allowed = {"audience_fidelity", "semantic_review", "not_evaluated"}
    receipt = _verified(_bytes(worksheet_questions=["Studies show colors sell?"]), material_requirement=_requirement(), artifact_type="worksheet")
    for key in _walk_keys(receipt):
        if key in allowed:
            continue
        assert not re.search(r"readab|grade|lexile|flesch|semantic|audience|quality|score|verdict|accura", key, re.IGNORECASE), key
    assert receipt["audience_fidelity"] == "not-evaluated-deterministically"


def test_receipt_contains_no_draft_text_only_codes_counts_tokens_hashes_and_fixed_strings():
    marker = "ZZ-UNIQUE-DRAFT-MARKER-ZZ"
    draft = _bytes(
        title=f"{marker} title",
        worksheet_questions=[f"{marker} Studies show 40% of colors sell?", f"{marker} q2?"],
        slides=[{"index": 1, "heading": f"{marker} heading", "bullets": [f"{marker} bullet"]}],
    )
    receipt = _verified(draft)
    assert marker not in json.dumps(receipt)
    assert marker not in json.dumps(receipt["preview"])


def test_exact_bytes_are_hashed_and_the_fingerprint_is_over_a_free_text_free_envelope():
    draft = _bytes()
    receipt = evaluate_draft(draft)
    assert receipt["inputs"]["draft_sha256"] == hashlib.sha256(draft).hexdigest()
    envelope = {key: value for key, value in receipt.items() if key != "receipt_fingerprint"}
    assert receipt["receipt_fingerprint"] == sha256_hex(envelope)
    # A trailing newline changes the exact-byte hash and therefore the fingerprint.
    changed = evaluate_draft(draft + b"\n")
    assert changed["inputs"]["draft_sha256"] != receipt["inputs"]["draft_sha256"]
    assert changed["receipt_fingerprint"] != receipt["receipt_fingerprint"]
    other = _verified(draft, prior_draft=draft)
    assert other["inputs"]["prior_draft_sha256"] == hashlib.sha256(draft).hexdigest()


def test_same_inputs_give_an_identical_receipt_and_fingerprint():
    first, second = _verified(), _verified()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["receipt_fingerprint"] == second["receipt_fingerprint"]
    assert first["receipt_fingerprint"] != evaluate_draft(_bytes())["receipt_fingerprint"]


def test_long_multiline_and_non_ascii_drafts_produce_receipts_without_raising():
    long_question = ("Why does " + "this very long worksheet question keep going " * 20).strip() + "?\nSecond line of the same prompt."
    assert len(long_question) > 512 and "\n" in long_question
    receipt = evaluate_draft(_bytes(
        title="Café – 日本語 title",
        worksheet_questions=[long_question, "¿Qué color elegiste y por qué?", "Third?"],
    ))
    assert receipt["status"] in {"no-deterministic-finding", "review"}
    assert re.fullmatch(r"[0-9a-f]{64}", receipt["receipt_fingerprint"])
    assert CODE_LONG_LINE in _codes(receipt)


@pytest.mark.parametrize("payload", [b"", b"\xff\xfe\x00", b"title: [unterminated", b"- just\n- a list\n", b"title: x\nobjectives: []\nslides: []\n"])
def test_unparseable_drafts_are_input_errors_and_never_echo_draft_text(payload):
    with pytest.raises(DraftEvaluationInputError) as caught:
        evaluate_draft(payload)
    assert caught.value.reason_code == "input-unreadable"


def test_inputs_over_the_byte_bound_are_rejected_for_every_file_input():
    big = b"#" * (draft_evaluation.MAX_INPUT_BYTES + 1)
    for name in ("draft", "prior_draft", "lesson_content_evidence", "material_requirement"):
        kwargs = {name: big}
        if name == "lesson_content_evidence":
            kwargs["selection"] = SELECTION
        with pytest.raises(DraftEvaluationInputError) as caught:
            evaluate_draft(big if name == "draft" else _bytes(), **({} if name == "draft" else kwargs))
        assert caught.value.reason_code == "input-unreadable", name
    assert draft_evaluation.MAX_INPUT_BYTES == cli.MAX_LESSON_CONTENT_RESULT_BYTES == 262_144


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def _write(tmp_path: Path, name: str, data: bytes) -> str:
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def _tree(path: Path) -> set[str]:
    return {str(item.relative_to(path)) for item in path.rglob("*")}


@contextlib.contextmanager
def _offline():
    with contextlib.ExitStack() as stack:
        for name in CLIENT_BOUNDARY:
            if hasattr(cli, name):
                stack.enter_context(patch.object(cli, name, side_effect=AssertionError(f"{name} must not be used")))
        stack.enter_context(patch.object(socket.socket, "connect", side_effect=AssertionError("network access")))
        stack.enter_context(patch.object(socket, "create_connection", side_effect=AssertionError("network access")))
        yield


def test_cli_verified_run_writes_only_the_requested_receipt_and_states_the_limits(tmp_path, capsys, monkeypatch):
    for variable in ("GOOGLE_OAUTH_CLIENT_SECRET_PATH", "GOOGLE_OAUTH_TOKEN_PATH", "NOTION_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.delenv(variable, raising=False)
    draft = _write(tmp_path, "draft.yaml", _bytes())
    before = _tree(tmp_path)
    out = tmp_path / "nested" / "receipt.json"
    with _offline():
        code = cli.main(["evaluate-draft", "--content", draft, *CLI_IDENTITY, "--min-questions", "3", "--receipt-out", str(out)])
    captured = capsys.readouterr()
    assert code == 0
    assert _tree(tmp_path) - before == {"nested", os.path.join("nested", "receipt.json")}
    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert receipt["status"] == "no-deterministic-finding" and receipt["lesson_identity"] == "verified"
    assert receipt == evaluate_draft(
        Path(draft).read_bytes(), lesson_content_evidence=LIVE_FIXTURE.read_bytes(), selection=SELECTION, min_questions=3
    )
    assert captured.out == ""
    assert "semantic_review: not-performed" in captured.err
    assert "not_evaluated: audience-fit, factual-accuracy, instructional-completeness, revision-regression" in captured.err
    assert not list(tmp_path.glob("**/.*.tmp"))


def test_cli_without_receipt_out_prints_only_the_receipt_to_stdout(tmp_path, capsys):
    draft = _write(tmp_path, "draft.yaml", _bytes())
    before = _tree(tmp_path)
    with _offline():
        code = cli.main(["evaluate-draft", "--content", draft])
    captured = capsys.readouterr()
    assert code == 0 and _tree(tmp_path) == before
    receipt = json.loads(captured.out)
    assert receipt["lesson_identity"] == "not-verified" and receipt["semantic_review"] == "not-performed"
    assert "not_evaluated:" in captured.err and "semantic_review: not-performed" in captured.err


@pytest.mark.parametrize(
    "extra, expected_exit, expected_status",
    [
        ([], 0, "no-deterministic-finding"),
        (["--min-questions", "9"], 1, "fail"),
        (["--artifact-type", "teacher-guide"], 1, "blocked"),
    ],
)
def test_cli_exit_codes_mirror_preview_worksheet(tmp_path, capsys, extra, expected_exit, expected_status):
    draft = _write(tmp_path, "draft.yaml", _bytes())
    code = cli.main(["evaluate-draft", "--content", draft, *extra])
    receipt = json.loads(capsys.readouterr().out)
    assert (code, receipt["status"]) == (expected_exit, expected_status)


def test_cli_review_status_exits_zero(tmp_path, capsys):
    draft = _write(tmp_path, "draft.yaml", _bytes(worksheet_questions=["Studies show colors sell?"]))
    assert cli.main(["evaluate-draft", "--content", draft]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "review"


def test_cli_prior_draft_material_requirement_and_artifact_type_arguments_are_honored(tmp_path, capsys):
    draft = _write(tmp_path, "draft.yaml", _bytes())
    code = cli.main([
        "evaluate-draft", "--content", draft, "--prior-draft", draft,
        "--material-requirement", _write(tmp_path, "requirement.json", _requirement(ai_permitted=False)),
        "--artifact-type", "worksheet",
    ])
    receipt = json.loads(capsys.readouterr().out)
    assert code == 1 and receipt["status"] == "blocked"
    assert set(_codes(receipt)) == {CODE_UNCHANGED, CODE_AI_NOT_PERMITTED}


def test_cli_identity_group_is_all_or_none(tmp_path, capsys):
    draft = _write(tmp_path, "draft.yaml", _bytes())
    for partial in (["--lesson-content-result", str(LIVE_FIXTURE)], ["--request-id", REQUEST_ID], CLI_IDENTITY[:-2]):
        assert cli.main(["evaluate-draft", "--content", draft, *partial]) == 1
        captured = capsys.readouterr()
        assert captured.out == "" and "identity-group-incomplete" in captured.err


def test_cli_blocked_identity_failure_exits_one_and_still_states_the_limits(tmp_path, capsys):
    draft = _write(tmp_path, "draft.yaml", _bytes())
    args = [*CLI_IDENTITY]
    args[args.index("--lesson") + 1] = "Day 99"
    assert cli.main(["evaluate-draft", "--content", draft, *args]) == 1
    captured = capsys.readouterr()
    receipt = json.loads(captured.out)
    assert receipt["status"] == "blocked" and receipt["identity_reason_code"]
    assert "semantic_review: not-performed" in captured.err and "not_evaluated:" in captured.err


def test_cli_rejects_unreadable_oversized_and_invalid_inputs_without_a_receipt(tmp_path, capsys):
    draft = _write(tmp_path, "draft.yaml", _bytes())
    receipt_path = tmp_path / "receipt.json"
    huge = _write(tmp_path, "huge.yaml", b"#" * (cli.MAX_LESSON_CONTENT_RESULT_BYTES + 1))
    cases = [
        ["--content", str(tmp_path / "missing.yaml")],
        ["--content", huge],
        ["--content", draft, "--prior-draft", huge],
        ["--content", _write(tmp_path, "bad.yaml", b"title: [")],
        ["--content", draft, "--min-questions", "0"],
        ["--content", draft, "--artifact-type", "Not A Token"],
        ["--content", draft, "--material-requirement", _write(tmp_path, "req.json", b"{}")],
    ]
    for case in cases:
        assert cli.main(["evaluate-draft", *case, "--receipt-out", str(receipt_path)]) == 1, case
        captured = capsys.readouterr()
        assert "input rejected" in captured.err and captured.out == ""
        assert not receipt_path.exists(), case


def test_cli_receipt_persistence_failure_exits_one(tmp_path, capsys):
    draft = _write(tmp_path, "draft.yaml", _bytes())
    blocker = _write(tmp_path, "blocker", b"x")
    assert cli.main(["evaluate-draft", "--content", draft, "--receipt-out", os.path.join(blocker, "r.json")]) == 1
    assert "receipt persistence failed" in capsys.readouterr().err


def test_cli_argument_surface_is_the_documented_one():
    parser_help = subprocess.run(
        [sys.executable, "-m", "instructional_materials_coach.cli", "evaluate-draft", "--help"],
        capture_output=True, text=True, check=True,
    ).stdout
    for flag in (
        "--content", "--prior-draft", "--lesson-content-result", "--request-id", "--canonical-unit-page-id",
        "--lesson", "--generated-at", "--material-requirement", "--artifact-type", "--min-questions",
        "--min-slides", "--receipt-out",
    ):
        assert flag in parser_help, flag


# --------------------------------------------------------------------------------------
# Boundary: no network, credential, provider, subprocess or external write is reachable
# --------------------------------------------------------------------------------------

FORBIDDEN_MODULE_NAMES = {
    "drive_client", "workspace_clients", "live_build", "placement_transport", "connected_visual_placement",
    "build_request", "classroom_admission", "build_receipt", "googleapiclient", "google", "requests", "urllib",
    "socket", "http", "subprocess", "notion_client", "github",
}
FORBIDDEN_LOADED_PREFIXES = (
    "googleapiclient", "google.auth", "google_auth_oauthlib", "httplib2", "requests", "notion_client", "github",
    "instructional_materials_coach.drive_client", "instructional_materials_coach.workspace_clients",
    "instructional_materials_coach.live_build", "instructional_materials_coach.placement_transport",
    "instructional_materials_coach.connected_visual_placement", "instructional_materials_coach.build_request",
    "instructional_materials_coach.classroom_admission", "instructional_materials_coach.build_receipt",
    "instructional_materials_coach.cli",
)


def test_module_imports_no_provider_credential_network_or_write_path():
    tree = ast.parse((COACH / "src" / "instructional_materials_coach" / "draft_evaluation.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                imported.add((node.module or "").split(".")[0])
            else:
                imported.add((node.module or "").split(".")[0])
    assert not imported & FORBIDDEN_MODULE_NAMES, imported & FORBIDDEN_MODULE_NAMES
    assert not any("conversational_unit_knowledge" in name for name in imported)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"open", "exec", "eval", "__import__"}, node.func.id


def _loaded_after(statement: str) -> list[str]:
    probe = f"import sys, json\n{statement}\nprint(json.dumps(sorted(sys.modules)))\n"
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(path for path in sys.path if path))
    return json.loads(subprocess.run([sys.executable, "-c", probe], env=env, check=True, capture_output=True, text=True).stdout)


def test_transitive_import_closure_has_no_provider_write_or_knowledge_persistence_module():
    loaded = _loaded_after("import instructional_materials_coach.draft_evaluation")
    assert not [name for name in loaded if name.startswith(FORBIDDEN_LOADED_PREFIXES)]
    assert not [name for name in loaded if "conversational_unit_knowledge" in name]


def test_requirement_path_also_loads_no_provider_or_write_module():
    loaded = _loaded_after(
        "from instructional_materials_coach.draft_evaluation import evaluate_draft\n"
        "import pathlib\n"
        f"req = pathlib.Path({str(REQUIREMENT_FIXTURE)!r}).read_bytes()\n"
        "receipt = evaluate_draft(b'title: t\\nobjectives: []\\nslides: []\\nworksheet_questions: []\\n', material_requirement=req)\n"
        "assert receipt['requirements'] == 'present', receipt\n"
        "assert receipt['applicability']['draft-ai-generation-not-permitted'] == 'applicable', receipt\n"
    )
    assert not [name for name in loaded if name.startswith(FORBIDDEN_LOADED_PREFIXES)]


def test_evaluation_performs_no_network_or_file_access():
    with patch.object(socket.socket, "connect", side_effect=AssertionError("network")), patch(
        "builtins.open", side_effect=AssertionError("file access")
    ):
        receipt = evaluate_draft(_bytes(), prior_draft=_bytes(), material_requirement=_requirement())
    assert receipt["status"] == "review"
    assert CODE_UNCHANGED in _codes(receipt)


# --------------------------------------------------------------------------------------
# Model-produced draft fixtures with recorded provenance and asserted goldens
# --------------------------------------------------------------------------------------


def _fixture_cases():
    manifest = json.loads((DRAFT_FIXTURES / "goldens.json").read_text(encoding="utf-8"))
    return [pytest.param(entry, id=entry["draft"]) for entry in manifest["fixtures"]]


def test_provenance_file_records_model_host_date_prompt_hash_and_golden_review_status():
    provenance = (DRAFT_FIXTURES / "PROVENANCE.md").read_text(encoding="utf-8")
    manifest = json.loads((DRAFT_FIXTURES / "goldens.json").read_text(encoding="utf-8"))
    assert len(manifest["fixtures"]) >= 3
    for field in ("| model |", "| host |", "| date |", "prompt (sha256)", "golden_review"):
        assert field in provenance, field
    for entry in manifest["fixtures"]:
        draft_bytes = (DRAFT_FIXTURES / entry["draft"]).read_bytes()
        assert hashlib.sha256(draft_bytes).hexdigest() == entry["draft_sha256"] == entry["provenance"]["draft_sha256"]
        assert entry["provenance"]["model"] and entry["provenance"]["host"] and entry["provenance"]["date"]
        assert re.fullmatch(r"[0-9a-f]{64}", entry["provenance"]["prompt_sha256"])
        assert entry["golden_review"] in {"unreviewed-by-human", "human-reviewed"}
        if entry["golden_review"] == "human-reviewed":
            assert entry["reviewer"] and entry["reviewed_on"]


@pytest.mark.parametrize("entry", _fixture_cases())
def test_model_produced_draft_matches_its_asserted_golden_findings(entry):
    draft = (DRAFT_FIXTURES / entry["draft"]).read_bytes()
    receipt = _verified(draft, **({"min_questions": entry["min_questions"]} if entry.get("min_questions") else {}))
    assert receipt["status"] == entry["expected_status"]
    assert {item["code"]: item["locations"] for item in receipt["findings"]} == entry["expected_findings"]
    assert receipt["lesson_identity"] == "verified"
    assert receipt["semantic_review"] == "not-performed"
    assert receipt["inputs"]["draft_sha256"] == entry["draft_sha256"]


def test_suite_states_that_ci_cannot_assert_writing_quality():
    assert "CI cannot assert" in (__doc__ or "")


# --------------------------------------------------------------------------------------
# Independent Gemini-review negative controls (verified/reproduced before repair)
# --------------------------------------------------------------------------------------


def test_gemini_receipt_out_rejects_same_input_symlink_and_hardlink(tmp_path, capsys):
    original = _bytes()
    source = tmp_path / "draft.yaml"
    source.write_bytes(original)
    symlink = tmp_path / "link.yaml"
    symlink.symlink_to(source)
    hardlink = tmp_path / "hardlink.yaml"
    os.link(source, hardlink)
    for output in (source, symlink, hardlink):
        assert cli.main(["evaluate-draft", "--content", str(source), "--receipt-out", str(output)]) == 1
        captured = capsys.readouterr()
        assert "input-output-path-collision" in captured.err and captured.out == ""
        assert source.read_bytes() == original
    assert cli.main([
        "evaluate-draft", "--content", str(source), "--prior-draft", str(hardlink),
        "--receipt-out", str(hardlink),
    ]) == 1
    assert source.read_bytes() == original


def test_gemini_draft_yaml_alias_and_excessive_nesting_are_rejected_before_expansion():
    original = _bytes()
    with pytest.raises(DraftEvaluationInputError) as caught:
        evaluate_draft(original + b"\nextra: &anchor [a,b]\nalias: *anchor\n")
    assert caught.value.reason_code == "input-unreadable"
    deep = original + b"\nextra: " + b"[" * 70 + b"x" + b"]" * 70 + b"\n"
    with pytest.raises(DraftEvaluationInputError) as caught:
        evaluate_draft(deep)
    assert caught.value.reason_code == "input-unreadable"


def test_gemini_empty_question_placeholders_do_not_meet_declared_minimum():
    receipt = evaluate_draft(_bytes(worksheet_questions=["A real question?", "", "  ", "\u200b"]), min_questions=4)
    assert receipt["status"] == "fail"
    assert _finding(receipt, CODE_BELOW_MINIMUM)["locations"] == ["worksheet_questions"]
    assert receipt["draft_counts"]["questions"] == 4


def test_gemini_metadata_only_changes_cannot_hide_unchanged_student_content():
    source = _bytes()
    other = _bytes(lesson_identity={"day_lesson_number": "Day 2"})
    receipt = evaluate_draft(other, prior_draft=source)
    assert CODE_UNCHANGED in _codes(receipt)
    assert receipt["status"] == "review"
    changed = _bytes(worksheet_questions=["A genuinely changed question?", *BASE["worksheet_questions"][1:]])
    assert CODE_UNCHANGED not in _codes(evaluate_draft(changed, prior_draft=source))


def test_gemini_conflicting_supported_artifact_declarations_are_input_errors():
    with patch.object(draft_evaluation, "_requirement_facts", return_value=("worksheet", True)):
        with pytest.raises(DraftEvaluationInputError) as caught:
            evaluate_draft(_bytes(), material_requirement=b"fixture", artifact_type="slide-deck")
        assert caught.value.reason_code == "artifact-type-conflict"
        with pytest.raises(DraftEvaluationInputError) as caught:
            evaluate_draft(_bytes(), material_requirement=b"fixture", artifact_type="rubric")
        assert caught.value.reason_code == "artifact-type-conflict"
        same = evaluate_draft(_bytes(), material_requirement=b"fixture", artifact_type="worksheet")
        assert same["declared"]["artifact_types"] == ["worksheet"]


def test_gemini_empty_artifact_flag_is_invalid_in_library_and_cli(tmp_path, capsys):
    with pytest.raises(DraftEvaluationInputError) as caught:
        evaluate_draft(_bytes(), artifact_type="")
    assert caught.value.reason_code == "artifact-type-invalid"
    draft = _write(tmp_path, "draft.yaml", _bytes())
    assert cli.main(["evaluate-draft", "--content", draft, "--artifact-type", ""]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "artifact-type-invalid" in captured.err
    assert cli.main(["evaluate-draft", "--content", draft]) == 0
    assert json.loads(capsys.readouterr().out)["declared"]["artifact_types"] == []


def test_gemini_finding_location_truncation_records_full_occurrence_count():
    marker = "NO-FREE-TEXT-MARKER"
    words = " ".join(["word"] * 36)
    receipt = evaluate_draft(_bytes(worksheet_questions=[f"{marker} {words} {i}?" for i in range(33)]))
    finding = _finding(receipt, CODE_LONG_LINE)
    assert finding["occurrences"] == 33
    assert len(finding["locations"]) == 32
    assert finding["locations"][0] == "question_1" and finding["locations"][-1] == "question_32"
    assert finding["locations_truncated"] is True
    assert marker not in json.dumps(receipt)


def test_gemini_invalid_scalar_parameter_precedes_yaml_parsing():
    with pytest.raises(DraftEvaluationInputError) as caught:
        evaluate_draft(b"this: [is not valid", min_questions=0)
    assert caught.value.reason_code == "declared-minimum-invalid"


def test_gemini_whitespace_identity_flag_returns_blocked_receipt(tmp_path, capsys):
    draft = _write(tmp_path, "draft.yaml", _bytes())
    evidence = _write(tmp_path, "lesson-content.json", _evidence_bytes())
    args = ["--lesson-content-result", evidence, "--request-id", "   ",
            "--canonical-unit-page-id", UNIT_PAGE_ID, "--lesson", "Day 1",
            "--generated-at", GENERATED_AT]
    assert cli.main(["evaluate-draft", "--content", draft, *args]) == 1
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "blocked"
    assert receipt["identity_reason_code"] == "selection-malformed"


def test_gemini_routing_note_is_non_authorizing_constant():
    from instructional_materials_coach.draft_evaluation import TEACHER_MODELING_ROUTING_NOTE
    _assert_no_quality_claims(TEACHER_MODELING_ROUTING_NOTE)
