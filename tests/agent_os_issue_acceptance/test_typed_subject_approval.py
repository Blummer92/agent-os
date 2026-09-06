from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

from scripts.agent_os_issue_acceptance.approval_records import (
    APPROVAL_RECORD_SCHEMA_VERSION,
    APPROVAL_RECORD_SEMANTIC_SCHEMA_VERSION,
    ApprovalState,
)
from scripts.agent_os_issue_acceptance.approved_execution_projection import (
    APPROVED_EXECUTION_PROJECTION_SCHEMA_VERSION,
)
from scripts.agent_os_issue_acceptance.typed_subject_approval import (
    TYPED_SUBJECT_APPROVAL_SCHEMA_VERSION,
    TYPED_SUBJECT_PROJECTION_SCHEMA_VERSION,
    build_typed_subject_approval_candidate,
    build_typed_subject_approved_execution_projection,
    evaluate_typed_subject_approval_applicability,
    record_typed_subject_approval_decision,
    serialize_typed_subject_approved_execution_projection,
    verified_typed_subject_reference,
)

ROOT = Path(__file__).resolve().parents[2]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


approval_fixtures = _load(
    ROOT / "tests/agent_os_issue_acceptance/test_approval_records.py",
    "approval_record_fixture_module",
)
subject_fixtures = _load(
    ROOT / "tests/test_live_operation_subject.py",
    "live_operation_subject_fixture_module",
)


def _candidate(subject=None):
    proposal, issueplan, repository = approval_fixtures._inputs()
    subject = subject or subject_fixtures._subject()
    candidate = build_typed_subject_approval_candidate(
        proposal,
        issueplan,
        repository,
        subject,
        approval_kind="implementation",
        authorizer_id="operator-1",
        decision_id="request-typed-1",
        decision_at=approval_fixtures.CREATED_AT,
        expires_at=approval_fixtures.EXPIRES_AT,
    )
    return candidate, subject, proposal, issueplan, repository


def _approved(subject=None):
    candidate, subject, proposal, issueplan, repository = _candidate(subject)
    approved = record_typed_subject_approval_decision(
        candidate,
        state=ApprovalState.APPROVED,
        decision_id="decision-typed-approve-1",
        authorizer_id="operator-2",
        decision_at=approval_fixtures.APPROVED_AT,
    )
    return approved, subject, proposal, issueplan, repository


def test_historical_schema_constants_remain_unchanged_and_successors_are_additive():
    assert APPROVAL_RECORD_SCHEMA_VERSION == "1.0"
    assert APPROVAL_RECORD_SEMANTIC_SCHEMA_VERSION == "1.1"
    assert APPROVED_EXECUTION_PROJECTION_SCHEMA_VERSION == "1.0"
    assert TYPED_SUBJECT_APPROVAL_SCHEMA_VERSION == "1.2"
    assert TYPED_SUBJECT_PROJECTION_SCHEMA_VERSION == "1.1"


def test_typed_subject_candidate_is_deterministic_and_binds_verified_subject():
    first, subject, *_ = _candidate()
    second, *_ = _candidate(copy.deepcopy(subject))
    assert first == second
    assert first.approval_id.startswith("approval:")
    assert first.approval_revision.startswith("approval-revision:")
    assert first.subject == verified_typed_subject_reference(subject)
    assert first.execution_authorized is False
    assert first.side_effects_performed is False


def test_arbitrary_subject_id_string_cannot_substitute_for_validated_subject_object():
    proposal, issueplan, repository = approval_fixtures._inputs()
    try:
        build_typed_subject_approval_candidate(
            proposal,
            issueplan,
            repository,
            "instructional-live-operation-subject:" + "0" * 64,
            approval_kind="implementation",
            authorizer_id="operator-1",
            decision_id="request-typed-1",
            decision_at=approval_fixtures.CREATED_AT,
        )
    except ValueError as exc:
        assert "exact validated subject" in str(exc)
    else:
        raise AssertionError("arbitrary subject id string must fail closed")


def test_exact_current_subject_is_applicable_and_changed_subject_is_stale():
    approved, subject, proposal, issueplan, repository = _approved()
    current = evaluate_typed_subject_approval_applicability(
        approved,
        subject,
        proposal,
        issueplan,
        repository,
        evaluated_at=approval_fixtures.APPROVED_AT,
    )
    assert current.status == "applicable"
    assert current.approval_applicable is True

    changed = copy.deepcopy(subject)
    changed["operation"]["docs_name"] = "Changed Worksheet"
    stale = evaluate_typed_subject_approval_applicability(
        approved,
        changed,
        proposal,
        issueplan,
        repository,
        evaluated_at=approval_fixtures.APPROVED_AT,
    )
    assert stale.status == "stale"
    assert stale.approval_applicable is False
    assert stale.changed_bindings == ("typed-subject",)


def test_typed_projection_carries_exact_approval_and_subject_and_remains_authority_false():
    approved, subject, proposal, issueplan, repository = _approved()
    applicability = evaluate_typed_subject_approval_applicability(
        approved,
        subject,
        proposal,
        issueplan,
        repository,
        evaluated_at=approval_fixtures.APPROVED_AT,
    )
    result = build_typed_subject_approved_execution_projection(
        proposal,
        approved,
        applicability,
        subject,
        issueplan,
        repository,
        projected_at=approval_fixtures.APPROVED_AT,
    )
    assert result.status == "complete"
    assert result.projection is not None
    projection = result.projection
    assert projection.approval_id == approved.approval_id
    assert projection.approval_revision == approved.approval_revision
    assert projection.subject == approved.subject
    assert projection.authoritative is False
    assert projection.execution_authorized is False
    assert projection.side_effects_performed is False
    payload = serialize_typed_subject_approved_execution_projection(projection)
    assert payload.endswith(b"\n")
    assert b'"authoritative":false' in payload
    assert b'"execution_authorized":false' in payload


def test_expired_typed_approval_stays_non_applicable_through_canonical_lifecycle():
    candidate, subject, proposal, issueplan, repository = _candidate()
    expired = record_typed_subject_approval_decision(
        candidate,
        state=ApprovalState.EXPIRED,
        decision_id="decision-expired",
        authorizer_id="operator-2",
        decision_at=approval_fixtures.EXPIRES_AT,
        reason_codes=("approval.expired",),
    )
    result = evaluate_typed_subject_approval_applicability(
        expired,
        subject,
        proposal,
        issueplan,
        repository,
        evaluated_at=approval_fixtures.EXPIRES_AT,
    )
    assert result.status != "applicable"
    assert result.approval_applicable is False
    assert "approval.expired" in result.reason_codes
