from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Literal

from scripts.agent_os_remote_validation import (
    MAX_PLAN_COMMANDS,
    MAX_PLAN_STRING_LENGTH,
    PRE_PR_PER_COMMAND_TIMEOUT_SECONDS,
    PRE_PR_TOTAL_VALIDATION_TIMEOUT_SECONDS,
    PRE_PR_VALIDATION_PLAN_SCHEMA_VERSION,
    VALIDATION_PLAN_SCHEMA_VERSION,
    PrePrValidationPlan,
    ValidationPlan,
    pre_pr_validation_plan_id,
    validate_validation_plan,
    validation_plan_id,
)

from .models import ExecutionServiceRequest, execution_service_request_fingerprint
from .request_validation import validate_execution_service_request

COMMAND_PLAN_SCHEMA_VERSION = "1.0"
COMMAND_REGISTRY_VERSION = "1.0"
MAX_COMMAND_PLAN_SERIALIZED_BYTES = 32_768

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_VALIDATION_PLAN_ID_RE = re.compile(r"^validation-plan:[0-9a-f]{64}$", re.ASCII)
_PRE_PR_VALIDATION_PLAN_ID_RE = re.compile(
    r"^pre-pr-validation-plan:[0-9a-f]{64}$", re.ASCII
)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class CommandOperation(str, Enum):
    VALIDATION_STATIC = "validation.static"
    VALIDATION_FOCUSED = "validation.focused"
    VALIDATION_AGGREGATE = "validation.aggregate"


