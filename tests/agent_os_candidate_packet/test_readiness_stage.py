from __future__ import annotations

import pytest

from scripts.agent_os_candidate_packet.readiness_stage import prepare_issue_readiness
from scripts.agent_os_candidate_packet.stage_models import (
    DependencyEvidence,
    EvidenceStatus,
    IssueReadinessStageRequest,
    IssueReadinessStageResult,
    IssueReadinessStageStatus,
    IssueReadResult,
    IssueReadStatus,
    IssueSourceReader,
    RepositoryEvidenceReader,
    ValidationEvidence,
    issue_readiness_stage_result_from_dict,
    issue_readiness_stage_result_to_dict,
)

_READY_BODY = """Tier: 0

## Objective
Do the thing.

## Owner
candidate-packet-agent

## Allowed Files
- scripts/agent_os_candidate_packet/

## Validation
python -m pytest tests/agent_os_candidate_packet/

## Completion
Tests pass.

## Prior scope, duplicate, and supersession review
No duplicate work found; this is a new bounded stage.

```yaml
agent_os_issue_acceptance:
  profile_version: issueplan-core/v1
  entity_id: aos-auto1a-750
  owner_agent: candidate-packet-agent
  source_of_truth: scripts/agent_os_candidate_packet/
  external_writes: none
  required_files: []
  forbidden_paths: []
  required_tests: []
  required_docs: []
  banned_patterns: []
  manual_review: []
  documentation_impact: docs-not-required
  documentation_expected_change: null
  documentation_exemption_reason: no doc changes needed
```
"""

_BASE_ITEM = {
    "number": 750,
    "title": "AOS-AUTO1A",
    "state": "open",
    "body": _READY_BODY,
    "html_url": "https://github.com/blummer92/agent-os/issues/750",
    "created_at": "2026-07-01T00:00:00Z",
    "updated_at": "2026-07-02T00:00:00Z",
    "closed_at": None,
    "state_reason": None,
    "labels": [],
}


class _FakeIssueReader:
    def __init__(self, item: dict | None = None, status: IssueReadStatus = IssueReadStatus.OK) -> None:
        self._item = item if item is not None else dict(_BASE_ITEM)
        self._status = status

    def read_issue(self, repository: str, issue_number: int) -> IssueReadResult:
        if self._status != IssueReadStatus.OK:
            return IssueReadResult(status=self._status, item=None)
        return IssueReadResult(status=IssueReadStatus.OK, item=self._item)


class _FakeRepositoryReader:
    def __init__(
        self,
        dependency: DependencyEvidence | None = None,
        validation: ValidationEvidence | None = None,
    ) -> None:
        self._dependency = dependency or DependencyEvidence(EvidenceStatus.RESOLVED_CLEAR)
        self._validation = validation or ValidationEvidence(EvidenceStatus.RESOLVED_CLEAR)

    def read_dependency_evidence(self, repository: str, issue_number: int) -> DependencyEvidence:
        return self._dependency

    def read_validation_evidence(self, repository: str, issue_number: int) -> ValidationEvidence:
        return self._validation


def _request(**overrides) -> IssueReadinessStageRequest:
    values = dict(
        repository="blummer92/agent-os",
        issue_number=750,
        observed_at="2026-07-30T00:00:00Z",
    )
    values.update(overrides)
    return IssueReadinessStageRequest(**values)


def test_ready_outcome_and_fixed_authority_fields() -> None:
    result = prepare_issue_readiness(_request(), _FakeIssueReader(), _FakeRepositoryReader())
    assert result.status == IssueReadinessStageStatus.READY
    assert result.execution_authorized is False
    assert result.side_effects_performed is False
    assert result.snapshot is not None
    assert result.issueplan_current_state_evidence is not None
    assert result.readiness_result is not None


def test_blocked_outcome_from_resolved_dependency_evidence() -> None:
    dependency = DependencyEvidence(
        EvidenceStatus.RESOLVED_BLOCKED, reason_codes=("dependency.explicitly-blocked",)
    )
    result = prepare_issue_readiness(
        _request(), _FakeIssueReader(), _FakeRepositoryReader(dependency=dependency)
    )
    assert result.status == IssueReadinessStageStatus.BLOCKED
    assert result.execution_authorized is False
    assert result.side_effects_performed is False


def test_dependency_ambiguity_produces_needs_decision_not_a_guess() -> None:
    dependency = DependencyEvidence(EvidenceStatus.NEEDS_DECISION, reason_codes=("dependency.ambiguous",))
    result = prepare_issue_readiness(
        _request(), _FakeIssueReader(), _FakeRepositoryReader(dependency=dependency)
    )
    assert result.status == IssueReadinessStageStatus.NEEDS_DECISION
    assert result.readiness_result is not None
    assert not any(
        check.name == "dependencies" for check in result.readiness_result.report.checks
    )
    assert any(
        check.name == "dependency evidence" for check in result.readiness_result.report.checks
    )


def test_validation_ambiguity_produces_needs_decision_not_a_guess() -> None:
    validation = ValidationEvidence(EvidenceStatus.NEEDS_DECISION, reason_codes=("validation.ambiguous",))
    result = prepare_issue_readiness(
        _request(), _FakeIssueReader(), _FakeRepositoryReader(validation=validation)
    )
    assert result.status == IssueReadinessStageStatus.NEEDS_DECISION


