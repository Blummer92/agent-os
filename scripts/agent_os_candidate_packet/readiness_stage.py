"""Glue the source stage, IssuePlan current-state evidence, and readiness
evaluation into one read-only candidate-packet stage result.

Reuses, and never reimplements:
  * ``scripts.agent_os_issue_acceptance.issueplan_scanner.scan_issueplan_source``
  * ``scripts.agent_os_issue_acceptance.issueplan_current_state``
    ``.build_issueplan_current_state_evidence``
  * ``scripts.agent_os_issue_acceptance.readiness``
    ``.evaluate_issue_readiness_with_labels``
"""

from __future__ import annotations

from scripts.agent_os_issue_acceptance.issueplan_current_state import (
    build_issueplan_current_state_evidence,
)
from scripts.agent_os_issue_acceptance.issueplan_scanner import (
    SourceEnvelope,
    scan_issueplan_source,
)
from scripts.agent_os_issue_acceptance.models import (
    AcceptanceReport,
    CheckResult,
    Status,
    strongest_status,
)
from scripts.agent_os_issue_acceptance.readiness import evaluate_issue_readiness_with_labels

from .source_stage import resolve_issue_snapshot
from .stage_models import (
    DependencyEvidence,
    EvidenceStatus,
    IssueReadinessStageRequest,
    IssueReadinessStageResult,
    IssueReadinessStageStatus,
    IssueSourceReader,
    IssueSourceStageStatus,
    RepositoryEvidenceReader,
    ValidationEvidence,
)

_BLOCKING_ISSUEPLAN_REASON_CODES = frozenset(
    {
        "scanner.multiple-identical",
        "scanner.multiple-conflicting",
        "scanner.malformed-candidate",
        "identity.quarantined",
        "source.unsupported",
    }
)

_STAGE_STATUS_FOR_SOURCE_STATUS = {
    IssueSourceStageStatus.SOURCE_FAILURE: IssueReadinessStageStatus.SOURCE_FAILURE,
    IssueSourceStageStatus.INCOMPLETE_EVIDENCE: IssueReadinessStageStatus.INCOMPLETE_EVIDENCE,
}


