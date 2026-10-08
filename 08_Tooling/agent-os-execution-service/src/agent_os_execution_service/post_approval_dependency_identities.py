"""Canonical post-approval dependency identities for #3413 (decision point 3).

Post-approval consumers rebuild the candidate through
``prepare_candidate_packet`` in post-approval mode, where the only way
canonical dependency identities enter a stage result is the caller-supplied
``dependency_identity_evidence``. Calling without it fails closed with
``dependency-identity.not-supplied`` -- truthful, but it makes every
first-packet-approved candidate unconsumable.

This module builds that evidence from the structured IssuePlan ``depends_on``
governed field: the consumer's own ``IssueSourceReader`` re-reads the issue,
the existing public IssuePlan scanner extracts the canonical
``owner/repository#NNNN`` identities, and the shared pure extractor
(``readiness_stage.dependency_identity_evidence_from_scan``) builds the
evidence. Identities never come from prose, labels, PR text, timeline events,
sub-issues, generic CI, or guessed state.

Safety: the rebuilt pipeline strictly compares the ``source`` and
``issueplan`` stage identities against the approved packet, so identities
derived from a changed issue body fail closed as drift before they can
authorize anything. A scan that cannot yield a structured finding returns
``None`` and the consumer keeps the existing fail-closed not-supplied path.
"""

from __future__ import annotations

from scripts.agent_os_candidate_packet.readiness_stage import (
    dependency_identity_evidence_from_scan,
)
from scripts.agent_os_candidate_packet.source_stage import resolve_issue_snapshot
from scripts.agent_os_candidate_packet.stage_models import (
    DependencyIdentityEvidence,
    DependencyIdentityStatus,
    IssueSourceReader,
    IssueSourceStageStatus,
)
from scripts.agent_os_issue_acceptance.issueplan_scanner import (
    SourceEnvelope,
    scan_issueplan_source,
)


def post_approval_dependency_identity_evidence(
    *,
    issue_reader: IssueSourceReader,
    repository: str,
    issue_number: int,
    observed_at: str,
) -> DependencyIdentityEvidence | None:
    """Build post-approval dependency identities from the structured IssuePlan.

    Returns canonical ``DependencyIdentityEvidence`` from the scanned
    ``depends_on`` governed field, or ``None`` when no usable structured
    source exists (unreadable issue, or no single parsed IssuePlan
    candidate). A present-but-malformed ``depends_on`` yields explicit
    ``UNAVAILABLE`` evidence. Pure read-only composition: one issue read
    plus the existing public scanner; no writes, no inference.
    """
    source_result = resolve_issue_snapshot(
        repository, issue_number, issue_reader, retrieved_at=observed_at
    )
    if source_result.status is not IssueSourceStageStatus.RESOLVED:
        return None
    snapshot = source_result.snapshot
    assert snapshot is not None
    envelope = SourceEnvelope(
        source_locator=f"github:{repository}#{issue_number}",
        source_revision=snapshot.source_revision,
        content=snapshot.body,
        source_family="github-issue",
        retrieval_complete=True,
        pagination_complete=True,
        accessible=True,
    )
    scan_result = scan_issueplan_source(envelope)
    # No strict_valid gate: dependency_identity_evidence_from_scan already
    # fails closed (None) on ambiguous/unparsable scans. A single malformed
    # candidate (malformed depends_on) is explicit UNAVAILABLE, never a
    # guess and never silently treated as "no dependencies".
    provenance = (
        f"issueplan:depends_on@{envelope.source_locator}@{envelope.source_revision}"
    )
    candidates = scan_result.candidates
    if len(candidates) == 1 and candidates[0].malformed:
        return DependencyIdentityEvidence(
            status=DependencyIdentityStatus.UNAVAILABLE,
            reason_codes=("dependency-identity.malformed-source",),
            provenance=(provenance,),
        )
    return dependency_identity_evidence_from_scan(
        scan_result, provenance=provenance
    )


__all__ = ["post_approval_dependency_identity_evidence"]
