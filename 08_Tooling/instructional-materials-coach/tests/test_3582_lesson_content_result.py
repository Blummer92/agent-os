"""#3582: governed #3580 lesson-content results reach the existing Coach seams.

The live fixture is the evidence object the governed ``agent-os-notion-read``
workflow printed for run 38462963519 attempt 1 (job 115522591011, head
665a7172080d0db1df50d3cbe3cddd0027b06349; uploaded artifact 11847730633,
zip digest sha256:9617779ef63deffe11493eb779776c7450ed462b903c42e0ae67f176cc9f469f).
It is pinned by its canonical-JSON SHA-256 so silent drift fails here.

Authored lesson text in these tests is fixture text only; it is not
classroom material and is used solely to prove preservation.
"""
from __future__ import annotations

import ast
import copy
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from instructional_materials_coach.content_spec import content_from_dict, load_lesson_content
from instructional_materials_coach.docs_requests import build_docs_replace_requests
from instructional_materials_coach.lesson_content_result import (
    TOKEN_DAY,
    TOKEN_FOCUS,
    TOKEN_GENERATED_AT,
    TOKEN_OBJECTIVE_SOURCE,
    TOKEN_RECORD_URL,
    TOKEN_REQUEST_ID,
    TOKEN_SOURCE_EVIDENCE,
    TOKEN_TARGET,
    TOKEN_UNIT_PAGE_ID,
    TOKEN_VOCABULARY,
    LessonContentResultError,
    LessonContentSelection,
    compose_lesson_content_result,
    lesson_content_result_from_evidence,
    verify_lesson_content_result,
)
from instructional_materials_coach.slides_requests import build_slides_replace_requests

COACH = Path(__file__).parents[1]
LIVE_FIXTURE = Path(__file__).parent / "fixtures" / "lesson_content_run_38462963519.json"
LIVE_FIXTURE_SHA256 = "d4b332b9b24335a6b700cc8d33b4e911eebce7fcb333392e82213558c5f69ec6"

REQUEST_ID = "candy-branding-lesson-content"
UNIT_PAGE_ID = "3907ac78-3131-8132-8f84-f9fd633acba5"
GENERATED_AT = "38462963519:1"
DAY1_TARGET = "I can choose colors on purpose and explain how they match the candy mood and audience."
DAY1_FOCUS = "Plan intentional candy color choices before software use."
DAY1_URL = "https://app.notion.com/p/Candy-Branding-Design-Day-1-Color-Planning-3717ac7831318135ae7cf2ead0cf28ac"
DAY3_TARGET = "I can use font pairing and hierarchy so my candy text is clear and intentional."

SELECTION = LessonContentSelection(
    request_id=REQUEST_ID,
    canonical_unit_page_id=UNIT_PAGE_ID,
    day_lesson_number="Day 1",
    generated_at=GENERATED_AT,
)


def _evidence() -> dict:
    return json.loads(LIVE_FIXTURE.read_text(encoding="utf-8"))


def _result() -> dict:
    return _evidence()["result"]


def _lesson(result: dict, day: str) -> dict:
    (match,) = [item for item in result["lessons"] if item["day_lesson_number"] == day]
    return match


def _authored(objectives=None, **overrides):
    data = {
        "title": "Fixture lesson title",
        "objectives": [] if objectives is None else objectives,
        # Independent authored lesson-identity binding: the fill of empty
        # authored objectives requires it to exactly match the selection.
        "lesson_identity": {"day_lesson_number": "Day 1"},
        "slides": [
            {"index": 1, "heading": "Fixture slide heading", "bullets": ["Fixture bullet A", "Fixture bullet B"]},
        ],
        "worksheet_questions": ["Fixture question one?", "Fixture question two?"],
    }
    data.update(overrides)
    return content_from_dict(data)


def _reject(code: str, content=None, evidence=None, selection=SELECTION) -> None:
    with pytest.raises(LessonContentResultError) as caught:
        compose_lesson_content_result(
            content if content is not None else _authored(),
            evidence if evidence is not None else _evidence(),
            selection,
        )
    assert caught.value.reason_code == code, str(caught.value)


