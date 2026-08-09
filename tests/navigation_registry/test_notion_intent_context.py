from dataclasses import FrozenInstanceError
from copy import deepcopy

import pytest

from navigation_registry.connectors.base import RegistryResource
from navigation_registry.connectors.notion_intent_context import (
    MAX_REFS,
    MAX_TEXT,
    NotionIntentContextError,
    NotionIntentEvidence,
    project_notion_intent_context,
)


def _resource(**overrides) -> RegistryResource:
    values = {
        "system": "notion",
        "entity_type": "Page",
        "canonical_id": "page-123",
        "display_name": "Task",
        "parent": "data-source-123",
        "owner": None,
        "source_of_truth": "notion-live",
        "verification_state": "VerifiedReadOnly",
        "cache_status": "LiveRead",
        "human_review_required": False,
        "write_allowed": False,
        "metadata": {"last_edited_time": "2026-08-08T00:00:00Z"},
    }
    values.update(overrides)
    return RegistryResource(**values)


def _evidence(**overrides) -> NotionIntentEvidence:
    values = {
        "resource": _resource(),
        "logical_source": "tasks_issues",
        "objective": "Implement the bounded change",
        "owner": "Integration Manager",
        "owner_dashboard": "dashboard-1",
        "status": "Ready",
        "governance_gate": "Approved scope only",
        "blocker": None,
        "next_action": "Run focused tests",
        "decision_refs": ("decision-b", "decision-a"),
        "lesson_refs": ("lesson-1",),
        "pattern_refs": ("pattern-1",),
        "source_refs": ("source-1",),
        "approval_required": True,
        "scope_change": False,
    }
    values.update(overrides)
    return NotionIntentEvidence(**values)


@pytest.mark.parametrize(
    ("logical_source", "refs"),
    [
        ("tasks_issues", {"decision_refs": ("decision-1",)}),
        ("decision_log", {"decision_refs": ("adr-1", "adr-2")}),
        ("lessons_learned", {"lesson_refs": ("lesson-1",)}),
        ("reusable_patterns", {"pattern_refs": ("pattern-1",)}),
    ],
)
def test_supported_operational_sources_project(logical_source, refs) -> None:
    context = project_notion_intent_context(_evidence(logical_source=logical_source, **refs))
    assert context.logical_source == logical_source
    assert context.data_source_id == "data-source-123"
    assert context.authority is False


def test_context_is_immutable_and_deterministic() -> None:
    first = project_notion_intent_context(_evidence())
    second = project_notion_intent_context(
        _evidence(decision_refs=("decision-a", "decision-b", "decision-a"))
    )
    assert first.serialize() == second.serialize()
    assert first.fingerprint() == second.fingerprint()
    with pytest.raises(FrozenInstanceError):
        first.status = "Changed"  # type: ignore[misc]


def test_input_evidence_is_not_mutated() -> None:
    resource = _resource(metadata={"last_edited_time": "rev-1", "extra": {"x": 1}})
    metadata_before = deepcopy(resource.metadata)
    evidence = _evidence(resource=resource)
    project_notion_intent_context(evidence)
    assert resource.metadata == metadata_before


def test_data_source_and_database_identity_remain_distinct() -> None:
    resource = _resource(
        metadata={
            "last_edited_time": "rev-1",
            "data_source_id": "data-source-123",
            "database_id": "database-123",
        }
    )
    context = project_notion_intent_context(_evidence(resource=resource))
    assert context.data_source_id == "data-source-123"
    assert context.database_id == "database-123"


@pytest.mark.parametrize(
    "resource",
    [
        _resource(parent=None),
        _resource(metadata={"last_edited_time": "rev", "data_source_id": "other"}),
        _resource(metadata={"last_edited_time": "rev", "database_id": "data-source-123"}),
    ],
)
def test_missing_or_conflicting_data_source_identity_fails_closed(resource) -> None:
    with pytest.raises(NotionIntentContextError):
        project_notion_intent_context(_evidence(resource=resource))


@pytest.mark.parametrize(
    "resource",
    [
        _resource(metadata={"last_edited_time": "rev", "archived": True}),
        _resource(metadata={"last_edited_time": "rev", "in_trash": True}),
        _resource(source_of_truth="notion-search-result"),
        _resource(verification_state="SearchResultOnly"),
        _resource(cache_status="SearchResult"),
        _resource(write_allowed=True),
    ],
)
def test_noncurrent_or_nonlive_evidence_fails_closed(resource) -> None:
    with pytest.raises(NotionIntentContextError):
        project_notion_intent_context(_evidence(resource=resource))


def test_stale_or_missing_revision_fails_closed() -> None:
    with pytest.raises(NotionIntentContextError):
        project_notion_intent_context(_evidence(resource=_resource(metadata={})))
    with pytest.raises(NotionIntentContextError):
        project_notion_intent_context(
            _evidence(resource=_resource(metadata={"last_edited_time": "rev-a"}), source_revision=3)
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"logical_source": "unknown"},
        {"objective": ""},
        {"owner": ""},
        {"owner": 7},
        {"approval_required": "yes"},
        {"relation_complete": "yes"},
        {"relation_depth": 2},
    ],
)
def test_required_contract_failures(overrides) -> None:
    with pytest.raises(NotionIntentContextError):
        project_notion_intent_context(_evidence(**overrides))


def test_text_and_reference_bounds_fail_closed() -> None:
    with pytest.raises(NotionIntentContextError):
        project_notion_intent_context(_evidence(objective="x" * (MAX_TEXT + 1)))
    with pytest.raises(NotionIntentContextError):
        project_notion_intent_context(
            _evidence(source_refs=tuple(f"source-{i}" for i in range(MAX_REFS + 1)))
        )


def test_unknown_additive_metadata_is_ignored() -> None:
    resource = _resource(metadata={"last_edited_time": "rev", "future_field": {"a": 1}})
    context = project_notion_intent_context(_evidence(resource=resource))
    assert context.source_revision == "rev"


def test_incomplete_relation_is_bounded_stop_evidence() -> None:
    context = project_notion_intent_context(
        _evidence(relation_complete=False, relation_depth=1)
    )
    handoff = context.to_memory_handoff_fields()
    assert "relation_continuation_required" in handoff["stop_conditions"]


def test_memory_manager_seam_uses_existing_concepts_only() -> None:
    context = project_notion_intent_context(_evidence())
    handoff = context.to_memory_handoff_fields()
    assert set(handoff) == {"objective", "known_facts", "prior_decisions", "stop_conditions"}
    assert handoff["objective"] == "Implement the bounded change"
    assert "approval_required" in handoff["stop_conditions"]
    assert any(item == "decision_ref=decision-a" for item in handoff["prior_decisions"])


def test_projection_exposes_no_write_or_network_capability() -> None:
    context = project_notion_intent_context(_evidence())
    assert context.authority is False
    for name in ("request", "fetch", "search", "write", "create", "update", "delete"):
        assert not hasattr(context, name)
