"""CKR PR4 offline bridge. No CLI, network client, serialized input or live caller.

Only trusted host composition may supply the readers and frozen policy. A reader
is a trust boundary, not a JSON validator: it must authenticate its source and
return None when source identity, completeness, or revocation cannot be verified.
GitHub's run-level artifact list cannot by itself supply VerifiedJobOutput.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from typing import Literal

from agent_memory_context_manager.lesson_applicability import (
    ApplicabilityMatch,
    ApplicabilityRecord,
    ShadowLessonState,
    TaskEvidence,
    VerifiedObservation,
    describe_applicability_match,
)
from scripts.agent_os_ci_evidence_collector import (
    AGGREGATE_STEP_NAME,
    MAX_ARCHIVE_BYTES,
    resolve_aggregate_step_number,
    validate_archive_members,
    verify_source_run,
)
from scripts.agent_os_ci_evidence_health import parse_junit_report

_SHA = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True, slots=True)
class FrozenCase:
    # Independently curated subject, including the issue-to-PR relationship.
    repository: str
    repository_id: int
    task_reference: str
    issue_number: int
    pr_number: int
    checkout_sha: str
    run_head_sha: str
    run_id: int
    attempt: int
    job_id: int
    step_number: int
    artifact_id: int
    member: str
    reporter_test_id: str
    not_before: datetime
    cutoff: datetime


@dataclass(frozen=True, slots=True)
class VerifiedJobOutput:
    """Only from the approved source reader, never from the artifact or PR body.

    The reader verifies actual checkout and job-to-member provenance via an
    authenticated producer receipt or equivalent provider evidence. No name join.
    """
    case: FrozenCase
    archive_sha256: str
    member_sha256: str


@dataclass(frozen=True, slots=True)
class CollectedExecution:
    """In-memory facts from the existing authenticated GitHub collection route."""
    run: dict
    job: dict
    artifact: dict
    archive: bytes
    output: VerifiedJobOutput | None


@dataclass(frozen=True, slots=True)
class ShadowPolicy:
    revision: str
    # Exact authorized pairs, not a cross product or inferred label mapping.
    approved_pairs: frozenset[tuple[str, str]]
    issuer: str
    reviewer: str


@dataclass(frozen=True, slots=True)
class ReviewedAttestation:
    """Projection of an independently authenticated, non-revoked review."""
    output: VerifiedJobOutput
    lesson_id: str
    lesson_revision: str
    annotation_sha256: str
    policy_revision: str
    issuer: str
    reviewer: str
    mechanism: str
    boundary: str
    reviewed_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ShadowEvidenceResult:
    status: Literal["qualified", "blocked"]
    reason: str
    execution_id: str | None = None
    match: ApplicabilityMatch | None = None
    job_conclusion: str | None = None  # Not the named testcase result.


def _time(value: object) -> bool:
    return type(value) is datetime and value.tzinfo is timezone.utc


def _same_case(candidate: object, expected: FrozenCase) -> bool:
    """Preserve exact types and UTC in nested receipt subjects."""
    if type(candidate) is not FrozenCase:
        return False
    for field in fields(FrozenCase):
        actual, wanted = getattr(candidate, field.name), getattr(expected, field.name)
        if (type(actual) is not type(wanted) or
            (type(wanted) is datetime and not _time(actual)) or actual != wanted):
            return False
    return True


def annotation_digest(record: ApplicabilityRecord) -> str:
    """Stable digest of the complete PR2 annotation, not just its lesson revision."""
    raw = json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _key(case: FrozenCase) -> str:
    # One execution does not become new evidence when an artifact is repackaged.
    raw = json.dumps([case.repository_id, case.run_id, case.attempt,
                      case.job_id, case.step_number, case.checkout_sha,
                      case.reporter_test_id], separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _execution(case: FrozenCase, evidence: object) -> tuple[str, datetime | None]:
    if type(evidence) is not CollectedExecution:
        return "execution-evidence-unavailable", None
    try:
        run, job, art = evidence.run, evidence.job, evidence.artifact
        verify_source_run(run, expected_run_id=case.run_id, expected_head=case.run_head_sha)
        repo = run["repository"]
        if not all(type(i) is int for i in (
            run["id"], run["run_attempt"], repo["id"], job["id"], job["run_id"],
            job["run_attempt"], art["id"], art["workflow_run"]["id"],
            art["workflow_run"]["repository_id"],
        )):
            return "provider-identity-malformed", None
        if (repo["id"], repo["full_name"]) != (case.repository_id, case.repository):
            return "repository-mismatch", None
        # Narrow first slice: provider-bound PR validation only. Workflow-dispatch
        # receipts without a provider PR association need a separately approved join.
        pr_numbers = [p["number"] for p in run["pull_requests"]]
        if (run["event"] != "pull_request" or pr_numbers != [case.pr_number]
            or type(pr_numbers[0]) is not int):
            return "pr-binding-missing-or-ambiguous", None
        if run["run_attempt"] != case.attempt or (
            job["id"], job["run_id"], job["run_attempt"], job["head_sha"]
        ) != (case.job_id, case.run_id, case.attempt, case.run_head_sha):
            return "run-attempt-job-mismatch", None
        if job["status"] != "completed" or job["conclusion"] not in {"success", "failure"}:
            return "job-not-executed", None
        try:
            resolved_step = resolve_aggregate_step_number(job)
        except ValueError:
            return "aggregate-step-unavailable-or-ambiguous", None
        if job["name"] != AGGREGATE_STEP_NAME or resolved_step != case.step_number:
            return "aggregate-step-mismatch", None
        matching_steps = [step for step in job["steps"] if
                          type(step) is dict and type(step.get("number")) is int
                          and step["number"] == resolved_step]
        if len(matching_steps) != 1 or (
            matching_steps[0].get("conclusion") != job["conclusion"]
        ):
            return "aggregate-step-mismatch", None
        # The shared resolver permits number coercion. The exact integer row
        # must itself be the completed aggregate step, not an unrelated row
        # occupying the same integer slot as malformed aggregate metadata.
        if (matching_steps[0].get("name"), matching_steps[0].get("status")) != (
            AGGREGATE_STEP_NAME, "completed"
        ):
            return "aggregate-step-mismatch", None
        finished = datetime.fromisoformat(job["completed_at"])
        if not _time(finished) or not case.not_before <= finished <= case.cutoff:
            return "execution-outside-window", None
        art_run = art["workflow_run"]
        if art["expired"] is not False or (
            art["id"], art_run["id"], art_run["repository_id"], art_run["head_sha"]
        ) != (case.artifact_id, case.run_id, case.repository_id, case.run_head_sha):
            return "artifact-binding-invalid", None
        output = evidence.output
        if type(output) is not VerifiedJobOutput:
            return "authenticated-job-output-unavailable", None
        if not _same_case(output.case, case):
            return "verified-job-output-subject-mismatch", None
        if type(evidence.archive) is not bytes or len(evidence.archive) > MAX_ARCHIVE_BYTES:
            return "archive-unavailable-or-oversized", None
        digest = hashlib.sha256(evidence.archive).hexdigest()
        if art.get("digest") != "sha256:" + digest or output.archive_sha256 != digest:
            return "archive-digest-missing-or-mismatch", None
        members = validate_archive_members(evidence.archive)
        if case.member not in members or not case.member.endswith(".xml"):
            return "junit-member-unavailable", None
        with zipfile.ZipFile(io.BytesIO(evidence.archive)) as archive:
            if archive.getinfo(case.member).file_size > 8_000_000:
                return "junit-member-oversized", None
            xml = archive.read(case.member)
        if hashlib.sha256(xml).hexdigest() != output.member_sha256:
            return "member-digest-mismatch", None
        # Do not let a wider XML encoding evade the shared validator's byte checks.
        xml.decode("utf-8")
        if b"\x00" in xml:
            return "execution-evidence-malformed", None
        ids, counts, shapes = parse_junit_report(xml)
        # This slice supports ordinary named testcases only, not subtest
        # surplus. Reject skip/error elements even if suite totals omit them.
        if (len(shapes) != 1 or any(declared != actual for declared, actual in shapes)
            or counts["failures"] != counts["failed_elements"]
            or counts["skipped"] != counts["skipped_elements"]
            or counts["errors"] != counts["error_elements"]
            or (job["conclusion"] == "success" and counts["failures"])):
            return "junit-contradiction", None
        if ids.count(case.reporter_test_id) != 1 or counts["skipped"] or counts["errors"]:
            return "named-test-not-confirmed", None
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError,
            EOFError, OSError, RuntimeError, zipfile.BadZipFile, zlib.error, NotImplementedError):
        return "execution-evidence-malformed", None
    return "execution-confirmed", finished


def evaluate_shadow_case(
    case: FrozenCase,
    task: TaskEvidence,
    record: ApplicabilityRecord,
    lesson: ShadowLessonState,
    *,
    policy: ShadowPolicy | None = None,
    collect: Callable[[FrozenCase], CollectedExecution | None] | None = None,
    read_review: Callable[[VerifiedJobOutput, str, str], tuple[ReviewedAttestation, ...]] | None = None,
    as_of: datetime,
) -> ShadowEvidenceResult:
    """Acquire once, qualify and project once into PR2. No reusable token returned.

    Trusted composition freezes the expected case, current lesson state, reviewed
    annotation and as-of time separately from incoming evidence. Review lookup must be complete and authentication
    must be external to this adapter; strings in review metadata prove nothing.
    """
    job_conclusion = None

    def blocked(reason: str, execution_id: str | None = None) -> ShadowEvidenceResult:
        return ShadowEvidenceResult("blocked", reason, execution_id, job_conclusion=job_conclusion)

    if type(case) is not FrozenCase or type(task) is not TaskEvidence or (
        task.repository, task.task_reference
    ) != (case.repository, case.task_reference):
        return blocked("task-binding-mismatch")
    if case.task_reference not in {
        f"https://github.com/{case.repository}/issues/{case.issue_number}",
        f"https://github.com/{case.repository}/pull/{case.pr_number}",
    }:
        return blocked("task-binding-mismatch")
    if not all(type(i) is int and i > 0 for i in (
        case.repository_id, case.issue_number, case.pr_number, case.run_id, case.attempt,
        case.job_id, case.step_number, case.artifact_id,
    )) or not all(type(s) is str and _SHA.fullmatch(s) for s in (
        case.checkout_sha, case.run_head_sha,
    )) or not all(type(s) is str and 0 < len(s) <= 512 for s in (
        case.member, case.reporter_test_id,
    )) or not all(_time(t) for t in (case.not_before, case.cutoff, as_of)):
        return blocked("case-incomplete")
    if not case.not_before <= case.cutoff <= as_of:
        return blocked("case-window-invalid")
    if type(record) is not ApplicabilityRecord or type(lesson) is not ShadowLessonState:
        return blocked("lesson-binding-missing")
    if (record.lesson_id, record.source_revision) != (lesson.lesson_id, lesson.source_revision):
        return blocked("lesson-revision-mismatch")
    if record.review_status != "reviewed" or lesson.currentness != "current" or (
        lesson.archived or not lesson.surface_before_work
    ):
        return blocked("lesson-not-eligible")
    if (type(policy) is not ShadowPolicy or type(policy.revision) is not str
        or not policy.revision.strip() or type(policy.approved_pairs) is not frozenset
        or not policy.approved_pairs):
        return blocked("policy-or-vocabulary-unapproved")
    if (not all(type(name) is str and name.strip() for name in (policy.issuer, policy.reviewer))
        or policy.issuer == policy.reviewer
        or not callable(read_review)):
        return blocked("independent-authority-unavailable")
    if not callable(collect):
        return blocked("authenticated-source-unavailable")
    try:
        evidence = collect(case)
    except (OSError, ValueError, RuntimeError):
        return blocked("execution-read-failed")
    reason, finished = _execution(case, evidence)
    if finished is None:
        return blocked(reason)
    execution_id = _key(case)
    job_conclusion = evidence.job["conclusion"]
    output = evidence.output
    try:
        reviews = read_review(output, record.lesson_id, record.source_revision)
    except (OSError, ValueError, RuntimeError):
        return blocked("review-read-failed", execution_id)
    if type(reviews) is not tuple or not reviews or len(reviews) > 16 or any(
        type(r) is not ReviewedAttestation for r in reviews
    ):
        return blocked("authenticated-attestation-unavailable", execution_id)
    review = reviews[0]
    if any(r != review for r in reviews[1:]):
        return blocked("conflicting-attestations", execution_id)
    if any(type(r.output) is not VerifiedJobOutput or not _same_case(r.output.case, case)
           for r in reviews):
        return blocked("attestation-subject-mismatch", execution_id)
    if (review.output, review.lesson_id, review.lesson_revision, review.annotation_sha256,
        review.policy_revision) != (
        output, record.lesson_id, record.source_revision, annotation_digest(record), policy.revision,
    ):
        return blocked("attestation-subject-mismatch", execution_id)
    if (review.issuer, review.reviewer) != (policy.issuer, policy.reviewer):
        return blocked("attestation-authority-mismatch", execution_id)
    if not _time(review.reviewed_at) or not _time(review.expires_at) or not (
        finished <= review.reviewed_at <= as_of < review.expires_at
    ):
        return blocked("attestation-stale-or-future", execution_id)
    if (type(review.mechanism) is not str or type(review.boundary) is not str or
        (review.mechanism, review.boundary) not in policy.approved_pairs
    ):
        return blocked("mechanism-boundary-unapproved", execution_id)
    try:
        observation = VerifiedObservation(review.mechanism, review.boundary, execution_id,
                                          case.repository, "fresh")
    except (TypeError, ValueError):
        return blocked("observation-invalid", execution_id)
    match = describe_applicability_match(record, lesson, task,
                                         verified_observations=(observation,))
    return ShadowEvidenceResult("qualified", "reviewed-observation", execution_id, match, job_conclusion)
