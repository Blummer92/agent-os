import copy
from dataclasses import FrozenInstanceError
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.agent_os_execution_capabilities import RepositoryIdentity
from scripts.agent_os_remote_validation import (
    PRE_PR_VALIDATION_PLAN_SCHEMA_VERSION,
    PrePrValidationPlan,
    PrePrValidationSubject,
    ValidationPlan,
    compute_command_set_digest,
    load_rule_map,
    pre_pr_validation_plan_id,
    select_pre_pr_validation_plan,
)
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


# --- Positive-PR characterization (#723 regression guard) ---------------------
#
# Captured from the pre-#723 planner. The registry gained one additional exact
# command, so this pins the serialized payload and the semantic `command-plan:`
# identity that every existing positive-PR caller already depends on.
POSITIVE_PR_COMMAND_PLAN_ID = (
    "command-plan:"
    "98e0a064f2abb0bfeceb80e25096060ad8906777f4d4272af8f397113427a35d"
)


def test_positive_pr_command_plan_payload_and_identity_are_unchanged() -> None:
    value = build_validation_command_plan(request(), plan(), evaluated_at=EVALUATED_AT)
    payload = serialize_validation_command_plan(value)
    assert payload == {
        "schema_version": "1.0",
        "registry_version": "1.0",
        "repository": "Blummer92/agent-os",
        "issue_or_handoff_identity": "issue:677",
        "requested_ref": "agent/677-immutable-validation-command-planning",
        "expected_sha": B,
        "request_revision": 1,
        "request_fingerprint": (
            "5c1b0f519ed53722372c438ae16f13b224da71927f6ed25c05619b8631a5cf4c"
        ),
        "validation_plan_id": (
            "validation-plan:"
            "626da63464a67ec164a9f5148356770cb323953ab35030d025b388c3a7ab2a88"
        ),
        "validation_plan_schema_version": "1.0",
        "selector_version": "1.0.0",
        "profile": "focused",
        "command_set_digest": compute_command_set_digest("1.0.0", (FOCUSED_COMMAND,)),
        "entries": [
            {
                "operation": "validation.focused",
                "argv": [
                    "python",
                    "-m",
                    "pytest",
                    "tests/test_curriculum_pipeline_boundaries.py",
                ],
            }
        ],
        "execution_authorized": False,
        "merge_authorized": False,
        "side_effects_performed": False,
    }
    assert validation_command_plan_id(value) == POSITIVE_PR_COMMAND_PLAN_ID


def test_non_plan_objects_still_fail_closed() -> None:
    with pytest.raises(TypeError, match="exact ExecutionServiceRequest"):
        build_validation_command_plan(object(), plan(), evaluated_at=EVALUATED_AT)
    with pytest.raises(TypeError, match="exact ValidationPlan"):
        build_validation_command_plan(request(), object(), evaluated_at=EVALUATED_AT)


# --- Pre-PR command binding (#723 / candidate #726) ---------------------------

PILOT_COMMAND = (
    "python -m pytest "
    "08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py"
)
PILOT_ARGV = (
    "python",
    "-m",
    "pytest",
    "08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py",
)
PILOT_PATH = "08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py"
PILOT_SHA = "df2d7d61db66d0835ed4ca6c9ec6d3fdcf85f465"
PILOT_BRANCH = "agent/723-pre-pr-validation-planning"
PILOT_ALLOWED = (PILOT_PATH,)
PILOT_FORBIDDEN = (".github/workflows", "cloudbuild.yaml", "scripts/validate-all.sh")
PILOT_EVALUATED_AT = "2026-07-29T21:30:00Z"


def pre_pr_subject(**overrides: object) -> PrePrValidationSubject:
    values: dict[str, object] = {
        "invocation_id": "invocation:726:0001",
        "base_sha": PILOT_SHA,
        "branch": PILOT_BRANCH,
        "expected_source_sha": PILOT_SHA,
        "tested_sha": PILOT_SHA,
        "allowed_files": PILOT_ALLOWED,
        "forbidden_paths": PILOT_FORBIDDEN,
        "required_command_identities": (PILOT_COMMAND,),
        "approval_id": "approval:398:0001",
        "approval_revision": 1,
        "projection_id": "projection:407:0001",
        "implementation_contract_fingerprint": "c" * 64,
    }
    values.update(overrides)
    return PrePrValidationSubject(**values)  # type: ignore[arg-type]


