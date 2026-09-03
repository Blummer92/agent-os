"""Immutable, content-bound authorization evidence for governed PR refresh (#1403).

The record specializes existing Agent OS content-bound authorization conventions for
#1187. It performs no retrieval, mutation, credential handling, or persistence.
Callers supply canonical records plus freshly reacquired PR/head/main/scope evidence;
the resolver selects exactly one applicable record or fails closed.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping

SCHEMA_VERSION = "1.0"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_MAX_PATHS = 256
_MAX_REASON_CODES = 32


class RefreshAuthorizationState(str, Enum):
    AUTHORIZED = "authorized"
    REJECTED = "rejected"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"
    CONSUMED = "consumed"
    SUPERSEDED = "superseded"


def _canonical(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _identity(prefix: str, payload: object) -> str:
    return f"{prefix}:{hashlib.sha256(_canonical(payload)).hexdigest()}"


def _paths(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    if type(values) is not tuple or len(values) > _MAX_PATHS:
        raise TypeError(f"{name} must be a bounded exact tuple")
    if any(type(value) is not str or not value or "\x00" in value for value in values):
        raise ValueError(f"{name} contains an invalid path")
    if len(set(values)) != len(values):
        raise ValueError(f"{name} contains duplicates")
    return tuple(sorted(values))


@dataclass(frozen=True, slots=True)
class RefreshAuthorization:
    schema_version: str
    repository: str
    pr_number: int
    base_branch: str
    expected_head_sha: str
    expected_main_sha: str
    allowed_changed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    required_validation_command_ids: tuple[str, ...]
    branch_refresh_authorized: bool
    label_write_authorized: bool
    owner_decision_reference: str
    state: RefreshAuthorizationState
    authorization_id: str = ""
    side_effects_performed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported refresh authorization schema version")
        if not _REPOSITORY.fullmatch(self.repository):
            raise ValueError("repository must use owner/name syntax")
        if type(self.pr_number) is not int or self.pr_number < 1:
            raise TypeError("pr_number must be a positive built-in integer")
        if self.base_branch != "main":
            raise ValueError("base_branch must be canonical main")
        for value, name in ((self.expected_head_sha, "expected_head_sha"), (self.expected_main_sha, "expected_main_sha")):
            if type(value) is not str or not _SHA40.fullmatch(value):
                raise ValueError(f"{name} must be a lowercase 40-character SHA")
        object.__setattr__(self, "allowed_changed_paths", _paths(self.allowed_changed_paths, "allowed_changed_paths"))
        object.__setattr__(self, "forbidden_paths", _paths(self.forbidden_paths, "forbidden_paths"))
        object.__setattr__(self, "required_validation_command_ids", _paths(self.required_validation_command_ids, "required_validation_command_ids"))
        if type(self.branch_refresh_authorized) is not bool or type(self.label_write_authorized) is not bool:
            raise TypeError("authority fields must be exact booleans")
        if type(self.owner_decision_reference) is not str or not self.owner_decision_reference.strip() or "\x00" in self.owner_decision_reference:
            raise ValueError("owner_decision_reference is required")
        if not isinstance(self.state, RefreshAuthorizationState):
            raise TypeError("state must use RefreshAuthorizationState")
        expected = _identity("refresh-authorization", self._identity_payload())
        if self.authorization_id and self.authorization_id != expected:
            raise ValueError("authorization_id does not match content")
        object.__setattr__(self, "authorization_id", expected)

    def _identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "repository": self.repository,
            "pr_number": self.pr_number,
            "base_branch": self.base_branch,
            "expected_head_sha": self.expected_head_sha,
            "expected_main_sha": self.expected_main_sha,
            "allowed_changed_paths": list(self.allowed_changed_paths),
            "forbidden_paths": list(self.forbidden_paths),
            "required_validation_command_ids": list(self.required_validation_command_ids),
            "branch_refresh_authorized": self.branch_refresh_authorized,
            "label_write_authorized": self.label_write_authorized,
            "owner_decision_reference": self.owner_decision_reference,
            "state": self.state.value,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_payload(), "authorization_id": self.authorization_id, "side_effects_performed": False}


@dataclass(frozen=True, slots=True)
class BranchRefreshAuthorizationEvidence:
    repository: str
    pr_number: int
    authorization_id: str | None
    applicable: bool
    authorization_current: bool
    branch_refresh_authorized: bool
    label_write_authorized: bool
    expected_head_sha: str
    current_main_sha: str
    allowed_changed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    required_validation_command_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    side_effects_performed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if len(self.reason_codes) > _MAX_REASON_CODES:
            raise ValueError("reason_codes exceed bound")
        if tuple(sorted(set(self.reason_codes))) != self.reason_codes:
            raise ValueError("reason_codes must be sorted and unique")
        if self.applicable != (not self.reason_codes):
            raise ValueError("applicable must match reason evidence")
        if self.authorization_current != self.applicable:
            raise ValueError("authorization_current must match applicability")
        if not self.applicable and (self.branch_refresh_authorized or self.label_write_authorized):
            raise ValueError("blocked evidence cannot carry write authority")

    def refresh_pr_kwargs(self, *, repository_root: str, invocation_id: str, environment: Mapping[str, str]) -> dict[str, object]:
        """Project only the existing #1402 facade inputs; never create authority."""
        if not self.applicable or self.authorization_id is None:
            raise RuntimeError("applicable refresh authorization is required")
        return {
            "repository": self.repository,
            "pr_number": self.pr_number,
            "expected_head_sha": self.expected_head_sha,
            "current_main_sha": self.current_main_sha,
            "authorization_id": self.authorization_id,
            "authorization_current": True,
            "branch_refresh_authorized": self.branch_refresh_authorized,
            "allowed_changed_paths": self.allowed_changed_paths,
            "forbidden_paths": self.forbidden_paths,
            "label_write_authorized": self.label_write_authorized,
            "repository_root": repository_root,
            "invocation_id": invocation_id,
            "environment": environment,
        }


