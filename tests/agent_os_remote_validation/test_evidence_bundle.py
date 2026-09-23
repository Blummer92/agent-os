from __future__ import annotations

import ast
import inspect
from dataclasses import FrozenInstanceError, replace

import pytest

from scripts.agent_os_execution_capabilities.approved_projection import (
    GovernedProjectionEvidenceResult,
)
from scripts.agent_os_execution_capabilities.models import (
    RepositoryEvidenceType,
    RepositoryIdentity,
)
from scripts.agent_os_remote_validation import (
    MAX_RESULT_DIAGNOSTIC_LENGTH,
    SuppliedCommandResult,
    build_validation_evidence_bundle,
    serialize_validation_evidence_bundle,
    validation_evidence_bundle_id,
)
from scripts.agent_os_remote_validation import evidence_bundle as bundle_module
from scripts.agent_os_remote_validation.models import ValidationPlan
from scripts.agent_os_remote_validation.selector import (
    compute_command_set_digest,
    validation_plan_id,
)

BASE_SHA = "b" * 40
HEAD_SHA = "a" * 40
MERGE_SHA = "c" * 40
CONTRACT = "1" * 64
PROJECTION_ID = "projection:" + "2" * 64
PROPOSAL_ID = "proposal:" + "3" * 64
APPROVAL_ID = "approval:" + "4" * 64
EVIDENCE_ID = "repository-state:" + "5" * 64
RUNNER_ID = "github-actions"
INVOCATION_ID = "run-562-1"


def _identity(**overrides: object) -> RepositoryIdentity:
    values = {
        "host": "github.com",
        "owner": "blummer92",
        "repository": "agent-os",
        "repository_id": 1289370915,
        "is_fork": False,
        "default_branch": "main",
    }
    values.update(overrides)
    return RepositoryIdentity(**values)


def _projection(*, synthetic: bool = False, status: str = "accepted"):
    tested_sha = MERGE_SHA if synthetic else HEAD_SHA
    evidence_type = (
        RepositoryEvidenceType.SYNTHETIC_PR_MERGE
        if synthetic
        else RepositoryEvidenceType.BRANCH_HEAD
    )
    reasons = () if status == "accepted" else ("ref.branch-moved",)
    return GovernedProjectionEvidenceResult(
        status=status,
        schema_version="1.0",
        projection_id=PROJECTION_ID,
        proposal_id=PROPOSAL_ID,
        approval_id=APPROVAL_ID,
        repository_identity=_identity(),
        base_branch="main",
        base_sha=BASE_SHA,
        head_sha=HEAD_SHA,
        evaluated_sha=BASE_SHA,
        tested_sha=tested_sha,
        repository_evidence_type=evidence_type,
        repository_state_evidence_id=EVIDENCE_ID,
        implementation_contract_fingerprint=CONTRACT,
        reason_codes=reasons,
        details=("fixture",) if reasons else (),
    )


def _plan(*, profile: str = "focused") -> ValidationPlan:
    commands = {
        "static": (),
        "focused": ("python -m pytest tests/agent_os_remote_validation -q",),
        "aggregate": ("python -m pytest",),
        "manual-review": (),
    }[profile]
    digest = (
        "unavailable"
        if profile == "manual-review"
        else compute_command_set_digest("1.0.0", commands)
    )
    reason = {
        "static": "profile.documentation-static",
        "focused": "profile.focused-package",
        "aggregate": "profile.aggregate-configuration",
        "manual-review": "rule.ambiguous",
    }[profile]
    return ValidationPlan(
        selector_version="1.0.0",
        repository="Blummer92/agent-os",
        pull_request=562,
        base_sha=BASE_SHA,
        head_sha=HEAD_SHA,
        profile=profile,
        commands=commands,
        command_set_digest=digest,
        reason_codes=(reason,),
        remote_build_required=profile in {"focused", "aggregate"},
    )


