"""Tests for the pure-local WSC5 single-issue execution orchestrator.

Every canonical input is built from the real published APIs (WSC4 approved
projection, IssuePlan current state, approval records, and the GEX validation
plan, evidence bundle, advisory evidence, and advisory render). Every adapter is
an in-memory fake: no network, no subprocess, no persistence, and no clock.
"""

from __future__ import annotations

import ast
import inspect
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
if str(SCHEDULER_SRC) not in sys.path:
    sys.path.insert(0, str(SCHEDULER_SRC))

from scripts.agent_os_execution_capabilities import (  # noqa: E402
    CAPABILITY_EVIDENCE_SCHEMA_NAME,
    CAPABILITY_EVIDENCE_SCHEMA_VERSION,
    RepositoryEvidenceType,
    RepositoryIdentity,
    RepositoryStateEvidence,
    WorktreeState,
)
from scripts.agent_os_execution_capabilities.approved_projection import (  # noqa: E402
    GovernedProjectionEvidenceResult,
)
from scripts.agent_os_issue_acceptance import (  # noqa: E402
    ApprovalKind,
    ApprovalState,
    HandoffCohort,
    SchedulerPlanningHandoff,
    build_approval_candidate,
    build_approved_execution_projection,
    build_issueplan_current_state_evidence,
    compute_handoff_digest,
    evaluate_approval_applicability,
    record_approval_decision,
)
from scripts.agent_os_issue_acceptance.issueplan_scanner import (  # noqa: E402
    AdoptionClass,
    MetadataCandidate,
    ScanResult,
    SourceEnvelope,
)
from scripts.agent_os_remote_validation import (  # noqa: E402
    SuppliedCommandResult,
    evaluate_advisory_pre_pr_evidence,
    render_advisory_evidence,
)
from scripts.agent_os_remote_validation.evidence_bundle import (  # noqa: E402
    build_validation_evidence_bundle,
    validation_evidence_bundle_id,
)
from scripts.agent_os_remote_validation.models import ValidationPlan  # noqa: E402
from scripts.agent_os_remote_validation.selector import (  # noqa: E402
    compute_command_set_digest,
    validation_plan_id,
)
from workflow_scheduler.execution import single_issue_pilot as pilot_module  # noqa: E402
from workflow_scheduler.execution.single_issue_pilot import (  # noqa: E402
    PilotExecutionObservation,
    PilotExecutionRequest,
    PilotLeaseGrant,
    PilotLeaseReleaseObservation,
    PilotLeaseRequest,
    PilotValidationObservation,
    PilotValidationRequest,
    SingleIssuePilotInput,
    SingleIssuePilotResult,
    WorkspaceCleanup,
    WorkspaceHandle,
    WorkspaceInspection,
    WorkspaceRequest,
    pilot_holder_identity,
    pilot_lease_identity,
    pilot_workspace_identity,
    run_single_issue_pilot,
    serialize_single_issue_pilot_result,
    single_issue_pilot_result_id,
)
from workflow_scheduler.planning import build_draft_task_proposals  # noqa: E402

ISSUE = 560
NODE_ID = f"issue-{ISSUE}"
REPOSITORY = "blummer92/agent-os"
BASE_BRANCH = "main"
BRANCH = "agent/560-wsc5-single-issue-pilot"
HEAD_SHA = "a" * 40
BASE_SHA = "b" * 40
EVALUATOR_SHA = "d" * 40
GRAPH_DIGEST = "1" * 64
PLANNING_DIGEST = "2" * 64
CONTRACT_DIGEST = "3" * 64
CREATED_AT = "2026-07-20T12:00:00Z"
APPROVED_AT = "2026-07-20T12:10:00Z"
PROJECTED_AT = "2026-07-20T12:20:00Z"
EXPIRES_AT = "2026-07-20T13:00:00Z"
INVOCATION_ID = "run-560"
WORKSPACE_REQUEST_ID = "workspace-560"
RUNNER_ID = "github-actions"
PULL_REQUEST = 561

TARGET_FILE = (
    "08_Tooling/workflow-scheduler/src/workflow_scheduler/execution/"
    "single_issue_pilot.py"
)
ALLOWED_FILES = (TARGET_FILE,)
FORBIDDEN_PATHS = (".github/workflows/**",)
REQUIRED_TESTS = (
    "python -m pytest 08_Tooling/workflow-scheduler/tests/test_single_issue_pilot.py -q",
)
CHANGED_PATHS = (TARGET_FILE,)


# --------------------------------------------------------------------------
# Canonical evidence fixtures (built once from the real published APIs)
# --------------------------------------------------------------------------


def _identity() -> RepositoryIdentity:
    return RepositoryIdentity(
        host="github.com",
        owner="blummer92",
        repository="agent-os",
        repository_id=1289370915,
        is_fork=False,
        default_branch="main",
    )


def _handoff() -> SchedulerPlanningHandoff:
    payload = {
        "contract_version": "0.2.0",
        "planning_result_version": "0.1.0",
        "evaluator_commit_sha": EVALUATOR_SHA,
        "repository": REPOSITORY,
        "base_branch": BASE_BRANCH,
        "evaluated_repository_sha": HEAD_SHA,
        "supplied_node_ids": [NODE_ID],
        "graph_digest": GRAPH_DIGEST,
        "planning_result_digest": PLANNING_DIGEST,
        "cohort_summaries": [
            {
                "node_ids": [NODE_ID],
                "classification": "parallel-candidate",
                "reason_codes": ["covered-no-deterministic-conflict"],
            }
        ],
        "planning_scope": "supplied-graph-only",
        "execution_authorized": False,
        "created_at": "2026-07-20T11:00:00Z",
        "handoff_digest": "0" * 64,
    }
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


def _issueplan(handoff: SchedulerPlanningHandoff, *, revision: str = "rev-1"):
    candidate = MetadataCandidate(
        1,
        "raw",
        {
            "profile_version": "issueplan-core/v1",
            "entity_id": NODE_ID,
            "revision": revision,
            "owner_agent": "Integration Manager",
            "required_files": [TARGET_FILE],
        },
    )
    scan = ScanResult(
        source_locator=f"github:Blummer92/agent-os#{ISSUE}",
        source_revision=revision,
        findings=(),
        adoption_class=AdoptionClass.STRICT_NATIVE,
        candidates=(candidate,),
        strict_valid=True,
        execution_authorized=False,
        evidence=("bounded=true",),
    )
    envelope = SourceEnvelope(
        source_locator=f"github:Blummer92/agent-os#{ISSUE}",
        source_revision=revision,
        content="issue body",
        retrieval_complete=True,
        pagination_complete=True,
        accessible=True,
        source_family="github-issue",
    )
    return build_issueplan_current_state_evidence(
        envelope,
        scan,
        observed_at="2026-07-20T11:30:00Z",
        freshness_boundary="main@3951c562",
        repository=handoff.repository,
        base_branch=handoff.base_branch,
        evaluated_repository_sha=handoff.evaluated_repository_sha,
        implementation_contract_fingerprint=CONTRACT_DIGEST,
        allowed_files=ALLOWED_FILES,
        forbidden_paths=FORBIDDEN_PATHS,
        required_tests=REQUIRED_TESTS,
        graph_reference=handoff.graph_digest,
        planning_result_reference=handoff.planning_result_digest,
        handoff_reference=handoff.handoff_digest,
        supplied_node_ids=handoff.supplied_node_ids,
    )