def pre_pr_plan(**overrides: object) -> PrePrValidationPlan:
    return select_pre_pr_validation_plan(pre_pr_subject(**overrides), load_rule_map())


def pre_pr_request(**overrides: object) -> ExecutionServiceRequest:
    values: dict[str, object] = {
        "schema_version": "1.0",
        "request_id": "pilot-726-001",
        "request_revision": 1,
        "created_at": "2026-07-29T21:00:00Z",
        "expires_at": "2026-07-29T22:00:00Z",
        "repository_identity": RepositoryIdentity(
            host="github.com",
            owner="Blummer92",
            repository="agent-os",
            repository_id=123,
            default_branch="main",
        ),
        "issue_or_handoff_identity": "issue:726",
        "canonical_owner": "integration-manager",
        "requesting_actor": "github-service-agent",
        "capability": ExecutionServiceCapability.INSPECT_REPOSITORY,
        "base_branch": "main",
        "base_sha": PILOT_SHA,
        "requested_ref": PILOT_BRANCH,
        "expected_sha": PILOT_SHA,
        "allowed_paths": PILOT_ALLOWED,
        "forbidden_paths": PILOT_FORBIDDEN,
        "inspected_file_count_limit": 8,
        "inspected_byte_limit": 100_000,
        "evidence_visibility_policy": EvidenceVisibilityPolicy.PUBLIC_SUMMARY_ONLY,
        "invalidation_conditions": tuple(
            sorted(ExecutionServiceInvalidationCondition, key=lambda item: item.value)
        ),
    }
    values.update(overrides)
    return ExecutionServiceRequest(**values)  # type: ignore[arg-type]


def test_pilot_command_maps_to_frozen_argv() -> None:
    value = build_validation_command_plan(
        pre_pr_request(), pre_pr_plan(), evaluated_at=PILOT_EVALUATED_AT
    )
    assert value.entries[0].operation is CommandOperation.VALIDATION_FOCUSED
    assert value.entries[0].argv == PILOT_ARGV
    assert len(value.entries) == 1


def test_pre_pr_command_plan_binds_issue_and_subject_identities() -> None:
    plan_value = pre_pr_plan()
    value = build_validation_command_plan(
        pre_pr_request(), plan_value, evaluated_at=PILOT_EVALUATED_AT
    )
    payload = serialize_validation_command_plan(value)
    assert payload["repository"] == "Blummer92/agent-os"
    assert payload["issue_or_handoff_identity"] == "issue:726"
    assert payload["requested_ref"] == PILOT_BRANCH
    assert payload["expected_sha"] == PILOT_SHA
    assert payload["profile"] == "focused"
    assert payload["registry_version"] == COMMAND_REGISTRY_VERSION
    assert payload["validation_plan_id"] == pre_pr_validation_plan_id(plan_value)
    assert str(payload["validation_plan_id"]).startswith("pre-pr-validation-plan:")
    assert payload["validation_plan_schema_version"] == (
        PRE_PR_VALIDATION_PLAN_SCHEMA_VERSION
    )
    assert payload["execution_authorized"] is False
    assert payload["merge_authorized"] is False
    assert payload["side_effects_performed"] is False
    assert validation_command_plan_id(value) == validation_command_plan_id(value)
    assert validation_command_plan_id(value) != POSITIVE_PR_COMMAND_PLAN_ID


def test_pre_pr_command_plan_identity_is_stable() -> None:
    value = build_validation_command_plan(
        pre_pr_request(), pre_pr_plan(), evaluated_at=PILOT_EVALUATED_AT
    )
    assert validation_command_plan_id(value) == (
        "command-plan:"
        "9d3e5032e1fc46f233b79ad6be3767bc507304d015a6ebebc974c5e747f3e835"
    )


