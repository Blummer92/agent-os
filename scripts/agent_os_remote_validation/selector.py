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
    MAX_PRE_PR_SERIALIZED_BYTES,
    PRE_PR_BASE_BRANCH,
    PRE_PR_CANDIDATE_ISSUE_NUMBER,
    PRE_PR_EXECUTION_MODE,
    PRE_PR_PER_COMMAND_TIMEOUT_SECONDS,
    PRE_PR_PROFILE,
    PRE_PR_REPOSITORY,
    PRE_PR_TOTAL_VALIDATION_TIMEOUT_SECONDS,
    PRE_PR_VALIDATION_PLAN_SCHEMA_NAME,
    PRE_PR_VALIDATION_PLAN_SCHEMA_VERSION,
    PRE_PR_VALIDATION_SUBJECT_SCHEMA_NAME,
    PRE_PR_VALIDATION_SUBJECT_SCHEMA_VERSION,
    PROTECTED_PRE_PR_REFS,
    VALIDATION_PLAN_SCHEMA_NAME,
    VALIDATION_PLAN_SCHEMA_VERSION,
    PrePrValidationPlan,
    PrePrValidationSubject,
    SelectionInput,
    ValidationPlan,
    ValidationProfile,
)

_RULES = Path(__file__).with_name("validation_profiles.yml")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SELECTOR_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_PRE_PR_SELECTOR_VERSION = "1.0.0"
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


def _usable_string_list(value: object) -> bool:
    return _string_list(value) and all(_bounded_text(item) for item in value)


def _valid_focused_rule_map(rules: object) -> bool:
    """Validate rule-map structure, independent of command-coverage metadata.

    Pre-PR planning never applies subsumption (frozen command bindings stay
    exact), so its rule-map validity must not depend on `command_coverage`
    remaining in sync with whatever focused-rule commands a caller supplies.
    """
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
        prefixes = rule.get("prefixes", [])
        exact_paths = rule.get("exact_paths", [])
        if not _usable_string_list(prefixes):
            return False
        if not _usable_string_list(exact_paths):
            return False
        if not prefixes and not exact_paths:
            return False
        if not _string_list(rule.get("commands")):
            return False
    return True


def _valid_rule_map(rules: object) -> bool:
    """Validate rule-map structure plus command-coverage metadata.

    Used only by positive-PR selection, which is the sole consumer of
    coverage-driven subsumption.
    """
    if not _valid_focused_rule_map(rules):
        return False
    if not _valid_command_coverage(
        rules.get("command_coverage", []), rules["focused_rules"]
    ):
        return False
    return True


def _registered_commands(focused_rules: list[Any]) -> set[str]:
    registered: set[str] = set()
    for rule in focused_rules:
        registered.update(rule.get("commands", []))
    return registered


def _valid_command_coverage(coverage: object, focused_rules: list[Any]) -> bool:
    """Validate explicit coverage declarations fail-closed; no inference allowed.

    Rejects duplicate declarations, unknown commands, self-subsumption,
    cycles, malformed command lists, and ambiguous conflicting coverage
    (a narrow command claimed by more than one broader command).
    """
    if not isinstance(coverage, list):
        return False
    registered = _registered_commands(focused_rules)
    declared_broader: set[str] = set()
    narrow_to_broader: dict[str, str] = {}
    for entry in coverage:
        if not isinstance(entry, dict):
            return False
        broader = entry.get("broader")
        subsumes = entry.get("subsumes")
        if not isinstance(broader, str) or broader not in registered:
            return False
        if not _string_list(subsumes) or not subsumes:
            return False
        if broader in declared_broader:
            return False
        declared_broader.add(broader)
        seen_in_entry: set[str] = set()
        for narrow in subsumes:
            if narrow not in registered:
                return False
            if narrow == broader:
                return False
            if narrow in seen_in_entry:
                return False
            seen_in_entry.add(narrow)
            if narrow in narrow_to_broader:
                return False
            narrow_to_broader[narrow] = broader
    for start in narrow_to_broader:
        current = start
        visited: set[str] = set()
        while current in narrow_to_broader:
            current = narrow_to_broader[current]
            if current == start or current in visited:
                return False
            visited.add(current)
    return True


