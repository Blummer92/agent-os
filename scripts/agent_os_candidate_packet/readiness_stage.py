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

from .preapproval_dependency_evidence import build_preapproval_dependency_evidence
from .source_stage import resolve_issue_snapshot
from .stage_models import (
    DependencyEvidence,
    DependencyIdentityEvidence,
    DependencyIdentityStatus,
    EvidenceStatus,
    IssuePlanningContext,
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
    *,
    dependency_identity_evidence: DependencyIdentityEvidence | None = None,
    planning_context: IssuePlanningContext | None = None,
) -> IssueReadinessStageResult:
    """Resolve one exact issue snapshot and its canonical readiness evidence.

    Performs no writes and no network calls itself -- ``issue_reader`` and
    ``repository_reader`` are injected, read-only dependencies. Every
    unresolved or ambiguous input produces an explicit ``needs-decision``,
    ``blocked``, ``source-failure``, or ``incomplete-evidence`` result; this
    function never infers a boolean from missing or ambiguous evidence.

    ``dependency_identity_evidence`` is the only way canonical dependency
    identities enter a stage result outside first-packet mode. It must already
    be structured; this function never derives identities from
    ``snapshot.body``, ``Depends on:`` text, reason codes, evidence details,
    comments, PR text, or labels. A caller that omits it gets explicit
    fail-closed ``unavailable`` identity evidence, which is distinct from a
    structured source reporting no dependencies.

    In first-packet mode (``request.approval_record_exists`` is ``False``,
    #3354) identities are derived from the scanned IssuePlan ``depends_on``
    governed field -- the one canonical structured identity source -- and a
    caller-supplied ``dependency_identity_evidence`` is treated as a
    conflicting source that fails closed to needs-decision.

    ``planning_context`` is the single authoritative pre-planning source for the
    repository, base branch, evaluated repository SHA, implementation-contract
    fingerprint, and authorized contract scope. It is projected into the
    IssuePlan current-state evidence *before* that evidence's identity is
    computed, so the identity covers the context and never has to be revised
    afterwards. Nothing here probes Git, a worktree, a provider, or a clock to
    obtain any of it; a caller that omits the context simply gets evidence
    without those fields, exactly as before.

    The downstream ``graph_reference``, ``planning_result_reference``, and
    ``handoff_reference`` fields are deliberately left unset. Those artifacts do
    not exist yet at readiness time, and their digests transitively embed this
    evidence's own identity -- populating them here would require a hash
    preimage. They are carried by ``PlanningBindingEvidence`` instead.
    """
    if not isinstance(request, IssueReadinessStageRequest):
        raise TypeError("request must be an IssueReadinessStageRequest")
    if repository_reader is None:
        raise TypeError("repository_reader is required")
    if dependency_identity_evidence is not None and not isinstance(
        dependency_identity_evidence, DependencyIdentityEvidence
    ):
        raise TypeError(
            "dependency_identity_evidence must be a DependencyIdentityEvidence"
        )
    if planning_context is not None:
        if not isinstance(planning_context, IssuePlanningContext):
            raise TypeError("planning_context must be an IssuePlanningContext")
        if planning_context.repository != request.repository:
            raise ValueError(
                "planning_context.repository must equal request.repository"
            )

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
    context_projection: dict[str, object] = {}
    if planning_context is not None:
        context_projection = {
            "base_branch": planning_context.base_branch,
            "evaluated_repository_sha": planning_context.evaluated_repository_sha,
            "implementation_contract_fingerprint": (
                planning_context.implementation_contract_fingerprint
            ),
            "allowed_files": planning_context.allowed_files,
            "forbidden_paths": planning_context.forbidden_paths,
            "required_tests": planning_context.required_tests,
        }
    issueplan_evidence = build_issueplan_current_state_evidence(
        envelope,
        scan_result,
        observed_at=request.observed_at,
        freshness_boundary=request.freshness_boundary,
        governed_field_names=request.governed_field_names,
        repository=request.repository,
        **context_projection,
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

    # Phase-aware readiness contract (#3354). First-packet mode is keyed on
    # the caller-established absence of any ApprovalRecord or approved
    # execution projection -- never on phase alone, since an APPROVAL_READY
    # re-preparation can also occur for already-approved work. In
    # first-packet mode the post-approval evidence owners
    # (DependencyReadinessEvidence, AdvisoryEvidenceResult) are not consulted
    # and not required; readiness is strict/current IssuePlan evidence plus
    # pre-approval issue-dependency identity/current-state evidence.
    first_packet_mode = not request.approval_record_exists
    if first_packet_mode:
        dependency_identity_evidence = _first_packet_identity_evidence(
            envelope=envelope,
            scan_result=scan_result,
            caller_supplied=dependency_identity_evidence,
            extra_checks=extra_checks,
        )
        dependency_evidence = build_preapproval_dependency_evidence(
            repository=request.repository,
            dependency_identities=(
                dependency_identity_evidence.dependency_ids
                if dependency_identity_evidence.status
                == DependencyIdentityStatus.RESOLVED
                else ()
            ),
            issue_reader=issue_reader,
            provenance=(
                f"issueplan:depends_on@{envelope.source_locator}"
                f"@{envelope.source_revision}"
            ),
        )
        # AdvisoryEvidenceResult binds approved proposal/projection/approval
        # lineage (#1320) and therefore cannot exist before the first
        # approval; the first-packet contract does not require it. This is an
        # explicit not-applicable marking, never a guessed validation pass.
        validation_evidence = ValidationEvidence(
            status=EvidenceStatus.RESOLVED_CLEAR,
            reason_codes=("validation.first-packet-not-required",),
            details=(
                "AdvisoryEvidenceResult is a post-approval owner and is not "
                "required before the first approval (#3354).",
            ),
        )
    else:
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
        dependency_identity_evidence=dependency_identity_evidence,
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


def dependency_identity_evidence_from_scan(
    scan_result, *, provenance: str
) -> DependencyIdentityEvidence | None:
    """Build canonical dependency-identity evidence from one IssuePlan scan.

    Pure extraction shared by first-packet mode and post-approval consumers
    (#3413): the scanner-normalized ``depends_on`` governed field is the one
    structured identity source. Returns ``None`` when the scan yields no
    structured finding (ambiguous parse); a present-but-malformed
    ``depends_on`` is an explicit ``UNAVAILABLE`` finding, never a guess.
    Nothing here reads issue prose, comments, labels, PR text, timeline
    events, sub-issues, or CI status. Strictness policy stays with the caller:
    first-packet mode records its own ``first-packet.issueplan-not-strict``
    check, while post-approval consumers fail closed via
    ``dependency-identity.not-supplied``.
    """
    valid = [
        candidate for candidate in scan_result.candidates if candidate.parsed is not None
    ]
    if len(valid) != 1:
        return None
    raw = valid[0].parsed.get("depends_on")
    if raw is None:
        return DependencyIdentityEvidence(
            status=DependencyIdentityStatus.ABSENT, provenance=(provenance,)
        )
    if not isinstance(raw, list) or not all(isinstance(entry, str) for entry in raw):
        return DependencyIdentityEvidence(
            status=DependencyIdentityStatus.UNAVAILABLE,
            reason_codes=("dependency-identity.malformed-source",),
        )
    # The scanner normalized depends_on to a sorted, duplicate-free tuple of
    # canonical owner/repository#NNNN identities.
    identities = tuple(raw)
    if not identities:
        return DependencyIdentityEvidence(
            status=DependencyIdentityStatus.ABSENT, provenance=(provenance,)
        )
    return DependencyIdentityEvidence(
        status=DependencyIdentityStatus.RESOLVED,
        dependency_ids=identities,
        provenance=(provenance,),
    )


def _first_packet_identity_evidence(
    *,
    envelope: SourceEnvelope,
    scan_result,
    caller_supplied: DependencyIdentityEvidence | None,
    extra_checks: list[CheckResult],
) -> DependencyIdentityEvidence:
    """Derive canonical dependency identities from the IssuePlan (#3354).

    The scanned ``depends_on`` governed field is the one structured identity
    source in first-packet mode. A caller-supplied identity evidence alongside
    it is a conflicting source and fails closed to needs-decision; a
    non-strict IssuePlan fails closed because first-packet mode requires
    strict/current evidence. ``resolved`` carries the scanner-normalized
    identities, ``absent`` is a positive none-declared finding, and anything
    else is explicit ``unavailable``.
    """
    provenance = (
        f"issueplan:depends_on@{envelope.source_locator}@{envelope.source_revision}"
    )
    if caller_supplied is not None:
        extra_checks.append(
            CheckResult(
                "dependency identity source",
                Status.MANUAL_REVIEW,
                "Caller-supplied dependency identities conflict with the canonical "
                "IssuePlan depends_on source; failing closed to needs-decision.",
                ["reason_code=dependency-identity.conflicting-sources"],
            )
        )
        return DependencyIdentityEvidence(
            status=DependencyIdentityStatus.UNAVAILABLE,
            reason_codes=("dependency-identity.conflicting-sources",),
        )
    if not scan_result.strict_valid:
        extra_checks.append(
            CheckResult(
                "first-packet IssuePlan",
                Status.FAIL,
                "First-packet mode requires a strict/current IssuePlan.",
                ["reason_code=first-packet.issueplan-not-strict"],
            )
        )
    extracted = dependency_identity_evidence_from_scan(
        scan_result, provenance=provenance
    )
    if extracted is None:
        return DependencyIdentityEvidence(
            status=DependencyIdentityStatus.UNAVAILABLE,
            reason_codes=("dependency-identity.no-structured-source",),
        )
    return extracted
