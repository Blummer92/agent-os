"""#3690: prepare_candidate_packet runs the readiness stage exactly once.

Before this change the entrypoint ran ``prepare_issue_readiness`` twice:
Pass 1 without a planning context (only to derive the implementation
contract fingerprint) and Pass 2 with that context. The context reaches
only six fields of the IssuePlan evidence, so Pass 2 re-read the issue,
re-scanned the IssuePlan, re-read dependency/validation evidence, and
re-evaluated readiness to change one object -- and silently mixed two
lineages if a live reader changed between passes. The entrypoint now
projects the derived context into the Pass 1 evidence, recomputing its
identity from the projected payload, and carries the single snapshot,
readiness result, and dependency-identity evidence forward.

These tests pin that behavior, and pin equivalence with the old second
pass: the projected evidence must be exactly what a direct
``prepare_issue_readiness(..., planning_context=...)`` call produces on
the same snapshot. They are not a substitute for independent QA or
exact-head CI.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXECUTION_SERVICE_SRC = REPOSITORY_ROOT / "08_Tooling/agent-os-execution-service/src"
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
for _path in (EXECUTION_SERVICE_SRC, SCHEDULER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402

from scripts.agent_os_candidate_packet.cli import prepare_candidate_packet  # noqa: E402
from scripts.agent_os_candidate_packet.contract_fingerprint import (  # noqa: E402
    compute_implementation_contract_fingerprint,
    derive_canonical_contract,
)
from scripts.agent_os_candidate_packet.readiness_stage import (  # noqa: E402
    prepare_issue_readiness,
)
from scripts.agent_os_candidate_packet.stage_models import (  # noqa: E402
    DependencyEvidence,
    DependencyIdentityEvidence,
    DependencyIdentityStatus,
    EvidenceStatus,
    IssuePlanningContext,
    IssueReadinessStageRequest,
    IssueReadResult,
    IssueReadStatus,
    IssueSourceReader,
    RepositoryEvidenceReader,
    ValidationEvidence,
)
from scripts.agent_os_issue_acceptance.issueplan_current_state import (  # noqa: E402
    compute_issueplan_current_state_fingerprint,
    project_planning_context,
)

_COMMAND = "python -m pytest 08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py"
_SHA = "b89de18da472a3cd79877c4f7ee13b49bd7014eb"
_REPOSITORY = "Blummer92/agent-os"
_ISSUE_NUMBER = 91105

_BODY = f"""Tier: 0

## Objective
Prove #3690 single readiness pass.

## Owner
candidate-packet-agent

## Allowed Files
- 08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py

## Validation
{_COMMAND}

## Completion
Tests pass.

## Prior scope, duplicate, and supersession review
No duplicate work found; this is a single-pass fixture.