def _coverage_map(rules: dict[str, Any]) -> dict[str, str]:
    """Return the validated narrow-command -> broader-command coverage map."""
    narrow_to_broader: dict[str, str] = {}
    for entry in rules.get("command_coverage", []):
        broader = entry["broader"]
        for narrow in entry["subsumes"]:
            narrow_to_broader[narrow] = broader
    return narrow_to_broader


def _apply_subsumption(
    commands: tuple[str, ...], narrow_to_broader: dict[str, str]
) -> tuple[str, ...]:
    """Suppress commands whose declared broader command is also selected.

    Pure and deterministic: the result of this fixed-point closure does not
    depend on dict iteration order, since removing a covered command never
    changes whether another command's declared broader command is present.
    """
    remaining = set(commands)
    changed = True
    while changed:
        changed = False
        for narrow, broader in narrow_to_broader.items():
            if narrow in remaining and broader in remaining:
                remaining.discard(narrow)
                changed = True
    return tuple(sorted(remaining))


def _focused_matches(
    path: str,
    focused_rules: list[Any],
) -> list[tuple[str, tuple[str, ...]]]:
    """Return focused owners of one path; an exact owner excludes prefix owners.

    Exact ownership intentionally outranks and masks every prefix owner of the
    same path. Selection remains independent of rule and changed-file order.
    """
    exact_matches: list[tuple[str, tuple[str, ...]]] = []
    prefix_matches: list[tuple[str, tuple[str, ...]]] = []
    for rule in focused_rules:
        owner = (rule["name"], tuple(rule["commands"]))
        prefixes = tuple(rule.get("prefixes", []))
        if path in frozenset(rule.get("exact_paths", [])):
            exact_matches.append(owner)
        elif prefixes and path.startswith(prefixes):
            prefix_matches.append(owner)
    return exact_matches or prefix_matches


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
    for path in paths:
        if path.startswith(doc_prefixes) and path.endswith(doc_suffixes):
            covered.add(path)
            continue
        path_matches = _focused_matches(path, rules["focused_rules"])
        distinct_command_sets = {commands for _, commands in path_matches}
        if len(distinct_command_sets) > 1:
            return _plan(value, "manual-review", (), "rule.ambiguous")
        if path_matches:
            covered.add(path)
            matched_rules.update(name for name, _ in path_matches)
            matched_commands.extend(path_matches[0][1])
    if matched_commands and len(covered) == len(paths):
        commands = _apply_subsumption(
            tuple(sorted(set(matched_commands))), _coverage_map(rules)
        )
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


