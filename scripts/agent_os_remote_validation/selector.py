from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .models import (
    MAX_PLAN_COMMANDS,
    MAX_PLAN_REASON_CODES,
    MAX_PLAN_SERIALIZED_BYTES,
    MAX_PLAN_STRING_LENGTH,
    VALIDATION_PLAN_SCHEMA_NAME,
    VALIDATION_PLAN_SCHEMA_VERSION,
    SelectionInput,
    ValidationPlan,
    ValidationProfile,
)

_RULES = Path(__file__).with_name("validation_profiles.yml")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SELECTOR_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PROFILES = frozenset({"static", "focused", "aggregate", "manual-review"})
_PROFILE_REASONS = {
    "static": frozenset({"profile.documentation-static"}),
    "focused": frozenset({"profile.focused-package", "profile.focused-union"}),
    "aggregate": frozenset(
        {"profile.aggregate-configuration", "profile.aggregate-unmapped-executable"}
    ),
    "manual-review": frozenset(
        {
            "rule.ambiguous",
            "rule.version-unsupported",
            "identity.repository-mismatch",
            "identity.base-sha-missing",
            "identity.head-sha-missing",
            "metadata.malformed",
            "metadata.empty-changed-files",
        }
    ),
}


def load_rule_map(path: Path | None = None) -> dict[str, Any]:
    """Load rules at the caller boundary; selection itself remains pure."""
    data = json.loads((path or _RULES).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("rule map must be an object")
    return data


def compute_command_set_digest(version: str, commands: tuple[str, ...]) -> str:
    """Return the canonical command-set digest used by existing selector output."""
    raw = json.dumps([version, commands], separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def validate_validation_plan(plan: object) -> tuple[str, ...]:
    """Validate one canonical plan without I/O or policy inference."""
    reasons: set[str] = set()
    if not isinstance(plan, ValidationPlan):
        return ("plan.invalid-type",)

    if not _bounded_text(plan.selector_version) or not _SELECTOR_VERSION.fullmatch(
        plan.selector_version
    ):
        reasons.add("plan.selector-version")
    if not _bounded_text(plan.repository):
        reasons.add("plan.repository")
    if not isinstance(plan.pull_request, int) or isinstance(plan.pull_request, bool):
        reasons.add("plan.pull-request")
    if plan.profile not in _PROFILES:
        reasons.add("plan.profile")
    if not isinstance(plan.commands, tuple):
        reasons.add("plan.commands")
    if not isinstance(plan.reason_codes, tuple):
        reasons.add("plan.reason-codes")
    if not isinstance(plan.remote_build_required, bool):
        reasons.add("plan.remote-build")
    if plan.execution_authorized is not False:
        reasons.add("plan.execution-authorized")
    if plan.side_effects_performed is not False:
        reasons.add("plan.side-effects")

    commands = plan.commands if isinstance(plan.commands, tuple) else ()
    reason_codes = plan.reason_codes if isinstance(plan.reason_codes, tuple) else ()
    if len(commands) > MAX_PLAN_COMMANDS:
        reasons.add("plan.commands-limit")
    if len(reason_codes) == 0 or len(reason_codes) > MAX_PLAN_REASON_CODES:
        reasons.add("plan.reason-codes")
    if len(set(commands)) != len(commands):
        reasons.add("plan.commands-duplicate")
    if any(not _bounded_text(command) for command in commands):
        reasons.add("plan.command-invalid")
    if any(not _bounded_text(reason) for reason in reason_codes):
        reasons.add("plan.reason-code-invalid")

    if plan.profile == "manual-review":
        if commands:
            reasons.add("plan.manual-review-commands")
        if plan.command_set_digest != "unavailable":
            reasons.add("plan.manual-review-digest")
        if plan.remote_build_required is not False:
            reasons.add("plan.manual-review-remote-build")
        if reason_codes and any(
            reason not in _PROFILE_REASONS["manual-review"] for reason in reason_codes
        ):
            reasons.add("plan.reason-profile")
    else:
        if not _SHA.fullmatch(plan.base_sha):
            reasons.add("plan.base-sha")
        if not _SHA.fullmatch(plan.head_sha):
            reasons.add("plan.head-sha")
        if plan.pull_request <= 0:
            reasons.add("plan.pull-request")
        if not _DIGEST.fullmatch(plan.command_set_digest):
            reasons.add("plan.command-digest")
        elif plan.command_set_digest != compute_command_set_digest(
            plan.selector_version, commands
        ):
            reasons.add("plan.command-digest")
        if reason_codes and any(
            reason not in _PROFILE_REASONS.get(plan.profile, frozenset())
            for reason in reason_codes
        ):
            reasons.add("plan.reason-profile")
        if plan.profile == "static":
            if commands:
                reasons.add("plan.static-commands")
            if plan.remote_build_required is not False:
                reasons.add("plan.static-remote-build")
        elif plan.profile in {"focused", "aggregate"}:
            if not commands:
                reasons.add("plan.executable-commands")
            if plan.remote_build_required is not True:
                reasons.add("plan.executable-remote-build")

    return tuple(sorted(reasons))


def serialize_validation_plan(plan: ValidationPlan) -> dict[str, object]:
    """Return deterministic canonical JSON-compatible plan data."""
    reasons = validate_validation_plan(plan)
    if reasons:
        raise ValueError("invalid validation plan: " + ",".join(reasons))
    payload: dict[str, object] = {
        "schema_name": VALIDATION_PLAN_SCHEMA_NAME,
        "schema_version": VALIDATION_PLAN_SCHEMA_VERSION,
        "selector_version": plan.selector_version,
        "repository": plan.repository,
        "pull_request": plan.pull_request,
        "base_sha": plan.base_sha,
        "head_sha": plan.head_sha,
        "profile": plan.profile,
        "commands": list(plan.commands),
        "command_set_digest": plan.command_set_digest,
        "reason_codes": list(plan.reason_codes),
        "remote_build_required": plan.remote_build_required,
        "execution_authorized": False,
        "side_effects_performed": False,
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    if len(encoded) > MAX_PLAN_SERIALIZED_BYTES:
        raise ValueError("validation plan exceeds canonical size limit")
    return payload


def validation_plan_id(plan: ValidationPlan) -> str:
    """Return a domain-separated semantic identity for one valid plan."""
    payload = serialize_validation_plan(plan)
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    digest = hashlib.sha256(b"agent-os-validation-plan:v1\0" + canonical).hexdigest()
    return f"validation-plan:{digest}"


def _safe_text(value: object) -> str:
    return value if isinstance(value, str) else "unavailable"


def _safe_pr(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _plan(
    value: SelectionInput,
    profile: ValidationProfile,
    commands: tuple[str, ...],
    reason: str,
) -> ValidationPlan:
    version = _safe_text(value.selector_version)
    return ValidationPlan(
        selector_version=version,
        repository=_safe_text(value.repository),
        pull_request=_safe_pr(value.pull_request),
        base_sha=_safe_text(value.base_sha),
        head_sha=_safe_text(value.head_sha),
        profile=profile,
        commands=commands,
        command_set_digest=(
            compute_command_set_digest(version, commands)
            if profile != "manual-review"
            else "unavailable"
        ),
        reason_codes=(reason,),
        remote_build_required=profile in {"focused", "aggregate"},
    )


def _bounded_text(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= MAX_PLAN_STRING_LENGTH
        and _CONTROL.search(value) is None
    )


def _string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _valid_rule_map(rules: object) -> bool:
    if not isinstance(rules, dict):
        return False
    if not isinstance(rules.get("selector_version"), str):
        return False
    if not isinstance(rules.get("repository"), str):
        return False
    if not isinstance(rules.get("aggregate_command"), str):
        return False
    for key in (
        "aggregate_paths",
        "aggregate_prefixes",
        "documentation_prefixes",
        "documentation_suffixes",
    ):
        if not _string_list(rules.get(key)):
            return False
    focused_rules = rules.get("focused_rules")
    if not isinstance(focused_rules, list):
        return False
    for rule in focused_rules:
        if not isinstance(rule, dict):
            return False
        if not isinstance(rule.get("name"), str):
            return False
        if not _string_list(rule.get("prefixes")):
            return False
        if not _string_list(rule.get("commands")):
            return False
    return True


def select_validation_plan(
    value: SelectionInput,
    rules: dict[str, Any],
) -> ValidationPlan:
    """Return a deterministic plan without file, network, or process I/O."""
    if not _valid_rule_map(rules):
        return _plan(value, "manual-review", (), "rule.ambiguous")
    if not isinstance(value.selector_version, str):
        return _plan(value, "manual-review", (), "metadata.malformed")
    if rules["selector_version"] != value.selector_version:
        return _plan(value, "manual-review", (), "rule.version-unsupported")
    if not isinstance(value.repository, str):
        return _plan(value, "manual-review", (), "metadata.malformed")
    if value.repository != rules["repository"]:
        return _plan(value, "manual-review", (), "identity.repository-mismatch")
    if (
        not isinstance(value.pull_request, int)
        or isinstance(value.pull_request, bool)
        or value.pull_request <= 0
    ):
        return _plan(value, "manual-review", (), "metadata.malformed")
    if not isinstance(value.base_sha, str) or not _SHA.fullmatch(value.base_sha):
        return _plan(value, "manual-review", (), "identity.base-sha-missing")
    if not isinstance(value.head_sha, str) or not _SHA.fullmatch(value.head_sha):
        return _plan(value, "manual-review", (), "identity.head-sha-missing")
    if not isinstance(value.changed_files, (tuple, list)) or any(
        not isinstance(path, str) for path in value.changed_files
    ):
        return _plan(value, "manual-review", (), "metadata.malformed")

    paths = tuple(
        sorted(
            {
                path.strip().replace("\\", "/").removeprefix("./")
                for path in value.changed_files
                if path.strip()
            }
        )
    )
    if not paths:
        return _plan(value, "manual-review", (), "metadata.empty-changed-files")

    aggregate_paths = set(rules["aggregate_paths"])
    aggregate_prefixes = tuple(rules["aggregate_prefixes"])
    if any(path in aggregate_paths or path.startswith(aggregate_prefixes) for path in paths):
        commands = (rules["aggregate_command"],)
        return _plan(value, "aggregate", commands, "profile.aggregate-configuration")

    doc_prefixes = tuple(rules["documentation_prefixes"])
    doc_suffixes = tuple(rules["documentation_suffixes"])
    if all(path.startswith(doc_prefixes) and path.endswith(doc_suffixes) for path in paths):
        return _plan(value, "static", (), "profile.documentation-static")

    matched_commands: list[str] = []
    matched_rules: set[str] = set()
    covered: set[str] = set()
    for rule in rules["focused_rules"]:
        prefixes = tuple(rule["prefixes"])
        for path in paths:
            if path.startswith(prefixes):
                covered.add(path)
                matched_rules.add(rule["name"])
                matched_commands.extend(rule["commands"])
    if matched_commands and len(covered) == len(paths):
        commands = tuple(sorted(set(matched_commands)))
        reason = (
            "profile.focused-package"
            if len(matched_rules) == 1
            else "profile.focused-union"
        )
        return _plan(value, "focused", commands, reason)

    executable = (".py", ".sh", ".yml", ".yaml", ".toml", ".json")
    if any(path.endswith(executable) for path in paths):
        return _plan(
            value,
            "aggregate",
            (rules["aggregate_command"],),
            "profile.aggregate-unmapped-executable",
        )
    return _plan(value, "manual-review", (), "rule.ambiguous")