# ---------------------------------------------------------------------------
# Test 2: the verified Candy Branding Day 1 lesson reaches the Coach
# ---------------------------------------------------------------------------


def test_live_fixture_is_the_pinned_run_evidence() -> None:
    evidence = _evidence()
    canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == LIVE_FIXTURE_SHA256
    assert evidence["generated_at"] == GENERATED_AT
    assert evidence["dispatch_status"] == "completed"
    assert len(evidence["result"]["lessons"]) == 6


def test_verified_day1_identity_objective_focus_and_provenance_reach_the_coach() -> None:
    authored = _authored()
    composed = compose_lesson_content_result(authored, _evidence(), SELECTION)

    tokens = composed.placeholder_tokens()
    assert tokens[TOKEN_TARGET] == DAY1_TARGET
    assert tokens[TOKEN_FOCUS] == DAY1_FOCUS
    assert tokens[TOKEN_DAY] == "Day 1"
    assert tokens[TOKEN_UNIT_PAGE_ID] == UNIT_PAGE_ID
    assert tokens[TOKEN_RECORD_URL] == DAY1_URL
    assert tokens[TOKEN_REQUEST_ID] == REQUEST_ID
    assert tokens[TOKEN_GENERATED_AT] == GENERATED_AT
    assert tokens[TOKEN_SOURCE_EVIDENCE].startswith("Candy Brand Design source says Day 1 ")
    assert tokens["context_lesson_logical_source"] == "daily-generation-packet"
    assert tokens["context_lesson_source_verification_state"] == "verified-current"
    assert tokens["context_production_authorized"] == "false"
    # Empty authored objectives are filled only from the verified record.
    assert composed.objectives == [DAY1_TARGET, DAY1_FOCUS]
    assert tokens["objective_1"] == DAY1_TARGET
    assert tokens[TOKEN_OBJECTIVE_SOURCE] == "governed-lesson-content"

    # The existing Coach request builders carry the verified lesson context.
    docs = {r["replaceAllText"]["containsText"]["text"]: r["replaceAllText"]["replaceText"]
            for r in build_docs_replace_requests(composed)}
    slides = {r["replaceAllText"]["containsText"]["text"]: r["replaceAllText"]["replaceText"]
              for r in build_slides_replace_requests(composed)}
    for planned in (docs, slides):
        assert planned["{{" + TOKEN_TARGET + "}}"] == DAY1_TARGET
        assert planned["{{" + TOKEN_FOCUS + "}}"] == DAY1_FOCUS


def test_authored_slides_questions_and_title_are_preserved_exactly() -> None:
    authored = _authored()
    composed = compose_lesson_content_result(authored, _evidence(), SELECTION)
    assert composed.title == authored.title
    assert composed.slides == authored.slides
    assert composed.worksheet_questions == authored.worksheet_questions
    tokens = composed.placeholder_tokens()
    assert tokens["question_1"] == "Fixture question one?"
    assert tokens["slide_1_bullet_2"] == "Fixture bullet B"
    lesson_tokens = {key for key in tokens if key.startswith("context_lesson_")}
    authored_tokens = set(authored.placeholder_tokens())
    assert set(tokens) == authored_tokens | lesson_tokens | {
        "objective_1", "objective_2",
        "context_production_authorized", "context_publication_authorized",
        "context_external_write_authorized",
    }


def test_bare_result_and_runner_envelope_compose_identically() -> None:
    from_envelope = compose_lesson_content_result(_authored(), _evidence(), SELECTION)
    from_result = compose_lesson_content_result(_authored(), _result(), SELECTION)
    assert from_envelope == from_result


def test_authored_objective_matching_the_verified_target_is_kept() -> None:
    authored = _authored(objectives=["  I can choose colors on purpose and explain how they\nmatch the candy mood and audience. ", "Fixture extra objective"])
    composed = compose_lesson_content_result(authored, _evidence(), SELECTION)
    assert composed.objectives == authored.objectives
    assert composed.placeholder_tokens()[TOKEN_OBJECTIVE_SOURCE] == "authored"