def _result(
    plan: ValidationPlan,
    *,
    tested_sha: str = HEAD_SHA,
    ordinal: int = 0,
    status: str = "passed",
    exit_code: int | None = 0,
    diagnostic_summary: str = "",
    invocation_id: str = INVOCATION_ID,
    runner_id: str = RUNNER_ID,
) -> SuppliedCommandResult:
    return SuppliedCommandResult(
        plan_id=validation_plan_id(plan),
        invocation_id=invocation_id,
        runner_id=runner_id,
        command_ordinal=ordinal,
        command=plan.commands[ordinal],
        source_head_sha=HEAD_SHA,
        tested_sha=tested_sha,
        started_at="2026-07-24T14:00:01Z",
        completed_at="2026-07-24T14:00:02Z",
        status=status,
        exit_code=exit_code,
        diagnostic_summary=diagnostic_summary,
        diagnostic_truncated=False,
    )


def _build(
    *,
    projection=None,
    plan: ValidationPlan | None = None,
    results: tuple[SuppliedCommandResult, ...] | None = None,
    synthetic: bool = False,
    **overrides: object,
):
    resolved_projection = projection or _projection(synthetic=synthetic)
    resolved_plan = plan or _plan()
    tested_sha = MERGE_SHA if synthetic else HEAD_SHA
    resolved_results = (
        results
        if results is not None
        else tuple(
            _result(resolved_plan, tested_sha=tested_sha, ordinal=index)
            for index in range(len(resolved_plan.commands))
        )
    )
    values = {
        "expected_repository": _identity(),
        "expected_pull_request": 562,
        "expected_base_branch": "main",
        "expected_base_sha": BASE_SHA,
        "expected_source_head_sha": HEAD_SHA,
        "expected_tested_sha": tested_sha,
        "expected_repository_evidence_type": (
            RepositoryEvidenceType.SYNTHETIC_PR_MERGE
            if synthetic
            else RepositoryEvidenceType.BRANCH_HEAD
        ),
        "expected_projection_id": PROJECTION_ID,
        "expected_proposal_id": PROPOSAL_ID,
        "expected_approval_id": APPROVAL_ID,
        "expected_repository_state_evidence_id": EVIDENCE_ID,
        "expected_implementation_contract_fingerprint": CONTRACT,
        "expected_selector_version": resolved_plan.selector_version,
        "expected_profile": resolved_plan.profile,
        "expected_command_set_digest": resolved_plan.command_set_digest,
        "expected_plan_id": validation_plan_id(resolved_plan),
        "runner_id": RUNNER_ID,
        "invocation_id": INVOCATION_ID,
        "started_at": "2026-07-24T14:00:00Z",
        "completed_at": "2026-07-24T14:01:00Z",
    }
    values.update(overrides)
    return build_validation_evidence_bundle(
        resolved_projection,
        resolved_plan,
        resolved_results,
        **values,
    )


def test_valid_focused_bundle_is_passed_and_fully_bound() -> None:
    bundle = _build()
    assert bundle.status == "passed"
    assert bundle.reason_codes == ()
    assert bundle.base_sha == BASE_SHA
    assert bundle.source_head_sha == HEAD_SHA
    assert bundle.tested_sha == HEAD_SHA
    assert bundle.pull_request == 562
    assert bundle.plan_id == validation_plan_id(_plan())
    assert len(bundle.command_results) == 1
    assert bundle.command_results[0].result_id.startswith("command-result:")
    assert bundle.authoritative is False
    assert bundle.execution_authorized is False
    assert bundle.merge_authorized is False
    assert bundle.attestation_verified is False
    assert bundle.side_effects_performed is False


def test_synthetic_merge_preserves_distinct_sha_roles() -> None:
    plan = _plan(profile="aggregate")
    bundle = _build(plan=plan, synthetic=True)
    assert BASE_SHA != HEAD_SHA != MERGE_SHA
    assert bundle.status == "passed"
    assert bundle.base_sha == BASE_SHA
    assert bundle.source_head_sha == HEAD_SHA
    assert bundle.tested_sha == MERGE_SHA
    assert bundle.repository_evidence_type is RepositoryEvidenceType.SYNTHETIC_PR_MERGE


def test_static_plan_accepts_exactly_zero_results() -> None:
    plan = _plan(profile="static")
    bundle = _build(plan=plan, results=())
    assert bundle.status == "passed"
    assert bundle.command_results == ()


def test_manual_review_plan_needs_decision() -> None:
    plan = _plan(profile="manual-review")
    bundle = _build(plan=plan, results=())
    assert bundle.status == "needs-decision"
    assert bundle.reason_codes == ("plan.manual-review",)


