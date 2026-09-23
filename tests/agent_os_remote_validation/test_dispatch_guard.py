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


def _static_plan(**overrides: object) -> ValidationPlan:
    values = {
        "profile": "static",
        "commands": (),
        "command_set_digest": compute_command_set_digest("1.0.0", ()),
        "reason_codes": ("profile.documentation-static",),
        "remote_build_required": False,
    }
    values.update(overrides)
    return _plan(**values)


def _manual_plan(**overrides: object) -> ValidationPlan:
    values = {
        "profile": "manual-review",
        "commands": (),
        "command_set_digest": "unavailable",
        "reason_codes": ("rule.ambiguous",),
        "remote_build_required": False,
    }
    values.update(overrides)
    return _plan(**values)


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


def _record(
    plan: object,
    *,
    record_id: object = "run-1",
    attempt: object = 0,
    state: object = "succeeded",
    failure_class: object = "none",
) -> DispatchEvidence:
    return DispatchEvidence(
        record_id=record_id,  # type: ignore[arg-type]
        validation_plan=plan,  # type: ignore[arg-type]
        attempt=attempt,  # type: ignore[arg-type]
        state=state,  # type: ignore[arg-type]
        failure_class=failure_class,  # type: ignore[arg-type]
    )


def _evaluate(plan: object | None = None, evidence: object = (), **overrides: object):
    resolved = _plan() if plan is None else plan
    values = {"current_pr_head_sha": HEAD_SHA}
    values.update(overrides)
    return evaluate_dispatch_decision(resolved, evidence, **values)


def test_no_prior_result_is_launch_eligible_and_non_authorizing() -> None:
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


def test_every_dispatch_identity_component_prevents_reuse_when_changed() -> None:
    plan = _plan()
    changed_commands = (plan.commands[0] + " -q",)
    variants = (
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
    assert all(validation_dispatch_identity(item) != identity for item in variants)
    for index, variant in enumerate(variants):
        result = _evaluate(plan, (_record(variant, record_id=f"other-{index}"),))
        assert result.status == "launch-eligible"


def test_exact_active_identity_is_duplicate_no_op() -> None:
    plan = _plan()
    result = _evaluate(plan, (_record(plan, state="active"),))
    assert result.status == "duplicate-no-op"
    assert result.launch_recommended is False


@pytest.mark.parametrize("plan", [_plan(), _static_plan()])
def test_stale_head_is_skipped_before_launch_or_static_no_op(plan: ValidationPlan) -> None:
    result = _evaluate(plan, current_pr_head_sha=NEW_HEAD_SHA)
    assert result.status == "stale-skipped"
    assert result.launch_recommended is False


def test_manual_review_plan_remains_manual_review() -> None:
    result = _evaluate(_manual_plan(), current_pr_head_sha=NEW_HEAD_SHA)
    assert result.status == "manual-review"
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


@pytest.mark.parametrize(
    ("retry_state", "failure_class", "expected_status"),
    [
        ("active", "none", "duplicate-no-op"),
        ("succeeded", "none", "reused"),
        ("failed", "transient-infrastructure", "manual-review"),
    ],
)
def test_second_attempt_is_bounded(
    retry_state: str, failure_class: str, expected_status: str
) -> None:
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
                state=retry_state,
                failure_class=failure_class,
            ),
        ),
    )
    assert result.status == expected_status
    if retry_state == "failed":
        assert result.reason_codes == ("retry.limit-reached",)
    else:
        assert result.matched_record_ids == ("attempt-1",)


@pytest.mark.parametrize(
    "record",
    [
        _record(_plan(head_sha="bad")),
        _record(_plan(command_set_digest="bad")),
        _record(_plan(selector_version="v1")),
        _record(_plan(), attempt=2),
        _record(_plan(), state="unknown"),
        _record(_plan(), failure_class="unknown"),
        _record(_plan(), state=[]),
        _record(_plan(), failure_class={}),
        _record(_plan(), record_id=[]),
    ],
)
def test_malformed_record_fields_fail_closed_without_raising(
    record: DispatchEvidence,
) -> None:
    result = _evaluate(evidence=(record,))
    assert result.status == "manual-review"
    assert "evidence.record-invalid" in result.reason_codes


