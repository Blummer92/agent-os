"""#3413 post-approval custody re-verification tests (execution service).

Covers decision point 3's consumer helper
(``post_approval_dependency_identity_evidence``) and the full custody chain
for a first-packet-approved candidate: first-packet APPROVAL_READY ->
explicit owner approval -> EXECUTION_CANDIDATE -> custody, for both the
current identity composition and the explicit legacy compatibility path.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
EXECUTION_SERVICE_SRC = REPOSITORY_ROOT / "08_Tooling/agent-os-execution-service/src"
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
for _path in (REPOSITORY_ROOT, EXECUTION_SERVICE_SRC, SCHEDULER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402

from agent_os_execution_service.candidate_approval_provenance import (  # noqa: E402
    append_candidate_approval_provenance,
    build_candidate_approval_provenance,
)
from agent_os_execution_service.execution_authorization_source import (  # noqa: E402
    ExecutionAuthorizationCommentSnapshot,
    ExecutionAuthorizationSourceSnapshot,
)
from agent_os_execution_service.human_approval_custody import (  # noqa: E402
    HumanApprovalCustodyError,
    produce_human_approval_custody,
)
from agent_os_execution_service.post_approval_dependency_identities import (  # noqa: E402
    post_approval_dependency_identity_evidence,
)
from agent_os_execution_service.production_host_bootstrap import (  # noqa: E402
    ProductionHostConfiguration,
)
from scripts.agent_os_candidate_packet.approval_stage import (  # noqa: E402
    ApprovalProjectionStageStatus,
    prepare_approval_projection,
)
from scripts.agent_os_candidate_packet.cli import prepare_candidate_packet  # noqa: E402
from scripts.agent_os_candidate_packet.models import CandidatePacketPhase  # noqa: E402
from scripts.agent_os_candidate_packet.stage_models import (  # noqa: E402
    DependencyEvidence,
    DependencyIdentityStatus,
    EvidenceStatus,
    IssueReadResult,
    IssueReadStatus,
    ValidationEvidence,
)
from scripts.agent_os_candidate_packet.validation_stage import (  # noqa: E402
    CandidateRuntimeInputs,
)
from scripts.agent_os_issue_acceptance import ApprovalState  # noqa: E402
from tests.agent_os_candidate_packet.test_first_packet_approval_lifecycle import (  # noqa: E402
    _REPOSITORY,
    _ISSUE_NUMBER,
    _SHA,
    _EVALUATOR_SHA,
    _BRANCH,
    _OBSERVED_AT,
    _TEST,
    _body,
    _candidate_context,
    _decision,
    _item,
    _items,
    _kwargs,
    _observation,
    _MapIssueReader,
    _PostApprovalReader,
)

_OWNER = "Blummer92"

# The pre-PR validation rule map has focused coverage for
# 08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py but not
# for the lifecycle fixture's own path. The custody proof reuses the
# first-packet fixture's approval shape with rule-map-covered file/test
# identities; the #3413 identity logic does not depend on which files change.
_COVERED_FILE = "08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py"
_COVERED_TEST = f"python -m pytest {_COVERED_FILE}"


def _custody_body() -> str:
    return _body().replace(
        "tests/agent_os_candidate_packet/test_first_packet_approval_lifecycle.py",
        _COVERED_FILE,
    ).replace(_TEST, _COVERED_TEST)


def _custody_items() -> dict:
    return {(_REPOSITORY, _ISSUE_NUMBER): _item(_custody_body())}


class _OwnerTransport:
    """Single exact owner approval command, mirroring the custody contract."""

    def __init__(self, provenance_id: str) -> None:
        self._provenance_id = provenance_id

    def read_authorization_source(self, repository: str, issue_number: int):
        return ExecutionAuthorizationSourceSnapshot(
            repository=repository,
            issue_number=issue_number,
            owner_login=_OWNER,
            owner_type="User",
            comments_complete=True,
            comments=(
                ExecutionAuthorizationCommentSnapshot(
                    comment_id=4242,
                    author_login=_OWNER,
                    created_at="2026-10-08T00:07:00Z",
                    body=f"/agent-os approve-candidate {self._provenance_id}",
                ),
            ),
        )


def _config(tmp_path: Path) -> ProductionHostConfiguration:
    root = tmp_path / "host"
    (root / "checkpoints").mkdir(parents=True)
    (root / "repo").mkdir(parents=True)
    (root / "worktrees").mkdir(parents=True)
    (root / "leases").mkdir(parents=True)
    return ProductionHostConfiguration(
        checkpoint_store_root=root / "checkpoints",
        repository_root=root / "repo",
        workspace_parent=root / "worktrees",
        lease_directory=root / "leases",
        delegated_parent_cgroup=None,
        repository_host="github.com",
    )


def _runtime_inputs(evidence, config: ProductionHostConfiguration, invocation_id: str) -> CandidateRuntimeInputs:
    return CandidateRuntimeInputs(
        repository_identity=evidence.repository_identity,
        repository_state_evidence=evidence,
        issue_number=_ISSUE_NUMBER,
        invocation_id=invocation_id,
        candidate_branch=_BRANCH,
        candidate_sha=_SHA,
        tested_sha=evidence.tested_sha,
        evaluator_sha=_EVALUATOR_SHA,
        expected_changed_paths=(),
        required_tests=(_COVERED_TEST,),
        created_at="2026-10-08T00:08:00Z",
        expires_at="2026-10-08T01:08:00Z",
        evaluated_at="2026-10-08T00:09:00Z",
        repository_root=str(config.repository_root.resolve()),
        workspace_parent=str(config.workspace_parent.resolve()),
        validation_bundle_id="validation-bundle:custody-3413",
        advisory_result_id="advisory-result:custody-3413",
        advisory_render_id="advisory-render:custody-3413",
        execution_authorization_present=True,
    )


def _seed_provenance(config: ProductionHostConfiguration, ready, proposal_stage):
    provenance = build_candidate_approval_provenance(
        approval_ready_packet=ready.packet,
        candidate_context=_candidate_context(),
        repository_proposal_stage_result=proposal_stage,
    )
    append_candidate_approval_provenance(
        config.checkpoint_store_root, provenance
    )
    return provenance


def _custody_ready(items: dict, identity_composition: str = "current"):
    """One first-packet APPROVAL_READY packet plus an explicit owner approval."""
    precheck = prepare_candidate_packet(**_kwargs(items))
    ready = prepare_candidate_packet(
        **_kwargs(
            items,
            repository_observation=_observation(precheck.implementation_contract_fingerprint),
            candidate_context=_candidate_context(),
            **({"identity_composition": identity_composition} if identity_composition != "current" else {}),
        )
    )
    assert ready.disposition == "approval-ready"
    observation = _observation(ready.implementation_contract_fingerprint)
    projection = prepare_approval_projection(
        ready.proposal_stage_result,
        candidate_context=_candidate_context(),
        approval_decision=_decision(ApprovalState.APPROVED),
        evaluated_at="2026-10-08T00:07:00Z",
        projected_at="2026-10-08T00:08:00Z",
    )
    assert projection.status is ApprovalProjectionStageStatus.COMPLETE
    return ready, observation


def _custody(tmp_path: Path, identity_composition: str = "current") -> str:
    config = _config(tmp_path)
    items = _custody_items()
    ready, observation = _custody_ready(items, identity_composition)
    provenance = _seed_provenance(
        config, ready, ready.proposal_stage_result
    )
    runtime_inputs = _runtime_inputs(
        ready.proposal_stage_result.repository_state_evidence,
        config,
        ready.packet.invocation_id,
    )
    return produce_human_approval_custody(
        candidate_provenance_id=provenance.evidence_id,
        transport=_OwnerTransport(provenance.evidence_id),
        issue_reader=_MapIssueReader(items),
        repository_reader=_PostApprovalReader(
            EvidenceStatus.RESOLVED_CLEAR, EvidenceStatus.RESOLVED_CLEAR
        ),
        repository_observation=observation,
        candidate_runtime_inputs=runtime_inputs,
        observed_at=_OBSERVED_AT,
        configuration=config,
    )


# --------------------------------------------------------------------------
# Point 3 helper: structured IssuePlan depends_on, nothing else.
# --------------------------------------------------------------------------


def test_helper_resolves_declared_identities() -> None:
    items = _items(
        f"  depends_on:\n    - {_REPOSITORY}#41", ((41, "closed"),)
    )
    evidence = post_approval_dependency_identity_evidence(
        issue_reader=_MapIssueReader(items),
        repository=_REPOSITORY,
        issue_number=_ISSUE_NUMBER,
        observed_at=_OBSERVED_AT,
    )
    assert evidence is not None
    assert evidence.status is DependencyIdentityStatus.RESOLVED
    assert evidence.dependency_ids == (f"{_REPOSITORY}#41",)
    assert evidence.provenance[0].startswith("issueplan:depends_on@github:")


def test_helper_reports_absent_when_no_depends_on() -> None:
    evidence = post_approval_dependency_identity_evidence(
        issue_reader=_MapIssueReader(_items()),
        repository=_REPOSITORY,
        issue_number=_ISSUE_NUMBER,
        observed_at=_OBSERVED_AT,
    )
    assert evidence is not None
    assert evidence.status is DependencyIdentityStatus.ABSENT
    assert evidence.dependency_ids == ()


def test_helper_returns_none_for_non_strict_issueplan() -> None:
    items = {(_REPOSITORY, _ISSUE_NUMBER): _item("not an issueplan")}
    evidence = post_approval_dependency_identity_evidence(
        issue_reader=_MapIssueReader(items),
        repository=_REPOSITORY,
        issue_number=_ISSUE_NUMBER,
        observed_at=_OBSERVED_AT,
    )
    assert evidence is None


def test_helper_marks_malformed_depends_on_unavailable() -> None:
    items = _items("  depends_on: not-a-list")
    evidence = post_approval_dependency_identity_evidence(
        issue_reader=_MapIssueReader(items),
        repository=_REPOSITORY,
        issue_number=_ISSUE_NUMBER,
        observed_at=_OBSERVED_AT,
    )
    assert evidence is not None
    assert evidence.status is DependencyIdentityStatus.UNAVAILABLE
    assert "dependency-identity.malformed-source" in evidence.reason_codes


def test_helper_returns_none_when_issue_unreadable() -> None:
    class _ExplodingReader:
        def read_issue(self, repository: str, issue_number: int) -> IssueReadResult:
            raise RuntimeError("boom")

    evidence = post_approval_dependency_identity_evidence(
        issue_reader=_ExplodingReader(),
        repository=_REPOSITORY,
        issue_number=_ISSUE_NUMBER,
        observed_at=_OBSERVED_AT,
    )
    assert evidence is None


# --------------------------------------------------------------------------
# Full custody chain for a first-packet-approved candidate.
# --------------------------------------------------------------------------


def test_first_packet_approved_candidate_reaches_custody(tmp_path: Path) -> None:
    """The #3413 repro, now fixed: custody verifies a first-packet approval."""
    capsule_id = _custody(tmp_path)
    assert capsule_id.startswith("pre-publication-evidence:")