@pytest.mark.parametrize(
    ("status", "exit_code", "expected"),
    [
        ("failed", 1, "failed"),
        ("timed-out", None, "timed-out"),
        ("cancelled", None, "cancelled"),
        ("unavailable", None, "needs-decision"),
        ("infrastructure-error", None, "needs-decision"),
    ],
)
def test_truthful_terminal_outcomes_remain_distinct(
    status: str, exit_code: int | None, expected: str
) -> None:
    plan = _plan()
    bundle = _build(results=(_result(plan, status=status, exit_code=exit_code),))
    assert bundle.status == expected


def test_exit_codes_are_not_fabricated() -> None:
    plan = _plan()
    timed_out = _result(plan, status="timed-out", exit_code=124)
    assert _build(results=(timed_out,)).status == "invalid"
    false_pass = _result(plan, status="passed", exit_code=1)
    assert _build(results=(false_pass,)).status == "invalid"


def test_nonaccepted_projection_and_plan_mismatches_fail_closed() -> None:
    assert _build(projection=_projection(status="stale")).status == "invalid"
    assert _build(expected_plan_id="validation-plan:" + "0" * 64).status == "invalid"
    assert _build(expected_source_head_sha="d" * 40).status == "invalid"


def test_missing_extra_duplicate_and_reordered_results_fail_closed() -> None:
    plan = _plan()
    assert _build(plan=plan, results=()).status == "incomplete"
    result = _result(plan)
    assert _build(plan=plan, results=(result, result)).status == "invalid"
    wrong_order = replace(result, command_ordinal=1)
    assert _build(plan=plan, results=(wrong_order,)).status == "invalid"


def test_cross_run_cross_plan_and_sha_mixing_fail_closed() -> None:
    plan = _plan()
    result = _result(plan)
    assert _build(results=(replace(result, invocation_id="run-other"),)).status == "invalid"
    assert _build(results=(replace(result, runner_id="runner-other"),)).status == "invalid"
    assert _build(
        results=(replace(result, plan_id="validation-plan:" + "0" * 64),)
    ).status == "invalid"
    assert _build(results=(replace(result, tested_sha="d" * 40),)).status == "invalid"


def test_timestamp_and_diagnostic_controls_fail_closed() -> None:
    plan = _plan()
    result = _result(plan)
    reversed_time = replace(
        result,
        started_at="2026-07-24T14:00:03Z",
        completed_at="2026-07-24T14:00:02Z",
    )
    assert _build(results=(reversed_time,)).status == "invalid"
    assert _build(
        results=(replace(result, diagnostic_summary="token=secret"),)
    ).status == "invalid"
    assert _build(
        results=(replace(result, diagnostic_summary="bad\x00value"),)
    ).status == "invalid"
    oversized = "x" * (MAX_RESULT_DIAGNOSTIC_LENGTH + 1)
    assert _build(
        results=(replace(result, diagnostic_summary=oversized),)
    ).status == "invalid"


def test_serialization_and_ids_are_deterministic_and_tamper_evident() -> None:
    first = _build()
    second = _build()
    assert first == second
    assert serialize_validation_evidence_bundle(
        first
    ) == serialize_validation_evidence_bundle(second)
    assert validation_evidence_bundle_id(first) == first.bundle_id

    plan = _plan()
    changed = _build(
        results=(_result(plan, diagnostic_summary="bounded diagnostic"),)
    )
    assert changed.bundle_id != first.bundle_id

    with pytest.raises(ValueError, match="bundle ID mismatch"):
        serialize_validation_evidence_bundle(
            replace(first, bundle_id="validation-evidence-bundle:" + "0" * 64)
        )


def test_bundle_and_command_evidence_are_immutable() -> None:
    bundle = _build()
    with pytest.raises(FrozenInstanceError):
        bundle.status = "failed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        bundle.command_results[0].status = "failed"  # type: ignore[misc]


def test_module_has_no_external_io_or_execution_imports() -> None:
    tree = ast.parse(inspect.getsource(bundle_module))
    banned = {"os", "pathlib", "socket", "subprocess", "requests", "urllib", "time"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(banned)
