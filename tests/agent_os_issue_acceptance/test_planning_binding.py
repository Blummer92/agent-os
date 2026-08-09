from __future__ import annotations

import json
import socket
import subprocess
from dataclasses import FrozenInstanceError, replace

import pytest

from scripts.agent_os_issue_acceptance.issueplan_current_state import (
    IssuePlanCurrentStateEvidence,
    IssuePlanSourceSnapshot,
)
from scripts.agent_os_issue_acceptance.planning_binding import (
    PLANNING_BINDING_SCHEMA_VERSION,
    PlanningBindingEvidence,
    build_planning_binding_evidence,
    compute_planning_binding_fingerprint,
    reconstruct_planning_binding_evidence,
    serialize_planning_binding_evidence,
)
from scripts.agent_os_issue_acceptance.scheduler_handoff import (
    HandoffCohort,
    SchedulerPlanningHandoff,
)

HEAD_SHA = "a" * 40
CONTRACT_DIGEST = "b" * 64
GRAPH_DIGEST = "c" * 64
PLANNING_DIGEST = "d" * 64
HANDOFF_DIGEST = "e" * 64
ISSUEPLAN_ID = "issueplan-current-state:" + "f" * 64
CREATED_AT = "2026-08-06T15:00:00Z"


def _issueplan(**changes) -> IssuePlanCurrentStateEvidence:
    snapshot = IssuePlanSourceSnapshot(
        source_locator="github:Blummer92/agent-os#917",
        source_family="github-issue",
        source_revision="revision-1",
        retrieval_status="present",
        completeness_status="complete",
        metadata_status="present",
        governed_fields=(),
        omitted_fields=(),
        provenance_references=(),
        candidate_set_fingerprint="1" * 64,
        scanner_result_fingerprint="2" * 64,
    )
    values = {
        "schema_version": "1.0",
        "evidence_id": ISSUEPLAN_ID,
        "observed_at": "2026-08-06T14:30:00Z",
        "freshness_boundary": "issue-observation",
        "source_snapshot": snapshot,
        "source_snapshot_fingerprint": "3" * 64,
        "scanner_result_fingerprint": "2" * 64,
        "entity_ids": ("issue-917",),
        "candidate_revisions": ("revision-1",),
        "repository": "Blummer92/agent-os",
        "base_branch": "agent/752-repository-proposal-coordinator",
        "evaluated_repository_sha": HEAD_SHA,
        "implementation_contract_fingerprint": CONTRACT_DIGEST,
    }
    values.update(changes)
    return IssuePlanCurrentStateEvidence(**values)


def _handoff(**changes) -> SchedulerPlanningHandoff:
    values = {
        "contract_version": "0.2.0",
        "planning_result_version": "0.1.0",
        "evaluator_commit_sha": "9" * 40,
        "repository": "Blummer92/agent-os",
        "base_branch": "agent/752-repository-proposal-coordinator",
        "evaluated_repository_sha": HEAD_SHA,
        "supplied_node_ids": ("issue-916", "issue-917"),
        "graph_digest": GRAPH_DIGEST,
        "planning_result_digest": PLANNING_DIGEST,
        "cohort_summaries": (
            HandoffCohort(
                node_ids=("issue-916", "issue-917"),
                classification="parallel-candidate",
                reason_codes=(),
            ),
        ),
        "created_at": "2026-08-06T14:45:00Z",
        "handoff_digest": HANDOFF_DIGEST,
    }
    values.update(changes)
    return SchedulerPlanningHandoff(**values)


def _binding(*, created_at: str = CREATED_AT, issueplan=None, handoff=None):
    return build_planning_binding_evidence(
        issueplan or _issueplan(),
        handoff or _handoff(),
        created_at=created_at,
    )


def _payload(binding=None) -> dict[str, object]:
    return json.loads(serialize_planning_binding_evidence(binding or _binding()))


def test_schema_identity_and_authority_are_exact() -> None:
    binding = _binding()
    assert PLANNING_BINDING_SCHEMA_VERSION == "1.0"
    assert binding.schema_version == "1.0"
    assert binding.binding_id.startswith("planning-binding:")
    assert binding.execution_authorized is False
    assert binding.side_effects_performed is False


def test_repeated_semantic_inputs_are_deterministic() -> None:
    first = _binding()
    second = _binding()
    assert first == second
    assert first.binding_id == second.binding_id
    assert serialize_planning_binding_evidence(first) == serialize_planning_binding_evidence(
        second
    )


def test_created_at_is_excluded_from_semantic_identity() -> None:
    first = _binding(created_at="2026-08-06T15:00:00Z")
    second = _binding(created_at="2026-08-06T15:01:00Z")
    assert first.binding_id == second.binding_id
    assert first.created_at != second.created_at


@pytest.mark.parametrize(
    "handoff",
    [
        _handoff(graph_digest="0" * 64),
        _handoff(planning_result_digest="1" * 64),
        _handoff(handoff_digest="2" * 64),
        _handoff(contract_version="0.3.0"),
        _handoff(planning_result_version="0.2.0"),
        _handoff(supplied_node_ids=("issue-915", "issue-917")),
    ],
)
def test_semantic_changes_change_binding_identity(handoff) -> None:
    assert _binding(handoff=handoff).binding_id != _binding().binding_id


def test_fingerprint_matches_binding_id() -> None:
    binding = _binding()
    assert binding.binding_id == (
        "planning-binding:" + compute_planning_binding_fingerprint(binding)
    )


def test_round_trip_is_exact_and_byte_stable() -> None:
    binding = _binding()
    serialized = serialize_planning_binding_evidence(binding)
    reconstructed = reconstruct_planning_binding_evidence(serialized)
    assert reconstructed == binding
    assert serialize_planning_binding_evidence(reconstructed) == serialized


