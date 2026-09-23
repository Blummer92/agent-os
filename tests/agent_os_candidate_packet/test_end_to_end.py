"""AOS-AUTO1G end-to-end/adversarial coverage for the #1105 public entrypoint.

Drives the real public pipeline exactly as ``prepare_candidate_packet``
composes it -- no manual identity copying, no fabricated approval/decision,
no reconstruction of a canonical object by hand. Every fixture here builds
only explicit read-only observations (an issue body, a repository
observation, an approval candidate context, a human decision, candidate
runtime inputs) and lets the real #750-#755 stage constructors do the rest.
"""

from __future__ import annotations

import ast
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

from scripts.agent_os_candidate_packet.approval_stage import (  # noqa: E402
    ApprovalCandidateContext,
    ApprovalDecision,
    ApprovalProjectionStageStatus,
)
from scripts.agent_os_candidate_packet.cli import (  # noqa: E402
    PreparedCandidatePacket,
    prepare_candidate_packet,
    prepared_candidate_packet_to_dict,
    render_summary,
)
from scripts.agent_os_candidate_packet.contract_fingerprint import (  # noqa: E402
    compute_implementation_contract_fingerprint,
    derive_canonical_contract,
)
from scripts.agent_os_candidate_packet.models import (  # noqa: E402
    CandidatePacket,
    CandidatePacketPhase,
    deserialize_candidate_packet,
    serialize_candidate_packet,
)
from scripts.agent_os_candidate_packet.proposal_stage import (  # noqa: E402
    RepositoryProposalStageStatus,
)
from scripts.agent_os_candidate_packet.repository_stage import RepositoryObservation  # noqa: E402
from scripts.agent_os_candidate_packet.stage_models import (  # noqa: E402
    DependencyEvidence,
    DependencyIdentityEvidence,
    DependencyIdentityStatus,
    EvidenceStatus,
    IssueReadinessStageStatus,
    IssueReadResult,
    IssueReadStatus,
    IssueSourceReader,
    RepositoryEvidenceReader,
    ValidationEvidence,
)
from scripts.agent_os_candidate_packet.validation_stage import CandidateRuntimeInputs  # noqa: E402
from scripts.agent_os_execution_capabilities import (  # noqa: E402
    RepositoryEvidenceType,
    RepositoryIdentity,
    WorktreeState,
)
from scripts.agent_os_issue_acceptance import ApprovalKind, ApprovalState  # noqa: E402

_COMMAND = "python -m pytest 08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py"
_SHA = "b89de18da472a3cd79877c4f7ee13b49bd7014eb"
_EVALUATOR_SHA = "a" * 40
_BRANCH = "agent/1105-e2e-candidate"
_REPOSITORY = "Blummer92/agent-os"
_ISSUE_NUMBER = 91105

