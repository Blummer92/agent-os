"""Stable failure-class and reason-code vocabulary for the #755 compiler.

``FailureClass`` is the repository-wide gap/blocker taxonomy #755 was asked to
draw its ``failure_class`` field from; most of its members describe missing
*capabilities* elsewhere in Agent OS and are never produced by this compiler.
``RUNTIME_REASON_CODES`` is the small, closed, machine-readable vocabulary the
compiler itself actually emits -- every value ``compiler.py`` can return is
listed here, and ``build_failure`` rejects anything outside it. Both
vocabularies are documented in ``README.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    CandidatePacketCompilationFailure,
    CandidatePacketPhase,
    FailureClass,
)

FAILURE_SCHEMA_NAME = "agent-os-candidate-packet-compilation-failure"
FAILURE_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class _ReasonMetadata:
    failure_class: FailureClass
    failed_stage: str
    remediation_owner: str
    human_judgment_required: bool = False
    external_authorization_required: bool = False
    connected_capability_required: bool = False


# Every reason code the compiler can ever emit, with its fixed metadata. A
# reason code not listed here cannot be used by ``build_failure`` -- the
# vocabulary is closed, exactly as the issue requires.
_REASON_METADATA: dict[str, _ReasonMetadata] = {
    "compiler-input.wrong-type": _ReasonMetadata(
        FailureClass.MISSING_MODEL, "compiler-input", "integration-manager"
    ),
    "compiler-input.unsupported-schema-version": _ReasonMetadata(
        FailureClass.MISSING_MODEL, "compiler-input", "integration-manager"
    ),
    "compiler-input.unsupported-phase": _ReasonMetadata(
        FailureClass.MISSING_MODEL, "compiler-input", "integration-manager"
    ),
    "compiler-input.authority-field-set-true": _ReasonMetadata(
        FailureClass.CONTRACT_CONFLICT, "compiler-input", "integration-manager"
    ),
    "compiler-input.phase-scope-violation": _ReasonMetadata(
        FailureClass.CONTRACT_CONFLICT, "compiler-input", "integration-manager"
    ),
    "source-stage.unresolved": _ReasonMetadata(
        FailureClass.MISSING_MODEL, "source", "integration-manager"
    ),
    "source-stage.blocked": _ReasonMetadata(
        FailureClass.CONTRACT_CONFLICT, "source", "integration-manager"
    ),
    "source-stage.needs-decision": _ReasonMetadata(
        FailureClass.MANUAL_JUDGMENT_REQUIRED,
        "source",
        "repository-owner",
        human_judgment_required=True,
    ),
    "source-stage.source-revision-mismatch": _ReasonMetadata(
        FailureClass.MISSING_FRESHNESS_CHECK, "source", "integration-manager"
    ),
    "issueplan.fingerprint-mismatch": _ReasonMetadata(
        FailureClass.MISSING_FRESHNESS_CHECK, "issueplan", "integration-manager"
    ),
    "issueplan.freshness-boundary-mismatch": _ReasonMetadata(
        FailureClass.MISSING_FRESHNESS_CHECK, "issueplan", "integration-manager"
    ),
    "planning-stage.invalid-input": _ReasonMetadata(
        FailureClass.MISSING_MODEL, "planning", "integration-manager"
    ),
    "planning-stage.blocked": _ReasonMetadata(
        FailureClass.CONTRACT_CONFLICT, "planning", "integration-manager"
    ),
    "planning-stage.needs-decision": _ReasonMetadata(
        FailureClass.MANUAL_JUDGMENT_REQUIRED,
        "planning",
        "repository-owner",
        human_judgment_required=True,
    ),
    "planning-stage.handoff-invalid": _ReasonMetadata(
        FailureClass.MISSING_VALIDATOR, "planning", "integration-manager"
    ),
    "repository-evidence.not-valid": _ReasonMetadata(
        FailureClass.CONTRACT_CONFLICT, "repository-evidence", "integration-manager"
    ),
    "repository-evidence.stale": _ReasonMetadata(
        FailureClass.MISSING_FRESHNESS_CHECK,
        "repository-evidence",
        "integration-manager",
    ),
    "repository-evidence.needs-decision": _ReasonMetadata(
        FailureClass.MANUAL_JUDGMENT_REQUIRED,
        "repository-evidence",
        "repository-owner",
        human_judgment_required=True,
    ),
    "proposal.not-eligible": _ReasonMetadata(
        FailureClass.CONTRACT_CONFLICT, "proposal", "integration-manager"
    ),
    "proposal.stale": _ReasonMetadata(
        FailureClass.MISSING_FRESHNESS_CHECK, "proposal", "integration-manager"
    ),
    "proposal.needs-decision": _ReasonMetadata(
        FailureClass.MANUAL_JUDGMENT_REQUIRED,
        "proposal",
        "repository-owner",
        human_judgment_required=True,
    ),
    "approval-stage.missing": _ReasonMetadata(
        FailureClass.MISSING_MODEL, "approval", "integration-manager"
    ),
    "approval-stage.pending-candidate-missing": _ReasonMetadata(
        FailureClass.MISSING_MODEL, "approval", "integration-manager"
    ),
    "approval-stage.decision-missing": _ReasonMetadata(
        FailureClass.AUTHORIZATION_REQUIRED,
        "approval",
        "repository-owner",
        external_authorization_required=True,
    ),
    "approval-stage.needs-decision": _ReasonMetadata(
        FailureClass.MANUAL_JUDGMENT_REQUIRED,
        "approval",
        "repository-owner",
        human_judgment_required=True,
    ),
    "approval-stage.rejected": _ReasonMetadata(
        FailureClass.AUTHORIZATION_REQUIRED,
        "approval",
        "repository-owner",
        external_authorization_required=True,
    ),
    "approval-stage.expired": _ReasonMetadata(
        FailureClass.AUTHORIZATION_REQUIRED,
        "approval",
        "repository-owner",
        external_authorization_required=True,
    ),
    "approval-stage.invalidated": _ReasonMetadata(
        FailureClass.AUTHORIZATION_REQUIRED,
        "approval",
        "repository-owner",
        external_authorization_required=True,
    ),
    "approval-stage.superseded": _ReasonMetadata(
        FailureClass.AUTHORIZATION_REQUIRED,
        "approval",
        "repository-owner",
        external_authorization_required=True,
    ),
    "approval-stage.stale": _ReasonMetadata(
        FailureClass.MISSING_FRESHNESS_CHECK, "approval", "integration-manager"
    ),
    "approval-stage.blocked": _ReasonMetadata(
        FailureClass.CONTRACT_CONFLICT, "approval", "integration-manager"
    ),
    "approval-stage.invalid": _ReasonMetadata(
        FailureClass.CONTRACT_CONFLICT, "approval", "integration-manager"
    ),
    "projection.binding-mismatch": _ReasonMetadata(
        FailureClass.CONTRACT_CONFLICT, "approval", "integration-manager"
    ),
    "execution-packet.missing": _ReasonMetadata(
        FailureClass.MISSING_MODEL, "execution-packet", "integration-manager"
    ),
    "execution-packet.not-complete": _ReasonMetadata(
        FailureClass.CONTRACT_CONFLICT, "execution-packet", "integration-manager"
    ),
    "execution-packet.runtime-capability-unavailable": _ReasonMetadata(
        FailureClass.EXTERNAL_CAPABILITY_REQUIRED,
        "execution-packet",
        "github-service-agent",
        connected_capability_required=True,
    ),
    "cross-binding.repository-mismatch": _ReasonMetadata(
        FailureClass.CONTRACT_CONFLICT, "cross-binding", "integration-manager"
    ),
    "cross-binding.issue-mismatch": _ReasonMetadata(
        FailureClass.CONTRACT_CONFLICT, "cross-binding", "integration-manager"
    ),
    "cross-binding.invocation-mismatch": _ReasonMetadata(
        FailureClass.CONTRACT_CONFLICT, "cross-binding", "integration-manager"
    ),
    "cross-binding.base-branch-mismatch": _ReasonMetadata(
        FailureClass.CONTRACT_CONFLICT, "cross-binding", "integration-manager"
    ),
    "cross-binding.base-sha-mismatch": _ReasonMetadata(
        FailureClass.CONTRACT_CONFLICT, "cross-binding", "integration-manager"
    ),
    "cross-binding.candidate-sha-mismatch": _ReasonMetadata(
        FailureClass.CONTRACT_CONFLICT, "cross-binding", "integration-manager"
    ),
    "cross-binding.source-sha-mismatch": _ReasonMetadata(
        FailureClass.CONTRACT_CONFLICT, "cross-binding", "integration-manager"
    ),
    "cross-binding.tested-sha-mismatch": _ReasonMetadata(
        FailureClass.MISSING_FRESHNESS_CHECK, "cross-binding", "integration-manager"
    ),
    "cross-binding.evaluator-sha-mismatch": _ReasonMetadata(
        FailureClass.CONTRACT_CONFLICT, "cross-binding", "integration-manager"
    ),
    "cross-binding.candidate-ref-mismatch": _ReasonMetadata(
        FailureClass.CONTRACT_CONFLICT, "cross-binding", "integration-manager"
    ),
    "scope.expected-changed-paths-outside-allowlist": _ReasonMetadata(
        FailureClass.CONTRACT_CONFLICT, "scope", "integration-manager"
    ),
    "scope.required-tests-mismatch": _ReasonMetadata(
        FailureClass.CONTRACT_CONFLICT, "scope", "integration-manager"
    ),
    "bounds.duplicate-stage-identity": _ReasonMetadata(
        FailureClass.MISSING_IDENTITY, "bounds", "integration-manager"
    ),
    "bounds.packet-too-large": _ReasonMetadata(
        FailureClass.MISSING_VALIDATOR, "bounds", "integration-manager"
    ),
    "serialization.reconstruction-mismatch": _ReasonMetadata(
        FailureClass.MISSING_SERIALIZER, "serialization", "integration-manager"
    ),
}

RUNTIME_REASON_CODES = frozenset(_REASON_METADATA)


def build_failure(
    *,
    requested_phase: CandidatePacketPhase,
    reason_code: str,
    failed_field: str | None = None,
    expected_identity: str | None = None,
    observed_identity: str | None = None,
    source_identity: str | None = None,
) -> CandidatePacketCompilationFailure:
    """Construct one closed-vocabulary compilation failure.

    ``reason_code`` must be a member of ``RUNTIME_REASON_CODES``; every other
    field on the returned object is derived from that code's fixed metadata,
    so two calls with the same reason code always classify identically.
    """
    if reason_code not in _REASON_METADATA:
        raise ValueError(f"unsupported compiler reason_code: {reason_code!r}")
    metadata = _REASON_METADATA[reason_code]
    return CandidatePacketCompilationFailure(
        schema_name=FAILURE_SCHEMA_NAME,
        schema_version=FAILURE_SCHEMA_VERSION,
        requested_phase=requested_phase,
        failure_class=metadata.failure_class,
        reason_code=reason_code,
        failed_stage=metadata.failed_stage,
        failed_field=failed_field,
        expected_identity=expected_identity,
        observed_identity=observed_identity,
        source_identity=source_identity,
        remediation_owner=metadata.remediation_owner,
        human_judgment_required=metadata.human_judgment_required,
        external_authorization_required=metadata.external_authorization_required,
        connected_capability_required=metadata.connected_capability_required,
    )
