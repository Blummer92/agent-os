"""Canonical lifecycle-stage acquisition for one GitHub issue (#3433).

A deterministic, pure-local *evaluator* -- not a reader, scheduler, router,
approval system, or persistence store. It consumes only caller-supplied
canonical evidence and derives a :class:`LifecycleStage` exactly when that
evidence unambiguously establishes one stage. Anything else fails closed
with a named, reason-coded ``unavailable`` or ``manual-review`` outcome.

Canonical evidence contract
---------------------------
- Issue identity, state, content-addressed ``github-issue-v1:<sha256>``
  revision, repository SHA, and observation timestamp are caller-supplied
  and re-echoed on the result as currentness bindings.
- PR-lineage evidence is a bounded tuple of already-read PR facts. Each
  claim's linkage to the issue is re-verified here with the existing
  GitHub-authoritative ``parse_pr.parse_linked_issue_result`` parser; a
  caller assertion alone is never trusted.
- Lineage completeness is a caller attestation
  (:class:`PrLineageEnumeration`). An incomplete enumeration can never
  prove the absence of a PR, so it fails closed instead of defaulting.

What this module never does
---------------------------
- No GitHub reads, writes, or client construction.
- No lifecycle inference from labels, issue prose, branch names, issue age,
  timestamps, scanner order, issue number, or AI judgment.
- ``planning`` and ``implementation`` are never emitted: with no verified
  PR lineage the absence of a PR proves neither stage, and no governed
  implementation-activity signal exists for arbitrary backlog issues yet.
  That signal is an explicit remaining prerequisite, not a silent default.
- ``primary_claims`` and ``approval_applicability`` remain separately
  governed boundaries; this module builds no ``PrimaryIssueClaim``.

Production seam
---------------
``lifecycle_stage_from_acquisition`` adapts an acquired result to the
``LifecycleStage | None`` input of ``LiveCandidateEvidence`` /
``LiveCurrentIssueSnapshotReader``. ``None`` preserves the existing
``candidate-evidence.no-canonical-lifecycle-stage`` fail-closed behavior.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum

from .issue_operational_state import (
    MAX_PRIMARY_CLAIMS,
    IssueState,
    LifecycleStage,
)
from .models import LinkedIssueParseStatus
from .parse_pr import parse_linked_issue_result

LIFECYCLE_STAGE_ACQUISITION_SCHEMA_NAME = "agent-os-lifecycle-stage-acquisition"
LIFECYCLE_STAGE_ACQUISITION_SCHEMA_VERSION = "1.0"

MAX_ENUMERATION_NOTE_CHARS = 512
MAX_PR_TITLE_CHARS = 4096
MAX_PR_BODY_CHARS = 65536

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_ISSUE_REVISION_RE = re.compile(r"^github-issue-v1:[0-9a-f]{64}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
# PR bodies, titles, and enumeration notes may legitimately contain tab, LF,
# and CR; only the remaining control characters are rejected.
_BODY_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class LifecycleAcquisitionOutcome(str, Enum):
    ACQUIRED = "acquired"
    UNAVAILABLE = "unavailable"
    MANUAL_REVIEW = "manual-review"


REASON_ACQUIRED = "lifecycle-acquisition.acquired"
REASON_NO_VERIFIED_PR_LINEAGE = "lifecycle-acquisition.no-verified-pr-lineage"
REASON_INCOMPLETE_ENUMERATION = "lifecycle-acquisition.incomplete-enumeration"
REASON_CONFLICTING_PR_CLAIMS = "lifecycle-acquisition.conflicting-pr-claims"
REASON_PR_LINKAGE_UNVERIFIABLE = "lifecycle-acquisition.pr-linkage-unverifiable"
REASON_PR_REPOSITORY_MISMATCH = "lifecycle-acquisition.pr-repository-mismatch"
REASON_CLOSED_UNMERGED_PR = "lifecycle-acquisition.closed-unmerged-pr"

LIFECYCLE_ACQUISITION_REASON_CODES = frozenset(
    {
        REASON_ACQUIRED,
        REASON_NO_VERIFIED_PR_LINEAGE,
        REASON_INCOMPLETE_ENUMERATION,
        REASON_CONFLICTING_PR_CLAIMS,
        REASON_PR_LINKAGE_UNVERIFIABLE,
        REASON_PR_REPOSITORY_MISMATCH,
        REASON_CLOSED_UNMERGED_PR,
    }
)


def _exact_text(value: object, name: str, maximum: int) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be a built-in string")
    if not value or len(value.encode("utf-8")) > maximum or _CONTROL_RE.search(value):
        raise ValueError(f"{name} is outside bounds")
    return value


def _optional_text(value: object, name: str, maximum: int) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be a built-in string")
    if len(value.encode("utf-8")) > maximum or _BODY_CONTROL_RE.search(value):
        raise ValueError(f"{name} is outside bounds")
    return value


def _repository(value: object) -> str:
    text = _exact_text(value, "repository", 255)
    if not _REPOSITORY_RE.fullmatch(text):
        raise ValueError("repository is malformed")
    return text


def _timestamp(value: object, name: str) -> str:
    text = _exact_text(value, name, 20)
    if not _TIMESTAMP_RE.fullmatch(text):
        raise ValueError(f"{name} must use YYYY-MM-DDTHH:MM:SSZ")
    return text


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _result_id(payload: object) -> str:
    material = b"agent-os-lifecycle-stage-acquisition:v1\0" + _canonical_json(
        payload
    ).encode("utf-8")
    return f"lifecycle-stage-acquisition:{hashlib.sha256(material).hexdigest()}"


@dataclass(frozen=True, slots=True)
class VerifiedPrLineage:
    """One already-read PR fact, before linkage verification.

    ``is_open`` / ``is_draft`` / ``is_merged`` are raw GitHub PR facts, not a
    derived classification: ``is_merged`` implies ``not is_open``, and
    ``is_draft`` implies ``is_open``. The linkage of this PR to the issue is
    re-verified by the acquirer with the existing ``parse_pr`` authority;
    supplying the entry asserts nothing by itself.
    """

    pull_request_number: int
    repository: str
    is_open: bool
    is_draft: bool
    is_merged: bool
    head_sha: str
    branch: str
    pr_title: str
    pr_body: str
    observed_at: str

    def __post_init__(self) -> None:
        if type(self.pull_request_number) is not int or self.pull_request_number < 1:
            raise TypeError("pull_request_number must be a positive built-in integer")
        _repository(self.repository)
        for name in ("is_open", "is_draft", "is_merged"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a built-in bool")
        if self.is_merged and self.is_open:
            raise ValueError("a merged pull request cannot be open")
        if self.is_draft and not self.is_open:
            raise ValueError("a draft pull request must be open")
        head_sha = _exact_text(self.head_sha, "head_sha", 40)
        if not _SHA40_RE.fullmatch(head_sha):
            raise ValueError("head_sha must be a lowercase 40-character SHA")
        _exact_text(self.branch, "branch", 255)
        _optional_text(self.pr_title, "pr_title", MAX_PR_TITLE_CHARS)
        _optional_text(self.pr_body, "pr_body", MAX_PR_BODY_CHARS)
        _timestamp(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class PrLineageEnumeration:
    """Caller attestation that the PR-lineage read is complete.

    ``complete`` may only be true when the caller proved full enumeration
    (all pages consumed, no truncation, no partial API failure). An
    incomplete enumeration can never prove that no PR exists, so the
    acquirer fails closed on it.
    """

    complete: bool
    enumeration_note: str = ""

    def __post_init__(self) -> None:
        if type(self.complete) is not bool:
            raise TypeError("complete must be a built-in bool")
        note = _optional_text(self.enumeration_note, "enumeration_note", MAX_ENUMERATION_NOTE_CHARS)
        if self.complete and not note:
            raise ValueError("a complete enumeration requires a non-empty note")
        object.__setattr__(self, "enumeration_note", note)


@dataclass(frozen=True, slots=True)
class LifecycleStageAcquisitionRequest:
    """Canonical evidence input for one lifecycle-stage acquisition."""

    repository: str
    issue_number: int
    issue_state: IssueState
    issue_source_revision: str
    source_revision: str
    observed_at: str
    pr_lineage: tuple[VerifiedPrLineage, ...]
    lineage_enumeration: PrLineageEnumeration

    def __post_init__(self) -> None:
        _repository(self.repository)
        if type(self.issue_number) is not int or self.issue_number < 1:
            raise TypeError("issue_number must be a positive built-in integer")
        if type(self.issue_state) is not IssueState:
            raise TypeError("issue_state must be exact IssueState")
        revision = _exact_text(self.issue_source_revision, "issue_source_revision", 128)
        if not _ISSUE_REVISION_RE.fullmatch(revision):
            raise ValueError("issue_source_revision must use github-issue-v1:<64 lowercase hex>")
        source_revision = _exact_text(self.source_revision, "source_revision", 40)
        if not _SHA40_RE.fullmatch(source_revision):
            raise ValueError("source_revision must be a lowercase 40-character SHA")
        _timestamp(self.observed_at, "observed_at")
        if type(self.pr_lineage) is not tuple:
            raise TypeError("pr_lineage must be an exact tuple")
        if len(self.pr_lineage) > MAX_PRIMARY_CLAIMS:
            raise ValueError("pr_lineage exceeds its bound")
        if any(type(item) is not VerifiedPrLineage for item in self.pr_lineage):
            raise TypeError("pr_lineage must contain exact VerifiedPrLineage values")
        numbers = [item.pull_request_number for item in self.pr_lineage]
        if len(set(numbers)) != len(numbers):
            raise ValueError("pr_lineage contains duplicate pull request numbers")
        if type(self.lineage_enumeration) is not PrLineageEnumeration:
            raise TypeError("lineage_enumeration must be exact PrLineageEnumeration")


@dataclass(frozen=True, slots=True)
class LifecycleStageAcquisitionResult:
    """One deterministic acquisition outcome with currentness bindings.

    ``issue_source_revision`` and ``source_revision`` echo the exact evidence
    the outcome was derived from. A changed issue revision or repository SHA
    therefore never silently reuses a stale result: re-acquisition binds the
    new revisions and yields a different ``result_id``.
    """

    repository: str
    issue_number: int
    issue_source_revision: str
    source_revision: str
    observed_at: str
    outcome: LifecycleAcquisitionOutcome
    lifecycle_stage: LifecycleStage | None
    reason_codes: tuple[str, ...]
    verified_claims: tuple[int, ...]
    result_id: str = ""

    def __post_init__(self) -> None:
        _repository(self.repository)
        if type(self.issue_number) is not int or self.issue_number < 1:
            raise TypeError("issue_number must be a positive built-in integer")
        if not _ISSUE_REVISION_RE.fullmatch(self.issue_source_revision):
            raise ValueError("issue_source_revision is malformed")
        if not _SHA40_RE.fullmatch(self.source_revision):
            raise ValueError("source_revision is malformed")
        if not _TIMESTAMP_RE.fullmatch(self.observed_at):
            raise ValueError("observed_at is malformed")
        if type(self.outcome) is not LifecycleAcquisitionOutcome:
            raise TypeError("outcome must be exact LifecycleAcquisitionOutcome")
        if self.lifecycle_stage is not None and type(self.lifecycle_stage) is not LifecycleStage:
            raise TypeError("lifecycle_stage must be exact LifecycleStage or None")
        if (self.outcome is LifecycleAcquisitionOutcome.ACQUIRED) != (
            self.lifecycle_stage is not None
        ):
            raise ValueError("acquired outcome requires a stage; otherwise the stage must be absent")
        if type(self.reason_codes) is not tuple or not self.reason_codes:
            raise TypeError("reason_codes must be a non-empty exact tuple")
        reasons = tuple(sorted(set(self.reason_codes)))
        if any(type(reason) is not str for reason in reasons):
            raise TypeError("reason_codes must contain built-in strings")
        if any(reason not in LIFECYCLE_ACQUISITION_REASON_CODES for reason in reasons):
            raise ValueError("reason_codes contains an unsupported reason code")
        object.__setattr__(self, "reason_codes", reasons)
        if type(self.verified_claims) is not tuple:
            raise TypeError("verified_claims must be an exact tuple")
        if any(type(number) is not int or number < 1 for number in self.verified_claims):
            raise TypeError("verified_claims must contain positive integers")
        if tuple(sorted(set(self.verified_claims))) != self.verified_claims:
            raise ValueError("verified_claims must be sorted and unique")
        object.__setattr__(self, "verified_claims", tuple(sorted(set(self.verified_claims))))
        expected = _result_id(self._payload())
        if self.result_id and self.result_id != expected:
            raise ValueError("result_id does not match acquisition result content")
        object.__setattr__(self, "result_id", expected)

    def _payload(self) -> dict[str, object]:
        return {
            "schema_name": LIFECYCLE_STAGE_ACQUISITION_SCHEMA_NAME,
            "schema_version": LIFECYCLE_STAGE_ACQUISITION_SCHEMA_VERSION,
            "repository": self.repository,
            "issue_number": self.issue_number,
            "issue_source_revision": self.issue_source_revision,
            "source_revision": self.source_revision,
            "observed_at": self.observed_at,
            "outcome": self.outcome.value,
            "lifecycle_stage": self.lifecycle_stage.value if self.lifecycle_stage else None,
            "reason_codes": list(self.reason_codes),
            "verified_claims": list(self.verified_claims),
        }


def _fail(
    request: LifecycleStageAcquisitionRequest,
    outcome: LifecycleAcquisitionOutcome,
    reason: str,
    verified_claims: tuple[int, ...] = (),
) -> LifecycleStageAcquisitionResult:
    return LifecycleStageAcquisitionResult(
        repository=request.repository,
        issue_number=request.issue_number,
        issue_source_revision=request.issue_source_revision,
        source_revision=request.source_revision,
        observed_at=request.observed_at,
        outcome=outcome,
        lifecycle_stage=None,
        reason_codes=(reason,),
        verified_claims=verified_claims,
    )


def _acquired(
    request: LifecycleStageAcquisitionRequest,
    stage: LifecycleStage,
    verified_claims: tuple[int, ...] = (),
) -> LifecycleStageAcquisitionResult:
    return LifecycleStageAcquisitionResult(
        repository=request.repository,
        issue_number=request.issue_number,
        issue_source_revision=request.issue_source_revision,
        source_revision=request.source_revision,
        observed_at=request.observed_at,
        outcome=LifecycleAcquisitionOutcome.ACQUIRED,
        lifecycle_stage=stage,
        reason_codes=(REASON_ACQUIRED,),
        verified_claims=verified_claims,
    )


def _verify_linkage(
    request: LifecycleStageAcquisitionRequest, claim: VerifiedPrLineage
) -> str | None:
    """Re-verify one PR claim against canonical evidence.

    Returns ``None`` when the claim is verified, else the fail-closed reason.
    Linkage uses the existing GitHub-authoritative ``parse_pr`` parser: only
    a RESOLVED parse whose target is exactly this issue counts as verified
    authoritative linkage. Repository identity is joined independently.
    """
    if claim.repository.casefold() != request.repository.casefold():
        return REASON_PR_REPOSITORY_MISMATCH
    parsed = parse_linked_issue_result(claim.pr_body, claim.pr_title)
    if (
        parsed.status is not LinkedIssueParseStatus.RESOLVED
        or parsed.issue_number != request.issue_number
    ):
        return REASON_PR_LINKAGE_UNVERIFIABLE
    return None


def acquire_lifecycle_stage(
    request: LifecycleStageAcquisitionRequest,
) -> LifecycleStageAcquisitionResult:
    """Derive one issue's lifecycle stage from canonical evidence, or fail closed.

    Pure and deterministic: identical evidence always yields the identical
    result. No I/O, no client, no inference from labels, prose, branch
    names, age, or ordering.
    """
    if type(request) is not LifecycleStageAcquisitionRequest:
        raise TypeError("request must be an exact LifecycleStageAcquisitionRequest")
    request.__post_init__()

    # A closed issue's lifecycle fact is established by GitHub's own
    # structured state field; lineage is not consulted for the stage.
    if request.issue_state is IssueState.CLOSED:
        return _acquired(request, LifecycleStage.CLOSED)

    if not request.lineage_enumeration.complete:
        return _fail(
            request, LifecycleAcquisitionOutcome.UNAVAILABLE, REASON_INCOMPLETE_ENUMERATION
        )

    verified: list[VerifiedPrLineage] = []
    for claim in request.pr_lineage:
        reason = _verify_linkage(request, claim)
        if reason is not None:
            # Never silently drop or reinterpret an unverifiable claim: a
            # competing or misdirected PR claim is a manual-review stop.
            return _fail(
                request, LifecycleAcquisitionOutcome.MANUAL_REVIEW, reason
            )
        verified.append(claim)

    if not verified:
        # A complete enumeration with zero verified claims proves nothing
        # about planning vs implementation: fail closed, never default.
        return _fail(
            request, LifecycleAcquisitionOutcome.UNAVAILABLE, REASON_NO_VERIFIED_PR_LINEAGE
        )
    if len(verified) > 1:
        return _fail(
            request,
            LifecycleAcquisitionOutcome.MANUAL_REVIEW,
            REASON_CONFLICTING_PR_CLAIMS,
            verified_claims=tuple(claim.pull_request_number for claim in verified),
        )

    claim = verified[0]
    verified_number = claim.pull_request_number
    if claim.is_merged:
        return _acquired(request, LifecycleStage.MERGED, verified_claims=(verified_number,))
    if claim.is_open and claim.is_draft:
        return _acquired(
            request, LifecycleStage.DRAFT_PR, verified_claims=(verified_number,)
        )
    if claim.is_open:
        return _acquired(request, LifecycleStage.REVIEW, verified_claims=(verified_number,))
    # Closed without merge: the PR no longer represents live work, so no
    # stage is defensible from this lineage.
    return _fail(
        request,
        LifecycleAcquisitionOutcome.MANUAL_REVIEW,
        REASON_CLOSED_UNMERGED_PR,
        verified_claims=(verified_number,),
    )


def lifecycle_stage_from_acquisition(
    result: LifecycleStageAcquisitionResult,
) -> LifecycleStage | None:
    """Adapt an acquisition result to the ``LiveCandidateEvidence`` stage input.

    Returns the acquired stage, or ``None`` when the acquisition failed
    closed -- preserving the existing
    ``candidate-evidence.no-canonical-lifecycle-stage`` behavior downstream.
    """
    if type(result) is not LifecycleStageAcquisitionResult:
        raise TypeError("result must be an exact LifecycleStageAcquisitionResult")
    if result.outcome is not LifecycleAcquisitionOutcome.ACQUIRED:
        return None
    return result.lifecycle_stage


def acquisition_bindings_current(
    result: LifecycleStageAcquisitionResult,
    *,
    issue_source_revision: str,
    source_revision: str,
) -> bool:
    """Check whether an acquisition result is still current for fresh evidence.

    A changed issue revision or repository SHA means the result was derived
    from superseded evidence; the caller must re-acquire rather than reuse it.
    """
    if type(result) is not LifecycleStageAcquisitionResult:
        raise TypeError("result must be an exact LifecycleStageAcquisitionResult")
    if type(issue_source_revision) is not str or type(source_revision) is not str:
        raise TypeError("revisions must be built-in strings")
    return (
        result.issue_source_revision == issue_source_revision
        and result.source_revision == source_revision
    )