def test_canonical_json_and_node_order_are_stable() -> None:
    serialized = serialize_planning_binding_evidence(_binding())
    assert serialized == json.dumps(
        json.loads(serialized),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert json.loads(serialized)["supplied_node_ids"] == ["issue-916", "issue-917"]


@pytest.mark.parametrize("field", ["binding_id", "created_at", "repository"])
def test_closed_schema_rejects_missing_fields(field) -> None:
    payload = _payload()
    payload.pop(field)
    with pytest.raises(ValueError, match="missing field"):
        reconstruct_planning_binding_evidence(payload)


def test_closed_schema_rejects_unknown_fields() -> None:
    payload = _payload()
    payload["unexpected"] = "value"
    with pytest.raises(ValueError, match="unsupported field"):
        reconstruct_planning_binding_evidence(payload)


@pytest.mark.parametrize("value", ["issue-917", ("issue-917",), {"issue-917": 1}])
def test_reconstruction_requires_an_actual_node_list(value) -> None:
    payload = _payload()
    payload["supplied_node_ids"] = value
    with pytest.raises(ValueError, match="list of strings"):
        reconstruct_planning_binding_evidence(payload)


def test_reconstruction_rejects_non_string_node_members() -> None:
    payload = _payload()
    payload["supplied_node_ids"] = ["issue-916", 917]
    with pytest.raises(ValueError, match="contain only strings"):
        reconstruct_planning_binding_evidence(payload)


@pytest.mark.parametrize(
    ("node_ids", "message"),
    [
        ((), "must not be empty"),
        (("issue-917", "issue-917"), "duplicates"),
        (("issue-917", "issue-916"), "must be sorted"),
        (("issue-916", ""), "non-empty strings"),
    ],
)
def test_builder_rejects_noncanonical_node_ids(node_ids, message) -> None:
    with pytest.raises(ValueError, match=message):
        _binding(handoff=_handoff(supplied_node_ids=node_ids))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", "2.0", "unsupported planning binding schema"),
        ("binding_id", "bad", "binding_id is malformed"),
        ("issueplan_current_state_evidence_id", "bad", "evidence_id is malformed"),
        ("repository", "agent-os", "owner/repository"),
        ("base_branch", "refs/heads/main", "base_branch is malformed"),
        ("evaluated_repository_sha", "A" * 40, "lowercase SHA"),
        ("implementation_contract_fingerprint", "0" * 63, "SHA-256"),
        ("handoff_contract_version", "v1", "semantic version"),
        ("planning_result_version", "latest", "semantic version"),
        ("graph_digest", "0" * 63, "SHA-256"),
        ("planning_result_digest", "0" * 63, "SHA-256"),
        ("handoff_digest", "0" * 63, "SHA-256"),
        ("created_at", "2026-99-99T00:00:00Z", "UTC timestamp"),
    ],
)
def test_malformed_fields_fail_closed(field, value, message) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises(ValueError, match=message):
        reconstruct_planning_binding_evidence(payload)


def test_tampered_identity_fails_closed() -> None:
    payload = _payload()
    payload["binding_id"] = "planning-binding:" + "0" * 64
    with pytest.raises(ValueError, match="does not match"):
        reconstruct_planning_binding_evidence(payload)


@pytest.mark.parametrize("field", ["execution_authorized", "side_effects_performed"])
def test_authority_fields_cannot_be_true(field) -> None:
    payload = _payload()
    payload[field] = True
    with pytest.raises(ValueError, match=f"{field} must be false"):
        reconstruct_planning_binding_evidence(payload)


def test_authority_fields_are_not_constructible() -> None:
    values = _binding().__dict__ if hasattr(_binding(), "__dict__") else _payload()
    values = dict(values)
    values.pop("execution_authorized", None)
    values.pop("side_effects_performed", None)
    with pytest.raises(TypeError):
        PlanningBindingEvidence(**values, execution_authorized=True)


def test_binding_is_frozen() -> None:
    binding = _binding()
    with pytest.raises(FrozenInstanceError):
        binding.repository = "other/repository"


@pytest.mark.parametrize(
    ("issueplan", "handoff", "message"),
    [
        (_issueplan(repository="other/repository"), _handoff(), "repository binding"),
        (_issueplan(base_branch="main"), _handoff(), "base_branch binding"),
        (
            _issueplan(evaluated_repository_sha="8" * 40),
            _handoff(),
            "evaluated_repository_sha binding",
        ),
    ],
)
def test_builder_rejects_issueplan_handoff_drift(issueplan, handoff, message) -> None:
    with pytest.raises(ValueError, match=message):
        _binding(issueplan=issueplan, handoff=handoff)


@pytest.mark.parametrize(
    "field",
    [
        "repository",
        "base_branch",
        "evaluated_repository_sha",
        "implementation_contract_fingerprint",
    ],
)
def test_builder_rejects_missing_issueplan_context(field) -> None:
    with pytest.raises(ValueError, match=field):
        _binding(issueplan=_issueplan(**{field: None}))


def test_payload_requires_mapping_json() -> None:
    with pytest.raises(ValueError, match="must be a mapping"):
        reconstruct_planning_binding_evidence("[]")
    with pytest.raises(ValueError, match="canonical UTF-8 JSON"):
        reconstruct_planning_binding_evidence(b"\xff")


def test_core_performs_no_external_io(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("external I/O is forbidden")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    binding = _binding()
    assert reconstruct_planning_binding_evidence(
        serialize_planning_binding_evidence(binding)
    ) == binding
