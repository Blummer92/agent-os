from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.agent_os_execution_capabilities import RepositoryIdentity
from scripts.agent_os_remote_validation import ValidationPlan, compute_command_set_digest
from agent_os_execution_service import (
    COMMAND_PLAN_SCHEMA_VERSION,
    COMMAND_REGISTRY_VERSION,
    CommandOperation,
    EvidenceVisibilityPolicy,
    ExecutionServiceCapability,
    ExecutionServiceInvalidationCondition,
    ExecutionServiceRequest,
    build_validation_command_plan,
    serialize_validation_command_plan,
    validation_command_plan_id,
)

A = "a" * 40
B = "b" * 40
EVALUATED_AT = "2026-07-27T03:30:00Z"


def request(**overrides: object) -> ExecutionServiceRequest:
    values: dict[str, object] = {
        "schema_version": "1.0",
        "request_id": "wsc6b2-001",
        "request_revision": 1,
        "created_at": "2026-07-27T03:00:00Z",
        "expires_at": "2026-07-27T04:00:00Z",
        "repository_identity": RepositoryIdentity(
            host="github.com",
            owner="blummer92",
            repository="agent-os",
            repository_id=123,
            default_branch="main",
        ),
        "issue_or_handoff_identity": "issue:677",
        "canonical_owner": "integration-manager",
        "requesting_actor": "github-service-agent",
        "capability": ExecutionServiceCapability.INSPECT_REPOSITORY,
        "base_branch": "main",
        "base_sha": A,
        "requested_ref": "agent/677-immutable-validation-command-planning",
        "expected_sha": B,
        "allowed_paths": ("08_Tooling/agent-os-execution-service",),
        "forbidden_paths": ("secrets",),
        "inspected_file_count_limit": 8,
        "inspected_byte_limit": 100_000,
        "evidence_visibility_policy": EvidenceVisibilityPolicy.PUBLIC_SUMMARY_ONLY,
        "invalidation_conditions": tuple(
            sorted(ExecutionServiceInvalidationCondition, key=lambda item: item.value)
        ),
    }
    values.update(overrides)
    return ExecutionServiceRequest(**values)  # type: ignore[arg-type]


def plan(
    *,
    profile: str = "focused",
    commands: tuple[str, ...] = (
        "python -m pytest tests/test_curriculum_pipeline_boundaries.py",
    ),
    reason_codes: tuple[str, ...] = ("profile.focused-package",),
) -> ValidationPlan:
    return ValidationPlan(
        selector_version="1.0.0",
        repository="blummer92/agent-os",
        pull_request=680,
        base_sha=A,
        head_sha=B,
        profile=profile,  # type: ignore[arg-type]
        commands=commands,
        command_set_digest=compute_command_set_digest("1.0.0", commands),
        reason_codes=reason_codes,
        remote_build_required=profile in {"focused", "aggregate"},
    )


def test_focused_plan_maps_to_exact_immutable_argv() -> None:
    value = build_validation_command_plan(request(), plan(), evaluated_at=EVALUATED_AT)
    assert value.schema_version == COMMAND_PLAN_SCHEMA_VERSION
    assert value.registry_version == COMMAND_REGISTRY_VERSION
    assert value.entries[0].operation is CommandOperation.VALIDATION_FOCUSED
    assert value.entries[0].argv == (
        "python",
        "-m",
        "pytest",
        "tests/test_curriculum_pipeline_boundaries.py",
    )
    assert value.execution_authorized is False
    assert value.merge_authorized is False
    assert value.side_effects_performed is False


def test_static_plan_contains_no_executable_entry() -> None:
    static = plan(
        profile="static",
        commands=(),
        reason_codes=("profile.documentation-static",),
    )
    value = build_validation_command_plan(request(), static, evaluated_at=EVALUATED_AT)
    assert value.entries == ()
    assert value.profile == "static"


def test_multi_command_order_and_identity_are_deterministic() -> None:
    commands = (
        "python -m pytest tests/test_teacher_modeling_workflows.py",
        "python -m pytest tests/test_curriculum_language_system.py",
    )
    first = build_validation_command_plan(
        request(),
        plan(profile="focused", commands=commands, reason_codes=("profile.focused-union",)),
        evaluated_at=EVALUATED_AT,
    )
    second = build_validation_command_plan(
        request(),
        plan(
            profile="focused",
            commands=tuple(reversed(commands)),
            reason_codes=("profile.focused-union",),
        ),
        evaluated_at=EVALUATED_AT,
    )
    assert tuple(entry.argv for entry in first.entries) == tuple(
        sorted(entry.argv for entry in first.entries)
    )
    assert validation_command_plan_id(first) != validation_command_plan_id(second)
    assert validation_command_plan_id(first) == validation_command_plan_id(first)


def test_unknown_command_and_manual_review_fail_closed() -> None:
    unknown = "python -m pytest tests/not-allowlisted.py"
    with pytest.raises(ValueError, match="not allowlisted"):
        build_validation_command_plan(
            request(),
            plan(commands=(unknown,)),
            evaluated_at=EVALUATED_AT,
        )
    manual = ValidationPlan(
        selector_version="1.0.0",
        repository="blummer92/agent-os",
        pull_request=680,
        base_sha="",
        head_sha="",
        profile="manual-review",
        commands=(),
        command_set_digest="unavailable",
        reason_codes=("rule.ambiguous",),
        remote_build_required=False,
    )
    with pytest.raises(ValueError, match="manual-review"):
        build_validation_command_plan(request(), manual, evaluated_at=EVALUATED_AT)


def test_repository_sha_and_request_time_must_match() -> None:
    with pytest.raises(ValueError, match="repository identity mismatch"):
        build_validation_command_plan(
            request(), replace(plan(), repository="other/repo"), evaluated_at=EVALUATED_AT
        )
    with pytest.raises(ValueError, match="expected SHA"):
        build_validation_command_plan(
            request(expected_sha=A), plan(), evaluated_at=EVALUATED_AT
        )
    with pytest.raises(ValueError, match="invalid execution service request"):
        build_validation_command_plan(
            request(), plan(), evaluated_at="2026-07-27T04:00:00Z"
        )


def test_serialization_is_bounded_public_and_immutable() -> None:
    value = build_validation_command_plan(request(), plan(), evaluated_at=EVALUATED_AT)
    payload = serialize_validation_command_plan(value)
    assert payload["entries"] == [
        {
            "operation": "validation.focused",
            "argv": [
                "python",
                "-m",
                "pytest",
                "tests/test_curriculum_pipeline_boundaries.py",
            ],
        }
    ]
    assert payload["execution_authorized"] is False
    assert payload["merge_authorized"] is False
    assert payload["side_effects_performed"] is False
    with pytest.raises(FrozenInstanceError):
        value.profile = "aggregate"  # type: ignore[misc]
