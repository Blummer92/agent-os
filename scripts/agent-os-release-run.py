#!/usr/bin/env python3
"""Compatibility entrypoint for the read-only release evaluator.

Closure authority comes only from the canonical lifecycle guard and its
content-bound records. The CLI exits 0 for READY_FOR_MERGE_AUTHORIZATION
or COMPLETED, 1 for BLOCKED/NEEDS_FIX, and 2 for unreadable/invalid input.
An exit of 0 is not itself permission to mutate anything.
"""
import argparse as _argparse
import json as _json
import re as _re
import types as _types
import typing as _typing
from dataclasses import MISSING as _MISSING, asdict as _asdict, fields as _fields
from dataclasses import is_dataclass as _is_dataclass
from datetime import date as _date, datetime as _datetime
from enum import Enum as _Enum
from functools import lru_cache as _cache


# Freeze the domain API, not the incidental stdlib names leaked by import *.
_CORE_EXPORTS = (
    "SCHEMA_NAME", "SCHEMA_VERSION", "CLASSIFICATIONS", "SUCCESS_CHECKS",
    "MERGE_METHODS", "BRANCH_STATES", "PR_LIFECYCLE_STATES",
    "REQUIRED_REFRESH_INVALIDATIONS", "ReleaseRunState", "EvidenceState",
    "RequirementResult", "ValidationFailureClassification", "ValidationFailureEvidence",
    "classify_validation_failure",
)
_GUARD_EXPORTS = (
    "AdmissionStatus", "LifecycleMutationAuthorization", "LifecycleStateSnapshot",
    "evaluate_lifecycle_mutation",
)
__all__ = (*_CORE_EXPORTS, *_GUARD_EXPORTS, "evaluate_release_run", "main")


@_cache(maxsize=1)
def _core():
    # The read-only legacy core changes sys.path when its directory is absent.
    # Defer loading it so simply importing the compatibility wrapper is inert.
    # Use one qualified module name in both the CLI and library processes.
    from scripts import agent_os_release_run_core as module
    return module


@_cache(maxsize=1)
def _guard():
    from scripts.agent_os_issue_acceptance import lifecycle_mutation_guard as module
    return module


def __getattr__(name):
    if name in _CORE_EXPORTS:
        return getattr(_core(), name)
    if name in _GUARD_EXPORTS:
        return getattr(_guard(), name)
    raise AttributeError(name)


def __dir__():
    return sorted(set(globals()) | set(__all__))


@_cache(maxsize=32)
def _hints(cls):
    try:
        return _typing.get_type_hints(cls)
    except NameError:
        raise ValueError("unresolvable field annotation") from None


def _copy_native(value, depth=0):
    """Detach bounded-depth JSON containers without invoking copy hooks."""
    if depth > 64:
        raise ValueError("evidence nesting exceeds limit")
    kind = type(value)
    if value is None or kind in (str, int, float, bool):
        return value
    if kind is dict and all(type(key) is str for key in value):
        return {key: _copy_native(item, depth + 1) for key, item in value.items()}
    if kind is list:
        return [_copy_native(item, depth + 1) for item in value]
    if kind is tuple:
        return tuple(_copy_native(item, depth + 1) for item in value)
    raise TypeError("evidence must contain only native JSON values or tuples")


def _coerce(hint, value, name):
    origin, args = _typing.get_origin(hint), _typing.get_args(hint)
    if hint is _typing.Any:
        return _copy_native(value)
    if origin in (_typing.Union, _types.UnionType):
        # Preserve an explicitly allowed native container before JSON coercion.
        candidates = sorted(args, key=lambda variant: (
            (_typing.get_origin(variant) or variant) is not type(value)
        ))
        for variant in candidates:
            try:
                return _coerce(variant, value, name)
            except (TypeError, ValueError):
                continue
        raise TypeError(f"{name} does not match its declared union")
    if origin is _typing.Literal:
        if any(type(value) is type(item) and value == item for item in args):
            return value
    elif origin is tuple and type(value) in (list, tuple):
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_coerce(args[0], item, name) for item in value)
        if len(value) == len(args):
            return tuple(_coerce(part, item, name) for part, item in zip(args, value))
    elif origin is list and type(value) is list:
        return [_coerce(args[0], item, name) for item in value]
    elif origin is dict and type(value) is dict:
        return {_coerce(args[0], key, name): _coerce(args[1], item, name)
                for key, item in value.items()}
    elif isinstance(hint, type) and _is_dataclass(hint):
        return _construct_exact(hint, value, name)
    elif type(value) is hint:
        return _copy_native(value)
    raise TypeError(f"{name} has the wrong type or shape")


