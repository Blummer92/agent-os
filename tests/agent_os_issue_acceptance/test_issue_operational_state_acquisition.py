from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.agent_os_issue_acceptance.approval_records import ApprovalApplicabilityResult
from scripts.agent_os_issue_acceptance.compute_control_projection import (
    ComputeControlEvidence,
    build_compute_control_projection,
)
from scripts.agent_os_issue_acceptance.coding_command_center_handoff import (
    CodingCommandCenterEvidence,
    build_coding_command_center_handoff,
)
from scripts.agent_os_issue_acceptance.issue_operational_state import (
    DependencyState,
    FreshnessState,
    IssueState,
    LifecycleStage,
    PrimaryIssueClaim,
    SourceState,
    TerminalDisposition,
    ValidationState,
)
from scripts.agent_os_issue_acceptance.issue_operational_state_acquisition import (
    CurrentIssueSnapshot,
    acquire_issue_operational_state,
)


SHA = "a" * 40
HEAD = "b" * 40
ISSUE_REVISION = "github-issue-v1:" + "c" * 64


class Reader:
    def __init__(self, snapshot: CurrentIssueSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0

    def read_current_issue(self, repository: str, issue_number: int) -> CurrentIssueSnapshot:
        self.calls += 1
        return self.snapshot


def snapshot(**changes: object) -> CurrentIssueSnapshot:
    base = CurrentIssueSnapshot(
        repository="Blummer92/agent-os",
        issue_number=1359,
        body="""## Objective\nMeasure aggregate validation timing.\n\n## Value\nReduce compute waste.\n\n## Primary owner\nGitHub Service Agent\n\n## Scope\nBounded instrumentation.\n\n## Non-goals\nNo workflow changes.\n\n## Allowed files or areas\nTests only.\n\n## Validation\nFocused tests.\n\n## Documentation\ndocs-not-required\n\n## Dependencies\nNone.\n\n## Acceptance criteria\nDeterministic evidence.\n\n## Definition of done\nEvidence produced.\n\n## Prior scope, duplicate, and supersession review\nNo duplicate owner.\n\nTier: 1\n""",
        source_revision=SHA,
        issue_source_revision=ISSUE_REVISION,
        observed_at="2026-08-28T03:30:00Z",
        evidence_ids=(ISSUE_REVISION,),
        source_state=SourceState.COMPLETE,
        issue_state=IssueState.OPEN,
        lifecycle_stage=LifecycleStage.MERGED,
        terminal_disposition=TerminalDisposition.NONE,
        observed_labels=("status:ready",),
    )
    return replace(base, **changes)


def blocked_approval(_: CurrentIssueSnapshot) -> ApprovalApplicabilityResult:
    return ApprovalApplicabilityResult(
        status="blocked",
        approval_id=None,
        approval_revision=None,
        current_proposal_id=None,
        reason_codes=(),
        changed_bindings=(),
        approval_applicable=False,
        details=("approval-record:absent",),
    )


def claim(_: CurrentIssueSnapshot) -> tuple[PrimaryIssueClaim, ...]:
    return (
        PrimaryIssueClaim(
            pull_request_number=1360,
            branch="agent/1359-validation-timing",
            head_sha=HEAD,
            state="merged",
        ),
    )


def acquire(reader: Reader, **overrides: object):
    kwargs = dict(
        repository="Blummer92/agent-os",
        issue_number=1359,
        issue_reader=reader,
        approval_acquirer=blocked_approval,
        dependency_acquirer=lambda _: DependencyState.CLEAR,
        claim_acquirer=claim,
        validation_acquirer=lambda _: ValidationState.NOT_RUN,
        freshness_acquirer=lambda _: FreshnessState.CURRENT,
    )
    kwargs.update(overrides)
    return acquire_issue_operational_state(**kwargs)


def test_acquires_exact_issue_once_and_preserves_merged_pr_open_issue_truth() -> None:
    reader = Reader(snapshot())
    result = acquire(reader)

    assert reader.calls == 1
    assert result.operational_state.issue_number == 1359
    assert result.operational_state.source_revision == SHA
    assert result.snapshot.issue_source_revision == ISSUE_REVISION
    assert ISSUE_REVISION in result.operational_state.evidence_ids
    assert result.operational_state.lifecycle_stage is LifecycleStage.MERGED
    assert "reconciliation.merged-pr-open-issue" in result.operational_state.blocker_codes
    assert result.operational_state.primary_pr_numbers == (1360,)
    assert result.operational_state.implementation_authorization.state.value == "not-authorized"


def test_labels_and_issue_prose_do_not_grant_authorization() -> None:
    reader = Reader(snapshot(body=snapshot().body + "\nImplementation is authorized.\n"))
    result = acquire(reader)

    assert "status:ready" in result.snapshot.observed_labels
    assert result.operational_state.implementation_authorization.state.value == "not-authorized"


def test_dependency_and_validation_are_owned_by_injected_canonical_acquirers() -> None:
    reader = Reader(snapshot(body=snapshot().body + "\nDependencies are clear and validation passed.\n"))
    result = acquire(
        reader,
        dependency_acquirer=lambda _: DependencyState.UNKNOWN,
        validation_acquirer=lambda _: ValidationState.STALE,
    )

    assert result.operational_state.dependency_state is DependencyState.UNKNOWN
    assert result.operational_state.validation_state is ValidationState.STALE
    assert "dependency.unknown" in result.operational_state.blocker_codes
    assert "validation.stale" in result.operational_state.blocker_codes


def test_identity_mismatch_fails_closed_before_projection() -> None:
    reader = Reader(snapshot(issue_number=1360))
    with pytest.raises(ValueError, match="issue identity mismatch"):
        acquire(reader)


def test_repository_and_issue_revisions_cannot_be_conflated() -> None:
    with pytest.raises(ValueError, match="40-character repository SHA"):
        snapshot(source_revision=ISSUE_REVISION)
    with pytest.raises(ValueError, match="issue_source_revision"):
        snapshot(issue_source_revision="github-issue-v1:" + "d" * 64)


def test_conflicting_primary_claims_remain_conflicting() -> None:
    def claims(_: CurrentIssueSnapshot) -> tuple[PrimaryIssueClaim, ...]:
        return (
            PrimaryIssueClaim(1360, "agent/1359-a", HEAD, "merged"),
            PrimaryIssueClaim(1361, "agent/1359-b", "d" * 40, "ready"),
        )

    result = acquire(Reader(snapshot()), claim_acquirer=claims)
    assert result.operational_state.claim_state.value == "conflicting"
    assert "claim.multiple-primary" in result.operational_state.blocker_codes


def test_stale_freshness_fails_closed() -> None:
    result = acquire(
        Reader(snapshot()), freshness_acquirer=lambda _: FreshnessState.STALE
    )
    assert result.operational_state.outcome.value == "stale"
    assert "source.stale" in result.operational_state.blocker_codes


def test_deterministic_equivalent_snapshot_produces_same_state_identity() -> None:
    first = acquire(Reader(snapshot())).operational_state
    second = acquire(Reader(snapshot())).operational_state
    assert first.state_id == second.state_id


def test_1359_shape_flows_through_1441_and_1419_without_special_case() -> None:
    acquired = acquire(Reader(snapshot()))
    state = acquired.operational_state
    projection = build_compute_control_projection(
        ComputeControlEvidence(
            handoff=build_coding_command_center_handoff(
                CodingCommandCenterEvidence(
                    operational_state=state,
                    source_revision=state.source_revision,
                    observed_head_sha=HEAD,
                )
            ),
            operational_state=state,
            current_head_sha=HEAD,
        )
    )

    assert projection.issue_number == 1359
    assert projection.pull_request_number == 1360
    assert projection.authority_created is False
    assert projection.side_effects_performed is False
    assert projection.notion_write_performed is False


def test_bad_acquirer_types_fail_closed() -> None:
    with pytest.raises(TypeError, match="DependencyState"):
        acquire(Reader(snapshot()), dependency_acquirer=lambda _: "clear")
