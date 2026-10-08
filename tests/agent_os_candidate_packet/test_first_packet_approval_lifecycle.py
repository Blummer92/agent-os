"""#3354 first-packet approval lifecycle regressions.

``test_first_packet_depends_on.py`` proves first-packet readiness reaches a
ready planning handoff. This module drives the same never-approved Tier-2
candidate through the rest of the pre-approval lifecycle with the real
pipeline -- repository observation, DraftTaskProposal, APPROVAL_READY packet,
and the explicit owner decision -- and proves the phase boundary on the other
side: approval never grants consumer eligibility, and the post-approval
evidence owners (#1320) stay mandatory once an approval record exists.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXECUTION_SERVICE_SRC = REPOSITORY_ROOT / "08_Tooling/agent-os-execution-service/src"
if str(EXECUTION_SERVICE_SRC) not in sys.path:
    sys.path.insert(0, str(EXECUTION_SERVICE_SRC))

import pytest  # noqa: E402

from scripts.agent_os_candidate_packet.approval_stage import (  # noqa: E402
    ApprovalCandidateContext,
    ApprovalDecision,
    ApprovalProjectionStageStatus,
    prepare_approval_projection,
)
from scripts.agent_os_candidate_packet.cli import prepare_candidate_packet  # noqa: E402
from scripts.agent_os_candidate_packet.models import CandidatePacketPhase  # noqa: E402
from scripts.agent_os_candidate_packet.proposal_stage import (  # noqa: E402
    RepositoryProposalStageStatus,
)
from scripts.agent_os_candidate_packet.repository_stage import (  # noqa: E402
    RepositoryObservation,
)
from scripts.agent_os_candidate_packet.stage_models import (  # noqa: E402
    DependencyEvidence,
    DependencyIdentityEvidence,
    DependencyIdentityStatus,
    EvidenceStatus,
    IssueReadinessStageStatus,
    IssueReadResult,
    IssueReadStatus,
    ValidationEvidence,
)
from scripts.agent_os_execution_capabilities import (  # noqa: E402
    RepositoryEvidenceType,
    RepositoryIdentity,
    WorktreeState,
)
from scripts.agent_os_issue_acceptance import ApprovalKind, ApprovalState  # noqa: E402

_REPOSITORY = "Blummer92/agent-os"
_ISSUE_NUMBER = 33541
_SHA = "b89de18da472a3cd79877c4f7ee13b49bd7014eb"
_EVALUATOR_SHA = "a" * 40
_BRANCH = "agent/3354-first-packet-lifecycle"
_OBSERVED_AT = "2026-10-08T00:05:00Z"
_TEST = "python -m pytest tests/agent_os_candidate_packet/test_first_packet_approval_lifecycle.py"


def _body(depends_on_block: str = "  depends_on: []") -> str:
    return f"""## Issue tier

tier:2-governed-cross-system

## Objective and value
First never-approved Tier-2 candidate for the #3354 lifecycle.

## Primary owner
github-service-agent

## Source of truth
GitHub

## External write boundary
no-external-write

## Scope
- tests/agent_os_candidate_packet/test_first_packet_approval_lifecycle.py

## Non-goals
- no workflow, credential, or production change

## Documentation impact
docs-not-required

## Dependencies and blockers
None.

## Acceptance criteria
- [ ] {_TEST} passes.

## Definition of done
Tests pass at the exact head.

## Authorization
Repository implementation only.

## Approval requirements
Explicit repository-owner approval of the candidate.

## Stop conditions
Head or base drift.

## Compatibility
Preserve the post-approval evidence contract.

## Rollback
Revert the change.

## Allowed files, areas, or governed surfaces
- tests/agent_os_candidate_packet/test_first_packet_approval_lifecycle.py

## Required tests, validation, and documentation
{_TEST}

## Prior scope, duplicate, and supersession review
No duplicate work found; this is a lifecycle fixture.

