from __future__ import annotations

import ast
import inspect
import socket
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.agent_os_execution_capabilities import (
    CAPABILITY_EVIDENCE_SCHEMA_NAME,
    CAPABILITY_EVIDENCE_SCHEMA_VERSION,
    RepositoryEvidenceType,
    RepositoryIdentity,
    RepositoryStateEvidence,
    WorktreeState,
)
from scripts.agent_os_issue_acceptance import (
    HandoffCohort,
    SchedulerPlanningHandoff,
    build_issueplan_current_state_evidence,
    compute_handoff_digest,
)
from scripts.agent_os_issue_acceptance.issueplan_scanner import (
    AdoptionClass,
    MetadataCandidate,
    ScanResult,
    SourceEnvelope,
)
from workflow_scheduler.planning import (
    DraftTaskProposal,
    build_draft_task_proposals,
)
from workflow_scheduler.planning import draft_ingestion

HEAD_SHA = "a" * 40
BASE_SHA = "b" * 40
MERGE_SHA = "c" * 40
EVALUATOR_SHA = "d" * 40
GRAPH_DIGEST = "1" * 64
PLANNING_DIGEST = "2" * 64
CONTRACT_DIGEST = "3" * 64
CREATED_AT = "2026-07-20T12:00:00Z"


def _handoff(*, evaluated_sha=HEAD_SHA, **changes):
    payload = {
        "contract_version": "0.2.0",
        "planning_result_version": "0.1.0",
        "evaluator_commit_sha": EVALUATOR_SHA,
        "repository": "Blummer92/agent-os",
        "base_branch": "main",
        "evaluated_repository_sha": evaluated_sha,
        "supplied_node_ids": ["issue-362"],
        "graph_digest": GRAPH_DIGEST,
        "planning_result_digest": PLANNING_DIGEST,
        "cohort_summaries": [
            {
                "node_ids": ["issue-362"],
                "classification": "parallel-candidate",
                "reason_codes": ["covered-no-deterministic-conflict"],
            }
        ],
        "planning_scope": "supplied-graph-only",
        "execution_authorized": False,
        "created_at": "2026-07-20T11:00:00Z",
        "handoff_digest": "0" * 64,
    }
    payload.update(changes)
    payload["handoff_digest"] = compute_handoff_digest(payload)
    cohorts = tuple(HandoffCohort(**item) for item in payload["cohort_summaries"])
    return SchedulerPlanningHandoff(
        contract_version=payload["contract_version"],
        planning_result_version=payload["planning_result_version"],
        evaluator_commit_sha=payload["evaluator_commit_sha"],
        repository=payload["repository"],
        base_branch=payload["base_branch"],
        evaluated_repository_sha=payload["evaluated_repository_sha"],
        supplied_node_ids=tuple(payload["supplied_node_ids"]),
        graph_digest=payload["graph_digest"],
        planning_result_digest=payload["planning_result_digest"],
        cohort_summaries=cohorts,
        created_at=payload["created_at"],
        handoff_digest=payload["handoff_digest"],
    )


def _handoff_mapping(**changes):
    handoff = _handoff(**changes)
    return {
        "contract_version": handoff.contract_version,
        "planning_result_version": handoff.planning_result_version,
        "evaluator_commit_sha": handoff.evaluator_commit_sha,
        "repository": handoff.repository,
        "base_branch": handoff.base_branch,
        "evaluated_repository_sha": handoff.evaluated_repository_sha,
        "supplied_node_ids": list(handoff.supplied_node_ids),
        "graph_digest": handoff.graph_digest,
        "planning_result_digest": handoff.planning_result_digest,
        "cohort_summaries": [
            {
                "node_ids": list(item.node_ids),
                "classification": item.classification,
                "reason_codes": list(item.reason_codes),
            }
            for item in handoff.cohort_summaries
        ],
        "planning_scope": handoff.planning_scope,
        "execution_authorized": False,
        "created_at": handoff.created_at,
        "handoff_digest": handoff.handoff_digest,
    }