@pytest.mark.parametrize(
    ("request_overrides", "message"),
    [
        ({"issue_or_handoff_identity": "issue:725"}, "issue identity mismatch"),
        ({"base_branch": "release"}, "base branch mismatch"),
        ({"base_sha": A}, "base SHA mismatch"),
        ({"requested_ref": "agent/other-branch"}, "branch mismatch"),
        ({"expected_sha": A}, "expected SHA"),
        ({"allowed_paths": ("08_Tooling",)}, "allowed scope mismatch"),
        ({"forbidden_paths": ("secrets",)}, "forbidden scope mismatch"),
    ],
)
def test_pre_pr_request_drift_fails_closed(
    request_overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        build_validation_command_plan(
            pre_pr_request(**request_overrides),
            pre_pr_plan(),
            evaluated_at=PILOT_EVALUATED_AT,
        )


def test_pre_pr_repository_and_freshness_drift_fail_closed() -> None:
    other = pre_pr_request(
        repository_identity=RepositoryIdentity(
            host="github.com",
            owner="other",
            repository="repo",
            repository_id=456,
            default_branch="main",
        )
    )
    with pytest.raises(ValueError, match="repository identity mismatch"):
        build_validation_command_plan(
            other, pre_pr_plan(), evaluated_at=PILOT_EVALUATED_AT
        )
    with pytest.raises(ValueError, match="invalid execution service request"):
        build_validation_command_plan(
            pre_pr_request(), pre_pr_plan(), evaluated_at="2026-07-29T22:00:00Z"
        )


def test_pre_pr_unregistered_command_fails_closed() -> None:
    unregistered = "python -m pytest tests/not-allowlisted.py"
    rules = copy.deepcopy(load_rule_map())
    for rule in rules["focused_rules"]:
        if rule["name"] == "workflow-scheduler-concrete-runtime-adapters":
            rule["commands"] = [unregistered]
    unallowlisted = select_pre_pr_validation_plan(
        pre_pr_subject(required_command_identities=(unregistered,)), rules
    )
    with pytest.raises(ValueError, match="allowlisted"):
        build_validation_command_plan(
            pre_pr_request(), unallowlisted, evaluated_at=PILOT_EVALUATED_AT
        )


def test_pre_pr_command_and_timeout_drift_fail_closed() -> None:
    drifted = pre_pr_plan()
    object.__setattr__(drifted, "commands", ("python -m pytest",))
    with pytest.raises(ValueError, match="command identity drift"):
        build_validation_command_plan(
            pre_pr_request(), drifted, evaluated_at=PILOT_EVALUATED_AT
        )

    over_ceiling = pre_pr_plan()
    object.__setattr__(over_ceiling, "per_command_timeout_seconds", 31)
    with pytest.raises(ValueError, match="timeout"):
        build_validation_command_plan(
            pre_pr_request(), over_ceiling, evaluated_at=PILOT_EVALUATED_AT
        )

    over_total = pre_pr_plan()
    object.__setattr__(over_total, "total_validation_timeout_seconds", 301)
    with pytest.raises(ValueError, match="timeout"):
        build_validation_command_plan(
            pre_pr_request(), over_total, evaluated_at=PILOT_EVALUATED_AT
        )


def test_pre_pr_plan_carries_the_frozen_timeout_ceilings() -> None:
    plan_value = pre_pr_plan()
    assert plan_value.per_command_timeout_seconds == 30
    assert plan_value.total_validation_timeout_seconds == 300
    assert plan_value.remote_build_required is False
    assert plan_value.execution_authorized is False
    assert plan_value.merge_authorized is False
    assert plan_value.side_effects_performed is False


def test_pre_pr_command_plan_is_immutable() -> None:
    value = build_validation_command_plan(
        pre_pr_request(), pre_pr_plan(), evaluated_at=PILOT_EVALUATED_AT
    )
    with pytest.raises(FrozenInstanceError):
        value.profile = "aggregate"  # type: ignore[misc]
