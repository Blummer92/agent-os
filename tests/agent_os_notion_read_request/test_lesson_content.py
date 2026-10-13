"""Focused tests for the Tier-2 Slice 1 lesson-content class (#3580).

The lesson-content class is record-driven (like source-schema): admission binds
exactly one catalog-declared logical source, execution runs one
``query_data_source`` step, and the projection emits exactly the 7 governed
lesson fields with provenance. The Daily Generation Packet Dashboard source is
verified-current; an unverified source fails closed. ``Key Vocabulary`` is
empty on all sampled lessons and is emitted as absent, never invented. The
existing governed reader, route, and authorization are reused unchanged.
"""

from __future__ import annotations

import copy

import pytest

from scripts.agent_os_notion_read_request import (
    NotionReadRequestError,
    admit_notion_read_request,
    parse_catalog,
)
from scripts.agent_os_notion_read_request.execution import execute_lesson_content
from scripts.agent_os_notion_read_request.projection import (
    RESULT_KIND_LESSON_CONTENT,
    project_lesson_content_result,
    reject_credential_keys,
)
from scripts.agent_os_notion_read_request.runner import run_notion_read_request

from .notion_read_support import (
    ACTOR,
    GENERATED_AT,
    REPOSITORY,
    transport,
    verified_payload,
)

ISSUE = 3580
LESSON_REQUEST = "candy-branding-lesson-content"
DATA_SOURCE_ID = "64ec8493-ece7-41d4-b130-c48cc01742c0"
UNIT_PAGE_ID = "3907ac78-3131-8132-8f84-f9fd633acba5"

EXPECTED_PAYLOAD_KEYS = {
    "schema_version",
    "result_kind",
    "repository",
    "issue_number",
    "request_id",
    "request_class",
    "source",
    "lessons",
    "authority",
    "generated_at",
}
EXPECTED_SOURCE_KEYS = {
    "logical_source",
    "display_name",
    "verification_state",
    "access",
}
EXPECTED_LESSON_KEYS = {
    "daily_learning_target",
    "daily_focus",
    "key_vocabulary",
    "canonical_unit",
    "source_evidence",
    "day_lesson_number",
    "record_url",
}

# Day 1 values verified live 2026-10-13 via notion-cli (read-only).
DAY1_TARGET = (
    "I can choose colors on purpose and explain how they match "
    "the candy mood and audience."
)
DAY1_FOCUS = "Plan intentional candy color choices before software use."
DAY1_EVIDENCE = (
    "Candy Brand Design source says Day 1 establishes intentional color planning "
    "before software use and portfolio checklist includes candy concept plus "
    "labeled palettes."
)
DAY1_URL = "https://app.notion.com/p/3717ac7831318135ae7cf2ead0cf28ac"


def _rich_text(value):
    return {
        "id": "prop-text",
        "type": "rich_text",
        "rich_text": [{"plain_text": value}] if value else [],
    }


def _day1_record(**overrides):
    properties = {
        "Daily Learning Target": _rich_text(DAY1_TARGET),
        "Daily Focus": _rich_text(DAY1_FOCUS),
        # Key Vocabulary is empty on all sampled lessons (Days 1/2/5).
        "Key Vocabulary": _rich_text(""),
        "Canonical Unit": {
            "id": "prop-relation",
            "type": "relation",
            "relation": [{"id": UNIT_PAGE_ID}],
        },
        "Source Evidence": _rich_text(DAY1_EVIDENCE),
        "Day / Lesson Number": _rich_text("Day 1"),
        # Unlisted property: must be dropped by the projection.
        "Agent Prompt to Run Next": _rich_text("internal planning text"),
    }
    properties.update(overrides)
    return {
        "id": "3717ac78-3131-8135-ae7c-f2ead0cf28ac",
        "url": DAY1_URL,
        "properties": properties,
    }


@pytest.fixture
def lesson_catalog(shipped_catalog):
    """The repository-owned catalog with the #3580 records (source verified)."""
    return shipped_catalog


def _admitted_lesson_decision(lesson_catalog, issue_number=ISSUE):
    return admit_notion_read_request(
        transport(request_id=LESSON_REQUEST, issue_number=issue_number),
        catalog=lesson_catalog,
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )


class LessonExecutor:
    """Fake #936 executor returning lesson records from the packet dashboard."""

    def __init__(self, records):
        self._records = records
        self.calls = []

    def factory(self):
        return self.execute

    def execute(self, payload):
        self.calls.append(copy.deepcopy(dict(payload)))
        assert payload["action"] == "query_data_source"
        assert payload["data_source_id"] == DATA_SOURCE_ID
        return {
            "status": "success",
            "output": {"results": copy.deepcopy(self._records)},
        }


