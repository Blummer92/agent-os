"""Read-only discovery of one existing governed invocation handoff for an issue.

AOS-ROUTE2 (#1237) needs a bounded way for an integration surface to locate an
already-persisted ``ExecutorHandoff`` identity without fabricating authority
from chat or issue prose. This module scans only the existing #1218 invocation
descriptor store, validates every descriptor it reads, and returns a handoff
only when exactly one descriptor matches the requested repository and issue.

Discovery is a locator, not a currentness or authorization decision. Callers
must still pass the returned immutable handoff through the existing #1218
reconstruction/current-evidence/lease path before Scheduler admission.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal

from .invocation_descriptor import (
    MAX_INVOCATION_DESCRIPTOR_BYTES,
    MAX_INVOCATION_DESCRIPTORS,
    GovernedInvocationDescriptor,
    deserialize_invocation_descriptor,
)
from .store import CheckpointStoreUnavailable, _reject_symlink

HANDOFF_DISCOVERY_SCHEMA_NAME = "agent-os.invocation-handoff-discovery"
HANDOFF_DISCOVERY_SCHEMA_VERSION = "1.0"
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", re.ASCII)
_HANDOFF_RE = re.compile(r"^executor-handoff:[0-9a-f]{64}$", re.ASCII)


class InvocationHandoffDiscoveryStatus(str, Enum):
    FOUND = "found"
    NOT_FOUND = "not-found"
    NEEDS_DECISION = "needs-decision"


class InvocationHandoffDiscoveryReason(str, Enum):
    FOUND = "found"
    NO_MATCHING_DESCRIPTOR = "no-matching-descriptor"
    MULTIPLE_MATCHING_DESCRIPTORS = "multiple-matching-descriptors"
    DESCRIPTOR_INTEGRITY_UNVERIFIED = "descriptor-integrity-unverified"
    STORE_UNAVAILABLE = "store-unavailable"
    STORE_BOUND_EXCEEDED = "store-bound-exceeded"


@dataclass(frozen=True, slots=True, kw_only=True)
class InvocationHandoffDiscoveryResult:
    """Bounded non-authorizing result for one repository/issue lookup."""

    schema_name: Literal["agent-os.invocation-handoff-discovery"]
    schema_version: Literal["1.0"]
    result_id: str
    status: InvocationHandoffDiscoveryStatus
    reason_codes: tuple[InvocationHandoffDiscoveryReason, ...]
    repository: str
    issue_number: int
    matching_descriptor_count: int
    handoff_id: str | None
    repository_implementation_authorized: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    github_writes_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    issue_closure_authorized: Literal[False] = field(default=False, init=False)
    external_writes_authorized: Literal[False] = field(default=False, init=False)
    scheduler_invoked: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_name != HANDOFF_DISCOVERY_SCHEMA_NAME:
            raise ValueError("unsupported handoff discovery schema name")
        if self.schema_version != HANDOFF_DISCOVERY_SCHEMA_VERSION:
            raise ValueError("unsupported handoff discovery schema version")
        _validate_repository(self.repository)
        _validate_issue_number(self.issue_number)
        if type(self.status) is not InvocationHandoffDiscoveryStatus:
            raise TypeError("status must be exact InvocationHandoffDiscoveryStatus")
        if type(self.reason_codes) is not tuple or not self.reason_codes:
            raise ValueError("reason_codes must be a non-empty exact tuple")
        if any(
            type(item) is not InvocationHandoffDiscoveryReason
            for item in self.reason_codes
        ):
            raise TypeError("reason_codes contain an invalid value")
        canonical_reasons = tuple(
            sorted(set(self.reason_codes), key=lambda item: item.value)
        )
        if self.reason_codes != canonical_reasons:
            raise ValueError("reason_codes must be sorted and unique")
        if type(self.matching_descriptor_count) is not int or self.matching_descriptor_count < 0:
            raise TypeError("matching_descriptor_count must be a non-negative integer")
        if self.status is InvocationHandoffDiscoveryStatus.FOUND:
            if self.reason_codes != (InvocationHandoffDiscoveryReason.FOUND,):
                raise ValueError("found result must carry only the found reason")
            if self.matching_descriptor_count != 1:
                raise ValueError("found result requires exactly one matching descriptor")
            if type(self.handoff_id) is not str or _HANDOFF_RE.fullmatch(self.handoff_id) is None:
                raise ValueError("found result requires a canonical handoff identity")
        elif self.handoff_id is not None:
            raise ValueError("non-found result must not expose a handoff identity")
        if self.result_id != _result_id(
            status=self.status,
            reasons=self.reason_codes,
            repository=self.repository,
            issue_number=self.issue_number,
            matching_descriptor_count=self.matching_descriptor_count,
            handoff_id=self.handoff_id,
        ):
            raise ValueError("result_id does not match discovery result")


def _validate_repository(repository: object) -> str:
    if type(repository) is not str or not _REPOSITORY_RE.fullmatch(repository):
        raise ValueError("repository must use owner/name syntax")
    return repository


def _validate_issue_number(issue_number: object) -> int:
    if type(issue_number) is not int or issue_number < 1:
        raise TypeError("issue_number must be a positive built-in integer")
    return issue_number


def _result_id(
    *,
    status: InvocationHandoffDiscoveryStatus,
    reasons: tuple[InvocationHandoffDiscoveryReason, ...],
    repository: str,
    issue_number: int,
    matching_descriptor_count: int,
    handoff_id: str | None,
) -> str:
    payload = {
        "schema_name": HANDOFF_DISCOVERY_SCHEMA_NAME,
        "schema_version": HANDOFF_DISCOVERY_SCHEMA_VERSION,
        "status": status.value,
        "reason_codes": [item.value for item in reasons],
        "repository": repository,
        "issue_number": issue_number,
        "matching_descriptor_count": matching_descriptor_count,
        "handoff_id": handoff_id,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    digest = hashlib.sha256(
        b"agent-os.invocation-handoff-discovery:v1\0" + encoded
    ).hexdigest()
    return f"invocation-handoff-discovery:{digest}"


def _result(
    *,
    status: InvocationHandoffDiscoveryStatus,
    reasons: tuple[InvocationHandoffDiscoveryReason, ...],
    repository: str,
    issue_number: int,
    matching_descriptor_count: int,
    handoff_id: str | None = None,
) -> InvocationHandoffDiscoveryResult:
    canonical_reasons = tuple(sorted(set(reasons), key=lambda item: item.value))
    return InvocationHandoffDiscoveryResult(
        schema_name=HANDOFF_DISCOVERY_SCHEMA_NAME,
        schema_version=HANDOFF_DISCOVERY_SCHEMA_VERSION,
        result_id=_result_id(
            status=status,
            reasons=canonical_reasons,
            repository=repository,
            issue_number=issue_number,
            matching_descriptor_count=matching_descriptor_count,
            handoff_id=handoff_id,
        ),
        status=status,
        reason_codes=canonical_reasons,
        repository=repository,
        issue_number=issue_number,
        matching_descriptor_count=matching_descriptor_count,
        handoff_id=handoff_id,
    )


def _read_descriptor(path: Path) -> GovernedInvocationDescriptor:
    _reject_symlink(path)
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise CheckpointStoreUnavailable(f"unable to read {path}") from exc
    if len(payload) > MAX_INVOCATION_DESCRIPTOR_BYTES:
        raise ValueError("descriptor exceeds the bounded size")
    descriptor = deserialize_invocation_descriptor(payload)
    expected_name = f"{descriptor.handoff_id.rsplit(':', 1)[-1]}.json"
    if path.name != expected_name:
        raise ValueError("descriptor filename does not match handoff identity")
    return descriptor


def discover_issue_handoff(
    store_root: Path | str,
    *,
    repository: str,
    issue_number: int,
) -> InvocationHandoffDiscoveryResult:
    """Locate exactly one existing handoff descriptor for repository + issue.

    The function performs read-only bounded scanning of the existing #1218
    ``invocations`` directory. It never chooses between multiple historical
    candidates and never claims the selected descriptor is current. Zero
    matches returns ``not-found``; ambiguity, corruption, or store failures
    return ``needs-decision`` with no handoff identity.
    """

    canonical_repository = _validate_repository(repository)
    canonical_issue = _validate_issue_number(issue_number)
    directory = Path(store_root) / "invocations"
    try:
        _reject_symlink(directory)
        if not directory.exists():
            return _result(
                status=InvocationHandoffDiscoveryStatus.NOT_FOUND,
                reasons=(InvocationHandoffDiscoveryReason.NO_MATCHING_DESCRIPTOR,),
                repository=canonical_repository,
                issue_number=canonical_issue,
                matching_descriptor_count=0,
            )
        entries = tuple(
            sorted(
                (entry for entry in directory.iterdir() if entry.suffix == ".json"),
                key=lambda item: item.name,
            )
        )
    except (OSError, CheckpointStoreUnavailable):
        return _result(
            status=InvocationHandoffDiscoveryStatus.NEEDS_DECISION,
            reasons=(InvocationHandoffDiscoveryReason.STORE_UNAVAILABLE,),
            repository=canonical_repository,
            issue_number=canonical_issue,
            matching_descriptor_count=0,
        )

    if len(entries) > MAX_INVOCATION_DESCRIPTORS:
        return _result(
            status=InvocationHandoffDiscoveryStatus.NEEDS_DECISION,
            reasons=(InvocationHandoffDiscoveryReason.STORE_BOUND_EXCEEDED,),
            repository=canonical_repository,
            issue_number=canonical_issue,
            matching_descriptor_count=0,
        )

    matches: list[GovernedInvocationDescriptor] = []
    try:
        for entry in entries:
            descriptor = _read_descriptor(entry)
            if (
                descriptor.repository.casefold() == canonical_repository.casefold()
                and descriptor.issue_number == canonical_issue
            ):
                matches.append(descriptor)
    except (TypeError, ValueError, CheckpointStoreUnavailable):
        return _result(
            status=InvocationHandoffDiscoveryStatus.NEEDS_DECISION,
            reasons=(InvocationHandoffDiscoveryReason.DESCRIPTOR_INTEGRITY_UNVERIFIED,),
            repository=canonical_repository,
            issue_number=canonical_issue,
            matching_descriptor_count=len(matches),
        )

    if not matches:
        return _result(
            status=InvocationHandoffDiscoveryStatus.NOT_FOUND,
            reasons=(InvocationHandoffDiscoveryReason.NO_MATCHING_DESCRIPTOR,),
            repository=canonical_repository,
            issue_number=canonical_issue,
            matching_descriptor_count=0,
        )
    if len(matches) != 1:
        return _result(
            status=InvocationHandoffDiscoveryStatus.NEEDS_DECISION,
            reasons=(InvocationHandoffDiscoveryReason.MULTIPLE_MATCHING_DESCRIPTORS,),
            repository=canonical_repository,
            issue_number=canonical_issue,
            matching_descriptor_count=len(matches),
        )
    return _result(
        status=InvocationHandoffDiscoveryStatus.FOUND,
        reasons=(InvocationHandoffDiscoveryReason.FOUND,),
        repository=canonical_repository,
        issue_number=canonical_issue,
        matching_descriptor_count=1,
        handoff_id=matches[0].handoff_id,
    )
