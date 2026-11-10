"""Render the canonical owner-authored PR refresh authorization record (#3463).

This module is a thin, production-callable entry point over existing
components only: it builds a :class:`RefreshAuthorization` (which validates
every field and computes the content-derived ``authorization_id``) and
renders it with the existing
:func:`serialize_refresh_authorization_comment`. It introduces no new
authorization model, evaluator, persistence, GitHub I/O, or mutation
authority.

Host-consumption contract (intended consumer: a future native ChatGPT host
integration; that integration is OUTSTANDING until demonstrated live):

1. The host must first obtain the owner's refresh decision through its own
   separately authorized channel, and reacquire fresh PR head, main, and
   changed-file scope from GitHub. Rendering never supplies, refreshes, or
   substitutes for any of that evidence.
2. The host passes those exact values here, with the owner's decision
   reference, and receives the deterministic canonical comment text.
3. Rendering alone grants nothing and authorizes nothing. A record becomes
   trusted only when it is posted verbatim (marker line plus canonical JSON)
   through an owner-authored channel, and even then the governed runner
   still reacquires current head/main/scope, checks the record is
   unconsumed and applicable, and fails closed on any mismatch.
4. This entry point never posts to GitHub, never calls the GitHub merge
   API, and never accepts a caller-supplied ``authorization_id``: the id
   is always recomputed from content, so a tampered id cannot be smuggled
   through the renderer.
5. The native ChatGPT posting connection -- producing and posting the
   trusted record, invoking the governed issue-only trigger, correlating
   the run, consuming the result, and continuing validation -- remains
   outstanding. A CLI that only prints a record is not proof of that
   integration, and must never be described as such.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, Mapping

from .pr_branch_refresh_authorization import (
    SCHEMA_VERSION,
    RefreshAuthorization,
    RefreshAuthorizationState,
)
from .pr_branch_refresh_authorization_source import (
    serialize_refresh_authorization_comment,
)

# The exact field set a renderer input must carry: no more, no less.
# ``schema_version`` and ``base_branch`` are canonical constants, not
# caller inputs, so they are deliberately absent from this set.
_RENDERER_FIELDS = frozenset(
    {
        "repository",
        "pr_number",
        "expected_head_sha",
        "expected_main_sha",
        "allowed_changed_paths",
        "forbidden_paths",
        "required_validation_command_ids",
        "branch_refresh_authorized",
        "label_write_authorized",
        "owner_decision_reference",
        "state",
    }
)


def _paths(value: object, field_name: str) -> tuple[str, ...]:
    """Accept a tuple or list of paths; refuse strings, mappings, and other types."""
    if isinstance(value, str) or isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a list or tuple of paths")
    if not isinstance(value, (tuple, list)):
        raise TypeError(f"{field_name} must be a list or tuple of paths")
    return tuple(value)


def _state(value: object) -> RefreshAuthorizationState:
    if isinstance(value, RefreshAuthorizationState):
        return value
    if isinstance(value, str):
        try:
            return RefreshAuthorizationState(value)
        except ValueError:
            raise ValueError(f"unsupported refresh authorization state: {value}") from None
    raise TypeError("state must be a RefreshAuthorizationState or its exact string value")


def render_refresh_authorization_comment(
    *,
    repository: str,
    pr_number: int,
    expected_head_sha: str,
    expected_main_sha: str,
    allowed_changed_paths: Iterable[str],
    forbidden_paths: Iterable[str],
    required_validation_command_ids: Iterable[str],
    branch_refresh_authorized: bool,
    label_write_authorized: bool,
    owner_decision_reference: str,
    state: RefreshAuthorizationState | str,
) -> str:
    """Render the canonical authorization comment for explicitly supplied inputs.

    Every field is required; there are no defaults for authority fields, so
    the caller cannot obtain an authorized record by omission. Validation
    and identifier computation are entirely delegated to
    :class:`RefreshAuthorization`; this function adds no rule of its own.
    """
    authorization = RefreshAuthorization(
        schema_version=SCHEMA_VERSION,
        repository=repository,
        pr_number=pr_number,
        base_branch="main",
        expected_head_sha=expected_head_sha,
        expected_main_sha=expected_main_sha,
        allowed_changed_paths=_paths(allowed_changed_paths, "allowed_changed_paths"),
        forbidden_paths=_paths(forbidden_paths, "forbidden_paths"),
        required_validation_command_ids=_paths(required_validation_command_ids, "required_validation_command_ids"),
        branch_refresh_authorized=branch_refresh_authorized,
        label_write_authorized=label_write_authorized,
        owner_decision_reference=owner_decision_reference,
        state=_state(state),
    )
    return serialize_refresh_authorization_comment(authorization)


def render_refresh_authorization_comment_from_mapping(payload: Mapping[str, object]) -> str:
    """Render from a structured mapping, refusing incomplete or extra fields."""
    if not isinstance(payload, Mapping):
        raise TypeError("renderer input must be a JSON object")
    if set(payload) != set(_RENDERER_FIELDS):
        missing = sorted(set(_RENDERER_FIELDS) - set(payload))
        extra = sorted(set(payload) - set(_RENDERER_FIELDS))
        raise ValueError(f"renderer input fields are invalid (missing={missing}, extra={extra})")
    return render_refresh_authorization_comment(
        repository=payload["repository"],  # type: ignore[arg-type]
        pr_number=payload["pr_number"],  # type: ignore[arg-type]
        expected_head_sha=payload["expected_head_sha"],  # type: ignore[arg-type]
        expected_main_sha=payload["expected_main_sha"],  # type: ignore[arg-type]
        allowed_changed_paths=payload["allowed_changed_paths"],  # type: ignore[arg-type]
        forbidden_paths=payload["forbidden_paths"],  # type: ignore[arg-type]
        required_validation_command_ids=payload["required_validation_command_ids"],  # type: ignore[arg-type]
        branch_refresh_authorized=payload["branch_refresh_authorized"],  # type: ignore[arg-type]
        label_write_authorized=payload["label_write_authorized"],  # type: ignore[arg-type]
        owner_decision_reference=payload["owner_decision_reference"],  # type: ignore[arg-type]
        state=payload["state"],  # type: ignore[arg-type]
    )


def _read_input(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """CLI: print the canonical record to stdout; never post it anywhere."""
    parser = argparse.ArgumentParser(
        description="Render one canonical PR refresh authorization record. "
        "Output only: this command performs no GitHub I/O and grants no authority."
    )
    parser.add_argument("--input", required=True, help="Path to a structured JSON renderer input, or - for stdin.")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(_read_input(args.input))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"unable to read structured renderer input: {exc}", file=sys.stderr)
        return 2
    try:
        print(render_refresh_authorization_comment_from_mapping(payload))
    except (TypeError, ValueError, KeyError) as exc:
        print(f"invalid refresh authorization input: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