def _project(lesson_catalog, records):
    decision = _admitted_lesson_decision(lesson_catalog)
    assert decision.status == "admitted"
    execution = execute_lesson_content(
        decision,
        catalog=lesson_catalog,
        scheduler_task_executor_factory=LessonExecutor(records).factory,
    )
    return project_lesson_content_result(
        decision,
        execution,
        catalog=lesson_catalog,
        generated_at=GENERATED_AT,
    )


# --------------------------------------------------------------------------
# Admission: verified source admits, unverified fails closed
# --------------------------------------------------------------------------


def test_verified_source_admits(lesson_catalog) -> None:
    decision = _admitted_lesson_decision(lesson_catalog)
    assert decision.status == "admitted"
    assert decision.reason_codes == ("admitted",)
    assert decision.secret_dispatch_authorized is True
    assert decision.request_class == "lesson-content"
    assert decision.required_logical_sources == ("daily-generation-packet",)
    assert decision.canonical_unit_key == "candy-branding"


def test_unverified_source_fails_closed(catalog_payload) -> None:
    payload = copy.deepcopy(catalog_payload)
    for source in payload["sources"]:
        if source["logical_source"] == "daily-generation-packet":
            source["data_source_id"] = None
            source["verification_state"] = "unverified"
    catalog = parse_catalog(payload)
    decision = admit_notion_read_request(
        transport(request_id=LESSON_REQUEST, issue_number=ISSUE),
        catalog=catalog,
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )
    assert decision.status == "rejected"
    assert decision.reason_codes == ("source-unverified",)
    assert decision.secret_dispatch_authorized is False


def test_unknown_logical_source_fails_closed(lesson_catalog) -> None:
    decision = admit_notion_read_request(
        transport(request_id="candy-branding-lesson-content", issue_number=ISSUE),
        catalog=lesson_catalog,
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )
    # Sanity: the real record admits; now prove an unbound source cannot.
    assert decision.status == "admitted"
    tampered = copy.deepcopy(lesson_catalog)
    assert tampered.source("no-such-source") is None


def test_issue_mismatch_rejected(lesson_catalog) -> None:
    decision = _admitted_lesson_decision(lesson_catalog, issue_number=9999)
    assert decision.status == "rejected"
    assert decision.secret_dispatch_authorized is False


# --------------------------------------------------------------------------
# Projection: exactly the 7 governed fields, vocabulary absent
# --------------------------------------------------------------------------


def test_projection_emits_exactly_seven_fields(lesson_catalog) -> None:
    result = _project(lesson_catalog, [_day1_record()])

    assert set(result.keys()) == EXPECTED_PAYLOAD_KEYS
    assert result["result_kind"] == RESULT_KIND_LESSON_CONTENT
    assert result["request_class"] == "lesson-content"
    assert set(result["source"].keys()) == EXPECTED_SOURCE_KEYS
    assert result["source"]["logical_source"] == "daily-generation-packet"
    assert result["source"]["verification_state"] == "verified-current"
    assert result["source"]["access"] == "read-only"

    (lesson,) = result["lessons"]
    assert set(lesson.keys()) == EXPECTED_LESSON_KEYS
    assert lesson["daily_learning_target"] == DAY1_TARGET
    assert lesson["daily_focus"] == DAY1_FOCUS
    assert lesson["source_evidence"] == DAY1_EVIDENCE
    assert lesson["day_lesson_number"] == "Day 1"
    assert lesson["canonical_unit"] == {"page_id": UNIT_PAGE_ID}
    assert lesson["record_url"] == DAY1_URL
    # The unlisted property never reaches the public surface.
    assert "Agent Prompt to Run Next" not in str(result["lessons"])
    assert "internal planning text" not in str(result["lessons"])
    reject_credential_keys(result, "result")


def test_empty_key_vocabulary_reads_as_absent(lesson_catalog) -> None:
    result = _project(lesson_catalog, [_day1_record()])
    (lesson,) = result["lessons"]
    # Present-but-empty: the key exists, the value is absent, nothing invented.
    assert "key_vocabulary" in lesson
    assert lesson["key_vocabulary"] is None


def test_missing_key_vocabulary_property_reads_as_absent(lesson_catalog) -> None:
    record = _day1_record()
    del record["properties"]["Key Vocabulary"]
    result = _project(lesson_catalog, [record])
    (lesson,) = result["lessons"]
    assert lesson["key_vocabulary"] is None


