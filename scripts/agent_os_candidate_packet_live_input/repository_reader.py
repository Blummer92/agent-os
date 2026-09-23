"""Production ``RepositoryEvidenceReader`` over canonical structured evidence.

Before AOS-GCE2F (#1320) this adapter had no structured source at all and was
truthfully, unconditionally ``EvidenceStatus.UNAVAILABLE`` (#1155). It now maps
the two *existing* canonical structured owners into the existing
``DependencyEvidence`` / ``ValidationEvidence`` vocabulary, and keeps the old
behaviour exactly when neither is supplied:

- dependency readiness comes only from #1185/#1197
  ``DependencyReadinessEvidence``, which remains the sole runtime
  dependency-readiness authority. This adapter re-reads it; it does not model
  it, cache it, prepare it, retry it, or admit anything on its behalf.
- validation readiness comes only from the existing
  ``scripts.agent_os_remote_validation`` advisory pre-PR evidence result. GitHub
  check runs, generic CI status, PR state, issue labels, issue prose, branch
  names, timestamps, and repository-file accidents are never consulted.

The immutable ``RequiredEnvironmentSpec`` is a *declarative requirement* and is
used here only as the identity the readiness evidence must match. It never, on
its own, produces ``RESOLVED_CLEAR``: a spec without current readiness evidence
stays ``UNAVAILABLE``.

Everything else fails closed. Missing, stale, subject-mismatched, identity
-mismatched, malformed, or unknown-status evidence yields ``UNAVAILABLE`` or
``RESOLVED_BLOCKED`` with an explicit finite reason code -- never a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from scripts.agent_os_candidate_packet.stage_models import (
    DependencyEvidence,
    EvidenceStatus,
    ValidationEvidence,
)
from scripts.agent_os_execution_capabilities.dependencies import (
    DependencyPreparationStatus,
    DependencyReadinessEvidence,
    RequiredEnvironmentSpec,
)
from scripts.agent_os_remote_validation.advisory_gate import AdvisoryEvidenceResult

DEPENDENCY_NO_STRUCTURED_SOURCE_REASON = "dependency.no-structured-source-configured"
VALIDATION_NO_STRUCTURED_SOURCE_REASON = "validation.no-structured-source-configured"
DEPENDENCY_SUBJECT_MISMATCH_REASON = "dependency.evidence-subject-mismatch"
DEPENDENCY_ENVIRONMENT_MISMATCH_REASON = "dependency.required-environment-mismatch"
DEPENDENCY_EVIDENCE_NOT_CURRENT_REASON = "dependency.evidence-not-current"
DEPENDENCY_EVIDENCE_MALFORMED_REASON = "dependency.evidence-malformed"
VALIDATION_SUBJECT_MISMATCH_REASON = "validation.evidence-subject-mismatch"
VALIDATION_PLAN_MISMATCH_REASON = "validation.plan-identity-mismatch"
VALIDATION_STATUS_UNKNOWN_REASON = "validation.evidence-status-unknown"

_BLOCKED_PREPARATION_REASONS = {
    DependencyPreparationStatus.PREPARATION_REQUIRED: (
        "dependency.preparation-required"
    ),
    DependencyPreparationStatus.SOURCE_UPDATE_REQUIRED: (
        "dependency.source-update-required"
    ),
    DependencyPreparationStatus.BLOCKED: "dependency.preparation-blocked",
    DependencyPreparationStatus.FAILED: "dependency.preparation-failed",
}

_ADVISORY_STATUS_EVIDENCE: dict[str, tuple[EvidenceStatus, tuple[str, ...]]] = {
    "passed": (EvidenceStatus.RESOLVED_CLEAR, ()),
    "failed": (EvidenceStatus.RESOLVED_BLOCKED, ("validation.advisory-failed",)),
    "incomplete": (
        EvidenceStatus.RESOLVED_BLOCKED,
        ("validation.advisory-incomplete",),
    ),
    "needs-decision": (
        EvidenceStatus.NEEDS_DECISION,
        ("validation.advisory-needs-decision",),
    ),
    "stale": (EvidenceStatus.UNAVAILABLE, ("validation.advisory-stale",)),
    "invalid": (EvidenceStatus.UNAVAILABLE, ("validation.advisory-invalid",)),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class LiveRepositoryEvidenceReader:
    """Production ``RepositoryEvidenceReader`` bound to one exact subject.

    Constructed with no structured evidence it stays the #1155 truthful
    always-``UNAVAILABLE`` reader. Supplying structured evidence also requires
    the subject it belongs to, so evidence for another repository, issue, or
    required environment can never be read as this subject's.
    """

    repository: str | None = None
    issue_number: int | None = None
    required_environment_spec: RequiredEnvironmentSpec | None = None
    dependency_readiness: DependencyReadinessEvidence | None = None
    validation_result: AdvisoryEvidenceResult | None = None
    evaluated_at: str | None = None
    expected_validation_plan_id: str | None = None
    execution_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.repository is not None and (
            type(self.repository) is not str or not self.repository.strip()
        ):
            raise TypeError("repository must be non-empty exact text or None")
        if self.issue_number is not None and (
            type(self.issue_number) is not int or self.issue_number <= 0
        ):
            raise TypeError("issue_number must be a positive exact int or None")
        if self.required_environment_spec is not None and (
            type(self.required_environment_spec) is not RequiredEnvironmentSpec
        ):
            raise TypeError(
                "required_environment_spec must be exact RequiredEnvironmentSpec or None"
            )
        if self.dependency_readiness is not None and (
            type(self.dependency_readiness) is not DependencyReadinessEvidence
        ):
            raise TypeError(
                "dependency_readiness must be exact DependencyReadinessEvidence or None"
            )
        if self.validation_result is not None and (
            type(self.validation_result) is not AdvisoryEvidenceResult
        ):
            raise TypeError(
                "validation_result must be exact AdvisoryEvidenceResult or None"
            )
        if self.evaluated_at is not None and (
            type(self.evaluated_at) is not str or not self.evaluated_at.strip()
        ):
            raise TypeError("evaluated_at must be non-empty exact text or None")
        if self.expected_validation_plan_id is not None and (
            type(self.expected_validation_plan_id) is not str
            or not self.expected_validation_plan_id.strip()
        ):
            raise TypeError(
                "expected_validation_plan_id must be non-empty exact text or None"
            )
        structured = (
            self.dependency_readiness is not None or self.validation_result is not None
        )
        if structured and (self.repository is None or self.issue_number is None):
            raise TypeError("structured evidence requires its exact bound subject")
        if self.dependency_readiness is not None and (
            self.required_environment_spec is None or self.evaluated_at is None
        ):
            raise TypeError(
                "dependency readiness evidence requires the required environment "
                "specification and an evaluation moment"
            )

    def read_dependency_evidence(
        self, repository: str, issue_number: int
    ) -> DependencyEvidence:
        readiness = self.dependency_readiness
        if readiness is None:
            return DependencyEvidence(
                status=EvidenceStatus.UNAVAILABLE,
                reason_codes=(DEPENDENCY_NO_STRUCTURED_SOURCE_REASON,),
            )
        if not self._subject_matches(repository, issue_number):
            return DependencyEvidence(
                status=EvidenceStatus.UNAVAILABLE,
                reason_codes=(DEPENDENCY_SUBJECT_MISMATCH_REASON,),
            )
        spec = self.required_environment_spec
        if spec is None:
            return DependencyEvidence(
                status=EvidenceStatus.UNAVAILABLE,
                reason_codes=(DEPENDENCY_NO_STRUCTURED_SOURCE_REASON,),
            )
        if (
            readiness.required_environment_id != spec.required_environment_id
            or readiness.ecosystem is not spec.ecosystem
            or readiness.package_root != spec.package_root
            or readiness.install_mode is not spec.install_mode
        ):
            return DependencyEvidence(
                status=EvidenceStatus.UNAVAILABLE,
                reason_codes=(DEPENDENCY_ENVIRONMENT_MISMATCH_REASON,),
                details=(
                    f"required-environment-id={spec.required_environment_id}",
                    f"evidence-required-environment-id={readiness.required_environment_id}",
                ),
            )
        try:
            current = readiness.is_current(self.evaluated_at)
        except (TypeError, ValueError) as error:
            return DependencyEvidence(
                status=EvidenceStatus.UNAVAILABLE,
                reason_codes=(DEPENDENCY_EVIDENCE_MALFORMED_REASON,),
                details=(str(error),),
            )
        if not current:
            return DependencyEvidence(
                status=EvidenceStatus.UNAVAILABLE,
                reason_codes=(DEPENDENCY_EVIDENCE_NOT_CURRENT_REASON,),
                details=(
                    f"observed_at={readiness.observed_at}",
                    f"expires_at={readiness.expires_at}",
                    f"evaluated_at={self.evaluated_at}",
                ),
            )
        details = (
            f"dependency-readiness-evidence-id={readiness.dependency_readiness_evidence_id}",
            f"required-environment-id={spec.required_environment_id}",
        )
        if readiness.preparation_status is DependencyPreparationStatus.READY:
            return DependencyEvidence(
                status=EvidenceStatus.RESOLVED_CLEAR, details=details
            )
        blocked_reason = _BLOCKED_PREPARATION_REASONS.get(readiness.preparation_status)
        if blocked_reason is None:
            return DependencyEvidence(
                status=EvidenceStatus.UNAVAILABLE,
                reason_codes=(DEPENDENCY_EVIDENCE_MALFORMED_REASON,),
                details=details,
            )
        return DependencyEvidence(
            status=EvidenceStatus.RESOLVED_BLOCKED,
            reason_codes=(blocked_reason, *readiness.reason_codes),
            details=details,
        )

    def read_validation_evidence(
        self, repository: str, issue_number: int
    ) -> ValidationEvidence:
        result = self.validation_result
        if result is None:
            return ValidationEvidence(
                status=EvidenceStatus.UNAVAILABLE,
                reason_codes=(VALIDATION_NO_STRUCTURED_SOURCE_REASON,),
            )
        if not self._subject_matches(
            repository, issue_number
        ) or not _advisory_repository_matches(result, repository):
            return ValidationEvidence(
                status=EvidenceStatus.UNAVAILABLE,
                reason_codes=(VALIDATION_SUBJECT_MISMATCH_REASON,),
            )
        if (
            self.expected_validation_plan_id is not None
            and result.plan_id != self.expected_validation_plan_id
        ):
            return ValidationEvidence(
                status=EvidenceStatus.UNAVAILABLE,
                reason_codes=(VALIDATION_PLAN_MISMATCH_REASON,),
                details=(
                    f"expected-plan-id={self.expected_validation_plan_id}",
                    f"evidence-plan-id={result.plan_id}",
                ),
            )
        mapped = _ADVISORY_STATUS_EVIDENCE.get(result.status)
        if mapped is None:
            return ValidationEvidence(
                status=EvidenceStatus.UNAVAILABLE,
                reason_codes=(VALIDATION_STATUS_UNKNOWN_REASON,),
                details=(f"advisory-result-id={result.result_id}",),
            )
        status, reason_codes = mapped
        return ValidationEvidence(
            status=status,
            reason_codes=(*reason_codes, *result.reason_codes),
            details=(
                f"advisory-result-id={result.result_id}",
                f"advisory-status={result.status}",
            ),
        )

    def _subject_matches(self, repository: object, issue_number: object) -> bool:
        if self.repository is None or self.issue_number is None:
            return False
        if type(repository) is not str or type(issue_number) is not int:
            return False
        return (
            repository.casefold() == self.repository.casefold()
            and issue_number == self.issue_number
        )


def _advisory_repository_matches(
    result: AdvisoryEvidenceResult, repository: str
) -> bool:
    identity = result.repository_identity
    if identity is None:
        return False
    owner = getattr(identity, "owner", None)
    name = getattr(identity, "repository", None)
    if type(owner) is not str or type(name) is not str:
        return False
    return f"{owner}/{name}".casefold() == repository.casefold()