```yaml
agent_os_issue_acceptance:
  profile_version: issueplan-core/v1
  entity_id: issue-3354-first-packet-lifecycle
  owner_agent: github-service-agent
  source_of_truth: GitHub
  external_writes: none
  required_files:
    - tests/agent_os_candidate_packet/test_first_packet_approval_lifecycle.py
  forbidden_paths:
    - .github/workflows
  required_tests:
    - {_TEST}
  required_docs: []
  manual_review: []
  documentation_impact: docs-not-required
  documentation_expected_change: null
  documentation_exemption_reason: lifecycle regression fixture only
{depends_on_block}
```
"""


def _item(body: str, number: int = _ISSUE_NUMBER, state: str = "open") -> dict:
    return {
        "number": number,
        "title": f"fixture-{number}",
        "state": state,
        "body": body,
        "html_url": f"https://github.com/{_REPOSITORY}/issues/{number}",
        "created_at": "2026-10-01T00:00:00Z",
        "updated_at": "2026-10-02T00:00:00Z",
        "closed_at": None,
        "state_reason": None,
        "labels": ["agent-os"],
    }


class _MapIssueReader:
    def __init__(self, items: dict[tuple[str, int], dict]) -> None:
        self._items = items

    def read_issue(self, repository: str, issue_number: int) -> IssueReadResult:
        item = self._items.get((repository, issue_number))
        if item is None:
            return IssueReadResult(status=IssueReadStatus.NOT_FOUND, item=None)
        return IssueReadResult(status=IssueReadStatus.OK, item=dict(item))


class _PostApprovalReaderMustNotBeConsulted:
    """The deadlock: before #3354 readiness demanded these post-approval owners."""

    def read_dependency_evidence(self, repository: str, issue_number: int):
        raise AssertionError("post-approval dependency evidence consulted pre-approval")

    def read_validation_evidence(self, repository: str, issue_number: int):
        raise AssertionError("post-approval validation evidence consulted pre-approval")


class _PostApprovalReader:
    def __init__(self, dependency: EvidenceStatus, validation: EvidenceStatus) -> None:
        self._dependency = dependency
        self._validation = validation

    def read_dependency_evidence(self, repository: str, issue_number: int):
        return DependencyEvidence(self._dependency)

    def read_validation_evidence(self, repository: str, issue_number: int):
        return ValidationEvidence(self._validation)


def _items(depends_on_block: str = "  depends_on: []", dependencies=()) -> dict:
    items = {(_REPOSITORY, _ISSUE_NUMBER): _item(_body(depends_on_block))}
    for number, state in dependencies:
        items[(_REPOSITORY, number)] = _item(_body(), number=number, state=state)
    return items


def _kwargs(items: dict, **overrides) -> dict[str, object]:
    values: dict[str, object] = dict(
        repository=_REPOSITORY,
        issue_number=_ISSUE_NUMBER,
        issue_reader=_MapIssueReader(items),
        repository_reader=_PostApprovalReaderMustNotBeConsulted(),
        observed_at=_OBSERVED_AT,
        base_branch="main",
        evaluated_repository_sha=_SHA,
        invocation_id="first-packet-lifecycle-3354",
        evaluator_sha=_EVALUATOR_SHA,
        approval_record_exists=False,
    )
    values.update(overrides)
    return values


def _observation(contract_fingerprint: str) -> RepositoryObservation:
    return RepositoryObservation(
        producer_adapter="first-packet-lifecycle-fixture",
        producer_adapter_version="1.0",
        correlation_id=f"issue-{_ISSUE_NUMBER}",
        repository_identity=RepositoryIdentity(
            host="github.com", owner="Blummer92", repository="agent-os", default_branch="main"
        ),
        base_ref="main",
        base_sha="c" * 40,
        head_ref=_BRANCH,
        head_sha=_SHA,
        requested_ref=_BRANCH,
        requested_sha=_SHA,
        observed_sha=_SHA,
        tested_sha=_SHA,
        pushed_sha=None,
        proposed_pr_sha=None,
        synthetic_merge_sha=None,
        external_build_sha=None,
        evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        contract_fingerprint=contract_fingerprint,
        worktree_state=WorktreeState.CLEAN,
        observed_at=_OBSERVED_AT,
        freshness_boundary="main@first-packet-lifecycle",
    )


def _candidate_context() -> ApprovalCandidateContext:
    return ApprovalCandidateContext(
        approval_kind=ApprovalKind.IMPLEMENTATION,
        authorizer_id="candidate-preparer",
        decision_id=f"candidate-{_ISSUE_NUMBER}",
        decision_at="2026-10-08T00:06:00Z",
    )