def test_compact_relation_id_normalized_to_dashed(lesson_catalog) -> None:
    record = _day1_record()
    record["properties"]["Canonical Unit"]["relation"] = [
        {"id": "3907ac78313181328f84f9fd633acba5"}
    ]
    result = _project(lesson_catalog, [record])
    (lesson,) = result["lessons"]
    assert lesson["canonical_unit"] == {"page_id": UNIT_PAGE_ID}


def test_ambiguous_canonical_unit_fails_closed(lesson_catalog) -> None:
    record = _day1_record()
    record["properties"]["Canonical Unit"]["relation"] = [
        {"id": UNIT_PAGE_ID},
        {"id": "3907ac78-3131-8129-8c73-cd9f6b8e8a7d"},
    ]
    with pytest.raises(NotionReadRequestError, match="ambiguous relations"):
        _project(lesson_catalog, [record])


def test_unrecognized_property_type_fails_closed(lesson_catalog) -> None:
    record = _day1_record(
        **{"Daily Focus": {"id": "x", "type": "people", "people": []}}
    )
    with pytest.raises(NotionReadRequestError, match="unrecognized type"):
        _project(lesson_catalog, [record])


def test_non_admitted_request_rejected_before_projection(lesson_catalog) -> None:
    decision = _admitted_lesson_decision(lesson_catalog, issue_number=9999)
    assert decision.status == "rejected"
    with pytest.raises(NotionReadRequestError):
        project_lesson_content_result(
            decision,
            {"records": [_day1_record()]},
            catalog=lesson_catalog,
            generated_at=GENERATED_AT,
        )


# --------------------------------------------------------------------------
# Unknown request class rejected; production behavior unchanged
# --------------------------------------------------------------------------


def test_unknown_request_class_rejected_at_catalog_load(catalog_payload) -> None:
    payload = copy.deepcopy(catalog_payload)
    payload["requests"].append(
        {
            "request_id": "bogus-request",
            "request_class": "not-a-real-class",
            "canonical_unit_key": "candy-branding",
            "issue_number": 3580,
        }
    )
    with pytest.raises(NotionReadRequestError, match="unknown request class"):
        parse_catalog(payload)


def test_lesson_content_without_logical_source_rejected(catalog_payload) -> None:
    payload = copy.deepcopy(catalog_payload)
    for record in payload["requests"]:
        if record["request_id"] == LESSON_REQUEST:
            del record["logical_source"]
    with pytest.raises(NotionReadRequestError):
        parse_catalog(payload)


def test_existing_request_classes_still_admit(lesson_catalog) -> None:
    # No production behavior change: the pre-existing finite vocabulary is
    # untouched by the lesson-content admission.
    decision = admit_notion_read_request(
        transport(
            request_id="candy-branding-visual-assets", issue_number=2816
        ),
        catalog=lesson_catalog,
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )
    assert decision.status == "admitted"
    assert "lesson-content" not in decision.required_logical_sources


# --------------------------------------------------------------------------
# End-to-end runner path uses the existing governed route
# --------------------------------------------------------------------------


def test_end_to_end_runner_path(lesson_catalog) -> None:
    evidence = run_notion_read_request(
        transport(request_id=LESSON_REQUEST, issue_number=ISSUE),
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
        generated_at=GENERATED_AT,
        catalog=lesson_catalog,
        scheduler_task_executor_factory=LessonExecutor([_day1_record()]).factory,
    )
    assert evidence["dispatch_status"] == "completed"
    assert evidence["dispatch_reason"] == "bounded-lesson-content-projected"
    assert evidence["notion_writes_performed"] is False
    (lesson,) = evidence["result"]["lessons"]
    assert set(lesson.keys()) == EXPECTED_LESSON_KEYS
    assert lesson["daily_learning_target"] == DAY1_TARGET
    assert lesson["key_vocabulary"] is None


def test_unauthorized_runner_path_projects_nothing(lesson_catalog) -> None:
    evidence = run_notion_read_request(
        transport(request_id=LESSON_REQUEST, issue_number=9999),
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
        generated_at=GENERATED_AT,
        catalog=lesson_catalog,
        scheduler_task_executor_factory=LessonExecutor([_day1_record()]).factory,
    )
    assert evidence["dispatch_status"] == "blocked"
    assert evidence["result"] is None
    assert "daily_learning_target" not in str(evidence).lower()
