from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .models import SelectionInput, ValidationPlan

_RULES = Path(__file__).with_name("validation_profiles.yml")
_SHA = re.compile(r"^[0-9a-f]{40}$")


def load_rule_map(path: Path | None = None) -> dict[str, Any]:
    data = json.loads((path or _RULES).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("rule map must be an object")
    return data


def _digest(version: str, commands: tuple[str, ...]) -> str:
    raw = json.dumps([version, commands], separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _plan(value: SelectionInput, profile: str, commands: tuple[str, ...], reason: str) -> ValidationPlan:
    return ValidationPlan(
        selector_version=value.selector_version,
        repository=value.repository,
        pull_request=value.pull_request,
        base_sha=value.base_sha,
        head_sha=value.head_sha,
        profile=profile,
        commands=commands,
        command_set_digest=_digest(value.selector_version, commands) if profile != "manual-review" else "unavailable",
        reason_codes=(reason,),
        remote_build_required=profile in {"focused", "aggregate"},
    )


def select_validation_plan(value: SelectionInput, rules: dict[str, Any] | None = None) -> ValidationPlan:
    rules = rules or load_rule_map()
    if rules.get("selector_version") != value.selector_version:
        return _plan(value, "manual-review", (), "rule.version-unsupported")
    if value.repository != rules.get("repository"):
        return _plan(value, "manual-review", (), "identity.repository-mismatch")
    if value.pull_request <= 0:
        return _plan(value, "manual-review", (), "metadata.malformed")
    if not _SHA.fullmatch(value.base_sha):
        return _plan(value, "manual-review", (), "identity.base-sha-missing")
    if not _SHA.fullmatch(value.head_sha):
        return _plan(value, "manual-review", (), "identity.head-sha-missing")

    paths = tuple(sorted({p.strip().replace("\\", "/").removeprefix("./") for p in value.changed_files if p.strip()}))
    if not paths:
        return _plan(value, "manual-review", (), "metadata.empty-changed-files")

    aggregate_paths = set(rules["aggregate_paths"])
    aggregate_prefixes = tuple(rules["aggregate_prefixes"])
    if any(p in aggregate_paths or p.startswith(aggregate_prefixes) for p in paths):
        command = (rules["aggregate_command"],)
        return _plan(value, "aggregate", command, "profile.aggregate-configuration")

    doc_prefixes = tuple(rules["documentation_prefixes"])
    doc_suffixes = tuple(rules["documentation_suffixes"])
    if all(p.startswith(doc_prefixes) and p.endswith(doc_suffixes) for p in paths):
        return _plan(value, "static", (), "profile.documentation-static")

    matches = []
    covered = set()
    for rule in rules["focused_rules"]:
        prefixes = tuple(rule["prefixes"])
        for path in paths:
            if path.startswith(prefixes):
                covered.add(path)
                matches.extend(rule["commands"])
    if matches and len(covered) == len(paths):
        commands = tuple(sorted(set(matches)))
        reason = "profile.focused-package" if len(commands) == 1 else "profile.focused-union"
        return _plan(value, "focused", commands, reason)

    executable = (".py", ".sh", ".yml", ".yaml", ".toml", ".json")
    if any(p.endswith(executable) for p in paths):
        return _plan(value, "aggregate", (rules["aggregate_command"],), "profile.aggregate-unmapped-executable")
    return _plan(value, "manual-review", (), "rule.ambiguous")
