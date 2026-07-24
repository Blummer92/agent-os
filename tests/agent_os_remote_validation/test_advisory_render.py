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
    AdvisoryRenderResult,
    SuppliedCommandResult,
    advisory_render_result_id,
    evaluate_advisory_pre_pr_evidence,
    observe_advisory_evidence_shadow,
    render_advisory_evidence,
    serialize_advisory_render_result,
)
from scripts.agent_os_remote_validation import advisory_render as render_module
from scripts.agent_os_remote_validation.models import ValidationPlan
from scripts.agent_os_remote_validation.selector import (
    compute_command_set_digest,
    validation_plan_id,
)

BASE_SHA = "b" * 40
HEAD_SHA = "a" * 40
CONTRACT = "1" * 64
PROJECTION_ID = "projection:" + "2" * 64
PROPOSAL_ID = "proposal:" + "3" * 64
APPROVAL_ID = "approval:" + "4" * 64
EVIDENCE_ID = "repository-state:" + "5" * 64
RUNNER_ID = "github-actions"


def _identity() -> RepositoryIdentity:
    return RepositoryIdentity(
        host="github.com",
        owner="blummer92",
        repository="agent-os",
        repository_id=1289370915,
        is_fork=False,
        default_branch="main",
    )


def _projection(*, status: str = "accepted") -> GovernedProjectionEvidenceResult:
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
        tested_sha=HEAD_SHA,
        repository_evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        repository_state_evidence_id=EVIDENCE_ID,
        implementation_contract_fingerprint=CONTRACT,
        reason_codes=reasons,
        details=("fixture",) if reasons else (),
    )


def _plan(*, profile: str = "focused") -> ValidationPlan:
    commands = {
        "focused": ("python -m pytest tests/agent_os_remote_validation -q",),
        "manual-review": (),
    }[profile]
    digest = (
        "unavailable"
        if profile == "manual-review"
        else compute_command_set_digest("1.0.0", commands)
    )
    reason = {
        "focused": "profile.focused-package",
        "manual-review": "rule.ambiguous",
    }[profile]
    return ValidationPlan(
        selector_version="1.0.0",
        repository="Blummer92/agent-os",
        pull_request=574,
        base_sha=BASE_SHA,
        head_sha=HEAD_SHA,
        profile=profile,
        commands=commands,
        command_set_digest=digest,
        reason_codes=(reason,),
        remote_build_required=profile == "focused",
    )


def _command_result(
    plan: ValidationPlan,
    *,
    status: str = "passed",
    exit_code: int | None = 0,
    invocation_id: str = "run-574",
) -> SuppliedCommandResult:
    return SuppliedCommandResult(
        plan_id=validation_plan_id(plan),
        invocation_id=invocation_id,
        runner_id=RUNNER_ID,
        command_ordinal=0,
        command=plan.commands[0],
        source_head_sha=HEAD_SHA,
        tested_sha=HEAD_SHA,
        started_at="2026-07-24T15:00:01Z",
        completed_at="2026-07-24T15:00:02Z",
        status=status,
        exit_code=exit_code,
        diagnostic_summary="must not render",
        diagnostic_truncated=False,
    )


def _advisory(status: str = "passed", *, invocation_id: str = "run-574"):
    projection = _projection(status="stale" if status == "stale" else "accepted")
    plan = _plan(profile="manual-review" if status == "needs-decision" else "focused")
    if status == "passed":
        results = (_command_result(plan, invocation_id=invocation_id),)
    elif status == "failed":
        results = (
            _command_result(
                plan,
                status="failed",
                exit_code=1,
                invocation_id=invocation_id,
            ),
        )
    elif status == "incomplete":
        results = ()
    elif status == "stale":
        results = (_command_result(plan, invocation_id=invocation_id),)
    elif status == "invalid":
        results = (_command_result(plan, invocation_id=invocation_id),)
    elif status == "needs-decision":
        results = ()
    else:
        raise AssertionError(f"unsupported test status: {status}")

    values: dict[str, object] = {
        "expected_repository": _identity(),
        "expected_pull_request": 574,
        "expected_base_branch": "main",
        "expected_base_sha": BASE_SHA,
        "expected_source_head_sha": HEAD_SHA,
        "expected_tested_sha": HEAD_SHA,
        "current_base_sha": BASE_SHA,
        "current_source_head_sha": HEAD_SHA,
        "expected_repository_evidence_type": RepositoryEvidenceType.BRANCH_HEAD,
        "expected_projection_id": PROJECTION_ID,
        "expected_proposal_id": PROPOSAL_ID,
        "expected_approval_id": APPROVAL_ID,
        "expected_repository_state_evidence_id": EVIDENCE_ID,
        "expected_implementation_contract_fingerprint": CONTRACT,
        "expected_selector_version": plan.selector_version,
        "expected_profile": plan.profile,
        "expected_command_set_digest": plan.command_set_digest,
        "expected_plan_id": validation_plan_id(plan),
        "runner_id": RUNNER_ID,
        "invocation_id": invocation_id,
        "started_at": "2026-07-24T15:00:00Z",
        "completed_at": "2026-07-24T15:01:00Z",
    }
    if status == "invalid":
        values["expected_bundle_id"] = "validation-evidence-bundle:" + "0" * 64

    result = evaluate_advisory_pre_pr_evidence(projection, plan, results, **values)
    assert result.status == status
    return result