_BODY = f"""Tier: 0

## Objective
Prove #1105 end to end.

## Owner
candidate-packet-agent

## Allowed Files
- 08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py

## Validation
{_COMMAND}

## Completion
Tests pass.

## Prior scope, duplicate, and supersession review
No duplicate work found; this is an end-to-end fixture.

```yaml
agent_os_issue_acceptance:
  profile_version: issueplan-core/v1
  entity_id: issue-1105-e2e
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
    "title": "AOS-AUTO1G end-to-end fixture",
    "state": "open",
    "html_url": f"https://github.com/{_REPOSITORY}/issues/{_ISSUE_NUMBER}",
    "created_at": "2026-08-14T00:00:00Z",
    "updated_at": "2026-08-14T00:00:00Z",
    "body": _BODY,
    "labels": ["agent-os"],
}


class _Reader(IssueSourceReader):
    def __init__(self, item: dict | None = None) -> None:
        self._item = item or dict(_ISSUE_ITEM)

    def read_issue(self, repository: str, issue_number: int) -> IssueReadResult:
        return IssueReadResult(status=IssueReadStatus.OK, item=dict(self._item))


class _RepoReader(RepositoryEvidenceReader):
    def read_dependency_evidence(self, repository: str, issue_number: int) -> DependencyEvidence:
        return DependencyEvidence(status=EvidenceStatus.RESOLVED_CLEAR)

    def read_validation_evidence(self, repository: str, issue_number: int) -> ValidationEvidence:
        return ValidationEvidence(status=EvidenceStatus.RESOLVED_CLEAR)


def _identity(**overrides) -> RepositoryIdentity:
    values = dict(host="github.com", owner="Blummer92", repository="agent-os", default_branch="main")
    values.update(overrides)
    return RepositoryIdentity(**values)


def _observation(**overrides) -> RepositoryObservation:
    values = dict(
        producer_adapter="e2e-fixture",
        producer_adapter_version="1.0",
        correlation_id=f"issue-{_ISSUE_NUMBER}",
        repository_identity=_identity(),
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
        contract_fingerprint=None,
        worktree_state=WorktreeState.CLEAN,
        observed_at="2026-08-14T00:05:00Z",
        freshness_boundary="main@e2e",
    )
    values.update(overrides)
    return RepositoryObservation(**values)


def _dependency_identity() -> DependencyIdentityEvidence:
    return DependencyIdentityEvidence(
        status=DependencyIdentityStatus.ABSENT, provenance=("e2e:no-dependencies",)
    )


def _base_kwargs(**overrides) -> dict[str, object]:
    values = dict(
        repository=_REPOSITORY,
        issue_number=_ISSUE_NUMBER,
        issue_reader=_Reader(),
        repository_reader=_RepoReader(),
        observed_at="2026-08-14T00:05:00Z",
        base_branch="main",
        evaluated_repository_sha=_SHA,
        invocation_id="candidate-packet-e2e-1105",
        evaluator_sha=_EVALUATOR_SHA,
        dependency_identity_evidence=_dependency_identity(),
    )
    values.update(overrides)
    return values


def _observation_with_fingerprint() -> RepositoryObservation:
    precheck = prepare_candidate_packet(**_base_kwargs())
    return _observation(contract_fingerprint=precheck.implementation_contract_fingerprint)


def _candidate_context(**overrides) -> ApprovalCandidateContext:
    values = dict(
        approval_kind=ApprovalKind.IMPLEMENTATION,
        authorizer_id="candidate-preparer",
        decision_id=f"candidate-{_ISSUE_NUMBER}",
        decision_at="2026-08-14T00:06:00Z",
    )
    values.update(overrides)
    return ApprovalCandidateContext(**values)


def _approval_decision(state: ApprovalState = ApprovalState.APPROVED) -> ApprovalDecision:
    return ApprovalDecision(
        state=state,
        decision_id=f"human-{state.value}-{_ISSUE_NUMBER}",
        authorizer_id="repository-owner",
        decision_at="2026-08-14T00:07:00Z",
    )


def _runtime_inputs(evidence, tmp_path, **overrides) -> CandidateRuntimeInputs:
    repository_root = tmp_path / "repo"
    workspace_parent = tmp_path / "worktrees"
    repository_root.mkdir(exist_ok=True)
    workspace_parent.mkdir(exist_ok=True)
    values = dict(
        repository_identity=evidence.repository_identity,
        repository_state_evidence=evidence,
        issue_number=_ISSUE_NUMBER,
        invocation_id="candidate-packet-e2e-1105",
        candidate_branch=_BRANCH,
        candidate_sha="d" * 40,
        tested_sha=evidence.tested_sha,
        evaluator_sha=_EVALUATOR_SHA,
        expected_changed_paths=(
            "08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py",
        ),
        required_tests=(_COMMAND,),
        created_at="2026-08-14T00:08:00Z",
        expires_at="2026-08-14T01:08:00Z",
        evaluated_at="2026-08-14T00:09:00Z",
        repository_root=str(repository_root.resolve()),
        workspace_parent=str(workspace_parent.resolve()),
        validation_bundle_id="validation-bundle:prior-evidence",
        advisory_result_id="advisory-result:prior-evidence",
        advisory_render_id="advisory-render:prior-evidence",
        execution_authorization_present=True,
    )
    values.update(overrides)
    return CandidateRuntimeInputs(**values)


# --------------------------------------------------------------------------
# Natural pipeline: every legitimately available stage, no manual copying.
# --------------------------------------------------------------------------


def test_planning_only_reaches_ready_without_repository_observation() -> None:
    result = prepare_candidate_packet(**_base_kwargs())

    assert isinstance(result, PreparedCandidatePacket)
    assert result.stage_reached == "planning"
    assert result.disposition == "ready"
    assert result.planning_stage_result is not None
    assert result.proposal_stage_result is None
    assert result.packet is None
    assert result.implementation_contract_fingerprint is not None
    assert result.source_revision is not None


def test_issueplanning_context_never_receives_a_caller_invented_fingerprint() -> None:
    """The caller supplies zero fingerprint material anywhere in the call."""
    result = prepare_candidate_packet(**_base_kwargs())
    issueplan = result.readiness_stage_result.issueplan_current_state_evidence

    recomputed = compute_implementation_contract_fingerprint(
        canonical_contract=derive_canonical_contract(
            result.readiness_stage_result.snapshot and issueplan.source_snapshot
        )
    )
    assert issueplan.implementation_contract_fingerprint == recomputed
    assert issueplan.implementation_contract_fingerprint == result.implementation_contract_fingerprint


def test_missing_candidate_context_stops_truthfully_before_approval() -> None:
    """No pending #398 candidate can exist without any ApprovalCandidateContext at all."""
    observation = _observation_with_fingerprint()
    result = prepare_candidate_packet(**_base_kwargs(repository_observation=observation))

    assert result.approval_stage_result is None
    assert result.proposal_stage_result is not None
    assert result.proposal_stage_result.status is RepositoryProposalStageStatus.ELIGIBLE
    assert result.packet is None
    assert result.compilation_failure is not None
    assert result.compilation_failure.reason_code == "approval-stage.missing"
    assert result.disposition == "blocked"