```yaml
agent_os_issue_acceptance:
  profile_version: issueplan-core/v1
  entity_id: issue-3690-single-pass
  owner_agent: integration-manager
  source_of_truth: GitHub
  external_writes: none
  required_files:
    - 08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py
  forbidden_paths:
    - .github/workflows
  required_tests:
    - {_COMMAND}
  required_docs: []
  manual_review: []
  documentation_impact: docs-not-required
  documentation_expected_change: null
  documentation_exemption_reason: no docs needed
```
"""

_ISSUE_ITEM = {
    "number": _ISSUE_NUMBER,
    "title": "#3690 single readiness pass fixture",
    "state": "open",
    "html_url": f"https://github.com/{_REPOSITORY}/issues/{_ISSUE_NUMBER}",
    "created_at": "2026-08-14T00:00:00Z",
    "updated_at": "2026-08-14T00:00:00Z",
    "body": _BODY,
    "labels": ["agent-os"],
}


class _CountingReader(IssueSourceReader):
    def __init__(self, *, mutate_on_second_read: bool = False) -> None:
        self.reads = 0
        self._mutate = mutate_on_second_read

    def read_issue(self, repository: str, issue_number: int) -> IssueReadResult:
        self.reads += 1
        item = dict(_ISSUE_ITEM)
        if self._mutate and self.reads > 1:
            item["body"] = _BODY + "\n\n## Changed\nA second read would silently change the lineage.\n"
        return IssueReadResult(status=IssueReadStatus.OK, item=item)


class _CountingRepoReader(RepositoryEvidenceReader):
    def __init__(self) -> None:
        self.dependency_reads = 0
        self.validation_reads = 0

    def read_dependency_evidence(self, repository: str, issue_number: int) -> DependencyEvidence:
        self.dependency_reads += 1
        return DependencyEvidence(status=EvidenceStatus.RESOLVED_CLEAR)

    def read_validation_evidence(self, repository: str, issue_number: int) -> ValidationEvidence:
        self.validation_reads += 1
        return ValidationEvidence(status=EvidenceStatus.RESOLVED_CLEAR)


def _base_kwargs(issue_reader, repository_reader, **overrides):
    values = dict(
        repository=_REPOSITORY,
        issue_number=_ISSUE_NUMBER,
        issue_reader=issue_reader,
        repository_reader=repository_reader,
        observed_at="2026-08-14T00:05:00Z",
        base_branch="main",
        evaluated_repository_sha=_SHA,
        invocation_id="candidate-packet-3690-single-pass",
        evaluator_sha="a" * 40,
        dependency_identity_evidence=DependencyIdentityEvidence(
            status=DependencyIdentityStatus.ABSENT,
            provenance=("single-pass:no-dependencies",),
        ),
    )
    values.update(overrides)
    return values


def _old_second_pass(issue_reader, repository_reader, *, approval_record_exists, dependency_identity_evidence):
    """Reproduce the pre-#3690 second readiness pass on fresh readers."""
    precheck = prepare_issue_readiness(
        IssueReadinessStageRequest(
            repository=_REPOSITORY,
            issue_number=_ISSUE_NUMBER,
            observed_at="2026-08-14T00:05:00Z",
            approval_record_exists=approval_record_exists,
        ),
        issue_reader,
        repository_reader,
        dependency_identity_evidence=dependency_identity_evidence,
        planning_context=None,
    )
    assert precheck.issueplan_current_state_evidence is not None
    assert precheck.snapshot is not None
    canonical_contract = derive_canonical_contract(
        precheck.issueplan_current_state_evidence.source_snapshot
    )
    fingerprint = compute_implementation_contract_fingerprint(
        canonical_contract=canonical_contract
    )
    context = IssuePlanningContext(
        repository=_REPOSITORY,
        base_branch="main",
        evaluated_repository_sha=_SHA,
        implementation_contract_fingerprint=fingerprint,
        allowed_files=tuple(canonical_contract["allowed_files"]),
        forbidden_paths=tuple(canonical_contract["forbidden_paths"]),
        required_tests=tuple(canonical_contract["required_tests"]),
        provenance=(
            f"agent-os-candidate-packet-cli:{_REPOSITORY}#{_ISSUE_NUMBER}"
            f"@{precheck.snapshot.source_revision}",
        ),
    )
    return prepare_issue_readiness(
        IssueReadinessStageRequest(
            repository=_REPOSITORY,
            issue_number=_ISSUE_NUMBER,
            observed_at="2026-08-14T00:05:00Z",
            approval_record_exists=approval_record_exists,
        ),
        issue_reader,
        repository_reader,
        dependency_identity_evidence=dependency_identity_evidence,
        planning_context=context,
    )


