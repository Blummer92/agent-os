from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.agent_os_execution_capabilities import (
    CAPABILITY_EVIDENCE_SCHEMA_NAME,
    RepositoryEvidenceType,
    RepositoryIdentity,
    RepositoryStateEvidence,
    RepositoryStateValidationResult,
    WorktreeState,
)
from agent_os_execution_service import (
    EvidenceVisibilityPolicy,
    ExecutionServiceCapability,
    ExecutionServiceInvalidationCondition,
    ExecutionServiceReason,
    ExecutionServiceRequest,
    ExecutionServiceStatus,
    InspectedFileEvidence,
    PrivateEvidence,
    RepositoryInspectionObservation,
    evaluate_read_only_request,
    project_public_result,
)
import agent_os_execution_service.read_only_service as service_module

A = "a" * 40
B = "b" * 40
DIGEST = "c" * 64


def identity(owner: str = "blummer92") -> RepositoryIdentity:
    return RepositoryIdentity(
        host="github.com",
        owner=owner,
        repository="agent-os",
        repository_id=123,
        default_branch="main",
    )


def request(**overrides: object) -> ExecutionServiceRequest:
    values: dict[str, object] = {
        "schema_version": "1.0",
        "request_id": "wsc6b1-001",
        "request_revision": 1,
        "created_at": "2026-07-27T03:00:00Z",
        "expires_at": "2026-07-27T04:00:00Z",
        "repository_identity": identity(),
        "issue_or_handoff_identity": "issue:634",
        "canonical_owner": "integration-manager",
        "requesting_actor": "github-service-agent",
        "capability": ExecutionServiceCapability.INSPECT_REPOSITORY,
        "base_branch": "main",
        "base_sha": A,
        "requested_ref": "agent/634-wsc6b1-read-only-execution-service",
        "expected_sha": B,
        "allowed_paths": ("08_Tooling/agent-os-execution-service",),
        "forbidden_paths": ("secrets",),
        "inspected_file_count_limit": 8,
        "inspected_byte_limit": 100_000,
        "evidence_visibility_policy": EvidenceVisibilityPolicy.PUBLIC_SUMMARY_ONLY,
        "invalidation_conditions": tuple(
            sorted(ExecutionServiceInvalidationCondition, key=lambda item: item.value)
        ),
    }
    values.update(overrides)
    return ExecutionServiceRequest(**values)  # type: ignore[arg-type]


def state_evidence(req: ExecutionServiceRequest) -> RepositoryStateEvidence:
    return RepositoryStateEvidence(
        schema_name=CAPABILITY_EVIDENCE_SCHEMA_NAME,
        evidence_schema_version="1.0",
        producer_adapter="test",
        producer_adapter_version="1.0",
        correlation_id=req.request_id,
        repository_identity=req.repository_identity,
        base_ref=req.base_branch,
        base_sha=req.base_sha,
        head_ref=req.requested_ref,
        head_sha=req.expected_sha,
        requested_ref=req.requested_ref,
        requested_sha=req.expected_sha,
        observed_sha=req.expected_sha,
        tested_sha=req.expected_sha,
        pushed_sha=req.expected_sha,
        proposed_pr_sha=None,
        synthetic_merge_sha=None,
        external_build_sha=req.expected_sha,
        evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        contract_fingerprint=req.request_fingerprint,
        worktree_state=WorktreeState.CLEAN,
        worktree_reason_codes=(),
        observed_at="2026-07-27T03:30:00Z",
        freshness_boundary="2026-07-27T04:00:00Z",
    )


def observation(
    req: ExecutionServiceRequest, **overrides: object
) -> RepositoryInspectionObservation:
    files = (
        InspectedFileEvidence(
            path="08_Tooling/agent-os-execution-service/README.md",
            size_bytes=10,
            sha256=DIGEST,
        ),
    )
    values: dict[str, object] = {
        "repository_identity": req.repository_identity,
        "observed_ref": req.requested_ref,
        "observed_sha": req.expected_sha,
        "files": files,
        "declared_file_count": 1,
        "declared_byte_count": 10,
        "private_evidence": (),
        "repository_state_evidence": None,
    }
    values.update(overrides)
    return RepositoryInspectionObservation(**values)  # type: ignore[arg-type]


class Inspector:
    def __init__(self, value: object) -> None:
        self.value = value
        self.calls = 0

    def inspect(self, req: ExecutionServiceRequest) -> object:
        self.calls += 1
        return self.value


def evaluate(
    req: object,
    inspector: object,
    evaluated_at: object = "2026-07-27T03:30:00Z",
):
    return evaluate_read_only_request(
        req,
        evaluated_at=evaluated_at,
        inspector=inspector,
    )


def validation_result(
    outcome: str,
    reason_codes: tuple[str, ...] = (),
) -> RepositoryStateValidationResult:
    return RepositoryStateValidationResult(
        outcome=outcome,
        schema_version="1.0",
        evidence_id="",
        repository_identity=None,
        base_ref=None,
        base_sha=None,
        head_ref=None,
        head_sha=None,
        requested_ref=None,
        requested_sha=None,
        observed_sha=None,
        tested_sha=None,
        pushed_sha=None,
        proposed_pr_sha=None,
        synthetic_merge_sha=None,
        external_build_sha=None,
        evidence_type=None,
        contract_fingerprint=None,
        worktree_state=None,
        reason_codes=reason_codes,
        details=(),
    )


