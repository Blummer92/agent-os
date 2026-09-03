"""Bounded live Lessons Learned activation bridge for CKR6 (#1516 / CKR11).

This module is the runtime seam between already-resolved
``CodingKnowledgeRequest`` signals and the existing CKR6
``consume_lesson_preflight`` contract. It performs no Notion network access
itself: the caller injects a bounded read executor that must reuse the
existing read-only Notion query path (``NotionReadOnlyAdapter.query_data_source``
via the Workflow Scheduler, or an equivalent already-approved read surface).

Ordering matches CKR6/CKR2 exactly: ``not-needed`` performs zero reads; a
known lesson reference is attempted before a bounded filtered query; the
filtered query never asks for more than ``MAX_LESSON_RECORDS`` rows before
normalization. Live Notion row shapes are mapped through a finite,
deterministic vocabulary; anything missing or ambiguous is excluded as
explicitly non-ready rather than guessed. The shared CKR2 candidate-owned
provenance invariant (#1520) is reused unchanged -- this module adds no
duplicate provenance guard.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .coding_knowledge_selection import CodingKnowledgeRequest, KnowledgeCurrentness, RetrievalEscalation
from .lesson_preflight import (
    MAX_LESSON_RECORDS,
    LessonPreflightResult,
    LessonRecordEvidence,
    consume_lesson_preflight,
    plan_lesson_preflight,
)

MAX_ROW_TEXT_CHARS = 512
MAX_ROW_LIST_ITEMS = 20

_LESSON_ID_PROPERTY = "Lesson ID"
_TITLE_PROPERTY = "Lesson Learned"
_STATUS_PROPERTY = "Status"
_SURFACE_PROPERTY = "Surface Before Work?"
_AREA_PROPERTY = "Area"
_APPLIES_TO_PROPERTY = "Applies To"
_LEARNING_TYPE_PROPERTY = "Learning Type"
_SOURCE_LINK_PROPERTY = "Source Link"
_GUARDRAIL_PROPERTY = "Guardrail"
_NEXT_TIME_PROPERTY = "What To Do Next Time"

REQUIRED_LESSON_PROPERTIES = (
    _LESSON_ID_PROPERTY,
    _TITLE_PROPERTY,
    _STATUS_PROPERTY,
    _SURFACE_PROPERTY,
    _AREA_PROPERTY,
    _APPLIES_TO_PROPERTY,
    _LEARNING_TYPE_PROPERTY,
    _SOURCE_LINK_PROPERTY,
    _GUARDRAIL_PROPERTY,
    _NEXT_TIME_PROPERTY,
)

# Live finite Status vocabulary (#1516 point 4 / notion-learning-databases.md).
_STATUS_VOCABULARY = frozenset({"New", "Applied", "Needs follow-up", "Archived note"})

# Finite deterministic Area -> ecosystem mapping. Anything outside this map
# fails closed as ambiguous activation vocabulary rather than being guessed.
_AREA_ECOSYSTEM: dict[str, str] = {
    "Curriculum": "agent-os",
    "Automation": "python",
    "Dashboard": "python",
    "Governance": "agent-os",
    "Documentation": "agent-os",
    "Testing": "python",
}

# Finite deterministic Learning Type -> capability_kind mapping.
_LEARNING_TYPE_CAPABILITY: dict[str, str] = {
    "Mistake": "failure-avoidance",
    "QA feedback": "quality-assurance",
    "Testing lesson": "testing",
    "Deployment lesson": "deployment",
    "Scope/permission lesson": "authorization-routing",
    "Trigger lesson": "scheduling",
}


class LessonActivationError(ValueError):
    """Bounded orchestration-boundary error. Never used to fabricate evidence."""


@dataclass(frozen=True, slots=True)
class LessonActivationSkip:
    """One explicitly non-ready live row and the fail-closed reason."""

    lesson_id: str | None
    reason: str


ReadExecutor = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def build_known_reference_query(known_ids: Sequence[str]) -> dict[str, Any]:
    """Smallest bounded query for an explicit known lesson identity lookup."""
    ids = [value for value in dict.fromkeys(known_ids) if value][:MAX_LESSON_RECORDS]
    if not ids:
        raise LessonActivationError("known_ids must contain at least one non-empty value")
    return {
        "page_size": MAX_LESSON_RECORDS,
        "filter_properties": list(REQUIRED_LESSON_PROPERTIES),
        "filter": {
            "or": [
                {"property": _LESSON_ID_PROPERTY, "rich_text": {"equals": value}}
                for value in ids
            ]
        },
    }


def build_filtered_query(request: CodingKnowledgeRequest) -> dict[str, Any]:
    """Smallest bounded ordinary filtered query, capped at the CKR6 budget."""
    if type(request) is not CodingKnowledgeRequest:
        raise TypeError("request must be a CodingKnowledgeRequest")
    return {
        "page_size": MAX_LESSON_RECORDS,
        "filter_properties": list(REQUIRED_LESSON_PROPERTIES),
        "filter": {
            "and": [
                {"property": _SURFACE_PROPERTY, "checkbox": {"equals": True}},
                {
                    "property": _STATUS_PROPERTY,
                    "status": {"does_not_equal": "Archived note"},
                },
            ]
        },
    }


def normalize_lesson_row(row: Mapping[str, Any]) -> LessonRecordEvidence | LessonActivationSkip:
    """Deterministically map one bounded live row, or fail closed as non-ready.

    Consumes only the finite set of controlled properties this module knows
    about. No raw page body, unknown property, or unbounded collection is
    read into the result; anything missing or ambiguous yields an explicit
    ``LessonActivationSkip`` rather than an invented value.
    """
    if not isinstance(row, Mapping):
        return LessonActivationSkip(None, "malformed-row")
    if row.get("object") not in (None, "page"):
        return LessonActivationSkip(None, "malformed-row")

    properties = row.get("properties")
    if not isinstance(properties, Mapping):
        return LessonActivationSkip(None, "missing-properties")

    lesson_id = _rich_text_or_unique_id(properties.get(_LESSON_ID_PROPERTY))
    if lesson_id is None:
        return LessonActivationSkip(None, "missing-stable-identity")

    source_revision = row.get("last_edited_time")
    if not isinstance(source_revision, str) or not source_revision.strip():
        return LessonActivationSkip(lesson_id, "missing-verified-revision")

    title = _title_text(properties.get(_TITLE_PROPERTY))
    if title is None:
        return LessonActivationSkip(lesson_id, "missing-title")

    status = _select_name(properties.get(_STATUS_PROPERTY))
    if status is None or status not in _STATUS_VOCABULARY:
        return LessonActivationSkip(lesson_id, "ambiguous-status-vocabulary")

    surface_before_work = _checkbox(properties.get(_SURFACE_PROPERTY))
    if surface_before_work is None:
        return LessonActivationSkip(lesson_id, "ambiguous-surface-flag")

    area = _select_name(properties.get(_AREA_PROPERTY))
    ecosystem = _AREA_ECOSYSTEM.get(area) if area is not None else None
    if ecosystem is None:
        return LessonActivationSkip(lesson_id, "ambiguous-area-vocabulary")

    learning_type = _select_name(properties.get(_LEARNING_TYPE_PROPERTY))
    capability_kind = (
        _LEARNING_TYPE_CAPABILITY.get(learning_type) if learning_type is not None else None
    )
    if capability_kind is None:
        return LessonActivationSkip(lesson_id, "ambiguous-learning-type-vocabulary")

    guardrail = _rich_text(properties.get(_GUARDRAIL_PROPERTY))
    what_to_do_next_time = _rich_text(properties.get(_NEXT_TIME_PROPERTY))
    if guardrail is None or what_to_do_next_time is None:
        return LessonActivationSkip(lesson_id, "missing-activation-guidance")

    applies_to = _multi_select_names(properties.get(_APPLIES_TO_PROPERTY))
    if applies_to is None:
        return LessonActivationSkip(lesson_id, "ambiguous-applies-to-vocabulary")

    canonical_ref = _github_source_link(properties.get(_SOURCE_LINK_PROPERTY))
    currentness = KnowledgeCurrentness.CURRENT if canonical_ref else KnowledgeCurrentness.UNVERIFIABLE
    canonical_github_refs = (canonical_ref,) if canonical_ref else ()

    evidence_refs: tuple[str, ...] = ()
    page_url = row.get("url")
    if isinstance(page_url, str) and page_url.strip():
        evidence_refs = (page_url.strip()[:MAX_ROW_TEXT_CHARS],)

    try:
        return LessonRecordEvidence(
            lesson_id=lesson_id,
            source_revision=source_revision,
            title=title,
            ecosystem=ecosystem,
            capability_kind=capability_kind,
            status=status,
            surface_before_work=surface_before_work,
            currentness=currentness,
            what_to_do_next_time=what_to_do_next_time,
            guardrail=guardrail,
            canonical_github_refs=canonical_github_refs,
            evidence_refs=evidence_refs,
            keywords=applies_to,
            archived=status == "Archived note",
        )
    except (TypeError, ValueError):
        return LessonActivationSkip(lesson_id, "oversized-or-malformed-field")


def orchestrate_lesson_activation(
    request: CodingKnowledgeRequest,
    *,
    execute_read: ReadExecutor | None,
) -> LessonPreflightResult:
    """Plan, bound, execute, and normalize one live Lessons Learned retrieval.

    ``execute_read`` must already be bound to the canonical Lessons Learned
    data source through the existing read-only Notion adapter; this function
    never constructs a client, credential, or second retrieval mechanism.
    """
    if type(request) is not CodingKnowledgeRequest:
        raise TypeError("request must be a CodingKnowledgeRequest")

    plan = plan_lesson_preflight(request)
    if not plan.retrieval_required:
        return consume_lesson_preflight(request, ())

    if execute_read is None:
        return consume_lesson_preflight(request, (), retrieval_available=False)

    if plan.recommended_escalation is RetrievalEscalation.KNOWN_REFERENCE and request.known_knowledge_refs:
        query = build_known_reference_query(request.known_knowledge_refs)
    else:
        query = build_filtered_query(request)

    raw = execute_read(query)
    rows = _extract_bounded_rows(raw)

    lessons: list[LessonRecordEvidence] = []
    for row in rows:
        normalized = normalize_lesson_row(row)
        if isinstance(normalized, LessonRecordEvidence):
            lessons.append(normalized)

    return consume_lesson_preflight(request, tuple(lessons))


def _extract_bounded_rows(raw: Any) -> list[Mapping[str, Any]]:
    if not isinstance(raw, Mapping):
        raise LessonActivationError("read executor must return a mapping")
    results = raw.get("results")
    if not isinstance(results, list):
        raise LessonActivationError("read executor result is missing 'results'")
    if len(results) > MAX_LESSON_RECORDS:
        raise LessonActivationError("read executor returned more than the CKR6 candidate budget")
    return [item for item in results if isinstance(item, Mapping)][:MAX_LESSON_RECORDS]


def _plain_text(rich_text: Any) -> str | None:
    if not isinstance(rich_text, list) or len(rich_text) > MAX_ROW_LIST_ITEMS:
        return None
    parts: list[str] = []
    for item in rich_text:
        if not isinstance(item, Mapping):
            return None
        text = item.get("plain_text")
        if not isinstance(text, str):
            return None
        parts.append(text)
    joined = "".join(parts).strip()
    if not joined or len(joined) > MAX_ROW_TEXT_CHARS:
        return None
    return joined


def _title_text(prop: Any) -> str | None:
    if not isinstance(prop, Mapping) or prop.get("type") != "title":
        return None
    return _plain_text(prop.get("title"))


def _rich_text(prop: Any) -> str | None:
    if not isinstance(prop, Mapping) or prop.get("type") != "rich_text":
        return None
    return _plain_text(prop.get("rich_text"))


def _rich_text_or_unique_id(prop: Any) -> str | None:
    if not isinstance(prop, Mapping):
        return None
    prop_type = prop.get("type")
    if prop_type == "rich_text":
        return _plain_text(prop.get("rich_text"))
    if prop_type == "title":
        return _plain_text(prop.get("title"))
    if prop_type == "unique_id":
        value = prop.get("unique_id")
        if not isinstance(value, Mapping):
            return None
        number = value.get("number")
        if not isinstance(number, int) or isinstance(number, bool):
            return None
        prefix = value.get("prefix")
        prefix_text = prefix if isinstance(prefix, str) and prefix else "lesson"
        return f"{prefix_text}-{number}"
    return None


def _select_name(prop: Any) -> str | None:
    if not isinstance(prop, Mapping) or prop.get("type") not in ("select", "status"):
        return None
    value = prop.get(prop["type"])
    if not isinstance(value, Mapping):
        return None
    name = value.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_ROW_TEXT_CHARS:
        return None
    return name


def _multi_select_names(prop: Any) -> tuple[str, ...] | None:
    if not isinstance(prop, Mapping) or prop.get("type") != "multi_select":
        return None
    values = prop.get("multi_select")
    if not isinstance(values, list) or len(values) > MAX_ROW_LIST_ITEMS:
        return None
    names: list[str] = []
    for item in values:
        if not isinstance(item, Mapping):
            return None
        name = item.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > MAX_ROW_TEXT_CHARS:
            return None
        names.append(name)
    return tuple(names)


def _checkbox(prop: Any) -> bool | None:
    if not isinstance(prop, Mapping) or prop.get("type") != "checkbox":
        return None
    value = prop.get("checkbox")
    if type(value) is not bool:
        return None
    return value


def _github_source_link(prop: Any) -> str | None:
    if not isinstance(prop, Mapping) or prop.get("type") != "url":
        return None
    value = prop.get("url")
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if len(value) > MAX_ROW_TEXT_CHARS:
        return None
    if not (
        value.startswith("https://github.com/")
        or value.startswith("00_Governance/")
        or value.startswith("01_Shared_Standards/")
        or value.startswith("02_Agent_Overlays/")
        or value.startswith("04_Registry/")
        or value.startswith("08_Tooling/")
    ):
        return None
    return value
