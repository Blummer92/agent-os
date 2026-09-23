"""Pure-local deterministic validation-failure classification.

Consumes caller-supplied bounded facts only. This module performs no provider
retrieval, process execution, repair, retry, publication, merge, workflow,
protected-setting, credential, production, or external-system mutation.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Literal

VALIDATION_FAILURE_CLASSIFIER_SCHEMA_VERSION = "1.0"
_MAX_TEXT_BYTES = 4096
_MAX_SOURCE_IDENTIFIERS = 32
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


class ValidationFailureClassification(str, Enum):
    PR_REGRESSION = "pr_regression"
    INHERITED_MAIN_FAILURE = "inherited_main_failure"
    CI_INFRASTRUCTURE_CONFIGURATION_FAILURE = (
        "ci_infrastructure_configuration_failure"
    )
    INSUFFICIENT_EVIDENCE_NEEDS_DECISION = (
        "insufficient_evidence_needs_decision"
    )


class RequirementResult(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNAVAILABLE = "unavailable"


class EvidenceState(str, Enum):
    CURRENT = "current"
    STALE = "stale"
    CONFLICTING = "conflicting"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ValidationFailureEvidence:
    pr_head_sha: str
    comparison_main_sha: str | None
    command: str
    failed_requirement: str | None
    error_excerpt: str | None
    exit_code: int | None
    source_identifiers: tuple[str, ...] = ()
    evidence_state: EvidenceState = EvidenceState.CURRENT
    comparable_pr_and_main: bool = False
    same_requirement_executed: bool = False
    pr_requirement_result: RequirementResult = RequirementResult.FAIL
    main_requirement_result: RequirementResult = RequirementResult.UNAVAILABLE
    materially_equivalent_failure: bool = False
    pr_scope_attribution_supported: bool = False
    infrastructure_configuration_failure_proven: bool = False
    infrastructure_authorization_boundary: str | None = None

    def __post_init__(self) -> None:
        _sha40(self.pr_head_sha, "pr_head_sha")
        if self.comparison_main_sha is not None:
            _sha40(self.comparison_main_sha, "comparison_main_sha")
        _bounded_text(self.command, "command", required=True)
        _bounded_text(self.failed_requirement, "failed_requirement")
        _bounded_text(self.error_excerpt, "error_excerpt")
        _bounded_text(
            self.infrastructure_authorization_boundary,
            "infrastructure_authorization_boundary",
        )
        if self.exit_code is not None and (
            not isinstance(self.exit_code, int) or isinstance(self.exit_code, bool)
        ):
            raise TypeError("exit_code must be int or None")
        if not isinstance(self.evidence_state, EvidenceState):
            raise TypeError("evidence_state must use EvidenceState")
        if not isinstance(self.pr_requirement_result, RequirementResult):
            raise TypeError("pr_requirement_result must use RequirementResult")
        if not isinstance(self.main_requirement_result, RequirementResult):
            raise TypeError("main_requirement_result must use RequirementResult")
        for name in (
            "comparable_pr_and_main",
            "same_requirement_executed",
            "materially_equivalent_failure",
            "pr_scope_attribution_supported",
            "infrastructure_configuration_failure_proven",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be bool")
        if len(self.source_identifiers) > _MAX_SOURCE_IDENTIFIERS:
            raise ValueError("source_identifiers exceeds bound")
        normalized = tuple(sorted(set(self.source_identifiers)))
        for item in normalized:
            _bounded_text(item, "source_identifier", required=True)
        object.__setattr__(self, "source_identifiers", normalized)


@dataclass(frozen=True, slots=True)
class ValidationFailureClassificationResult:
    schema_version: str
    classification: ValidationFailureClassification
    pr_head_sha: str
    comparison_main_sha: str | None
    command: str
    failed_requirement: str | None
    error_excerpt: str | None
    exit_code: int | None
    source_identifiers: tuple[str, ...]
    reason: str
    evidence_completeness: Literal["complete", "incomplete"]
    recommended_next_action: str
    authorization_boundary: str | None
    evidence_id: str
    repair_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


_NEXT_ACTION = {
    ValidationFailureClassification.PR_REGRESSION: (
        "repair within authorized current scope -> rerun focused validation -> "
        "rerun exact-head aggregate validation -> continue"
    ),
    ValidationFailureClassification.INHERITED_MAIN_FAILURE: (
        "do not contaminate the PR -> preserve scope -> report blocker"
    ),
    ValidationFailureClassification.CI_INFRASTRUCTURE_CONFIGURATION_FAILURE: (
        "preserve repository state -> stop at exact authorization boundary -> "
        "request the separately governed change"
    ),
    ValidationFailureClassification.INSUFFICIENT_EVIDENCE_NEEDS_DECISION: (
        "do not guess -> preserve current state -> request only the missing "
        "evidence or decision"
    ),
}


def classify_validation_failure(
    evidence: ValidationFailureEvidence,
) -> ValidationFailureClassificationResult:
    """Classify supplied bounded evidence without inferring missing facts."""
    if not isinstance(evidence, ValidationFailureEvidence):
        raise TypeError("evidence must be ValidationFailureEvidence")

    classification, reason, completeness, boundary = _classify(evidence)
    payload = {
        "schema_version": VALIDATION_FAILURE_CLASSIFIER_SCHEMA_VERSION,
        "classification": classification.value,
        "pr_head_sha": evidence.pr_head_sha,
        "comparison_main_sha": evidence.comparison_main_sha,
        "command": evidence.command,
        "failed_requirement": evidence.failed_requirement,
        "error_excerpt": evidence.error_excerpt,
        "exit_code": evidence.exit_code,
        "source_identifiers": evidence.source_identifiers,
        "reason": reason,
        "evidence_completeness": completeness,
        "recommended_next_action": _NEXT_ACTION[classification],
        "authorization_boundary": boundary,
        "repair_authorized": False,
        "merge_authorized": False,
        "side_effects_performed": False,
    }
    evidence_id = "validation-failure-classification:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ValidationFailureClassificationResult(
        schema_version=VALIDATION_FAILURE_CLASSIFIER_SCHEMA_VERSION,
        classification=classification,
        pr_head_sha=evidence.pr_head_sha,
        comparison_main_sha=evidence.comparison_main_sha,
        command=evidence.command,
        failed_requirement=evidence.failed_requirement,
        error_excerpt=evidence.error_excerpt,
        exit_code=evidence.exit_code,
        source_identifiers=evidence.source_identifiers,
        reason=reason,
        evidence_completeness=completeness,
        recommended_next_action=_NEXT_ACTION[classification],
        authorization_boundary=boundary,
        evidence_id=evidence_id,
    )


def serialize_validation_failure_classification(
    result: ValidationFailureClassificationResult,
) -> str:
    if not isinstance(result, ValidationFailureClassificationResult):
        raise TypeError("result must be ValidationFailureClassificationResult")
    payload = asdict(result)
    payload["classification"] = result.classification.value
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def render_validation_failure_classification(
    result: ValidationFailureClassificationResult,
) -> str:
    if not isinstance(result, ValidationFailureClassificationResult):
        raise TypeError("result must be ValidationFailureClassificationResult")
    unavailable = "unavailable"
    sources = ", ".join(result.source_identifiers) or unavailable
    lines = (
        f"PR head SHA: {result.pr_head_sha}",
        f"Comparison main SHA: {result.comparison_main_sha or unavailable}",
        f"Command: {result.command}",
        f"Failed subcommand/test/check: {result.failed_requirement or unavailable}",
        f"Error: {result.error_excerpt or unavailable}",
        f"Classification: {result.classification.value}",
        f"Reason: {result.reason}",
        f"Evidence completeness: {result.evidence_completeness}",
        f"Source identifiers: {sources}",
        f"Recommended next action: {result.recommended_next_action}",
        f"Authorization boundary: {result.authorization_boundary or 'none'}",
        "repair_authorized: false",
        "merge_authorized: false",
        "side_effects_performed: false",
    )
    return "\n".join(lines)


def _classify(
    evidence: ValidationFailureEvidence,
) -> tuple[ValidationFailureClassification, str, Literal["complete", "incomplete"], str | None]:
    if evidence.evidence_state is not EvidenceState.CURRENT:
        return (
            ValidationFailureClassification.INSUFFICIENT_EVIDENCE_NEEDS_DECISION,
            f"evidence state is {evidence.evidence_state.value}; current attributable evidence is required",
            "incomplete",
            None,
        )

    if evidence.infrastructure_configuration_failure_proven:
        boundary = evidence.infrastructure_authorization_boundary or (
            "workflow/protected-setting/credential/provider configuration requires separate authorization"
        )
        return (
            ValidationFailureClassification.CI_INFRASTRUCTURE_CONFIGURATION_FAILURE,
            "explicit bounded evidence proves an execution/reporting/configuration failure",
            "complete",
            boundary,
        )

    comparable = (
        evidence.comparison_main_sha is not None
        and evidence.comparable_pr_and_main
        and evidence.same_requirement_executed
        and evidence.failed_requirement is not None
        and evidence.pr_requirement_result is RequirementResult.FAIL
    )
    if not comparable:
        return (
            ValidationFailureClassification.INSUFFICIENT_EVIDENCE_NEEDS_DECISION,
            "exact comparable PR/main evidence for the same failed requirement is incomplete or unavailable",
            "incomplete",
            None,
        )

    if (
        evidence.main_requirement_result is RequirementResult.PASS
        and evidence.pr_scope_attribution_supported
    ):
        return (
            ValidationFailureClassification.PR_REGRESSION,
            "the exact requirement fails on the PR head, passes on comparable main, and PR-scope attribution is supported",
            "complete",
            None,
        )

    if (
        evidence.main_requirement_result is RequirementResult.FAIL
        and evidence.materially_equivalent_failure
    ):
        return (
            ValidationFailureClassification.INHERITED_MAIN_FAILURE,
            "the same comparable requirement fails on PR head and main with materially equivalent failure evidence",
            "complete",
            None,
        )

    return (
        ValidationFailureClassification.INSUFFICIENT_EVIDENCE_NEEDS_DECISION,
        "comparable evidence does not prove PR regression, inherited main failure, or infrastructure/configuration failure",
        "incomplete",
        None,
    )


def _sha40(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SHA40_RE.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase 40-character SHA")


def _bounded_text(value: str | None, name: str, *, required: bool = False) -> None:
    if value is None:
        if required:
            raise ValueError(f"{name} is required")
        return
    if not isinstance(value, str):
        raise TypeError(f"{name} must be str or None")
    if required and not value.strip():
        raise ValueError(f"{name} is required")
    if len(value.encode("utf-8")) > _MAX_TEXT_BYTES:
        raise ValueError(f"{name} exceeds {_MAX_TEXT_BYTES} bytes")
