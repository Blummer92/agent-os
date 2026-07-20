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

from scripts.agent_os_execution_capabilities import (  # noqa: E402
    CAPABILITY_EVIDENCE_SCHEMA_NAME,
    CAPABILITY_EVIDENCE_SCHEMA_VERSION,
    RepositoryEvidenceType,
    RepositoryIdentity,
    RepositoryStateEvidence,
    WorktreeState,
)
from scripts.agent_os_issue_acceptance import (  # noqa: E402
    HandoffCohort,
    SchedulerPlanningHandoff,
    build_issueplan_current_state_evidence,
    compute_handoff_digest,
)
from scripts.agent_os_issue_acceptance.issueplan_scanner import (  # noqa: E402
    AdoptionClass,
    MetadataCandidate,
    ScanResult,
    SourceEnvelope,
)
from workflow_scheduler.planning import (  # noqa: E402
    DRAFT_TASK_PROPOSAL_VERSION,
    DraftTaskProposal,
    build_draft_task_proposals,
)
from workflow_scheduler.planning import draft_ingestion  # noqa: E402

HEAD_SHA = "a" * 40
BASE_SHA = "b" * 40
MERGE_SHA = "c" * 40
EVALUATOR_SHA = "d" * 40
GRAPH_DIGEST = "1" * 64
PLANNING_DIGEST = "2" * 64
CONTRACT_DIGEST = "3" * 64
CREATED_AT = "2026-07-20T12:00:00Z"


def _handoff(**changes):
    payload = {
        "contract_version": "0.2.0",
        "planning_result_version": "0.1.0",
        "evaluator_commit_sha": EVALUATOR_SHA,
        "repository": "blummer92/agent-os",
        "base_branch": "main",
        "evaluated_repository_sha": HEAD_SHA,
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
        cohort_summaries=tuple(
            HandoffCohort(**item) for item in payload["cohort_summaries"]
        ),
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
        freshness_boundary="main@07c01820",
        **values,
    )


