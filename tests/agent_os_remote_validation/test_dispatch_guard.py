from __future__ import annotations

import ast
import inspect
from dataclasses import FrozenInstanceError, replace

import pytest

from scripts.agent_os_remote_validation import (
    MAX_DISPATCH_RECORDS,
    MAX_DISPATCH_SERIALIZED_BYTES,
    DispatchEvidence,
    ValidationPlan,
    compute_command_set_digest,
    dispatch_decision_id,
    evaluate_dispatch_decision,
    serialize_dispatch_decision,
    validation_dispatch_identity,
)
from scripts.agent_os_remote_validation import dispatch_guard as guard_module

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
NEW_HEAD_SHA = "c" * 40
REPOSITORY = "Blummer92/agent-os"
PR = 369


def _plan(**overrides: object) -> ValidationPlan:
    commands = ("python -m pytest tests/agent_os_remote_validation",)
    values = {
        "selector_version": "1.0.0",
        "repository": REPOSITORY,
        "pull_request": PR,
        "base_sha": BASE_SHA,
        "head_sha": HEAD_SHA,
        "profile": "focused",
        "commands": commands,
        "command_set_digest": compute_command_set_digest("1.0.0", commands),
        "reason_codes": ("profile.focused-package",),
        "remote_build_required": True,
    }
    values.update(overrides)
    return ValidationPlan(**values)


def _record(
    plan: ValidationPlan,
    *,
    record_id: str = "run-1",
    attempt: int = 0,
    state: str = "succeeded",
    failure_class: str = "none",
) -> DispatchEvidence:
    return DispatchEvidence(
        record_id=record_id,
        validation_plan=plan,
        attempt=attempt,
        state=state,
        failure_class=failure_class,
    )


def _evaluate(plan: object | None = None, evidence: object = (), **overrides: object):
    resolved = _plan() if plan is None else plan
    values = {"current_pr_head_sha": HEAD_SHA}
    values.update(overrides)
    return evaluate_dispatch_decision(resolved, evidence, **values)


def _aggregate_plan(**overrides: object) -> ValidationPlan:
    commands = ("python -m pytest",)
    values = {
        "profile": "aggregate",
        "commands": commands,
        "command_set_digest": compute_command_set_digest("1.0.0", commands),
        "reason_codes": ("profile.aggregate-configuration",),
    }
    values.update(overrides)
    return _plan(**values)


def test_no_prior_result_is_launch_eligible() -> None:
    result = _evaluate()
    assert result.status == "launch-eligible"
    assert result.launch_recommended is True
    assert result.retry_recommended is False
    assert result.execution_authorized is False
    assert result.side_effects_performed is False


def test_exact_success_is_reused() -> None:
    plan = _plan()
    result = _evaluate(plan, (_record(plan),))
    assert result.status == "reused"
    assert result.launch_recommended is False
    assert result.matched_record_ids == ("run-1",)


def test_each_identity_component_prevents_reuse_when_changed() -> None:
    plan = _plan()
    changed_commands = (plan.commands[0] + " -q",)
    same_scope_variants = (
        replace(plan, head_sha=NEW_HEAD_SHA),
        _aggregate_plan(),
        replace(
            plan,
            selector_version="1.0.1",
            command_set_digest=compute_command_set_digest("1.0.1", plan.commands),
        ),
        replace(
            plan,
            commands=changed_commands,
            command_set_digest=compute_command_set_digest(
                plan.selector_version, changed_commands
            ),
        ),
        replace(plan, base_sha="d" * 40),
    )
    identity = validation_dispatch_identity(plan)
    assert validation_dispatch_identity(
        replace(plan, repository="Other/agent-os")
    ) != identity
    assert all(
        validation_dispatch_identity(item) != identity for item in same_scope_variants
    )
    for index, variant in enumerate(same_scope_variants):
        result = _evaluate(plan, (_record(variant, record_id=f"other-{index}"),))
        assert result.status == "launch-eligible"


def test_exact_active_identity_is_duplicate_no_op() -> None:
    plan = _plan()
    result = _evaluate(plan, (_record(plan, state="active"),))
    assert result.status == "duplicate-no-op"
    assert result.launch_recommended is False


def test_stale_proposed_head_is_skipped() -> None:
    result = _evaluate(current_pr_head_sha=NEW_HEAD_SHA)
    assert result.status == "stale-skipped"
    assert result.launch_recommended is False


