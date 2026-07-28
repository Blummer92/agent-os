"""Pure-local Cloud Build evidence normalization, PR resolution, and rendering.

Every function here operates only on values the caller supplies. There is no
network, filesystem, clock, subprocess, environment, or credential access, and
no input is ever mutated.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import asdict

from .models import (
    CLOUD_BUILD_EVIDENCE_SCHEMA_NAME,
    CLOUD_BUILD_EVIDENCE_SCHEMA_VERSION,
    CloudBuildCommentProjection,
    CloudBuildEvidenceError,
    CloudBuildResultEvidence,
    OverallResult,
    PullRequestResolutionCandidate,
    PullRequestResolutionResult,
    PullRequestState,
    ResolutionStatus,
)

_REDACT_TEXT_MAX_LENGTH = 200

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)bearer\s+[a-z0-9\-_.]+"),
    re.compile(r"(?i)authorization\s*[:=]\s*\S+"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd)\s*[:=]\s*\S+"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)https?://\S*[?&](?:sig|signature|token|x-goog-signature)=\S+"),
)


def _redact_text(value: str | None) -> str:
    if value is None:
        return "unavailable"
    text = value
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    if len(text) > _REDACT_TEXT_MAX_LENGTH:
        text = text[:_REDACT_TEXT_MAX_LENGTH] + "…[truncated]"
    return text


def normalize_cloud_build_evidence(
    *,
    build_id: str,
    tested_sha: str,
    repository: str,
    overall_result: OverallResult | str,
    terminal: bool,
    source_complete: bool,
    trigger_id: str | None = None,
    invocation_id: str | None = None,
    failed_step: str | None = None,
    exit_code: int | None = None,
    observed_at: str | None = None,
) -> CloudBuildResultEvidence:
    """Build a validated evidence record from caller-supplied primitives.

    Raises CloudBuildEvidenceError for structurally malformed or
    contradictory input; nothing is fabricated or defaulted into place.
    """
    if isinstance(overall_result, str):
        try:
            overall_result = OverallResult(overall_result)
        except ValueError as exc:
            raise CloudBuildEvidenceError(
                f"unsupported overall_result value: {overall_result!r}"
            ) from exc

    return CloudBuildResultEvidence(
        build_id=build_id,
        tested_sha=tested_sha,
        repository=repository,
        trigger_id=trigger_id,
        invocation_id=invocation_id,
        overall_result=overall_result,
        failed_step=failed_step,
        exit_code=exit_code,
        observed_at=observed_at,
        terminal=terminal,
        source_complete=source_complete,
    )


def resolve_pull_request(
    evidence: CloudBuildResultEvidence,
    *,
    authoritative_pr_number: int | None = None,
    candidates: Sequence[PullRequestResolutionCandidate] = (),
) -> PullRequestResolutionResult:
    """Resolve PR identity only from exact repository-and-SHA evidence."""
    candidates = tuple(candidates)

    if not evidence.source_complete:
        return PullRequestResolutionResult(
            status=ResolutionStatus.INVALID,
            pull_request_number=None,
            reason_codes=("resolution.incomplete-evidence",),
        )
    if evidence.overall_result == OverallResult.MALFORMED:
        return PullRequestResolutionResult(
            status=ResolutionStatus.INVALID,
            pull_request_number=None,
            reason_codes=("resolution.malformed-evidence",),
        )

    if authoritative_pr_number is not None:
        if (
            isinstance(authoritative_pr_number, bool)
            or not isinstance(authoritative_pr_number, int)
            or authoritative_pr_number <= 0
        ):
            return PullRequestResolutionResult(
                status=ResolutionStatus.INVALID,
                pull_request_number=None,
                reason_codes=("resolution.malformed-evidence",),
            )

        matches = [
            candidate
            for candidate in candidates
            if candidate.pull_request_number == authoritative_pr_number
        ]
        if not matches:
            return PullRequestResolutionResult(
                status=ResolutionStatus.MANUAL_REVIEW,
                pull_request_number=None,
                reason_codes=("resolution.no-candidate",),
            )
        if len(matches) > 1:
            return PullRequestResolutionResult(
                status=ResolutionStatus.MANUAL_REVIEW,
                pull_request_number=None,
                reason_codes=("resolution.duplicate-candidate",),
            )

        candidate = matches[0]
        problems: list[str] = []
        if candidate.repository != evidence.repository:
            problems.append("resolution.repository-mismatch")
        if candidate.head_sha != evidence.tested_sha:
            problems.append("resolution.sha-mismatch")
        if candidate.state != PullRequestState.OPEN:
            problems.append("resolution.closed-candidate")
        if problems:
            return PullRequestResolutionResult(
                status=ResolutionStatus.MANUAL_REVIEW,
                pull_request_number=None,
                reason_codes=tuple(problems),
            )

        conflicting = [
            other
            for other in candidates
            if other.repository == evidence.repository
            and other.head_sha == evidence.tested_sha
            and other.pull_request_number != authoritative_pr_number
        ]
        if conflicting:
            return PullRequestResolutionResult(
                status=ResolutionStatus.MANUAL_REVIEW,
                pull_request_number=None,
                reason_codes=("resolution.conflicting-evidence",),
            )

        return PullRequestResolutionResult(
            status=ResolutionStatus.RESOLVED,
            pull_request_number=candidate.pull_request_number,
            reason_codes=("resolution.authoritative-match",),
        )

    if not candidates:
        return PullRequestResolutionResult(
            status=ResolutionStatus.SKIPPED,
            pull_request_number=None,
            reason_codes=("resolution.no-candidate",),
        )

    exact = [
        candidate
        for candidate in candidates
        if candidate.repository == evidence.repository and candidate.head_sha == evidence.tested_sha
    ]
    if not exact:
        reasons: list[str] = []
        if any(candidate.head_sha == evidence.tested_sha for candidate in candidates):
            reasons.append("resolution.repository-mismatch")
        if any(candidate.repository == evidence.repository for candidate in candidates):
            reasons.append("resolution.sha-mismatch")
        if not reasons:
            reasons.append("resolution.no-candidate")
        return PullRequestResolutionResult(
            status=ResolutionStatus.SKIPPED,
            pull_request_number=None,
            reason_codes=tuple(reasons),
        )

    numbers = [candidate.pull_request_number for candidate in exact]
    if len(set(numbers)) != len(numbers):
        return PullRequestResolutionResult(
            status=ResolutionStatus.MANUAL_REVIEW,
            pull_request_number=None,
            reason_codes=("resolution.duplicate-candidate",),
        )

    open_exact = [candidate for candidate in exact if candidate.state == PullRequestState.OPEN]
    if not open_exact:
        return PullRequestResolutionResult(
            status=ResolutionStatus.SKIPPED,
            pull_request_number=None,
            reason_codes=("resolution.closed-candidate",),
        )
    if len(open_exact) > 1:
        return PullRequestResolutionResult(
            status=ResolutionStatus.MANUAL_REVIEW,
            pull_request_number=None,
            reason_codes=("resolution.multiple-candidates",),
        )

    return PullRequestResolutionResult(
        status=ResolutionStatus.RESOLVED,
        pull_request_number=open_exact[0].pull_request_number,
        reason_codes=("resolution.single-candidate-match",),
    )


def compute_stable_marker(evidence: CloudBuildResultEvidence) -> str:
    """Deterministic hidden marker for the managed build identity.

    The same repository/build/trigger/invocation identity always yields the
    same marker; a different identity always yields a different one.
    """
    identity = "|".join(
        (
            CLOUD_BUILD_EVIDENCE_SCHEMA_NAME,
            CLOUD_BUILD_EVIDENCE_SCHEMA_VERSION,
            evidence.repository,
            evidence.build_id,
            evidence.trigger_id or "",
            evidence.invocation_id or "",
        )
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"<!-- agent-os-cloud-build:{digest} -->"


_REPORTING_STATUS_BY_RESOLUTION = {
    ResolutionStatus.RESOLVED: "reported",
    ResolutionStatus.SKIPPED: "skipped",
    ResolutionStatus.MANUAL_REVIEW: "manual-review",
    ResolutionStatus.INVALID: "invalid",
}


def render_comment_projection(
    evidence: CloudBuildResultEvidence,
    resolution: PullRequestResolutionResult,
) -> CloudBuildCommentProjection:
    """Render one bounded, deterministic, secret-safe comment projection."""
    marker = compute_stable_marker(evidence)
    failed_step_text = "none" if evidence.failed_step == "none" else _redact_text(evidence.failed_step)
    exit_code_text = "unavailable" if evidence.exit_code is None else str(evidence.exit_code)
    reporting_status = _REPORTING_STATUS_BY_RESOLUTION[resolution.status]
    manual_review_reasons: tuple[str, ...] = (
        () if resolution.status == ResolutionStatus.RESOLVED else resolution.reason_codes
    )

    lines = [
        marker,
        "Cloud Build report (supplemental, non-authorizing)",
        f"build: {_redact_text(evidence.build_id)}",
        f"tested sha: {evidence.tested_sha}",
        f"result: {evidence.overall_result.value}",
        f"failed step: {failed_step_text}",
        f"exit code: {exit_code_text}",
        f"reporting status: {reporting_status}",
    ]
    if manual_review_reasons:
        lines.append("reasons: " + ", ".join(manual_review_reasons))
    lines.append(
        "This report is informational only. It does not authorize merge, "
        "approval, readiness, or required-check status."
    )
    rendered_body = "\n".join(lines)

    return CloudBuildCommentProjection(
        stable_marker=marker,
        build_id=evidence.build_id,
        tested_sha=evidence.tested_sha,
        overall_result=evidence.overall_result.value,
        failed_step=failed_step_text,
        exit_code=exit_code_text,
        reporting_status=reporting_status,
        manual_review_reasons=manual_review_reasons,
        rendered_body=rendered_body,
    )


def serialize_projection(projection: CloudBuildCommentProjection) -> str:
    """Canonical, deterministic JSON serialization of a rendered projection."""
    payload = asdict(projection)
    payload["manual_review_reasons"] = list(projection.manual_review_reasons)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def evidence_semantic_identity(evidence: CloudBuildResultEvidence) -> tuple[str, str, str, str]:
    """Bounded identity tuple used to compare two evidence records for replay."""
    return (
        evidence.repository,
        evidence.build_id,
        evidence.trigger_id or "",
        evidence.invocation_id or "",
    )


def is_same_build(a: CloudBuildResultEvidence, b: CloudBuildResultEvidence) -> bool:
    """True when two evidence records describe the same managed build."""
    return evidence_semantic_identity(a) == evidence_semantic_identity(b)
