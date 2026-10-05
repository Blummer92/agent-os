"""Production ``CanonicalCandidateEvidenceReader`` for #3329.

Mirrors the merged #1464 adapter pattern (``live_compute_control_binding``):
a thin binding/adapter boundary that composes genuinely canonical evidence
into ``CandidateIssueEvidence`` and fails closed wherever no canonical live
owner exists. It owns no lifecycle, claim, freshness, dependency, validation,
approval, authorization, or operating-mode semantics of its own.

Target flow:

```text
Live GitHub issue payload (one injected SingleIssueTransport read)
  -> existing canonical owners/adapters (#1464, #1451, operating_mode.py)
  -> CandidateIssueEvidence (exact joins enforced by the model)
  -> existing ExecutableLaneSelection (shadow_issue_selection seam)
```

## Canonical owner for each ``CandidateIssueEvidence`` input

- ``issue_number`` -- the caller-supplied candidate number, joined against the
  live-read snapshot by #1451 (``current issue snapshot issue identity
  mismatch``) and re-joined by the ``CandidateIssueEvidence`` model itself.
- ``operational_state`` -- the unchanged #1451
  ``acquire_issue_operational_state`` composition over the reused #1464
  ``LiveCurrentIssueSnapshotReader`` (issue state, observed labels, the
  content-addressed ``github-issue-v1:<sha256>`` issue revision, and
  ``terminal_disposition`` from GitHub's own structured ``state_reason``
  field) plus the reused #1464 ``dependency_state_from_evidence`` /
  ``validation_state_from_evidence`` projections over the canonical
  ``RepositoryEvidenceReader`` (the #1155 truthful always-``UNAVAILABLE``
  reader when the caller supplies none).
- ``mode_decision`` -- the unchanged
  ``operating_mode.evaluate_operating_mode_decision`` over the acquired
  state, the caller-supplied requested mode, and caller-supplied
  ``EnvironmentCapabilityEvidence``. The ``state_id`` join is preserved
  inside the evaluator (``source_operational_state_id``) and re-checked by
  the ``CandidateIssueEvidence`` model.
- Every other required input -- caller-supplied canonical evidence only.
  Nothing here infers meaning from issue prose, labels, timestamps, scanner
  ordering, issue number, or AI judgment.

## Fail-closed, never manufactured

For every required field, canonical evidence available means adapt/reuse;
canonical evidence unavailable or ambiguous means return ``None`` with a
named ``candidate-evidence.*`` reason (surfacing as the seam's
``shadow-selection.candidate-evidence-incomplete``). In particular:

- ``source_revision`` (repository SHA): no canonical live owner in the
  shadow path -> ``candidate-evidence.no-canonical-repository-source-revision``.
- ``lifecycle_stage``: no canonical lifecycle authority -> fail closed.
- ``primary_claims``: no canonical live PR-linkage reader; #1460 forbids
  inventing a claim authority -> fail closed.
- ``approval_applicability``: the approval evidence graph is not
  reconstructible for arbitrary backlog issues -> fail closed.
- ``freshness_state``: no general-purpose currentness owner -> fail closed.
- ``dependency_depth`` / ``substitutable``: caller-supplied request context
  with no canonical live owner -> fail closed (never defaulted).
- ``requested_mode``: absent means absent; ``evaluate_operating_mode_decision``
  would silently default an absent mode to ``PLANNING`` with a
  ``mode.missing`` blocker, so the reader refuses to launder that default
  and fails closed instead.
- ``environment``: no canonical environment-capability owner in the shadow
  path -> fail closed.
- Live-read failures: the transport outcome is surfaced as
  ``candidate-evidence.issue-read-failed:<outcome>``; anything else the
  composition chain rejects (identity-join violations, unmappable evidence)
  becomes ``candidate-evidence.composition-contract-violation`` with the
  underlying message preserved as diagnostic detail.

## No second GitHub client

Like #1464, this module creates no GitHub client: the live read runs over a
caller-injected ``SingleIssueTransport`` -- the same seam
``scripts.agent_os_candidate_packet_live_input.LiveIssueReader`` already
uses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from scripts.agent_os_candidate_packet.executable_lane_selection import (
    CandidateIssueEvidence,
)
from scripts.agent_os_candidate_packet.stage_models import RepositoryEvidenceReader
from scripts.agent_os_candidate_packet_live_input import SingleIssueTransport

from .approval_records import ApprovalApplicabilityResult
from .issue_operational_state import (
    DependencyState,
    FreshnessState,
    LifecycleStage,
    PrimaryIssueClaim,
    TerminalDisposition,
    ValidationState,
)
from .issue_operational_state_acquisition import (
    CurrentIssueSnapshot,
    acquire_issue_operational_state,
)
from .live_compute_control_binding import (
    LiveCurrentIssueSnapshotReader,
    dependency_state_from_evidence,
    validation_state_from_evidence,
)
from .operating_mode import (
    EnvironmentCapabilityEvidence,
    evaluate_operating_mode_decision,
)

# Reason codes emitted when the reader fails closed. Every code names the
# missing or conflicting canonical owner; none of them manufactures evidence.
REASON_MISSING_REPOSITORY_SOURCE_REVISION = (
    "candidate-evidence.no-canonical-repository-source-revision"
)
REASON_MISSING_LIFECYCLE_STAGE = "candidate-evidence.no-canonical-lifecycle-stage"
REASON_MISSING_PRIMARY_CLAIMS = "candidate-evidence.no-canonical-primary-claims"
REASON_MISSING_APPROVAL_APPLICABILITY = (
    "candidate-evidence.no-canonical-approval-applicability"
)
REASON_MISSING_FRESHNESS_STATE = "candidate-evidence.no-canonical-freshness-state"
REASON_MISSING_DEPENDENCY_DEPTH = "candidate-evidence.no-canonical-dependency-depth"
REASON_MISSING_SUBSTITUTABLE = "candidate-evidence.no-canonical-substitutable"
REASON_MISSING_REQUESTED_MODE = "candidate-evidence.no-canonical-requested-mode"
REASON_MISSING_ENVIRONMENT = "candidate-evidence.no-canonical-environment-capability"
REASON_REPOSITORY_MISMATCH = "candidate-evidence.repository-identity-mismatch"
REASON_COMPOSITION_CONTRACT_VIOLATION = (
    "candidate-evidence.composition-contract-violation"
)

# ``LiveCurrentIssueSnapshotReader.read_current_issue`` raises
# ``ValueError(f"live issue read did not succeed: {result.status.value}")``
# when the transport outcome is not OK. This prefix maps that one known
# same-package message to the bounded transport-outcome reason below; any
# other composition failure keeps the generic contract-violation reason.
_ISSUE_READ_FAILURE_PREFIX = "live issue read did not succeed: "
_ISSUE_READ_FAILURE_RE = re.compile(
    r"^live issue read did not succeed: ([a-z][a-z-]*)$"
)


def _issue_read_failure_reason(exc: ValueError) -> str | None:
    match = _ISSUE_READ_FAILURE_RE.match(str(exc))
    if match is None:
        return None
    return f"candidate-evidence.issue-read-failed:{match.group(1)}"


@dataclass(frozen=True, slots=True)
class LiveCandidateEvidence:
    """Already-acquired canonical evidence for one #3329 production read.

    Every field is either produced by this module's own live read (the issue
    snapshot, over the injected transport) or is a caller-supplied result
    from an existing canonical owner, as documented in this module's
    docstring. ``None`` on any required canonical input is not a default: it
    is the honest "no canonical live owner" marker and makes the reader fail
    closed with the named reason for that input. Nothing here infers meaning
    from issue prose or labels.
    """

    repository: str
    issue_transport: SingleIssueTransport
    observed_at: str
    source_revision: str | None
    lifecycle_stage: LifecycleStage | None
    primary_claims: tuple[PrimaryIssueClaim, ...] | None
    approval_applicability: ApprovalApplicabilityResult | None
    freshness_state: FreshnessState | None
    requested_mode: str | None
    environment: EnvironmentCapabilityEvidence | None
    dependency_depth: int | None
    substitutable: bool | None
    dependency_reader: RepositoryEvidenceReader | None = None
    terminal_disposition: TerminalDisposition | None = None

    def __post_init__(self) -> None:
        if (
            type(self.repository) is not str
            or not self.repository
            or "/" not in self.repository
        ):
            raise ValueError("repository must use owner/name form")
        if self.issue_transport is None:
            raise TypeError("issue_transport is required")
        if type(self.observed_at) is not str or not self.observed_at:
            raise TypeError("observed_at must be non-empty built-in text")
        if self.source_revision is not None and (
            type(self.source_revision) is not str or not self.source_revision
        ):
            raise TypeError("source_revision must be non-empty built-in text or None")
        if self.lifecycle_stage is not None and type(self.lifecycle_stage) is not LifecycleStage:
            raise TypeError("lifecycle_stage must be exact LifecycleStage or None")
        if self.primary_claims is not None and (
            type(self.primary_claims) is not tuple
            or any(type(claim) is not PrimaryIssueClaim for claim in self.primary_claims)
        ):
            raise TypeError(
                "primary_claims must be an exact tuple[PrimaryIssueClaim, ...] or None"
            )
        if self.approval_applicability is not None and type(
            self.approval_applicability
        ) is not ApprovalApplicabilityResult:
            raise TypeError(
                "approval_applicability must be exact ApprovalApplicabilityResult or None"
            )
        if self.freshness_state is not None and type(self.freshness_state) is not FreshnessState:
            raise TypeError("freshness_state must be exact FreshnessState or None")
        if self.requested_mode is not None and (
            type(self.requested_mode) is not str or not self.requested_mode.strip()
        ):
            raise TypeError("requested_mode must be non-blank built-in text or None")
        if self.environment is not None and type(self.environment) is not EnvironmentCapabilityEvidence:
            raise TypeError(
                "environment must be exact EnvironmentCapabilityEvidence or None"
            )
        if self.dependency_depth is not None and (
            type(self.dependency_depth) is not int or self.dependency_depth < 0
        ):
            raise TypeError("dependency_depth must be a non-negative built-in int or None")
        if self.substitutable is not None and type(self.substitutable) is not bool:
            raise TypeError("substitutable must be an exact bool or None")
        if self.terminal_disposition is not None and type(
            self.terminal_disposition
        ) is not TerminalDisposition:
            raise TypeError(
                "terminal_disposition must be exact TerminalDisposition or None"
            )


@dataclass(frozen=True, slots=True)
class CandidateEvidenceReadOutcome:
    """One reader attempt: evidence, or the named fail-closed reason.

    Exactly one of ``evidence`` / ``failure_reason`` is set. ``failure_detail``
    carries the underlying diagnostic text for a contract violation; it is
    never a substitute for the bounded ``failure_reason`` code.
    """

    evidence: CandidateIssueEvidence | None
    failure_reason: str | None
    failure_detail: str | None = None

    def __post_init__(self) -> None:
        if (self.evidence is None) == (self.failure_reason is None):
            raise ValueError("outcome must carry evidence or a failure reason, not both")
        if self.evidence is not None and type(self.evidence) is not CandidateIssueEvidence:
            raise TypeError("evidence must be exact CandidateIssueEvidence or None")
        if self.failure_reason is not None and (
            type(self.failure_reason) is not str or not self.failure_reason
        ):
            raise TypeError("failure_reason must be non-empty built-in text or None")
        if self.failure_detail is not None and type(self.failure_detail) is not str:
            raise TypeError("failure_detail must be built-in text or None")


@dataclass(frozen=True, slots=True)
class LiveCandidateEvidenceReader:
    """Production ``CanonicalCandidateEvidenceReader`` over injected canonical evidence.

    Holds one ``LiveCandidateEvidence`` bundle (already-acquired canonical
    inputs plus the injected transport) and, per admitted candidate, performs
    the one live issue read and composes exact ``CandidateIssueEvidence``
    through the unchanged #1451 / operating-mode owners. Any missing or
    conflicting canonical evidence fails closed to ``None`` with the named
    reason from ``read_candidate_evidence_detailed`` -- which the shadow seam
    reports as ``shadow-selection.candidate-evidence-incomplete``.
    """

    evidence: LiveCandidateEvidence

    def __post_init__(self) -> None:
        if type(self.evidence) is not LiveCandidateEvidence:
            raise TypeError("evidence must be exact LiveCandidateEvidence")
        self.evidence.__post_init__()

    def read_candidate_evidence(
        self, repository: str, issue_number: int
    ) -> CandidateIssueEvidence | None:
        """Satisfy the ``CanonicalCandidateEvidenceReader`` protocol.

        Fail-closed: ``None`` wherever no canonical live owner exists for a
        required input, or the live/composed evidence conflicts.
        """
        return self.read_candidate_evidence_detailed(repository, issue_number).evidence

    def read_candidate_evidence_detailed(
        self, repository: str, issue_number: int
    ) -> CandidateEvidenceReadOutcome:
        """Compose evidence, or name the exact fail-closed reason."""
        bundle = self.evidence
        if type(repository) is not str or repository.casefold() != bundle.repository.casefold():
            return CandidateEvidenceReadOutcome(
                evidence=None, failure_reason=REASON_REPOSITORY_MISMATCH
            )
        if type(issue_number) is not int or issue_number < 1:
            return CandidateEvidenceReadOutcome(
                evidence=None,
                failure_reason=REASON_COMPOSITION_CONTRACT_VIOLATION,
                failure_detail="issue_number must be a positive built-in integer",
            )
        # Fail closed in canonical-input order before any live read: each
        # missing input names the semantic owner that must supply it.
        missing: tuple[tuple[object, str], ...] = (
            (bundle.source_revision, REASON_MISSING_REPOSITORY_SOURCE_REVISION),
            (bundle.lifecycle_stage, REASON_MISSING_LIFECYCLE_STAGE),
            (bundle.primary_claims, REASON_MISSING_PRIMARY_CLAIMS),
            (bundle.approval_applicability, REASON_MISSING_APPROVAL_APPLICABILITY),
            (bundle.freshness_state, REASON_MISSING_FRESHNESS_STATE),
            (bundle.dependency_depth, REASON_MISSING_DEPENDENCY_DEPTH),
            (bundle.substitutable, REASON_MISSING_SUBSTITUTABLE),
            (bundle.requested_mode, REASON_MISSING_REQUESTED_MODE),
            (bundle.environment, REASON_MISSING_ENVIRONMENT),
        )
        for value, reason in missing:
            if value is None:
                return CandidateEvidenceReadOutcome(evidence=None, failure_reason=reason)
        try:
            return CandidateEvidenceReadOutcome(
                evidence=_compose_candidate_evidence(bundle, repository, issue_number),
                failure_reason=None,
            )
        except ValueError as exc:
            reason = _issue_read_failure_reason(exc)
            if reason is not None:
                return CandidateEvidenceReadOutcome(evidence=None, failure_reason=reason)
            return CandidateEvidenceReadOutcome(
                evidence=None,
                failure_reason=REASON_COMPOSITION_CONTRACT_VIOLATION,
                failure_detail=str(exc),
            )
        except TypeError as exc:
            return CandidateEvidenceReadOutcome(
                evidence=None,
                failure_reason=REASON_COMPOSITION_CONTRACT_VIOLATION,
                failure_detail=str(exc),
            )


def _compose_candidate_evidence(
    bundle: LiveCandidateEvidence, repository: str, issue_number: int
) -> CandidateIssueEvidence:
    """The governed composition: one live read, #1451, operating mode, join-checked model.

    Reuses the #1464 ``LiveCurrentIssueSnapshotReader`` for the canonical
    live sub-fields (issue state, observed labels, content-addressed issue
    revision, terminal disposition from ``state_reason``), the unchanged #1451
    ``acquire_issue_operational_state`` for the operational state (identity
    joins enforced inside), and the unchanged
    ``evaluate_operating_mode_decision`` for the mode decision (the
    ``state_id`` join preserved by the evaluator and re-checked by the
    ``CandidateIssueEvidence`` model). Missing, conflicting, or malformed
    required evidence raises; the caller converts that to the named
    fail-closed outcome. No GitHub write, no execution authorization, no
    other external-system mutation.
    """
    assert bundle.source_revision is not None
    assert bundle.lifecycle_stage is not None
    assert bundle.primary_claims is not None
    assert bundle.approval_applicability is not None
    assert bundle.freshness_state is not None
    assert bundle.requested_mode is not None
    assert bundle.environment is not None
    assert bundle.dependency_depth is not None
    assert bundle.substitutable is not None

    snapshot_reader = LiveCurrentIssueSnapshotReader(
        transport=bundle.issue_transport,
        source_revision=bundle.source_revision,
        observed_at=bundle.observed_at,
        lifecycle_stage=bundle.lifecycle_stage,
        terminal_disposition_override=bundle.terminal_disposition,
    )

    def approval_acquirer(
        _snapshot: CurrentIssueSnapshot,
    ) -> ApprovalApplicabilityResult:
        return bundle.approval_applicability

    def dependency_acquirer(_snapshot: CurrentIssueSnapshot) -> DependencyState:
        if bundle.dependency_reader is None:
            return DependencyState.UNKNOWN
        return dependency_state_from_evidence(
            bundle.dependency_reader.read_dependency_evidence(
                bundle.repository, issue_number
            )
        )

    def claim_acquirer(
        _snapshot: CurrentIssueSnapshot,
    ) -> tuple[PrimaryIssueClaim, ...]:
        return bundle.primary_claims

    def validation_acquirer(_snapshot: CurrentIssueSnapshot) -> ValidationState:
        if bundle.dependency_reader is None:
            return ValidationState.NOT_RUN
        return validation_state_from_evidence(
            bundle.dependency_reader.read_validation_evidence(
                bundle.repository, issue_number
            )
        )

    def freshness_acquirer(_snapshot: CurrentIssueSnapshot) -> FreshnessState:
        return bundle.freshness_state

    acquired = acquire_issue_operational_state(
        repository=repository,
        issue_number=issue_number,
        issue_reader=snapshot_reader,
        approval_acquirer=approval_acquirer,
        dependency_acquirer=dependency_acquirer,
        claim_acquirer=claim_acquirer,
        validation_acquirer=validation_acquirer,
        freshness_acquirer=freshness_acquirer,
    )
    state = acquired.operational_state

    mode_decision = evaluate_operating_mode_decision(
        state, bundle.requested_mode, bundle.environment
    )

    return CandidateIssueEvidence(
        issue_number=issue_number,
        operational_state=state,
        mode_decision=mode_decision,
        dependency_depth=bundle.dependency_depth,
        substitutable=bundle.substitutable,
    )