def _repository_state() -> RepositoryStateEvidence:
    return RepositoryStateEvidence(
        schema_name=CAPABILITY_EVIDENCE_SCHEMA_NAME,
        evidence_schema_version=CAPABILITY_EVIDENCE_SCHEMA_VERSION,
        producer_adapter="fixture-adapter",
        producer_adapter_version="1.0",
        correlation_id=NODE_ID,
        repository_identity=_identity(),
        base_ref=BASE_BRANCH,
        base_sha=BASE_SHA,
        head_ref=BRANCH,
        head_sha=HEAD_SHA,
        requested_ref=BRANCH,
        requested_sha=HEAD_SHA,
        observed_sha=HEAD_SHA,
        tested_sha=HEAD_SHA,
        pushed_sha=HEAD_SHA,
        proposed_pr_sha=HEAD_SHA,
        synthetic_merge_sha=None,
        external_build_sha=HEAD_SHA,
        evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        contract_fingerprint=CONTRACT_DIGEST,
        worktree_state=WorktreeState.CLEAN,
        worktree_reason_codes=(),
        observed_at="2026-07-20T11:45:00Z",
        freshness_boundary=f"workflow-run-{ISSUE}",
    )


def _canonical_inputs():
    handoff = _handoff()
    issueplan = _issueplan(handoff)
    repository_state = _repository_state()
    planning = build_draft_task_proposals(
        handoff, issueplan, repository_state, created_at=CREATED_AT
    )
    assert planning.status == "eligible"
    proposal = planning.proposals[0]

    candidate = build_approval_candidate(
        proposal,
        issueplan,
        repository_state,
        approval_kind=ApprovalKind.IMPLEMENTATION,
        authorizer_id="operator-1",
        decision_id=f"request-{ISSUE}",
        decision_at=CREATED_AT,
        expires_at=EXPIRES_AT,
    )
    approval = record_approval_decision(
        candidate,
        state=ApprovalState.APPROVED,
        decision_id=f"decision-approve-{ISSUE}",
        authorizer_id="operator-2",
        decision_at=APPROVED_AT,
    )
    applicability = evaluate_approval_applicability(
        approval, proposal, issueplan, repository_state, evaluated_at=PROJECTED_AT
    )
    assert applicability.status == "applicable"

    projection_result = build_approved_execution_projection(
        proposal=proposal,
        approval_record=approval,
        approval_applicability=applicability,
        issueplan_current_state_evidence=issueplan,
        repository_state_evidence=repository_state,
        projected_at=PROJECTED_AT,
    )
    assert projection_result.status == "complete"
    projection = projection_result.projection
    assert projection is not None

    return {
        "handoff": handoff,
        "issueplan": issueplan,
        "repository_state": repository_state,
        "proposal": proposal,
        "approval": approval,
        "projection": projection,
    }


CANONICAL = _canonical_inputs()
PROJECTION = CANONICAL["projection"]
ISSUEPLAN = CANONICAL["issueplan"]
REPOSITORY_STATE = CANONICAL["repository_state"]
PROPOSAL = CANONICAL["proposal"]
APPROVAL = CANONICAL["approval"]


def _governed_projection() -> GovernedProjectionEvidenceResult:
    return GovernedProjectionEvidenceResult(
        status="accepted",
        schema_version="1.0",
        projection_id=PROJECTION.projection_id,
        proposal_id=PROJECTION.proposal_id,
        approval_id=PROJECTION.approval_id,
        repository_identity=_identity(),
        base_branch=BASE_BRANCH,
        base_sha=BASE_SHA,
        head_sha=HEAD_SHA,
        evaluated_sha=BASE_SHA,
        tested_sha=HEAD_SHA,
        repository_evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        repository_state_evidence_id=PROJECTION.repository_state_evidence_id,
        implementation_contract_fingerprint=CONTRACT_DIGEST,
        reason_codes=(),
        details=(),
    )


def _plan() -> ValidationPlan:
    commands = (REQUIRED_TESTS[0],)
    return ValidationPlan(
        selector_version="1.0.0",
        repository="Blummer92/agent-os",
        pull_request=PULL_REQUEST,
        base_sha=BASE_SHA,
        head_sha=HEAD_SHA,
        profile="focused",
        commands=commands,
        command_set_digest=compute_command_set_digest("1.0.0", commands),
        reason_codes=("profile.focused-package",),
        remote_build_required=True,
    )


def _command_results(plan: ValidationPlan) -> tuple[SuppliedCommandResult, ...]:
    return (
        SuppliedCommandResult(
            plan_id=validation_plan_id(plan),
            invocation_id=INVOCATION_ID,
            runner_id=RUNNER_ID,
            command_ordinal=0,
            command=plan.commands[0],
            source_head_sha=HEAD_SHA,
            tested_sha=HEAD_SHA,
            started_at="2026-07-24T15:00:01Z",
            completed_at="2026-07-24T15:00:02Z",
            status="passed",
            exit_code=0,
            diagnostic_summary="",
            diagnostic_truncated=False,
        ),
    )


def _gex_expectations(plan: ValidationPlan) -> dict[str, object]:
    return {
        "expected_repository": _identity(),
        "expected_pull_request": PULL_REQUEST,
        "expected_base_branch": BASE_BRANCH,
        "expected_base_sha": BASE_SHA,
        "expected_source_head_sha": HEAD_SHA,
        "expected_tested_sha": HEAD_SHA,
        "expected_repository_evidence_type": RepositoryEvidenceType.BRANCH_HEAD,
        "expected_projection_id": PROJECTION.projection_id,
        "expected_proposal_id": PROJECTION.proposal_id,
        "expected_approval_id": PROJECTION.approval_id,
        "expected_repository_state_evidence_id": (
            PROJECTION.repository_state_evidence_id
        ),
        "expected_implementation_contract_fingerprint": CONTRACT_DIGEST,
        "expected_selector_version": plan.selector_version,
        "expected_profile": plan.profile,
        "expected_command_set_digest": plan.command_set_digest,
        "expected_plan_id": validation_plan_id(plan),
        "runner_id": RUNNER_ID,
        "invocation_id": INVOCATION_ID,
        "started_at": "2026-07-24T15:00:00Z",
        "completed_at": "2026-07-24T15:01:00Z",
    }