def _issueplan(handoff, *, revision="rev-1", **changes):
    candidate = MetadataCandidate(
        1,
        "raw",
        {
            "profile_version": "issueplan-core/v1",
            "entity_id": "issue-362",
            "revision": revision,
            "owner_agent": "Integration Manager",
            "required_files": [
                "08_Tooling/workflow-scheduler/src/workflow_scheduler/planning/draft_ingestion.py"
            ],
        },
    )
    scan = ScanResult(
        source_locator="github:Blummer92/agent-os#362",
        source_revision=revision,
        findings=(),
        adoption_class=AdoptionClass.STRICT_NATIVE,
        candidates=(candidate,),
        strict_valid=True,
        execution_authorized=False,
        evidence=("bounded=true",),
    )
    envelope = SourceEnvelope(
        source_locator="github:Blummer92/agent-os#362",
        source_revision=revision,
        content="issue body",
        retrieval_complete=True,
        pagination_complete=True,
        accessible=True,
        source_family="github-issue",
    )
    values = {
        "repository": handoff.repository,
        "base_branch": handoff.base_branch,
        "evaluated_repository_sha": handoff.evaluated_repository_sha,
        "implementation_contract_fingerprint": CONTRACT_DIGEST,
        "allowed_files": (
            "08_Tooling/workflow-scheduler/src/workflow_scheduler/planning/draft_ingestion.py",
        ),
        "forbidden_paths": (".github/workflows/**",),
        "required_tests": (
            "python -m pytest 08_Tooling/workflow-scheduler/tests/test_draft_ingestion.py -q",
        ),
        "graph_reference": handoff.graph_digest,
        "planning_result_reference": handoff.planning_result_digest,
        "handoff_reference": handoff.handoff_digest,
        "supplied_node_ids": handoff.supplied_node_ids,
    }
    values.update(changes)
    return build_issueplan_current_state_evidence(
        envelope,
        scan,
        observed_at="2026-07-20T11:30:00Z",
        freshness_boundary="main@97cf4c38",
        **values,
    )


def _repository_state(*, tested_sha=HEAD_SHA, synthetic=False, worktree=None):
    worktree = worktree or WorktreeState.CLEAN
    return RepositoryStateEvidence(
        schema_name=CAPABILITY_EVIDENCE_SCHEMA_NAME,
        evidence_schema_version=CAPABILITY_EVIDENCE_SCHEMA_VERSION,
        producer_adapter="fixture-adapter",
        producer_adapter_version="1.0",
        correlation_id="issue-362",
        repository_identity=RepositoryIdentity(
            host="github.com",
            owner="Blummer92",
            repository="agent-os",
            repository_id=123,
            default_branch="main",
        ),
        base_ref="main",
        base_sha=BASE_SHA,
        head_ref="agent/wsc3-draft-ingestion",
        head_sha=HEAD_SHA,
        requested_ref="agent/wsc3-draft-ingestion",
        requested_sha=HEAD_SHA,
        observed_sha=tested_sha,
        tested_sha=tested_sha,
        pushed_sha=HEAD_SHA,
        proposed_pr_sha=HEAD_SHA,
        synthetic_merge_sha=tested_sha if synthetic else None,
        external_build_sha=tested_sha,
        evidence_type=(
            RepositoryEvidenceType.SYNTHETIC_PR_MERGE
            if synthetic
            else RepositoryEvidenceType.BRANCH_HEAD
        ),
        contract_fingerprint=CONTRACT_DIGEST,
        worktree_state=worktree,
        worktree_reason_codes=(
            ("worktree.dirty",) if worktree is WorktreeState.DIRTY else ()
        ),
        observed_at="2026-07-20T11:45:00Z",
        freshness_boundary="workflow-run-1",
    )


def _build(*, handoff=None, issueplan=None, repository=None, created_at=CREATED_AT):
    handoff = handoff or _handoff()
    issueplan = issueplan or _issueplan(handoff)
    repository = repository or _repository_state(
        tested_sha=handoff.evaluated_repository_sha
    )
    return build_draft_task_proposals(
        handoff,
        issueplan,
        repository,
        created_at=created_at,
    )


def test_matching_current_evidence_emits_one_unapproved_deterministic_proposal():
    first = _build()
    second = _build()
    assert first == second
    assert first.status == "eligible"
    assert first.reason_codes == ("approval-not-evaluated",)
    assert len(first.proposals) == 1
    proposal = first.proposals[0]
    assert proposal.authorization_status == "not-evaluated"
    assert proposal.execution_authorized is False
    assert first.execution_authorized is False
    assert first.side_effects_performed is False
    assert len(proposal.proposal_id) == 64


