from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from agent_os_execution_service.command_planning import (
    reconstruct_validation_command_plan,
    serialize_validation_command_plan,
    validation_command_plan_id,
)


def canonical_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "registry_version": "1.0",
        "repository": "Blummer92/agent-os",
        "issue_or_handoff_identity": "issue:726",
        "requested_ref": "agent/723-pre-pr-validation-planning",
        "expected_sha": "d" * 40,
        "request_revision": 1,
        "request_fingerprint": "e" * 64,
        "validation_plan_id": "pre-pr-validation-plan:" + "f" * 64,
        "validation_plan_schema_version": "1.0",
        "selector_version": "1.0.0",
        "profile": "focused",
        "command_set_digest": "a" * 64,
        "entries": [
            {
                "operation": "validation.focused",
                "argv": [
                    "python",
                    "-m",
                    "pytest",
                    "08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py",
                ],
            }
        ],
        "execution_authorized": False,
        "merge_authorized": False,
        "side_effects_performed": False,
    }


def test_canonical_round_trip_and_identity_are_stable() -> None:
    payload = canonical_payload()
    plan = reconstruct_validation_command_plan(payload)
    assert serialize_validation_command_plan(plan) == payload
    assert validation_command_plan_id(plan).startswith("command-plan:")
    assert validation_command_plan_id(plan) == validation_command_plan_id(plan)


@pytest.mark.parametrize("field", list(canonical_payload()))
def test_missing_field_fails_closed(field: str) -> None:
    payload = canonical_payload()
    del payload[field]
    with pytest.raises(ValueError, match="fields"):
        reconstruct_validation_command_plan(payload)


def test_unknown_field_fails_closed() -> None:
    payload = canonical_payload()
    payload["unexpected"] = "value"
    with pytest.raises(ValueError, match="fields"):
        reconstruct_validation_command_plan(payload)


def test_bool_request_revision_is_rejected() -> None:
    payload = canonical_payload()
    payload["request_revision"] = True
    with pytest.raises(TypeError, match="exact int"):
        reconstruct_validation_command_plan(payload)


def test_entry_and_argv_require_array_shapes() -> None:
    payload = canonical_payload()
    payload["entries"] = tuple(payload["entries"])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="entries"):
        reconstruct_validation_command_plan(payload)

    payload = canonical_payload()
    entry = payload["entries"][0]  # type: ignore[index]
    entry["argv"] = tuple(entry["argv"])  # type: ignore[index]
    with pytest.raises(TypeError, match="argv"):
        reconstruct_validation_command_plan(payload)


def test_malformed_operation_and_entry_shape_fail_closed() -> None:
    payload = canonical_payload()
    payload["entries"][0]["operation"] = "validation.unknown"  # type: ignore[index]
    with pytest.raises(ValueError, match="unsupported command operation"):
        reconstruct_validation_command_plan(payload)

    payload = canonical_payload()
    payload["entries"][0]["extra"] = True  # type: ignore[index]
    with pytest.raises(ValueError, match="entry fields"):
        reconstruct_validation_command_plan(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "2.0"),
        ("registry_version", "2.0"),
        ("validation_plan_schema_version", "2.0"),
        ("profile", "aggregate"),
    ],
)
def test_semantic_validator_remains_authoritative(field: str, value: object) -> None:
    payload = canonical_payload()
    payload[field] = value
    with pytest.raises(ValueError, match="invalid validation command plan"):
        reconstruct_validation_command_plan(payload)


def test_unregistered_duplicate_and_authority_drift_fail_closed() -> None:
    payload = canonical_payload()
    payload["entries"][0]["argv"] = ["python", "-m", "pytest", "not-allowed.py"]  # type: ignore[index]
    with pytest.raises(ValueError, match="argv-not-registered"):
        reconstruct_validation_command_plan(payload)

    payload = canonical_payload()
    payload["entries"].append(dict(payload["entries"][0]))  # type: ignore[union-attr,index]
    with pytest.raises(ValueError, match="duplicate-argv"):
        reconstruct_validation_command_plan(payload)

    for field in ("execution_authorized", "merge_authorized", "side_effects_performed"):
        payload = canonical_payload()
        payload[field] = True
        with pytest.raises(ValueError, match="must remain false"):
            reconstruct_validation_command_plan(payload)