def _gex_evidence():
    governed = _governed_projection()
    plan = _plan()
    results = _command_results(plan)
    expectations = _gex_expectations(plan)
    bundle = build_validation_evidence_bundle(
        governed, plan, results, **expectations
    )
    assert bundle.status == "passed"
    advisory = evaluate_advisory_pre_pr_evidence(
        governed,
        plan,
        results,
        current_base_sha=BASE_SHA,
        current_source_head_sha=HEAD_SHA,
        **expectations,
    )
    assert advisory.status == "passed"
    render = render_advisory_evidence(advisory)
    return plan, bundle, advisory, render


PLAN, BUNDLE, ADVISORY, RENDER = _gex_evidence()


def _pilot_input(**changes) -> SingleIssuePilotInput:
    values: dict[str, object] = {
        "issue_numbers": (ISSUE,),
        "requested_concurrency": 1,
        "repository": REPOSITORY,
        "base_branch": BASE_BRANCH,
        "base_sha": BASE_SHA,
        "source_head_sha": HEAD_SHA,
        "tested_sha": HEAD_SHA,
        "branch": BRANCH,
        "invocation_id": INVOCATION_ID,
        "workspace_request_id": WORKSPACE_REQUEST_ID,
        "projection": PROJECTION,
        "expected_projection_id": PROJECTION.projection_id,
        "expected_proposal_id": PROJECTION.proposal_id,
        "expected_approval_id": PROJECTION.approval_id,
        "expected_issueplan_evidence": ISSUEPLAN,
        "current_issueplan_evidence": ISSUEPLAN,
        "approval_record": APPROVAL,
        "current_proposal": PROPOSAL,
        "repository_state_evidence": REPOSITORY_STATE,
        "evaluated_at": PROJECTED_AT,
        "validation_plan": PLAN,
        "expected_plan_id": validation_plan_id(PLAN),
        "evidence_bundle": BUNDLE,
        "expected_bundle_id": validation_evidence_bundle_id(BUNDLE),
        "advisory_result": ADVISORY,
        "expected_advisory_result_id": ADVISORY.result_id,
        "advisory_render": RENDER,
        "expected_advisory_render_id": RENDER.render_id,
        "allowed_files": ALLOWED_FILES,
        "forbidden_paths": FORBIDDEN_PATHS,
        "required_tests": REQUIRED_TESTS,
    }
    values.update(changes)
    return SingleIssuePilotInput(**values)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# In-memory adapters
# --------------------------------------------------------------------------


class FakeLease:
    """In-memory lease adapter recording every acquisition and release."""

    def __init__(
        self,
        *,
        grant: PilotLeaseGrant | None = None,
        acquire_error: Exception | None = None,
        release: PilotLeaseReleaseObservation | object | None = None,
        release_error: Exception | None = None,
        single_use: bool = False,
    ) -> None:
        self._grant = grant
        self._acquire_error = acquire_error
        self._release = release
        self._release_error = release_error
        self._single_use = single_use
        self._held = False
        self.acquire_calls: list[PilotLeaseRequest] = []
        self.release_calls: list[PilotLeaseGrant] = []
        self.last_grant: PilotLeaseGrant | None = None

    def acquire(self, request: PilotLeaseRequest):
        self.acquire_calls.append(request)
        if self._acquire_error is not None:
            raise self._acquire_error
        if self._single_use and self._held:
            return PilotLeaseGrant(
                acquired=False,
                lease_identity=pilot_lease_identity(request),
                holder_identity=pilot_holder_identity(request),
                generation=0,
                reason="lease already held by another invocation",
            )
        self._held = True
        grant = self._grant
        if grant is None:
            grant = PilotLeaseGrant(
                acquired=True,
                lease_identity=pilot_lease_identity(request),
                holder_identity=pilot_holder_identity(request),
                generation=1,
            )
        self.last_grant = grant
        return grant

    def release(self, grant: PilotLeaseGrant):
        self.release_calls.append(grant)
        if self._release_error is not None:
            raise self._release_error
        if self._release is not None:
            return self._release
        return PilotLeaseReleaseObservation(
            released=True,
            lease_identity=grant.lease_identity,
            holder_identity=grant.holder_identity,
            generation=grant.generation,
        )


def _inspection(**changes) -> WorkspaceInspection:
    values: dict[str, object] = {
        "resolved": True,
        "repository": REPOSITORY,
        "branch": BRANCH,
        "expected_revision": HEAD_SHA,
        "actual_revision": HEAD_SHA,
        "clean": True,
        "detached": False,
        "reused": False,
        "locked": False,
        "locked_expected": False,
        "missing": False,
        "prunable": False,
    }
    values.update(changes)
    return WorkspaceInspection(**values)  # type: ignore[arg-type]


class FakeWorkspace:
    """In-memory workspace adapter with explicit, independently observable state."""

    def __init__(
        self,
        *,
        handle: WorkspaceHandle | None = None,
        create_error: Exception | None = None,
        inspection: WorkspaceInspection | object | None = None,
        inspect_error: Exception | None = None,
        cleanup: WorkspaceCleanup | object | None = None,
        cleanup_error: Exception | None = None,
    ) -> None:
        self._handle = handle
        self._create_error = create_error
        self._inspection = inspection
        self._inspect_error = inspect_error
        self._cleanup = cleanup
        self._cleanup_error = cleanup_error
        self.create_calls: list[WorkspaceRequest] = []
        self.inspect_calls: list[WorkspaceHandle] = []
        self.cleanup_calls: list[WorkspaceHandle] = []

    def create(self, request: WorkspaceRequest):
        self.create_calls.append(request)
        if self._create_error is not None:
            raise self._create_error
        if self._handle is not None:
            return self._handle
        return WorkspaceHandle(
            created=True, workspace_identity=pilot_workspace_identity(request)
        )

    def inspect(self, handle: WorkspaceHandle):
        self.inspect_calls.append(handle)
        if self._inspect_error is not None:
            raise self._inspect_error
        if self._inspection is not None:
            return self._inspection
        return _inspection()

    def cleanup(self, handle: WorkspaceHandle):
        self.cleanup_calls.append(handle)
        if self._cleanup_error is not None:
            raise self._cleanup_error
        if self._cleanup is not None:
            return self._cleanup
        return WorkspaceCleanup(filesystem_removed=True, metadata_removed=True)


