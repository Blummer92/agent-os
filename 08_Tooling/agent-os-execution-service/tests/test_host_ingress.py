"""#3333 (D61) trusted-host ingress operation tests.

Covers the two narrowly typed host operations: closed argv surfaces,
fail-closed identity/schema handling, the genuine Contract A assembly up to
its precise missing-producer boundary, and the Contract B single delegation
with no caller-selected compatibility seams.
"""
from __future__ import annotations

import io
import json
import sys
from dataclasses import replace
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXECUTION_SERVICE_SRC = REPOSITORY_ROOT / "08_Tooling/agent-os-execution-service/src"
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
for _path in (REPOSITORY_ROOT, EXECUTION_SERVICE_SRC, SCHEDULER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402

from agent_os_execution_service import host_ingress  # noqa: E402
from agent_os_execution_service.authorized_validation import (  # noqa: E402
    AUTHORIZED_VALIDATION_SCHEMA_VERSION,
    reconstruct_authorized_validation_lifecycle_request,
    serialize_authorized_validation_lifecycle_request,
)
from agent_os_execution_service.fresh_pre_validation import (  # noqa: E402
    FreshPreValidationError,
)
from agent_os_execution_service.host_github_read_transport import (  # noqa: E402
    HostGitHubTransportUnavailable,
)
from agent_os_execution_service.host_ingress import (  # noqa: E402
    HostIngressError,
    capture_approved_candidate_custody,
    main_capture_custody,
    main_record_dependency_readiness,
    main_run_authorized_validation,
    record_codespaces_dependency_readiness,
    run_authorized_validation,
)
from agent_os_execution_service.human_approval_custody import (  # noqa: E402
    HumanApprovalCustodyError,
)
from agent_os_execution_service.production_host_bootstrap import (  # noqa: E402
    ProductionHostBootstrapError,
)
from test_3413_post_approval_custody import (  # noqa: E402
    _OwnerTransport,
    _config,
    _custody_items,
    _custody_ready,
    _seed_provenance,
)
from agent_os_execution_service.candidate_approval_provenance import (  # noqa: E402
    append_candidate_approval_provenance,
    build_candidate_approval_provenance,
)
from test_authorized_validation_vnext import _request, _vnext  # noqa: E402
from test_candidate_environment_provenance import _python_repo  # noqa: E402
from agent_os_execution_service.candidate_environment_provenance import (  # noqa: E402
    derive_initial_required_environment_spec,
)
from scripts.agent_os_execution_capabilities.dependencies import (  # noqa: E402
    DependencyCacheState,
    DependencyPreparationStatus,
    DependencyReadinessEvidence,
    ReproducibilityLevel,
)
from scripts.agent_os_execution_checkpoint.dependency_readiness_store import (  # noqa: E402
    append_dependency_readiness,
    load_dependency_readiness,
)


# ---------------------------------------------------------------------------
# Contract A: closed argv and fail-closed provenance identity.
# ---------------------------------------------------------------------------


def test_capture_custody_parser_rejects_missing_and_extra_arguments() -> None:
    with pytest.raises(SystemExit):
        main_capture_custody([])
    with pytest.raises(SystemExit):
        main_capture_custody(
            ["--candidate-provenance-id", "pre-publication-evidence:" + "a" * 64,
             "--approved", "true"]
        )


def test_capture_custody_rejects_malformed_provenance_identity(tmp_path: Path) -> None:
    config = _config(tmp_path)
    for bad in (
        "pre-publication-evidence:" + "A" * 64,
        "pre-publication-evidence:" + "a" * 63,
        "validation-bundle:" + "a" * 64,
        "",
    ):
        with pytest.raises(HostIngressError, match="candidate-provenance-id-malformed"):
            capture_approved_candidate_custody(bad, configuration=config)


def test_capture_custody_rejects_unknown_provenance(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with pytest.raises(HostIngressError, match="candidate-provenance-unavailable"):
        capture_approved_candidate_custody(
            "pre-publication-evidence:" + "b" * 64, configuration=config
        )


def test_capture_custody_reports_configuration_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise_bootstrap():
        raise ProductionHostBootstrapError("missing host configuration")

    monkeypatch.setattr(
        host_ingress, "load_production_host_configuration", _raise_bootstrap
    )
    with pytest.raises(HostIngressError, match="host-configuration-unavailable"):
        capture_approved_candidate_custody(
            "pre-publication-evidence:" + "b" * 64
        )


def test_capture_custody_reports_transport_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    ready, _observation = _custody_ready(_custody_items())
    provenance = _seed_provenance(config, ready, ready.proposal_stage_result)

    def _raise_transport():
        raise HostGitHubTransportUnavailable("no GitHub credentials")

    monkeypatch.setattr(
        host_ingress,
        "build_host_github_read_transport_from_environment",
        _raise_transport,
    )
    with pytest.raises(HostIngressError, match="host-transport-unavailable"):
        capture_approved_candidate_custody(
            provenance.evidence_id,
            configuration=config,
            evaluated_at="2026-10-08T00:08:00Z",
        )


def test_capture_custody_reports_approval_reacquisition_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    ready, _observation = _custody_ready(_custody_items())
    provenance = _seed_provenance(config, ready, ready.proposal_stage_result)

    def _raise_reacquisition(**kwargs):
        raise HumanApprovalCustodyError("approval-source-unavailable")

    monkeypatch.setattr(
        host_ingress, "reacquire_human_approval_decision", _raise_reacquisition
    )
    with pytest.raises(
        HostIngressError, match="approval-reacquisition-unavailable"
    ):
        capture_approved_candidate_custody(
            provenance.evidence_id,
            configuration=config,
            transport=_OwnerTransport(provenance.evidence_id),
            evaluated_at="2026-10-08T00:08:00Z",
        )


def test_capture_custody_reports_fresh_pre_validation_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    ready, _observation = _custody_ready(_custody_items())
    provenance = _seed_provenance(config, ready, ready.proposal_stage_result)

    def _raise_fresh(**kwargs):
        raise FreshPreValidationError("candidate-proposal-stage-incomplete")

    monkeypatch.setattr(
        host_ingress, "prepare_fresh_pre_validation", _raise_fresh
    )
    with pytest.raises(
        HostIngressError, match="fresh-pre-validation-unavailable"
    ):
        capture_approved_candidate_custody(
            provenance.evidence_id,
            configuration=config,
            transport=_OwnerTransport(provenance.evidence_id),
            evaluated_at="2026-10-08T00:08:00Z",
        )


def test_capture_custody_reaches_missing_producer_boundary(tmp_path: Path) -> None:
    """Genuine assembly succeeds up to the precise first-run boundary.

    Provenance load, live owner-approval reacquisition, and the fresh
    pre-validation plan all complete from existing canonical owners; custody
    then fails closed because no admitted producer of frozen pre-validation
    evidence exists to supply truthful runtime evidence references.
    """
    config = _config(tmp_path)
    ready, _observation = _custody_ready(_custody_items())
    provenance = _seed_provenance(config, ready, ready.proposal_stage_result)
    with pytest.raises(
        HostIngressError, match="pre-validation-evidence-references-unavailable"
    ):
        capture_approved_candidate_custody(
            provenance.evidence_id,
            configuration=config,
            transport=_OwnerTransport(provenance.evidence_id),
            evaluated_at="2026-10-08T00:08:00Z",
        )


# ---------------------------------------------------------------------------
# Contract B: identity verification, v1.1 requirement, single delegation.
# ---------------------------------------------------------------------------


def test_run_validation_rejects_malformed_expected_identity(tmp_path: Path) -> None:
    payload = serialize_authorized_validation_lifecycle_request(_vnext(tmp_path))
    with pytest.raises(HostIngressError, match="expected-request-id-malformed"):
        run_authorized_validation(
            "authorized-validation-request:" + "A" * 64, payload
        )


def test_run_validation_rejects_malformed_payload(tmp_path: Path) -> None:
    with pytest.raises(HostIngressError, match="authorized-validation-request-malformed"):
        run_authorized_validation(
            "authorized-validation-request:" + "a" * 64, {"schema_version": "9.9"}
        )


def test_run_validation_requires_v1_1(tmp_path: Path) -> None:
    request = _request(tmp_path, schema_version=AUTHORIZED_VALIDATION_SCHEMA_VERSION)
    payload = serialize_authorized_validation_lifecycle_request(request)
    with pytest.raises(HostIngressError, match="authorized-validation-v1.1-required"):
        run_authorized_validation(request.request_id, payload)


def test_run_validation_rejects_identity_mismatch(tmp_path: Path) -> None:
    request = _vnext(tmp_path)
    payload = serialize_authorized_validation_lifecycle_request(request)
    with pytest.raises(
        HostIngressError, match="authorized-validation-request-identity-mismatch"
    ):
        run_authorized_validation(
            "authorized-validation-request:" + "0" * 64, payload
        )


def test_run_validation_delegates_once_without_caller_seams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _vnext(tmp_path)
    payload = serialize_authorized_validation_lifecycle_request(request)
    calls: list[dict] = []

    def _fake_caller(payload_arg, **kwargs):
        calls.append(kwargs)
        return ("terminal-result", "pre-publication-evidence:" + "c" * 64)

    monkeypatch.setattr(host_ingress, "run_production_authorized_validation", _fake_caller)
    result = run_authorized_validation(request.request_id, payload)
    assert result == ("terminal-result", "pre-publication-evidence:" + "c" * 64)
    assert len(calls) == 1
    kwargs = calls[0]
    # The never-cancelled probe reports no cancellation source; no
    # caller-selected compatibility decision, runner, or inspector is wired.
    assert kwargs["cancelled"]("any-checkpoint") is False
    assert kwargs["configuration"] is None
    assert kwargs["transport"] is None
    assert kwargs["run_verifier"] is None
    assert "compatibility_decision" not in kwargs
    assert "git_runner" not in kwargs
    assert "process_cancelled" not in kwargs
    assert "changed_paths_inspector" not in kwargs


def test_main_run_validation_rejects_oversize_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    from agent_os_execution_service.authorized_validation import (
        _MAX_VNEXT_SERIALIZED_BYTES,
    )

    class _Stdin:
        def __init__(self, data: bytes) -> None:
            self.buffer = io.BytesIO(data)

    monkeypatch.setattr(
        sys, "stdin", _Stdin(b"x" * (_MAX_VNEXT_SERIALIZED_BYTES + 1))
    )
    status = main_run_authorized_validation(
        ["--expected-request-id", "authorized-validation-request:" + "a" * 64]
    )
    assert status == 1
    assert "authorized-validation-request-oversize" in capsys.readouterr().err


def test_main_run_validation_rejects_malformed_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    class _Stdin:
        def __init__(self, data: bytes) -> None:
            self.buffer = io.BytesIO(data)

    monkeypatch.setattr(sys, "stdin", _Stdin(b"not json"))
    status = main_run_authorized_validation(
        ["--expected-request-id", "authorized-validation-request:" + "a" * 64]
    )
    assert status == 1
    assert "authorized-validation-request-malformed" in capsys.readouterr().err


def test_main_capture_custody_prints_blocked_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    config = _config(tmp_path)
    ready, _observation = _custody_ready(_custody_items())
    provenance = _seed_provenance(config, ready, ready.proposal_stage_result)
    # main_capture_custody binds the real environment-backed owners, so the
    # malformed-identity path is the only environment-independent assertion.
    status = main_capture_custody(
        [
            "--candidate-provenance-id",
            "bogus",
            "--dependency-readiness-evidence-id",
            "dependency-readiness:" + "a" * 64,
        ]
    )
    assert status == 1
    assert "candidate-provenance-id-malformed" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Frozen pre-validation evidence path (D61 Scope A/C/B): genuine receipts
# from the admitted Codespaces dev-validation lane, identity-checked bundle
# bytes between operations, custody completion, and request origination.
# ---------------------------------------------------------------------------

from agent_os_execution_service.execution_authorization_source import (  # noqa: E402
    ExecutionAuthorizationCommentSnapshot,
    ExecutionAuthorizationSourceSnapshot,
    serialize_execution_authorization_comment,
)
from agent_os_execution_service.host_ingress import (  # noqa: E402
    freeze_pre_validation_evidence,
    main_freeze_pre_validation,
    main_originate_authorized_validation_request,
    originate_authorized_validation_request,
)
from agent_os_execution_service.pre_publication_evidence_store import (  # noqa: E402
    load_approval_custody_pre_publication_evidence,
)
from scripts.agent_os_candidate_packet_live_input.issue_reader import (  # noqa: E402
    SingleIssueTransportOutcome,
    SingleIssueTransportResult,
)
from scripts.agent_os_remote_validation.pre_pr_evidence_bundle import (  # noqa: E402
    reconstruct_pre_pr_validation_evidence_bundle,
    serialize_pre_pr_validation_evidence_bundle,
)
from scripts.agent_os_remote_validation.selector import (  # noqa: E402
    deserialize_pre_pr_validation_plan,
    pre_pr_validation_plan_id,
)
from scripts.agent_os_candidate_packet.approval_stage import (  # noqa: E402
    ApprovalProjectionStageStatus,
    prepare_approval_projection,
)
from scripts.agent_os_candidate_packet.cli import (  # noqa: E402
    prepare_candidate_packet,
)
from scripts.agent_os_issue_acceptance import ApprovalState  # noqa: E402
from tests.agent_os_candidate_packet.test_first_packet_approval_lifecycle import (  # noqa: E402
    _REPOSITORY,
    _ISSUE_NUMBER,
    _SHA,
    _BRANCH,
    _TEST,
    _body,
    _candidate_context,
    _decision,
    _item,
    _kwargs,
    _observation,
)
from workflow_scheduler.governance.dev_validation import (  # noqa: E402
    build_dev_validation_request,
)
from workflow_scheduler.governance.first_run_validation_observation import (  # noqa: E402
    CODESPACES_RUNNER_ID,
)

_RV_FILE = "scripts/agent_os_remote_validation/selector.py"
_RV_TEST = "python -m pytest tests/agent_os_remote_validation"
_RV_VALIDATION_ID = "remote-validation-suite"
_RV_PROFILE_ID = "remote-validation"
_OWNER_LOGIN = "Blummer92"
_OTHER_SHA = "c9" + "0" * 38


def _observation_with_sha(contract_fingerprint: str, sha: str):
    return replace(
        _observation(contract_fingerprint),
        head_sha=sha,
        requested_sha=sha,
        observed_sha=sha,
        tested_sha=sha,
    )


def _custody_ready_other(items: dict, sha: str):
    """The #3354 approval-ready lineage for a different candidate head sha."""
    precheck = prepare_candidate_packet(
        **_kwargs(items, evaluated_repository_sha=sha)
    )
    ready = prepare_candidate_packet(
        **_kwargs(
            items,
            evaluated_repository_sha=sha,
            repository_observation=_observation_with_sha(
                precheck.implementation_contract_fingerprint, sha
            ),
            candidate_context=_candidate_context(),
        )
    )
    assert ready.disposition == "approval-ready"
    observation = _observation_with_sha(ready.implementation_contract_fingerprint, sha)
    projection = prepare_approval_projection(
        ready.proposal_stage_result,
        candidate_context=_candidate_context(),
        approval_decision=_decision(ApprovalState.APPROVED),
        evaluated_at="2026-10-08T00:07:00Z",
        projected_at="2026-10-08T00:08:00Z",
    )
    assert projection.status is ApprovalProjectionStageStatus.COMPLETE
    return ready, observation


def _rv_items() -> dict:
    # _TEST contains the bare file path as a substring, so the command
    # identity must be replaced before the standalone allowed-file path.
    body = _body().replace(_TEST, _RV_TEST).replace(
        "tests/agent_os_candidate_packet/test_first_packet_approval_lifecycle.py",
        _RV_FILE,
    )
    return {(_REPOSITORY, _ISSUE_NUMBER): _item(body)}


def _rv_ready():
    items = _rv_items()
    # Production approval-ready packets carry the invocation descriptor's
    # canonical freshness timestamp; the shared lifecycle fixture leaves the
    # "stage-observation" sentinel, which the EXECUTION_CANDIDATE request
    # owner rightly rejects. Bind a genuine-shape canonical boundary.
    ready, observation = _custody_ready(
        items, freshness_boundary="2026-10-08T02:00:00Z"
    )
    return items, ready, observation


def _lane_evidence(ready, **updates):
    """The shape the admitted Codespaces dev-validation lane records."""
    packet = ready.packet
    request = build_dev_validation_request(
        repository=_REPOSITORY,
        issue_number=_ISSUE_NUMBER,
        branch=packet.candidate_ref,
        source_sha=packet.tested_sha,
        validation_id=_RV_VALIDATION_ID,
    )
    value = {
        "repository": _REPOSITORY,
        "issue_number": _ISSUE_NUMBER,
        "tested_sha": packet.tested_sha,
        "validation_id": _RV_VALIDATION_ID,
        "profile_id": _RV_PROFILE_ID,
        "request_id": request.request_id,
        "runner_id": CODESPACES_RUNNER_ID,
        "started_at": "2026-10-08T00:06:00Z",
        "completed_at": "2026-10-08T00:06:30Z",
        "status": "success",
        "exit_code": 0,
        "stdout_tail": "ok",
        "stderr_tail": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
    }
    value.update(updates)
    return value


class _OwnerHostTransport:
    """Host GitHub read-transport double: owner approval plus issue reads.

    Optionally carries additional issue comments, such as the structured
    execution-authorization comment, so the request originator can reacquire
    it through the same source owner it uses in production.
    """

    def __init__(self, provenance_id: str, items: dict, extra_comments=()) -> None:
        self._provenance_id = provenance_id
        self._items = items
        self._extra = tuple(extra_comments)

    def read_authorization_source(self, repository: str, issue_number: int):
        return ExecutionAuthorizationSourceSnapshot(
            repository=repository,
            issue_number=issue_number,
            owner_login=_OWNER_LOGIN,
            owner_type="User",
            comments_complete=True,
            comments=(
                ExecutionAuthorizationCommentSnapshot(
                    comment_id=4242,
                    author_login=_OWNER_LOGIN,
                    created_at="2026-10-08T00:07:00Z",
                    body=f"/agent-os approve-candidate {self._provenance_id}",
                ),
                *self._extra,
            ),
        )

    def get_issue(self, repository: str, issue_number: int):
        item = self._items.get((repository, issue_number))
        if item is None:
            return SingleIssueTransportResult(
                outcome=SingleIssueTransportOutcome.NOT_FOUND, item=None
            )
        return SingleIssueTransportResult(
            outcome=SingleIssueTransportOutcome.OK, item=dict(item)
        )


def _fake_verifier(ready):
    """Verifier double for a repository unchanged since approval.

    A genuine verifier run over a candidate whose base and head have not
    moved since the approval-time observation prints exactly the durable
    proposal-stage evidence values. Seeded from the genuinely constructed
    upstream stage result, never from the custody adapter under test.
    """
    packet = ready.packet
    durable = ready.proposal_stage_result.repository_state_evidence

    def run(invocation):
        assert invocation.branch == packet.candidate_ref
        assert invocation.base_branch == packet.base_branch
        return "\n".join(
            [
                f"HEAD_REF={durable.head_ref}",
                f"HEAD_SHA={durable.head_sha}",
                f"BASE_REF=origin/{durable.base_ref}",
                f"BASE_SHA={durable.base_sha}",
                "CHANGED_FILES_BEGIN",
                "CHANGED_FILES_END",
                "",
            ]
        )

    return run


def _frozen_bundle_payload(config, provenance, ready):
    serialized = freeze_pre_validation_evidence(
        provenance.evidence_id,
        _lane_evidence(ready),
        configuration=config,
        transport=_OwnerTransport(provenance.evidence_id),
        evaluated_at="2026-10-08T00:08:00Z",
    )
    return json.loads(serialized)


def _ready_evidence(spec, tested_sha: str) -> DependencyReadinessEvidence:
    """Genuine-shape READY evidence bound to the exact spec and candidate."""
    return DependencyReadinessEvidence(
        execution_surface_id="codespace:agent-os-d61",
        workspace_identity="workspace:remote-validation",
        source_sha=tested_sha,
        required_environment_id=spec.required_environment_id,
        package_root=spec.package_root,
        ecosystem=spec.ecosystem,
        runtime_version="3.11.13",
        package_manager_version="24.0",
        declared_dependency_identity=spec.dependency_manifest_identity.sha256,
        lock_or_constraints_identity=(
            None
            if spec.lock_or_constraints_identity is None
            else spec.lock_or_constraints_identity.sha256
        ),
        install_mode=spec.install_mode,
        source_or_registry_identity=spec.approved_source_identity,
        cache_state=DependencyCacheState.NOT_APPLICABLE,
        preparation_status=DependencyPreparationStatus.READY,
        resolved_dependency_identity="resolved:remote-validation",
        environment_health_evidence_id="health:1",
        observed_at="2026-10-08T00:07:00Z",
        expires_at="2026-10-08T01:00:00Z",
        reproducibility_level=(
            ReproducibilityLevel.LOCKED
            if spec.lock_or_constraints_identity is not None
            else ReproducibilityLevel.RESOLVED
        ),
        reason_codes=(),
    )


def _custody_setup(tmp_path: Path):
    config = replace(
        _config(tmp_path), repository_root=_python_repo(tmp_path / "specrepo")
    )
    items, ready, _observation = _rv_ready()
    provenance = _seed_provenance(config, ready, ready.proposal_stage_result)
    payload = _frozen_bundle_payload(config, provenance, ready)
    spec = derive_initial_required_environment_spec(
        config.repository_root, required_tests=("remote-validation",)
    )
    readiness_id = append_dependency_readiness(
        config.checkpoint_store_root, _ready_evidence(spec, ready.packet.tested_sha)
    ).evidence_id
    return config, items, ready, provenance, payload, readiness_id


def _complete_custody(
    config, items, ready, provenance, payload, readiness_id, extra_comments=()
):
    return capture_approved_candidate_custody(
        provenance.evidence_id,
        pre_validation_bundle_payload=payload,
        dependency_readiness_evidence_id=readiness_id,
        configuration=config,
        transport=_OwnerHostTransport(
            provenance.evidence_id, items, extra_comments=extra_comments
        ),
        run_verifier=_fake_verifier(ready),
        evaluated_at="2026-10-08T00:08:00Z",
        content_root=config.repository_root,
    )


def test_freeze_emits_bundle_bound_to_fresh_plan(tmp_path: Path) -> None:
    config = _config(tmp_path)
    items, ready, _observation = _rv_ready()
    provenance = _seed_provenance(config, ready, ready.proposal_stage_result)
    serialized = freeze_pre_validation_evidence(
        provenance.evidence_id,
        _lane_evidence(ready),
        configuration=config,
        transport=_OwnerTransport(provenance.evidence_id),
        evaluated_at="2026-10-08T00:08:00Z",
    )
    payload = json.loads(serialized)
    bundle = reconstruct_pre_pr_validation_evidence_bundle(payload)
    plan = deserialize_pre_pr_validation_plan(payload["validation_plan"])
    assert bundle.runner_id == CODESPACES_RUNNER_ID
    assert bundle.bundle_id.startswith("validation-evidence-bundle:")
    assert bundle.status == "passed"
    assert bundle.plan_id == pre_pr_validation_plan_id(plan)
    assert bundle.tested_sha == ready.packet.tested_sha
    assert bundle.invocation_id == ready.packet.invocation_id
    assert bundle.command_results[0].status == "passed"
    reserialized = json.dumps(
        serialize_pre_pr_validation_evidence_bundle(bundle, plan),
        sort_keys=True,
        separators=(",", ":"),
    )
    assert reserialized == serialized


def test_freeze_rejects_receipt_identity_drift(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _items, ready, _observation = _rv_ready()
    provenance = _seed_provenance(config, ready, ready.proposal_stage_result)
    drifted = _lane_evidence(ready, request_id="dev-validation:" + "f" * 64)
    with pytest.raises(HostIngressError, match="dev-validation-observation-rejected"):
        freeze_pre_validation_evidence(
            provenance.evidence_id,
            drifted,
            configuration=config,
            transport=_OwnerTransport(provenance.evidence_id),
            evaluated_at="2026-10-08T00:08:00Z",
        )


def test_freeze_rejects_retired_runner(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _items, ready, _observation = _rv_ready()
    provenance = _seed_provenance(config, ready, ready.proposal_stage_result)
    retired = _lane_evidence(ready, runner_id="agent-os-gce-dev-validation-v1")
    with pytest.raises(HostIngressError, match="dev-validation-observation-rejected"):
        freeze_pre_validation_evidence(
            provenance.evidence_id,
            retired,
            configuration=config,
            transport=_OwnerTransport(provenance.evidence_id),
            evaluated_at="2026-10-08T00:08:00Z",
        )


def test_freeze_rejects_plan_without_fixed_profile(tmp_path: Path) -> None:
    config = _config(tmp_path)
    ready, _observation = _custody_ready(_custody_items())
    provenance = _seed_provenance(config, ready, ready.proposal_stage_result)
    with pytest.raises(HostIngressError, match="fixed-validation-profile-unavailable"):
        freeze_pre_validation_evidence(
            provenance.evidence_id,
            _lane_evidence(ready),
            configuration=config,
            transport=_OwnerTransport(provenance.evidence_id),
            evaluated_at="2026-10-08T00:08:00Z",
        )


def test_capture_custody_completes_with_verified_bundle_bytes(tmp_path: Path) -> None:
    config, items, ready, provenance, payload, readiness_id = _custody_setup(tmp_path)
    capsule_id = _complete_custody(config, items, ready, provenance, payload, readiness_id)
    capsule = load_approval_custody_pre_publication_evidence(
        config.checkpoint_store_root, capsule_id
    )
    bundle = reconstruct_pre_pr_validation_evidence_bundle(payload)
    packet = capsule.candidate_packet
    assert packet.phase is not ready.packet.phase
    assert packet.invocation_id == ready.packet.invocation_id
    identities = dict(packet.stage_identities)
    # The composition-independent identities reproduce the approved packet's
    # exactly: the custody observation is the approval-time observation
    # reconstructed from durable provenance.
    approved = dict(ready.packet.stage_identities)
    for name in ("source", "issueplan", "repository-evidence"):
        assert identities[name] == approved[name]
    # The execution-candidate stages completed with genuine identities.
    assert identities["validation-plan"] == bundle.plan_id
    assert identities["validation-subject"].startswith("pre-pr-validation-subject:")
    assert identities["command-plan"].startswith("command-plan:")
    assert identities["runtime-configuration"].startswith("concrete-adapters:")
    assert identities["execution-request"]
    assert identities["projection"].startswith("approved-execution-projection:")
    assert packet.evidence_completeness == "complete"
    assert packet.disposition == "verified"
    assert packet.execution_authorized is False


def test_capture_custody_rejects_tampered_bundle_bytes(tmp_path: Path) -> None:
    config, items, ready, provenance, payload, readiness_id = _custody_setup(tmp_path)
    tampered = dict(payload, runner_id="agent-os-gce-dev-validation-v1")
    with pytest.raises(HostIngressError, match="pre-validation-bundle-malformed"):
        _complete_custody(config, items, ready, provenance, tampered, readiness_id)


def _drift_verifier(ready, *, head_sha=None, base_sha=None):
    """Verifier double for a repository that moved since approval."""
    durable = ready.proposal_stage_result.repository_state_evidence

    def run(invocation):
        return "\n".join(
            [
                f"HEAD_REF={durable.head_ref}",
                f"HEAD_SHA={head_sha or durable.head_sha}",
                f"BASE_REF=origin/{durable.base_ref}",
                f"BASE_SHA={base_sha or durable.base_sha}",
                "CHANGED_FILES_BEGIN",
                "CHANGED_FILES_END",
                "",
            ]
        )

    return run


def _capture_with_verifier(config, items, provenance, payload, readiness_id, verifier):
    return capture_approved_candidate_custody(
        provenance.evidence_id,
        pre_validation_bundle_payload=payload,
        dependency_readiness_evidence_id=readiness_id,
        configuration=config,
        transport=_OwnerHostTransport(provenance.evidence_id, items),
        run_verifier=verifier,
        evaluated_at="2026-10-08T00:08:00Z",
        content_root=config.repository_root,
    )


def test_capture_custody_rejects_moved_candidate_branch(tmp_path: Path) -> None:
    config, items, ready, provenance, payload, readiness_id = _custody_setup(tmp_path)
    with pytest.raises(HostIngressError, match="candidate-repository-subject-drift"):
        _capture_with_verifier(
            config,
            items,
            provenance,
            payload,
            readiness_id,
            _drift_verifier(ready, head_sha=_OTHER_SHA),
        )


def test_capture_custody_rejects_moved_base_branch(tmp_path: Path) -> None:
    config, items, ready, provenance, payload, readiness_id = _custody_setup(tmp_path)
    with pytest.raises(HostIngressError, match="candidate-repository-subject-drift"):
        _capture_with_verifier(
            config,
            items,
            provenance,
            payload,
            readiness_id,
            _drift_verifier(ready, base_sha=_OTHER_SHA),
        )


def _tampered_custody_setup(tmp_path: Path, **drifted_overrides):
    """Pair the approved packet with drifted durable proposal-stage material.

    Freezes the bundle against the genuine provenance first (the bundle is
    genuine pre-drift evidence), builds a second genuine upstream lineage
    with the given compile overrides, then appends provenance pairing the
    original packet with the drifted lineage's stage result: exactly the
    post-approval durable drift the custody path must refuse. Every
    artifact is owner-built; only the final pairing is wrong.
    """
    config = replace(
        _config(tmp_path), repository_root=_python_repo(tmp_path / "specrepo")
    )
    items, ready, _observation = _rv_ready()
    genuine_provenance = _seed_provenance(config, ready, ready.proposal_stage_result)
    payload = _frozen_bundle_payload(config, genuine_provenance, ready)
    spec = derive_initial_required_environment_spec(
        config.repository_root, required_tests=("remote-validation",)
    )
    readiness_id = append_dependency_readiness(
        config.checkpoint_store_root, _ready_evidence(spec, ready.packet.tested_sha)
    ).evidence_id
    drifted_ready, _obs = _custody_ready(
        items,
        freshness_boundary="2026-10-08T02:00:00Z",
        **drifted_overrides,
    )
    provenance = build_candidate_approval_provenance(
        approval_ready_packet=ready.packet,
        candidate_context=_candidate_context(),
        repository_proposal_stage_result=drifted_ready.proposal_stage_result,
    )
    append_candidate_approval_provenance(config.checkpoint_store_root, provenance)
    return config, items, ready, provenance, payload, readiness_id


def test_capture_custody_rejects_tampered_durable_evidence(tmp_path: Path) -> None:
    _items0, _ready0, observation0 = _rv_ready()
    config, items, ready, provenance, payload, readiness_id = _tampered_custody_setup(
        tmp_path,
        repository_observation=replace(observation0, observed_at="2026-10-08T00:05:30Z"),
    )
    with pytest.raises(HostIngressError) as excinfo:
        _capture_with_verifier(
            config,
            items,
            provenance,
            payload,
            readiness_id,
            _fake_verifier(ready),
        )
    assert excinfo.value.args[0] in {
        "candidate-repository-subject-drift",
        "approval-custody-unavailable",
        "fresh-pre-validation-unavailable",
        "validation-bundle-subject-mismatch",
        "governed-projection-not-accepted",
    }


def test_capture_custody_rejects_wrong_correlation(tmp_path: Path) -> None:
    _items0, _ready0, observation0 = _rv_ready()
    config, items, ready, provenance, payload, readiness_id = _tampered_custody_setup(
        tmp_path,
        repository_observation=replace(observation0, correlation_id="other-invocation"),
    )
    with pytest.raises(HostIngressError) as excinfo:
        _capture_with_verifier(
            config,
            items,
            provenance,
            payload,
            readiness_id,
            _fake_verifier(ready),
        )
    assert excinfo.value.args[0] in {
        "candidate-repository-subject-drift",
        "approval-custody-unavailable",
        "fresh-pre-validation-unavailable",
        "validation-bundle-subject-mismatch",
        "governed-projection-not-accepted",
    }


def test_capture_custody_completes_with_nondefault_durable_stage_times(
    tmp_path: Path,
) -> None:
    """A genuine lineage whose approval compile used explicit stage clocks.

    The custody owner must re-present the durable planning-binding and
    proposal created_at fields, not the packet clock, so a packet approved
    with nondefault stage times still reproduces its stored identities.
    """
    config = replace(
        _config(tmp_path), repository_root=_python_repo(tmp_path / "specrepo")
    )
    items = _rv_items()
    ready, _observation = _custody_ready(
        items,
        freshness_boundary="2026-10-08T02:00:00Z",
        planning_created_at="2026-10-08T00:04:00Z",
        proposal_created_at="2026-10-08T00:04:30Z",
    )
    stage = ready.proposal_stage_result
    assert stage.planning_binding.created_at == "2026-10-08T00:04:00Z"
    assert stage.proposal.created_at == "2026-10-08T00:04:30Z"
    assert ready.packet.evaluated_at == "2026-10-08T00:05:00Z"
    provenance = _seed_provenance(config, ready, stage)
    payload = _frozen_bundle_payload(config, provenance, ready)
    spec = derive_initial_required_environment_spec(
        config.repository_root, required_tests=("remote-validation",)
    )
    readiness_id = append_dependency_readiness(
        config.checkpoint_store_root, _ready_evidence(spec, ready.packet.tested_sha)
    ).evidence_id
    capsule_id = _complete_custody(
        config, items, ready, provenance, payload, readiness_id
    )
    capsule = load_approval_custody_pre_publication_evidence(
        config.checkpoint_store_root, capsule_id
    )
    identities = dict(capsule.candidate_packet.stage_identities)
    approved = dict(ready.packet.stage_identities)
    for name in ("source", "issueplan", "repository-evidence"):
        assert identities[name] == approved[name]


def test_capture_custody_rejects_drifted_durable_stage_times(tmp_path: Path) -> None:
    """Durable stage times that drifted after approval fail closed."""
    config, items, ready, provenance, payload, readiness_id = _tampered_custody_setup(
        tmp_path,
        planning_created_at="2026-10-08T00:04:00Z",
        proposal_created_at="2026-10-08T00:04:30Z",
    )
    with pytest.raises(HostIngressError) as excinfo:
        _capture_with_verifier(
            config,
            items,
            provenance,
            payload,
            readiness_id,
            _fake_verifier(ready),
        )
    assert excinfo.value.args[0] in {
        "candidate-repository-subject-drift",
        "approval-custody-unavailable",
        "fresh-pre-validation-unavailable",
        "validation-bundle-subject-mismatch",
        "governed-projection-not-accepted",
    }


def test_capture_custody_rejects_stale_freshness_boundary(tmp_path: Path) -> None:
    config = replace(
        _config(tmp_path), repository_root=_python_repo(tmp_path / "specrepo")
    )
    items = _rv_items()
    # The boundary was still ahead at the approval-time observation clock
    # (00:05) but has lapsed by the custody evaluation clock (00:08).
    ready, _observation = _custody_ready(
        items, freshness_boundary="2026-10-08T00:06:00Z"
    )
    provenance = _seed_provenance(config, ready, ready.proposal_stage_result)
    serialized = freeze_pre_validation_evidence(
        provenance.evidence_id,
        _lane_evidence(ready),
        configuration=config,
        transport=_OwnerTransport(provenance.evidence_id),
        evaluated_at="2026-10-08T00:05:30Z",
    )
    payload = json.loads(serialized)
    spec = derive_initial_required_environment_spec(
        config.repository_root, required_tests=("remote-validation",)
    )
    readiness_id = append_dependency_readiness(
        config.checkpoint_store_root, _ready_evidence(spec, ready.packet.tested_sha)
    ).evidence_id
    with pytest.raises(HostIngressError) as excinfo:
        _capture_with_verifier(
            config,
            items,
            provenance,
            payload,
            readiness_id,
            _fake_verifier(ready),
        )
    assert excinfo.value.args[0] in {
        "approval-custody-unavailable",
        "execution-packet-incomplete",
        "candidate-repository-subject-drift",
    }


def test_capture_custody_rejects_other_candidates_bundle(tmp_path: Path) -> None:
    config, items, ready, provenance, payload, readiness_id = _custody_setup(tmp_path)
    # A genuine bundle frozen for a different provenance lineage cannot be
    # attached to this candidate: the embedded plan identity must match the
    # fresh canonical plan exactly.
    other_dir = tmp_path / "other"
    other_config = _config(other_dir)
    other_items = _rv_items()
    other_ready, _obs = _custody_ready_other(other_items, _OTHER_SHA)
    other_provenance = _seed_provenance(
        other_config, other_ready, other_ready.proposal_stage_result
    )
    other_payload = _frozen_bundle_payload(other_config, other_provenance, other_ready)
    # The other lineage's different head sha must yield a different embedded
    # plan identity, or this negative test would be vacuous.
    assert (
        other_payload["validation_plan"] != payload["validation_plan"]
    ), "other lineage must produce a distinct embedded plan"
    with pytest.raises(HostIngressError, match="validation-plan-identity-mismatch"):
        _complete_custody(config, items, ready, provenance, other_payload, readiness_id)


def _authorization_comment(capsule, ready, fingerprint, command_plan_id, **overrides):
    packet = capsule.candidate_packet
    values = dict(
        issue_number=packet.issue_number,
        authorizer_id=_OWNER_LOGIN,
        authorized_candidate_packet_id=packet.packet_id,
        authorized_invocation_id=packet.invocation_id,
        authorized_operation="pre-pr-developer-loop",
        request_fingerprint=fingerprint,
        command_plan_id=command_plan_id,
        repository=packet.repository,
        expected_sha=packet.candidate_sha,
        authorized_at="2026-10-08T00:09:00Z",
        expires_at="2026-10-08T01:08:00Z",
        execution_authorized=True,
    )
    values.update(overrides)
    return ExecutionAuthorizationCommentSnapshot(
        comment_id=4243,
        author_login=_OWNER_LOGIN,
        created_at="2026-10-08T00:09:30Z",
        body=serialize_execution_authorization_comment(**values),
    )


def _originate_setup(tmp_path: Path):
    config, items, ready, provenance, payload, readiness_id = _custody_setup(tmp_path)
    capsule_id = _complete_custody(config, items, ready, provenance, payload, readiness_id)
    capsule = load_approval_custody_pre_publication_evidence(
        config.checkpoint_store_root, capsule_id
    )
    identities = dict(capsule.candidate_packet.stage_identities)
    comment = _authorization_comment(
        capsule,
        ready,
        identities["execution-request"],
        identities["command-plan"],
    )
    return config, items, ready, provenance, payload, capsule_id, capsule, comment


def test_originate_request_emits_canonical_v1_1_request(tmp_path: Path) -> None:
    (
        config,
        items,
        ready,
        provenance,
        payload,
        capsule_id,
        capsule,
        comment,
    ) = _originate_setup(tmp_path)
    serialized = originate_authorized_validation_request(
        provenance.evidence_id,
        capsule_id,
        payload,
        configuration=config,
        transport=_OwnerHostTransport(
            provenance.evidence_id, items, extra_comments=(comment,)
        ),
        evaluated_at="2026-10-08T00:10:00Z",
        content_root=config.repository_root,
    )
    request_payload = json.loads(serialized)
    assert request_payload["schema_version"] == "1.1"
    assert request_payload["request_id"].startswith("authorized-validation-request:")
    assert request_payload["validation_evidence_bundle"]["bundle_id"] == (
        payload["bundle_id"]
    )
    assert request_payload["execution_authorized"] is False
    assert request_payload["merge_authorized"] is False
    assert request_payload["automatic_retry"] is False
    assert request_payload["side_effects_performed"] is False
    reconstructed = reconstruct_authorized_validation_lifecycle_request(request_payload)
    assert reconstructed.request_id == request_payload["request_id"]
    assert reconstructed.candidate_packet.packet_id == capsule.candidate_packet.packet_id
    assert (
        reconstructed.execution_packet_stage.disposition.value
        if hasattr(reconstructed.execution_packet_stage.disposition, "value")
        else reconstructed.execution_packet_stage.disposition
    ) == "GO"


def test_originate_request_requires_current_authorization(tmp_path: Path) -> None:
    (
        config,
        items,
        ready,
        provenance,
        payload,
        capsule_id,
        capsule,
        comment,
    ) = _originate_setup(tmp_path)
    with pytest.raises(HostIngressError, match="execution-authorization-not-current"):
        originate_authorized_validation_request(
            provenance.evidence_id,
            capsule_id,
            payload,
            configuration=config,
            transport=_OwnerHostTransport(provenance.evidence_id, items),
            evaluated_at="2026-10-08T00:10:00Z",
            content_root=config.repository_root,
        )


def test_originate_request_rejects_fingerprint_mismatched_authorization(
    tmp_path: Path,
) -> None:
    (
        config,
        items,
        ready,
        provenance,
        payload,
        capsule_id,
        capsule,
        comment,
    ) = _originate_setup(tmp_path)
    wrong = _authorization_comment(
        capsule,
        ready,
        "0" * 64,
        dict(capsule.candidate_packet.stage_identities)["command-plan"],
    )
    with pytest.raises(HostIngressError, match="execution-authorization-not-current"):
        originate_authorized_validation_request(
            provenance.evidence_id,
            capsule_id,
            payload,
            configuration=config,
            transport=_OwnerHostTransport(
                provenance.evidence_id, items, extra_comments=(wrong,)
            ),
            evaluated_at="2026-10-08T00:10:00Z",
            content_root=config.repository_root,
        )


def test_originate_request_rejects_bundle_not_bound_to_custody(
    tmp_path: Path,
) -> None:
    (
        config,
        items,
        ready,
        provenance,
        payload,
        capsule_id,
        capsule,
        comment,
    ) = _originate_setup(tmp_path)
    other_dir = tmp_path / "other"
    other_config = _config(other_dir)
    other_items = _rv_items()
    other_ready, _obs = _custody_ready(other_items)
    other_provenance = _seed_provenance(
        other_config, other_ready, other_ready.proposal_stage_result
    )
    other_payload = _frozen_bundle_payload(other_config, other_provenance, other_ready)
    if json.dumps(other_payload, sort_keys=True) == json.dumps(payload, sort_keys=True):
        pytest.skip("identical fixtures produce identical bundles")
    with pytest.raises(HostIngressError):
        originate_authorized_validation_request(
            provenance.evidence_id,
            capsule_id,
            other_payload,
            configuration=config,
            transport=_OwnerHostTransport(
                provenance.evidence_id, items, extra_comments=(comment,)
            ),
            evaluated_at="2026-10-08T00:10:00Z",
            content_root=config.repository_root,
        )


def test_originate_request_rejects_unknown_custody_capsule(tmp_path: Path) -> None:
    config, items, ready, provenance, payload, readiness_id = _custody_setup(tmp_path)
    with pytest.raises(HostIngressError, match="approval-custody-unavailable"):
        originate_authorized_validation_request(
            provenance.evidence_id,
            "pre-publication-evidence:" + "0" * 64,
            payload,
            configuration=config,
            transport=_OwnerHostTransport(provenance.evidence_id, items),
            evaluated_at="2026-10-08T00:10:00Z",
            content_root=config.repository_root,
        )


def test_main_freeze_pre_validation_rejects_malformed_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    class _Stdin:
        def __init__(self, data: bytes) -> None:
            self.buffer = io.BytesIO(data)

    monkeypatch.setattr(sys, "stdin", _Stdin(b"not json"))
    status = main_freeze_pre_validation(
        ["--candidate-provenance-id", "pre-publication-evidence:" + "a" * 64]
    )
    assert status == 1
    assert "dev-validation-evidence-malformed" in capsys.readouterr().err


def test_main_originate_request_rejects_empty_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    class _Stdin:
        def __init__(self, data: bytes) -> None:
            self.buffer = io.BytesIO(data)

    monkeypatch.setattr(sys, "stdin", _Stdin(b""))
    status = main_originate_authorized_validation_request(
        [
            "--candidate-provenance-id",
            "pre-publication-evidence:" + "a" * 64,
            "--approval-custody-capsule-id",
            "pre-publication-evidence:" + "b" * 64,
        ]
    )
    assert status == 1
    assert "pre-validation-bundle-malformed" in capsys.readouterr().err


def test_main_capture_custody_without_bundle_still_stops_at_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    class _Stdin:
        def __init__(self, data: bytes) -> None:
            self.buffer = io.BytesIO(data)

    monkeypatch.setattr(sys, "stdin", _Stdin(b""))
    config = _config(tmp_path)
    ready, _observation = _custody_ready(_custody_items())
    provenance = _seed_provenance(config, ready, ready.proposal_stage_result)
    monkeypatch.setattr(
        host_ingress,
        "capture_approved_candidate_custody",
        lambda provenance_id,
        pre_validation_bundle_payload=None,
        dependency_readiness_evidence_id=None: (
            (_ for _ in ()).throw(
                HostIngressError("pre-validation-evidence-references-unavailable")
            )
        ),
    )
    status = main_capture_custody(
        [
            "--candidate-provenance-id",
            provenance.evidence_id,
            "--dependency-readiness-evidence-id",
            "dependency-readiness:" + "a" * 64,
        ]
    )
    assert status == 1
    assert "pre-validation-evidence-references-unavailable" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# #3333: record_codespaces_dependency_readiness


def _prep_measurements(ready, spec, **overrides):
    """Genuine-shape fixed-script measurements bound to the exact candidate."""
    measured = {
        "execution_surface_id": "codespace:agent-os-d61",
        "workspace_identity": (
            "codespace:agent-os-d61:worktree-sha:" + ready.packet.tested_sha
        ),
        "source_sha": ready.packet.tested_sha,
        "environment_health_evidence_id": "sha256:" + "b" * 64,
        "manifest_sha256": spec.dependency_manifest_identity.sha256,
        "local_project_sha256": {
            requirement.relative_path: requirement.sha256
            for requirement in spec.local_project_requirements
        },
        "runtime_version": "3.11.13",
        "source_identity": spec.approved_source_identity,
        "source_reachable": True,
        "package_manager_version": "24.0",
        "observed_at": "2026-10-08T00:07:00Z",
        "expires_at": "2026-10-08T01:00:00Z",
        "install_attempted": True,
        "install_succeeded": True,
        "install_terminated_on_timeout": False,
        "failure_reason_code": None,
        "resolved_dependency_identity": "pip-freeze:" + "0" * 64,
        "argv": [
            "/usr/local/bin/python3",
            "-m",
            "pip",
            "install",
            "--only-binary=:all:",
            "--index-url=https://pypi.org/simple",
            "-r",
            "requirements-dev.txt",
            "-e",
            "08_Tooling/agent-memory-context-manager",
            "-e",
            "08_Tooling/reusable-capability-registry",
            "-e",
            "08_Tooling/visual-asset-intake",
            "-e",
            "08_Tooling/workflow-scheduler",
            "-e",
            "src",
        ],
    }
    measured.update(overrides)
    return measured


def test_record_readiness_completes_and_feeds_custody(tmp_path: Path) -> None:
    config, items, ready, provenance, payload, _id = _custody_setup(tmp_path)
    spec = derive_initial_required_environment_spec(
        config.repository_root, required_tests=("remote-validation",)
    )
    receipt = _lane_evidence(
        ready,
        execution_surface_id="codespace:agent-os-d61",
        environment_health_evidence_id="sha256:" + "b" * 64,
        dependency_preparation=_prep_measurements(ready, spec),
    )
    evidence_id = record_codespaces_dependency_readiness(
        provenance.evidence_id,
        receipt,
        configuration=config,
        transport=_OwnerTransport(provenance.evidence_id),
        evaluated_at="2026-10-08T00:08:00Z",
        content_root=config.repository_root,
    )
    stored = load_dependency_readiness(config.checkpoint_store_root, evidence_id)
    assert stored.preparation_status is DependencyPreparationStatus.READY
    assert stored.source_sha == ready.packet.tested_sha
    assert stored.required_environment_id == spec.required_environment_id
    assert stored.resolved_dependency_identity == "pip-freeze:" + "0" * 64
    assert stored.execution_surface_id == "codespace:agent-os-d61"
    assert stored.environment_health_evidence_id == "sha256:" + "b" * 64
    assert stored.observed_at == "2026-10-08T00:07:00Z"
    # The recorded readiness is accepted by the custody capture path.
    capsule_id = _complete_custody(
        config, items, ready, provenance, payload, evidence_id
    )
    assert capsule_id.startswith("pre-publication-evidence:")


def test_record_readiness_requires_measurements(tmp_path: Path) -> None:
    config, items, ready, provenance, payload, _id = _custody_setup(tmp_path)
    for missing in (None, "READY"):
        receipt = _lane_evidence(
            ready,
            execution_surface_id="codespace:agent-os-d61",
            environment_health_evidence_id="sha256:" + "b" * 64,
            dependency_preparation=missing,
        )
        with pytest.raises(
            HostIngressError, match="dependency-readiness-record-unavailable"
        ):
            record_codespaces_dependency_readiness(
                provenance.evidence_id,
                receipt,
                configuration=config,
                transport=_OwnerTransport(provenance.evidence_id),
                evaluated_at="2026-10-08T00:08:00Z",
                content_root=config.repository_root,
            )


def test_record_readiness_fails_closed_on_partial_measurements(
    tmp_path: Path,
) -> None:
    config, items, ready, provenance, payload, _id = _custody_setup(tmp_path)
    spec = derive_initial_required_environment_spec(
        config.repository_root, required_tests=("remote-validation",)
    )
    measured = _prep_measurements(ready, spec)
    del measured["runtime_version"]
    receipt = _lane_evidence(
        ready,
        execution_surface_id="codespace:agent-os-d61",
        environment_health_evidence_id="sha256:" + "b" * 64,
        dependency_preparation=measured,
    )
    with pytest.raises(HostIngressError, match="dependency-readiness-malformed"):
        record_codespaces_dependency_readiness(
            provenance.evidence_id,
            receipt,
            configuration=config,
            transport=_OwnerTransport(provenance.evidence_id),
            evaluated_at="2026-10-08T00:08:00Z",
            content_root=config.repository_root,
        )


def test_record_readiness_rejects_argv_drift(tmp_path: Path) -> None:
    config, items, ready, provenance, payload, _id = _custody_setup(tmp_path)
    spec = derive_initial_required_environment_spec(
        config.repository_root, required_tests=("remote-validation",)
    )
    measured = _prep_measurements(
        ready,
        spec,
        argv=[
            "/usr/local/bin/python3",
            "-m",
            "pip",
            "install",
            "--index-url=https://pypi.org/simple",
            "-r",
            "requirements-dev.txt",
        ],
    )
    receipt = _lane_evidence(
        ready,
        execution_surface_id="codespace:agent-os-d61",
        environment_health_evidence_id="sha256:" + "b" * 64,
        dependency_preparation=measured,
    )
    with pytest.raises(
        HostIngressError, match="dependency-preparation-argv-mismatch"
    ):
        record_codespaces_dependency_readiness(
            provenance.evidence_id,
            receipt,
            configuration=config,
            transport=_OwnerTransport(provenance.evidence_id),
            evaluated_at="2026-10-08T00:08:00Z",
            content_root=config.repository_root,
        )


def test_record_readiness_rejects_drifted_and_failed_measurements(
    tmp_path: Path,
) -> None:
    config, items, ready, provenance, payload, _id = _custody_setup(tmp_path)
    spec = derive_initial_required_environment_spec(
        config.repository_root, required_tests=("remote-validation",)
    )
    drifted_subject = (
        "0" * 40 if ready.packet.tested_sha != "0" * 40 else "1" * 40
    )
    cases = [
        # Manifest digest no longer matches the tested content's spec.
        ({"manifest_sha256": "0" * 64}, "dependency-readiness-not-ready"),
        # Approved source identity drift.
        (
            {"source_identity": "evil.example.com/simple"},
            "dependency-readiness-not-ready",
        ),
        # Local project content drift.
        (
            {
                "local_project_sha256": {
                    requirement.relative_path: "0" * 64
                    for requirement in spec.local_project_requirements
                }
            },
            "dependency-readiness-not-ready",
        ),
        # Incompatible measured runtime.
        ({"runtime_version": "3.10.0"}, "dependency-readiness-not-ready"),
        # The bounded attempt never happened.
        ({"install_attempted": False}, "dependency-readiness-not-ready"),
        # The bounded attempt failed with a canonical classification.
        (
            {
                "install_succeeded": False,
                "resolved_dependency_identity": None,
                "failure_reason_code": "dependency.package-unavailable",
            },
            "dependency-readiness-not-ready",
        ),
        # Stale readiness at the record clock.
        (
            {"expires_at": "2026-10-08T00:07:30Z"},
            "dependency-readiness-not-current",
        ),
        # Tested-subject drift.
        (
            {"source_sha": drifted_subject},
            "dependency-readiness-subject-mismatch",
        ),
    ]
    for overrides, reason in cases:
        receipt = _lane_evidence(
            ready,
            execution_surface_id="codespace:agent-os-d61",
            environment_health_evidence_id="sha256:" + "b" * 64,
            dependency_preparation=_prep_measurements(ready, spec, **overrides),
        )
        with pytest.raises(HostIngressError, match=reason):
            record_codespaces_dependency_readiness(
                provenance.evidence_id,
                receipt,
                configuration=config,
                transport=_OwnerTransport(provenance.evidence_id),
                evaluated_at="2026-10-08T00:08:00Z",
                content_root=config.repository_root,
            )


def test_record_readiness_binds_surface_and_health_evidence(tmp_path: Path) -> None:
    config, items, ready, provenance, payload, _id = _custody_setup(tmp_path)
    spec = derive_initial_required_environment_spec(
        config.repository_root, required_tests=("remote-validation",)
    )
    measured = _prep_measurements(ready, spec)
    surface_drift = _lane_evidence(
        ready,
        execution_surface_id="codespace:other-surface",
        environment_health_evidence_id="sha256:" + "b" * 64,
        dependency_preparation=measured,
    )
    with pytest.raises(
        HostIngressError, match="dependency-readiness-surface-mismatch"
    ):
        record_codespaces_dependency_readiness(
            provenance.evidence_id,
            surface_drift,
            configuration=config,
            transport=_OwnerTransport(provenance.evidence_id),
            evaluated_at="2026-10-08T00:08:00Z",
            content_root=config.repository_root,
        )
    health_drift = _lane_evidence(
        ready,
        execution_surface_id="codespace:agent-os-d61",
        environment_health_evidence_id="sha256:" + "c" * 64,
        dependency_preparation=measured,
    )
    with pytest.raises(
        HostIngressError, match="dependency-readiness-health-mismatch"
    ):
        record_codespaces_dependency_readiness(
            provenance.evidence_id,
            health_drift,
            configuration=config,
            transport=_OwnerTransport(provenance.evidence_id),
            evaluated_at="2026-10-08T00:08:00Z",
            content_root=config.repository_root,
        )


def test_record_readiness_rejects_receipt_identity_drift(tmp_path: Path) -> None:
    config, items, ready, provenance, payload, _id = _custody_setup(tmp_path)
    spec = derive_initial_required_environment_spec(
        config.repository_root, required_tests=("remote-validation",)
    )
    receipt = _lane_evidence(
        ready,
        request_id="dev-validation:" + "f" * 64,
        execution_surface_id="codespace:agent-os-d61",
        environment_health_evidence_id="sha256:" + "b" * 64,
        dependency_preparation=_prep_measurements(ready, spec),
    )
    with pytest.raises(
        HostIngressError, match="dev-validation-observation-rejected"
    ):
        record_codespaces_dependency_readiness(
            provenance.evidence_id,
            receipt,
            configuration=config,
            transport=_OwnerTransport(provenance.evidence_id),
            evaluated_at="2026-10-08T00:08:00Z",
            content_root=config.repository_root,
        )


def test_main_record_dependency_readiness_rejects_malformed_identity(
    capsys: pytest.CaptureFixture,
) -> None:
    status = main_record_dependency_readiness(
        ["--candidate-provenance-id", "bogus"]
    )
    assert status == 1
    assert "candidate-provenance-id-malformed" in capsys.readouterr().err


def test_main_record_dependency_readiness_prints_blocked_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    class _Stdin:
        def __init__(self, data: bytes) -> None:
            self.buffer = io.BytesIO(data)

    monkeypatch.setattr(sys, "stdin", _Stdin(b"{}"))
    config = _config(tmp_path)
    ready, _observation = _custody_ready(_custody_items())
    provenance = _seed_provenance(config, ready, ready.proposal_stage_result)
    monkeypatch.setattr(
        host_ingress,
        "record_codespaces_dependency_readiness",
        lambda provenance_id, observed_evidence: (
            (_ for _ in ()).throw(
                HostIngressError("dependency-readiness-record-unavailable")
            )
        ),
    )
    status = main_record_dependency_readiness(
        ["--candidate-provenance-id", provenance.evidence_id]
    )
    assert status == 1
    assert "dependency-readiness-record-unavailable" in capsys.readouterr().err
