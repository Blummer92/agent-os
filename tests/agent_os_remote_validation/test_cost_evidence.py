from __future__ import annotations

import ast
import inspect
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from scripts.agent_os_remote_validation import cost_evidence as evidence_module
from scripts.agent_os_remote_validation.cost_evidence import (
    MAX_COMPUTE_RECORDS,
    MAX_COMPUTE_SERIALIZED_BYTES,
    ComputeEvidenceSummary,
    SuppliedComputeRecord,
    build_compute_evidence_summary,
    compute_evidence_summary_id,
    serialize_compute_evidence_summary,
)
from scripts.agent_os_remote_validation.dispatch_guard import (
    DispatchDecision,
    validation_dispatch_identity,
)
from scripts.agent_os_remote_validation.models import ValidationPlan
from scripts.agent_os_remote_validation.selector import (
    compute_command_set_digest,
    validation_plan_id,
)

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
REPOSITORY = "Blummer92/agent-os"
PR = 370


def _plan(profile: str = "focused", **overrides: object) -> ValidationPlan:
    commands = {
        "static": (),
        "focused": ("python -m pytest tests/agent_os_remote_validation",),
        "aggregate": ("python -m pytest",),
        "manual-review": (),
    }[profile]
    values = {
        "selector_version": "1.0.0",
        "repository": REPOSITORY,
        "pull_request": PR,
        "base_sha": BASE_SHA,
        "head_sha": HEAD_SHA,
        "profile": profile,
        "commands": commands,
        "command_set_digest": (
            "unavailable"
            if profile == "manual-review"
            else compute_command_set_digest("1.0.0", commands)
        ),
        "reason_codes": {
            "static": ("profile.documentation-static",),
            "focused": ("profile.focused-package",),
            "aggregate": ("profile.aggregate-configuration",),
            "manual-review": ("rule.ambiguous",),
        }[profile],
        "remote_build_required": profile in {"focused", "aggregate"},
    }
    values.update(overrides)
    return ValidationPlan(**values)


def _decision(
    plan: ValidationPlan,
    status: str,
    *,
    retry: bool = False,
    marker: str = "one",
) -> DispatchDecision:
    launch = status == "launch-eligible"
    reasons = {
        "launch-eligible": (
            "retry.transient-once" if retry else "dispatch.no-prior-exact-result",
        ),
        "reused": ("terminal.exact-success",),
        "duplicate-no-op": ("active.exact-duplicate",),
        "stale-skipped": ("head.stale",),
        "supersede-required": ("active.different-identity",),
        "manual-review": ("retry.limit-reached",),
    }[status]
    preliminary = DispatchDecision(
        schema_name="agent-os-validation-dispatch-decision",
        schema_version="1.0",
        status=status,
        decision_id="",
        dispatch_identity=validation_dispatch_identity(plan),
        repository=plan.repository,
        pull_request=plan.pull_request,
        head_sha=plan.head_sha,
        profile=plan.profile,
        selector_version=plan.selector_version,
        command_set_digest=plan.command_set_digest,
        plan_id=validation_plan_id(plan),
        launch_recommended=launch,
        retry_recommended=retry,
        retry_attempt=1 if retry else None,
        matched_record_ids=(marker,) if status != "launch-eligible" or retry else (),
        reason_codes=reasons,
    )
    from scripts.agent_os_remote_validation import dispatch_guard as guard_module

    decision_id = "validation-dispatch-decision:" + guard_module._semantic_digest(
        "agent-os-validation-dispatch-decision:v1",
        guard_module._decision_payload(preliminary),
    )
    return replace(preliminary, decision_id=decision_id)


def _record(
    plan: ValidationPlan,
    status: str,
    *,
    record_id: str = "record-1",
    triggered: bool = False,
    build_id: str = "unavailable",
    terminal_status: str = "unavailable",
    machine_type: str = "unavailable",
    elapsed_seconds: int | None = None,
    retry: bool = False,
    marker: str = "one",
) -> SuppliedComputeRecord:
    return SuppliedComputeRecord(
        record_id=record_id,
        dispatch_decision=_decision(plan, status, retry=retry, marker=marker),
        remote_build_triggered=triggered,
        build_id=build_id,
        terminal_status=terminal_status,
        machine_type=machine_type,
        elapsed_seconds=elapsed_seconds,
    )


def _summary(
    plan: ValidationPlan | None = None,
    records: object = (),
) -> ComputeEvidenceSummary:
    return build_compute_evidence_summary(plan or _plan(), records)


def test_static_evidence_reports_zero_builds() -> None:
    plan = _plan("static")
    summary = _summary(plan, (_record(plan, "duplicate-no-op"),))
    assert summary.status == "within-policy"
    assert summary.remote_builds_triggered == 0
    assert summary.aggregate_runs_for_exact_sha == 0
    assert summary.machine_type == "unavailable"
    assert summary.elapsed_seconds == "unavailable"