def test_prepare_candidate_packet_reads_issue_and_evidence_exactly_once() -> None:
    issue_reader = _CountingReader()
    repository_reader = _CountingRepoReader()
    result = prepare_candidate_packet(**_base_kwargs(issue_reader, repository_reader))

    assert result.readiness_stage_result is not None
    assert result.readiness_stage_result.status.value == "ready"
    # One readiness pass, not two: one issue read and one of each
    # repository evidence read per packet preparation.
    assert issue_reader.reads == 1
    assert repository_reader.dependency_reads == 1
    assert repository_reader.validation_reads == 1

    evidence = result.readiness_stage_result.issueplan_current_state_evidence
    assert evidence is not None
    # The derived context is present in the single-pass evidence, so
    # planning could run (it requires base_branch and evaluated SHA).
    assert evidence.base_branch == "main"
    assert evidence.evaluated_repository_sha == _SHA
    assert evidence.implementation_contract_fingerprint == (
        result.implementation_contract_fingerprint
    )
    assert evidence.allowed_files == (
        "08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py",
    )
    assert evidence.forbidden_paths == (".github/workflows",)
    assert evidence.required_tests == (_COMMAND,)
    assert evidence.evidence_id == (
        f"issueplan-current-state:{compute_issueplan_current_state_fingerprint(evidence)}"
    )
    assert result.planning_stage_result is not None
    assert result.planning_stage_result.status.value == "ready"


def test_single_pass_evidence_equals_old_second_pass_evidence() -> None:
    """Projected Pass 1 evidence == a direct Pass 2 readiness call.

    This is the equivalence proof for the consolidation: same snapshot,
    same planning context, same reader fixture -- the old second pass
    and the new projection must produce identical IssuePlan evidence,
    readiness results, and snapshots.
    """
    result = prepare_candidate_packet(
        **_base_kwargs(_CountingReader(), _CountingRepoReader())
    )
    readiness = result.readiness_stage_result
    assert readiness is not None
    assert readiness.issueplan_current_state_evidence is not None

    # Rebuild the planning context exactly as the entrypoint derives it.
    precheck = prepare_issue_readiness(
        IssueReadinessStageRequest(
            repository=_REPOSITORY,
            issue_number=_ISSUE_NUMBER,
            observed_at="2026-08-14T00:05:00Z",
            approval_record_exists=True,
        ),
        _CountingReader(),
        _CountingRepoReader(),
        dependency_identity_evidence=DependencyIdentityEvidence(
            status=DependencyIdentityStatus.ABSENT,
            provenance=("single-pass:no-dependencies",),
        ),
        planning_context=None,
    )
    assert precheck.issueplan_current_state_evidence is not None
    canonical_contract = derive_canonical_contract(
        precheck.issueplan_current_state_evidence.source_snapshot
    )
    fingerprint = compute_implementation_contract_fingerprint(
        canonical_contract=canonical_contract
    )
    context = IssuePlanningContext(
        repository=_REPOSITORY,
        base_branch="main",
        evaluated_repository_sha=_SHA,
        implementation_contract_fingerprint=fingerprint,
        allowed_files=tuple(canonical_contract["allowed_files"]),
        forbidden_paths=tuple(canonical_contract["forbidden_paths"]),
        required_tests=tuple(canonical_contract["required_tests"]),
        provenance=(
            f"agent-os-candidate-packet-cli:{_REPOSITORY}#{_ISSUE_NUMBER}"
            f"@{precheck.snapshot.source_revision}",
        ),
    )
    old_second_pass = prepare_issue_readiness(
        IssueReadinessStageRequest(
            repository=_REPOSITORY,
            issue_number=_ISSUE_NUMBER,
            observed_at="2026-08-14T00:05:00Z",
            approval_record_exists=True,
        ),
        _CountingReader(),
        _CountingRepoReader(),
        dependency_identity_evidence=DependencyIdentityEvidence(
            status=DependencyIdentityStatus.ABSENT,
            provenance=("single-pass:no-dependencies",),
        ),
        planning_context=context,
    )

    assert readiness.issueplan_current_state_evidence == (
        old_second_pass.issueplan_current_state_evidence
    )
    assert readiness.readiness_result == old_second_pass.readiness_result
    assert readiness.snapshot == old_second_pass.snapshot
    assert readiness.reason_codes == old_second_pass.reason_codes
    assert readiness.dependency_identity_evidence == (
        old_second_pass.dependency_identity_evidence
    )


