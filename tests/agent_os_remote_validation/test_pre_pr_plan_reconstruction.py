from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from scripts.agent_os_remote_validation.models import (
    PrePrValidationPlan,
    PrePrValidationSubject,
)
from scripts.agent_os_remote_validation.selector import (
    compute_command_set_digest,
    deserialize_pre_pr_validation_plan,
    pre_pr_validation_plan_id,
    serialize_pre_pr_validation_plan,
)

COMMANDS = (
    "python -m pytest tests/agent_os_issue_acceptance",
    "python -m pytest tests/agent_os_remote_validation",
)


def _subject() -> PrePrValidationSubject:
    return PrePrValidationSubject(
        invocation_id="invocation:1068:0001",
        base_sha="a" * 40,
        branch="agent/1068-pre-pr-validation-plan-reconstruction",
        expected_source_sha="b" * 40,
        tested_sha="b" * 40,
        allowed_files=(
            "scripts/agent_os_remote_validation/selector.py",
            "tests/agent_os_remote_validation/test_pre_pr_plan_reconstruction.py",
        ),
        forbidden_paths=("production",),
        required_command_identities=COMMANDS,
        approval_id="approval:1068:0001",
        approval_revision=1,
        projection_id="projection:1068:0001",
        implementation_contract_fingerprint="c" * 64,
        candidate_bound=True,
        issue_number=1068,
    )


def _plan() -> PrePrValidationPlan:
    subject = _subject()
    return PrePrValidationPlan(
        selector_version="1.0.0",
        subject=subject,
        commands=COMMANDS,
        command_set_digest=compute_command_set_digest("1.0.0", COMMANDS),
        reason_codes=("profile.focused-union",),
    )


def _payload() -> dict[str, object]:
    return serialize_pre_pr_validation_plan(_plan())


def test_pre_pr_plan_reconstruction_round_trip_and_identity_are_stable() -> None:
    original = _plan()
    payload = serialize_pre_pr_validation_plan(original)
    reconstructed = deserialize_pre_pr_validation_plan(payload)

    assert reconstructed == original
    assert serialize_pre_pr_validation_plan(reconstructed) == payload
    assert pre_pr_validation_plan_id(reconstructed) == pre_pr_validation_plan_id(original)


@pytest.mark.parametrize("field", ["schema_name", "subject", "commands", "reason_codes"])
def test_pre_pr_plan_reconstruction_rejects_missing_fields(field: str) -> None:
    payload = _payload()
    del payload[field]
    with pytest.raises(ValueError, match="payload fields drift"):
        deserialize_pre_pr_validation_plan(payload)


def test_pre_pr_plan_reconstruction_rejects_unknown_fields() -> None:
    payload = _payload()
    payload["unexpected"] = "value"
    with pytest.raises(ValueError, match="payload fields drift"):
        deserialize_pre_pr_validation_plan(payload)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("schema_name", "other-schema", "schema_name"),
        ("schema_version", "2.0", "schema_version"),
        ("selector_version", "2.0.0", "selector version is unsupported"),
        ("profile", "aggregate", "profile"),
    ],
)
def test_pre_pr_plan_reconstruction_rejects_unsupported_contract_values(
    field: str, value: object, match: str
) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises((TypeError, ValueError), match=match):
        deserialize_pre_pr_validation_plan(payload)


@pytest.mark.parametrize("field", ["commands", "reason_codes"])
def test_pre_pr_plan_reconstruction_requires_array_shapes(field: str) -> None:
    payload = _payload()
    payload[field] = tuple(payload[field])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="exact array"):
        deserialize_pre_pr_validation_plan(payload)


@pytest.mark.parametrize(
    "field",
    ["per_command_timeout_seconds", "total_validation_timeout_seconds"],
)
def test_pre_pr_plan_reconstruction_rejects_bool_for_integer(field: str) -> None:
    payload = _payload()
    payload[field] = True
    with pytest.raises(TypeError):
        deserialize_pre_pr_validation_plan(payload)


def test_pre_pr_plan_reconstruction_rejects_subject_identity_drift() -> None:
    payload = _payload()
    payload["subject_id"] = "pre-pr-validation-subject:" + "0" * 64
    with pytest.raises(ValueError, match="subject identity drift"):
        deserialize_pre_pr_validation_plan(payload)


def test_pre_pr_plan_reconstruction_rejects_nested_subject_drift() -> None:
    payload = _payload()
    subject = deepcopy(payload["subject"])
    assert isinstance(subject, dict)
    subject["tested_sha"] = "not-a-sha"
    payload["subject"] = subject
    with pytest.raises(ValueError):
        deserialize_pre_pr_validation_plan(payload)


def test_pre_pr_plan_reconstruction_rejects_command_digest_and_order_drift() -> None:
    digest_drift = _payload()
    digest_drift["command_set_digest"] = "0" * 64
    with pytest.raises(ValueError, match="command digest drift"):
        deserialize_pre_pr_validation_plan(digest_drift)

    order_drift = _payload()
    order_drift["commands"] = list(reversed(order_drift["commands"]))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="ordered command identities"):
        deserialize_pre_pr_validation_plan(order_drift)


def test_pre_pr_plan_reconstruction_rejects_reason_vocabulary_drift() -> None:
    payload = _payload()
    payload["reason_codes"] = ["rule.ambiguous"]
    with pytest.raises(ValueError, match="reason code drift"):
        deserialize_pre_pr_validation_plan(payload)


@pytest.mark.parametrize(
    "field",
    [
        "remote_build_required",
        "execution_authorized",
        "merge_authorized",
        "side_effects_performed",
    ],
)
def test_pre_pr_plan_reconstruction_rejects_authority_drift(field: str) -> None:
    payload = _payload()
    payload[field] = True
    with pytest.raises(ValueError, match="non-authority drift"):
        deserialize_pre_pr_validation_plan(payload)


def test_pre_pr_plan_reconstruction_performs_no_file_io(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _payload()

    def fail_read(*args: object, **kwargs: object) -> str:
        raise AssertionError("reconstruction attempted file I/O")

    monkeypatch.setattr(Path, "read_text", fail_read)
    reconstructed = deserialize_pre_pr_validation_plan(payload)
    assert serialize_pre_pr_validation_plan(reconstructed) == payload