def test_invalid_request_calls_zero_times_and_valid_request_calls_once() -> None:
    inspector = Inspector(object())
    assert evaluate(object(), inspector).reasons == (
        ExecutionServiceReason.MALFORMED_REQUEST,
    )
    assert inspector.calls == 0

    req = request()
    inspector = Inspector(observation(req))
    result = evaluate(req, inspector)
    assert inspector.calls == 1
    assert result.reasons == (ExecutionServiceReason.ACCEPTED,)
    assert result.side_effects_performed is False


def test_identical_inputs_produce_identical_results() -> None:
    req = request()
    assert evaluate(req, Inspector(observation(req))) == evaluate(
        req, Inspector(observation(req))
    )


def test_exception_is_bounded_without_retry_and_control_exceptions_propagate() -> None:
    req = request()

    class ExplodingInspector:
        calls = 0

        def inspect(self, req: ExecutionServiceRequest):
            self.calls += 1
            raise RuntimeError("github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456")

    inspector = ExplodingInspector()
    result = evaluate(req, inspector)
    assert inspector.calls == 1
    assert result.reasons == (ExecutionServiceReason.SERVICE_UNAVAILABLE,)
    assert "github_pat_" not in result.public_summary

    for exception_type in (KeyboardInterrupt, SystemExit, GeneratorExit):
        class ControlInspector:
            def inspect(self, req: ExecutionServiceRequest):
                raise exception_type()

        with pytest.raises(exception_type):
            evaluate(req, ControlInspector())


def test_drift_counts_limits_and_paths_fail_closed() -> None:
    req = request(inspected_byte_limit=9)
    result = evaluate(
        req,
        Inspector(
            observation(
                req,
                repository_identity=identity("other"),
                observed_sha=A,
                declared_file_count=2,
            )
        ),
    )
    assert set(result.reasons) == {
        ExecutionServiceReason.IDENTITY_MISMATCH,
        ExecutionServiceReason.STALE_REPOSITORY_STATE,
        ExecutionServiceReason.EVIDENCE_UNAVAILABLE,
        ExecutionServiceReason.INSPECTION_LIMIT_EXCEEDED,
    }

    bad_file = InspectedFileEvidence(
        path="00_Governance/x.md",
        size_bytes=10,
        sha256=DIGEST,
    )
    req = request()
    assert evaluate(req, Inspector(observation(req, files=(bad_file,)))).reasons == (
        ExecutionServiceReason.CAPABILITY_NOT_AUTHORIZED,
    )


def test_verify_reuses_canonical_object_and_every_expected_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    req = request(capability=ExecutionServiceCapability.VERIFY_REPOSITORY_STATE)
    captured: dict[str, object] = {}

    def fake_validator(value: object, **kwargs: object):
        captured["value"] = value
        captured.update(kwargs)
        return validation_result("valid")

    monkeypatch.setattr(
        service_module,
        "validate_repository_state_evidence",
        fake_validator,
    )
    evidence = state_evidence(req)
    result = evaluate(
        req,
        Inspector(observation(req, repository_state_evidence=evidence)),
    )
    assert result.status is ExecutionServiceStatus.ACCEPTED
    assert captured == {
        "value": evidence,
        "expected_repository": req.repository_identity,
        "expected_base_ref": req.base_branch,
        "expected_base_sha": req.base_sha,
        "expected_head_ref": req.requested_ref,
        "expected_head_sha": req.expected_sha,
        "expected_requested_sha": req.expected_sha,
        "expected_contract_fingerprint": req.request_fingerprint,
    }


def test_nonvalid_or_missing_state_never_partially_accepts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    req = request(capability=ExecutionServiceCapability.VERIFY_REPOSITORY_STATE)
    assert evaluate(req, Inspector(observation(req))).reasons == (
        ExecutionServiceReason.EVIDENCE_UNAVAILABLE,
    )
    monkeypatch.setattr(
        service_module,
        "validate_repository_state_evidence",
        lambda *args, **kwargs: validation_result(
            "stale", ("ref.branch-moved", "repo.identity-mismatch")
        ),
    )
    result = evaluate(
        req,
        Inspector(observation(req, repository_state_evidence=state_evidence(req))),
    )
    assert set(result.reasons) == {
        ExecutionServiceReason.IDENTITY_MISMATCH,
        ExecutionServiceReason.STALE_REPOSITORY_STATE,
    }


def test_private_policy_and_invalid_time_are_bounded() -> None:
    secret = "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
    private = (PrivateEvidence(label="diagnostic", value=secret),)

    req = request()
    assert evaluate(
        req, Inspector(observation(req, private_evidence=private))
    ).private_evidence == ()

    req = request(evidence_visibility_policy=EvidenceVisibilityPolicy.INCLUDE_PRIVATE)
    result = evaluate(req, Inspector(observation(req, private_evidence=private)))
    assert result.private_evidence == private
    assert secret not in str(project_public_result(result))

    inspector = Inspector(observation(req))
    assert evaluate(req, inspector, "bad").reasons == (
        ExecutionServiceReason.MALFORMED_REQUEST,
    )
    assert inspector.calls == 0
