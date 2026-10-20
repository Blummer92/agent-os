"""#3582: the IMC lesson-content adapter consumes the real #3580 producer contract.

The Materials Coach adapter never imports the GitHub-side Notion read package.
This root test is the cross-package guard: it pins the adapter's copy of the
published lesson-content contract to the producer's own constants, and runs
the real governed runner (admission -> execution -> projection) with a fake
#936 executor into the adapter, proving Day 1 identity, objective, focus,
and provenance reach the Coach while foreign-unit records never do.
"""
from __future__ import annotations

import copy

import pytest

from instructional_materials_coach import lesson_content_result as adapter
from instructional_materials_coach.content_spec import content_from_dict
from instructional_materials_coach.lesson_content_result import (
    LessonContentResultError,
    LessonContentSelection,
    compose_lesson_content_result,
)
from navigation_registry.connectors.curriculum_evidence_orchestrator import MAX_RESULTS
from scripts.agent_os_notion_read_request import NotionReadRequestError, models, projection
from scripts.agent_os_notion_read_request.catalog import load_catalog
from scripts.agent_os_notion_read_request.runner import (
    DISPATCH_COMPLETED,
    run_notion_read_request,
)
from tests.agent_os_notion_read_request.notion_read_support import (
    ACTOR,
    GENERATED_AT,
    REPOSITORY,
    transport,
)

REQUEST_ID = "candy-branding-lesson-content"
UNIT_PAGE_ID = "3907ac78-3131-8132-8f84-f9fd633acba5"
DATA_SOURCE_ID = "64ec8493-ece7-41d4-b130-c48cc01742c0"
DAY1_TARGET = "I can choose colors on purpose and explain how they match the candy mood and audience."
DAY1_FOCUS = "Plan intentional candy color choices before software use."
DAY1_EVIDENCE = "Candy Brand Design source says Day 1 establishes intentional color planning before software use."
SELECTION = LessonContentSelection(
    request_id=REQUEST_ID,
    canonical_unit_page_id=UNIT_PAGE_ID,
    day_lesson_number="Day 1",
    generated_at=GENERATED_AT,
)


def _text(value):
    return {"id": "p", "type": "rich_text", "rich_text": [{"plain_text": value}] if value else []}


def _record(page_id, day, target, focus, unit=UNIT_PAGE_ID):
    return {
        "id": page_id,
        "url": f"https://app.notion.com/p/{page_id.replace('-', '')}",
        "properties": {
            "Daily Learning Target": _text(target),
            "Daily Focus": _text(focus),
            "Key Vocabulary": _text(""),
            "Canonical Unit": {"id": "r", "type": "relation", "relation": [{"id": unit}]},
            "Source Evidence": _text(DAY1_EVIDENCE),
            "Day / Lesson Number": _text(day),
            "Agent Prompt to Run Next": _text("internal planning text"),
        },
    }


class _Executor:
    def __init__(self, records):
        self._records = records

    def factory(self):
        return self.execute

    def execute(self, payload):
        assert payload["action"] == "query_data_source"
        assert payload["data_source_id"] == DATA_SOURCE_ID
        return {
            "status": "success",
            "output": {"results": copy.deepcopy(self._records), "has_more": False, "next_cursor": None},
        }


def _run(records):
    return run_notion_read_request(
        transport(request_id=REQUEST_ID, issue_number=3580),
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
        generated_at=GENERATED_AT,
        catalog=load_catalog(),
        scheduler_task_executor_factory=_Executor(records).factory,
    )


def _authored():
    return content_from_dict(
        {
            "title": "Fixture lesson title",
            "objectives": [],
            "lesson_identity": {"day_lesson_number": "Day 1"},
            "slides": [{"index": 1, "heading": "Fixture heading", "bullets": ["Fixture bullet"]}],
            "worksheet_questions": ["Fixture question?"],
        }
    )