def _verify_pre_pr_subject(subject: object) -> PrePrValidationSubject:
    """Re-verify one supplied pre-PR subject's frozen bindings before planning."""
    if type(subject) is not PrePrValidationSubject:
        raise TypeError("subject must be an exact PrePrValidationSubject")
    if subject.schema_name != PRE_PR_VALIDATION_SUBJECT_SCHEMA_NAME:
        raise ValueError("pre-PR subject schema name drift")
    if subject.schema_version != PRE_PR_VALIDATION_SUBJECT_SCHEMA_VERSION:
        raise ValueError("pre-PR subject schema version drift")
    if type(subject.candidate_bound) is not bool:
        raise ValueError("pre-PR candidate-bound mode drift")
    if subject.candidate_bound:
        if (
            not _bounded_text(subject.repository)
            or subject.repository.count("/") != 1
            or any(not part for part in subject.repository.split("/"))
        ):
            raise ValueError("pre-PR repository drift")
        if (
            not isinstance(subject.issue_number, int)
            or isinstance(subject.issue_number, bool)
            or subject.issue_number <= 0
        ):
            raise ValueError("pre-PR issue identity drift")
        if not _bounded_text(subject.base_branch):
            raise ValueError("pre-PR base branch drift")
        if not _bounded_text(subject.execution_mode):
            raise ValueError("pre-PR execution mode mismatch")
    else:
        if subject.repository != PRE_PR_REPOSITORY:
            raise ValueError("pre-PR repository drift")
        if subject.issue_number != PRE_PR_CANDIDATE_ISSUE_NUMBER:
            raise ValueError("pre-PR issue identity drift")
        if subject.base_branch != PRE_PR_BASE_BRANCH:
            raise ValueError("pre-PR base branch drift")
        if subject.execution_mode != PRE_PR_EXECUTION_MODE:
            raise ValueError("pre-PR execution mode mismatch")
    if (
        subject.branch.casefold() in PROTECTED_PRE_PR_REFS
        or subject.branch == subject.base_branch
    ):
        raise ValueError("pre-PR branch drift")
    if (
        not _SHA.fullmatch(subject.base_sha)
        or not _SHA.fullmatch(subject.expected_source_sha)
        or not _SHA.fullmatch(subject.tested_sha)
    ):
        raise ValueError("pre-PR SHA drift")
    if not subject.candidate_bound and subject.tested_sha != subject.expected_source_sha:
        raise ValueError("pre-PR tested SHA drift")
    if type(subject.expected_changed_paths) is not tuple:
        raise ValueError("pre-PR expected changed paths drift")
    if subject.expected_changed_paths and (
        not subject.candidate_bound
        or tuple(sorted(set(subject.expected_changed_paths))) != subject.expected_changed_paths
        or any(
            not isinstance(path, str)
            or not path
            or path not in subject.allowed_files
            for path in subject.expected_changed_paths
        )
    ):
        raise ValueError("pre-PR expected changed paths drift")
    return subject


def select_pre_pr_validation_plan(
    subject: object,
    rules: dict[str, Any],
) -> PrePrValidationPlan:
    """Return one deterministic pre-PR plan without file, network, or process I/O.

    Unlike positive-PR selection, an unusable rule map, uncovered path, ambiguous
    owner, aggregate fallback, or command-identity drift fails closed by raising
    instead of degrading to a manual-review plan.
    """
    value = _verify_pre_pr_subject(subject)
    if not _valid_focused_rule_map(rules):
        raise ValueError("pre-PR rule map is not usable")
    selector_version = rules["selector_version"]
    if not _SELECTOR_VERSION.fullmatch(selector_version):
        raise ValueError("pre-PR selector version is unsupported")
    if rules["repository"] != value.repository:
        raise ValueError("pre-PR repository drift")

    aggregate_paths = frozenset(rules["aggregate_paths"])
    aggregate_prefixes = tuple(rules["aggregate_prefixes"])
    matched_rules: set[str] = set()
    matched_commands: set[str] = set()
    for path in value.allowed_files:
        if path in aggregate_paths or path.startswith(aggregate_prefixes):
            raise ValueError("pre-PR scope requires focused coverage")
        path_matches = _focused_matches(path, rules["focused_rules"])
        if not path_matches:
            raise ValueError("pre-PR scope has partial focused coverage")
        if len({commands for _, commands in path_matches}) > 1:
            raise ValueError("pre-PR scope has ambiguous focused coverage")
        matched_rules.update(name for name, _ in path_matches)
        matched_commands.update(path_matches[0][1])

    if matched_commands != set(value.required_command_identities):
        raise ValueError("pre-PR command identity drift")
    commands = value.required_command_identities
    reason = (
        "profile.focused-package" if len(matched_rules) == 1 else "profile.focused-union"
    )
    return PrePrValidationPlan(
        selector_version=selector_version,
        subject=value,
        commands=commands,
        command_set_digest=compute_command_set_digest(selector_version, commands),
        reason_codes=(reason,),
    )


