from __future__ import annotations

import pytest

from scripts.agent_os_candidate_packet.readiness_stage import prepare_issue_readiness
from scripts.agent_os_candidate_packet.stage_models import (
    DEPENDENCY_IDENTITY_NOT_SUPPLIED,
    DEPENDENCY_IDENTITY_NOT_SUPPLIED_REASON,
    STAGE_SCHEMA_VERSION,
    DependencyEvidence,
    DependencyIdentityEvidence,
    DependencyIdentityStatus,
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


# --------------------------------------------------------------------------
# AOS-AUTO1A2 (#776): canonical dependency-identity evidence on the stage.
# --------------------------------------------------------------------------

_RESOLVED_IDENTITY = DependencyIdentityEvidence(
    status=DependencyIdentityStatus.RESOLVED,
    dependency_ids=("issue-752", "issue-751"),
    provenance=("caller:structured-dependency-input",),
)


def _resolved_outcomes() -> list[tuple[IssueReadinessStageStatus, _FakeRepositoryReader]]:
    """One reader per resolved #750 outcome classification."""
    return [
        (IssueReadinessStageStatus.READY, _FakeRepositoryReader()),
        (
            IssueReadinessStageStatus.BLOCKED,
            _FakeRepositoryReader(
                dependency=DependencyEvidence(
                    EvidenceStatus.RESOLVED_BLOCKED,
                    reason_codes=("dependency.explicitly-blocked",),
                )
            ),
        ),
        (
            IssueReadinessStageStatus.NEEDS_DECISION,
            _FakeRepositoryReader(
                dependency=DependencyEvidence(
                    EvidenceStatus.NEEDS_DECISION,
                    reason_codes=("dependency.ambiguous",),
                )
            ),
        ),
    ]


def test_every_resolved_outcome_carries_dependency_identity_evidence() -> None:
    for expected_status, reader in _resolved_outcomes():
        result = prepare_issue_readiness(
            _request(),
            _FakeIssueReader(),
            reader,
            dependency_identity_evidence=_RESOLVED_IDENTITY,
        )
        assert result.status == expected_status
        assert result.dependency_identity_evidence == _RESOLVED_IDENTITY
        assert result.dependency_identity_evidence.dependency_ids == (
            "issue-751",
            "issue-752",
        )


def test_omitted_identity_evidence_fails_closed_to_unavailable() -> None:
    for expected_status, reader in _resolved_outcomes():
        result = prepare_issue_readiness(_request(), _FakeIssueReader(), reader)
        assert result.status == expected_status
        evidence = result.dependency_identity_evidence
        assert evidence == DEPENDENCY_IDENTITY_NOT_SUPPLIED
        assert evidence.status == DependencyIdentityStatus.UNAVAILABLE
        assert evidence.dependency_ids == ()
        assert DEPENDENCY_IDENTITY_NOT_SUPPLIED_REASON in evidence.reason_codes


def test_dependency_prose_in_the_body_never_becomes_an_identity() -> None:
    prose_item = dict(_BASE_ITEM)
    prose_item["body"] = _READY_BODY + (
        "\n## Dependencies\n"
        "Depends on: #751\n"
        "Depends on: https://github.com/blummer92/agent-os/issues/752\n"
        "Blocked by issue-753 until the coordinator lands.\n"
    )
    prose_item["labels"] = [{"name": "depends-on-751"}]
    result = prepare_issue_readiness(
        _request(), _FakeIssueReader(item=prose_item), _FakeRepositoryReader()
    )
    evidence = result.dependency_identity_evidence
    assert evidence is not None
    assert evidence.dependency_ids == ()
    assert evidence.status == DependencyIdentityStatus.UNAVAILABLE
    assert not any("751" in code for code in evidence.reason_codes)


def test_dependency_evidence_reason_codes_never_become_identities() -> None:
    dependency = DependencyEvidence(
        EvidenceStatus.RESOLVED_BLOCKED,
        reason_codes=("issue-751", "dependency.explicitly-blocked"),
        details=("issue-752 is not merged",),
    )
    result = prepare_issue_readiness(
        _request(), _FakeIssueReader(), _FakeRepositoryReader(dependency=dependency)
    )
    assert result.dependency_identity_evidence.dependency_ids == ()
    assert "issue-751" in result.reason_codes  # preserved as a reason code only


def test_unresolved_stage_result_rejects_dependency_identity_evidence() -> None:
    for status in (
        IssueReadinessStageStatus.SOURCE_FAILURE,
        IssueReadinessStageStatus.INCOMPLETE_EVIDENCE,
    ):
        with pytest.raises(ValueError):
            IssueReadinessStageResult(
                status=status,
                snapshot=None,
                issueplan_current_state_evidence=None,
                readiness_result=None,
                dependency_identity_evidence=_RESOLVED_IDENTITY,
            )


def test_unresolved_stage_results_carry_no_identity_evidence() -> None:
    for read_status in (
        IssueReadStatus.SOURCE_INACCESSIBLE,
        IssueReadStatus.MALFORMED_RESPONSE,
    ):
        result = prepare_issue_readiness(
            _request(),
            _FakeIssueReader(status=read_status),
            _FakeRepositoryReader(),
            dependency_identity_evidence=_RESOLVED_IDENTITY,
        )
        assert result.dependency_identity_evidence is None


def test_resolved_stage_result_rejects_a_non_evidence_value() -> None:
    baseline = prepare_issue_readiness(_request(), _FakeIssueReader(), _FakeRepositoryReader())
    for bad in ("issue-751", ("issue-751",), 751, True, object()):
        with pytest.raises(TypeError):
            IssueReadinessStageResult(
                status=baseline.status,
                snapshot=baseline.snapshot,
                issueplan_current_state_evidence=baseline.issueplan_current_state_evidence,
                readiness_result=baseline.readiness_result,
                dependency_identity_evidence=bad,
            )


def test_producer_rejects_a_non_evidence_identity_argument() -> None:
    for bad in ("issue-751", ("issue-751",), 751, True):
        with pytest.raises(TypeError):
            prepare_issue_readiness(
                _request(),
                _FakeIssueReader(),
                _FakeRepositoryReader(),
                dependency_identity_evidence=bad,
            )


def test_identity_evidence_survives_round_trip_and_cannot_be_dropped() -> None:
    result = prepare_issue_readiness(
        _request(),
        _FakeIssueReader(),
        _FakeRepositoryReader(),
        dependency_identity_evidence=_RESOLVED_IDENTITY,
    )
    payload = issue_readiness_stage_result_to_dict(result)
    assert payload["dependency_identity_evidence"] == {
        "status": "resolved",
        "dependency_ids": ["issue-751", "issue-752"],
        "provenance": ["caller:structured-dependency-input"],
        "reason_codes": [],
        "execution_authorized": False,
        "side_effects_performed": False,
    }

    reconstructed = issue_readiness_stage_result_from_dict(payload)
    assert reconstructed.dependency_identity_evidence == _RESOLVED_IDENTITY
    assert issue_readiness_stage_result_to_dict(reconstructed) == payload

    dropped = dict(payload)
    dropped["dependency_identity_evidence"] = None
    rebuilt = issue_readiness_stage_result_from_dict(dropped)
    # A dropped field cannot silently mean "no dependencies".
    assert rebuilt.dependency_identity_evidence == DEPENDENCY_IDENTITY_NOT_SUPPLIED


def test_legacy_schema_payloads_are_rejected_rather_than_reinterpreted() -> None:
    result = prepare_issue_readiness(_request(), _FakeIssueReader(), _FakeRepositoryReader())
    payload = issue_readiness_stage_result_to_dict(result)
    assert payload["schema_version"] == STAGE_SCHEMA_VERSION == "1.1"

    legacy = {key: value for key, value in payload.items() if key != "dependency_identity_evidence"}
    legacy["schema_version"] = "1.0"
    with pytest.raises(ValueError):
        issue_readiness_stage_result_from_dict(legacy)


def test_stage_payload_rejects_unknown_and_missing_fields() -> None:
    result = prepare_issue_readiness(_request(), _FakeIssueReader(), _FakeRepositoryReader())
    payload = issue_readiness_stage_result_to_dict(result)
    with pytest.raises(ValueError):
        issue_readiness_stage_result_from_dict({**payload, "dependency_ids": ["issue-751"]})
    for key in payload:
        if key == "schema_version":
            continue
        partial = {name: value for name, value in payload.items() if name != key}
        with pytest.raises(ValueError):
            issue_readiness_stage_result_from_dict(partial)


def test_identity_evidence_keeps_repeated_output_deterministic() -> None:
    first = prepare_issue_readiness(
        _request(),
        _FakeIssueReader(),
        _FakeRepositoryReader(),
        dependency_identity_evidence=DependencyIdentityEvidence(
            status=DependencyIdentityStatus.RESOLVED,
            dependency_ids=("issue-752", "issue-751"),
            provenance=("caller:structured-dependency-input",),
        ),
    )
    second = prepare_issue_readiness(
        _request(),
        _FakeIssueReader(),
        _FakeRepositoryReader(),
        dependency_identity_evidence=DependencyIdentityEvidence(
            status=DependencyIdentityStatus.RESOLVED,
            dependency_ids=("issue-751", "issue-752"),
            provenance=("caller:structured-dependency-input",),
        ),
    )
    assert issue_readiness_stage_result_to_dict(first) == issue_readiness_stage_result_to_dict(second)


def test_existing_750_outcome_classifications_are_unchanged() -> None:
    """Identity evidence must not shift any readiness outcome."""
    cases = [
        (IssueReadinessStageStatus.READY, _FakeIssueReader(), _FakeRepositoryReader()),
        *[
            (status, _FakeIssueReader(), reader)
            for status, reader in _resolved_outcomes()[1:]
        ],
        (
            IssueReadinessStageStatus.BLOCKED,
            _FakeIssueReader(),
            _FakeRepositoryReader(
                dependency=DependencyEvidence(
                    EvidenceStatus.UNAVAILABLE, reason_codes=("dependency.reader-error",)
                )
            ),
        ),
        (
            IssueReadinessStageStatus.SOURCE_FAILURE,
            _FakeIssueReader(status=IssueReadStatus.SOURCE_INACCESSIBLE),
            _FakeRepositoryReader(),
        ),
        (
            IssueReadinessStageStatus.INCOMPLETE_EVIDENCE,
            _FakeIssueReader(status=IssueReadStatus.MALFORMED_RESPONSE),
            _FakeRepositoryReader(),
        ),
    ]
    for expected_status, issue_reader, repository_reader in cases:
        without = prepare_issue_readiness(_request(), issue_reader, repository_reader)
        with_identity = prepare_issue_readiness(
            _request(),
            issue_reader,
            repository_reader,
            dependency_identity_evidence=(
                _RESOLVED_IDENTITY
                if expected_status
                in {
                    IssueReadinessStageStatus.READY,
                    IssueReadinessStageStatus.BLOCKED,
                    IssueReadinessStageStatus.NEEDS_DECISION,
                }
                else None
            ),
        )
        assert without.status == expected_status
        assert with_identity.status == expected_status
        assert without.readiness_result == with_identity.readiness_result
        assert without.reason_codes == with_identity.reason_codes


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
