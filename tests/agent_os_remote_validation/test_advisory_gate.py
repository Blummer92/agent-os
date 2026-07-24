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
    MAX_ADVISORY_SERIALIZED_BYTES,
    SuppliedCommandResult,
    advisory_evidence_result_id,
    evaluate_advisory_pre_pr_evidence,
    serialize_advisory_evidence_result,
)
from scripts.agent_os_remote_validation import advisory_gate as gate_module
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
INVOCATION_ID = "run-570-1"


def _identity() -> RepositoryIdentity:
    return RepositoryIdentity(
        host="github.com",
        owner="blummer92",
        repository="agent-os",
        repository_id=1289370915,
        is_fork=False,
        default_branch="main",
    )


def _projection(
    *,
    status: str = "accepted",
    synthetic: bool = False,
) -> GovernedProjectionEvidenceResult:
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
        tested_sha=MERGE_SHA if synthetic else HEAD_SHA,
        repository_evidence_type=(
            RepositoryEvidenceType.SYNTHETIC_PR_MERGE
            if synthetic
            else RepositoryEvidenceType.BRANCH_HEAD
        ),
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
    return ValidationPlan(
        selector_version="1.0.0",
        repository="Blummer92/agent-os",
        pull_request=570,
        base_sha=BASE_SHA,
        head_sha=HEAD_SHA,
        profile=profile,
        commands=commands,
        command_set_digest=digest,
        reason_codes=(f"profile.{profile}",),
        remote_build_required=profile in {"focused", "aggregate"},
    )


def _result(
    plan: ValidationPlan,
    *,
    tested_sha: str = HEAD_SHA,
    status: str = "passed",
    exit_code: int | None = 0,
    invocation_id: str = INVOCATION_ID,
    diagnostic_summary: str = "",
) -> SuppliedCommandResult:
    return SuppliedCommandResult(
        plan_id=validation_plan_id(plan),
        invocation_id=invocation_id,
        runner_id=RUNNER_ID,
        command_ordinal=0,
        command=plan.commands[0],
        source_head_sha=HEAD_SHA,
        tested_sha=tested_sha,
        started_at="2026-07-24T15:00:01Z",
        completed_at="2026-07-24T15:00:02Z",
        status=status,
        exit_code=exit_code,
        diagnostic_summary=diagnostic_summary,
        diagnostic_truncated=False,
    )


def _evaluate(
    *,
    projection=None,
    plan: ValidationPlan | None = None,
    results: object | None = None,
    synthetic: bool = False,
    **overrides: object,
):
    resolved_plan = plan or _plan()
    resolved_projection = projection or _projection(synthetic=synthetic)
    tested_sha = MERGE_SHA if synthetic else HEAD_SHA
    if results is None:
        results = tuple(
            _result(resolved_plan, tested_sha=tested_sha)
            for _ in resolved_plan.commands
        )
    values = {
        "expected_repository": _identity(),
        "expected_pull_request": 570,
        "expected_base_branch": "main",
        "expected_base_sha": BASE_SHA,
        "expected_source_head_sha": HEAD_SHA,
        "expected_tested_sha": tested_sha,
        "current_base_sha": BASE_SHA,
        "current_source_head_sha": HEAD_SHA,
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
        "started_at": "2026-07-24T15:00:00Z",
        "completed_at": "2026-07-24T15:01:00Z",
    }
    values.update(overrides)
    return evaluate_advisory_pre_pr_evidence(
        resolved_projection,
        resolved_plan,
        results,
        **values,
    )


@pytest.mark.parametrize("profile", ["static", "focused", "aggregate"])
def test_passed_profiles_are_fully_bound(profile: str) -> None:
    plan = _plan(profile=profile)
    result = _evaluate(plan=plan, results=() if profile == "static" else None)
    assert result.status == "passed"
    assert result.base_sha == BASE_SHA
    assert result.source_head_sha == HEAD_SHA
    assert result.tested_sha == HEAD_SHA
    assert result.plan_id == validation_plan_id(plan)
    assert result.authoritative is False
    assert result.execution_authorized is False
    assert result.merge_authorized is False
    assert result.attestation_verified is False
    assert result.side_effects_performed is False


def test_synthetic_merge_preserves_three_sha_roles() -> None:
    result = _evaluate(plan=_plan(profile="aggregate"), synthetic=True)
    assert result.status == "passed"
    assert result.base_sha == BASE_SHA
    assert result.source_head_sha == HEAD_SHA
    assert result.tested_sha == MERGE_SHA


@pytest.mark.parametrize(
    ("status", "exit_code"),
    [("failed", 1), ("timed-out", None), ("cancelled", None)],
)
def test_terminal_failures_map_to_failed_and_preserve_source_status(
    status: str, exit_code: int | None
) -> None:
    plan = _plan()
    result = _evaluate(results=(_result(plan, status=status, exit_code=exit_code),))
    assert result.status == "failed"
    assert result.command_result_statuses == (status,)