def serialize_pre_pr_validation_subject(subject: object) -> dict[str, object]:
    """Return deterministic canonical JSON-compatible pre-PR subject data."""
    value = _verify_pre_pr_subject(subject)
    payload: dict[str, object] = {
        "schema_name": value.schema_name,
        "schema_version": value.schema_version,
        "repository": value.repository,
        "issue_number": value.issue_number,
        "invocation_id": value.invocation_id,
        "base_branch": value.base_branch,
        "base_sha": value.base_sha,
        "branch": value.branch,
        "expected_source_sha": value.expected_source_sha,
        "tested_sha": value.tested_sha,
        "allowed_files": list(value.allowed_files),
        "forbidden_paths": list(value.forbidden_paths),
        "required_command_identities": list(value.required_command_identities),
        "approval_id": value.approval_id,
        "approval_revision": value.approval_revision,
        "projection_id": value.projection_id,
        "implementation_contract_fingerprint": value.implementation_contract_fingerprint,
        "execution_mode": value.execution_mode,
    }
    if value.candidate_bound:
        payload["candidate_bound"] = True
    if value.expected_changed_paths:
        payload["expected_changed_paths"] = list(value.expected_changed_paths)
    return payload


def deserialize_pre_pr_validation_subject(payload: object) -> PrePrValidationSubject:
    """Reconstruct one canonical pre-PR subject and rerun constructor invariants."""
    if type(payload) is not dict:
        raise TypeError("payload must be an exact dictionary")
    candidate_bound = payload.get("candidate_bound", False)
    if "candidate_bound" in payload and candidate_bound is not True:
        raise TypeError("candidate_bound must be exactly true when present")
    serialized_fields = {
        "schema_name",
        "schema_version",
        "repository",
        "issue_number",
        "invocation_id",
        "base_branch",
        "base_sha",
        "branch",
        "expected_source_sha",
        "tested_sha",
        "allowed_files",
        "forbidden_paths",
        "required_command_identities",
        "approval_id",
        "approval_revision",
        "projection_id",
        "implementation_contract_fingerprint",
        "execution_mode",
    }
    expected_fields = serialized_fields | ({"candidate_bound"} if candidate_bound else set())
    if "expected_changed_paths" in payload:
        expected_fields.add("expected_changed_paths")
    if set(payload) != expected_fields:
        raise ValueError("pre-PR subject payload fields drift")
    tuple_fields = {
        "allowed_files",
        "forbidden_paths",
        "required_command_identities",
        "expected_changed_paths",
    }
    values: dict[str, object] = {}
    for key, value in payload.items():
        if key == "candidate_bound":
            continue
        values[key] = tuple(value) if key in tuple_fields and type(value) is list else value
    values["candidate_bound"] = candidate_bound
    return PrePrValidationSubject(**values)  # type: ignore[arg-type]


def pre_pr_validation_subject_id(subject: object) -> str:
    """Return a domain-separated semantic identity for one valid pre-PR subject."""
    canonical = _canonical_bytes(serialize_pre_pr_validation_subject(subject))
    digest = hashlib.sha256(
        b"agent-os-pre-pr-validation-subject:v1\0" + canonical
    ).hexdigest()
    return f"pre-pr-validation-subject:{digest}"


def serialize_pre_pr_validation_plan(plan: object) -> dict[str, object]:
    """Return deterministic canonical JSON-compatible pre-PR plan data."""
    if type(plan) is not PrePrValidationPlan:
        raise TypeError("plan must be an exact PrePrValidationPlan")
    if plan.schema_name != PRE_PR_VALIDATION_PLAN_SCHEMA_NAME:
        raise ValueError("invalid pre-PR validation plan: schema name drift")
    if plan.schema_version != PRE_PR_VALIDATION_PLAN_SCHEMA_VERSION:
        raise ValueError("invalid pre-PR validation plan: schema version drift")
    if plan.profile != PRE_PR_PROFILE:
        raise ValueError("invalid pre-PR validation plan: profile drift")
    subject = _verify_pre_pr_subject(plan.subject)
    if plan.commands != subject.required_command_identities:
        raise ValueError("invalid pre-PR validation plan: command identity drift")
    if plan.command_set_digest != compute_command_set_digest(
        plan.selector_version, plan.commands
    ):
        raise ValueError("invalid pre-PR validation plan: command digest drift")
    if any(
        reason not in _PROFILE_REASONS[PRE_PR_PROFILE] for reason in plan.reason_codes
    ):
        raise ValueError("invalid pre-PR validation plan: reason code drift")
    if (
        plan.per_command_timeout_seconds > PRE_PR_PER_COMMAND_TIMEOUT_SECONDS
        or plan.total_validation_timeout_seconds > PRE_PR_TOTAL_VALIDATION_TIMEOUT_SECONDS
    ):
        raise ValueError("invalid pre-PR validation plan: timeout ceiling exceeded")
    if (
        plan.remote_build_required is not False
        or plan.execution_authorized is not False
        or plan.merge_authorized is not False
        or plan.side_effects_performed is not False
    ):
        raise ValueError("invalid pre-PR validation plan: non-authorizing invariant broken")

    payload: dict[str, object] = {
        "schema_name": plan.schema_name,
        "schema_version": plan.schema_version,
        "selector_version": plan.selector_version,
        "subject": serialize_pre_pr_validation_subject(subject),
        "subject_id": pre_pr_validation_subject_id(subject),
        "profile": plan.profile,
        "commands": list(plan.commands),
        "command_set_digest": plan.command_set_digest,
        "reason_codes": list(plan.reason_codes),
        "per_command_timeout_seconds": plan.per_command_timeout_seconds,
        "total_validation_timeout_seconds": plan.total_validation_timeout_seconds,
        "remote_build_required": False,
        "execution_authorized": False,
        "merge_authorized": False,
        "side_effects_performed": False,
    }
    if len(_canonical_bytes(payload)) > MAX_PRE_PR_SERIALIZED_BYTES:
        raise ValueError("pre-PR validation plan exceeds canonical size limit")
    return payload