class FakeExecutor:
    """In-memory executor adapter that reports one bounded observation."""

    def __init__(
        self,
        *,
        observation: PilotExecutionObservation | object | None = None,
        error: BaseException | None = None,
    ) -> None:
        self._observation = observation
        self._error = error
        self.calls: list[PilotExecutionRequest] = []

    def run(self, request: PilotExecutionRequest):
        self.calls.append(request)
        if self._error is not None:
            raise self._error
        if self._observation is not None:
            return self._observation
        return PilotExecutionObservation(
            outcome="succeeded",
            started=True,
            termination_confirmed=True,
            changed_paths=CHANGED_PATHS,
        )


class FakeValidator:
    """In-memory validation adapter running the required tests once."""

    def __init__(
        self,
        *,
        observation: PilotValidationObservation | object | None = None,
        error: Exception | None = None,
    ) -> None:
        self._observation = observation
        self._error = error
        self.calls: list[PilotValidationRequest] = []

    def validate(self, request: PilotValidationRequest):
        self.calls.append(request)
        if self._error is not None:
            raise self._error
        if self._observation is not None:
            return self._observation
        return PilotValidationObservation(
            attempted=True, passed=True, completed_tests=REQUIRED_TESTS
        )


def never_cancelled(checkpoint: str) -> bool:
    return False


def cancel_at(*checkpoints: str):
    wanted = frozenset(checkpoints)
    seen: list[str] = []

    def probe(checkpoint: str) -> bool:
        seen.append(checkpoint)
        return checkpoint in wanted

    probe.seen = seen  # type: ignore[attr-defined]
    return probe


def _run(pilot_input=None, **adapters) -> SingleIssuePilotResult:
    return run_single_issue_pilot(
        pilot_input if pilot_input is not None else _pilot_input(),
        lease=adapters.pop("lease", None) or FakeLease(),
        workspace=adapters.pop("workspace", None) or FakeWorkspace(),
        executor=adapters.pop("executor", None) or FakeExecutor(),
        validator=adapters.pop("validator", None) or FakeValidator(),
        cancelled=adapters.pop("cancelled", None) or never_cancelled,
    )


# --------------------------------------------------------------------------
# Success path
# --------------------------------------------------------------------------


def test_valid_single_issue_executes_exactly_once_and_completes() -> None:
    lease = FakeLease()
    workspace = FakeWorkspace()
    executor = FakeExecutor()
    validator = FakeValidator()

    result = _run(lease=lease, workspace=workspace, executor=executor, validator=validator)

    assert result.status == "completed"
    assert result.primary_status == "completed"
    assert result.issue_numbers == (ISSUE,)
    assert len(lease.acquire_calls) == 1
    assert len(lease.release_calls) == 1
    assert len(workspace.create_calls) == 1
    assert len(workspace.cleanup_calls) == 1
    assert len(executor.calls) == 1
    assert len(validator.calls) == 1
    assert result.executor_dispatch_attempts == 1
    assert result.validation_attempts == 1
    assert result.changed_paths == CHANGED_PATHS
    assert result.completed_tests == REQUIRED_TESTS
    assert result.reason_codes == ()
    assert result.primary_error is None


def test_completed_result_carries_every_canonical_identity() -> None:
    result = _run()

    assert result.projection_id == PROJECTION.projection_id
    assert result.proposal_id == PROJECTION.proposal_id
    assert result.approval_id == PROJECTION.approval_id
    assert result.approval_revision == PROJECTION.approval_revision
    assert result.issueplan_evidence_id == ISSUEPLAN.evidence_id
    assert result.plan_id == validation_plan_id(PLAN)
    assert result.bundle_id == validation_evidence_bundle_id(BUNDLE)
    assert result.advisory_result_id == ADVISORY.result_id
    assert result.advisory_render_id == RENDER.render_id
    assert result.base_sha == BASE_SHA
    assert result.source_head_sha == HEAD_SHA
    assert result.tested_sha == HEAD_SHA
    assert result.lease_identity is not None
    assert result.lease_holder_identity is not None
    assert result.lease_generation == 1
    assert result.workspace_identity is not None


def test_result_carries_no_false_authority_and_never_retries() -> None:
    result = _run()

    assert result.authoritative is False
    assert result.implementation_authorized is False
    assert result.execution_authorized is False
    assert result.publication_authorized is False
    assert result.merge_authorized is False
    assert result.attestation_verified is False
    assert result.side_effects_authorized is False
    assert result.retry_attempted is False


def test_result_is_immutable_deterministic_and_tamper_evident() -> None:
    first = _run()
    second = _run()

    assert first.result_id == second.result_id
    assert serialize_single_issue_pilot_result(first) == (
        serialize_single_issue_pilot_result(second)
    )
    assert single_issue_pilot_result_id(first) == first.result_id
    with pytest.raises(FrozenInstanceError):
        first.status = "failed"  # type: ignore[misc]
    with pytest.raises(ValueError, match="result ID mismatch"):
        serialize_single_issue_pilot_result(replace(first, details=("tampered",)))
    with pytest.raises(TypeError):
        serialize_single_issue_pilot_result({})  # type: ignore[arg-type]


def test_entry_point_rejects_unsupported_input_type() -> None:
    with pytest.raises(TypeError):
        run_single_issue_pilot(
            {},  # type: ignore[arg-type]
            lease=FakeLease(),
            workspace=FakeWorkspace(),
            executor=FakeExecutor(),
            validator=FakeValidator(),
            cancelled=never_cancelled,
        )


def test_completed_invariant_cannot_be_forged() -> None:
    result = _run()
    with pytest.raises(ValueError, match="success invariant"):
        replace(result, validation_passed=False)


# --------------------------------------------------------------------------
# Input validation
# --------------------------------------------------------------------------


def test_zero_issues_is_blocked() -> None:
    result = _run(_pilot_input(issue_numbers=()))
    assert result.status == "blocked"
    assert "input.no-issue" in result.reason_codes


def test_multiple_issues_are_blocked() -> None:
    result = _run(_pilot_input(issue_numbers=(ISSUE, ISSUE + 1)))
    assert result.status == "blocked"
    assert "input.multiple-issues" in result.reason_codes


def test_ambiguous_issue_input_needs_decision() -> None:
    result = _run(_pilot_input(issue_numbers=(0,)))
    assert result.status == "needs-decision"
    assert "input.ambiguous" in result.reason_codes


def test_concurrency_above_one_is_blocked() -> None:
    result = _run(_pilot_input(requested_concurrency=2))
    assert result.status == "blocked"
    assert "input.concurrency-unsupported" in result.reason_codes


def test_missing_identity_needs_decision() -> None:
    result = _run(_pilot_input(invocation_id="   "))
    assert result.status == "needs-decision"
    assert "input.identity-missing" in result.reason_codes