# ``COMMAND_REGISTRY_VERSION`` is serialized into every command plan and therefore
# into its identity. Allowlisting an additional exact command is purely additive,
# so the version stays pinned and existing positive-PR command-plan payloads and
# ``command-plan:`` identities remain byte-for-byte stable.
_COMMAND_REGISTRY = MappingProxyType(
    {
        "python -m pytest": ("python", "-m", "pytest"),
        "python -m pytest tests/agent_os_issue_acceptance": (
            "python",
            "-m",
            "pytest",
            "tests/agent_os_issue_acceptance",
        ),
        "python -m pytest 08_Tooling/workflow-scheduler/tests": (
            "python",
            "-m",
            "pytest",
            "08_Tooling/workflow-scheduler/tests",
        ),
        (
            "python -m pytest "
            "08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py"
        ): (
            "python",
            "-m",
            "pytest",
            "08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py",
        ),
        "python -m pytest 08_Tooling/notion-navigation-client/tests": (
            "python",
            "-m",
            "pytest",
            "08_Tooling/notion-navigation-client/tests",
        ),
        "python -m pytest 08_Tooling/instructional-materials-coach/tests": (
            "python",
            "-m",
            "pytest",
            "08_Tooling/instructional-materials-coach/tests",
        ),
        "python -m pytest tests/test_curriculum_pipeline_boundaries.py": (
            "python",
            "-m",
            "pytest",
            "tests/test_curriculum_pipeline_boundaries.py",
        ),
        "python -m pytest tests/test_curriculum_language_system.py": (
            "python",
            "-m",
            "pytest",
            "tests/test_curriculum_language_system.py",
        ),
        "python -m pytest tests/test_teacher_modeling_workflows.py": (
            "python",
            "-m",
            "pytest",
            "tests/test_teacher_modeling_workflows.py",
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
        if not all(
            type(item) is str and item and len(item) <= MAX_PLAN_STRING_LENGTH
            for item in self.argv
        ):
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


# Keyed by profile name so both the builder and the validator agree on exactly
# one operation per profile without duplicating the mapping.
_PROFILE_OPERATIONS = MappingProxyType(
    {
        "static": CommandOperation.VALIDATION_STATIC,
        "focused": CommandOperation.VALIDATION_FOCUSED,
        "aggregate": CommandOperation.VALIDATION_AGGREGATE,
    }
)

# Derived once from the private registry so argv membership can be checked
# without exposing, duplicating, or mutating the registry itself.
_REGISTRY_ARGV_VALUES = frozenset(_COMMAND_REGISTRY.values())


def _operation_for(profile: str) -> CommandOperation:
    operation = _PROFILE_OPERATIONS.get(profile)
    if operation is None:
        raise ValueError("manual-review plans cannot produce command plans")
    return operation


def build_validation_command_plan(
    request: object,
    validation_plan: object,
    *,
    evaluated_at: object,
) -> ValidationCommandPlan:
    if type(request) is not ExecutionServiceRequest:
        raise TypeError("request must be an exact ExecutionServiceRequest")
    if type(validation_plan) is PrePrValidationPlan:
        return _build_pre_pr_command_plan(
            request,
            validation_plan,
            evaluated_at=evaluated_at,
        )
    if type(validation_plan) is not ValidationPlan:
        raise TypeError("validation_plan must be an exact ValidationPlan")
    request_reasons = validate_execution_service_request(
        request,
        evaluated_at=evaluated_at,
    )
    if request_reasons:
        raise ValueError("invalid execution service request")
    plan_reasons = validate_validation_plan(validation_plan)
    if plan_reasons:
        raise ValueError("invalid validation plan")

    request_repository = (
        f"{request.repository_identity.owner}/"
        f"{request.repository_identity.repository}"
    )
    if request_repository.casefold() != validation_plan.repository.casefold():
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
        repository=validation_plan.repository,
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


def _build_pre_pr_command_plan(
    request: ExecutionServiceRequest,
    plan: PrePrValidationPlan,
    *,
    evaluated_at: object,
) -> ValidationCommandPlan:
    """Bind one issue- and invocation-bound pre-PR plan to fixed registry argv.

    The pre-PR branch never invents a pull-request identity: the command plan is
    bound to the subject's issue, invocation, branch, and SHAs instead. Entry order
    follows the subject's ordered command identities rather than argv order.
    """
    request_reasons = validate_execution_service_request(
        request,
        evaluated_at=evaluated_at,
    )
    if request_reasons:
        raise ValueError("invalid execution service request")
    if plan.per_command_timeout_seconds > PRE_PR_PER_COMMAND_TIMEOUT_SECONDS:
        raise ValueError("pre-PR per-command timeout exceeds the ceiling")
    if plan.total_validation_timeout_seconds > PRE_PR_TOTAL_VALIDATION_TIMEOUT_SECONDS:
        raise ValueError("pre-PR total validation timeout exceeds the ceiling")
    plan_identity = pre_pr_validation_plan_id(plan)
    subject = plan.subject

    request_repository = (
        f"{request.repository_identity.owner}/"
        f"{request.repository_identity.repository}"
    )
    if request_repository.casefold() != subject.repository.casefold():
        raise ValueError("repository identity mismatch")
    if request.issue_or_handoff_identity != f"issue:{subject.issue_number}":
        raise ValueError("pre-PR issue identity mismatch")
    if request.base_branch != subject.base_branch:
        raise ValueError("pre-PR base branch mismatch")
    if request.base_sha != subject.base_sha:
        raise ValueError("pre-PR base SHA mismatch")
    if request.requested_ref != subject.branch:
        raise ValueError("pre-PR branch mismatch")
    if request.expected_sha != subject.expected_source_sha:
        raise ValueError("expected SHA does not match validation plan")
    if request.allowed_paths != subject.allowed_files:
        raise ValueError("pre-PR allowed scope mismatch")
    if request.forbidden_paths != subject.forbidden_paths:
        raise ValueError("pre-PR forbidden scope mismatch")
    if request.request_fingerprint != execution_service_request_fingerprint(request):
        raise ValueError("request fingerprint mismatch")
    if plan.commands != subject.required_command_identities:
        raise ValueError("pre-PR command identity drift")
    if len(plan.commands) > MAX_PLAN_COMMANDS:
        raise ValueError("validation command count exceeds limit")
    if len(set(plan.commands)) != len(plan.commands):
        raise ValueError("duplicate validation command")

    built: list[CommandPlanEntry] = []
    for command in plan.commands:
        argv = _COMMAND_REGISTRY.get(command)
        if argv is None:
            raise ValueError("validation command is not allowlisted")
        built.append(
            CommandPlanEntry(operation=CommandOperation.VALIDATION_FOCUSED, argv=argv)
        )

    return ValidationCommandPlan(
        schema_version=COMMAND_PLAN_SCHEMA_VERSION,
        registry_version=COMMAND_REGISTRY_VERSION,
        repository=subject.repository,
        issue_or_handoff_identity=request.issue_or_handoff_identity,
        requested_ref=request.requested_ref,
        expected_sha=request.expected_sha,
        request_revision=request.request_revision,
        request_fingerprint=request.request_fingerprint,
        validation_plan_id=plan_identity,
        validation_plan_schema_version=PRE_PR_VALIDATION_PLAN_SCHEMA_VERSION,
        selector_version=plan.selector_version,
        profile=plan.profile,
        command_set_digest=plan.command_set_digest,
        entries=tuple(built),
    )


def _runtime_safe_command_plan_entry(entry: object) -> bool:
    """Return whether one command-plan entry has every exact runtime type and
    bound this module trusts before it is ever used for registry membership,
    hashing, tuple comparison, set construction, sorting, or serialization.

    ``CommandPlanEntry.__post_init__`` only validates at construction time, so
    an exact-type instance reached through ``object.__setattr__`` tampering
    can still carry a non-tuple ``argv``, a non-``CommandOperation``
    ``operation``, or an argv element outside the bounds construction would
    have enforced. Every such shape is rejected here first.
    """
    if type(entry) is not CommandPlanEntry:
        return False
    if type(entry.operation) is not CommandOperation:
        return False
    if type(entry.argv) is not tuple:
        return False
    if not entry.argv or len(entry.argv) > MAX_PLAN_COMMANDS:
        return False
    for item in entry.argv:
        if type(item) is not str or not item or len(item) > MAX_PLAN_STRING_LENGTH:
            return False
        if _CONTROL_CHAR_RE.search(item) is not None:
            return False
    return True


def _runtime_safe_command_plan(plan: ValidationCommandPlan) -> bool:
    """Return whether every field has the exact runtime type this validator trusts.

    Short-circuits before any risky access: ``entries`` is confirmed to be a
    tuple before it is ever iterated, and every item is confirmed to be an
    exact ``CommandPlanEntry`` with a defensively revalidated ``operation``
    and ``argv`` (see ``_runtime_safe_command_plan_entry``) before either is
    read anywhere else in this module.
    """
    return (
        type(plan.schema_version) is str
        and type(plan.registry_version) is str
        and type(plan.repository) is str
        and type(plan.issue_or_handoff_identity) is str
        and type(plan.requested_ref) is str
        and type(plan.expected_sha) is str
        and type(plan.request_revision) is int
        and not isinstance(plan.request_revision, bool)
        and type(plan.request_fingerprint) is str
        and type(plan.validation_plan_id) is str
        and type(plan.validation_plan_schema_version) is str
        and type(plan.selector_version) is str
        and type(plan.profile) is str
        and type(plan.command_set_digest) is str
        and type(plan.entries) is tuple
        and all(_runtime_safe_command_plan_entry(item) for item in plan.entries)
        and plan.execution_authorized is False
        and plan.merge_authorized is False
        and plan.side_effects_performed is False
    )


def _validation_plan_schema_reason(plan: ValidationCommandPlan) -> str | None:
    if _VALIDATION_PLAN_ID_RE.fullmatch(plan.validation_plan_id):
        if plan.validation_plan_schema_version != VALIDATION_PLAN_SCHEMA_VERSION:
            return "command-plan.validation-plan-schema"
        return None
    if _PRE_PR_VALIDATION_PLAN_ID_RE.fullmatch(plan.validation_plan_id):
        if plan.validation_plan_schema_version != PRE_PR_VALIDATION_PLAN_SCHEMA_VERSION:
            return "command-plan.validation-plan-schema"
        return None
    return "command-plan.validation-plan-schema"


def _bounded_identity_text(value: str) -> bool:
    return bool(value) and len(value) <= MAX_PLAN_STRING_LENGTH


def validate_validation_command_plan(plan: object) -> tuple[str, ...]:
    """Validate one command plan without I/O, mutation, or ever raising.

    Returns a sorted tuple of bounded reason codes; an empty tuple means the
    plan satisfies every check below. This is the single source of truth
    ``serialize_validation_command_plan`` and ``validation_command_plan_id``
    defer to -- neither function accepts a plan this validator rejects, and
    neither carves out an exemption for unregistered argv or a profile/
    operation mismatch. Argv membership is checked against the existing
    private ``_COMMAND_REGISTRY`` in this module; the registry itself is
    never exposed, copied, mutated, or version-bumped by this function.
    """
    if type(plan) is not ValidationCommandPlan:
        return ("command-plan.invalid-type",)
    if not _runtime_safe_command_plan(plan):
        return ("command-plan.malformed-runtime",)

    reasons: set[str] = set()
    if plan.schema_version != COMMAND_PLAN_SCHEMA_VERSION:
        reasons.add("command-plan.schema-version")
    if plan.registry_version != COMMAND_REGISTRY_VERSION:
        reasons.add("command-plan.registry-version")
    if plan.request_revision <= 0:
        reasons.add("command-plan.request-revision")

    for value in (
        plan.repository,
        plan.issue_or_handoff_identity,
        plan.requested_ref,
        plan.request_fingerprint,
        plan.validation_plan_id,
        plan.selector_version,
        plan.command_set_digest,
    ):
        if not _bounded_identity_text(value):
            reasons.add("command-plan.identity-bounds")
            break
    if not _SHA40_RE.fullmatch(plan.expected_sha):
        reasons.add("command-plan.identity-bounds")
    if not _SHA256_RE.fullmatch(plan.request_fingerprint):
        reasons.add("command-plan.identity-bounds")
    if not _SHA256_RE.fullmatch(plan.command_set_digest):
        reasons.add("command-plan.identity-bounds")

    schema_reason = _validation_plan_schema_reason(plan)
    if schema_reason is not None:
        reasons.add(schema_reason)

    expected_operation = _PROFILE_OPERATIONS.get(plan.profile)
    if expected_operation is None:
        reasons.add("command-plan.profile-operation-mismatch")
    elif any(entry.operation is not expected_operation for entry in plan.entries):
        reasons.add("command-plan.profile-operation-mismatch")

    if plan.profile == "static" and plan.entries:
        reasons.add("command-plan.static-not-empty")
    if plan.profile in ("focused", "aggregate") and not plan.entries:
        reasons.add("command-plan.executable-empty")

    argvs = tuple(entry.argv for entry in plan.entries)
    if any(argv not in _REGISTRY_ARGV_VALUES for argv in argvs):
        reasons.add("command-plan.argv-not-registered")
    if len(set(argvs)) != len(argvs):
        reasons.add("command-plan.duplicate-argv")
    if _VALIDATION_PLAN_ID_RE.fullmatch(plan.validation_plan_id) and argvs != tuple(
        sorted(argvs)
    ):
        reasons.add("command-plan.ordering")

    encoded = json.dumps(
        _command_plan_payload(plan),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_COMMAND_PLAN_SERIALIZED_BYTES:
        reasons.add("command-plan.serialized-size")

    return tuple(sorted(reasons))


def _command_plan_payload(plan: ValidationCommandPlan) -> dict[str, object]:
    return {
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


def serialize_validation_command_plan(plan: object) -> dict[str, object]:
    if type(plan) is not ValidationCommandPlan:
        raise TypeError("plan must be an exact ValidationCommandPlan")
    reasons = validate_validation_command_plan(plan)
    if reasons:
        raise ValueError(
            "invalid validation command plan: " + ",".join(reasons)
        )
    return _command_plan_payload(plan)


def validation_command_plan_id(plan: object) -> str:
    payload = serialize_validation_command_plan(plan)
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(
        b"agent-os-command-plan:v1\0" + canonical
    ).hexdigest()
    return f"command-plan:{digest}"
