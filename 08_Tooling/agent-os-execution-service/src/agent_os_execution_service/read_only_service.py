from __future__ import annotations

from typing import Protocol

from scripts.agent_os_execution_capabilities import (
    RepositoryStateValidationResult,
    validate_repository_state_evidence,
)

from .models import (
    EXECUTION_SERVICE_RESULT_SCHEMA_VERSION,
    EXECUTION_SERVICE_VERSION,
    EvidenceVisibilityPolicy,
    ExecutionServiceCapability,
    ExecutionServiceReason,
    ExecutionServiceRequest,
    ExecutionServiceResult,
    ExecutionServiceStatus,
    MAX_EVIDENCE_TOTAL_BYTES,
    RepositoryInspectionObservation,
    parse_canonical_utc,
    path_is_within,
)
from .request_validation import contains_secret_marker, redact_public_text, validate_execution_service_request

_FALLBACK_EVALUATED_AT = "1970-01-01T00:00:00Z"
_ZERO_FINGERPRINT = "0" * 64


class RepositoryInspector(Protocol):
    def inspect(self, request: ExecutionServiceRequest) -> RepositoryInspectionObservation:
        """Return one supplied read-only snapshot without performing service-side writes."""


def evaluate_read_only_request(
    request: object,
    *,
    evaluated_at: object,
    inspector: object,
) -> ExecutionServiceResult:
    reasons = validate_execution_service_request(request, evaluated_at=evaluated_at)
    if reasons:
        return _result_for_request(
            request if type(request) is ExecutionServiceRequest else None,
            evaluated_at=evaluated_at,
            status=ExecutionServiceStatus.REJECTED,
            reasons=reasons,
        )

    assert type(request) is ExecutionServiceRequest
    try:
        observation = inspector.inspect(request)  # type: ignore[attr-defined]
    except (KeyboardInterrupt, SystemExit, GeneratorExit):
        raise
    except Exception:
        return _result_for_request(
            request,
            evaluated_at=evaluated_at,
            status=ExecutionServiceStatus.UNAVAILABLE,
            reasons=(ExecutionServiceReason.SERVICE_UNAVAILABLE,),
        )

    observation_reasons = _validate_observation(request, observation)
    if observation_reasons:
        return _result_for_request(
            request,
            evaluated_at=evaluated_at,
            status=ExecutionServiceStatus.REJECTED,
            reasons=observation_reasons,
            observation=observation if type(observation) is RepositoryInspectionObservation else None,
        )

    assert type(observation) is RepositoryInspectionObservation
    if request.capability is ExecutionServiceCapability.VERIFY_REPOSITORY_STATE:
        state_evidence = observation.repository_state_evidence
        if state_evidence is None:
            return _result_for_request(
                request,
                evaluated_at=evaluated_at,
                status=ExecutionServiceStatus.REJECTED,
                reasons=(ExecutionServiceReason.EVIDENCE_UNAVAILABLE,),
                observation=observation,
            )
        try:
            validation = validate_repository_state_evidence(
                state_evidence,
                expected_repository=request.repository_identity,
                expected_base_ref=request.base_branch,
                expected_base_sha=request.base_sha,
                expected_head_ref=request.requested_ref,
                expected_head_sha=request.expected_sha,
                expected_requested_sha=request.expected_sha,
                expected_contract_fingerprint=request.request_fingerprint,
            )
        except (KeyboardInterrupt, SystemExit, GeneratorExit):
            raise
        except Exception:
            return _result_for_request(
                request,
                evaluated_at=evaluated_at,
                status=ExecutionServiceStatus.UNAVAILABLE,
                reasons=(ExecutionServiceReason.SERVICE_UNAVAILABLE,),
                observation=observation,
            )
        if type(validation) is not RepositoryStateValidationResult:
            return _result_for_request(
                request,
                evaluated_at=evaluated_at,
                status=ExecutionServiceStatus.REJECTED,
                reasons=(ExecutionServiceReason.EVIDENCE_UNAVAILABLE,),
                observation=observation,
            )
        if validation.outcome != "valid":
            return _result_for_request(
                request,
                evaluated_at=evaluated_at,
                status=ExecutionServiceStatus.REJECTED,
                reasons=_map_repository_state_reasons(validation),
                observation=observation,
            )

    return _result_for_request(
        request,
        evaluated_at=evaluated_at,
        status=ExecutionServiceStatus.ACCEPTED,
        reasons=(ExecutionServiceReason.ACCEPTED,),
        observation=observation,
    )