def test_unsupported_schema_version_needs_decision() -> None:
    result = _run(_pilot_input(schema_version="9.9"))
    assert result.status == "needs-decision"
    assert "contract.unsupported" in result.reason_codes


def test_no_adapter_is_touched_before_input_validation_passes() -> None:
    lease = FakeLease()
    workspace = FakeWorkspace()
    executor = FakeExecutor()
    _run(
        _pilot_input(issue_numbers=()),
        lease=lease,
        workspace=workspace,
        executor=executor,
    )
    assert lease.acquire_calls == []
    assert workspace.create_calls == []
    assert executor.calls == []


# --------------------------------------------------------------------------
# Canonical evidence revalidation
# --------------------------------------------------------------------------


def test_stale_projection_is_stale() -> None:
    result = _run(_pilot_input(source_head_sha="c" * 40))
    assert result.status == "stale"
    assert "projection.stale" in result.reason_codes


def test_tested_sha_mismatch_is_stale() -> None:
    result = _run(_pilot_input(tested_sha="e" * 40))
    assert result.status == "stale"
    assert "projection.stale" in result.reason_codes


def test_repository_mismatch_is_blocked() -> None:
    result = _run(_pilot_input(repository="blummer92/other"))
    assert result.status == "blocked"
    assert "projection.rejected" in result.reason_codes


def test_base_branch_mismatch_is_blocked() -> None:
    result = _run(_pilot_input(base_branch="release"))
    assert result.status == "blocked"
    assert "projection.rejected" in result.reason_codes


def test_unsupported_projection_type_is_blocked() -> None:
    result = _run(_pilot_input(projection=object()))
    assert result.status == "blocked"
    assert "projection.rejected" in result.reason_codes


def test_projection_identity_mismatch_needs_decision() -> None:
    result = _run(
        _pilot_input(expected_projection_id="approved-execution-projection:" + "0" * 64)
    )
    assert result.status == "needs-decision"
    assert "projection.needs-decision" in result.reason_codes


def test_stale_issueplan_current_state_is_stale() -> None:
    handoff = CANONICAL["handoff"]
    result = _run(
        _pilot_input(current_issueplan_evidence=_issueplan(handoff, revision="rev-2"))
    )
    assert result.status == "stale"
    assert "issueplan.stale" in result.reason_codes


def test_unsupported_issueplan_evidence_needs_decision() -> None:
    result = _run(_pilot_input(current_issueplan_evidence=object()))
    assert result.status == "needs-decision"
    assert "issueplan.needs-decision" in result.reason_codes


def test_absent_approval_record_is_blocked() -> None:
    result = _run(_pilot_input(approval_record=None))
    assert result.status == "blocked"
    assert "approval.blocked" in result.reason_codes


def test_invalidated_approval_is_not_applicable() -> None:
    result = _run(
        _pilot_input(invalidation_events=("contract.allowlist-changed",))
    )
    assert result.status in {"blocked", "stale"}
    assert any(code.startswith("approval.") for code in result.reason_codes)


def test_unsupported_approval_record_needs_decision() -> None:
    result = _run(_pilot_input(approval_record=object()))
    assert result.status == "needs-decision"
    assert "approval.invalid" in result.reason_codes


@pytest.mark.parametrize(
    ("field_name", "value", "reason"),
    [
        ("expected_plan_id", "validation-plan:" + "0" * 64, "evidence.plan-mismatch"),
        (
            "expected_bundle_id",
            "validation-evidence-bundle:" + "0" * 64,
            "evidence.bundle-mismatch",
        ),
        (
            "expected_advisory_result_id",
            "advisory-evidence:" + "0" * 64,
            "evidence.advisory-mismatch",
        ),
        (
            "expected_advisory_render_id",
            "advisory-render:" + "0" * 64,
            "evidence.render-mismatch",
        ),
    ],
)
def test_gex_evidence_identity_mismatches_are_blocked(
    field_name: str, value: str, reason: str
) -> None:
    result = _run(_pilot_input(**{field_name: value}))
    assert result.status == "blocked"
    assert reason in result.reason_codes


def test_unsupported_gex_evidence_type_needs_decision() -> None:
    result = _run(_pilot_input(validation_plan=object()))
    assert result.status == "needs-decision"
    assert "evidence.unsupported" in result.reason_codes


# --------------------------------------------------------------------------
# Identity cross-check
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field_name", "value", "reason"),
    [
        ("base_sha", "f" * 40, "identity.base-sha-mismatch"),
        ("issue_numbers", (ISSUE + 1,), "identity.issue-mismatch"),
        ("invocation_id", "run-other", "identity.invocation-mismatch"),
        ("allowed_files", ("docs/other.md",), "identity.allowed-files-mismatch"),
        ("forbidden_paths", ("secrets/**",), "identity.forbidden-paths-mismatch"),
        ("required_tests", ("pytest -q",), "identity.required-tests-mismatch"),
    ],
)
def test_identity_cross_check_rejects_drift(
    field_name: str, value: object, reason: str
) -> None:
    result = _run(_pilot_input(**{field_name: value}))
    assert result.status == "blocked"
    assert reason in result.reason_codes


# --------------------------------------------------------------------------
# Cancellation checkpoints
# --------------------------------------------------------------------------


def test_cancellation_before_lease_denies_safely() -> None:
    lease = FakeLease()
    result = _run(cancelled=cancel_at("pre-lease"), lease=lease)
    assert result.status == "cancelled"
    assert result.phase == "pre-lease-cancellation"
    assert lease.acquire_calls == []
    assert result.cancellation_requested is True


def test_cancellation_after_lease_releases_the_lease() -> None:
    lease = FakeLease()
    workspace = FakeWorkspace()
    result = _run(cancelled=cancel_at("post-lease"), lease=lease, workspace=workspace)
    assert result.status == "cancelled"
    assert result.phase == "post-lease-cancellation"
    assert len(lease.acquire_calls) == 1
    assert len(lease.release_calls) == 1
    assert workspace.create_calls == []
    assert result.lease_released is True


def test_cancellation_after_workspace_cleans_up_and_releases() -> None:
    lease = FakeLease()
    workspace = FakeWorkspace()
    executor = FakeExecutor()
    result = _run(
        cancelled=cancel_at("post-workspace"),
        lease=lease,
        workspace=workspace,
        executor=executor,
    )
    assert result.status == "cancelled"
    assert executor.calls == []
    assert len(workspace.cleanup_calls) == 1
    assert len(lease.release_calls) == 1