def test_absent_key_vocabulary_stays_absent() -> None:
    tokens = compose_lesson_content_result(_authored(), _evidence(), SELECTION).placeholder_tokens()
    assert TOKEN_VOCABULARY not in tokens
    assert not [key for key in tokens if "vocab" in key]


def test_verified_key_vocabulary_passes_through_verbatim() -> None:
    evidence = _evidence()
    _lesson(evidence["result"], "Day 1")["key_vocabulary"] = "hue, value, palette"
    tokens = compose_lesson_content_result(_authored(), evidence, SELECTION).placeholder_tokens()
    assert tokens[TOKEN_VOCABULARY] == "hue, value, palette"


def test_inputs_are_not_mutated() -> None:
    evidence = _evidence()
    authored = _authored()
    before_evidence = copy.deepcopy(evidence)
    before_authored = copy.deepcopy(authored)
    compose_lesson_content_result(authored, evidence, SELECTION)
    assert evidence == before_evidence
    assert authored == before_authored


def test_yaml_only_behavior_is_unchanged() -> None:
    content = load_lesson_content(COACH / "samples" / "sample_lesson.yaml")
    assert content.context_tokens == {}
    assert content.placeholder_tokens() == {
        "title": "Fractions Intro",
        "objective_1": "Add fractions with like denominators",
        "objective_2": "Compare the size of two fractions",
        "slide_1_heading": "Welcome",
        "slide_1_bullet_1": "Today we're learning about fractions",
        "slide_1_bullet_2": "By the end you'll be able to add and compare them",
        "slide_2_heading": "Adding Fractions",
        "slide_2_bullet_1": "Keep the denominator the same",
        "slide_2_bullet_2": "Add the numerators",
        "question_1": "What is 1/4 + 2/4?",
        "question_2": "Which is bigger, 3/8 or 1/2?",
    }


# ---------------------------------------------------------------------------
# Negative cases: every one fails closed with an explicit reason
# ---------------------------------------------------------------------------


def test_foreign_unit_record_rejects_the_whole_result() -> None:
    evidence = _evidence()
    _lesson(evidence["result"], "Day 4")["canonical_unit"]["page_id"] = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    _reject("unit-mismatch", evidence=evidence)


