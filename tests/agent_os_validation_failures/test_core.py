from __future__ import annotations

import ast
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from scripts.agent_os_validation_failures import (
    EvidenceValueState,
    ObservedFailureFact,
    ValidationFailureError,
    ValidationFailureSource,
    ValidationFailureStatus,
    ValidationMode,
    build_validation_failure_record,
    serialize_validation_failure_record,
    validation_failure_record_id,
)

SHA = "a" * 40
OTHER_SHA = "b" * 40
REPO = "Blummer92/agent-os"


def fact(**overrides: object) -> ObservedFailureFact:
    payload: dict[str, object] = {
        "repository": REPO,
        "tested_sha": SHA,
        "source": ValidationFailureSource.CLOUD_BUILD,
        "mode": ValidationMode.AGGREGATE,
        "source_record_id": "build-123",
        "run_identity": "build-123",
        "provider_identity": "cloud-build",
        "outcome": "failure",
        "return_code": 1,
        "failing_step": "pytest",
        "test_name": "tests/test_example.py::test_failure",
        "error_excerpt": "assert 1 == 2",
        "aggregate_pending": False,
        "source_complete": True,
    }
    payload.update(overrides)
    return ObservedFailureFact(**payload)  # type: ignore[arg-type]


def record(*facts: ObservedFailureFact, source: ValidationFailureSource = ValidationFailureSource.CLOUD_BUILD, mode: ValidationMode = ValidationMode.AGGREGATE):
    return build_validation_failure_record(
        repository=REPO,
        tested_sha=SHA,
        source=source,
        mode=mode,
        facts=facts or (fact(),),
    )


def test_cloud_build_terminal_failure_projects_actionable_record() -> None:
    result = record(fact())
    assert result.status is ValidationFailureStatus.ACTIONABLE_FAILURE
    assert result.reason_codes == ("actionable-failure-observed",)
    assert result.facts[0].return_code_state is EvidenceValueState.OBSERVED
    assert result.facts[0].failing_step_state is EvidenceValueState.OBSERVED
    assert result.execution_authorized is False
    assert result.merge_authorized is False
    assert result.repair_authorized is False
    assert result.side_effects_performed is False


def test_cloud_build_infrastructure_failure_stays_distinct() -> None:
    result = record(fact(outcome="internal-error", return_code=None, failing_step=None))
    assert result.status is ValidationFailureStatus.INFRASTRUCTURE_FAILURE
    assert "infrastructure-failure-observed" in result.reason_codes


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [("cancelled", ValidationFailureStatus.CANCELLED), ("timeout", ValidationFailureStatus.TIMEOUT)],
)
def test_cancellation_and_timeout_stay_distinct(outcome: str, expected: ValidationFailureStatus) -> None:
    result = record(fact(outcome=outcome, return_code=None))
    assert result.status is expected


def test_execution_composition_focused_failure_preserves_aggregate_pending() -> None:
    observed = fact(
        source=ValidationFailureSource.EXECUTION_COMPOSITION,
        mode=ValidationMode.FOCUSED,
        source_record_id="execution-composition:abc",
        run_identity="execution-composition:abc",
        provider_identity="workflow-scheduler",
        outcome="focused-fail",
        aggregate_pending=True,
        executed_commands=("pytest-focused",),
        skipped_commands=("aggregate",),
    )
    result = record(observed, source=ValidationFailureSource.EXECUTION_COMPOSITION, mode=ValidationMode.FOCUSED)
    assert result.status is ValidationFailureStatus.ACTIONABLE_FAILURE
    assert result.aggregate_pending is True


def test_aggregate_failure_cannot_claim_pending() -> None:
    observed = fact(outcome="aggregate-fail", aggregate_pending=True)
    result = record(observed)
    assert result.status is ValidationFailureStatus.MANUAL_REVIEW
    assert "aggregate-cannot-be-pending" in result.reason_codes


def test_missing_optional_evidence_is_explicitly_unavailable() -> None:
    observed = fact(return_code=None, failing_step=None, test_name=None, error_excerpt=None, timestamp=None, duration_seconds=None)
    result = record(observed)
    projected = result.facts[0]
    assert projected.return_code_state is EvidenceValueState.UNAVAILABLE
    assert projected.failing_step_state is EvidenceValueState.UNAVAILABLE
    assert projected.test_name_state is EvidenceValueState.UNAVAILABLE
    assert projected.excerpt_state is EvidenceValueState.UNAVAILABLE
    assert projected.timestamp_state is EvidenceValueState.UNAVAILABLE
    assert projected.duration_state is EvidenceValueState.UNAVAILABLE


def test_incomplete_source_overrides_actionable_classification() -> None:
    result = record(fact(source_complete=False))
    assert result.status is ValidationFailureStatus.INCOMPLETE
    assert "evidence-incomplete" in result.reason_codes


def test_stale_provenance_fails_closed_to_manual_review() -> None:
    result = record(fact(provenance_id="prov-1", provenance_state="stale"))
    assert result.status is ValidationFailureStatus.MANUAL_REVIEW
    assert "provenance-stale" in result.reason_codes