def test_cancellation_before_executor_never_dispatches() -> None:
    executor = FakeExecutor()
    result = _run(cancelled=cancel_at("pre-executor"), executor=executor)
    assert result.status == "cancelled"
    assert result.phase == "pre-execution-cancellation"
    assert executor.calls == []
    assert result.executor_called is False


def test_cancellation_probe_failure_needs_decision() -> None:
    def broken(checkpoint: str) -> bool:
        raise RuntimeError("probe unavailable")

    result = _run(cancelled=broken)
    assert result.status == "needs-decision"
    assert "cancellation.requested" in result.reason_codes


# --------------------------------------------------------------------------
# Lease hardening
# --------------------------------------------------------------------------


def test_lease_identity_is_bound_to_every_governed_input() -> None:
    lease = FakeLease()
    _run(lease=lease)
    request = lease.acquire_calls[0]
    assert request.repository == REPOSITORY
    assert request.issue_number == ISSUE
    assert request.invocation_id == INVOCATION_ID
    assert request.branch == BRANCH
    assert request.workspace_request_id == WORKSPACE_REQUEST_ID
    assert request.projection_id == PROJECTION.projection_id
    assert request.approval_id == PROJECTION.approval_id
    assert request.source_head_sha == HEAD_SHA

    other = replace(request, source_head_sha="c" * 40)
    assert pilot_lease_identity(other) != pilot_lease_identity(request)
    assert pilot_holder_identity(other) == pilot_holder_identity(request)


def test_duplicate_invocation_cannot_take_the_held_lease() -> None:
    lease = FakeLease(single_use=True)
    first = _run(lease=lease)
    assert first.status == "completed"

    second = _run(lease=lease)
    assert second.status == "blocked"
    assert "lease.acquisition-failed" in second.reason_codes
    assert second.lease_acquired is False
    assert second.lease_release_attempts == 0


def test_lease_acquisition_error_is_blocked() -> None:
    lease = FakeLease(acquire_error=RuntimeError("lease store unavailable"))
    result = _run(lease=lease)
    assert result.status == "blocked"
    assert "lease.acquisition-failed" in result.reason_codes
    assert len(lease.acquire_calls) == 1


def test_lease_holder_drift_is_quarantined() -> None:
    request = PilotLeaseRequest(
        repository=REPOSITORY,
        issue_number=ISSUE,
        invocation_id=INVOCATION_ID,
        branch=BRANCH,
        workspace_request_id=WORKSPACE_REQUEST_ID,
        projection_id=PROJECTION.projection_id,
        approval_id=PROJECTION.approval_id,
        source_head_sha=HEAD_SHA,
    )
    lease = FakeLease(
        grant=PilotLeaseGrant(
            acquired=True,
            lease_identity=pilot_lease_identity(request),
            holder_identity="pilot-holder:" + "0" * 64,
            generation=1,
        )
    )
    result = _run(lease=lease)
    assert result.status == "quarantined"
    assert "lease.holder-drift" in result.reason_codes


def test_lease_identity_drift_is_quarantined() -> None:
    lease = FakeLease(
        grant=PilotLeaseGrant(
            acquired=True,
            lease_identity="pilot-lease:" + "0" * 64,
            holder_identity="pilot-holder:" + "0" * 64,
            generation=1,
        )
    )
    result = _run(lease=lease)
    assert result.status == "quarantined"
    assert "lease.identity-mismatch" in result.reason_codes


def test_lease_generation_drift_is_quarantined() -> None:
    request = PilotLeaseRequest(
        repository=REPOSITORY,
        issue_number=ISSUE,
        invocation_id=INVOCATION_ID,
        branch=BRANCH,
        workspace_request_id=WORKSPACE_REQUEST_ID,
        projection_id=PROJECTION.projection_id,
        approval_id=PROJECTION.approval_id,
        source_head_sha=HEAD_SHA,
    )
    lease = FakeLease(
        grant=PilotLeaseGrant(
            acquired=True,
            lease_identity=pilot_lease_identity(request),
            holder_identity=pilot_holder_identity(request),
            generation=0,
        )
    )
    result = _run(lease=lease)
    assert result.status == "quarantined"
    assert "lease.generation-drift" in result.reason_codes


def test_release_is_attempted_once_and_only_for_the_acquired_holder() -> None:
    lease = FakeLease()
    result = _run(lease=lease)
    assert len(lease.release_calls) == 1
    assert lease.release_calls[0] is lease.last_grant
    assert result.lease_release_attempts == 1


def test_release_failure_is_quarantined_and_keeps_the_primary_outcome() -> None:
    lease = FakeLease(release_error=RuntimeError("release unavailable"))
    result = _run(lease=lease)
    assert result.status == "quarantined"
    assert result.primary_status == "completed"
    assert "lease.release-failed" in result.reason_codes
    assert result.release_errors


def test_ambiguous_release_is_quarantined() -> None:
    lease = FakeLease()

    class AmbiguousLease(FakeLease):
        def release(self, grant):
            self.release_calls.append(grant)
            return PilotLeaseReleaseObservation(
                released=False,
                lease_identity=grant.lease_identity,
                holder_identity=grant.holder_identity,
                generation=grant.generation,
                ambiguous=True,
                reason="store unreachable",
            )

    lease = AmbiguousLease()
    result = _run(lease=lease)
    assert result.status == "quarantined"
    assert "lease.release-ambiguous" in result.reason_codes


def test_forced_release_is_never_a_successful_path() -> None:
    class ForcingLease(FakeLease):
        def release(self, grant):
            self.release_calls.append(grant)
            return PilotLeaseReleaseObservation(
                released=True,
                lease_identity=grant.lease_identity,
                holder_identity=grant.holder_identity,
                generation=grant.generation,
                forced=True,
            )

    result = _run(lease=ForcingLease())
    assert result.status == "quarantined"
    assert "lease.release-forced" in result.reason_codes
    assert result.lease_released is False


def test_release_generation_drift_is_quarantined() -> None:
    class DriftingLease(FakeLease):
        def release(self, grant):
            self.release_calls.append(grant)
            return PilotLeaseReleaseObservation(
                released=True,
                lease_identity=grant.lease_identity,
                holder_identity=grant.holder_identity,
                generation=grant.generation + 1,
            )

    result = _run(lease=DriftingLease())
    assert result.status == "quarantined"
    assert "lease.generation-drift" in result.reason_codes


# --------------------------------------------------------------------------
# Workspace hardening
# --------------------------------------------------------------------------


