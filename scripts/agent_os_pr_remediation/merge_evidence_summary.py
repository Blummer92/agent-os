"""Pure-local truthful review and merge-evidence projection for one PR lineage.

The projection consumes already-owned evidence only. It performs no GitHub or
provider I/O, does not select review depth, does not authorize merge/closure,
and never treats workflow/check completion as proof of semantic success.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Iterable

from .models import EvidenceValidationError, deterministic_id

MAX_ITEMS = 256
MAX_TEXT = 10_000


class EvidenceStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    NOT_APPLICABLE = "not-applicable"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    MANUAL_REVIEW = "manual-review"


class ReviewStatus(str, Enum):
    PERFORMED_CLEAR = "performed-clear"
    PERFORMED_BLOCKED = "performed-blocked"
    SKIPPED = "skipped"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    NOT_REQUIRED = "not-required"


class MergeEvidenceStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    STALE = "stale"
    BLOCKED = "blocked"


class PostMergeClassification(str, Enum):
    MERGE_SHA_INDEPENDENT_EVIDENCE = "merge-sha-independent-evidence"
    PRE_MERGE_RUN_DRAINING = "pre-merge-run-draining"
    DUPLICATE_NONUNIQUE_EVIDENCE = "duplicate-nonunique-evidence"
    SUPERSEDED = "superseded"
    MANUAL_REVIEW = "manual-review"


@dataclass(frozen=True, slots=True)
class ValidationEvidence:
    name: str
    status: EvidenceStatus
    tested_sha: str | None = None
    profile: str | None = None
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AcceptanceEvidence:
    transport_completed: bool
    status: EvidenceStatus
    metadata_fingerprint: str | None
    current_metadata_fingerprint: str | None
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AIReviewEvidence:
    provider: str
    status: ReviewStatus
    reviewed_sha: str | None
    unresolved_finding_ids: tuple[str, ...] = ()
    resolved_finding_ids: tuple[str, ...] = ()
    invalidated_finding_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReviewMergeEvidenceSummary:
    repository: str
    pr_number: int
    source_head_sha: str
    base_sha: str | None
    synthetic_merge_sha: str | None
    merge_commit_sha: str | None
    locally_tested_sha: str | None
    acceptance: AcceptanceEvidence
    focused_validation: tuple[ValidationEvidence, ...]
    aggregate_validation: ValidationEvidence
    language_validation: tuple[ValidationEvidence, ...]
    specialized_validation: tuple[ValidationEvidence, ...]
    normal_review: AIReviewEvidence
    adversarial_review: AIReviewEvidence
    unresolved_finding_ids: tuple[str, ...]
    merge_evidence_status: MergeEvidenceStatus
    reason_codes: tuple[str, ...]
    execution_authorized: bool = False
    merge_authorized: bool = False
    closure_authorized: bool = False
    production_authorized: bool = False
    external_write_authorized: bool = False
    side_effects_performed: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["merge_evidence_status"] = self.merge_evidence_status.value
        for key in ("focused_validation", "language_validation", "specialized_validation"):
            payload[key] = [
                {**item, "status": item["status"].value}
                for item in payload[key]
            ]
        payload["aggregate_validation"]["status"] = payload["aggregate_validation"]["status"].value
        payload["acceptance"]["status"] = payload["acceptance"]["status"].value
        payload["normal_review"]["status"] = payload["normal_review"]["status"].value
        payload["adversarial_review"]["status"] = payload["adversarial_review"]["status"].value
        return payload

    @property
    def summary_id(self) -> str:
        return deterministic_id(self.to_dict())


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value or len(value) > MAX_TEXT:
        raise EvidenceValidationError(f"{field} must be a bounded non-empty string")
    return value


def _sha(value: object, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    text = _text(value, field).lower()
    if len(text) != 40 or any(char not in "0123456789abcdef" for char in text):
        raise EvidenceValidationError(f"{field} must be a 40-character hexadecimal SHA")
    return text


def _fingerprint(value: object, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    text = _text(value, field).lower()
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise EvidenceValidationError(f"{field} must be a SHA-256 hexadecimal digest")
    return text


def _items(values: Iterable[str], field: str) -> tuple[str, ...]:
    if type(values) not in {tuple, list} or len(values) > MAX_ITEMS:
        raise EvidenceValidationError(f"{field} must be a bounded list or tuple")
    result = tuple(_text(value, f"{field} item") for value in values)
    if len(set(result)) != len(result):
        raise EvidenceValidationError(f"{field} contains duplicates")
    return tuple(sorted(result))


def validation_evidence(
    *,
    name: str,
    status: EvidenceStatus,
    tested_sha: str | None = None,
    profile: str | None = None,
    reason_codes: tuple[str, ...] | list[str] = (),
) -> ValidationEvidence:
    if type(status) is not EvidenceStatus:
        raise EvidenceValidationError("validation status must be EvidenceStatus")
    return ValidationEvidence(
        name=_text(name, "validation name"),
        status=status,
        tested_sha=_sha(tested_sha, "tested_sha", optional=True),
        profile=None if profile is None else _text(profile, "validation profile"),
        reason_codes=_items(reason_codes, "validation reason_codes"),
    )


def acceptance_evidence(
    *,
    transport_completed: bool,
    status: EvidenceStatus,
    metadata_fingerprint: str | None,
    current_metadata_fingerprint: str | None,
    reason_codes: tuple[str, ...] | list[str] = (),
) -> AcceptanceEvidence:
    if type(transport_completed) is not bool or type(status) is not EvidenceStatus:
        raise EvidenceValidationError("acceptance transport/status evidence is malformed")
    observed = _fingerprint(metadata_fingerprint, "metadata_fingerprint", optional=True)
    current = _fingerprint(current_metadata_fingerprint, "current_metadata_fingerprint", optional=True)
    if observed is not None and current is not None and observed != current:
        status = EvidenceStatus.STALE
    return AcceptanceEvidence(
        transport_completed=transport_completed,
        status=status,
        metadata_fingerprint=observed,
        current_metadata_fingerprint=current,
        reason_codes=_items(reason_codes, "acceptance reason_codes"),
    )


def ai_review_evidence(
    *,
    provider: str,
    status: ReviewStatus,
    reviewed_sha: str | None,
    current_head_sha: str,
    unresolved_finding_ids: tuple[str, ...] | list[str] = (),
    resolved_finding_ids: tuple[str, ...] | list[str] = (),
    invalidated_finding_ids: tuple[str, ...] | list[str] = (),
    reason_codes: tuple[str, ...] | list[str] = (),
) -> AIReviewEvidence:
    if type(status) is not ReviewStatus:
        raise EvidenceValidationError("review status must be ReviewStatus")
    current = _sha(current_head_sha, "current_head_sha")
    reviewed = _sha(reviewed_sha, "reviewed_sha", optional=True)
    unresolved = _items(unresolved_finding_ids, "unresolved_finding_ids")
    resolved = _items(resolved_finding_ids, "resolved_finding_ids")
    invalidated = _items(invalidated_finding_ids, "invalidated_finding_ids")
    if set(unresolved) & set(resolved):
        raise EvidenceValidationError("finding cannot be both resolved and unresolved")
    if reviewed is not None and reviewed != current and status in {
        ReviewStatus.PERFORMED_CLEAR,
        ReviewStatus.PERFORMED_BLOCKED,
    }:
        status = ReviewStatus.STALE
    if invalidated and status is ReviewStatus.PERFORMED_CLEAR:
        status = ReviewStatus.STALE
    if unresolved and status is ReviewStatus.PERFORMED_CLEAR:
        status = ReviewStatus.PERFORMED_BLOCKED
    return AIReviewEvidence(
        provider=_text(provider, "provider"),
        status=status,
        reviewed_sha=reviewed,
        unresolved_finding_ids=unresolved,
        resolved_finding_ids=resolved,
        invalidated_finding_ids=invalidated,
        reason_codes=_items(reason_codes, "review reason_codes"),
    )


def build_review_merge_evidence_summary(
    *,
    repository: str,
    pr_number: int,
    source_head_sha: str,
    base_sha: str | None,
    synthetic_merge_sha: str | None,
    merge_commit_sha: str | None,
    locally_tested_sha: str | None,
    acceptance: AcceptanceEvidence,
    focused_validation: tuple[ValidationEvidence, ...] | list[ValidationEvidence],
    aggregate_validation: ValidationEvidence,
    language_validation: tuple[ValidationEvidence, ...] | list[ValidationEvidence],
    specialized_validation: tuple[ValidationEvidence, ...] | list[ValidationEvidence],
    normal_review: AIReviewEvidence,
    adversarial_review: AIReviewEvidence,
) -> ReviewMergeEvidenceSummary:
    head = _sha(source_head_sha, "source_head_sha") or ""
    base = _sha(base_sha, "base_sha", optional=True)
    synthetic = _sha(synthetic_merge_sha, "synthetic_merge_sha", optional=True)
    merge_commit = _sha(merge_commit_sha, "merge_commit_sha", optional=True)
    local = _sha(locally_tested_sha, "locally_tested_sha", optional=True)
    if type(pr_number) is not int or pr_number <= 0:
        raise EvidenceValidationError("pr_number must be a positive integer")
    if type(acceptance) is not AcceptanceEvidence:
        raise EvidenceValidationError("acceptance must be AcceptanceEvidence")
    if type(aggregate_validation) is not ValidationEvidence:
        raise EvidenceValidationError("aggregate_validation must be ValidationEvidence")
    if type(normal_review) is not AIReviewEvidence or type(adversarial_review) is not AIReviewEvidence:
        raise EvidenceValidationError("review evidence is malformed")

    validation_groups = (focused_validation, language_validation, specialized_validation)
    if any(type(group) not in {tuple, list} or len(group) > MAX_ITEMS for group in validation_groups):
        raise EvidenceValidationError("validation evidence groups must be bounded")
    if any(type(item) is not ValidationEvidence for group in validation_groups for item in group):
        raise EvidenceValidationError("validation evidence group contains unsupported value")

    focused = tuple(focused_validation)
    language = tuple(language_validation)
    specialized = tuple(specialized_validation)
    all_validation = (*focused, aggregate_validation, *language, *specialized)

    reasons: set[str] = set()
    status = MergeEvidenceStatus.COMPLETE

    if acceptance.status in {EvidenceStatus.FAILED, EvidenceStatus.MANUAL_REVIEW}:
        status = MergeEvidenceStatus.BLOCKED
        reasons.add("acceptance-blocked")
    elif acceptance.status is EvidenceStatus.STALE:
        status = MergeEvidenceStatus.STALE
        reasons.add("acceptance-stale")
    elif acceptance.status is not EvidenceStatus.PASSED:
        status = MergeEvidenceStatus.INCOMPLETE
        reasons.add("acceptance-incomplete")

    for item in all_validation:
        if item.status is EvidenceStatus.FAILED:
            status = MergeEvidenceStatus.BLOCKED
            reasons.add(f"validation-failed:{item.name}")
        elif item.status is EvidenceStatus.STALE or (
            item.status is EvidenceStatus.PASSED and item.tested_sha != head
        ):
            if status is not MergeEvidenceStatus.BLOCKED:
                status = MergeEvidenceStatus.STALE
            reasons.add(f"validation-stale:{item.name}")
        elif item.status not in {EvidenceStatus.PASSED, EvidenceStatus.NOT_APPLICABLE}:
            if status is MergeEvidenceStatus.COMPLETE:
                status = MergeEvidenceStatus.INCOMPLETE
            reasons.add(f"validation-incomplete:{item.name}")

    for label, review in (("normal", normal_review), ("adversarial", adversarial_review)):
        if review.status is ReviewStatus.PERFORMED_BLOCKED:
            status = MergeEvidenceStatus.BLOCKED
            reasons.add(f"review-blocked:{label}")
        elif review.status is ReviewStatus.STALE:
            if status is not MergeEvidenceStatus.BLOCKED:
                status = MergeEvidenceStatus.STALE
            reasons.add(f"review-stale:{label}")
        elif review.status in {ReviewStatus.SKIPPED, ReviewStatus.UNAVAILABLE}:
            if status is MergeEvidenceStatus.COMPLETE:
                status = MergeEvidenceStatus.INCOMPLETE
            reasons.add(f"review-incomplete:{label}")

    unresolved = tuple(sorted(set(normal_review.unresolved_finding_ids) | set(adversarial_review.unresolved_finding_ids)))
    if unresolved:
        status = MergeEvidenceStatus.BLOCKED
        reasons.add("unresolved-findings")

    return ReviewMergeEvidenceSummary(
        repository=_text(repository, "repository"),
        pr_number=pr_number,
        source_head_sha=head,
        base_sha=base,
        synthetic_merge_sha=synthetic,
        merge_commit_sha=merge_commit,
        locally_tested_sha=local,
        acceptance=acceptance,
        focused_validation=focused,
        aggregate_validation=aggregate_validation,
        language_validation=language,
        specialized_validation=specialized,
        normal_review=normal_review,
        adversarial_review=adversarial_review,
        unresolved_finding_ids=unresolved,
        merge_evidence_status=status,
        reason_codes=tuple(sorted(reasons)),
    )


def classify_post_merge_evidence(
    *,
    run_sha: str | None,
    pre_merge_source_head_sha: str,
    merge_commit_sha: str,
    newer_run_exists: bool,
    duplicates_existing_proof: bool,
    run_started_before_merge: bool,
) -> PostMergeClassification:
    run = _sha(run_sha, "run_sha", optional=True)
    source = _sha(pre_merge_source_head_sha, "pre_merge_source_head_sha")
    merged = _sha(merge_commit_sha, "merge_commit_sha")
    if any(type(value) is not bool for value in (newer_run_exists, duplicates_existing_proof, run_started_before_merge)):
        raise EvidenceValidationError("post-merge classification flags must be booleans")
    if run is None:
        return PostMergeClassification.MANUAL_REVIEW
    if newer_run_exists:
        return PostMergeClassification.SUPERSEDED
    if run == merged:
        if duplicates_existing_proof:
            return PostMergeClassification.DUPLICATE_NONUNIQUE_EVIDENCE
        return PostMergeClassification.MERGE_SHA_INDEPENDENT_EVIDENCE
    if run == source and run_started_before_merge:
        return PostMergeClassification.PRE_MERGE_RUN_DRAINING
    return PostMergeClassification.MANUAL_REVIEW