def prepare_issue_readiness(
    request: IssueReadinessStageRequest,
    issue_reader: IssueSourceReader,
    repository_reader: RepositoryEvidenceReader,
) -> IssueReadinessStageResult:
    """Resolve one exact issue snapshot and its canonical readiness evidence.

    Performs no writes and no network calls itself -- ``issue_reader`` and
    ``repository_reader`` are injected, read-only dependencies. Every
    unresolved or ambiguous input produces an explicit ``needs-decision``,
    ``blocked``, ``source-failure``, or ``incomplete-evidence`` result; this
    function never infers a boolean from missing or ambiguous evidence.
    """
    if not isinstance(request, IssueReadinessStageRequest):
        raise TypeError("request must be an IssueReadinessStageRequest")
    if repository_reader is None:
        raise TypeError("repository_reader is required")

    source_result = resolve_issue_snapshot(
        request.repository,
        request.issue_number,
        issue_reader,
        retrieved_at=request.observed_at,
    )
    if source_result.status != IssueSourceStageStatus.RESOLVED:
        return IssueReadinessStageResult(
            status=_STAGE_STATUS_FOR_SOURCE_STATUS[source_result.status],
            snapshot=None,
            issueplan_current_state_evidence=None,
            readiness_result=None,
            reason_codes=(*source_result.reason_codes, "authorization.not-granted"),
            details=source_result.details,
        )

    snapshot = source_result.snapshot
    assert snapshot is not None

    envelope = SourceEnvelope(
        source_locator=f"github:{request.repository}#{request.issue_number}",
        source_revision=snapshot.source_revision,
        content=snapshot.body,
        source_family="github-issue",
        retrieval_complete=True,
        pagination_complete=True,
        accessible=True,
        expected_revision=request.expected_source_revision,
    )
    scan_result = scan_issueplan_source(envelope)
    issueplan_evidence = build_issueplan_current_state_evidence(
        envelope,
        scan_result,
        observed_at=request.observed_at,
        freshness_boundary=request.freshness_boundary,
        governed_field_names=request.governed_field_names,
        repository=request.repository,
    )

    extra_checks: list[CheckResult] = []
    if issueplan_evidence.reason_codes:
        blocking = _BLOCKING_ISSUEPLAN_REASON_CODES & set(issueplan_evidence.reason_codes)
        evidence = [f"reason_code={code}" for code in issueplan_evidence.reason_codes]
        extra_checks.append(
            CheckResult(
                "issueplan current-state evidence",
                Status.FAIL if blocking else Status.MANUAL_REVIEW,
                "IssuePlan current-state evidence reports unresolved conditions.",
                evidence,
            )
        )

    dependency_evidence = _read_dependency_evidence(
        repository_reader, request.repository, request.issue_number
    )
    validation_evidence = _read_validation_evidence(
        repository_reader, request.repository, request.issue_number
    )

    dependency_blocked = dependency_evidence.status == EvidenceStatus.RESOLVED_BLOCKED
    if dependency_evidence.status == EvidenceStatus.NEEDS_DECISION:
        extra_checks.append(
            CheckResult(
                "dependency evidence",
                Status.MANUAL_REVIEW,
                "Dependency readiness evidence is ambiguous and requires a decision.",
                [f"reason_code={code}" for code in dependency_evidence.reason_codes]
                or ["reason_code=dependency.ambiguous"],
            )
        )
    elif dependency_evidence.status == EvidenceStatus.UNAVAILABLE:
        extra_checks.append(
            CheckResult(
                "dependency evidence",
                Status.FAIL,
                "Dependency readiness evidence is unavailable; failing closed.",
                [f"reason_code={code}" for code in dependency_evidence.reason_codes]
                or ["reason_code=dependency.unavailable"],
            )
        )

    validation_pending = validation_evidence.status == EvidenceStatus.RESOLVED_BLOCKED
    if validation_evidence.status == EvidenceStatus.NEEDS_DECISION:
        extra_checks.append(
            CheckResult(
                "validation evidence",
                Status.MANUAL_REVIEW,
                "Validation readiness evidence is ambiguous and requires a decision.",
                [f"reason_code={code}" for code in validation_evidence.reason_codes]
                or ["reason_code=validation.ambiguous"],
            )
        )
    elif validation_evidence.status == EvidenceStatus.UNAVAILABLE:
        extra_checks.append(
            CheckResult(
                "validation evidence",
                Status.FAIL,
                "Validation readiness evidence is unavailable; failing closed.",
                [f"reason_code={code}" for code in validation_evidence.reason_codes]
                or ["reason_code=validation.unavailable"],
            )
        )

    evidence_report = AcceptanceReport(
        linked_issue=None,
        overall_status=strongest_status(extra_checks),
        checks=extra_checks,
    )
    readiness_result = evaluate_issue_readiness_with_labels(
        snapshot.body,
        evidence_report,
        dependency_blocked=dependency_blocked,
        validation_pending=validation_pending,
    )

    reason_codes = [
        "authorization.not-granted",
        *issueplan_evidence.reason_codes,
        *dependency_evidence.reason_codes,
        *validation_evidence.reason_codes,
    ]
    stage_status = {
        "ready": IssueReadinessStageStatus.READY,
        "blocked": IssueReadinessStageStatus.BLOCKED,
        "needs-decision": IssueReadinessStageStatus.NEEDS_DECISION,
    }[readiness_result.outcome.value]

    return IssueReadinessStageResult(
        status=stage_status,
        snapshot=snapshot,
        issueplan_current_state_evidence=issueplan_evidence,
        readiness_result=readiness_result,
        reason_codes=tuple(reason_codes),
    )


def _read_dependency_evidence(
    repository_reader: RepositoryEvidenceReader, repository: str, issue_number: int
) -> DependencyEvidence:
    try:
        result = repository_reader.read_dependency_evidence(repository, issue_number)
    except (TypeError, ValueError, PermissionError, LookupError, RuntimeError) as error:
        return DependencyEvidence(
            status=EvidenceStatus.UNAVAILABLE,
            reason_codes=("dependency.reader-error",),
            details=(str(error),),
        )
    if not isinstance(result, DependencyEvidence):
        return DependencyEvidence(
            status=EvidenceStatus.UNAVAILABLE,
            reason_codes=("dependency.reader-contract-violation",),
        )
    return result


def _read_validation_evidence(
    repository_reader: RepositoryEvidenceReader, repository: str, issue_number: int
) -> ValidationEvidence:
    try:
        result = repository_reader.read_validation_evidence(repository, issue_number)
    except (TypeError, ValueError, PermissionError, LookupError, RuntimeError) as error:
        return ValidationEvidence(
            status=EvidenceStatus.UNAVAILABLE,
            reason_codes=("validation.reader-error",),
            details=(str(error),),
        )
    if not isinstance(result, ValidationEvidence):
        return ValidationEvidence(
            status=EvidenceStatus.UNAVAILABLE,
            reason_codes=("validation.reader-contract-violation",),
        )
    return result
