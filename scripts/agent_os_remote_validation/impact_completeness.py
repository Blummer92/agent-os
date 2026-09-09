from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Literal, Mapping

MAX_IMPACT_REASONS = 64
MAX_IMPACT_FAMILIES = 64
MAX_IMPACT_SERIALIZED_BYTES = 131_072

ImpactStatus = Literal["complete", "incomplete", "manual-review", "not-applicable"]


@dataclass(frozen=True, slots=True, kw_only=True)
class ImpactCouplingRule:
    """One finite repository-owned coupling family.

    `trigger_paths` are canonical surfaces whose change activates the rule.
    `required_companion_paths` are exact paths or directory prefixes (ending in /)
    that must move in the same candidate when the trigger moves.
    `forbidden_tokens` are retired interfaces that must be absent from the bounded
    `scan_prefixes` snapshot after a migration. No semantic inference is performed.
    """

    name: str
    trigger_paths: tuple[str, ...]
    required_companion_paths: tuple[str, ...] = ()
    scan_prefixes: tuple[str, ...] = ()
    forbidden_tokens: tuple[str, ...] = ()
    ambiguous: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class ImpactCompletenessResult:
    status: ImpactStatus
    result_id: str
    applicable_families: tuple[str, ...]
    incomplete_families: tuple[str, ...]
    reason_codes: tuple[str, ...]
    aggregate_escalation_required: bool
    authoritative: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


def evaluate_impact_completeness(
    *,
    changed_files: object,
    rules: object,
    repository_text: object | None = None,
) -> ImpactCompletenessResult:
    """Evaluate finite changed-surface coupling obligations without I/O.

    This is deliberately cheaper and narrower than behavioral validation. Callers
    supply already-read text only for bounded token-scan families; this function
    performs no filesystem, network, provider, model, or process calls.
    """
    if not _valid_changed_files(changed_files) or not _valid_rules(rules):
        return _result(
            "manual-review",
            (),
            (),
            ("impact.input-invalid",),
            aggregate=True,
        )

    changed = tuple(sorted(set(changed_files)))
    text = repository_text if isinstance(repository_text, Mapping) else {}
    applicable: list[str] = []
    incomplete: list[str] = []
    reasons: set[str] = set()
    manual = False

    for rule in sorted(rules, key=lambda item: item.name):
        if not any(_path_matches(path, rule.trigger_paths) for path in changed):
            continue
        applicable.append(rule.name)
        if rule.ambiguous:
            manual = True
            reasons.add(f"impact.{rule.name}.manual-review")
            continue

        missing_companions = tuple(
            required
            for required in rule.required_companion_paths
            if not any(_path_matches(path, (required,)) for path in changed)
        )
        if missing_companions:
            incomplete.append(rule.name)
            reasons.add(f"impact.{rule.name}.companion-missing")

        if rule.forbidden_tokens:
            bounded_paths = tuple(
                sorted(
                    path
                    for path in text
                    if isinstance(path, str)
                    and any(path.startswith(prefix) for prefix in rule.scan_prefixes)
                )
            )
            if not bounded_paths:
                incomplete.append(rule.name)
                reasons.add(f"impact.{rule.name}.scan-evidence-missing")
            else:
                for path in bounded_paths:
                    content = text.get(path)
                    if not isinstance(content, str):
                        incomplete.append(rule.name)
                        reasons.add(f"impact.{rule.name}.scan-evidence-invalid")
                        break
                    if any(token in content for token in rule.forbidden_tokens):
                        incomplete.append(rule.name)
                        reasons.add(f"impact.{rule.name}.retired-interface-present")
                        break

    applicable_tuple = tuple(sorted(set(applicable)))[:MAX_IMPACT_FAMILIES]
    incomplete_tuple = tuple(sorted(set(incomplete)))[:MAX_IMPACT_FAMILIES]
    if manual:
        return _result(
            "manual-review",
            applicable_tuple,
            incomplete_tuple,
            tuple(sorted(reasons)),
            aggregate=True,
        )
    if incomplete_tuple:
        return _result(
            "incomplete",
            applicable_tuple,
            incomplete_tuple,
            tuple(sorted(reasons)),
            aggregate=True,
        )
    if applicable_tuple:
        return _result(
            "complete",
            applicable_tuple,
            (),
            ("impact.complete",),
            aggregate=False,
        )
    return _result(
        "not-applicable",
        (),
        (),
        ("impact.not-applicable",),
        aggregate=False,
    )


def serialize_impact_completeness(result: ImpactCompletenessResult) -> dict[str, object]:
    if not isinstance(result, ImpactCompletenessResult):
        raise TypeError("result must be ImpactCompletenessResult")
    payload = _payload(result)
    expected = "impact-completeness:" + _digest(payload)
    if result.result_id != expected:
        raise ValueError("impact completeness result ID mismatch")
    serialized = dict(payload)
    serialized["result_id"] = result.result_id
    encoded = json.dumps(serialized, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > MAX_IMPACT_SERIALIZED_BYTES:
        raise ValueError("impact completeness result exceeds size limit")
    return serialized


def impact_completeness_result_id(result: ImpactCompletenessResult) -> str:
    return str(serialize_impact_completeness(result)["result_id"])


def _valid_changed_files(value: object) -> bool:
    return (
        isinstance(value, tuple)
        and bool(value)
        and all(isinstance(path, str) and bool(path) for path in value)
    )


def _valid_rules(value: object) -> bool:
    if not isinstance(value, tuple) or len(value) > MAX_IMPACT_FAMILIES:
        return False
    names: set[str] = set()
    for rule in value:
        if not isinstance(rule, ImpactCouplingRule) or not rule.name or rule.name in names:
            return False
        names.add(rule.name)
        if not rule.trigger_paths:
            return False
        for group in (
            rule.trigger_paths,
            rule.required_companion_paths,
            rule.scan_prefixes,
            rule.forbidden_tokens,
        ):
            if not isinstance(group, tuple) or any(
                not isinstance(item, str) or not item for item in group
            ):
                return False
        if bool(rule.scan_prefixes) != bool(rule.forbidden_tokens):
            return False
    return True


def _path_matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(path.startswith(pattern) if pattern.endswith("/") else path == pattern for pattern in patterns)


def _result(
    status: ImpactStatus,
    applicable: tuple[str, ...],
    incomplete: tuple[str, ...],
    reasons: tuple[str, ...],
    *,
    aggregate: bool,
) -> ImpactCompletenessResult:
    preliminary = ImpactCompletenessResult(
        status=status,
        result_id="",
        applicable_families=applicable,
        incomplete_families=incomplete,
        reason_codes=tuple(sorted(set(reasons)))[:MAX_IMPACT_REASONS],
        aggregate_escalation_required=aggregate,
    )
    return replace(
        preliminary,
        result_id="impact-completeness:" + _digest(_payload(preliminary)),
    )


def _payload(result: ImpactCompletenessResult) -> dict[str, object]:
    return {
        "status": result.status,
        "applicable_families": list(result.applicable_families),
        "incomplete_families": list(result.incomplete_families),
        "reason_codes": list(result.reason_codes),
        "aggregate_escalation_required": result.aggregate_escalation_required,
        "authoritative": False,
        "execution_authorized": False,
        "merge_authorized": False,
        "side_effects_performed": False,
    }


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(b"agent-os-impact-completeness:v1\0" + encoded).hexdigest()