def test_candidate_context_without_decision_reaches_approval_ready_packet() -> None:
    observation = _observation_with_fingerprint()
    result = prepare_candidate_packet(
        **_base_kwargs(
            repository_observation=observation,
            candidate_context=_candidate_context(),
        )
    )

    assert result.approval_stage_result is not None
    assert result.approval_stage_result.status is ApprovalProjectionStageStatus.NEEDS_DECISION
    assert result.approval_stage_result.decision_revision is None
    assert result.packet is not None
    assert result.packet.phase is CandidatePacketPhase.APPROVAL_READY
    assert result.disposition == "approval-ready"


def test_absent_human_decision_never_invents_authority() -> None:
    observation = _observation_with_fingerprint()
    result = prepare_candidate_packet(
        **_base_kwargs(
            repository_observation=observation,
            candidate_context=_candidate_context(),
            requested_phase=CandidatePacketPhase.EXECUTION_CANDIDATE,
        )
    )

    assert result.packet is None
    assert result.compilation_failure is not None
    assert result.compilation_failure.reason_code == "approval-stage.decision-missing"
    assert result.compilation_failure.external_authorization_required is True
    assert result.disposition == "needs-decision"
    assert result.execution_authorized is False
    assert result.side_effects_performed is False


def test_rejected_decision_never_produces_an_execution_candidate_packet() -> None:
    observation = _observation_with_fingerprint()
    result = prepare_candidate_packet(
        **_base_kwargs(
            repository_observation=observation,
            candidate_context=_candidate_context(),
            approval_decision=_approval_decision(ApprovalState.REJECTED),
            requested_phase=CandidatePacketPhase.EXECUTION_CANDIDATE,
        )
    )

    assert result.packet is None
    assert result.compilation_failure is not None
    assert result.compilation_failure.reason_code == "approval-stage.rejected"
    assert result.compilation_failure.external_authorization_required is True


def test_complete_synthetic_fixture_reaches_an_execution_candidate_packet(tmp_path) -> None:
    observation = _observation_with_fingerprint()
    approved_probe = prepare_candidate_packet(
        **_base_kwargs(
            repository_observation=observation,
            candidate_context=_candidate_context(),
            approval_decision=_approval_decision(),
        )
    )
    assert approved_probe.approval_stage_result is not None
    assert approved_probe.approval_stage_result.status is ApprovalProjectionStageStatus.COMPLETE
    evidence = approved_probe.proposal_stage_result.repository_state_evidence
    runtime_inputs = _runtime_inputs(evidence, tmp_path)

    result = prepare_candidate_packet(
        **_base_kwargs(
            repository_observation=observation,
            candidate_context=_candidate_context(),
            approval_decision=_approval_decision(),
            requested_phase=CandidatePacketPhase.EXECUTION_CANDIDATE,
            candidate_runtime_inputs=runtime_inputs,
        )
    )

    assert isinstance(result.packet, CandidatePacket)
    assert result.packet.phase is CandidatePacketPhase.EXECUTION_CANDIDATE
    assert result.packet.command_identities == (_COMMAND,)
    assert result.disposition == "execution-candidate"
    assert result.execution_authorized is False
    assert result.merge_authorized is False
    assert result.automatic_retry is False
    assert result.side_effects_performed is False


# --------------------------------------------------------------------------
# Determinism and serialization.
# --------------------------------------------------------------------------


def test_repeated_immutable_inputs_produce_semantically_identical_output() -> None:
    observation = _observation_with_fingerprint()
    kwargs = _base_kwargs(
        repository_observation=observation, candidate_context=_candidate_context()
    )

    first = prepare_candidate_packet(**kwargs)
    second = prepare_candidate_packet(**kwargs)

    assert first.implementation_contract_fingerprint == second.implementation_contract_fingerprint
    assert first.packet.packet_id == second.packet.packet_id
    assert serialize_candidate_packet(first.packet) == serialize_candidate_packet(second.packet)


def test_packet_serialization_round_trips_exactly() -> None:
    observation = _observation_with_fingerprint()
    result = prepare_candidate_packet(
        **_base_kwargs(repository_observation=observation, candidate_context=_candidate_context())
    )

    payload = serialize_candidate_packet(result.packet)
    rebuilt = deserialize_candidate_packet(payload)

    assert rebuilt == result.packet
    assert serialize_candidate_packet(rebuilt) == payload


