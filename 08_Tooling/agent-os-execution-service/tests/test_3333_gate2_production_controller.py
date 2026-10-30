"""Focused tests for the Gate 2 (#3333) production-host controller.

All tests are offline: the pilot driver, the codespace selection resolver,
and the transport builder are injected fakes. No live codespace execution,
no network, and no credential use happens in this file. The happy path
composes the REAL ``build_production_host_bootstrap`` with fake transports
so the production composition seam itself is exercised.

The bound-path tests at the end are different on purpose: they use a real
temporary checkpoint store, real canonical record loaders, the real
governed-resume factory, and the real production bootstrap, with only the
external GitHub/Codespaces/network surfaces mocked (a dummy read token,
a fake Codespace selection, and a test-only dispatch stub for the
controller-level receipt test). Downstream fixed-pilot admission itself is
proved by the existing fixed-codespace-pilot suite, not by that stub.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXECUTION_SERVICE_SRC = REPOSITORY_ROOT / "08_Tooling/agent-os-execution-service/src"
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
for _path in (REPOSITORY_ROOT, EXECUTION_SERVICE_SRC, SCHEDULER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import hashlib

import pytest

from agent_os_execution_service.gate2_production_controller import (
    Gate2ControllerError,
    _build_bound_bootstrap,
    _persist_receipt_atomically,
    main,
    run_gate2_fixed_pilot_controller,
)
from agent_os_execution_service.host_github_read_transport import (
    HostGitHubTransportUnavailable,
)
from agent_os_execution_service.production_host_bootstrap import (
    ProductionHostBootstrap,
)
from workflow_scheduler.governance.dev_validation_codespaces import (
    CodespaceSelection,
)

HANDOFF = "a" * 64
SHA = "b" * 40
OTHER_SHA = "c" * 40
BODY = f"/agent-os codespace-implementation executor-handoff:{HANDOFF} {SHA}"


def _event(
    body: str = BODY,
    *,
    actor: str = "Blummer92",
    repo: str = "Blummer92/agent-os",
    issue: int = 3333,
    action: str = "created",
) -> dict:
    return {
        "action": action,
        "repository": {"full_name": repo},
        "issue": {"number": issue},
        "comment": {"id": 101, "body": body, "user": {"login": actor}},
        "sender": {"login": actor},
    }


@pytest.fixture()
def host(tmp_path: Path) -> dict:
    store = tmp_path / "store"
    repo_root = tmp_path / "repo"
    workspace_parent = tmp_path / "ws"
    lease_dir = tmp_path / "leases"
    (store / "invocations").mkdir(parents=True)
    (repo_root / "scripts").mkdir(parents=True)
    (repo_root / "scripts" / "verify-repo-state.sh").write_text("#!/bin/sh\n")
    (repo_root / ".git").mkdir()
    workspace_parent.mkdir()
    lease_dir.mkdir()
    return {
        "AGENT_OS_CHECKPOINT_STORE_ROOT": str(store),
        "AGENT_OS_REPOSITORY_ROOT": str(repo_root),
        "AGENT_OS_WORKSPACE_PARENT": str(workspace_parent),
        "AGENT_OS_LEASE_DIRECTORY": str(lease_dir),
        "CODESPACE_NAME": "test-box",
        "store": store,
        "lease_dir": lease_dir,
    }


def _write_event(tmp_path: Path, event: dict) -> Path:
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event))
    return path


def _selection(name: str = "test-box") -> CodespaceSelection:
    return CodespaceSelection(
        selected=True, reason="test", codespace_name=name, state="Available"
    )


class _FakeIssueTransport:
    def get_issue(self, repository: str, issue_number: int):  # pragma: no cover
        raise AssertionError("no network in tests")


class _FakeAuthTransport:
    def read_authorization_source(
        self, repository: str, issue_number: int
    ):  # pragma: no cover
        raise AssertionError("no network in tests")


class _FakeEvidenceReader:
    def read_dependency_evidence(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("no evidence reads in tests")

    def read_validation_evidence(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("no evidence reads in tests")


def _transports():
    return (
        _FakeIssueTransport(),
        _FakeAuthTransport(),
        _FakeEvidenceReader(),
        lambda invocation: "fake-verifier-stdout",
    )


def _completed_receipt() -> dict:
    return {
        "schema_version": "1.0",
        "operation_id": "codespace-implementation-pilot-v1",
        "status": "completed",
        "reason_codes": ["fixed-head-probe-passed"],
        "repository": "Blummer92/agent-os",
        "issue_number": 3333,
        "handoff_id": f"executor-handoff:{HANDOFF}",
        "expected_sha": SHA,
    }


def test_missing_event_document_fails_closed(tmp_path: Path, host: dict) -> None:
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=tmp_path / "nope.json",
            environ=host,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "event-document-unreadable"


def test_malformed_event_document_fails_closed(tmp_path: Path, host: dict) -> None:
    path = tmp_path / "event.json"
    path.write_text("{not json")
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "event-document-malformed"


def test_wrong_actor_envelope_never_drives(tmp_path: Path, host: dict) -> None:
    calls: list = []
    path = _write_event(tmp_path, _event(actor="mallory"))
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=lambda envelope, bootstrap: calls.append(envelope),
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "envelope-not-accepted"
    assert calls == []


def test_wrong_repository_envelope_rejected(tmp_path: Path, host: dict) -> None:
    path = _write_event(tmp_path, _event(repo="someone-else/agent-os"))
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "envelope-not-accepted"


def test_wrong_issue_envelope_rejected(tmp_path: Path, host: dict) -> None:
    path = _write_event(tmp_path, _event(issue=9999))
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "envelope-not-accepted"


def test_unrecognized_trigger_body_rejected(tmp_path: Path, host: dict) -> None:
    path = _write_event(tmp_path, _event(body="/agent-os do something else"))
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "envelope-not-accepted"


def test_missing_host_paths_fail_closed(tmp_path: Path) -> None:
    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ={},
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "host-configuration-invalid"
    assert "AGENT_OS_CHECKPOINT_STORE_ROOT" in str(excinfo.value)


def test_missing_invocations_dir_fails_closed(tmp_path: Path, host: dict) -> None:
    (host["store"] / "invocations").rmdir()
    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "checkpoint-store-not-initialized"


def test_missing_verifier_script_fails_closed(tmp_path: Path, host: dict) -> None:
    (
        Path(host["AGENT_OS_REPOSITORY_ROOT"]) / "scripts" / "verify-repo-state.sh"
    ).unlink()
    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "repository-identity-unverified"


def test_unqualified_surface_fails_closed(tmp_path: Path, host: dict) -> None:
    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            resolve_selection=lambda: CodespaceSelection(selected=False, reason="nope"),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "execution-surface-unqualified"


def test_host_surface_identity_mismatch_fails_closed(
    tmp_path: Path, host: dict
) -> None:
    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            resolve_selection=lambda: _selection(name="other-box"),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "host-surface-identity-mismatch"


def test_missing_host_surface_identity_fails_closed(tmp_path: Path, host: dict) -> None:
    del host["CODESPACE_NAME"]
    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "host-surface-identity-unavailable"


def test_conflicting_active_lease_fails_closed(tmp_path: Path, host: dict) -> None:
    (host["lease_dir"] / ("d" * 64 + ".active.json")).write_text("{}")
    calls: list = []
    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=lambda envelope, bootstrap: calls.append(envelope),
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "conflicting-active-lease"
    assert calls == []


def test_symlink_in_lease_directory_fails_closed(tmp_path: Path, host: dict) -> None:
    target = tmp_path / "target"
    target.write_text("x")
    (host["lease_dir"] / "sneaky").symlink_to(target)
    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "lease-directory-symlink-present"


def test_missing_credential_fails_closed(tmp_path: Path, host: dict) -> None:
    def _no_credential() -> tuple:
        raise HostGitHubTransportUnavailable("no token")

    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            resolve_selection=lambda: _selection(),
            build_transports=_no_credential,
        )
    assert excinfo.value.reason == "github-read-credential-unavailable"


def test_happy_path_persists_receipt_atomically(tmp_path: Path, host: dict) -> None:
    seen: dict = {}

    def _drive(envelope: dict, *, bootstrap: object) -> dict:
        assert type(bootstrap) is ProductionHostBootstrap
        seen["envelope"] = envelope
        return _completed_receipt()

    path = _write_event(tmp_path, _event())
    result = run_gate2_fixed_pilot_controller(
        event_path=path,
        environ=host,
        drive=_drive,
        resolve_selection=lambda: _selection(),
        build_transports=_transports,
    )
    assert result.status == "completed"
    assert result.reason_codes == ("fixed-head-probe-passed",)
    receipt_path = Path(result.receipt_path)
    receipts_dir = host["store"] / "invocations" / "receipts"
    assert receipt_path.parent == receipts_dir
    assert receipt_path.suffix == ".json"
    assert receipt_path.name.startswith("fixed-head-probe-")
    assert HANDOFF in receipt_path.name and SHA in receipt_path.name
    # The top-level invocations/*.json descriptor invariant is untouched: the
    # existing handoff discovery scans every top-level *.json as a descriptor.
    assert list((host["store"] / "invocations").glob("*.json")) == []
    # Atomicity: no temp file left behind, content is exactly the receipt.
    assert list(receipts_dir.glob("*.tmp")) == []
    assert json.loads(receipt_path.read_text()) == _completed_receipt()
    # Bounded reference for the existing authorized consumer.
    reference = result.receipt_reference
    assert reference["receipt_path"] == str(receipt_path)
    assert reference["handoff_id"] == f"executor-handoff:{HANDOFF}"
    assert reference["expected_sha"] == SHA
    assert reference["status"] == "completed"
    assert "stdout_tail" not in reference
    assert seen["envelope"]["codespace_implementation_sha_or_none"] == SHA


def test_blocked_receipt_is_persisted_as_blocked(tmp_path: Path, host: dict) -> None:
    blocked = dict(_completed_receipt())
    blocked.update(status="blocked", reason_codes=["canonical-invocation-not-admitted"])
    path = _write_event(tmp_path, _event())
    result = run_gate2_fixed_pilot_controller(
        event_path=path,
        environ=host,
        drive=lambda envelope, bootstrap: blocked,
        resolve_selection=lambda: _selection(),
        build_transports=_transports,
    )
    assert result.status == "blocked"
    assert result.reason_codes == ("canonical-invocation-not-admitted",)
    assert json.loads(Path(result.receipt_path).read_text())["status"] == "blocked"


def test_receipt_write_failure_fails_closed(tmp_path: Path) -> None:
    not_a_dir = tmp_path / "file"
    not_a_dir.write_text("x")
    with pytest.raises(Gate2ControllerError) as excinfo:
        _persist_receipt_atomically(not_a_dir, "r.json", {"a": 1})
    assert excinfo.value.reason == "receipt-write-failed"


def test_receipt_name_collision_fails_closed(tmp_path: Path, host: dict) -> None:
    invocations = host["store"] / "invocations"
    (invocations / "fixed-head-probe-x.json").write_text("{}")
    with pytest.raises(Gate2ControllerError) as excinfo:
        _persist_receipt_atomically(invocations, "fixed-head-probe-x.json", {"a": 1})
    assert excinfo.value.reason == "receipt-already-exists"


def test_receipts_dir_created_private_on_demand(tmp_path: Path, host: dict) -> None:
    import stat

    path = _write_event(tmp_path, _event())
    result = run_gate2_fixed_pilot_controller(
        event_path=path,
        environ=host,
        drive=lambda envelope, bootstrap: _completed_receipt(),
        resolve_selection=lambda: _selection(),
        build_transports=_transports,
    )
    receipts_dir = host["store"] / "invocations" / "receipts"
    assert receipts_dir.is_dir()
    assert stat.S_IMODE(receipts_dir.stat().st_mode) == 0o700
    assert Path(result.receipt_path).parent == receipts_dir


def test_receipts_dir_symlink_fails_closed(tmp_path: Path, host: dict) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (host["store"] / "invocations" / "receipts").symlink_to(target)
    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=lambda envelope, bootstrap: _completed_receipt(),
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "receipts-dir-is-symlink"


def test_handoff_discovery_unaffected_by_receipts(tmp_path: Path, host: dict) -> None:
    from scripts.agent_os_execution_checkpoint.handoff_discovery import (
        InvocationHandoffDiscoveryStatus,
        discover_issue_handoff,
    )

    path = _write_event(tmp_path, _event())
    run_gate2_fixed_pilot_controller(
        event_path=path,
        environ=host,
        drive=lambda envelope, bootstrap: _completed_receipt(),
        resolve_selection=lambda: _selection(),
        build_transports=_transports,
    )
    outcome = discover_issue_handoff(
        host["store"], repository="Blummer92/agent-os", issue_number=3333
    )
    # NOT_FOUND (empty descriptor store), never NEEDS_DECISION: the receipt
    # must not poison the existing descriptor discovery.
    assert outcome.status is InvocationHandoffDiscoveryStatus.NOT_FOUND


def test_receipts_dir_failure_precedes_drive(tmp_path: Path, host: dict) -> None:
    # The receipts home must exist before the pilot drives: a post-drive
    # failure would lose the receipt of an already-consumed probe.
    target = tmp_path / "target"
    target.mkdir()
    (host["store"] / "invocations" / "receipts").symlink_to(target)
    calls: list = []
    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=lambda envelope, bootstrap: calls.append(envelope),
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "receipts-dir-is-symlink"
    assert calls == []


def test_main_cli_failure_contract(tmp_path: Path, capsys) -> None:
    code = main(["--event", str(tmp_path / "missing.json")])
    assert code == 1
    err = json.loads(capsys.readouterr().err)
    assert err["status"] == "failed"
    assert err["reason_codes"] == ["event-document-unreadable"]


def test_main_cli_success_contract(
    tmp_path: Path, host: dict, capsys, monkeypatch
) -> None:
    for key, value in host.items():
        if isinstance(value, str):
            monkeypatch.setenv(key, value)
    path = _write_event(tmp_path, _event())

    import agent_os_execution_service.gate2_production_controller as controller

    monkeypatch.setattr(
        controller,
        "read_canonical_codespace_selection",
        lambda resolve_selection=None: _selection(),
    )
    monkeypatch.setattr(
        controller,
        "_build_bound_bootstrap",
        lambda envelope, configuration: controller._build_bootstrap(
            _transports(), configuration
        ),
    )
    monkeypatch.setattr(
        controller,
        "drive_fixed_codespace_pilot_on_host",
        lambda envelope, bootstrap: _completed_receipt(),
    )
    code = main(["--event", str(path)])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["status"] == "completed"
    assert out["consumer"] == "github-service-agent-governed-publication-path"
    assert Path(out["receipt_path"]).is_file()


@pytest.mark.parametrize(
    "reason_fields",
    [
        pytest.param({}, id="missing"),
        pytest.param({"reason_codes": None}, id="null"),
        pytest.param({"reason_codes": []}, id="empty-list"),
        pytest.param({"reason_codes": "not-a-list"}, id="scalar-string"),
        pytest.param({"reason_codes": 17}, id="scalar-integer"),
        pytest.param({"reason_codes": ["valid", 17]}, id="mixed-list"),
        pytest.param({"reason_codes": [""]}, id="empty-string"),
        pytest.param({"reason_codes": ["valid", ""]}, id="mixed-empty-string"),
    ],
)
def test_malformed_driver_reason_codes_fail_before_persistence(
    tmp_path: Path, host: dict, reason_fields: dict
) -> None:
    """Bad driver evidence must never become a durable or successful receipt."""
    receipt = _completed_receipt()
    del receipt["reason_codes"]
    receipt.update(reason_fields)
    path = _write_event(tmp_path, _event())

    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=lambda envelope, bootstrap: receipt,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )

    assert excinfo.value.reason == "receipt-reason-codes-invalid"
    receipts_dir = host["store"] / "invocations" / "receipts"
    assert receipts_dir.is_dir()
    assert list(receipts_dir.iterdir()) == []


# ---------------------------------------------------------------------------
# Bound production path (R1, #3333): real store + real factory + real
# bootstrap. Only external surfaces are mocked: a dummy GH read token
# (token construction is local; no transport method is ever invoked),
# a fake Codespace selection, and, for the controller-level receipt test,
# a dispatch stub that first asserts the bound bootstrap. The stub does
# NOT prove downstream pilot admission; that is proved by the existing
# fixed-codespace-pilot suite with real reconstruction.
# ---------------------------------------------------------------------------

_BOUND_REPO = "Blummer92/agent-os"
_BOUND_BASE = "1" * 40
_BOUND_SHA = "a" * 40
_BOUND_FINGERPRINT = "3" * 64
_BOUND_INVOCATION = "invocation:3333-probe"
_BOUND_CODESPACE = "happy-codespace"


def _bound_hid(prefix: str, label: str) -> str:
    return f"{prefix}:{hashlib.sha256(label.encode()).hexdigest()}"


def _bound_store(tmp_path: Path, monkeypatch, *, readiness_expires: str = "2030-01-01T00:00:00Z"):
    """Build a real checkpoint store with mutually consistent records."""
    from scripts.agent_os_candidate_packet.models import (
        CandidatePacket,
        CandidatePacketPhase,
        candidate_packet_id,
    )
    from scripts.agent_os_execution_capabilities.approved_projection import (
        GovernedProjectionEvidenceResult,
    )
    from scripts.agent_os_execution_capabilities.dependencies import (
        DependencyArtifactIdentity,
        DependencyCacheState,
        DependencyEcosystem,
        DependencyInstallMode,
        DependencyPreparationStatus,
        DependencyReadinessEvidence,
        ReproducibilityLevel,
        RequiredEnvironmentSpec,
    )
    from scripts.agent_os_execution_capabilities.models import (
        RepositoryEvidenceType,
        RepositoryIdentity,
    )
    from scripts.agent_os_execution_checkpoint.dependency_readiness_store import (
        append_dependency_readiness,
    )
    from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
        INVOCATION_DESCRIPTOR_SCHEMA_NAME,
        INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
        GovernedInvocationDescriptor,
    )
    from agent_os_execution_service.executor_routing import (
        EXECUTOR_ROUTING_SCHEMA_VERSION,
        ExecutorCapability,
        ExecutorHandoff,
        ExecutorRoute,
        ExecutorRouteDecision,
        ExecutorRouteReason,
    )
    from agent_os_execution_service.governed_resume_restart_capsule import (
        GovernedResumeRestartCapsule,
    )
    from agent_os_execution_service.production_host_bootstrap import (
        load_production_host_configuration,
    )
    from agent_os_execution_service.runtime_execution_request import (
        RUNTIME_EXECUTION_REQUEST_LEGACY_SCHEMA_VERSION,
        RUNTIME_EXECUTION_REQUEST_SCHEMA_NAME,
        RuntimeExecutionRequest,
        append_runtime_execution_request,
    )
    from scripts.agent_os_issue_acceptance.approval_records import (
        ApprovalBinding,
        ApprovalKind,
        ApprovalRecord,
        ApprovalState,
    )
    from scripts.agent_os_issue_acceptance.scheduler_handoff import HandoffCohort
    from scripts.agent_os_remote_validation.advisory_gate import (
        evaluate_advisory_pre_pr_evidence,
    )
    from scripts.agent_os_remote_validation.evidence_bundle import (
        build_validation_evidence_bundle,
        serialize_validation_evidence_bundle,
    )
    from scripts.agent_os_remote_validation.models import ValidationPlan
    from scripts.agent_os_remote_validation.selector import (
        compute_command_set_digest,
        validation_plan_id,
    )

    identity = RepositoryIdentity(host="github.com", owner="Blummer92", repository="agent-os")
    plan = ValidationPlan(
        selector_version="1.0.0", repository=_BOUND_REPO, pull_request=1,
        base_sha=_BOUND_BASE, head_sha=_BOUND_SHA, profile="static", commands=(),
        command_set_digest=compute_command_set_digest("1.0.0", ()),
        reason_codes=("profile.documentation-static",), remote_build_required=False,
    )
    plan_id = validation_plan_id(plan)
    projection = GovernedProjectionEvidenceResult(
        status="accepted", schema_version="1.0", projection_id="projection:test",
        proposal_id="proposal:test", approval_id="approval:test",
        repository_identity=identity, base_branch="main", base_sha=_BOUND_BASE,
        head_sha=_BOUND_SHA, evaluated_sha=_BOUND_BASE, tested_sha=_BOUND_SHA,
        repository_evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        repository_state_evidence_id="repository-state:test",
        implementation_contract_fingerprint=_BOUND_FINGERPRINT, reason_codes=(), details=(),
    )
    expectations = dict(
        expected_repository=identity, expected_pull_request=1, expected_base_branch="main",
        expected_base_sha=_BOUND_BASE, expected_source_head_sha=_BOUND_SHA,
        expected_tested_sha=_BOUND_SHA,
        expected_repository_evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        expected_projection_id="projection:test", expected_proposal_id="proposal:test",
        expected_approval_id="approval:test",
        expected_repository_state_evidence_id="repository-state:test",
        expected_implementation_contract_fingerprint=_BOUND_FINGERPRINT,
        expected_selector_version="1.0.0", expected_profile="static",
        expected_command_set_digest=plan.command_set_digest, expected_plan_id=plan_id,
        runner_id="runner:test", invocation_id=_BOUND_INVOCATION,
        started_at="2026-08-21T12:00:00Z", completed_at="2026-08-21T12:00:01Z",
    )
    bundle = build_validation_evidence_bundle(projection, plan, (), **expectations)
    advisory = evaluate_advisory_pre_pr_evidence(
        projection, plan, (), current_base_sha=_BOUND_BASE,
        current_source_head_sha=_BOUND_SHA, expected_bundle_id=bundle.bundle_id, **expectations,
    )
    payload = serialize_validation_evidence_bundle(bundle)

    spec = RequiredEnvironmentSpec(
        ecosystem=DependencyEcosystem.PYTHON_PIP, package_root=".",
        runtime_requirement="python>=3.12",
        dependency_manifest_identity=DependencyArtifactIdentity(
            relative_path="pyproject.toml", sha256="0" * 64),
        lock_or_constraints_identity=None, install_mode=DependencyInstallMode.NORMAL,
        approved_source_identity="pypi", required_validation_command_ids=("pytest",),
    )
    readiness = DependencyReadinessEvidence(
        execution_surface_id="codespace:" + _BOUND_CODESPACE,
        workspace_identity="pilot-workspace:test", source_sha=_BOUND_SHA,
        required_environment_id=spec.required_environment_id, package_root=".",
        ecosystem=DependencyEcosystem.PYTHON_PIP, runtime_version="3.12",
        package_manager_version="pip", declared_dependency_identity="deps:test",
        lock_or_constraints_identity=None, install_mode=DependencyInstallMode.NORMAL,
        source_or_registry_identity="pypi", cache_state=DependencyCacheState.CURRENT_COMPLETE,
        preparation_status=DependencyPreparationStatus.READY,
        resolved_dependency_identity="resolved:test",
        environment_health_evidence_id="environment-health:test",
        observed_at="2026-01-01T00:00:00Z", expires_at=readiness_expires,
        reproducibility_level=ReproducibilityLevel.LOCKED,
    )

    def _packet(packet_id: str) -> CandidatePacket:
        return CandidatePacket(
            schema_name="agent-os-candidate-packet", schema_version="1.0",
            phase=CandidatePacketPhase.EXECUTION_CANDIDATE, packet_id=packet_id,
            repository=_BOUND_REPO, issue_number=3333, invocation_id=_BOUND_INVOCATION,
            candidate_ref="refs/heads/agent/3333-probe", base_branch="main",
            base_sha=_BOUND_BASE, candidate_sha=_BOUND_SHA, source_sha=_BOUND_SHA,
            tested_sha=_BOUND_SHA, evaluator_sha=_BOUND_SHA, external_build_sha=None,
            freshness_boundary="2026-08-21T12:00:00Z", evaluated_at="2026-08-21T12:00:00Z",
            stage_identities=(), stage_payload_digests=(), provenance_manifest=(),
            invalidation_manifest=(), allowed_files=("08_Tooling/agent-os-execution-service",),
            forbidden_paths=(".github/workflows",), expected_changed_paths=(),
            required_tests=(), command_identities=(), argv_bindings=(),
            per_command_timeout_seconds=None, total_timeout_seconds=None,
            max_output_bytes=None, approval_boundary_summary="none",
            execution_authorization_boundary_summary="none", evidence_completeness="complete",
            disposition="execution-candidate",
        )

    probe = object.__new__(CandidatePacket)
    for _name, _value in dict(
        schema_name="agent-os-candidate-packet", schema_version="1.0",
        phase=CandidatePacketPhase.EXECUTION_CANDIDATE, repository=_BOUND_REPO,
        issue_number=3333, invocation_id=_BOUND_INVOCATION,
        candidate_ref="refs/heads/agent/3333-probe", base_branch="main",
        base_sha=_BOUND_BASE, candidate_sha=_BOUND_SHA, source_sha=_BOUND_SHA,
        tested_sha=_BOUND_SHA, evaluator_sha=_BOUND_SHA, external_build_sha=None,
        freshness_boundary="2026-08-21T12:00:00Z", stage_identities=(),
        stage_payload_digests=(), provenance_manifest=(), invalidation_manifest=(),
        allowed_files=("08_Tooling/agent-os-execution-service",),
        forbidden_paths=(".github/workflows",), expected_changed_paths=(),
        required_tests=(), command_identities=(), argv_bindings=(),
        per_command_timeout_seconds=None, total_timeout_seconds=None,
        max_output_bytes=None, approval_boundary_summary="none",
        execution_authorization_boundary_summary="none", evidence_completeness="complete",
        disposition="execution-candidate",
    ).items():
        object.__setattr__(probe, _name, _value)
    packet = _packet(candidate_packet_id(probe))

    approval = ApprovalRecord(
        schema_version="1.0", approval_id="", approval_revision="",
        revision_number=1, previous_revision=None, approval_kind=ApprovalKind.IMPLEMENTATION,
        state=ApprovalState.PENDING,
        binding=ApprovalBinding(
            proposal_version="1", proposal_id="draft-task-proposal:" + "0" * 64,
            handoff_digest="0" * 64, graph_digest="0" * 64, planning_result_digest="0" * 64,
            repository=_BOUND_REPO, base_branch="main", evaluated_repository_sha=_BOUND_SHA,
            evaluator_commit_sha=_BOUND_SHA, supplied_node_ids=("node:test",),
            cohort_summaries=(HandoffCohort(node_ids=("node:test",), classification="test", reason_codes=()),),
            issueplan_current_state_evidence_id="issueplan-current-state:" + "0" * 64,
            repository_state_evidence_id="0" * 64, repository_evidence_type="branch-head",
            tested_repository_sha=_BOUND_SHA, source_snapshot_fingerprint="0" * 64,
            scanner_result_fingerprint="0" * 64,
            implementation_contract_fingerprint=_BOUND_FINGERPRINT,
            allowed_files=("08_Tooling/agent-os-execution-service",),
            forbidden_paths=(".github/workflows",), required_tests=(),
        ),
        authorizer_id="Blummer92", decision_id="decision:test",
        decision_at="2026-08-21T12:00:00Z", expires_at=None, supersedes_approval_id=None,
        reason_codes=(),
    )
    caps = tuple(sorted((
        ExecutorCapability.CHECKOUT, ExecutorCapability.ISOLATED_WORKTREE,
        ExecutorCapability.DEPENDENCY_INSTALLATION, ExecutorCapability.PROCESS_EXECUTION,
        ExecutorCapability.TEST_EXECUTION, ExecutorCapability.GIT_RECONCILIATION,
    ), key=lambda item: item.value))
    route = ExecutorRouteDecision(
        schema_version=EXECUTOR_ROUTING_SCHEMA_VERSION, repository=_BOUND_REPO,
        issue_or_handoff_identity="issue:3333", requested_operation="pre-pr-developer-loop",
        required_capabilities=caps, governed_runner_capabilities=caps,
        governed_runner_available=True, external_fallback_available=False,
        external_fallback_explicitly_permitted=False,
        selected_route=ExecutorRoute.CHATGPT_GOVERNED_RUNNER,
        route_reasons=(ExecutorRouteReason.GOVERNED_RUNNER_CAPABLE,
                       ExecutorRouteReason.RUNTIME_CAPABILITY_REQUIRED),
        rejected_lower_cost_routes=(ExecutorRoute.CHATGPT_CONNECTOR_NATIVE,),
        execution_service_request_fingerprint_or_none=_bound_hid("execution-request", "request"),
        authorization_id_or_none=_bound_hid("authorization", "authorization"),
        environment_profile_id_or_none=_bound_hid("environment-profile", "profile"),
        environment_health_evidence_id_or_none=_bound_hid("environment-health", "health"),
        checkpoint_id_or_none=_bound_hid("agent-os.execution-checkpoint", "checkpoint"),
        resume_plan_id_or_none=_bound_hid("agent-os.execution-checkpoint.resume-plan", "resume"),
        workflow_runtime_identity_or_none=_bound_hid("workflow-runtime", "runtime"),
        operating_mode_decision_id_or_none="operating-mode:3333-probe",
        executable_lane_selection_id_or_none="lane-selection:3333-probe",
        validation_command_plan_id_or_none="command-plan:3333-probe",
        created_at="2026-10-14T11:00:00Z", expires_at="2026-10-14T13:00:00Z",
    )
    handoff = ExecutorHandoff(
        schema_version=EXECUTOR_ROUTING_SCHEMA_VERSION, route_decision_id=route.decision_id,
        destination_route=ExecutorRoute.CHATGPT_GOVERNED_RUNNER, repository=_BOUND_REPO,
        issue_or_handoff_identity="issue:3333", requested_operation="pre-pr-developer-loop",
        source_ref_or_none="refs/heads/agent/3333-probe", source_sha_or_none=_BOUND_SHA,
        required_capabilities=caps, allowed_paths=packet.allowed_files,
        forbidden_paths=packet.forbidden_paths,
        execution_service_request_fingerprint_or_none=route.execution_service_request_fingerprint_or_none,
        authorization_id_or_none=route.authorization_id_or_none,
        checkpoint_id_or_none=route.checkpoint_id_or_none,
        resume_plan_id_or_none=route.resume_plan_id_or_none,
        environment_profile_id_or_none=route.environment_profile_id_or_none,
        validation_command_plan_id_or_none=route.validation_command_plan_id_or_none,
        required_return_evidence=(), stop_conditions=(),
    )
    capsule = GovernedResumeRestartCapsule(
        schema_name="agent-os-governed-resume-restart-capsule", schema_version="1.1",
        handoff_id=handoff.handoff_id, candidate_packet=packet, approval_record=approval,
        required_environment_spec=spec, validation_bundle_json=json.dumps(payload, sort_keys=True),
        validation_plan_id=plan_id, validation_bundle_id=bundle.bundle_id,
        advisory_result_id=advisory.result_id, advisory_render_id="advisory-render:test",
        candidate_branch="agent/3333-probe", workspace_request_id="workspace-3333-probe",
        invalidation_events=(), created_at="2026-08-21T12:00:00Z",
        expires_at="2030-01-01T00:00:00Z", evaluated_at="2026-08-21T12:00:00Z",
    )
    descriptor = GovernedInvocationDescriptor(
        schema_name=INVOCATION_DESCRIPTOR_SCHEMA_NAME,
        schema_version=INVOCATION_DESCRIPTOR_SCHEMA_VERSION, repository=_BOUND_REPO,
        issue_number=3333, issue_or_handoff_identity="issue:3333",
        handoff_id=handoff.handoff_id, route_decision_id=route.decision_id,
        execution_service_request_fingerprint=route.execution_service_request_fingerprint_or_none,
        authorization_id=route.authorization_id_or_none,
        source_ref="refs/heads/agent/3333-probe", source_sha=_BOUND_SHA,
        checkpoint_id=route.checkpoint_id_or_none, resume_plan_id=route.resume_plan_id_or_none,
        environment_profile_id=route.environment_profile_id_or_none,
        environment_health_evidence_id=route.environment_health_evidence_id_or_none,
        required_environment_id=spec.required_environment_id,
        dependency_readiness_evidence_id=readiness.dependency_readiness_evidence_id,
        execution_surface_id="codespace:" + _BOUND_CODESPACE,
        workspace_identity="pilot-workspace:test",
        workflow_runtime_identity=route.workflow_runtime_identity_or_none,
        candidate_packet_id=packet.packet_id,
        runtime_configuration_fingerprint=_bound_hid("concrete-adapters", "configuration"),
        execution_id="execution-3333-probe", invocation_id=_BOUND_INVOCATION,
    )
    request = RuntimeExecutionRequest(
        schema_name=RUNTIME_EXECUTION_REQUEST_SCHEMA_NAME,
        schema_version=RUNTIME_EXECUTION_REQUEST_LEGACY_SCHEMA_VERSION,
        route_decision=route, handoff=handoff, invocation_descriptor=descriptor,
        restart_capsule=capsule, compute_control_projection=None,
    )

    store = tmp_path / "store"
    repo_root = tmp_path / "repo"
    workspace_parent = tmp_path / "ws"
    lease_dir = tmp_path / "leases"
    (store / "invocations").mkdir(parents=True)
    (repo_root / "scripts").mkdir(parents=True)
    (repo_root / "scripts" / "verify-repo-state.sh").write_text("#!/bin/sh\n")
    (repo_root / ".git").mkdir()
    workspace_parent.mkdir()
    lease_dir.mkdir()
    lease_dir.chmod(0o700)
    append_runtime_execution_request(store, request)
    append_dependency_readiness(store, readiness)
    monkeypatch.setenv("AGENT_OS_CHECKPOINT_STORE_ROOT", str(store))
    monkeypatch.setenv("GH_TOKEN", "test-token")
    configuration = load_production_host_configuration({
        "AGENT_OS_CHECKPOINT_STORE_ROOT": str(store),
        "AGENT_OS_REPOSITORY_ROOT": str(repo_root),
        "AGENT_OS_WORKSPACE_PARENT": str(workspace_parent),
        "AGENT_OS_LEASE_DIRECTORY": str(lease_dir),
        "CODESPACE_NAME": _BOUND_CODESPACE,
    })
    envelope = {
        "codespace_implementation_handoff_id_or_none": handoff.handoff_id,
        "codespace_implementation_sha_or_none": _BOUND_SHA,
    }
    return {
        "store": store, "repo_root": repo_root, "lease_dir": lease_dir,
        "configuration": configuration, "envelope": envelope, "handoff": handoff,
        "descriptor": descriptor, "request": request, "readiness": readiness,
        "environ": {
            "AGENT_OS_CHECKPOINT_STORE_ROOT": str(store),
            "AGENT_OS_REPOSITORY_ROOT": str(repo_root),
            "AGENT_OS_WORKSPACE_PARENT": str(workspace_parent),
            "AGENT_OS_LEASE_DIRECTORY": str(lease_dir),
            "CODESPACE_NAME": _BOUND_CODESPACE,
        },
    }


def _bound_event(bound: dict) -> dict:
    body = (
        "/agent-os codespace-implementation "
        f"{bound['handoff'].handoff_id} {_BOUND_SHA}"
    )
    return _event(body=body)


def test_bound_bootstrap_uses_real_evidence_not_unavailable_reader(tmp_path, monkeypatch) -> None:
    """The production default must bind canonical evidence, not an empty reader."""
    bound = _bound_store(tmp_path, monkeypatch)
    bootstrap = _build_bound_bootstrap(bound["envelope"], bound["configuration"])

    assert bootstrap.runtime_request.request_id == bound["request"].request_id
    assert bootstrap.runtime_request.invocation_descriptor.descriptor_id == bound["descriptor"].descriptor_id
    providers = bootstrap.admission_providers()
    assert providers.evaluated_at == bootstrap.evaluated_at
    assert providers.descriptor_loader(bound["handoff"].handoff_id).descriptor_id == bound["descriptor"].descriptor_id
    reader = bootstrap.sources.repository_reader
    dependency = reader.read_dependency_evidence(_BOUND_REPO, 3333)
    validation = reader.read_validation_evidence(_BOUND_REPO, 3333)
    assert str(dependency.status) == "EvidenceStatus.RESOLVED_CLEAR"
    assert str(validation.status) == "EvidenceStatus.RESOLVED_CLEAR"
    # No network: the host transport is token-constructed only, and the
    # reader/descriptor paths above never invoke its read method. Replace
    # it with a failing reader and prove those paths still work locally.
    transport = bootstrap.authorization_transport
    object.__setattr__(
        transport, "read_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network call")),
    )
    assert reader.read_dependency_evidence(_BOUND_REPO, 3333).status == dependency.status
    assert providers.descriptor_loader(bound["handoff"].handoff_id).descriptor_id == bound["descriptor"].descriptor_id


def test_bound_controller_persists_receipt_on_bound_path(tmp_path, monkeypatch) -> None:
    """Controller production path (no injected transports) reaches durable receipt."""
    bound = _bound_store(tmp_path, monkeypatch)
    path = _write_event(tmp_path, _bound_event(bound))
    calls: list = []

    def drive(envelope, bootstrap):
        # Test-only dispatch stub: it first proves the bound bootstrap, then
        # returns a completed receipt. Downstream pilot admission is proved
        # by the fixed-codespace-pilot suite, not by this stub.
        assert bootstrap.runtime_request.request_id == bound["request"].request_id
        reader = bootstrap.sources.repository_reader
        assert str(reader.read_dependency_evidence(_BOUND_REPO, 3333).status) == "EvidenceStatus.RESOLVED_CLEAR"
        calls.append(envelope)
        return _completed_receipt()

    result = run_gate2_fixed_pilot_controller(
        event_path=path,
        environ=bound["environ"],
        drive=drive,
        resolve_selection=lambda: _selection(_BOUND_CODESPACE),
    )
    assert result.status == "completed"
    assert len(calls) == 1
    assert Path(result.receipt_path).is_file()
    assert json.loads(Path(result.receipt_path).read_text())["status"] == "completed"


@pytest.mark.parametrize(
    "reason, mutate",
    [
        pytest.param("bound-evidence-unavailable", "missing-request", id="missing-handoff"),
        pytest.param("handoff-envelope-mismatch", "wrong-sha", id="sha-mismatch"),
        pytest.param("github-read-credential-unavailable", "no-token", id="missing-token"),
    ],
)
def test_bound_controller_fails_closed_before_dispatch(tmp_path, monkeypatch, reason, mutate) -> None:
    bound = _bound_store(tmp_path, monkeypatch)
    if mutate == "missing-request":
        for path in (bound["store"] / "runtime-execution-requests").glob("*.json"):
            path.unlink()
    elif mutate == "no-token":
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    event = _bound_event(bound)
    if mutate == "wrong-sha":
        # The mismatch must be in the admitted comment itself, not in a
        # local dict the controller never reads.
        event = _event(body=(
            "/agent-os codespace-implementation "
            f"{bound['handoff'].handoff_id} {'c' * 40}"
        ))
    path = _write_event(tmp_path, event)
    calls: list = []

    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=bound["environ"],
            drive=lambda envelope, bootstrap: calls.append(envelope) or _completed_receipt(),
            resolve_selection=lambda: _selection(_BOUND_CODESPACE),
        )
    assert excinfo.value.reason == reason
    assert calls == []
    receipts_dir = bound["store"] / "invocations" / "receipts"
    assert not receipts_dir.exists() or list(receipts_dir.iterdir()) == []


def test_bound_controller_refuses_wrong_codespace_and_active_lease(tmp_path, monkeypatch) -> None:
    """Pre-bootstrap host gates still block the bound path before any dispatch."""
    bound = _bound_store(tmp_path, monkeypatch)
    path = _write_event(tmp_path, _bound_event(bound))
    calls: list = []

    def drive(envelope, bootstrap):
        calls.append(envelope)
        return _completed_receipt()

    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path, environ=bound["environ"], drive=drive,
            resolve_selection=lambda: _selection("test-box"),
        )
    assert excinfo.value.reason == "host-surface-identity-mismatch"
    assert calls == []

    lease_file = bound["lease_dir"] / ("0" * 64 + ".active.json")
    lease_file.write_text("{}\n")
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path, environ=bound["environ"], drive=drive,
            resolve_selection=lambda: _selection(_BOUND_CODESPACE),
        )
    assert excinfo.value.reason == "conflicting-active-lease"
    assert calls == []


def test_bound_controller_refuses_unsupported_operation(tmp_path, monkeypatch) -> None:
    bound = _bound_store(tmp_path, monkeypatch)
    path = _write_event(tmp_path, _event(body="/agent-os discover"))
    calls: list = []
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path, environ=bound["environ"],
            drive=lambda envelope, bootstrap: calls.append(envelope) or _completed_receipt(),
            resolve_selection=lambda: _selection(_BOUND_CODESPACE),
        )
    assert excinfo.value.reason == "envelope-not-accepted"
    assert calls == []


def test_bound_bootstrap_fails_on_corrupted_readiness(tmp_path, monkeypatch) -> None:
    bound = _bound_store(tmp_path, monkeypatch)
    for path in (bound["store"] / "dependency-readiness").glob("*.json"):
        path.write_text("{not json")
    with pytest.raises(Gate2ControllerError) as excinfo:
        _build_bound_bootstrap(bound["envelope"], bound["configuration"])
    assert excinfo.value.reason == "bound-evidence-unavailable"


def test_bound_reader_reports_expired_readiness_as_unavailable(tmp_path, monkeypatch) -> None:
    """Stale dependency readiness must not become RESOLVED_CLEAR evidence."""
    bound = _bound_store(tmp_path, monkeypatch, readiness_expires="2026-01-02T00:00:00Z")
    bootstrap = _build_bound_bootstrap(bound["envelope"], bound["configuration"])
    dependency = bootstrap.sources.repository_reader.read_dependency_evidence(_BOUND_REPO, 3333)
    assert str(dependency.status) == "EvidenceStatus.UNAVAILABLE"
    assert any("not-current" in code for code in dependency.reason_codes)
