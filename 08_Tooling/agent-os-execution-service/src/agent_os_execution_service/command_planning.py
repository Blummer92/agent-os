from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Literal

from scripts.agent_os_remote_validation import (
    MAX_PLAN_COMMANDS,
    MAX_PLAN_STRING_LENGTH,
    VALIDATION_PLAN_SCHEMA_VERSION,
    ValidationPlan,
    validate_validation_plan,
    validation_plan_id,
)

from .models import ExecutionServiceRequest, execution_service_request_fingerprint
from .request_validation import validate_execution_service_request

COMMAND_PLAN_SCHEMA_VERSION = "1.0"
COMMAND_REGISTRY_VERSION = "1.0"
MAX_COMMAND_PLAN_SERIALIZED_BYTES = 32_768


class CommandOperation(str, Enum):
    VALIDATION_STATIC = "validation.static"
    VALIDATION_FOCUSED = "validation.focused"
    VALIDATION_AGGREGATE = "validation.aggregate"


_COMMAND_REGISTRY = MappingProxyType(
    {
        "python -m pytest": ("python", "-m", "pytest"),
        "python -m pytest tests/agent_os_issue_acceptance": (
            "python", "-m", "pytest", "tests/agent_os_issue_acceptance"
        ),
        "python -m pytest 08_Tooling/workflow-scheduler/tests": (
            "python", "-m", "pytest", "08_Tooling/workflow-scheduler/tests"
        ),
        "python -m pytest 08_Tooling/notion-navigation-client/tests": (
            "python", "-m", "pytest", "08_Tooling/notion-navigation-client/tests"
        ),
        "python -m pytest 08_Tooling/instructional-materials-coach/tests": (
            "python", "-m", "pytest", "08_Tooling/instructional-materials-coach/tests"
        ),
        "python -m pytest tests/test_curriculum_pipeline_boundaries.py": (
            "python", "-m", "pytest", "tests/test_curriculum_pipeline_boundaries.py"
        ),
        "python -m pytest tests/test_curriculum_language_system.py": (
            "python", "-m", "pytest", "tests/test_curriculum_language_system.py"
        ),
        "python -m pytest tests/test_teacher_modeling_workflows.py": (
            "python", "-m", "pytest", "tests/test_teacher_modeling_workflows.py"
        ),
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class CommandPlanEntry:
    operation: CommandOperation
    argv: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.operation) is not CommandOperation:
            raise TypeError("operation must be CommandOperation")
        if type(self.argv) is not tuple or not self.argv:
            raise TypeError("argv must be a non-empty exact tuple")
        if not all(type(item) is str and item and len(item) <= MAX_PLAN_STRING_LENGTH for item in self.argv):
            raise ValueError("argv contains an invalid item")


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidationCommandPlan:
    schema_version: str
    registry_version: str
    repository: str
    issue_or_handoff_identity: str
    requested_ref: str
    expected_sha: str
    request_revision: int
    request_fingerprint: str
    validation_plan_id: str
    validation_plan_schema_version: str
    selector_version: str
    profile: str
    command_set_digest: str
    entries: tuple[CommandPlanEntry, ...]
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


def _operation_for(profile: str) -> CommandOperation:
    if profile == "static":
        return CommandOperation.VALIDATION_STATIC
    if profile == "focused":
        return CommandOperation.VALIDATION_FOCUSED
    if profile == "aggregate":
        return CommandOperation.VALIDATION_AGGREGATE
    raise ValueError("manual-review plans cannot produce command plans")


def build_validation_command_plan(
    request: object,
    validation_plan: object,
    *,
    evaluated_at: object,
) -> ValidationCommandPlan:
    if type(request) is not ExecutionServiceRequest:
        raise TypeError("request must be an exact ExecutionServiceRequest")
    if type(validation_plan) is not ValidationPlan:
        raise TypeError("validation_plan must be an exact ValidationPlan")
    request_reasons = validate_execution_service_request(request, evaluated_at=evaluated_at)
    if request_reasons:
        raise ValueError("invalid execution service request")
    plan_reasons = validate_validation_plan(validation_plan)
    if plan_reasons:
        raise ValueError("invalid validation plan")

    repository = f"{request.repository_identity.owner}/{request.repository_identity.repository}"
    if repository != validation_plan.repository:
        raise ValueError("repository identity mismatch")
    if request.expected_sha != validation_plan.head_sha:
        raise ValueError("expected SHA does not match validation plan")
    if request.request_fingerprint != execution_service_request_fingerprint(request):
        raise ValueError("request fingerprint mismatch")
    if len(validation_plan.commands) > MAX_PLAN_COMMANDS:
        raise ValueError("validation command count exceeds limit")

    operation = _operation_for(validation_plan.profile)
    entries: tuple[CommandPlanEntry, ...]
    if operation is CommandOperation.VALIDATION_STATIC:
        if validation_plan.commands:
            raise ValueError("static validation plan must not contain commands")
        entries = ()
    else:
        if len(set(validation_plan.commands)) != len(validation_plan.commands):
            raise ValueError("duplicate validation command")
        built: list[CommandPlanEntry] = []
        for command in validation_plan.commands:
            argv = _COMMAND_REGISTRY.get(command)
            if argv is None:
                raise ValueError("validation command is not allowlisted")
            built.append(CommandPlanEntry(operation=operation, argv=argv))
        entries = tuple(sorted(built, key=lambda item: item.argv))

    return ValidationCommandPlan(
        schema_version=COMMAND_PLAN_SCHEMA_VERSION,
        registry_version=COMMAND_REGISTRY_VERSION,
        repository=repository,
        issue_or_handoff_identity=request.issue_or_handoff_identity,
        requested_ref=request.requested_ref,
        expected_sha=request.expected_sha,
        request_revision=request.request_revision,
        request_fingerprint=request.request_fingerprint,
        validation_plan_id=validation_plan_id(validation_plan),
        validation_plan_schema_version=VALIDATION_PLAN_SCHEMA_VERSION,
        selector_version=validation_plan.selector_version,
        profile=validation_plan.profile,
        command_set_digest=validation_plan.command_set_digest,
        entries=entries,
    )


def serialize_validation_command_plan(plan: object) -> dict[str, object]:
    if type(plan) is not ValidationCommandPlan:
        raise TypeError("plan must be an exact ValidationCommandPlan")
    payload: dict[str, object] = {
        "schema_version": plan.schema_version,
        "registry_version": plan.registry_version,
        "repository": plan.repository,
        "issue_or_handoff_identity": plan.issue_or_handoff_identity,
        "requested_ref": plan.requested_ref,
        "expected_sha": plan.expected_sha,
        "request_revision": plan.request_revision,
        "request_fingerprint": plan.request_fingerprint,
        "validation_plan_id": plan.validation_plan_id,
        "validation_plan_schema_version": plan.validation_plan_schema_version,
        "selector_version": plan.selector_version,
        "profile": plan.profile,
        "command_set_digest": plan.command_set_digest,
        "entries": [
            {"operation": entry.operation.value, "argv": list(entry.argv)}
            for entry in plan.entries
        ],
        "execution_authorized": False,
        "merge_authorized": False,
        "side_effects_performed": False,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_COMMAND_PLAN_SERIALIZED_BYTES:
        raise ValueError("command plan exceeds serialized size limit")
    return payload


def validation_command_plan_id(plan: object) -> str:
    payload = serialize_validation_command_plan(plan)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(b"agent-os-command-plan:v1\0" + canonical).hexdigest()
    return f"command-plan:{digest}"
