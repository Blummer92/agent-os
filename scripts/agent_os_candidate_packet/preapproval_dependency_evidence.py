"""Bounded pre-approval issue-dependency evidence producer (#3354).

First-packet mode only. This module turns the canonical structured
``depends_on`` identities from an IssuePlan (issueplan-core/v1) into
``DependencyEvidence`` about the *issue-dependency graph*: each declared
dependency's current issue state (open/closed) is read through the injected
``IssueSourceReader`` -- in production a ``LiveIssueReader`` over the existing
``SingleIssueTransport``.

This evidence is strictly separate from the #1185/#1197 runtime-package
``DependencyReadinessEvidence`` consumed post-approval: it describes whether
the issue's declared issue dependencies are resolved, not whether a runtime
package's dependencies are prepared. It is not a second dependency system --
it has no scheduler, no transitive traversal (direct dependencies only), no
persistence, and performs no writes.

Identities enter only through the ``dependency_identities`` parameter, which
callers derive from the scanned IssuePlan ``depends_on`` field. Nothing here
reads issue prose, comments, labels, PR state, CI status, or any other
unstructured surface (#776).
"""

from __future__ import annotations

from collections.abc import Mapping

from scripts.agent_os_issue_acceptance.issueplan_scanner import normalize_depends_on

from .stage_models import (
    DependencyEvidence,
    EvidenceStatus,
    IssueReadStatus,
    IssueSourceReader,
)

_READER_ERRORS = (TypeError, ValueError, PermissionError, LookupError, RuntimeError)

_NO_DEPENDENCIES_REASON = "dependency-graph.no-dependencies-declared"
_ALL_CLOSED_REASON = "dependency-graph.all-dependencies-closed"
_OPEN_DEPENDENCIES_REASON = "dependency-graph.open-dependencies"
_STATE_UNAVAILABLE_REASON = "dependency-graph.state-unavailable"
_IDENTITY_MALFORMED_REASON = "dependency-graph.identity-malformed"


def parse_depends_on_identity(identity: object) -> tuple[str, int] | None:
    """Split one canonical ``owner/repository#NNNN`` identity.

    Returns ``(repository, issue_number)`` or ``None`` when the identity is
    not canonical. The scanner already normalizes identities; this is
    defense-in-depth so a non-canonical identity can never reach a transport.
    """
    normalized = normalize_depends_on([identity])
    if normalized is None or len(normalized) != 1:
        return None
    canonical = normalized[0]
    repository, _, number = canonical.rpartition("#")
    return repository, int(number)


def build_preapproval_dependency_evidence(
    *,
    repository: str,
    dependency_identities: tuple[str, ...],
    issue_reader: IssueSourceReader,
    provenance: str,
) -> DependencyEvidence:
    """Read each declared dependency's current issue state, fail-closed.

    * no identities -> ``RESOLVED_CLEAR`` (the structured source declared none);
    * every dependency closed -> ``RESOLVED_CLEAR``;
    * any dependency open -> ``RESOLVED_BLOCKED``;
    * any identity malformed, unreadable, or reporting a non-open/closed
      state -> ``UNAVAILABLE`` (the graph state is unknowable, never guessed).

    ``provenance`` names the structured source the identities came from; it is
    recorded in details, never used to authorize anything.
    """
    _require_provenance(provenance)
    identities = tuple(dependency_identities)
    if not identities:
        return DependencyEvidence(
            status=EvidenceStatus.RESOLVED_CLEAR,
            reason_codes=(_NO_DEPENDENCIES_REASON,),
            details=(f"provenance={provenance}",),
        )

    parsed: list[tuple[str, str, int]] = []
    for identity in identities:
        split = parse_depends_on_identity(identity)
        if split is None:
            return DependencyEvidence(
                status=EvidenceStatus.UNAVAILABLE,
                reason_codes=(_IDENTITY_MALFORMED_REASON,),
                details=(f"malformed-identity={identity}", f"provenance={provenance}"),
            )
        parsed.append((identity, split[0], split[1]))

    open_dependencies: list[str] = []
    closed_dependencies: list[str] = []
    unavailable: list[str] = []
    for identity, dependency_repository, dependency_number in parsed:
        try:
            result = issue_reader.read_issue(dependency_repository, dependency_number)
        except _READER_ERRORS as error:
            unavailable.append(f"{identity}:reader-error:{error}")
            continue
        if result.status != IssueReadStatus.OK or not isinstance(result.item, Mapping):
            unavailable.append(f"{identity}:{result.status.value}")
            continue
        state = result.item.get("state")
        if state == "closed":
            closed_dependencies.append(identity)
        elif state == "open":
            open_dependencies.append(identity)
        else:
            unavailable.append(f"{identity}:malformed-state:{state!r}")

    details = (f"provenance={provenance}",)
    if unavailable:
        return DependencyEvidence(
            status=EvidenceStatus.UNAVAILABLE,
            reason_codes=(_STATE_UNAVAILABLE_REASON,),
            details=(*details, *(f"unavailable={item}" for item in unavailable)),
        )
    if open_dependencies:
        return DependencyEvidence(
            status=EvidenceStatus.RESOLVED_BLOCKED,
            reason_codes=(_OPEN_DEPENDENCIES_REASON,),
            details=(
                *details,
                *(f"open={item}" for item in open_dependencies),
                *(f"closed={item}" for item in closed_dependencies),
            ),
        )
    return DependencyEvidence(
        status=EvidenceStatus.RESOLVED_CLEAR,
        reason_codes=(_ALL_CLOSED_REASON,),
        details=(*details, *(f"closed={item}" for item in closed_dependencies)),
    )


def _require_provenance(provenance: object) -> None:
    if not isinstance(provenance, str) or not provenance.strip():
        raise ValueError("provenance must be a non-empty string")
    if any(character < " " or character == "\x7f" for character in provenance):
        raise ValueError("provenance must not contain control characters")
