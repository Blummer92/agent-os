from dataclasses import FrozenInstanceError
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
FOCUSED_COMMAND = "python -m pytest tests/test_curriculum_pipeline_boundaries.py"


def request(*, expected_sha: str = B) -> ExecutionServiceRequest:
    return ExecutionServiceRequest(
        schema_version="1.0",
        request_id="wsc6b2-001",
        request_revision=1,
        created_at="2026-07-27T03:00:00Z",
        expires_at="2026-07-27T04:00:00Z",
        repository_identity=RepositoryIdentity(
            host="github.com",
            owner="Blummer92",
            repository="agent-os",
            repository_id=123,
            default_branch="main",
        ),
        issue_or_handoff_identity="issue:677",
        canonical_owner="integration-manager",
        requesting_actor="github-service-agent",
        capability=ExecutionServiceCapability.INSPECT_REPOSITORY,
        base_branch="main",
        base_sha=A,
        requested_ref="agent/677-immutable-validation-command-planning",
        expected_sha=expected_sha,
        allowed_paths=("08_Tooling/agent-os-execution-service",),
        forbidden_paths=("secrets",),
        inspected_file_count_limit=8,
        inspected_byte_limit=100_000,
        evidence_visibility_policy=EvidenceVisibilityPolicy.PUBLIC_SUMMARY_ONLY,
        invalidation_conditions=tuple(
            sorted(ExecutionServiceInvalidationCondition, key=lambda item: item.value)
        ),
    )


def plan(
    *,
    repository: str = "Blummer92/agent-os",
    profile: str = "focused",
    commands: tuple[str, ...] = (FOCUSED_COMMAND,),
    reason_codes: tuple[str, ...] = ("profile.focused-package",),
) -> ValidationPlan:
    return ValidationPlan(
        selector_version="1.0.0",
        repository=repository,
        pull_request=681,
        base_sha=A,
        head_sha=B,
        profile=profile,  # type: ignore[arg-type]
        commands=commands,
        command_set_digest=compute_command_set_digest("1.0.0", commands),
        reason_codes=reason_codes,
        remote_build_required=profile in {"focused", "aggregate"},
    )


def test_focused_plan_maps_exact_command_to_argv() -> None:
    value = build_validation_command_plan(request(), plan(), evaluated_at=EVALUATED_AT)
    assert value.schema_version == COMMAND_PLAN_SCHEMA_VERSION
    assert value.registry_version == COMMAND_REGISTRY_VERSION
    assert value.repository == "Blummer92/agent-os"
    assert value.entries == (
        value.entries[0],
    )
    assert value.entries[0].operation is CommandOperation.VALIDATION_FOCUSED
    assert value.entries[0].argv == (
        "python",
        "-m",
        "pytest",
        "tests/test_curriculum_pipeline_boundaries.py",
    )


def test_static_plan_has_no_executable_entries() -> None:
    static = plan(
        profile="static",
        commands=(),
        reason_codes=("profile.documentation-static",),
    )
    value = build_validation_command_plan(request(), static, evaluated_at=EVALUATED_AT)
    assert value.profile == "static"
    assert value.entries == ()


def test_unknown_command_fails_closed() -> None:
    unknown = "python -m pytest tests/not-allowlisted.py"
    with pytest.raises(ValueError, match="allowlisted"):
        build_validation_command_plan(
            request(),
            plan(commands=(unknown,)),
            evaluated_at=EVALUATED_AT,
        )


def test_identity_sha_and_freshness_mismatches_fail_closed() -> None:
    with pytest.raises(ValueError, match="repository identity mismatch"):
        build_validation_command_plan(
            request(),
            plan(repository="other/repo"),
            evaluated_at=EVALUATED_AT,
        )
    with pytest.raises(ValueError, match="expected SHA"):
        build_validation_command_plan(
            request(expected_sha=A),
            plan(),
            evaluated_at=EVALUATED_AT,
        )
    with pytest.raises(ValueError, match="invalid execution service request"):
        build_validation_command_plan(
            request(),
            plan(),
            evaluated_at="2026-07-27T04:00:00Z",
        )


def test_serialization_identity_and_immutability_are_deterministic() -> None:
    value = build_validation_command_plan(request(), plan(), evaluated_at=EVALUATED_AT)
    payload = serialize_validation_command_plan(value)
    assert payload["repository"] == "Blummer92/agent-os"
    assert payload["execution_authorized"] is False
    assert payload["merge_authorized"] is False
    assert payload["side_effects_performed"] is False
    assert validation_command_plan_id(value) == validation_command_plan_id(value)
    with pytest.raises(FrozenInstanceError):
        value.profile = "aggregate"  # type: ignore[misc]