def test_adapter_contract_constants_match_the_producer() -> None:
    assert adapter.RESULT_KIND == projection.RESULT_KIND_LESSON_CONTENT
    assert adapter.SCHEMA_VERSION == models.SCHEMA_VERSION
    assert adapter.REQUEST_CLASS in models.REQUEST_CLASSES
    assert adapter.VERIFIED_STATE == models.VERIFIED_STATE
    assert adapter.CREDENTIAL_KEY_FRAGMENTS == models.CREDENTIAL_KEY_FRAGMENTS
    assert adapter.LESSON_KEYS == frozenset(projection._LESSON_RESULT_KEYS)
    assert adapter.MAX_LESSONS == MAX_RESULTS
    assert adapter.DISPATCH_COMPLETED == DISPATCH_COMPLETED
    lesson_sources = {
        source.logical_source
        for source in load_catalog().sources
        if source.content_class == "lesson-content"
    }
    assert adapter.ADMITTED_LOGICAL_SOURCES == lesson_sources
    # The admitted display names are pinned to the catalog, and the
    # admission shape to the producer's own admission record.
    assert adapter.ADMITTED_SOURCE_DISPLAY_NAMES == {
        source.logical_source: source.display_name
        for source in load_catalog().sources
        if source.content_class == "lesson-content"
    }
    assert set(models.NotionReadAdmission(
        status="admitted",
        reason_codes=("admitted",),
        repository=REPOSITORY,
    ).to_dict()) == adapter.ADMISSION_KEYS


def test_real_runner_output_reaches_the_coach() -> None:
    evidence = _run(
        [
            _record("3717ac78-3131-8135-ae7c-f2ead0cf28ac", "Day 1", DAY1_TARGET, DAY1_FOCUS),
            _record("3717ac78-3131-81bf-a296-c3a6fb32a22d", "Day 2", "Fixture day 2 target.", "Fixture day 2 focus."),
        ]
    )
    assert evidence["dispatch_status"] == "completed"
    # The producer's exact top-level and authority shapes are what the adapter pins.
    assert set(evidence) == adapter.ENVELOPE_KEYS
    assert set(evidence["result"]) == adapter.RESULT_KEYS
    assert set(evidence["result"]["authority"]) == adapter.AUTHORITY_KEYS
    assert set(evidence["result"]["source"]) == adapter.SOURCE_KEYS
    assert set(evidence["admission"]) == adapter.ADMISSION_KEYS

    composed = compose_lesson_content_result(_authored(), evidence, SELECTION)
    tokens = composed.placeholder_tokens()
    assert tokens["context_lesson_learning_target"] == DAY1_TARGET
    assert tokens["context_lesson_daily_focus"] == DAY1_FOCUS
    assert tokens["context_lesson_day_lesson_number"] == "Day 1"
    assert tokens["context_lesson_canonical_unit_page_id"] == UNIT_PAGE_ID
    assert tokens["context_lesson_generated_at"] == GENERATED_AT
    assert "context_lesson_key_vocabulary" not in tokens
    assert "internal planning text" not in tokens.values()
    assert composed.worksheet_questions == ["Fixture question?"]


def test_foreign_unit_records_never_reach_the_coach() -> None:
    foreign = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    records = [_record("3717ac78-3131-8135-ae7c-f2ead0cf28ac", "Day 1", DAY1_TARGET, DAY1_FOCUS, unit=foreign)]
    # The producer refuses to publish them; a tampered result is refused here too.
    with pytest.raises(NotionReadRequestError, match="different canonical unit"):
        _run(records)
    evidence = _run([_record("3717ac78-3131-8135-ae7c-f2ead0cf28ac", "Day 1", DAY1_TARGET, DAY1_FOCUS)])
    evidence["result"]["lessons"][0]["canonical_unit"]["page_id"] = foreign
    with pytest.raises(LessonContentResultError) as caught:
        compose_lesson_content_result(_authored(), evidence, SELECTION)
    assert caught.value.reason_code == "unit-mismatch"


def test_blocked_producer_evidence_is_not_consumable() -> None:
    evidence = run_notion_read_request(
        transport(request_id=REQUEST_ID, issue_number=9999),
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
        generated_at=GENERATED_AT,
        catalog=load_catalog(),
        scheduler_task_executor_factory=_Executor([]).factory,
    )
    assert evidence["dispatch_status"] == "blocked"
    with pytest.raises(LessonContentResultError) as caught:
        compose_lesson_content_result(_authored(), evidence, SELECTION)
    assert caught.value.reason_code == "dispatch-not-completed"

