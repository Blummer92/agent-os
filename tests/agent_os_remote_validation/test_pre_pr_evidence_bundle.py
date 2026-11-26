from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.agent_os_execution_capabilities.models import RepositoryEvidenceType
from scripts.agent_os_remote_validation import (
    PrePrValidationPlan,
    PrePrValidationSubject,
    SuppliedCommandResult,
    compute_command_set_digest,
    pre_pr_validation_plan_id,
)
from scripts.agent_os_remote_validation.evidence_bundle import (
    reconstruct_validation_evidence_bundle,
    serialize_validation_evidence_bundle,
    validation_evidence_bundle_id,
)
from scripts.agent_os_remote_validation.pre_pr_evidence_bundle import (
    build_pre_pr_validation_evidence_bundle,
    pre_pr_validation_evidence_bundle_id,
    reconstruct_pre_pr_validation_evidence_bundle,
    serialize_pre_pr_validation_evidence_bundle,
)
from tests.agent_os_remote_validation.test_evidence_bundle import (
    APPROVAL_ID,
    BASE_SHA,
    CONTRACT,
    EVIDENCE_ID,
    HEAD_SHA,
    PROPOSAL_ID,
    PROJECTION_ID,
    _identity,
    _projection,
)

COMMAND = "python -m pytest tests/agent_os_remote_validation"


def _plan() -> PrePrValidationPlan:
    subject = PrePrValidationSubject(
        repository="Blummer92/agent-os",
        issue_number=1985,
        invocation_id="pre-pr-1985",
        base_branch="main",
        base_sha=BASE_SHA,
        branch="agent/issue-1985-pre-validation-evidence-part2",
        expected_source_sha=HEAD_SHA,
        tested_sha=HEAD_SHA,
        allowed_files=("tests/agent_os_remote_validation",),
        forbidden_paths=(".github/workflows",),
        required_command_identities=(COMMAND,),
        approval_id=APPROVAL_ID,
        approval_revision=1,
        projection_id=PROJECTION_ID,
        implementation_contract_fingerprint=CONTRACT,
        expected_changed_paths=("tests/agent_os_remote_validation",),
        candidate_bound=True,
    )
    return PrePrValidationPlan(
        selector_version="1.0.0",
        subject=subject,
        commands=(COMMAND,),
        command_set_digest=compute_command_set_digest("1.0.0", (COMMAND,)),
        reason_codes=("profile.focused-package",),
    )


def _result(plan: PrePrValidationPlan) -> SuppliedCommandResult:
    return SuppliedCommandResult(
        plan_id=pre_pr_validation_plan_id(plan),
        invocation_id=plan.subject.invocation_id,
        runner_id="dev-validation:remote-validation",
        command_ordinal=0,
        command=COMMAND,
        source_head_sha=HEAD_SHA,
        tested_sha=HEAD_SHA,
        started_at="2026-09-08T17:00:00Z",
        completed_at="2026-09-08T17:00:01Z",
        status="passed",
        exit_code=0,
    )


def _bundle(plan: PrePrValidationPlan):
    return build_pre_pr_validation_evidence_bundle(
        _projection(),
        plan,
        (_result(plan),),
        expected_repository=_identity(),
        expected_repository_evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        expected_proposal_id=PROPOSAL_ID,
        expected_repository_state_evidence_id=EVIDENCE_ID,
        runner_id="dev-validation:remote-validation",
        started_at="2026-09-08T17:00:00Z",
        completed_at="2026-09-08T17:00:01Z",
    )


def test_pr_less_bundle_carries_canonical_plan_without_dummy_pr() -> None:
    plan = _plan()
    bundle = _bundle(plan)

    assert bundle.status == "passed"
    assert bundle.pull_request is None
    assert bundle.validation_plan is plan
    assert bundle.plan_id == pre_pr_validation_plan_id(plan)
    assert bundle.execution_authorized is False
    payload = serialize_pre_pr_validation_evidence_bundle(bundle)
    assert payload["pull_request"] is None
    assert payload["validation_plan"]["subject"]["issue_number"] == 1985
    assert pre_pr_validation_evidence_bundle_id(bundle) == bundle.bundle_id


def test_pr_less_bundle_round_trips_without_positive_pr_assumption() -> None:
    plan = _plan()
    bundle = _bundle(plan)
    payload = serialize_pre_pr_validation_evidence_bundle(bundle)

    reconstructed = reconstruct_pre_pr_validation_evidence_bundle(payload)

    assert reconstructed.pull_request is None
    assert type(reconstructed.validation_plan) is PrePrValidationPlan
    assert reconstructed.validation_plan == plan
    assert pre_pr_validation_evidence_bundle_id(reconstructed) == bundle.bundle_id
    assert serialize_pre_pr_validation_evidence_bundle(reconstructed) == payload


def test_canonical_bundle_api_dispatches_pr_less_without_fabricating_pr() -> None:
    plan = _plan()
    bundle = _bundle(plan)

    payload = serialize_validation_evidence_bundle(bundle)
    reconstructed = reconstruct_validation_evidence_bundle(payload)

    assert payload["pull_request"] is None
    assert payload["validation_plan"]["subject"]["issue_number"] == 1985
    assert type(reconstructed.validation_plan) is PrePrValidationPlan
    assert reconstructed.validation_plan == plan
    assert reconstructed.pull_request is None
    assert validation_evidence_bundle_id(reconstructed) == bundle.bundle_id
    assert serialize_validation_evidence_bundle(reconstructed) == payload


def test_pr_less_bundle_rejects_fabricated_positive_pr() -> None:
    bundle = _bundle(_plan())
    with pytest.raises(ValueError, match="must not carry a pull request"):
        serialize_pre_pr_validation_evidence_bundle(replace(bundle, pull_request=1))


def test_pr_less_bundle_identity_changes_with_observed_result() -> None:
    plan = _plan()
    first = _bundle(plan)
    changed = SuppliedCommandResult(
        plan_id=pre_pr_validation_plan_id(plan),
        invocation_id=plan.subject.invocation_id,
        runner_id="dev-validation:remote-validation",
        command_ordinal=0,
        command=COMMAND,
        source_head_sha=HEAD_SHA,
        tested_sha=HEAD_SHA,
        started_at="2026-09-08T17:00:00Z",
        completed_at="2026-09-08T17:00:01Z",
        status="passed",
        exit_code=0,
        diagnostic_summary="bounded observation",
    )
    second = build_pre_pr_validation_evidence_bundle(
        _projection(),
        plan,
        (changed,),
        expected_repository=_identity(),
        expected_repository_evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        expected_proposal_id=PROPOSAL_ID,
        expected_repository_state_evidence_id=EVIDENCE_ID,
        runner_id="dev-validation:remote-validation",
        started_at="2026-09-08T17:00:00Z",
        completed_at="2026-09-08T17:00:01Z",
    )
    assert first.bundle_id != second.bundle_id