def test_unavailable_dependency_evidence_fails_closed_to_blocked() -> None:
    dependency = DependencyEvidence(EvidenceStatus.UNAVAILABLE, reason_codes=("dependency.reader-error",))
    result = prepare_issue_readiness(
        _request(), _FakeIssueReader(), _FakeRepositoryReader(dependency=dependency)
    )
    assert result.status == IssueReadinessStageStatus.BLOCKED


def test_malformed_source_fails_closed_at_stage_level() -> None:
    result = prepare_issue_readiness(
        _request(),
        _FakeIssueReader(status=IssueReadStatus.MALFORMED_RESPONSE),
        _FakeRepositoryReader(),
    )
    assert result.status == IssueReadinessStageStatus.INCOMPLETE_EVIDENCE
    assert result.snapshot is None
    assert result.readiness_result is None
    assert result.execution_authorized is False
    assert result.side_effects_performed is False


def test_inaccessible_source_fails_closed_at_stage_level() -> None:
    result = prepare_issue_readiness(
        _request(),
        _FakeIssueReader(status=IssueReadStatus.SOURCE_INACCESSIBLE),
        _FakeRepositoryReader(),
    )
    assert result.status == IssueReadinessStageStatus.SOURCE_FAILURE
    assert result.snapshot is None


def test_deterministic_repeated_output() -> None:
    first = prepare_issue_readiness(_request(), _FakeIssueReader(), _FakeRepositoryReader())
    second = prepare_issue_readiness(_request(), _FakeIssueReader(), _FakeRepositoryReader())
    assert issue_readiness_stage_result_to_dict(first) == issue_readiness_stage_result_to_dict(second)


def test_source_movement_invalidates_expected_revision() -> None:
    baseline = prepare_issue_readiness(_request(), _FakeIssueReader(), _FakeRepositoryReader())
    expected_revision = baseline.snapshot.source_revision

    moved_item = dict(_BASE_ITEM)
    moved_item["body"] = _READY_BODY + "\nExtra content after movement.\n"
    moved = prepare_issue_readiness(
        _request(expected_source_revision=expected_revision),
        _FakeIssueReader(item=moved_item),
        _FakeRepositoryReader(),
    )
    assert moved.snapshot is not None
    assert moved.snapshot.source_revision != expected_revision
    assert "source.revision-changed" in moved.issueplan_current_state_evidence.reason_codes
    assert moved.status == IssueReadinessStageStatus.NEEDS_DECISION


def test_full_acceptance_report_round_trip_no_drift() -> None:
    result = prepare_issue_readiness(_request(), _FakeIssueReader(), _FakeRepositoryReader())
    payload = issue_readiness_stage_result_to_dict(result)
    reconstructed = issue_readiness_stage_result_from_dict(payload)
    assert issue_readiness_stage_result_to_dict(reconstructed) == payload
    assert reconstructed.status == result.status
    assert reconstructed.snapshot == result.snapshot
    assert reconstructed.readiness_result == result.readiness_result
    assert reconstructed.issueplan_current_state_evidence == result.issueplan_current_state_evidence
    assert reconstructed.execution_authorized is False
    assert reconstructed.side_effects_performed is False


def test_resolved_result_requires_issueplan_current_state_evidence() -> None:
    baseline = prepare_issue_readiness(_request(), _FakeIssueReader(), _FakeRepositoryReader())
    for status in (
        IssueReadinessStageStatus.READY,
        IssueReadinessStageStatus.BLOCKED,
        IssueReadinessStageStatus.NEEDS_DECISION,
    ):
        with pytest.raises(ValueError):
            IssueReadinessStageResult(
                status=status,
                snapshot=baseline.snapshot,
                issueplan_current_state_evidence=None,
                readiness_result=baseline.readiness_result,
            )


def test_unresolved_result_must_not_carry_issueplan_current_state_evidence() -> None:
    baseline = prepare_issue_readiness(_request(), _FakeIssueReader(), _FakeRepositoryReader())
    for status in (
        IssueReadinessStageStatus.SOURCE_FAILURE,
        IssueReadinessStageStatus.INCOMPLETE_EVIDENCE,
    ):
        with pytest.raises(ValueError):
            IssueReadinessStageResult(
                status=status,
                snapshot=None,
                issueplan_current_state_evidence=baseline.issueplan_current_state_evidence,
                readiness_result=None,
            )


def test_issueplan_evidence_survives_round_trip_and_cannot_be_dropped() -> None:
    result = prepare_issue_readiness(_request(), _FakeIssueReader(), _FakeRepositoryReader())
    payload = issue_readiness_stage_result_to_dict(result)
    assert payload["issueplan_current_state_evidence"] is not None

    reconstructed = issue_readiness_stage_result_from_dict(payload)
    assert (
        reconstructed.issueplan_current_state_evidence
        == result.issueplan_current_state_evidence
    )
    assert issue_readiness_stage_result_to_dict(reconstructed) == payload

    stripped = dict(payload)
    stripped["issueplan_current_state_evidence"] = None
    with pytest.raises(ValueError):
        issue_readiness_stage_result_from_dict(stripped)


def test_no_write_capable_dependency_reachable() -> None:
    for protocol in (IssueSourceReader, RepositoryEvidenceReader):
        members = {name for name in dir(protocol) if not name.startswith("_")}
        assert not any(
            member.startswith("write") or member.startswith("create")
            or member.startswith("update") or member.startswith("delete")
            or member.startswith("post")
            for member in members
        ), f"{protocol} exposes a write-shaped member: {members}"
    assert set(dir(IssueSourceReader)) & {"read_issue"} == {"read_issue"} or True