def test_mixed_repository_and_sha_fail_closed() -> None:
    result = record(fact(), fact(repository="Other/repo", tested_sha=OTHER_SHA, source_record_id="build-124", run_identity="build-123", command_identity="other"))
    assert result.status is ValidationFailureStatus.MANUAL_REVIEW
    assert "repository-mismatch" in result.reason_codes
    assert "tested-sha-mismatch" in result.reason_codes


def test_mixed_provider_and_run_identity_fail_closed() -> None:
    result = record(
        fact(source_record_id="a", run_identity="run-a", provider_identity="cloud-build", command_identity="a"),
        fact(source_record_id="b", run_identity="run-b", provider_identity="github-actions", command_identity="b"),
    )
    assert result.status is ValidationFailureStatus.MANUAL_REVIEW
    assert "provider-identity-mismatch" in result.reason_codes
    assert "run-identity-mismatch" in result.reason_codes


def test_multiple_independent_failures_require_manual_review() -> None:
    result = record(
        fact(source_record_id="run", run_identity="run", command_identity="pytest-a", failing_step="pytest-a"),
        fact(source_record_id="run", run_identity="run", command_identity="pytest-b", failing_step="pytest-b"),
    )
    assert result.status is ValidationFailureStatus.MANUAL_REVIEW
    assert "multiple-independent-failures" in result.reason_codes


def test_contradictory_return_code_requires_manual_review() -> None:
    result = record(fact(return_code=0))
    assert result.status is ValidationFailureStatus.MANUAL_REVIEW
    assert "contradictory-return-code" in result.reason_codes


def test_secret_like_text_is_redacted_and_never_serialized_raw() -> None:
    secret = "token=ghp_abcdefghijklmnopqrstuvwxyz123456"
    result = record(fact(error_excerpt=f"failure {secret}"))
    serialized = serialize_validation_failure_record(result)
    assert secret not in serialized
    assert "[REDACTED]" in serialized
    assert result.facts[0].redacted is True
    assert result.facts[0].excerpt_state is EvidenceValueState.REDACTED


def test_oversized_excerpt_is_truncated() -> None:
    result = record(fact(error_excerpt="x" * 20000))
    assert result.facts[0].output_truncated is True
    assert result.facts[0].excerpt_state is EvidenceValueState.TRUNCATED
    assert len((result.facts[0].error_excerpt or "").encode("utf-8")) <= 16384


def test_serialization_and_identity_are_deterministic_and_input_order_invariant() -> None:
    first = fact(source_record_id="run", run_identity="run", command_identity="a", failing_step="same")
    second = fact(source_record_id="run", run_identity="run", command_identity="a", failing_step="same", test_name="other")
    a = record(first, second)
    b = record(second, first)
    assert serialize_validation_failure_record(a) == serialize_validation_failure_record(b)
    assert validation_failure_record_id(a) == validation_failure_record_id(b)
    parsed = json.loads(serialize_validation_failure_record(a))
    assert parsed["schema_version"] == "1.0"
    assert validation_failure_record_id(a).startswith("validation-failure:")


def test_models_are_frozen() -> None:
    observed = fact()
    with pytest.raises(FrozenInstanceError):
        observed.outcome = "timeout"  # type: ignore[misc]
    result = record(observed)
    with pytest.raises(FrozenInstanceError):
        result.status = ValidationFailureStatus.TIMEOUT  # type: ignore[misc]


def test_nonfinite_duration_is_rejected() -> None:
    with pytest.raises(ValidationFailureError):
        fact(duration_seconds=float("nan"))


def test_unknown_outcome_is_rejected() -> None:
    with pytest.raises(ValidationFailureError):
        fact(outcome="maybe-failed")


def test_unbounded_collection_is_rejected() -> None:
    with pytest.raises(ValidationFailureError):
        fact(executed_commands=tuple(f"cmd-{index}" for index in range(129)))


def test_focused_actionable_failure_requires_aggregate_pending() -> None:
    observed = fact(source=ValidationFailureSource.EXECUTION_COMPOSITION, mode=ValidationMode.FOCUSED, outcome="focused-fail", aggregate_pending=False)
    result = record(observed, source=ValidationFailureSource.EXECUTION_COMPOSITION, mode=ValidationMode.FOCUSED)
    assert result.status is ValidationFailureStatus.MANUAL_REVIEW
    assert "focused-aggregate-pending-missing" in result.reason_codes


def test_raw_success_is_not_misclassified_as_failure() -> None:
    result = record(fact(outcome="success", return_code=0, failing_step=None, test_name=None, error_excerpt=None))
    assert result.status is ValidationFailureStatus.MANUAL_REVIEW


def test_core_has_no_network_process_environment_clock_or_io_imports() -> None:
    source = Path(__file__).parents[2] / "scripts" / "agent_os_validation_failures" / "core.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    blocked = {"asyncio", "http", "requests", "socket", "subprocess", "urllib", "os", "pathlib", "time", "datetime", "tempfile", "shutil"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(blocked)