def deserialize_pre_pr_validation_plan(payload: object) -> PrePrValidationPlan:
    """Reconstruct one canonical pre-PR plan without runtime or repository I/O."""
    if type(payload) is not dict:
        raise TypeError("payload must be an exact dictionary")
    expected_fields = {
        "schema_name",
        "schema_version",
        "selector_version",
        "subject",
        "subject_id",
        "profile",
        "commands",
        "command_set_digest",
        "reason_codes",
        "per_command_timeout_seconds",
        "total_validation_timeout_seconds",
        "remote_build_required",
        "execution_authorized",
        "merge_authorized",
        "side_effects_performed",
    }
    if set(payload) != expected_fields:
        raise ValueError("pre-PR validation plan payload fields drift")
    if payload["selector_version"] != _PRE_PR_SELECTOR_VERSION:
        raise ValueError("pre-PR selector version is unsupported")
    for field in (
        "remote_build_required",
        "execution_authorized",
        "merge_authorized",
        "side_effects_performed",
    ):
        if payload[field] is not False:
            raise ValueError("pre-PR validation plan non-authority drift")
    if type(payload["commands"]) is not list:
        raise TypeError("commands must be an exact array")
    if type(payload["reason_codes"]) is not list:
        raise TypeError("reason_codes must be an exact array")

    subject = deserialize_pre_pr_validation_subject(payload["subject"])
    if payload["subject_id"] != pre_pr_validation_subject_id(subject):
        raise ValueError("pre-PR validation plan subject identity drift")

    plan = PrePrValidationPlan(
        schema_name=payload["schema_name"],
        schema_version=payload["schema_version"],
        selector_version=payload["selector_version"],
        subject=subject,
        profile=payload["profile"],
        commands=tuple(payload["commands"]),
        command_set_digest=payload["command_set_digest"],
        reason_codes=tuple(payload["reason_codes"]),
        per_command_timeout_seconds=payload["per_command_timeout_seconds"],
        total_validation_timeout_seconds=payload["total_validation_timeout_seconds"],
    )  # type: ignore[arg-type]
    if serialize_pre_pr_validation_plan(plan) != payload:
        raise ValueError("pre-PR validation plan payload is not canonical")
    pre_pr_validation_plan_id(plan)
    return plan


def pre_pr_validation_plan_id(plan: object) -> str:
    """Return a domain-separated semantic identity for one valid pre-PR plan."""
    canonical = _canonical_bytes(serialize_pre_pr_validation_plan(plan))
    digest = hashlib.sha256(b"agent-os-pre-pr-validation-plan:v1\0" + canonical).hexdigest()
    return f"pre-pr-validation-plan:{digest}"


def _canonical_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")