def _construct_exact(cls, raw, name):
    if type(raw) is not dict:
        raise TypeError(f"{name} must be an object")
    allowed = {item.name: item for item in _fields(cls) if item.init}
    if raw.keys() - allowed.keys():
        # Reject rather than exposing untrusted field names or accepting init=False.
        raise ValueError(f"{name} contains unsupported input fields")
    for key, item in allowed.items():
        if key not in raw and item.default is _MISSING and item.default_factory is _MISSING:
            raise ValueError(f"{name}.{key} is required")
    hints = _hints(cls)
    return cls(**{key: _coerce(hints[key], value, f"{name}.{key}")
                  for key, value in raw.items()})


_REPOSITORY = _re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_SHA = _re.compile(r"[0-9a-f]{40}")


def _repository(value):
    if type(value) is not str:
        return None
    value = value.strip()
    for prefix in ("https://github.com/", "http://github.com/"):
        if value.lower().startswith(prefix):
            value = value[len(prefix):].removesuffix("/")
            break
    if not _REPOSITORY.fullmatch(value) or any(p in (".", "..") for p in value.split("/")):
        return None
    return value


def _normalize_evidence(evidence):
    fields = {}
    for name in ("repository", "issue_number", "pull_request_number", "observed_head_sha", "issue_state"):
        value = evidence.get(name)
        if name == "repository":
            value = _repository(value)
        elif name in ("issue_number", "pull_request_number"):
            value = value if type(value) is int and value > 0 else None
        elif name == "observed_head_sha":
            value = value.strip().lower() if type(value) is str else None
            value = value if value and _SHA.fullmatch(value) else None
        else:
            value = value.strip().lower() if type(value) is str else None
            value = value if value in ("open", "closed") else None
        if value is None:
            return f"invalid-release-identity:{name}"
        fields[name] = value
    evidence.update(fields)
    for name in ("expected_head_sha", "validation_head_sha", "current_main_sha", "checkpoint_head_sha"):
        value = evidence.get(name)
        if type(value) is str and _SHA.fullmatch(value.strip().lower()):
            evidence[name] = value.strip().lower()
    return None


def _closure_admission(evidence):
    # Absent or null is intentionally unauthorizing (normal before the close).
    raw = evidence.get("issue_closure_lifecycle")
    if raw is None:
        return False, None
    if type(raw) is not dict or raw.keys() != {"authorization", "snapshot"}:
        return False, "invalid-closure-evidence:packet-shape"
    guard = _guard()
    try:
        authorization = _construct_exact(
            guard.LifecycleMutationAuthorization, raw["authorization"], "authorization")
        snapshot = _construct_exact(guard.LifecycleStateSnapshot, raw["snapshot"], "snapshot")
    except (TypeError, ValueError, OverflowError):
        return False, "invalid-closure-evidence:record-shape-or-digest"
    # Constructors support minting IDs for canonical producers. This consumer
    # must receive the already bound IDs, not create them from unproven input.
    if not all(raw[group].get(field) for group, field in (
        ("authorization", "authorization_id"),
        ("authorization", "authorization_revision"),
        ("snapshot", "snapshot_id"),
    )):
        return False, "invalid-closure-evidence:missing-content-binding"
    checks = (
        ("repository", snapshot.repository.casefold(), evidence["repository"].casefold()),
        ("issue_number", snapshot.issue_number, evidence["issue_number"]),
        ("pull_request_number", snapshot.pull_request_number, evidence["pull_request_number"]),
        ("observed_head_sha", snapshot.source_head, evidence["observed_head_sha"]),
        ("issue_state", snapshot.issue_state, evidence["issue_state"]),
    )
    for name, actual, expected in checks:
        if actual is None or expected is None or actual != expected:
            return False, f"closure-binding-mismatch:{name}"
    pr_state = evidence.get("pr_state")
    if pr_state in ("open", "merged") and snapshot.merged is not (pr_state == "merged"):
        return False, "closure-binding-mismatch:merged"
    pr_lifecycle_state = evidence.get("pr_lifecycle_state")
    if pr_lifecycle_state in ("draft", "ready") and snapshot.pr_state != pr_lifecycle_state:
        return False, "closure-binding-mismatch:pr_state"
    # Compare independent facts when supplied; current_main_sha is not
    # necessarily the PR's observed base head after merge.
    for name in ("base_head", "review_state", "unresolved_threads",
                 "lifecycle_labels", "observed_revision"):
        if name in evidence:
            expected = evidence[name]
            actual = getattr(snapshot, name)
            if name == "lifecycle_labels" and type(expected) in (list, tuple):
                expected = tuple(expected)
            if type(expected) is not type(actual) or expected != actual:
                return False, f"closure-binding-mismatch:{name}"
    summary = evidence.get("review_thread_summary")
    if type(summary) is dict and type(summary.get("blocking_unresolved")) is int:
        if not 0 <= summary["blocking_unresolved"] <= snapshot.unresolved_threads:
            return False, "closure-binding-mismatch:unresolved_threads"
    # Canonical guard compares ALL authorization scopes/freshness against the
    # snapshot. Keep it the single authority; surface its bounded reason code.
    admission = guard.evaluate_lifecycle_mutation(authorization, snapshot, "close-issue")
    if admission.status is guard.AdmissionStatus.ADMITTED and admission.admitted is True:
        return True, None
    return False, f"closure-not-admitted:{admission.reason_codes[0]}" if admission.reason_codes else "closure-not-admitted"