def _validate_observation(
    request: ExecutionServiceRequest,
    observation: object,
) -> tuple[ExecutionServiceReason, ...]:
    if type(observation) is not RepositoryInspectionObservation:
        return (ExecutionServiceReason.EVIDENCE_UNAVAILABLE,)
    reasons: set[ExecutionServiceReason] = set()
    if observation.repository_identity.canonical_key != request.repository_identity.canonical_key:
        reasons.add(ExecutionServiceReason.IDENTITY_MISMATCH)
    if observation.observed_ref != request.requested_ref or observation.observed_sha != request.expected_sha:
        reasons.add(ExecutionServiceReason.STALE_REPOSITORY_STATE)

    file_count = len(observation.files)
    byte_count = sum(item.size_bytes for item in observation.files)
    if observation.declared_file_count != file_count or observation.declared_byte_count != byte_count:
        reasons.add(ExecutionServiceReason.EVIDENCE_UNAVAILABLE)
    if file_count > request.inspected_file_count_limit or byte_count > request.inspected_byte_limit:
        reasons.add(ExecutionServiceReason.INSPECTION_LIMIT_EXCEEDED)
    for item in observation.files:
        if not path_is_within(item.path, request.allowed_paths):
            reasons.add(ExecutionServiceReason.CAPABILITY_NOT_AUTHORIZED)
        if path_is_within(item.path, request.forbidden_paths):
            reasons.add(ExecutionServiceReason.CAPABILITY_NOT_AUTHORIZED)
    private_bytes = sum(len(item.value.encode("utf-8")) for item in observation.private_evidence)
    if private_bytes > MAX_EVIDENCE_TOTAL_BYTES:
        reasons.add(ExecutionServiceReason.INSPECTION_LIMIT_EXCEEDED)
    return tuple(sorted(reasons, key=lambda item: item.value))


def _map_repository_state_reasons(
    validation: RepositoryStateValidationResult,
) -> tuple[ExecutionServiceReason, ...]:
    mapped: set[ExecutionServiceReason] = set()
    for code in validation.reason_codes:
        if type(code) is not str:
            mapped.add(ExecutionServiceReason.EVIDENCE_UNAVAILABLE)
        elif code.startswith("repo."):
            mapped.add(ExecutionServiceReason.IDENTITY_MISMATCH)
        elif code.startswith("ref.") or code.startswith("worktree."):
            mapped.add(ExecutionServiceReason.STALE_REPOSITORY_STATE)
        else:
            mapped.add(ExecutionServiceReason.EVIDENCE_UNAVAILABLE)
    if not mapped:
        mapped.add(ExecutionServiceReason.EVIDENCE_UNAVAILABLE)
    return tuple(sorted(mapped, key=lambda item: item.value))


def _result_for_request(
    request: ExecutionServiceRequest | None,
    *,
    evaluated_at: object,
    status: ExecutionServiceStatus,
    reasons: tuple[ExecutionServiceReason, ...],
    observation: RepositoryInspectionObservation | None = None,
) -> ExecutionServiceResult:
    try:
        parse_canonical_utc(evaluated_at)
        safe_evaluated_at = evaluated_at
    except (TypeError, ValueError):
        safe_evaluated_at = _FALLBACK_EVALUATED_AT
    if request is None:
        request_id = "unknown"
        request_revision = 0
        request_fingerprint = _ZERO_FINGERPRINT
        repository_identity = None
        requested_ref = None
        expected_sha = None
        private_evidence = ()
    else:
        request_id = request.request_id
        request_revision = request.request_revision
        request_fingerprint = request.request_fingerprint
        repository_identity = request.repository_identity
        requested_ref = request.requested_ref
        expected_sha = request.expected_sha
        private_evidence = (
            observation.private_evidence
            if observation is not None and request.evidence_visibility_policy is EvidenceVisibilityPolicy.INCLUDE_PRIVATE
            else ()
        )
    inspected_file_count = len(observation.files) if observation is not None else 0
    inspected_byte_count = sum(item.size_bytes for item in observation.files) if observation is not None else 0
    reason_text = ",".join(item.value for item in reasons)
    summary = redact_public_text(
        f"status={status.value}; reasons={reason_text}; "
        f"inspected_files={inspected_file_count}; inspected_bytes={inspected_byte_count}"
    )
    if contains_secret_marker(summary):
        summary = "result available; sensitive detail withheld"
    return ExecutionServiceResult(
        schema_version=EXECUTION_SERVICE_RESULT_SCHEMA_VERSION,
        request_id=request_id,
        request_revision=request_revision,
        request_fingerprint=request_fingerprint,
        evaluated_at=safe_evaluated_at,
        service_version=EXECUTION_SERVICE_VERSION,
        status=status,
        reasons=tuple(sorted(set(reasons), key=lambda item: item.value)),
        repository_identity=repository_identity,
        requested_ref=requested_ref,
        expected_sha=expected_sha,
        observed_ref=observation.observed_ref if observation is not None else None,
        observed_sha=observation.observed_sha if observation is not None else None,
        inspected_file_count=inspected_file_count,
        inspected_byte_count=inspected_byte_count,
        private_evidence=private_evidence,
        public_summary=summary,
    )
