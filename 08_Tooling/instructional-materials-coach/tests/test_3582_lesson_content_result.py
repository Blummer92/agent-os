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


@pytest.mark.parametrize("value", ["", "   ", 7, ["hue"]])
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