def test_json_summary_is_deterministic_and_carries_authority_flags_false() -> None:
    observation = _observation_with_fingerprint()
    result = prepare_candidate_packet(
        **_base_kwargs(repository_observation=observation, candidate_context=_candidate_context())
    )

    payload = prepared_candidate_packet_to_dict(result)
    assert payload == prepared_candidate_packet_to_dict(result)
    assert payload["execution_authorized"] is False
    assert payload["merge_authorized"] is False
    assert payload["automatic_retry"] is False
    assert payload["side_effects_performed"] is False
    assert payload["packet_id"] == result.packet.packet_id


def test_render_summary_never_raises_on_a_blocked_result() -> None:
    result = prepare_candidate_packet(
        **_base_kwargs(
            repository_observation=_observation_with_fingerprint(),
            candidate_context=_candidate_context(),
            requested_phase=CandidatePacketPhase.EXECUTION_CANDIDATE,
        )
    )
    text = render_summary(result)
    assert "blocker:" in text
    assert "execution_authorized=false" in text


# --------------------------------------------------------------------------
# Drift invalidates only the canonical downstream objects #755 already owns.
# --------------------------------------------------------------------------


def test_candidate_sha_drift_invalidates_the_repository_stage() -> None:
    observation = _observation_with_fingerprint()
    drifted = replace(observation, head_sha="f" * 40, requested_sha="f" * 40, observed_sha="f" * 40)

    result = prepare_candidate_packet(
        **_base_kwargs(repository_observation=drifted, candidate_context=_candidate_context())
    )

    assert result.proposal_stage_result.status is not RepositoryProposalStageStatus.ELIGIBLE
    assert result.packet is None


def test_contract_fingerprint_mismatch_on_the_observation_fails_closed() -> None:
    mismatched = _observation(contract_fingerprint="0" * 64)

    result = prepare_candidate_packet(
        **_base_kwargs(repository_observation=mismatched, candidate_context=_candidate_context())
    )

    assert result.proposal_stage_result.status is not RepositoryProposalStageStatus.ELIGIBLE
    assert result.packet is None


# --------------------------------------------------------------------------
# Source-failure boundary.
# --------------------------------------------------------------------------


def test_source_failure_stops_before_any_fingerprint_is_derived() -> None:
    result = prepare_candidate_packet(
        **_base_kwargs(issue_reader=_Reader({"number": _ISSUE_NUMBER}))
    )

    assert result.stage_reached == "readiness"
    assert result.implementation_contract_fingerprint is None
    assert result.readiness_stage_result.status in (
        IssueReadinessStageStatus.SOURCE_FAILURE,
        IssueReadinessStageStatus.INCOMPLETE_EVIDENCE,
    )


# --------------------------------------------------------------------------
# Architecture boundaries for the two new #1105 production files.
# --------------------------------------------------------------------------

_NEW_MODULES = (
    REPOSITORY_ROOT / "scripts/agent_os_candidate_packet/contract_fingerprint.py",
    REPOSITORY_ROOT / "scripts/agent_os_candidate_packet/cli.py",
)
_FORBIDDEN_IMPORT_PREFIXES = (
    "subprocess",
    "socket",
    "urllib",
    "requests",
    "git",
    "github",
    "google",
    "googleapiclient",
    "notion_client",
    "workflow_scheduler.execution.executor",
    "workflow_scheduler.execution.lease",
    "workflow_scheduler.execution.worktree",
)


@pytest.mark.parametrize("path", _NEW_MODULES)
def test_module_imports_no_forbidden_capability(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    for name in names:
        for forbidden in _FORBIDDEN_IMPORT_PREFIXES:
            assert not name.startswith(forbidden), f"{path.name} imports forbidden module {name!r}"


@pytest.mark.parametrize("path", _NEW_MODULES)
def test_module_contains_no_subprocess_or_network_calls(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    for banned in (
        "subprocess.",
        "os.system(",
        "os.popen(",
        "socket.socket",
        "urlopen(",
        "shutil.rmtree",
    ):
        assert banned not in source, f"{path.name} contains banned call {banned!r}"


def test_cli_module_reaches_no_scheduler_execution_import() -> None:
    """``cli.py`` only reaches the execution-service lazily, and never a runtime adapter."""
    source = (REPOSITORY_ROOT / "scripts/agent_os_candidate_packet/cli.py").read_text(
        encoding="utf-8"
    )
    assert "workflow_scheduler.execution.executor" not in source
    assert "workflow_scheduler.execution.lease" not in source
    assert "workflow_scheduler.execution.worktree" not in source
