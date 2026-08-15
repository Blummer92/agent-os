"""AOS-AUTO1H live-input adapter package for #1105's ``prepare_candidate_packet``.

Sibling to ``scripts.agent_os_candidate_packet`` (deliberately network/
subprocess-free) and to ``scripts.agent_os_github_issue_provider`` (a
separate paginated-listing contract for a different consumer). This package
supplies production ``IssueSourceReader`` / ``RepositoryEvidenceReader``
implementations plus a ``verify-repo-state.sh``-backed ``RepositoryObservation``
assembler, so a caller can invoke the unchanged
``scripts.agent_os_candidate_packet.prepare_candidate_packet(...)`` entrypoint
against real GitHub/repository evidence instead of a hand-authored fixture.

See ``README.md`` for the field-derivation and inference boundaries.
"""

from __future__ import annotations

from .issue_reader import (
    LiveIssueReader,
    SingleIssueTransport,
    SingleIssueTransportOutcome,
    SingleIssueTransportResult,
)
from .repository_observation import (
    VerifierStdoutError,
    build_repository_observation_from_verifier_stdout,
    parse_verifier_stdout,
)
from .repository_reader import (
    DEPENDENCY_NO_STRUCTURED_SOURCE_REASON,
    VALIDATION_NO_STRUCTURED_SOURCE_REASON,
    LiveRepositoryEvidenceReader,
)

__all__ = [
    "LiveIssueReader",
    "SingleIssueTransport",
    "SingleIssueTransportOutcome",
    "SingleIssueTransportResult",
    "VerifierStdoutError",
    "build_repository_observation_from_verifier_stdout",
    "parse_verifier_stdout",
    "DEPENDENCY_NO_STRUCTURED_SOURCE_REASON",
    "VALIDATION_NO_STRUCTURED_SOURCE_REASON",
    "LiveRepositoryEvidenceReader",
]