def resolve_branch_refresh_authorization(
    records: Iterable[RefreshAuthorization],
    *,
    repository: str,
    pr_number: int,
    current_head_sha: str,
    current_main_sha: str,
    current_changed_paths: tuple[str, ...],
) -> BranchRefreshAuthorizationEvidence:
    """Resolve exactly one current authorization from canonical supplied records."""
    changed = _paths(current_changed_paths, "current_changed_paths")
    candidates = [record for record in records if record.repository == repository and record.pr_number == pr_number]
    reasons: set[str] = set()
    if not candidates:
        reasons.add("authorization.absent")
        return _blocked(repository, pr_number, current_head_sha, current_main_sha, reasons)
    if len(candidates) != 1:
        reasons.add("authorization.ambiguous")
        return _blocked(repository, pr_number, current_head_sha, current_main_sha, reasons)
    record = candidates[0]
    if record.state is RefreshAuthorizationState.CONSUMED:
        reasons.add("authorization.consumed")
    elif record.state is not RefreshAuthorizationState.AUTHORIZED:
        reasons.add("authorization.not-current")
    if not record.branch_refresh_authorized:
        reasons.add("authorization.refresh-not-granted")
    if record.expected_head_sha != current_head_sha:
        reasons.add("head.moved")
    if record.expected_main_sha != current_main_sha:
        reasons.add("main.moved")
    changed_set = set(changed)
    if changed_set & set(record.forbidden_paths):
        reasons.add("scope.forbidden-path")
    if not changed_set.issubset(set(record.allowed_changed_paths)):
        reasons.add("scope.expanded")
    if reasons:
        return _blocked(repository, pr_number, current_head_sha, current_main_sha, reasons)
    return BranchRefreshAuthorizationEvidence(
        repository=repository,
        pr_number=pr_number,
        authorization_id=record.authorization_id,
        applicable=True,
        authorization_current=True,
        branch_refresh_authorized=True,
        label_write_authorized=record.label_write_authorized,
        expected_head_sha=record.expected_head_sha,
        current_main_sha=record.expected_main_sha,
        allowed_changed_paths=record.allowed_changed_paths,
        forbidden_paths=record.forbidden_paths,
        required_validation_command_ids=record.required_validation_command_ids,
        reason_codes=(),
    )


def _blocked(repository: str, pr_number: int, head: str, main: str, reasons: set[str]) -> BranchRefreshAuthorizationEvidence:
    return BranchRefreshAuthorizationEvidence(
        repository=repository,
        pr_number=pr_number,
        authorization_id=None,
        applicable=False,
        authorization_current=False,
        branch_refresh_authorized=False,
        label_write_authorized=False,
        expected_head_sha=head,
        current_main_sha=main,
        allowed_changed_paths=(),
        forbidden_paths=(),
        required_validation_command_ids=(),
        reason_codes=tuple(sorted(reasons)),
    )
