from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .models import SelectionInput, ValidationPlan, ValidationProfile

_RULES = Path(__file__).with_name("validation_profiles.yml")
_SHA = re.compile(r"^[0-9a-f]{40}$")


def load_rule_map(path: Path | None = None) -> dict[str, Any]:
    """Load rules at the caller boundary; selection itself remains pure."""
    data = json.loads((path or _RULES).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("rule map must be an object")
    return data


def _digest(version: str, commands: tuple[str, ...]) -> str:
    raw = json.dumps([version, commands], separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


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
            _digest(version, commands) if profile != "manual-review" else "unavailable"
        ),
        reason_codes=(reason,),
        remote_build_required=profile in {"focused", "aggregate"},
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