def _repository_state(
    *,
    owner="blummer92",
    base_ref="main",
    head_sha=HEAD_SHA,
    requested_sha=HEAD_SHA,
    tested_sha=HEAD_SHA,
    synthetic=False,
    worktree=WorktreeState.CLEAN,
):
    return RepositoryStateEvidence(
        schema_name=CAPABILITY_EVIDENCE_SCHEMA_NAME,
        evidence_schema_version=CAPABILITY_EVIDENCE_SCHEMA_VERSION,
        producer_adapter="fixture-adapter",
        producer_adapter_version="1.0",
        correlation_id="issue-362",
        repository_identity=RepositoryIdentity(
            host="github.com",
            owner=owner,
            repository="agent-os",
            repository_id=123,
            default_branch="main",
        ),
        base_ref=base_ref,
        base_sha=BASE_SHA,
        head_ref="agent/wsc3-draft-ingestion",
        head_sha=head_sha,
        requested_ref="agent/wsc3-draft-ingestion",
        requested_sha=requested_sha,
        observed_sha=tested_sha,
        tested_sha=tested_sha,
        pushed_sha=head_sha,
        proposed_pr_sha=head_sha,
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
    repository = repository or _repository_state()
    return build_draft_task_proposals(
        handoff, issueplan, repository, created_at=created_at
    )


def test_matching_current_evidence_emits_one_unapproved_proposal():
    first = _build()
    second = _build()
    assert first == second
    assert first.status == "eligible"
    assert first.reason_codes == ("approval-not-evaluated",)
    proposal = first.proposals[0]
    assert proposal.proposal_version == DRAFT_TASK_PROPOSAL_VERSION
    assert proposal.proposal_id.startswith("draft-task-proposal:")
    assert proposal.authorization_status == "not-evaluated"
    assert proposal.execution_authorized is False
    assert first.authorization_status == "not-evaluated"
    assert first.execution_authorized is False
    assert first.side_effects_performed is False


def test_created_at_is_provenance_not_proposal_identity():
    first = _build(created_at="2026-07-20T12:00:00Z")
    second = _build(created_at="2026-07-20T12:01:00Z")
    assert first.proposals[0].proposal_id == second.proposals[0].proposal_id
    assert first.proposals[0].created_at != second.proposals[0].created_at


def test_invalid_created_at_fails_closed_without_clock_read():
    with pytest.raises(ValueError):
        _build(created_at="2026-99-99T12:00:00Z")


def test_source_revision_changes_proposal_identity():
    handoff = _handoff()
    first = _build(handoff=handoff, issueplan=_issueplan(handoff, revision="rev-1"))
    second = _build(handoff=handoff, issueplan=_issueplan(handoff, revision="rev-2"))
    assert first.status == second.status == "eligible"
    assert first.proposals[0].proposal_id != second.proposals[0].proposal_id


def test_mapping_handoff_is_untrusted_and_validated():
    mapping = _handoff_mapping()
    handoff = _handoff()
    result = _build(handoff=mapping, issueplan=_issueplan(handoff))
    assert result.status == "eligible"


def test_authorizing_or_digest_tampered_handoff_is_invalid():
    payload = _handoff_mapping()
    payload["execution_authorized"] = True
    payload["handoff_digest"] = compute_handoff_digest(payload)
    result = build_draft_task_proposals(payload, None, None, created_at=CREATED_AT)
    assert result.status == "invalid"
    assert "execution-authorized-violation" in result.reason_codes

    payload = _handoff_mapping()
    payload["handoff_digest"] = "0" * 64
    result = build_draft_task_proposals(payload, None, None, created_at=CREATED_AT)
    assert result.status == "invalid"
    assert result.reason_codes == ("handoff-digest-mismatch",)


def test_missing_external_evidence_is_blocked_not_inferred():
    handoff = _handoff()
    assert build_draft_task_proposals(
        handoff, None, _repository_state(), created_at=CREATED_AT
    ).reason_codes == ("hard-dependency-unmet",)
    assert build_draft_task_proposals(
        handoff, _issueplan(handoff), None, created_at=CREATED_AT
    ).reason_codes == ("hard-dependency-unmet",)


@pytest.mark.parametrize(
    ("classification", "status", "reason"),
    [
        ("blocked", "blocked", "hard-dependency-unmet"),
        ("needs-decision", "needs-decision", "planning-state-mismatch"),
        ("sequencing-review", "needs-decision", "planning-state-mismatch"),
    ],
)
def test_non_executable_cohort_classification_never_emits_proposal(
    classification, status, reason
):
    handoff = _handoff(
        cohort_summaries=[
            {
                "node_ids": ["issue-362"],
                "classification": classification,
                "reason_codes": ["cohort-not-executable"],
            }
        ]
    )
    result = _build(handoff=handoff, issueplan=_issueplan(handoff))
    assert result.status == status
    assert result.reason_codes == (reason,)
    assert result.proposals == ()


@pytest.mark.parametrize(
    ("change", "status", "reason"),
    [
        ({"retrieval_status": "stale"}, "stale", "source.revision-changed"),
        ({"retrieval_status": "unsupported"}, "blocked", "source.unsupported"),
        ({"completeness_status": "partial"}, "needs-decision", "source.partial"),
        ({"schema_version": "2.0"}, "invalid", "version.unsupported"),
    ],
)
def test_issueplan_outcomes_pass_through_without_aliases(change, status, reason):
    handoff = _handoff()
    result = _build(handoff=handoff, issueplan=_issueplan(handoff, **change))
    assert result.status == status
    assert reason in result.reason_codes
    assert "planning-state-mismatch" not in result.reason_codes


@pytest.mark.parametrize(
    ("repository", "reason"),
    [
        (_repository_state(owner="other"), "repo.identity-mismatch"),
        (_repository_state(base_ref="develop"), "ref.base-mismatch"),
        (_repository_state(head_sha=MERGE_SHA), "ref.branch-moved"),
        (_repository_state(requested_sha=MERGE_SHA), "ref.test-sha-mismatch"),
    ],
)
def test_repository_bindings_use_exact_upstream_reasons(repository, reason):
    result = _build(repository=repository)
    assert result.status == "stale"
    assert reason in result.reason_codes
    assert "planning-state-mismatch" not in result.reason_codes


def test_repository_worktree_outcomes_pass_through():
    dirty = _build(repository=_repository_state(worktree=WorktreeState.DIRTY))
    assert dirty.status == "blocked"
    assert dirty.reason_codes == ("worktree.dirty",)

    indeterminate = _build(
        repository=_repository_state(worktree=WorktreeState.INDETERMINATE)
    )
    assert indeterminate.status == "needs-decision"
    assert indeterminate.reason_codes == ("worktree.indeterminate",)


def test_malformed_repository_evidence_is_invalid():
    result = _build(repository={"schema_name": "bad"})
    assert result.status == "invalid"
    assert result.repository_state_validation is not None


def test_synthetic_merge_preserves_source_head_and_tested_sha():
    result = _build(
        repository=_repository_state(tested_sha=MERGE_SHA, synthetic=True)
    )
    assert result.status == "eligible"
    validation = result.repository_state_validation
    assert validation.head_sha == HEAD_SHA
    assert validation.requested_sha == HEAD_SHA
    assert validation.tested_sha == MERGE_SHA
    assert validation.synthetic_merge_sha == MERGE_SHA
    assert result.proposals[0].evaluated_repository_sha == HEAD_SHA


def test_synthetic_test_sha_mislabeled_as_branch_head_is_stale():
    result = _build(repository=_repository_state(tested_sha=MERGE_SHA))
    assert result.status == "stale"
    assert "ref.stale-sha" in result.reason_codes


@pytest.mark.parametrize(
    "change",
    [
        {"repository": "other/repo"},
        {"base_branch": "develop"},
        {"evaluated_repository_sha": MERGE_SHA},
        {"graph_reference": "8" * 64},
        {"planning_result_reference": "9" * 64},
        {"handoff_reference": "0" * 64},
        {"supplied_node_ids": ()},
        {"implementation_contract_fingerprint": None},
    ],
)
def test_planning_binding_mismatch_is_wsc3_owned_stale(change):
    handoff = _handoff()
    result = _build(handoff=handoff, issueplan=_issueplan(handoff, **change))
    assert result.status == "stale"
    assert result.reason_codes == ("planning-state-mismatch",)
    assert result.proposals == ()


def test_models_are_frozen_and_authorization_is_not_constructible():
    proposal = _build().proposals[0]
    with pytest.raises(FrozenInstanceError):
        proposal.proposal_id = "changed"
    with pytest.raises(TypeError):
        DraftTaskProposal(
            **{
                **{
                    name: getattr(proposal, name)
                    for name, field in proposal.__dataclass_fields__.items()
                    if field.init
                },
                "execution_authorized": True,
            }
        )


def test_runtime_status_and_reason_vocabularies_are_exact():
    assert draft_ingestion._WSC3_STATUSES == {
        "eligible", "blocked", "stale", "invalid", "needs-decision"
    }
    assert draft_ingestion._WSC3_REASON_CODES == {
        "hard-dependency-unmet",
        "planning-state-mismatch",
        "approval-not-evaluated",
    }


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