def test_one_focused_launch_reports_one_build() -> None:
    plan = _plan()
    summary = _summary(
        plan,
        (
            _record(
                plan,
                "launch-eligible",
                triggered=True,
                build_id="build-1",
                terminal_status="succeeded",
                machine_type="e2-standard-2",
                elapsed_seconds=42,
            ),
        ),
    )
    assert summary.status == "within-policy"
    assert summary.remote_builds_triggered == 1
    assert summary.build_ids == ("build-1",)
    assert summary.terminal_statuses == ("succeeded",)
    assert summary.machine_type == "e2-standard-2"
    assert summary.elapsed_seconds == 42


@pytest.mark.parametrize("status", ["reused", "duplicate-no-op"])
def test_reuse_and_duplicate_no_op_avoid_builds(status: str) -> None:
    plan = _plan()
    summary = _summary(plan, (_record(plan, status),))
    assert summary.remote_builds_triggered == 0
    assert summary.duplicate_builds_avoided == 1
    assert summary.stale_proposals_skipped == 0


def test_stale_skip_increments_skipped_only() -> None:
    plan = _plan()
    summary = _summary(plan, (_record(plan, "stale-skipped"),))
    assert summary.remote_builds_triggered == 0
    assert summary.duplicate_builds_avoided == 0
    assert summary.stale_proposals_skipped == 1


def test_superseded_proposal_is_warning_not_current_success() -> None:
    plan = _plan()
    summary = _summary(plan, (_record(plan, "supersede-required"),))
    assert summary.status == "warning"
    assert summary.remote_builds_triggered == 0
    assert summary.superseded_proposals_identified == 1
    assert "dispatch.supersede-required" in summary.reason_codes


def test_multiple_aggregate_runs_for_exact_sha_warn() -> None:
    plan = _plan("aggregate")
    records = tuple(
        _record(
            plan,
            "launch-eligible",
            record_id=f"record-{index}",
            marker=f"marker-{index}",
            triggered=True,
            build_id=f"build-{index}",
            terminal_status="succeeded",
            machine_type="e2-standard-2",
            elapsed_seconds=10,
        )
        for index in (1, 2)
    )
    summary = _summary(plan, records)
    assert summary.status == "warning"
    assert summary.aggregate_runs_for_exact_sha == 2
    assert "policy.aggregate-repeat" in summary.reason_codes


def test_retry_over_policy_is_manual_review() -> None:
    plan = _plan()
    records = tuple(
        _record(
            plan,
            "launch-eligible",
            record_id=f"retry-{index}",
            marker=f"marker-{index}",
            triggered=True,
            retry=True,
            build_id=f"build-{index}",
            terminal_status="infrastructure-error",
            machine_type="e2-standard-2",
            elapsed_seconds=5,
        )
        for index in (1, 2)
    )
    summary = _summary(plan, records)
    assert summary.status == "manual-review"
    assert summary.retry_count == 2
    assert "policy.retry-limit" in summary.reason_codes


def test_unavailable_build_metadata_remains_explicit() -> None:
    plan = _plan()
    summary = _summary(
        plan,
        (_record(plan, "launch-eligible", triggered=True),),
    )
    assert summary.status == "warning"
    assert summary.build_ids == ("unavailable",)
    assert summary.terminal_statuses == ("unavailable",)
    assert summary.machine_type == "unavailable"
    assert summary.elapsed_seconds == "unavailable"
    assert "build.metadata-unavailable" in summary.reason_codes


def test_false_trigger_with_new_build_id_fails_closed() -> None:
    plan = _plan()
    summary = _summary(
        plan,
        (_record(plan, "reused", build_id="impossible-build"),),
    )
    assert summary.status == "manual-review"
    assert summary.remote_builds_triggered == 0
    assert summary.record_ids == ()
    assert "records.no-build-metadata-contradiction" in summary.reason_codes


def test_static_profile_with_triggered_build_fails_closed() -> None:
    plan = _plan("static")
    summary = _summary(
        plan,
        (
            _record(
                plan,
                "launch-eligible",
                triggered=True,
                build_id="build-1",
                terminal_status="succeeded",
                machine_type="e2-standard-2",
                elapsed_seconds=1,
            ),
        ),
    )
    assert summary.status == "manual-review"
    assert "policy.static-build-triggered" in summary.reason_codes


class _HostileEquality:
    def __eq__(self, other: object) -> bool:
        raise AssertionError("caller-controlled equality executed")


def test_hostile_non_string_metadata_fails_closed_without_equality_dispatch() -> None:
    plan = _plan()
    record = replace(
        _record(plan, "reused"),
        build_id=_HostileEquality(),  # type: ignore[arg-type]
        machine_type=_HostileEquality(),  # type: ignore[arg-type]
    )
    summary = _summary(plan, (record,))
    assert summary.status == "manual-review"
    assert "records.build-id" in summary.reason_codes
    assert "records.machine-type" in summary.reason_codes