def _blocked(reason):
    return _core().ReleaseRunState(blockers=[reason])


def evaluate_release_run(evidence):
    """Return blocked states for invalid lifecycle evidence, without mutation."""
    if type(evidence) is not dict:
        raise TypeError("release evidence must be an object")
    # Preserve the documented Python strictness for non-string canonical text.
    for name in ("repository", "expected_head_sha", "observed_head_sha", "current_main_sha",
                 "validation_head_sha", "branch_state", "pr_state", "pr_lifecycle_state", "issue_state"):
        value = evidence.get(name)
        if value is not None and type(value) is not str:
            if evidence.get("issue_closure_lifecycle") is not None:
                return _blocked(f"invalid-release-identity:{name}")
            raise TypeError(f"{name} must be a string")
    try:
        canonical = _copy_native(evidence)
    except (TypeError, ValueError):
        return _blocked("invalid-release-evidence:non-native-or-unbounded")
    issue = _normalize_evidence(canonical)
    if issue:
        return _blocked(issue)
    admitted, reason = _closure_admission(canonical)
    canonical["issue_closure_authorized"] = admitted
    try:
        state = _core().evaluate_release_run(canonical)
    except (TypeError, ValueError, OverflowError, RecursionError):
        if reason:
            return _blocked(reason)
        raise
    if reason:
        # Keep the core's existing authorization pause. For an explicitly
        # contradictory packet, never expose a progressive/green disposition.
        state.blockers.append(reason)
        if state.next_action != "request-issue-closure-authorization":
            return _blocked(reason)
    return state


def _json_default(value):
    if isinstance(value, _Enum):
        return value.value
    if isinstance(value, (_datetime, _date)):
        return value.isoformat()
    raise TypeError("unsupported release result value")


def main() -> int:
    parser = _argparse.ArgumentParser(description="Evaluate bounded Agent OS release-run evidence")
    parser.add_argument("evidence", help="Path to JSON evidence file")
    path = parser.parse_args().evidence
    try:
        with open(path, encoding="utf-8") as handle:
            evidence = _json.load(handle)
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        # Bounded input diagnostics; never emit file contents.
        print(_json.dumps(_asdict(_blocked(f"evidence-file:{path[:240]}:{type(error).__name__}"))))
        return 2
    try:
        state = evaluate_release_run(evidence)
        output = _json.dumps(_asdict(state), sort_keys=True, separators=(",", ":"),
                             allow_nan=False, default=_json_default)
    except (TypeError, ValueError, OverflowError, RecursionError):
        print(_json.dumps(_asdict(_blocked("invalid-release-evidence"))))
        return 2
    print(output)
    return 0 if state.classification in ("READY_FOR_MERGE_AUTHORIZATION", "COMPLETED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