def _decision(state: ApprovalState = ApprovalState.APPROVED) -> ApprovalDecision:
    return ApprovalDecision(
        state=state,
        decision_id=f"github-comment:{_ISSUE_NUMBER}{state.value}",
        authorizer_id="repository-owner",
        decision_at="2026-10-08T00:07:00Z",
    )


def _approval_ready(items: dict | None = None, **overrides):
    items = items or _items()
    precheck = prepare_candidate_packet(**_kwargs(items))
    return prepare_candidate_packet(
        **_kwargs(
            items,
            repository_observation=_observation(precheck.implementation_contract_fingerprint),
            candidate_context=_candidate_context(),
            **overrides,
        )
    )


# --------------------------------------------------------------------------
# 1, 7: a never-approved Tier-2 candidate reaches the approval decision using
# only pre-approval evidence; the post-approval owners are never consulted.
# --------------------------------------------------------------------------


def test_first_tier2_candidate_reaches_approval_ready_packet() -> None:
    result = _approval_ready()

    assert result.readiness_stage_result.status is IssueReadinessStageStatus.READY
    assert result.proposal_stage_result is not None
    assert result.proposal_stage_result.status is RepositoryProposalStageStatus.ELIGIBLE
    assert result.approval_stage_result is not None
    assert result.approval_stage_result.status is ApprovalProjectionStageStatus.NEEDS_DECISION
    assert result.approval_stage_result.decision_revision is None
    assert result.packet is not None
    assert result.packet.phase is CandidatePacketPhase.APPROVAL_READY
    assert result.disposition == "approval-ready"
    assert result.execution_authorized is False
    assert result.merge_authorized is False
    assert result.side_effects_performed is False


def test_first_packet_marks_post_approval_validation_not_required_not_passed() -> None:
    reasons = _approval_ready().readiness_stage_result.reason_codes

    assert "validation.first-packet-not-required" in reasons
    assert "validation.no-structured-source-configured" not in reasons
    assert "dependency.no-structured-source-configured" not in reasons
    assert "dependency-identity.not-supplied" not in reasons


def test_explicit_owner_decision_completes_projection_from_first_packet_proposal() -> None:
    result = _approval_ready()

    approval = prepare_approval_projection(
        result.proposal_stage_result,
        candidate_context=_candidate_context(),
        approval_decision=_decision(),
        evaluated_at="2026-10-08T00:07:30Z",
        projected_at="2026-10-08T00:07:30Z",
    )

    assert approval.status is ApprovalProjectionStageStatus.COMPLETE
    assert approval.decision_revision is not None
    assert approval.projection is not None


def test_first_packet_execution_candidate_is_built_from_the_same_approved_proposal() -> None:
    """An explicit decision on the same first-packet inputs approves exactly
    the proposal the APPROVAL_READY packet carried."""
    ready = _approval_ready()
    approved = _approval_ready(approval_decision=_decision())

    assert approved.approval_stage_result.status is ApprovalProjectionStageStatus.COMPLETE
    assert dict(approved.packet.stage_identities)["proposal"] == dict(
        ready.packet.stage_identities
    )["proposal"]


# --------------------------------------------------------------------------
# 2, 3: required pre-approval evidence is enforced; missing or invalid
# evidence rejects before any approval-ready packet exists.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("depends_on_block", "dependencies"),
    [
        (f"  depends_on:\n    - {_REPOSITORY}#41", ((41, "open"),)),
        (f"  depends_on:\n    - {_REPOSITORY}#42", ()),
        ("  depends_on:\n    - not-an-identity", ()),
    ],
    ids=["open-dependency", "missing-dependency", "malformed-depends-on"],
)
def test_invalid_pre_approval_dependency_evidence_never_reaches_approval(
    depends_on_block: str, dependencies
) -> None:
    result = _approval_ready(_items(depends_on_block, dependencies))

    assert result.readiness_stage_result.status is not IssueReadinessStageStatus.READY
    assert result.packet is None
    assert result.approval_stage_result.status is ApprovalProjectionStageStatus.INVALID_INPUT


def test_non_strict_issueplan_never_reaches_approval() -> None:
    body = _body().replace("  profile_version: issueplan-core/v1\n", "")
    result = _approval_ready({(_REPOSITORY, _ISSUE_NUMBER): _item(body)})

    assert result.readiness_stage_result.status is not IssueReadinessStageStatus.READY
    assert result.packet is None