def test_single_snapshot_survives_a_reader_that_changes_on_second_read() -> None:
    """A live reader change must not silently mix two lineages.

    Under the old double pass, a second read with different body text
    would have produced readiness from the new snapshot while the
    contract fingerprint still came from the first. The single pass
    keeps the first snapshot for the whole packet.
    """
    issue_reader = _CountingReader(mutate_on_second_read=True)
    result = prepare_candidate_packet(
        **_base_kwargs(issue_reader, _CountingRepoReader())
    )
    assert issue_reader.reads == 1
    assert result.readiness_stage_result is not None
    assert result.readiness_stage_result.snapshot is not None
    assert result.readiness_stage_result.snapshot.body == _BODY
    assert "Changed" not in result.readiness_stage_result.snapshot.body


def test_project_planning_context_rejects_a_forged_evidence_id() -> None:
    precheck = prepare_issue_readiness(
        IssueReadinessStageRequest(
            repository=_REPOSITORY,
            issue_number=_ISSUE_NUMBER,
            observed_at="2026-08-14T00:05:00Z",
            approval_record_exists=True,
        ),
        _CountingReader(),
        _CountingRepoReader(),
        dependency_identity_evidence=DependencyIdentityEvidence(
            status=DependencyIdentityStatus.ABSENT,
            provenance=("single-pass:no-dependencies",),
        ),
        planning_context=None,
    )
    evidence = precheck.issueplan_current_state_evidence
    assert evidence is not None
    forged = replace(evidence, evidence_id="issueplan-current-state:" + "0" * 64)
    with pytest.raises(ValueError, match="evidence_id does not match"):
        project_planning_context(
            forged,
            base_branch="main",
            evaluated_repository_sha=_SHA,
            implementation_contract_fingerprint="0" * 64,
            allowed_files=(),
            forbidden_paths=(),
            required_tests=(),
        )


def test_project_planning_context_changes_only_context_fields() -> None:
    precheck = prepare_issue_readiness(
        IssueReadinessStageRequest(
            repository=_REPOSITORY,
            issue_number=_ISSUE_NUMBER,
            observed_at="2026-08-14T00:05:00Z",
            approval_record_exists=True,
        ),
        _CountingReader(),
        _CountingRepoReader(),
        dependency_identity_evidence=DependencyIdentityEvidence(
            status=DependencyIdentityStatus.ABSENT,
            provenance=("single-pass:no-dependencies",),
        ),
        planning_context=None,
    )
    evidence = precheck.issueplan_current_state_evidence
    assert evidence is not None
    projected = project_planning_context(
        evidence,
        base_branch="main",
        evaluated_repository_sha=_SHA,
        implementation_contract_fingerprint="f" * 64,
        allowed_files=("a.py",),
        forbidden_paths=(".github/workflows",),
        required_tests=("pytest a",),
    )
    assert projected.evidence_id != evidence.evidence_id
    assert projected.evidence_id == (
        f"issueplan-current-state:{compute_issueplan_current_state_fingerprint(projected)}"
    )
    # Every non-context field is byte-identical to the input evidence.
    restored = replace(
        projected,
        base_branch=evidence.base_branch,
        evaluated_repository_sha=evidence.evaluated_repository_sha,
        implementation_contract_fingerprint=evidence.implementation_contract_fingerprint,
        allowed_files=evidence.allowed_files,
        forbidden_paths=evidence.forbidden_paths,
        required_tests=evidence.required_tests,
        evidence_id=evidence.evidence_id,
    )
    assert restored == evidence