def test_duplicate_record_decision_and_build_ids_fail_closed() -> None:
    plan = _plan()
    record = _record(
        plan,
        "launch-eligible",
        triggered=True,
        build_id="build-1",
        terminal_status="succeeded",
        machine_type="e2-standard-2",
        elapsed_seconds=1,
    )
    summary = _summary(plan, (record, record))
    assert summary.status == "manual-review"
    assert summary.remote_builds_triggered == 0
    assert "records.duplicate-record-id" in summary.reason_codes
    assert "records.duplicate-build-id" in summary.reason_codes


@pytest.mark.parametrize(
    "other_plan",
    [
        _plan(repository="Other/agent-os"),
        _plan(pull_request=371),
        _plan(head_sha="c" * 40),
    ],
)
def test_mixed_repository_pr_or_head_fails_closed(
    other_plan: ValidationPlan,
) -> None:
    plan = _plan()
    summary = _summary(plan, (_record(other_plan, "reused"),))
    assert summary.status == "manual-review"
    assert summary.record_ids == ()
    assert "records.identity-mismatch" in summary.reason_codes


def test_oversized_collection_fails_closed() -> None:
    plan = _plan()
    records = tuple(
        _record(plan, "reused", record_id=f"record-{index}", marker=f"m-{index}")
        for index in range(MAX_COMPUTE_RECORDS + 1)
    )
    summary = _summary(plan, records)
    assert summary.status == "manual-review"
    assert summary.reason_codes == ("records.collection-limit",)


def test_input_order_does_not_change_output_or_semantic_id() -> None:
    plan = _plan()
    first = _record(plan, "reused", record_id="a", marker="a")
    second = _record(plan, "stale-skipped", record_id="b", marker="b")
    left = _summary(plan, (first, second))
    right = _summary(plan, (second, first))
    assert serialize_compute_evidence_summary(left) == serialize_compute_evidence_summary(
        right
    )
    assert compute_evidence_summary_id(left) == compute_evidence_summary_id(right)


def test_serialization_has_no_monetary_field_or_inferred_price() -> None:
    plan = _plan()
    serialized = serialize_compute_evidence_summary(
        _summary(plan, (_record(plan, "reused"),))
    )
    lowered = repr(serialized).lower()
    assert "price" not in lowered
    assert "dollar" not in lowered
    assert "currency" not in lowered
    assert "estimated_cost" not in lowered


def test_serialization_is_tamper_evident_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = _summary(_plan(), (_record(_plan(), "reused"),))
    assert compute_evidence_summary_id(summary) == summary.summary_id
    with pytest.raises(ValueError, match="summary ID mismatch"):
        serialize_compute_evidence_summary(
            replace(summary, summary_id="compute-evidence-summary:" + "0" * 64)
        )
    monkeypatch.setattr(evidence_module, "MAX_COMPUTE_SERIALIZED_BYTES", 1)
    with pytest.raises(ValueError, match="canonical size limit"):
        serialize_compute_evidence_summary(summary)


def test_models_are_frozen_and_secretish_invalid_input_is_not_echoed() -> None:
    summary = _summary(_plan(), (_record(_plan(), "reused"),))
    with pytest.raises(FrozenInstanceError):
        summary.status = "warning"  # type: ignore[misc]
    secret_record = replace(
        _record(_plan(), "reused"),
        record_id="token=do-not-echo",
    )
    invalid = _summary(_plan(), (secret_record,))
    assert "token=do-not-echo" not in repr(
        serialize_compute_evidence_summary(invalid)
    )


def test_non_authorization_and_no_side_effect_invariants_hold() -> None:
    summary = _summary(_plan(), (_record(_plan(), "reused"),))
    assert summary.authoritative is False
    assert summary.execution_authorized is False
    assert summary.merge_authorized is False
    assert summary.side_effects_performed is False


def test_module_has_no_external_io_execution_environment_or_clock_imports() -> None:
    tree = ast.parse(inspect.getsource(evidence_module))
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


def test_validation_report_names_public_schema_and_statuses() -> None:
    text = Path("VALIDATION_REPORT.md").read_text(encoding="utf-8")
    assert "agent-os-compute-evidence-summary" in text
    assert "within-policy" in text
    assert "warning" in text
    assert "manual-review" in text


def test_default_summary_fits_declared_size_limit() -> None:
    encoded = repr(
        serialize_compute_evidence_summary(
            _summary(_plan(), (_record(_plan(), "reused"),))
        )
    ).encode("utf-8")
    assert len(encoded) < MAX_COMPUTE_SERIALIZED_BYTES