def test_workspace_creation_failure_is_blocked() -> None:
    workspace = FakeWorkspace(
        handle=WorkspaceHandle(
            created=False, workspace_identity="pilot-workspace:" + "0" * 64
        )
    )
    result = _run(workspace=workspace)
    assert result.status == "blocked"
    assert "workspace.creation-failed" in result.reason_codes
    assert workspace.cleanup_calls == []


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"clean": False}, "workspace.dirty"),
        ({"detached": True}, "workspace.detached"),
        ({"reused": True}, "workspace.reused"),
        ({"missing": True}, "workspace.missing"),
        ({"prunable": True}, "workspace.prunable"),
        ({"locked": True}, "workspace.locked"),
        ({"resolved": False}, "workspace.unresolved"),
        ({"actual_revision": "c" * 40}, "workspace.revision-mismatch"),
        ({"repository": "blummer92/other"}, "workspace.repository-mismatch"),
        ({"branch": "other"}, "workspace.branch-mismatch"),
    ],
)
def test_unsafe_workspace_states_are_rejected(
    changes: dict[str, object], reason: str
) -> None:
    executor = FakeExecutor()
    result = _run(
        workspace=FakeWorkspace(inspection=_inspection(**changes)), executor=executor
    )
    assert result.status == "blocked"
    assert reason in result.reason_codes
    assert executor.calls == []
    assert result.workspace_safe is False


def test_expected_lock_alone_does_not_reject_the_workspace() -> None:
    result = _run(
        workspace=FakeWorkspace(
            inspection=_inspection(locked=True, locked_expected=True)
        )
    )
    assert result.status == "completed"


def test_filesystem_cleanup_failure_is_quarantined() -> None:
    result = _run(
        workspace=FakeWorkspace(
            cleanup=WorkspaceCleanup(filesystem_removed=False, metadata_removed=True)
        )
    )
    assert result.status == "quarantined"
    assert "workspace.filesystem-cleanup-failed" in result.reason_codes
    assert result.primary_status == "completed"


def test_metadata_cleanup_failure_is_quarantined() -> None:
    result = _run(
        workspace=FakeWorkspace(
            cleanup=WorkspaceCleanup(filesystem_removed=True, metadata_removed=False)
        )
    )
    assert result.status == "quarantined"
    assert "workspace.metadata-cleanup-failed" in result.reason_codes
    assert result.workspace_filesystem_cleaned is True
    assert result.workspace_metadata_cleaned is False


def test_path_absence_alone_is_not_cleanup_success() -> None:
    result = _run(
        workspace=FakeWorkspace(
            cleanup=WorkspaceCleanup(
                filesystem_removed=False, metadata_removed=False, path_absent=True
            )
        )
    )
    assert result.status == "quarantined"
    assert "workspace.filesystem-cleanup-failed" in result.reason_codes
    assert "workspace.metadata-cleanup-failed" in result.reason_codes


def test_force_cleanup_is_forbidden_as_a_successful_path() -> None:
    result = _run(
        workspace=FakeWorkspace(
            cleanup=WorkspaceCleanup(
                filesystem_removed=True, metadata_removed=True, force_required=True
            )
        )
    )
    assert result.status == "quarantined"
    assert "workspace.force-cleanup-forbidden" in result.reason_codes
    assert result.workspace_filesystem_cleaned is False


def test_cleanup_is_attempted_exactly_once() -> None:
    workspace = FakeWorkspace(cleanup_error=OSError("device busy"))
    result = _run(workspace=workspace)
    assert len(workspace.cleanup_calls) == 1
    assert result.workspace_cleanup_attempts == 1
    assert result.status == "quarantined"


def test_cleanup_and_release_failures_both_preserve_the_primary_failure() -> None:
    executor = FakeExecutor(
        observation=PilotExecutionObservation(
            outcome="failed",
            started=True,
            termination_confirmed=True,
            reason="implementation rejected",
        )
    )
    result = _run(
        executor=executor,
        workspace=FakeWorkspace(cleanup_error=OSError("device busy")),
        lease=FakeLease(release_error=RuntimeError("release unavailable")),
    )
    assert result.primary_status == "failed"
    assert result.status == "quarantined"
    assert result.primary_error == "implementation rejected"
    assert result.cleanup_errors
    assert result.release_errors


# --------------------------------------------------------------------------
# Executor hardening
# --------------------------------------------------------------------------


def test_executor_failure_with_confirmed_termination_fails() -> None:
    executor = FakeExecutor(
        observation=PilotExecutionObservation(
            outcome="failed",
            started=True,
            termination_confirmed=True,
            reason="tests rejected the change",
        )
    )
    validator = FakeValidator()
    result = _run(executor=executor, validator=validator)
    assert result.status == "failed"
    assert "executor.failed" in result.reason_codes
    assert validator.calls == []
    assert result.lease_released is True


def test_executor_exception_is_quarantined_with_possible_partial_effects() -> None:
    result = _run(executor=FakeExecutor(error=RuntimeError("worker vanished")))
    assert result.status == "quarantined"
    assert "executor.exception" in result.reason_codes
    assert "executor.termination-unconfirmed" in result.reason_codes
    assert "executor.possible-partial-effects" in result.reason_codes
    assert result.possible_partial_effects is True


def test_executor_base_exception_is_also_quarantined() -> None:
    result = _run(executor=FakeExecutor(error=KeyboardInterrupt()))
    assert result.status == "quarantined"
    assert "executor.exception" in result.reason_codes


def test_timeout_with_confirmed_termination_is_timed_out() -> None:
    executor = FakeExecutor(
        observation=PilotExecutionObservation(
            outcome="timed-out", started=True, termination_confirmed=True
        )
    )
    result = _run(executor=executor)
    assert result.status == "timed-out"
    assert "executor.timeout" in result.reason_codes
    assert result.termination_confirmed is True
    assert result.lease_released is True


def test_timeout_without_confirmed_termination_is_quarantined() -> None:
    executor = FakeExecutor(
        observation=PilotExecutionObservation(
            outcome="timed-out", started=True, termination_confirmed=False
        )
    )
    result = _run(executor=executor)
    assert result.status == "quarantined"
    assert "executor.termination-unconfirmed" in result.reason_codes


def test_cancellation_during_execution_requires_confirmed_termination() -> None:
    confirmed = _run(
        executor=FakeExecutor(
            observation=PilotExecutionObservation(
                outcome="cancelled",
                started=True,
                cancellation_requested=True,
                termination_confirmed=True,
            )
        )
    )
    assert confirmed.status == "cancelled"

    unconfirmed = _run(
        executor=FakeExecutor(
            observation=PilotExecutionObservation(
                outcome="cancelled",
                started=True,
                cancellation_requested=True,
                termination_confirmed=False,
            )
        )
    )
    assert unconfirmed.status == "quarantined"
    assert "cancellation.unconfirmed" in unconfirmed.reason_codes