@pytest.mark.parametrize(
    "plan",
    [
        _plan(profile=[]),
        _plan(commands=([],)),
        _plan(reason_codes=([],)),
        _plan(command_set_digest=[]),
        _plan(repository=[]),
        _plan(pull_request=[]),
    ],
)
def test_unhashable_or_malformed_plan_fields_fail_closed_without_raising(
    plan: ValidationPlan,
) -> None:
    result = _evaluate(plan)
    assert result.status == "manual-review"
    assert "plan.invalid" in result.reason_codes
    assert "plan-detail.plan.malformed-runtime" in result.reason_codes


def test_duplicate_record_and_attempt_evidence_fail_closed() -> None:
    plan = _plan()
    record = _record(plan)
    result = _evaluate(plan, (record, record))
    assert result.status == "manual-review"
    assert "evidence.duplicate-record-id" in result.reason_codes
    assert "evidence.duplicate-attempt" in result.reason_codes


def test_retry_after_non_retryable_failure_is_contradictory() -> None:
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


def test_invalid_collection_current_head_and_bounds_fail_closed() -> None:
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


def test_static_plan_is_zero_build_no_op() -> None:
    result = _evaluate(_static_plan())
    assert result.status == "duplicate-no-op"
    assert result.launch_recommended is False


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


# --- dispatch_identity independent verification (#804) -------------------------


def test_dispatch_identity_is_independently_verified_from_its_source_fields() -> None:
    plan = _plan()
    result = _evaluate(plan)
    assert result.dispatch_identity == validation_dispatch_identity(plan)
    assert serialize_dispatch_decision(result)["dispatch_identity"] == (
        validation_dispatch_identity(plan)
    )


def test_changing_dispatch_identity_and_recomputing_decision_id_still_fails() -> None:
    """A self-consistent forged pair -- new dispatch_identity, decision_id
    recomputed to match it -- must still fail, because dispatch_identity no
    longer agrees with the six declared source fields it is derived from.
    """
    plan = _plan()
    result = _evaluate(plan)
    forged_identity = validation_dispatch_identity(replace(plan, head_sha="c" * 40))
    assert forged_identity != result.dispatch_identity
    forged = replace(result, dispatch_identity=forged_identity)
    forged_payload = guard_module._decision_payload(forged)
    forged_decision_id = "validation-dispatch-decision:" + guard_module._semantic_digest(
        "agent-os-validation-dispatch-decision:v1", forged_payload
    )
    forged = replace(forged, decision_id=forged_decision_id)
    # The forged decision_id is internally self-consistent with the payload,
    # proving the attack only succeeds if dispatch_identity is trusted as-is.
    assert forged.decision_id == forged_decision_id
    with pytest.raises(ValueError, match="dispatch identity mismatch"):
        serialize_dispatch_decision(forged)
    with pytest.raises(ValueError, match="dispatch identity mismatch"):
        dispatch_decision_id(forged)


def test_dispatch_identity_source_field_tampering_fails_independently_of_decision_id() -> None:
    plan = _plan()
    result = _evaluate(plan)
    for field, value in (
        ("repository", "Other/agent-os"),
        ("head_sha", "c" * 40),
        ("profile", "aggregate"),
        ("selector_version", "9.9.9"),
        ("command_set_digest", "0" * 64),
        ("plan_id", "validation-plan:" + "0" * 64),
    ):
        tampered = replace(result, **{field: value})
        with pytest.raises(ValueError, match="dispatch identity mismatch"):
            serialize_dispatch_decision(tampered)


def test_dispatch_identity_partial_null_source_fields_fail_closed() -> None:
    result = _evaluate()
    tampered = replace(result, repository=None)
    with pytest.raises(ValueError, match="dispatch identity mismatch"):
        serialize_dispatch_decision(tampered)


def test_manual_review_decision_with_no_plan_has_no_dispatch_identity() -> None:
    result = _evaluate(plan={"bad": True})
    assert result.status == "manual-review"
    assert result.dispatch_identity is None
    assert serialize_dispatch_decision(result)["dispatch_identity"] is None