def test_caller_supplied_identity_conflicts_with_first_packet_source() -> None:
    supplied = DependencyIdentityEvidence(
        status=DependencyIdentityStatus.ABSENT, provenance=("caller:override",)
    )
    result = _approval_ready(dependency_identity_evidence=supplied)

    assert result.readiness_stage_result.status is IssueReadinessStageStatus.NEEDS_DECISION
    assert result.packet is None


# --------------------------------------------------------------------------
# 4: approval does not automatically grant consumer eligibility.
# --------------------------------------------------------------------------


def test_missing_owner_decision_never_produces_an_execution_candidate() -> None:
    result = _approval_ready(requested_phase=CandidatePacketPhase.EXECUTION_CANDIDATE)

    assert result.packet is None
    assert result.compilation_failure is not None
    assert result.compilation_failure.reason_code == "approval-stage.decision-missing"
    assert result.compilation_failure.external_authorization_required is True
    assert result.execution_authorized is False


def test_rejected_owner_decision_never_completes_projection() -> None:
    result = _approval_ready()

    approval = prepare_approval_projection(
        result.proposal_stage_result,
        candidate_context=_candidate_context(),
        approval_decision=_decision(ApprovalState.REJECTED),
        evaluated_at="2026-10-08T00:07:30Z",
        projected_at="2026-10-08T00:07:30Z",
    )

    assert approval.status is not ApprovalProjectionStageStatus.COMPLETE
    assert approval.projection is None


def test_approved_projection_carries_no_execution_or_merge_authority() -> None:
    approved = _approval_ready(approval_decision=_decision())

    assert approved.approval_stage_result.status is ApprovalProjectionStageStatus.COMPLETE
    assert approved.packet.phase is CandidatePacketPhase.APPROVAL_READY
    assert approved.packet.execution_authorized is False
    assert approved.packet.merge_authorized is False
    assert approved.execution_authorized is False
    assert approved.merge_authorized is False


# --------------------------------------------------------------------------
# 5, 6: once an approval record exists the post-approval owners (#1320) are
# mandatory again, exactly as before #3354.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dependency", "validation"),
    [
        (EvidenceStatus.UNAVAILABLE, EvidenceStatus.RESOLVED_CLEAR),
        (EvidenceStatus.RESOLVED_CLEAR, EvidenceStatus.UNAVAILABLE),
        (EvidenceStatus.RESOLVED_CLEAR, EvidenceStatus.RESOLVED_BLOCKED),
    ],
    ids=["dependency-unavailable", "validation-unavailable", "validation-pending"],
)
def test_post_approval_evidence_remains_mandatory_after_approval(
    dependency: EvidenceStatus, validation: EvidenceStatus
) -> None:
    items = _items()
    precheck = prepare_candidate_packet(**_kwargs(items))
    result = prepare_candidate_packet(
        **_kwargs(
            items,
            repository_reader=_PostApprovalReader(dependency, validation),
            approval_record_exists=True,
            dependency_identity_evidence=precheck.readiness_stage_result.dependency_identity_evidence,
            repository_observation=_observation(precheck.implementation_contract_fingerprint),
            candidate_context=_candidate_context(),
            approval_decision=_decision(),
        )
    )

    assert result.readiness_stage_result.status is IssueReadinessStageStatus.BLOCKED
    assert result.packet is None
    assert "validation.first-packet-not-required" not in (
        result.readiness_stage_result.reason_codes
    )


def test_already_approved_candidate_with_clear_post_approval_evidence_is_unchanged() -> None:
    items = _items()
    precheck = prepare_candidate_packet(**_kwargs(items))
    result = prepare_candidate_packet(
        **_kwargs(
            items,
            repository_reader=_PostApprovalReader(
                EvidenceStatus.RESOLVED_CLEAR, EvidenceStatus.RESOLVED_CLEAR
            ),
            approval_record_exists=True,
            dependency_identity_evidence=precheck.readiness_stage_result.dependency_identity_evidence,
            repository_observation=_observation(precheck.implementation_contract_fingerprint),
            candidate_context=_candidate_context(),
            approval_decision=_decision(),
        )
    )

    assert result.readiness_stage_result.status is IssueReadinessStageStatus.READY
    assert result.approval_stage_result.status is ApprovalProjectionStageStatus.COMPLETE
    assert result.packet is not None
    assert result.packet.phase is CandidatePacketPhase.APPROVAL_READY
