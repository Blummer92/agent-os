"""Pre-tool governed-route preflight for the host execution interface (#1237).

#1237 owns the seam between a host execution interface and the already-merged
Agent OS governed runner path. The failure this module removes is:

```text
work on an Agent OS issue
-> generic GitHub publish tooling selected first
-> local `gh` prerequisite checked
-> `gh` absent
-> false blocker
```

The adapter is deliberately thin. It recognizes a governed Agent OS checkout,
delegates the whole lookup to the existing #1237 read-only handoff locator, and
reports which existing governed resume ingress the interface should use. It
resolves nothing else:

- it does not re-derive :mod:`executor_routing` precedence or duplicate
  ``ExecutorRouteDecision``;
- it does not scan, index, or persist descriptors itself;
- it does not synthesize, choose, or age-rank a handoff identity;
- it does not acquire a lease, admit work, or invoke the Scheduler;
- it performs no network, subprocess, GitHub, cloud, or credential access.

Discovery is bootstrap, never authorization or currentness. Every identity this
module reports must still pass the existing #1218/#1253 reconstruction,
authorization, source/scope, checkpoint, ResumePlan, environment, and lease
checks before any Scheduler execution.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal, Sequence

from scripts.agent_os_execution_checkpoint.handoff_discovery import (
    InvocationHandoffDiscoveryStatus,
    discover_issue_handoff,
)

GOVERNED_ROUTE_PREFLIGHT_SCHEMA_NAME = "agent-os.execution-interface-governed-route-preflight"
GOVERNED_ROUTE_PREFLIGHT_SCHEMA_VERSION = "1.0"

#: Files that must all exist for a checkout to count as Agent OS governed.
#: Recognition is repository evidence only; chat text, branch names, issue
#: prose, and labels never make a checkout governed.
GOVERNED_CHECKOUT_MARKERS: tuple[str, ...] = (
    "AGENTS.md",
    "00_Governance/write-authorization-policy.md",
    "04_Registry/agent-inheritance-registry.md",
    "scripts/agent_os_execution_checkpoint/handoff_discovery.py",
)

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", re.ASCII)
_HANDOFF_RE = re.compile(r"^executor-handoff:[0-9a-f]{64}$", re.ASCII)

#: The existing #1203 bounded issue-comment ingress command shape. The adapter
#: only ever fills in an identity the locator returned; it never composes shell
#: text, prompts, branch operations, URLs, credentials, or free-form commands.
GOVERNED_RESUME_INGRESS_TEMPLATE = "/agent-os resume {handoff_id}"


class GovernedRoutePreflightStatus(str, Enum):
    GOVERNED_RESUME_AVAILABLE = "governed-resume-available"
    NOT_APPLICABLE = "not-applicable"
    NOT_FOUND = "not-found"
    NEEDS_DECISION = "needs-decision"


class GovernedRoutePreflightReason(str, Enum):
    GOVERNED_RESUME_AVAILABLE = "governed-resume-available"
    NOT_AGENT_OS_CHECKOUT = "not-agent-os-checkout"
    NO_GOVERNED_ISSUE_REFERENCE = "no-governed-issue-reference"
    REPOSITORY_IDENTITY_UNRESOLVED = "repository-identity-unresolved"
    AMBIGUOUS_ISSUE_REFERENCE = "ambiguous-issue-reference"
    DESCRIPTOR_STORE_NOT_CONFIGURED = "descriptor-store-not-configured"
    DISCOVERY_NO_MATCHING_DESCRIPTOR = "discovery-no-matching-descriptor"
    DISCOVERY_MULTIPLE_MATCHING_DESCRIPTORS = "discovery-multiple-matching-descriptors"
    DISCOVERY_DESCRIPTOR_INTEGRITY_UNVERIFIED = "discovery-descriptor-integrity-unverified"
    DISCOVERY_STORE_UNAVAILABLE = "discovery-store-unavailable"
    DISCOVERY_STORE_BOUND_EXCEEDED = "discovery-store-bound-exceeded"


_DISCOVERY_REASON_MAP: dict[str, GovernedRoutePreflightReason] = {
    "found": GovernedRoutePreflightReason.GOVERNED_RESUME_AVAILABLE,
    "no-matching-descriptor": GovernedRoutePreflightReason.DISCOVERY_NO_MATCHING_DESCRIPTOR,
    "multiple-matching-descriptors": (
        GovernedRoutePreflightReason.DISCOVERY_MULTIPLE_MATCHING_DESCRIPTORS
    ),
    "descriptor-integrity-unverified": (
        GovernedRoutePreflightReason.DISCOVERY_DESCRIPTOR_INTEGRITY_UNVERIFIED
    ),
    "store-unavailable": GovernedRoutePreflightReason.DISCOVERY_STORE_UNAVAILABLE,
    "store-bound-exceeded": GovernedRoutePreflightReason.DISCOVERY_STORE_BOUND_EXCEEDED,
}

_DISCOVERY_STATUS_MAP: dict[InvocationHandoffDiscoveryStatus, GovernedRoutePreflightStatus] = {
    InvocationHandoffDiscoveryStatus.FOUND: (
        GovernedRoutePreflightStatus.GOVERNED_RESUME_AVAILABLE
    ),
    InvocationHandoffDiscoveryStatus.NOT_FOUND: GovernedRoutePreflightStatus.NOT_FOUND,
    InvocationHandoffDiscoveryStatus.NEEDS_DECISION: (
        GovernedRoutePreflightStatus.NEEDS_DECISION
    ),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class GovernedRoutePreflightResult:
    """Bounded, non-authorizing pre-tool routing evidence for one request."""

    schema_name: Literal["agent-os.execution-interface-governed-route-preflight"]
    schema_version: Literal["1.0"]
    result_id: str
    status: GovernedRoutePreflightStatus
    reason_codes: tuple[GovernedRoutePreflightReason, ...]
    repository: str | None
    issue_number: int | None
    handoff_id: str | None
    resume_command: str | None
    #: Fixed-false contract fields. The preflight is a locator consumer only.
    #: ``local_gh_absence_is_execution_blocker`` encodes #1237's hard invariant:
    #: a missing local CLI is capability-mismatch evidence about one surface and
    #: is never evidence that Agent OS execution is unavailable.
    local_gh_absence_is_execution_blocker: Literal[False] = field(default=False, init=False)
    repository_implementation_authorized: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    github_writes_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    issue_closure_authorized: Literal[False] = field(default=False, init=False)
    external_writes_authorized: Literal[False] = field(default=False, init=False)
    scheduler_invoked: Literal[False] = field(default=False, init=False)
    handoff_persisted: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_name != GOVERNED_ROUTE_PREFLIGHT_SCHEMA_NAME:
            raise ValueError("unsupported governed-route preflight schema name")
        if self.schema_version != GOVERNED_ROUTE_PREFLIGHT_SCHEMA_VERSION:
            raise ValueError("unsupported governed-route preflight schema version")
        if type(self.status) is not GovernedRoutePreflightStatus:
            raise TypeError("status must be exact GovernedRoutePreflightStatus")
        if type(self.reason_codes) is not tuple or not self.reason_codes:
            raise ValueError("reason_codes must be a non-empty exact tuple")
        if any(
            type(item) is not GovernedRoutePreflightReason for item in self.reason_codes
        ):
            raise TypeError("reason_codes contain an invalid value")
        canonical_reasons = tuple(
            sorted(set(self.reason_codes), key=lambda item: item.value)
        )
        if self.reason_codes != canonical_reasons:
            raise ValueError("reason_codes must be sorted and unique")
        if self.repository is not None and (
            type(self.repository) is not str
            or _REPOSITORY_RE.fullmatch(self.repository) is None
        ):
            raise ValueError("repository must be None or owner/name syntax")
        if self.issue_number is not None and (
            type(self.issue_number) is not int or self.issue_number < 1
        ):
            raise TypeError("issue_number must be None or a positive built-in integer")
        if self.status is GovernedRoutePreflightStatus.GOVERNED_RESUME_AVAILABLE:
            if self.reason_codes != (
                GovernedRoutePreflightReason.GOVERNED_RESUME_AVAILABLE,
            ):
                raise ValueError("available result must carry only the available reason")
            if (
                type(self.handoff_id) is not str
                or _HANDOFF_RE.fullmatch(self.handoff_id) is None
            ):
                raise ValueError("available result requires a canonical handoff identity")
            if self.repository is None or self.issue_number is None:
                raise ValueError("available result requires repository and issue")
            if self.resume_command != GOVERNED_RESUME_INGRESS_TEMPLATE.format(
                handoff_id=self.handoff_id
            ):
                raise ValueError("resume_command must be the existing bounded ingress")
        else:
            if self.handoff_id is not None:
                raise ValueError("non-available result must not expose a handoff identity")
            if self.resume_command is not None:
                raise ValueError("non-available result must not expose a resume command")
        if self.result_id != _result_id(
            status=self.status,
            reasons=self.reason_codes,
            repository=self.repository,
            issue_number=self.issue_number,
            handoff_id=self.handoff_id,
        ):
            raise ValueError("result_id does not match preflight result")


def _result_id(
    *,
    status: GovernedRoutePreflightStatus,
    reasons: tuple[GovernedRoutePreflightReason, ...],
    repository: str | None,
    issue_number: int | None,
    handoff_id: str | None,
) -> str:
    payload = {
        "schema_name": GOVERNED_ROUTE_PREFLIGHT_SCHEMA_NAME,
        "schema_version": GOVERNED_ROUTE_PREFLIGHT_SCHEMA_VERSION,
        "status": status.value,
        "reason_codes": [item.value for item in reasons],
        "repository": repository,
        "issue_number": issue_number,
        "handoff_id": handoff_id,
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    digest = hashlib.sha256(
        b"agent-os.execution-interface-governed-route-preflight:v1\0" + encoded
    ).hexdigest()
    return f"governed-route-preflight:{digest}"


def _result(
    *,
    status: GovernedRoutePreflightStatus,
    reasons: tuple[GovernedRoutePreflightReason, ...],
    repository: str | None = None,
    issue_number: int | None = None,
    handoff_id: str | None = None,
) -> GovernedRoutePreflightResult:
    canonical_reasons = tuple(sorted(set(reasons), key=lambda item: item.value))
    resume_command = (
        GOVERNED_RESUME_INGRESS_TEMPLATE.format(handoff_id=handoff_id)
        if handoff_id is not None
        else None
    )
    return GovernedRoutePreflightResult(
        schema_name=GOVERNED_ROUTE_PREFLIGHT_SCHEMA_NAME,
        schema_version=GOVERNED_ROUTE_PREFLIGHT_SCHEMA_VERSION,
        result_id=_result_id(
            status=status,
            reasons=canonical_reasons,
            repository=repository,
            issue_number=issue_number,
            handoff_id=handoff_id,
        ),
        status=status,
        reason_codes=canonical_reasons,
        repository=repository,
        issue_number=issue_number,
        handoff_id=handoff_id,
        resume_command=resume_command,
    )


def is_governed_checkout(checkout_root: Path | str | None) -> bool:
    """Return whether ``checkout_root`` carries every governed marker file."""
    if checkout_root is None:
        return False
    try:
        root = Path(checkout_root)
        return all((root / marker).is_file() for marker in GOVERNED_CHECKOUT_MARKERS)
    except OSError:
        return False


def resolve_governed_route_preflight(
    *,
    checkout_root: Path | str | None,
    repository: str | None,
    issue_numbers: Sequence[int],
    store_root: Path | str | None,
) -> GovernedRoutePreflightResult:
    """Resolve the governed route for a known repository + issue, or stand down.

    Ordering matters: this runs before the host interface selects generic
    GitHub publish tooling, so a non-governed checkout or a request that names
    no issue returns ``not-applicable`` and leaves existing generic behavior
    completely untouched.
    """
    if not is_governed_checkout(checkout_root):
        return _result(
            status=GovernedRoutePreflightStatus.NOT_APPLICABLE,
            reasons=(GovernedRoutePreflightReason.NOT_AGENT_OS_CHECKOUT,),
        )

    if type(issue_numbers) not in (list, tuple):
        raise TypeError("issue_numbers must be a list or tuple")
    distinct_issues = sorted({_validate_issue_number(item) for item in issue_numbers})
    if not distinct_issues:
        return _result(
            status=GovernedRoutePreflightStatus.NOT_APPLICABLE,
            reasons=(GovernedRoutePreflightReason.NO_GOVERNED_ISSUE_REFERENCE,),
        )

    # A governed checkout whose repository identity cannot be resolved is
    # ambiguous, not generic. Fail closed rather than guessing an owner/name.
    if type(repository) is not str or _REPOSITORY_RE.fullmatch(repository) is None:
        return _result(
            status=GovernedRoutePreflightStatus.NEEDS_DECISION,
            reasons=(GovernedRoutePreflightReason.REPOSITORY_IDENTITY_UNRESOLVED,),
        )

    # Never pick one issue out of several. Selecting a target is the caller's
    # decision, not a heuristic this seam is allowed to make.
    if len(distinct_issues) != 1:
        return _result(
            status=GovernedRoutePreflightStatus.NEEDS_DECISION,
            reasons=(GovernedRoutePreflightReason.AMBIGUOUS_ISSUE_REFERENCE,),
            repository=repository,
        )
    issue_number = distinct_issues[0]

    # The descriptor store location is existing #1218 host composition. An
    # unconfigured store is unavailable evidence, never a default path to
    # invent and never a reason to fall back to local CLI tooling.
    if store_root is None or (type(store_root) is str and not store_root.strip()):
        return _result(
            status=GovernedRoutePreflightStatus.NEEDS_DECISION,
            reasons=(GovernedRoutePreflightReason.DESCRIPTOR_STORE_NOT_CONFIGURED,),
            repository=repository,
            issue_number=issue_number,
        )

    discovery = discover_issue_handoff(
        store_root, repository=repository, issue_number=issue_number
    )
    status = _DISCOVERY_STATUS_MAP[discovery.status]
    reasons = tuple(
        _DISCOVERY_REASON_MAP[item.value] for item in discovery.reason_codes
    )
    return _result(
        status=status,
        reasons=reasons,
        repository=discovery.repository,
        issue_number=discovery.issue_number,
        handoff_id=discovery.handoff_id,
    )


def _validate_issue_number(issue_number: object) -> int:
    if type(issue_number) is not int or issue_number < 1:
        raise TypeError("issue_number must be a positive built-in integer")
    return issue_number


def serialize_preflight_result(result: GovernedRoutePreflightResult) -> str:
    """Render one preflight result as canonical bounded JSON evidence."""
    if type(result) is not GovernedRoutePreflightResult:
        raise TypeError("result must be an exact GovernedRoutePreflightResult")
    payload = {
        "schema_name": result.schema_name,
        "schema_version": result.schema_version,
        "result_id": result.result_id,
        "status": result.status.value,
        "reason_codes": [item.value for item in result.reason_codes],
        "repository": result.repository,
        "issue_number": result.issue_number,
        "handoff_id": result.handoff_id,
        "resume_command": result.resume_command,
        "local_gh_absence_is_execution_blocker": result.local_gh_absence_is_execution_blocker,
        "repository_implementation_authorized": result.repository_implementation_authorized,
        "execution_authorized": result.execution_authorized,
        "github_writes_authorized": result.github_writes_authorized,
        "merge_authorized": result.merge_authorized,
        "issue_closure_authorized": result.issue_closure_authorized,
        "external_writes_authorized": result.external_writes_authorized,
        "scheduler_invoked": result.scheduler_invoked,
        "handoff_persisted": result.handoff_persisted,
        "side_effects_performed": result.side_effects_performed,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