def test_selection_for_a_foreign_unit_rejects() -> None:
    _reject("unit-mismatch", selection=dataclasses.replace(SELECTION, canonical_unit_page_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"))


def test_wrong_lesson_number_is_not_found() -> None:
    _reject("lesson-not-found", selection=dataclasses.replace(SELECTION, day_lesson_number="Day 9"))


def test_wrong_lesson_against_authored_day1_objective_conflicts() -> None:
    authored = _authored(objectives=[DAY1_TARGET])
    _reject("objective-conflict", content=authored, selection=dataclasses.replace(SELECTION, day_lesson_number="Day 3"))


def test_authored_objectives_without_the_verified_target_conflict() -> None:
    _reject("objective-conflict", content=_authored(objectives=["A different authored objective"]))


def test_authored_objectives_mixing_another_lessons_target_conflict() -> None:
    _reject("objective-conflict", content=_authored(objectives=[DAY1_TARGET, DAY3_TARGET]))


@pytest.mark.parametrize(
    "relation",
    [
        {},
        {"page_id": UNIT_PAGE_ID, "url": "https://example.invalid"},
        {"page_id": UNIT_PAGE_ID.replace("-", "")},
        {"page_id": "not-a-notion-id"},
        {"page_id": None},
        [UNIT_PAGE_ID],
    ],
)
def test_malformed_relations_reject(relation) -> None:
    evidence = _evidence()
    _lesson(evidence["result"], "Day 2")["canonical_unit"] = relation
    _reject("lesson-malformed", evidence=evidence)


@pytest.mark.parametrize("state", ["unverified", "verified-stale", "historical-lead"])
def test_unverified_or_stale_source_rejects(state) -> None:
    evidence = _evidence()
    evidence["result"]["source"]["verification_state"] = state
    _reject("source-unverified", evidence=evidence)


def test_unknown_source_rejects() -> None:
    evidence = _evidence()
    evidence["result"]["source"]["logical_source"] = "icon-system"
    _reject("source-unknown", evidence=evidence)


def test_stale_run_provenance_rejects() -> None:
    _reject("provenance-mismatch", selection=dataclasses.replace(SELECTION, generated_at="38458482848:1"))


def test_envelope_and_result_provenance_must_agree() -> None:
    evidence = _evidence()
    evidence["generated_at"] = "38462963519:2"
    _reject("provenance-mismatch", evidence=evidence)


def test_request_mismatch_rejects() -> None:
    _reject("request-mismatch", selection=dataclasses.replace(SELECTION, request_id="photography-lesson-content"))


@pytest.mark.parametrize("field", ["daily_learning_target", "source_evidence", "record_url", "day_lesson_number"])
def test_missing_required_field_key_rejects(field) -> None:
    evidence = _evidence()
    del _lesson(evidence["result"], "Day 1")[field]
    _reject("lesson-field-missing", evidence=evidence)


@pytest.mark.parametrize("field", ["daily_learning_target", "source_evidence"])
def test_absent_required_selected_value_rejects(field) -> None:
    evidence = _evidence()
    _lesson(evidence["result"], "Day 1")[field] = None
    _reject("lesson-field-missing", evidence=evidence)


@pytest.mark.parametrize("value", ["", "   "])
def test_whitespace_only_vocabulary_is_absent_not_malformed(value) -> None:
    """Defect 9: a whitespace-only optional field is producer-absent (#3582).

    It must not reject an otherwise valid record; no vocabulary token is
    planned. Invisible (zero-width) text stays malformed, never absent.
    """
    evidence = _evidence()
    _lesson(evidence["result"], "Day 1")["key_vocabulary"] = value
    tokens = compose_lesson_content_result(_authored(), evidence, SELECTION).placeholder_tokens()
    assert TOKEN_VOCABULARY not in tokens


@pytest.mark.parametrize("value", [7, ["hue"], "​"])
def test_fabricated_or_malformed_vocabulary_rejects(value) -> None:
    evidence = _evidence()
    _lesson(evidence["result"], "Day 1")["key_vocabulary"] = value
    _reject("lesson-malformed", evidence=evidence)


def test_non_notion_record_url_rejects() -> None:
    evidence = _evidence()
    _lesson(evidence["result"], "Day 1")["record_url"] = "https://example.invalid/day-1"
    _reject("lesson-malformed", evidence=evidence)


def test_unexpected_result_and_lesson_keys_reject() -> None:
    evidence = _evidence()
    evidence["result"]["page_body"] = "raw page text"
    _reject("result-unexpected-key", evidence=evidence)
    evidence = _evidence()
    _lesson(evidence["result"], "Day 1")["agent_prompt_to_run_next"] = "internal"
    _reject("result-unexpected-key", evidence=evidence)


@pytest.mark.parametrize("where", ["result", "lesson", "envelope", "admission"])
def test_credential_bearing_keys_reject(where) -> None:
    evidence = _evidence()
    target = {
        "result": evidence["result"],
        "lesson": _lesson(evidence["result"], "Day 1"),
        "envelope": evidence,
        "admission": evidence["admission"],
    }[where]
    target["notion_token"] = "secret_value"
    _reject("credential-key-present", evidence=evidence)


@pytest.mark.parametrize(
    ("key", "value"),
    [("result_kind", "agent-os-notion-read-result"), ("request_class", "source-schema"), ("schema_version", "2.0")],
)
def test_wrong_result_class_rejects(key, value) -> None:
    evidence = _evidence()
    evidence["result"][key] = value
    _reject("result-class-mismatch", evidence=evidence)


def test_widened_authority_rejects() -> None:
    evidence = _evidence()
    evidence["result"]["authority"]["write_allowed"] = True
    _reject("authority-not-fail-closed", evidence=evidence)
    evidence = _evidence()
    evidence["drive_writes_performed"] = True
    _reject("authority-not-fail-closed", evidence=evidence)


def test_incomplete_dispatch_rejects() -> None:
    evidence = _evidence()
    evidence["dispatch_status"] = "blocked"
    _reject("dispatch-not-completed", evidence=evidence)


def test_duplicate_lesson_identity_is_ambiguous() -> None:
    evidence = _evidence()
    duplicate = copy.deepcopy(_lesson(evidence["result"], "Day 1"))
    duplicate["record_url"] = DAY1_URL + "-copy"
    evidence["result"]["lessons"].append(duplicate)
    _reject("lesson-identity-ambiguous", evidence=evidence)
    evidence = _evidence()
    _lesson(evidence["result"], "Day 2")["record_url"] = DAY1_URL
    _reject("lesson-identity-ambiguous", evidence=evidence)


@pytest.mark.parametrize(("key", "value"), [("slides", []), ("worksheet_questions", []), ("worksheet_questions", ["  "])])
def test_missing_authored_materials_reject(key, value) -> None:
    _reject("authored-content-missing", content=_authored(**{key: value}))


def test_conflicting_existing_context_token_rejects() -> None:
    authored = _authored().with_context_tokens({TOKEN_TARGET: "A different target"})
    _reject("context-token-conflict", content=authored)


@pytest.mark.parametrize(
    "selection",
    [
        dataclasses.replace(SELECTION, canonical_unit_page_id=UNIT_PAGE_ID.replace("-", "")),
        dataclasses.replace(SELECTION, day_lesson_number=" Day 1"),
        dataclasses.replace(SELECTION, generated_at=""),
        None,
    ],
)
def test_malformed_selection_rejects(selection) -> None:
    with pytest.raises(LessonContentResultError) as caught:
        verify_lesson_content_result(_result(), selection)
    assert caught.value.reason_code == "selection-malformed"


@pytest.mark.parametrize("value", [None, [], "result", {"neither": True}])
def test_non_result_evidence_rejects(value) -> None:
    with pytest.raises(LessonContentResultError) as caught:
        lesson_content_result_from_evidence(value)
    assert caught.value.reason_code == "result-malformed"


def test_adapter_and_preview_modules_import_no_provider_or_write_path() -> None:
    forbidden = {
        "drive_client", "workspace_clients", "live_build", "placement_transport",
        "build_receipt", "connected_visual_placement", "googleapiclient", "google",
        "requests", "urllib", "socket", "http", "subprocess",
    }
    package = COACH / "src" / "instructional_materials_coach"
    for name in ("lesson_content_result.py", "worksheet_preview.py"):
        tree = ast.parse((package / name).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        assert not imported & forbidden, (name, imported & forbidden)


def test_preview_transitive_import_closure_has_no_provider_or_write_module() -> None:
    probe = (
        "import sys, json\n"
        "import instructional_materials_coach.worksheet_preview\n"
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(path for path in sys.path if path))
    loaded = json.loads(
        subprocess.run([sys.executable, "-c", probe], env=env, check=True, capture_output=True, text=True).stdout
    )
    forbidden_prefixes = (
        "googleapiclient", "google.auth", "google_auth_oauthlib", "httplib2", "requests",
        "instructional_materials_coach.drive_client", "instructional_materials_coach.workspace_clients",
        "instructional_materials_coach.live_build", "instructional_materials_coach.placement_transport",
        "instructional_materials_coach.cli",
    )
    assert not [name for name in loaded if name.startswith(forbidden_prefixes)]


# ---------------------------------------------------------------------------
# #3584 repair regressions: the 12 QA defects fail closed, invariants hold
# ---------------------------------------------------------------------------


def test_scalar_worksheet_questions_are_malformed_input_not_characters() -> None:
    """Defect 1: ``worksheet_questions: "Why?"`` must not preview as W/h/y/?."""
    with pytest.raises(ValueError, match="worksheet_questions"):
        _authored(worksheet_questions="Why?")
    with pytest.raises(ValueError, match="objectives"):
        _authored(objectives="Why?")
    with pytest.raises(ValueError, match="slides"):
        _authored(slides="Why?")


def test_scalar_authored_fields_reject_at_the_adapter() -> None:
    """Scalar fields built outside the YAML parser still fail closed."""
    from instructional_materials_coach.content_spec import LessonContent

    content = LessonContent(
        title="T",
        objectives=[],
        slides=[{"index": 1, "heading": "H"}],
        worksheet_questions="Why?",  # type: ignore[arg-type]
        lesson_identity={"day_lesson_number": "Day 1"},
    )
    _reject("authored-content-missing", content=content)


@pytest.mark.parametrize("logical_source", [{"source": "x"}, ["daily-generation-packet"], 7, None])
def test_unhashable_or_nonstr_logical_source_fails_closed(logical_source) -> None:
    """Defect 2: no uncaught TypeError from the admitted-source membership test."""
    evidence = _evidence()
    evidence["result"]["source"]["logical_source"] = logical_source
    _reject("source-unknown", evidence=evidence)


@pytest.mark.parametrize("target", ["​", "‌‍﻿", "  ​  "])
def test_invisible_zero_width_learning_target_rejects(target) -> None:
    """Defect 3: zero-width/format-only text is not a learning target."""
    evidence = _evidence()
    _lesson(evidence["result"], "Day 1")["daily_learning_target"] = target
    _reject("lesson-malformed", evidence=evidence)


def test_zero_width_selection_values_reject() -> None:
    evidence = _evidence()
    with pytest.raises(LessonContentResultError) as caught:
        verify_lesson_content_result(
            _result(), dataclasses.replace(SELECTION, day_lesson_number="​")
        )
    assert caught.value.reason_code == "selection-malformed"


def test_extra_admission_key_rejects() -> None:
    """Defect 4: the admission object is exact-keyed; drift is refused."""
    evidence = _evidence()
    evidence["admission"]["unexpected_key"] = "drift"
    _reject("result-unexpected-key", evidence=evidence)


def test_missing_admission_key_rejects() -> None:
    evidence = _evidence()
    del evidence["admission"]["status"]
    _reject("result-malformed", evidence=evidence)


def test_gce_required_true_in_admission_rejects() -> None:
    """Defect 4: ``gce_required=True`` is not an admitted lesson-content read."""
    evidence = _evidence()
    evidence["admission"]["gce_required"] = True
    _reject("authority-not-fail-closed", evidence=evidence)


@pytest.mark.parametrize("flag", ["write_allowed", "production_authorized", "notion_write_reachable"])
def test_true_admission_flag_rejects(flag) -> None:
    evidence = _evidence()
    evidence["admission"][flag] = True
    _reject("authority-not-fail-closed", evidence=evidence)


def test_admission_for_another_request_class_rejects() -> None:
    evidence = _evidence()
    evidence["admission"]["request_class"] = "source-schema"
    _reject("result-class-mismatch", evidence=evidence)


@pytest.mark.parametrize("version", ["2.0", "0.9", None])
def test_envelope_schema_drift_rejects(version) -> None:
    """Defect 5: the runner envelope's schema_version is pinned to 1.0."""
    evidence = _evidence()
    evidence["schema_version"] = version
    _reject("result-class-mismatch", evidence=evidence)


def test_envelope_admission_schema_drift_rejects() -> None:
    evidence = _evidence()
    evidence["admission"]["schema_version"] = "2.0"
    _reject("result-class-mismatch", evidence=evidence)


@pytest.mark.parametrize("key", ["dispatch_status", "dispatch_reason", "result", "generated_at"])
def test_envelope_missing_key_rejects(key) -> None:
    evidence = _evidence()
    del evidence[key]
    _reject("result-malformed", evidence=evidence)


def test_envelope_extra_key_rejects() -> None:
    evidence = _evidence()
    evidence["extra_envelope_key"] = "drift"
    _reject("result-unexpected-key", evidence=evidence)


@pytest.mark.parametrize("flag", ["notion_writes_performed", "drive_writes_performed",
                                  "classroom_artifact_writes_performed", "gce_invoked"])
def test_true_envelope_write_flag_rejects(flag) -> None:
    evidence = _evidence()
    evidence[flag] = True
    _reject("authority-not-fail-closed", evidence=evidence)


def test_wrong_dispatch_reason_rejects() -> None:
    evidence = _evidence()
    evidence["dispatch_reason"] = "bounded-read-projected"
    _reject("dispatch-not-completed", evidence=evidence)


@pytest.mark.parametrize("display_name", ["Evil Source", "", "   ", None, 7, "daily generation packet"])
def test_invalid_source_display_name_rejects(display_name) -> None:
    """Defect 6: the display name is pinned to the catalog's admitted source."""
    evidence = _evidence()
    evidence["result"]["source"]["display_name"] = display_name
    _reject("source-unknown", evidence=evidence)


def test_source_extra_key_rejects() -> None:
    evidence = _evidence()
    evidence["result"]["source"]["data_source_id"] = "64ec8493-ece7-41d4-b130-c48cc01742c0"
    _reject("result-unexpected-key", evidence=evidence)


@pytest.mark.parametrize("variant", ["day 1", "Day  1", "DAY 1", " Day 1 "])
def test_case_or_whitespace_variant_lesson_identity_is_ambiguous(variant) -> None:
    """Defect 7: near-duplicate lesson identities never silently resolve."""
    evidence = _evidence()
    duplicate = copy.deepcopy(_lesson(evidence["result"], "Day 1"))
    duplicate["day_lesson_number"] = variant
    duplicate["record_url"] = DAY1_URL + "?variant=1"
    evidence["result"]["lessons"].append(duplicate)
    _reject("lesson-identity-ambiguous", evidence=evidence)


def test_empty_objectives_without_identity_binding_reject() -> None:
    """Defect 8: no silent Notion-target adoption without an authored binding."""
    content = content_from_dict(
        {
            "title": "Fixture lesson title",
            "objectives": [],
            "slides": [{"index": 1, "heading": "H"}],
            "worksheet_questions": ["Q?"],
        }
    )
    _reject("authored-identity-missing", content=content)


def test_empty_objectives_with_mismatched_identity_binding_reject() -> None:
    _reject(
        "authored-identity-missing",
        content=_authored(lesson_identity={"day_lesson_number": "Day 2"}),
    )


def test_title_naming_the_lesson_is_not_an_identity_binding() -> None:
    """The title is not canonical identity and never satisfies the binding."""
    content = content_from_dict(
        {
            "title": "Day 1 candy branding lesson",
            "objectives": [],
            "slides": [{"index": 1, "heading": "H"}],
            "worksheet_questions": ["Q?"],
        }
    )
    _reject("authored-identity-missing", content=content)


def test_empty_objectives_with_matching_identity_binding_fill() -> None:
    """The bound fill still adopts the verified target and focus."""
    composed = compose_lesson_content_result(_authored(), _evidence(), SELECTION)
    assert composed.objectives == [DAY1_TARGET, DAY1_FOCUS]
    assert composed.placeholder_tokens()[TOKEN_OBJECTIVE_SOURCE] == "governed-lesson-content"


def test_malformed_lesson_identity_yaml_rejects() -> None:
    with pytest.raises(ValueError, match="lesson_identity"):
        _authored(lesson_identity={"day_lesson_number": "Day 1", "extra": "x"})
    with pytest.raises(ValueError, match="lesson_identity"):
        _authored(lesson_identity={"day_lesson_number": "   "})
    with pytest.raises(ValueError, match="lesson_identity"):
        _authored(lesson_identity="Day 1")


def test_whitespace_only_optional_source_fields_are_absent() -> None:
    """Defect 9: whitespace-only optional fields no longer reject the record."""
    evidence = _evidence()
    _lesson(evidence["result"], "Day 1")["daily_focus"] = "   "
    composed = compose_lesson_content_result(_authored(), evidence, SELECTION)
    tokens = composed.placeholder_tokens()
    assert TOKEN_FOCUS not in tokens
    assert composed.objectives == [DAY1_TARGET]


@pytest.mark.parametrize(
    "slides",
    [
        ["not-a-mapping"],
        [{"heading": "missing index"}],
        [{"index": None, "heading": "H"}],
        [{"index": True, "heading": "H"}],
        [{"index": 1, "heading": "H", "bullets": "not-a-list"}],
        [{"index": 1, "heading": "H", "bullets": ["ok", 7]}],
        [{"index": 1, "heading": 7}],
    ],
)
def test_malformed_authored_slide_structures_fail_closed(slides) -> None:
    """Defect 10: malformed slides raise a closed reason, never TypeError."""
    from instructional_materials_coach.content_spec import LessonContent

    content = LessonContent(
        title="T",
        objectives=[],
        slides=slides,
        worksheet_questions=["Q?"],
        lesson_identity={"day_lesson_number": "Day 1"},
    )
    _reject("authored-content-missing", content=content)


@pytest.mark.parametrize(
    "slides",
    [
        ["not-a-mapping"],
        [{"heading": "missing index"}],
        [{"index": 1, "bullets": "not-a-list"}],
    ],
)
def test_malformed_slide_yaml_is_malformed_input(slides) -> None:
    with pytest.raises(ValueError, match="slide"):
        _authored(slides=slides)


def _nested(depth: int) -> dict:
    root: dict = {}
    current = root
    for _ in range(depth):
        child: dict = {}
        current["k"] = child
        current = child
    return root


def test_deeply_nested_evidence_fails_closed() -> None:
    """Defect 11: deep nesting is refused as malformed, not RecursionError."""
    evidence = _evidence()
    evidence["result"]["lessons"][0]["daily_focus"] = _nested(5000)
    _reject("result-malformed", evidence=evidence)


def test_deeply_nested_credential_branch_fails_closed() -> None:
    evidence = _evidence()
    evidence["admission"]["reason_codes"] = [_nested(5000)]
    _reject("result-malformed", evidence=evidence)


@pytest.mark.parametrize("field", ["daily_learning_target", "daily_focus", "source_evidence"])
def test_unresolved_placeholder_in_governed_text_rejects_at_adapter(field) -> None:
    """Defect 12: ``{{placeholder}}`` in governed text fails at the adapter."""
    evidence = _evidence()
    _lesson(evidence["result"], "Day 1")[field] = "Governed {{unresolved}} text."
    _reject("lesson-malformed", content=_authored(objectives=[DAY1_TARGET]), evidence=evidence)


def test_unresolved_placeholder_in_day_lesson_number_rejects() -> None:
    evidence = _evidence()
    _lesson(evidence["result"], "Day 1")["day_lesson_number"] = "Day {{1}}"
    selection = dataclasses.replace(SELECTION, day_lesson_number="Day {{1}}")
    _reject(
        "lesson-malformed",
        content=_authored(objectives=[DAY1_TARGET]),
        evidence=evidence,
        selection=selection,
    )


def test_repository_mismatch_rejects() -> None:
    evidence = _evidence()
    evidence["result"]["repository"] = "Blummer92/other-repo"
    evidence["admission"]["repository"] = "Blummer92/other-repo"
    _reject("repository-mismatch", evidence=evidence)


def test_authority_extra_key_rejects() -> None:
    evidence = _evidence()
    evidence["result"]["authority"]["superuser_authorized"] = False
    _reject("result-unexpected-key", evidence=evidence)


def test_non_boolean_authority_value_rejects() -> None:
    evidence = _evidence()
    evidence["result"]["authority"]["write_allowed"] = "false"
    _reject("authority-not-fail-closed", evidence=evidence)


def test_result_missing_key_rejects() -> None:
    evidence = _evidence()
    del evidence["result"]["authority"]
    _reject("result-malformed", evidence=evidence)


def test_malformed_issue_number_rejects() -> None:
    evidence = _evidence()
    evidence["result"]["issue_number"] = "3580"
    evidence["admission"]["issue_number"] = "3580"
    _reject("result-malformed", evidence=evidence)
    evidence = _evidence()
    evidence["result"]["issue_number"] = 0
    evidence["admission"]["issue_number"] = 0
    _reject("result-malformed", evidence=evidence)


def test_admission_result_provenance_triple_must_agree() -> None:
    for key in ("request_id", "repository", "issue_number"):
        evidence = _evidence()
        evidence["admission"][key] = "tampered"
        _reject("provenance-mismatch", evidence=evidence)