def test_one_different_active_identity_requires_supersession() -> None:
    plan = _plan()
    other = replace(plan, head_sha=NEW_HEAD_SHA)
    result = _evaluate(plan, (_record(other, state="active"),))
    assert result.status == "supersede-required"
    assert result.launch_recommended is False


def test_multiple_active_records_fail_to_manual_review() -> None:
    plan = _plan()
    other = replace(plan, head_sha=NEW_HEAD_SHA)
    result = _evaluate(
        plan,
        (
            _record(plan, record_id="run-1", state="active"),
            _record(other, record_id="run-2", state="active"),
        ),
    )
    assert result.status == "manual-review"
    assert result.reason_codes == ("active.multiple",)


@pytest.mark.parametrize(
    "failure_class",
    ["test", "configuration", "permission", "policy", "malformed-input"],
)
def test_non_retryable_failures_never_retry(failure_class: str) -> None:
    plan = _plan()
    result = _evaluate(
        plan,
        (_record(plan, state="failed", failure_class=failure_class),),
    )
    assert result.status == "manual-review"
    assert result.retry_recommended is False
    assert result.launch_recommended is False


def test_one_transient_retry_is_recommended() -> None:
    plan = _plan()
    result = _evaluate(
        plan,
        (
            _record(
                plan,
                state="failed",
                failure_class="transient-infrastructure",
            ),
        ),
    )
    assert result.status == "launch-eligible"
    assert result.retry_recommended is True
    assert result.retry_attempt == 1


def test_active_retry_is_a_duplicate_no_op() -> None:
    plan = _plan()
    result = _evaluate(
        plan,
        (
            _record(
                plan,
                record_id="attempt-0",
                state="failed",
                failure_class="transient-infrastructure",
            ),
            _record(
                plan,
                record_id="attempt-1",
                attempt=1,
                state="active",
            ),
        ),
    )
    assert result.status == "duplicate-no-op"
    assert result.matched_record_ids == ("attempt-1",)


def test_successful_retry_is_reused() -> None:
    plan = _plan()
    result = _evaluate(
        plan,
        (
            _record(
                plan,
                record_id="attempt-0",
                state="failed",
                failure_class="transient-infrastructure",
            ),
            _record(
                plan,
                record_id="attempt-1",
                attempt=1,
                state="succeeded",
            ),
        ),
    )
    assert result.status == "reused"
    assert result.matched_record_ids == ("attempt-1",)


def test_second_transient_retry_is_rejected() -> None:
    plan = _plan()
    result = _evaluate(
        plan,
        (
            _record(
                plan,
                record_id="attempt-0",
                state="failed",
                failure_class="transient-infrastructure",
            ),
            _record(
                plan,
                record_id="attempt-1",
                attempt=1,
                state="failed",
                failure_class="transient-infrastructure",
            ),
        ),
    )
    assert result.status == "manual-review"
    assert result.reason_codes == ("retry.limit-reached",)


@pytest.mark.parametrize(
    "record",
    [
        DispatchEvidence(
            record_id="run-1",
            validation_plan=_plan(head_sha="bad"),
            attempt=0,
            state="succeeded",
        ),
        DispatchEvidence(
            record_id="run-1",
            validation_plan=_plan(command_set_digest="bad"),
            attempt=0,
            state="succeeded",
        ),
        DispatchEvidence(
            record_id="run-1",
            validation_plan=_plan(selector_version="v1"),
            attempt=0,
            state="succeeded",
        ),
        DispatchEvidence(
            record_id="run-1",
            validation_plan=_plan(),
            attempt=2,
            state="succeeded",
        ),
        DispatchEvidence(
            record_id="run-1",
            validation_plan=_plan(),
            attempt=0,
            state="unknown",
        ),
        DispatchEvidence(
            record_id="run-1",
            validation_plan=_plan(),
            attempt=0,
            state="failed",
            failure_class="unknown",
        ),
    ],
)
def test_malformed_record_fields_fail_closed(record: DispatchEvidence) -> None:
    result = _evaluate(evidence=(record,))
    assert result.status == "manual-review"
    assert "evidence.record-invalid" in result.reason_codes