@pytest.mark.parametrize(
    ("status", "exit_code"),
    [("unavailable", None), ("infrastructure-error", None)],
)
def test_unavailable_results_need_decision(status: str, exit_code: int | None) -> None:
    plan = _plan()
    result = _evaluate(results=(_result(plan, status=status, exit_code=exit_code),))
    assert result.status == "needs-decision"


def test_manual_review_and_blocked_projection_need_decision() -> None:
    plan = _plan(profile="manual-review")
    assert _evaluate(plan=plan, results=()).status == "needs-decision"
    assert _evaluate(projection=_projection(status="blocked")).status == "needs-decision"


def test_missing_results_are_incomplete() -> None:
    assert _evaluate(results=()).status == "incomplete"


def test_explicit_current_revision_drift_is_stale() -> None:
    assert _evaluate(current_base_sha="d" * 40).status == "stale"
    assert _evaluate(current_source_head_sha="e" * 40).status == "stale"
    assert _evaluate(projection=_projection(status="stale")).status == "stale"


def test_invalid_precedes_stale_and_failed() -> None:
    plan = _plan()
    result = _evaluate(
        results=(
            replace(
                _result(plan, status="failed", exit_code=1),
                invocation_id="other-run",
            ),
        ),
        current_base_sha="d" * 40,
    )
    assert result.status == "invalid"


def test_malformed_types_and_mappings_return_invalid() -> None:
    assert _evaluate(projection={}).status == "invalid"
    assert _evaluate(plan={}).status == "invalid"  # type: ignore[arg-type]
    assert _evaluate(results=[]).status == "invalid"


def test_cross_run_plan_sha_and_expected_bundle_mixing_fail_closed() -> None:
    plan = _plan()
    base = _result(plan)
    assert _evaluate(results=(replace(base, invocation_id="other"),)).status == "invalid"
    assert _evaluate(
        results=(replace(base, plan_id="validation-plan:" + "0" * 64),)
    ).status == "invalid"
    assert _evaluate(results=(replace(base, tested_sha="d" * 40),)).status == "invalid"
    assert _evaluate(
        expected_bundle_id="validation-evidence-bundle:" + "0" * 64
    ).status == "invalid"


def test_command_diagnostics_do_not_propagate_to_advisory_output() -> None:
    plan = _plan()
    marker = "safe bounded diagnostic"
    result = _evaluate(results=(_result(plan, diagnostic_summary=marker),))
    serialized = serialize_advisory_evidence_result(result)
    assert marker not in repr(serialized)
    assert "diagnostic" not in serialized


def test_unicode_is_preserved_without_normalization() -> None:
    composed = "caf\u00e9"
    decomposed = "cafe\u0301"
    first = _evaluate(invocation_id=composed)
    second = _evaluate(invocation_id=decomposed)
    assert first.invocation_id == composed
    assert second.invocation_id == decomposed
    assert first.result_id != second.result_id


def test_timestamp_changes_do_not_establish_freshness() -> None:
    first = _evaluate(started_at="2026-07-24T15:00:00Z")
    second = _evaluate(started_at="2026-07-24T14:59:59Z")
    assert first.status == "passed"
    assert second.status == "passed"
    assert first.result_id != second.result_id


def test_serialization_is_deterministic_and_tamper_evident() -> None:
    first = _evaluate()
    second = _evaluate()
    assert serialize_advisory_evidence_result(first) == serialize_advisory_evidence_result(
        second
    )
    assert advisory_evidence_result_id(first) == first.result_id
    with pytest.raises(ValueError, match="result ID mismatch"):
        serialize_advisory_evidence_result(
            replace(first, result_id="advisory-evidence:" + "0" * 64)
        )


def test_result_is_immutable() -> None:
    result = _evaluate()
    with pytest.raises(FrozenInstanceError):
        result.status = "failed"  # type: ignore[misc]


def test_serializer_enforces_final_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _evaluate()
    monkeypatch.setattr(gate_module, "MAX_ADVISORY_SERIALIZED_BYTES", 1)
    with pytest.raises(ValueError, match="canonical size limit"):
        serialize_advisory_evidence_result(result)


def test_only_expected_validation_errors_are_converted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gate_module,
        "build_validation_evidence_bundle",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("programmer defect")),
    )
    with pytest.raises(RuntimeError, match="programmer defect"):
        _evaluate()


def test_module_has_no_external_io_execution_or_clock_imports() -> None:
    tree = ast.parse(inspect.getsource(gate_module))
    banned = {
        "os",
        "pathlib",
        "socket",
        "subprocess",
        "requests",
        "urllib",
        "time",
        "datetime",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(banned)


def test_default_result_fits_declared_size_limit() -> None:
    result = _evaluate()
    encoded = repr(serialize_advisory_evidence_result(result)).encode("utf-8")
    assert len(encoded) < MAX_ADVISORY_SERIALIZED_BYTES