@pytest.mark.parametrize(
    "status",
    ["passed", "failed", "incomplete", "stale", "invalid", "needs-decision"],
)
def test_renders_real_canonical_gex3_results(status: str) -> None:
    result = render_advisory_evidence(_advisory(status))
    assert result.status == status
    assert result.authoritative is False
    assert result.implementation_authorized is False
    assert result.execution_authorized is False
    assert result.merge_authorized is False
    assert result.attestation_verified is False
    assert result.side_effects_performed is False
    assert f'status="{status}"' in result.lines


def test_preserves_three_sha_roles_and_ordered_results() -> None:
    result = render_advisory_evidence(_advisory())
    assert 'base_sha="' + BASE_SHA + '"' in result.lines
    assert 'source_head_sha="' + HEAD_SHA + '"' in result.lines
    assert 'tested_sha="' + HEAD_SHA + '"' in result.lines
    result_ids = next(line for line in result.lines if line.startswith("command_result_ids="))
    statuses = next(
        line for line in result.lines if line.startswith("command_result_statuses=")
    )
    assert "command-result:" in result_ids
    assert statuses.endswith('["passed"]')


def test_render_is_deterministic_and_tamper_evident() -> None:
    first = render_advisory_evidence(_advisory())
    second = render_advisory_evidence(_advisory())
    assert serialize_advisory_render_result(first) == serialize_advisory_render_result(
        second
    )
    assert advisory_render_result_id(first) == first.render_id
    with pytest.raises(ValueError, match="render ID mismatch"):
        serialize_advisory_render_result(
            replace(first, render_id="advisory-render:" + "0" * 64)
        )
    with pytest.raises(ValueError, match="result ID mismatch"):
        render_advisory_evidence(
            replace(_advisory(), result_id="advisory-evidence:" + "0" * 64)
        )


def test_rejects_wrong_types_duplicates_and_identity_disagreement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(TypeError):
        render_advisory_evidence({})
    with pytest.raises(TypeError):
        observe_advisory_evidence_shadow([])
    advisory = _advisory()
    with pytest.raises(ValueError, match="duplicate"):
        observe_advisory_evidence_shadow((advisory, advisory))
    monkeypatch.setattr(render_module, "advisory_evidence_result_id", lambda result: "other")
    with pytest.raises(ValueError, match="identity mismatch"):
        render_advisory_evidence(advisory)


def test_output_has_exact_authority_notices_and_no_diagnostics() -> None:
    result = render_advisory_evidence(_advisory())
    text = "\n".join(result.lines).lower()
    for marker in (
        "advisory_only=true",
        "authoritative=false",
        "implementation_authorized=false",
        "execution_authorized=false",
        "merge_authorized=false",
        "attestation_verified=false",
        "freshness_proven=false",
        "provenance_verified=false",
        "side_effects_performed=false",
    ):
        assert marker in text
    for forbidden in (
        "must not render",
        "stdout",
        "stderr",
        "token=",
        "authorization:",
        "environment=",
    ):
        assert forbidden not in text

    with pytest.raises(ValueError, match="notices"):
        serialize_advisory_render_result(
            replace(result, lines=result.lines[:-1] + ("side_effects_performed=true",))
        )


def test_unicode_is_preserved_and_line_breaks_are_json_escaped() -> None:
    composed = render_module._line("details", "caf\u00e9\nnext")
    decomposed = render_module._line("details", "cafe\u0301\nnext")
    assert composed != decomposed
    assert "caf\u00e9" in composed
    assert "\n" not in composed
    assert "\\n" in composed


def test_render_result_is_immutable() -> None:
    result = render_advisory_evidence(_advisory())
    with pytest.raises(FrozenInstanceError):
        result.status = "failed"  # type: ignore[misc]


def test_module_has_no_io_execution_clock_or_publication_imports() -> None:
    tree = ast.parse(inspect.getsource(render_module))
    banned = {
        "os",
        "pathlib",
        "socket",
        "subprocess",
        "requests",
        "urllib",
        "time",
        "datetime",
        "github",
        "google",
        "boto3",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(banned)


def test_serializer_rejects_wrong_type_size_and_invalid_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(TypeError):
        serialize_advisory_render_result({})  # type: ignore[arg-type]
    result = render_advisory_evidence(_advisory())
    with pytest.raises(ValueError, match="status"):
        serialize_advisory_render_result(replace(result, status="unknown"))
    monkeypatch.setattr(render_module, "MAX_RENDER_SERIALIZED_BYTES", 1)
    with pytest.raises(ValueError, match="size limit"):
        serialize_advisory_render_result(result)


def test_shadow_observation_is_in_memory_ordered_and_distinct() -> None:
    results = (
        _advisory("passed", invocation_id="run-574-passed"),
        _advisory("failed", invocation_id="run-574-failed"),
        _advisory("stale", invocation_id="run-574-stale"),
    )
    observed = observe_advisory_evidence_shadow(results)
    assert tuple(item.status for item in observed) == ("passed", "failed", "stale")
    assert len({item.advisory_result_id for item in observed}) == 3
    assert all(isinstance(item, AdvisoryRenderResult) for item in observed)