def test_legacy_first_packet_approved_candidate_reaches_custody(
    tmp_path: Path,
) -> None:
    """A pre-#3413-composed approval reaches custody via the explicit path."""
    capsule_id = _custody(tmp_path, identity_composition="legacy")
    assert capsule_id.startswith("pre-publication-evidence:")


def test_custody_still_fails_closed_on_genuine_drift(tmp_path: Path) -> None:
    """A changed IssuePlan after approval still fails closed, not legacy."""
    config = _config(tmp_path)
    items = _custody_items()
    ready, observation = _custody_ready(items)
    provenance = _seed_provenance(config, ready, ready.proposal_stage_result)
    runtime_inputs = _runtime_inputs(
        ready.proposal_stage_result.repository_state_evidence,
        config,
        ready.packet.invocation_id,
    )
    changed = dict(items)
    changed[(_REPOSITORY, _ISSUE_NUMBER)] = _item(
        _custody_body().replace("First never-approved", "First never-approved CHANGED")
    )
    with pytest.raises(HumanApprovalCustodyError, match="candidate-provenance-drift"):
        produce_human_approval_custody(
            candidate_provenance_id=provenance.evidence_id,
            transport=_OwnerTransport(provenance.evidence_id),
            issue_reader=_MapIssueReader(changed),
            repository_reader=_PostApprovalReader(
                EvidenceStatus.RESOLVED_CLEAR, EvidenceStatus.RESOLVED_CLEAR
            ),
            repository_observation=observation,
            candidate_runtime_inputs=runtime_inputs,
            observed_at=_OBSERVED_AT,
            configuration=config,
        )