def test_suppressed_cancellation_reported_as_success_is_quarantined() -> None:
    executor = FakeExecutor(
        observation=PilotExecutionObservation(
            outcome="succeeded",
            started=True,
            cancellation_requested=True,
            termination_confirmed=True,
            changed_paths=CHANGED_PATHS,
        )
    )
    result = _run(executor=executor)
    assert result.status == "quarantined"
    assert "cancellation.unconfirmed" in result.reason_codes


def test_possible_partial_effects_always_quarantine() -> None:
    executor = FakeExecutor(
        observation=PilotExecutionObservation(
            outcome="succeeded",
            started=True,
            termination_confirmed=True,
            possible_partial_effects=True,
            changed_paths=CHANGED_PATHS,
        )
    )
    result = _run(executor=executor)
    assert result.status == "quarantined"
    assert "executor.possible-partial-effects" in result.reason_codes


def test_success_without_started_evidence_is_quarantined() -> None:
    executor = FakeExecutor(
        observation=PilotExecutionObservation(
            outcome="succeeded",
            started=False,
            termination_confirmed=True,
            changed_paths=CHANGED_PATHS,
        )
    )
    result = _run(executor=executor)
    assert result.status == "quarantined"
    assert "executor.termination-unconfirmed" in result.reason_codes


def test_unsupported_executor_observation_is_quarantined() -> None:
    result = _run(executor=FakeExecutor(observation=object()))
    assert result.status == "quarantined"
    assert "executor.termination-unconfirmed" in result.reason_codes


def test_executor_is_dispatched_at_most_once_on_every_path() -> None:
    for executor in (
        FakeExecutor(),
        FakeExecutor(error=RuntimeError("worker vanished")),
        FakeExecutor(
            observation=PilotExecutionObservation(
                outcome="failed", started=True, termination_confirmed=True
            )
        ),
    ):
        result = _run(executor=executor)
        assert len(executor.calls) <= 1
        assert result.executor_dispatch_attempts <= 1


# --------------------------------------------------------------------------
# Changed-path containment
# --------------------------------------------------------------------------


def test_forbidden_path_write_is_quarantined() -> None:
    executor = FakeExecutor(
        observation=PilotExecutionObservation(
            outcome="succeeded",
            started=True,
            termination_confirmed=True,
            changed_paths=(".github/workflows/ci.yml",),
        )
    )
    validator = FakeValidator()
    result = _run(executor=executor, validator=validator)
    assert result.status == "quarantined"
    assert "changed-paths.forbidden" in result.reason_codes
    assert validator.calls == []


def test_out_of_allowlist_write_is_quarantined() -> None:
    executor = FakeExecutor(
        observation=PilotExecutionObservation(
            outcome="succeeded",
            started=True,
            termination_confirmed=True,
            changed_paths=("README.md",),
        )
    )
    result = _run(executor=executor)
    assert result.status == "quarantined"
    assert "changed-paths.out-of-allowlist" in result.reason_codes


def test_changed_paths_are_rechecked_after_validation() -> None:
    validator = FakeValidator(
        observation=PilotValidationObservation(
            attempted=True,
            passed=True,
            completed_tests=REQUIRED_TESTS,
            changed_paths=("README.md",),
        )
    )
    result = _run(validator=validator)
    assert result.status == "quarantined"
    assert result.phase == "post-validation-path-check"
    assert "changed-paths.out-of-allowlist" in result.reason_codes


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def test_validation_failure_is_failed() -> None:
    validator = FakeValidator(
        observation=PilotValidationObservation(
            attempted=True, passed=False, reason="pytest reported failures"
        )
    )
    result = _run(validator=validator)
    assert result.status == "failed"
    assert "validation.failed" in result.reason_codes
    assert result.primary_error == "pytest reported failures"


def test_missing_required_test_is_failed() -> None:
    validator = FakeValidator(
        observation=PilotValidationObservation(
            attempted=True, passed=True, completed_tests=()
        )
    )
    result = _run(validator=validator)
    assert result.status == "failed"
    assert "validation.required-tests-missing" in result.reason_codes


def test_validation_error_is_failed() -> None:
    result = _run(validator=FakeValidator(error=RuntimeError("runner unavailable")))
    assert result.status == "failed"
    assert "validation.error" in result.reason_codes


def test_unsupported_validation_observation_needs_decision() -> None:
    result = _run(validator=FakeValidator(observation=object()))
    assert result.status == "needs-decision"
    assert "validation.error" in result.reason_codes


def test_validation_runs_exactly_once_against_the_verified_plan() -> None:
    validator = FakeValidator()
    result = _run(validator=validator)
    assert len(validator.calls) == 1
    assert validator.calls[0].plan_id == validation_plan_id(PLAN)
    assert validator.calls[0].required_tests == REQUIRED_TESTS
    assert result.validation_attempts == 1


# --------------------------------------------------------------------------
# Module boundaries
# --------------------------------------------------------------------------


def _module_tree() -> ast.Module:
    return ast.parse(inspect.getsource(pilot_module))


def _imported_roots() -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(_module_tree()):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _imported_names() -> set[str]:
    names: set[str] = set()
    for node in ast.walk(_module_tree()):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names.add(module)
            names.update(f"{module}.{alias.name}" for alias in node.names)
    return names


def test_module_has_no_io_network_persistence_or_clock_imports() -> None:
    assert _imported_roots().isdisjoint(
        {
            "asyncio",
            "boto3",
            "concurrent",
            "datetime",
            "github",
            "google",
            "http",
            "multiprocessing",
            "os",
            "pathlib",
            "queue",
            "requests",
            "shutil",
            "signal",
            "socket",
            "sqlalchemy",
            "sqlite3",
            "subprocess",
            "tempfile",
            "threading",
            "time",
            "urllib",
        }
    )


def test_module_never_imports_retry_manager_or_the_legacy_executor() -> None:
    names = _imported_names()
    assert not any("RetryManager" in name for name in names)
    assert not any(name.endswith("execution.executor") for name in names)
    assert not any("retry" in name.lower() for name in names)


def test_module_defines_no_queue_daemon_or_persistence_calls() -> None:
    banned_calls = {
        "Queue",
        "Thread",
        "Process",
        "connect",
        "daemon",
        "open",
        "sleep",
        "spawn",
        "urlopen",
    }
    called: set[str] = set()
    for node in ast.walk(_module_tree()):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Name):
            called.add(function.id)
        elif isinstance(function, ast.Attribute):
            called.add(function.attr)
    assert called.isdisjoint(banned_calls)


def test_module_reuses_only_canonical_upstream_apis() -> None:
    roots = _imported_roots()
    assert roots <= {
        "__future__",
        "dataclasses",
        "hashlib",
        "json",
        "scripts",
        "typing",
        "workflow_scheduler",
    }