def test_created_at_is_provenance_not_proposal_identity():
    first = _build(created_at="2026-07-20T12:00:00Z")
    second = _build(created_at="2026-07-20T12:01:00Z")
    assert first.proposals[0].proposal_id == second.proposals[0].proposal_id
    assert first.proposals[0].created_at != second.proposals[0].created_at


def test_source_or_scanner_revision_changes_proposal_identity():
    handoff = _handoff()
    first = _build(handoff=handoff, issueplan=_issueplan(handoff, revision="rev-1"))
    second = _build(handoff=handoff, issueplan=_issueplan(handoff, revision="rev-2"))
    assert first.status == second.status == "eligible"
    assert first.proposals[0].proposal_id != second.proposals[0].proposal_id


def test_mapping_handoff_is_treated_as_untrusted_and_validated():
    mapping = _handoff_mapping()
    handoff = _handoff()
    result = _build(handoff=mapping, issueplan=_issueplan(handoff))
    assert result.status == "eligible"


def test_malformed_or_authorizing_handoff_is_invalid_with_upstream_reason():
    payload = _handoff_mapping()
    payload["execution_authorized"] = True
    payload["handoff_digest"] = compute_handoff_digest(payload)
    result = build_draft_task_proposals(
        payload,
        None,
        None,
        created_at=CREATED_AT,
    )
    assert result.status == "invalid"
    assert "execution-authorized-violation" in result.reason_codes
    assert result.execution_authorized is False


def test_missing_external_evidence_is_blocked_not_inferred():
    handoff = _handoff()
    missing_issueplan = build_draft_task_proposals(
        handoff, None, _repository_state(), created_at=CREATED_AT
    )
    assert missing_issueplan.status == "blocked"
    assert missing_issueplan.reason_codes == ("hard-dependency-unmet",)

    missing_repository = build_draft_task_proposals(
        handoff, _issueplan(handoff), None, created_at=CREATED_AT
    )
    assert missing_repository.status == "blocked"
    assert missing_repository.reason_codes == ("hard-dependency-unmet",)


def test_planning_reference_or_node_mismatch_is_stale():
    handoff = _handoff()
    issueplan = _issueplan(handoff, graph_reference="9" * 64)
    result = _build(handoff=handoff, issueplan=issueplan)
    assert result.status == "stale"
    assert result.reason_codes == ("planning-state-mismatch",)
    assert result.proposals == ()


def test_upstream_repository_blocker_passes_through_unchanged():
    handoff = _handoff()
    result = _build(
        handoff=handoff,
        repository=_repository_state(worktree=WorktreeState.DIRTY),
    )
    assert result.status == "blocked"
    assert "worktree.dirty" in result.reason_codes
    assert "hard-dependency-unmet" not in result.reason_codes


def test_synthetic_merge_tested_sha_remains_distinct_from_source_head():
    handoff = _handoff(evaluated_sha=MERGE_SHA)
    issueplan = _issueplan(handoff)
    repository = _repository_state(tested_sha=MERGE_SHA, synthetic=True)
    result = _build(handoff=handoff, issueplan=issueplan, repository=repository)
    assert result.status == "eligible"
    assert result.repository_state_validation.head_sha == HEAD_SHA
    assert result.repository_state_validation.tested_sha == MERGE_SHA
    assert result.proposals[0].evaluated_repository_sha == MERGE_SHA


def test_models_are_frozen_and_cannot_construct_authorization():
    proposal = _build().proposals[0]
    with pytest.raises(FrozenInstanceError):
        proposal.proposal_id = "changed"
    with pytest.raises(TypeError):
        DraftTaskProposal(
            **{
                **{
                    field: getattr(proposal, field)
                    for field in proposal.__dataclass_fields__
                    if field not in {"authorization_status", "execution_authorized"}
                },
                "execution_authorized": True,
            }
        )


def test_builder_performs_no_external_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("external operation attempted")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    assert _build().status == "eligible"


def test_planning_module_does_not_import_scheduler_runtime_authority():
    tree = ast.parse(inspect.getsource(draft_ingestion))
    forbidden = {
        "workflow_scheduler.models",
        "workflow_scheduler.execution",
        "workflow_scheduler.repository",
        "workflow_scheduler.queue",
        "workflow_scheduler.adapters",
        "workflow_scheduler.governance",
    }
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert imported.isdisjoint(forbidden)