def test_first_packet_single_pass_matches_old_second_pass() -> None:
    """First-packet mode (approval_record_exists=False) is also single-pass.

    In first-packet mode the caller supplies no dependency identities, so
    the stage derives them from the IssuePlan; with no dependencies
    declared, that is one issue read total, not two.
    """
    issue_reader = _CountingReader()
    result = prepare_candidate_packet(
        **_base_kwargs(
            issue_reader,
            _CountingRepoReader(),
            approval_record_exists=False,
            dependency_identity_evidence=None,
        )
    )
    readiness = result.readiness_stage_result
    assert readiness is not None
    assert readiness.status.value == "ready"
    assert issue_reader.reads == 1

    old = _old_second_pass(
        _CountingReader(),
        _CountingRepoReader(),
        approval_record_exists=False,
        dependency_identity_evidence=None,
    )
    assert readiness.issueplan_current_state_evidence == (
        old.issueplan_current_state_evidence
    )
    assert readiness.readiness_result == old.readiness_result
    assert readiness.snapshot == old.snapshot


def test_blocked_single_pass_matches_old_second_pass() -> None:
    """A BLOCKED readiness outcome also projects, unchanged, from Pass 1."""

    class _BlockedRepoReader(RepositoryEvidenceReader):
        def __init__(self) -> None:
            self.dependency_reads = 0
            self.validation_reads = 0

        def read_dependency_evidence(self, repository, issue_number):
            self.dependency_reads += 1
            return DependencyEvidence(
                status=EvidenceStatus.RESOLVED_BLOCKED,
                reason_codes=("dependency.blocked",),
            )

        def read_validation_evidence(self, repository, issue_number):
            self.validation_reads += 1
            return ValidationEvidence(status=EvidenceStatus.RESOLVED_CLEAR)

    issue_reader = _CountingReader()
    repository_reader = _BlockedRepoReader()
    result = prepare_candidate_packet(
        **_base_kwargs(issue_reader, repository_reader)
    )
    readiness = result.readiness_stage_result
    assert readiness is not None
    assert readiness.status.value == "blocked"
    assert issue_reader.reads == 1
    assert repository_reader.dependency_reads == 1
    assert repository_reader.validation_reads == 1

    old = _old_second_pass(
        _CountingReader(),
        _BlockedRepoReader(),
        approval_record_exists=True,
        dependency_identity_evidence=DependencyIdentityEvidence(
            status=DependencyIdentityStatus.ABSENT,
            provenance=("single-pass:no-dependencies",),
        ),
    )
    assert readiness.issueplan_current_state_evidence == (
        old.issueplan_current_state_evidence
    )
    assert readiness.readiness_result == old.readiness_result


@pytest.mark.parametrize(
    "overrides",
    [
        {"base_branch": ""},
        {"evaluated_repository_sha": "g" * 40},
        {"evaluated_repository_sha": "a" * 39},
        {"implementation_contract_fingerprint": "f" * 63},
        {"allowed_files": "abc"},
        {"forbidden_paths": "abc"},
        {"required_tests": "abc"},
    ],
)
def test_project_planning_context_rejects_malformed_context(overrides) -> None:
    precheck = prepare_issue_readiness(
        IssueReadinessStageRequest(
            repository=_REPOSITORY,
            issue_number=_ISSUE_NUMBER,
            observed_at="2026-08-14T00:05:00Z",
            approval_record_exists=True,
        ),
        _CountingReader(),
        _CountingRepoReader(),
        dependency_identity_evidence=DependencyIdentityEvidence(
            status=DependencyIdentityStatus.ABSENT,
            provenance=("single-pass:no-dependencies",),
        ),
        planning_context=None,
    )
    evidence = precheck.issueplan_current_state_evidence
    assert evidence is not None
    values = dict(
        base_branch="main",
        evaluated_repository_sha=_SHA,
        implementation_contract_fingerprint="f" * 64,
        allowed_files=("a.py",),
        forbidden_paths=(".github/workflows",),
        required_tests=("pytest a",),
    )
    values.update(overrides)
    with pytest.raises((TypeError, ValueError)):
        project_planning_context(evidence, **values)