def test_duplicate_record_and_attempt_evidence_fail_closed() -> None:
    plan = _plan()
    record = _record(plan)
    result = _evaluate(plan, (record, record))
    assert result.status == "manual-review"
    assert "evidence.duplicate-record-id" in result.reason_codes
    assert "evidence.duplicate-attempt" in result.reason_codes


def test_retry_after_non_retryable_failure_is_rejected_as_contradictory() -> None:
    plan = _plan()
    result = _evaluate(
        plan,
        (
            _record(
                plan,
                record_id="attempt-0",
                state="failed",
                failure_class="test",
            ),
            _record(
                plan,
                record_id="attempt-1",
                attempt=1,
                state="active",
            ),
        ),
    )
    assert result.status == "manual-review"
    assert "evidence.retry-sequence" in result.reason_codes


def test_invalid_plan_collection_current_head_and_bounds_fail_closed() -> None:
    assert _evaluate(plan={"bad": True}).status == "manual-review"
    assert _evaluate(evidence=[]).status == "manual-review"
    assert _evaluate(current_pr_head_sha="bad").status == "manual-review"
    plan = _plan()
    oversized = tuple(
        _record(replace(plan, head_sha=f"{index:040x}"), record_id=f"run-{index}")
        for index in range(MAX_DISPATCH_RECORDS + 1)
    )
    assert _evaluate(plan, oversized).reason_codes == ("evidence.collection-limit",)


def test_cross_repository_or_pr_evidence_fails_closed() -> None:
    plan = _plan()
    assert _evaluate(
        plan,
        (_record(replace(plan, repository="Other/agent-os")),),
    ).status == "manual-review"
    assert _evaluate(
        plan,
        (_record(replace(plan, pull_request=370)),),
    ).status == "manual-review"


def test_static_plan_is_zero_build_no_op_and_manual_plan_needs_review() -> None:
    static = _plan(
        profile="static",
        commands=(),
        command_set_digest=compute_command_set_digest("1.0.0", ()),
        reason_codes=("profile.documentation-static",),
        remote_build_required=False,
    )
    static_result = _evaluate(static)
    assert static_result.status == "duplicate-no-op"
    assert static_result.launch_recommended is False
    manual = _plan(
        profile="manual-review",
        commands=(),
        command_set_digest="unavailable",
        reason_codes=("rule.ambiguous",),
        remote_build_required=False,
    )
    assert _evaluate(manual).status == "manual-review"


def test_input_order_does_not_change_result_or_semantic_id() -> None:
    plan = _plan()
    unrelated = replace(plan, head_sha=NEW_HEAD_SHA)
    first = _record(unrelated, record_id="old-success")
    second = _record(plan, record_id="current-success")
    left = _evaluate(plan, (first, second))
    right = _evaluate(plan, (second, first))
    assert serialize_dispatch_decision(left) == serialize_dispatch_decision(right)
    assert dispatch_decision_id(left) == dispatch_decision_id(right)


def test_serialization_is_deterministic_tamper_evident_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _evaluate()
    assert serialize_dispatch_decision(result) == serialize_dispatch_decision(_evaluate())
    assert dispatch_decision_id(result) == result.decision_id
    with pytest.raises(ValueError, match="decision ID mismatch"):
        serialize_dispatch_decision(
            replace(
                result,
                decision_id="validation-dispatch-decision:" + "0" * 64,
            )
        )
    monkeypatch.setattr(guard_module, "MAX_DISPATCH_SERIALIZED_BYTES", 1)
    with pytest.raises(ValueError, match="canonical size limit"):
        serialize_dispatch_decision(result)


def test_models_are_frozen_and_invalid_secretish_plan_is_not_echoed() -> None:
    result = _evaluate()
    with pytest.raises(FrozenInstanceError):
        result.status = "reused"  # type: ignore[misc]
    invalid = _evaluate(plan=_plan(repository="token=should-not-echo"))
    assert invalid.repository is None
    assert "token=should-not-echo" not in repr(serialize_dispatch_decision(invalid))


def test_module_has_no_external_io_execution_environment_or_clock_imports() -> None:
    tree = ast.parse(inspect.getsource(guard_module))
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
    encoded = repr(serialize_dispatch_decision(_evaluate())).encode("utf-8")
    assert len(encoded) < MAX_DISPATCH_SERIALIZED_BYTES
