import json
from pathlib import Path

import pytest

from agent_memory_context_manager.coding_knowledge_selection import (
    CodingKnowledgeRequest,
    RetrievalEscalation,
    SufficiencyStatus,
)
from agent_memory_context_manager.lesson_activation_accountability import (
    ACTIVATION_CLASSES,
    ACTIVATION_READINESS,
    LessonAccountabilityError,
    LessonActivationAccountability,
    allows_ordinary_signal_activation,
    compare_live_eligible_identities,
    load_lesson_accountability_catalog,
)
from agent_memory_context_manager.lesson_activation_bridge import (
    LessonActivationSkip,
    normalize_lesson_row,
)
from agent_memory_context_manager.lesson_preflight import (
    MAX_LESSON_RECORDS,
    consume_lesson_preflight,
    plan_lesson_preflight,
)


def _title(text):
    return {"type": "title", "title": [{"plain_text": text}]}


def _rich(text):
    return {"type": "rich_text", "rich_text": [{"plain_text": text}]}


def _status(value):
    return {"type": "status", "status": {"name": value}}


def _select(value):
    return {"type": "select", "select": {"name": value}}


def _multi(values):
    return {
        "type": "multi_select",
        "multi_select": [{"name": value} for value in values],
    }


def _checkbox(value):
    return {"type": "checkbox", "checkbox": value}


def _url(value):
    return {"type": "url", "url": value}


def _row(source_link="https://github.com/Blummer92/agent-os/issues/1517",
         applies_to=("Notion",)):
    return {
        "object": "page",
        "url": "https://notion.so/example",
        "last_edited_time": "2026-08-31T00:00:00.000Z",
        "properties": {
            "Lesson ID": {
                "type": "unique_id",
                "unique_id": {"prefix": "lesson", "number": 999},
            },
            "Lesson Learned": _title("Fixture lesson"),
            "Status": _status("Applied"),
            "Surface Before Work?": _checkbox(True),
            "Area": _select("Testing"),
            "Applies To": _multi(applies_to),
            "Learning Type": _select("Testing lesson"),
            "Source Link": _url(source_link),
            "Guardrail": _rich("Keep validation bounded."),
            "What To Do Next Time": _rich("Run the focused test."),
        },
    }


def test_catalog_contains_50_current_eligible_ids():
    catalog = load_lesson_accountability_catalog()
    assert len(catalog) == 50
    assert {e.lesson_id for e in catalog} == {
        f"lesson-{n}" for n in range(2, 52)
    }


def test_new_live_identity_is_reported_missing():
    catalog = load_lesson_accountability_catalog()
    drift = compare_live_eligible_identities(
        catalog, ("lesson-2", "lesson-new")
    )
    assert drift["missing"] == ("lesson-new",)


def test_stale_catalog_identity_is_detected():
    catalog = (
        LessonActivationAccountability(
            "lesson-live", "signal-activatable", "ready"
        ),
        LessonActivationAccountability(
            "lesson-stale", "known-reference-only", "manual-review"
        ),
    )
    drift = compare_live_eligible_identities(catalog, ("lesson-live",))
    assert drift["stale"] == ("lesson-stale",)


def test_duplicate_live_identity_is_detected():
    catalog = (
        LessonActivationAccountability(
            "lesson-1", "signal-activatable", "ready"
        ),
    )
    drift = compare_live_eligible_identities(
        catalog, ("lesson-1", "lesson-1")
    )
    assert drift["duplicate_live"] == ("lesson-1",)


def test_duplicate_catalog_identity_fails(tmp_path: Path):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps([
        {
            "lesson_id": "lesson-1",
            "activation_class": "signal-activatable",
            "activation_readiness": "ready",
        },
        {
            "lesson_id": "lesson-1",
            "activation_class": "known-reference-only",
            "activation_readiness": "manual-review",
        },
    ]), encoding="utf-8")

    with pytest.raises(
        LessonAccountabilityError,
        match="duplicate lesson identity",
    ):
        load_lesson_accountability_catalog(path)


def test_vocabularies_are_exact_and_orthogonal():
    assert ACTIVATION_CLASSES == {
        "signal-activatable",
        "known-reference-only",
        "context-only",
        "out-of-coding-scope",
    }
    assert ACTIVATION_READINESS == {
        "ready",
        "blocked-provenance",
        "blocked-vocabulary",
        "blocked-currentness",
        "blocked-conflict",
        "manual-review",
    }

    blocked_signal = LessonActivationAccountability(
        "lesson-x", "signal-activatable", "blocked-provenance"
    )
    ready_known = LessonActivationAccountability(
        "lesson-y", "known-reference-only", "ready"
    )
    assert allows_ordinary_signal_activation(blocked_signal)
    assert not allows_ordinary_signal_activation(ready_known)


@pytest.mark.parametrize(
    "activation_class",
    ["context-only", "out-of-coding-scope"],
)
def test_non_signal_classes_do_not_auto_activate(activation_class):
    entry = LessonActivationAccountability(
        "lesson-x", activation_class, "ready"
    )
    assert not allows_ordinary_signal_activation(entry)


def test_known_reference_uses_ckr6_known_reference_first():
    request = CodingKnowledgeRequest(
        task_reference="#1517",
        known_knowledge_refs=("lesson-4",),
        specialized_knowledge_required=True,
    )
    plan = plan_lesson_preflight(request)

    assert plan.retrieval_required
    assert plan.recommended_escalation is RetrievalEscalation.KNOWN_REFERENCE


def test_signal_candidate_uses_ckr11_then_ckr6_ckr2():
    lesson = normalize_lesson_row(_row())
    assert not isinstance(lesson, LessonActivationSkip)

    request = CodingKnowledgeRequest(
        task_reference="#1517",
        ecosystem_hints=("python",),
        capability_keywords=("testing",),
        canonical_rule_refs=(
            "https://github.com/Blummer92/agent-os/issues/1517",
        ),
        specialized_knowledge_required=True,
    )

    result = consume_lesson_preflight(request, (lesson,))

    assert result.selection is not None
    assert result.selection.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert result.selected_count <= 3


def test_missing_candidate_provenance_stays_fail_closed():
    lesson = normalize_lesson_row(_row(source_link=None))
    assert not isinstance(lesson, LessonActivationSkip)
    assert lesson.canonical_github_refs == ()

    request = CodingKnowledgeRequest(
        task_reference="#1517",
        ecosystem_hints=("python",),
        capability_keywords=("testing",),
        canonical_rule_refs=(
            "https://github.com/Blummer92/agent-os/issues/1517",
        ),
        specialized_knowledge_required=True,
    )

    result = consume_lesson_preflight(request, (lesson,))

    assert result.selection is not None
    assert result.selection.sufficiency_status is not SufficiencyStatus.SUFFICIENT


def test_missing_applies_to_is_ckr11_vocabulary_failure():
    row = _row()
    del row["properties"]["Applies To"]

    normalized = normalize_lesson_row(row)

    assert isinstance(normalized, LessonActivationSkip)
    assert normalized.reason == "ambiguous-applies-to-vocabulary"


def test_candidate_budget_remains_ckr6_owned():
    assert MAX_LESSON_RECORDS == 5


def test_catalog_stores_only_minimum_metadata():
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "agent_memory_context_manager"
        / "data"
        / "lesson_activation_accountability.json"
    )

    raw = json.loads(path.read_text(encoding="utf-8"))

    for item in raw:
        assert set(item) == {
            "lesson_id",
            "activation_class",
            "activation_readiness",
        }
