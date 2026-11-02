"""#3333 MCP connection repair: B02 sink, B10 replay/claim, receipt consumer.

All tests are offline: the pilot driver, the codespace selection
resolver, and the transport builder are injected fakes. No live
codespace execution, no network, and no credential use happens here.
"""

from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXECUTION_SERVICE_SRC = REPOSITORY_ROOT / "08_Tooling/agent-os-execution-service/src"
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
for _path in (REPOSITORY_ROOT, EXECUTION_SERVICE_SRC, SCHEDULER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest

import agent_os_execution_service.gate2_production_controller as ctrl
from agent_os_execution_service.gate2_production_controller import (
    Gate2ControllerError,
    _acquire_fixed_pilot_claim,
    _claim_digest,
    _find_completed_receipt,
    _validate_completed_dispatch_evidence,
    run_gate2_fixed_pilot_controller,
)
from agent_os_execution_service.production_host_bootstrap import (
    ProductionHostBootstrap,
)
from agent_os_execution_service.receipt_consumer import (
    ReceiptExpectation,
    verify_receipt_file,
)
from workflow_scheduler.governance.dev_validation_codespaces import (
    CodespaceSelection,
)

HANDOFF = "a" * 64
SHA = "b" * 40
OTHER_SHA = "c" * 40
BODY = f"/agent-os codespace-implementation executor-handoff:{HANDOFF} {SHA}"


def _event(body: str = BODY, *, actor: str = "Blummer92") -> dict:
    return {
        "action": "created",
        "repository": {"full_name": "Blummer92/agent-os"},
        "issue": {"number": 3333},
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


def _envelope() -> dict:
    return {
        "codespace_implementation_handoff_id_or_none": f"executor-handoff:{HANDOFF}",
        "codespace_implementation_sha_or_none": SHA,
        "repository": "Blummer92/agent-os",
        "issue_number": 3333,
    }


def _completed_receipt(**overrides) -> dict:
    receipt = {
        "schema_version": "1.0",
        "operation_id": "codespace-implementation-pilot-v1",
        "status": "completed",
        "reason_codes": ["fixed-head-probe-passed"],
        "repository": "Blummer92/agent-os",
        "issue_number": 3333,
        "handoff_id": f"executor-handoff:{HANDOFF}",
        "expected_sha": SHA,
        "request_id": "request-test-box-probe",
        "codespace_name": "test-box",
        "argv": ["git", "rev-parse", "HEAD"],
        "exit_status": 0,
        "stdout_tail": SHA + "\n",
        "stderr_tail": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "admission_id": "admission-test",
        "invocation_id": "invocation-test",
        "descriptor_id": "descriptor-test",
    }
    receipt.update(overrides)
    return receipt


def _expectation(**overrides) -> ReceiptExpectation:
    values = {
        "repository": "Blummer92/agent-os",
        "issue_number": 3333,
        "handoff_id": f"executor-handoff:{HANDOFF}",
        "expected_sha": SHA,
        "request_id": "request-test-box-probe",
        "codespace_name": "test-box",
        "admission_id": "admission-test",
        "invocation_id": "invocation-test",
        "descriptor_id": "descriptor-test",
    }
    values.update(overrides)
    return ReceiptExpectation(**values)


def _run_controller(tmp_path, host, *, drive, event=None):
    path = _write_event(tmp_path, event or _event())
    return run_gate2_fixed_pilot_controller(
        event_path=path,
        environ=host,
        drive=drive,
        resolve_selection=lambda: _selection(),
        build_transports=_transports,
    )


# --- B02: dispatch-evidence sink ------------------------------------------


def test_b02_completed_receipt_with_full_evidence_passes_sink():
    _validate_completed_dispatch_evidence(_envelope(), _completed_receipt(), "test-box")


@pytest.mark.parametrize(
    "field,value",
    [
        ("exit_status", True),  # bool is not an exact int zero
        ("exit_status", 1),
        ("exit_status", "0"),
        ("stdout_tail", OTHER_SHA + "\n"),
        ("stdout_tail", ""),
        ("stdout_truncated", True),
        ("stderr_truncated", True),
        ("argv", ["git", "log", "-1"]),
        ("argv", ("git", "rev-parse", "HEAD")),
        ("codespace_name", "other-box"),
        ("admission_id", ""),
        ("invocation_id", 42),
        ("descriptor_id", None),
    ],
)
def test_b02_completed_receipt_missing_any_evidence_is_rejected(field, value):
    receipt = _completed_receipt(**{field: value})
    with pytest.raises(Gate2ControllerError) as excinfo:
        _validate_completed_dispatch_evidence(_envelope(), receipt, "test-box")
    assert excinfo.value.reason == "receipt-dispatch-evidence-mismatch"


def test_b02_forged_completed_receipt_never_persists(tmp_path, host):
    calls: list = []

    def drive(envelope, bootstrap):
        calls.append(envelope)
        # A driver-only completion: right identity, no dispatch evidence.
        forged = _completed_receipt()
        del forged["exit_status"]
        forged["stdout_tail"] = "forged\n"
        return forged

    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=drive,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "receipt-dispatch-evidence-mismatch"
    assert calls
    receipts_dir = host["store"] / "invocations" / "receipts"
    assert not receipts_dir.exists() or list(receipts_dir.glob("*.json")) == []


def test_b02_blocked_receipt_without_evidence_still_persists_as_blocked(tmp_path, host):
    # The sink applies to completed receipts only; a blocked outcome must
    # not be rejected for lacking dispatch evidence.
    blocked = {
        "schema_version": "1.0",
        "operation_id": "codespace-implementation-pilot-v1",
        "status": "blocked",
        "reason_codes": ["canonical-invocation-not-admitted"],
        "repository": "Blummer92/agent-os",
        "issue_number": 3333,
        "handoff_id": f"executor-handoff:{HANDOFF}",
        "expected_sha": SHA,
    }
    result = _run_controller(tmp_path, host, drive=lambda e, bootstrap: blocked)
    assert result.status == "blocked"
    assert json.loads(Path(result.receipt_path).read_text())["status"] == "blocked"


# --- B10: replay scan, claim, crash ---------------------------------------


def test_b10_sequential_replay_returns_existing_receipt_without_redispatch(tmp_path, host):
    calls: list = []

    def drive(envelope, bootstrap):
        calls.append(envelope)
        return _completed_receipt()

    first = _run_controller(tmp_path, host, drive=drive)
    assert first.status == "completed"
    assert len(calls) == 1

    def never_drive(envelope, bootstrap):
        raise AssertionError("replay must not dispatch again")

    second = _run_controller(tmp_path, host, drive=never_drive)
    assert second.status == "completed"
    assert second.receipt_path == first.receipt_path
    assert len(calls) == 1


def test_b10_replay_matches_body_not_filename_across_seconds(tmp_path, host):
    # Rename the persisted receipt to a different timestamp filename: the
    # scan must still find it by body identity, proving filenames (which
    # embed evaluated_at) are not the dedup key.
    def drive(envelope, bootstrap):
        return _completed_receipt()

    first = _run_controller(tmp_path, host, drive=drive)
    old_path = Path(first.receipt_path)
    new_name = old_path.name[:-19] + "20260102T030405Z.json"
    new_path = old_path.with_name(new_name)
    old_path.rename(new_path)

    def never_drive(envelope, bootstrap):
        raise AssertionError("replay must not dispatch again")

    second = _run_controller(tmp_path, host, drive=never_drive)
    assert second.status == "completed"
    assert second.receipt_path == str(new_path)


def test_b10_blocked_prior_receipt_does_not_block_a_new_attempt(tmp_path, host):
    calls: list = []

    def drive_blocked(envelope, bootstrap):
        calls.append("blocked")
        blocked = _completed_receipt()
        blocked.update(status="blocked", reason_codes=["codespace-dispatch-not-completed"])
        return blocked

    first = _run_controller(tmp_path, host, drive=drive_blocked)
    assert first.status == "blocked"
    # Move the blocked receipt to another timestamp filename so the new
    # attempt's persist filename cannot collide in the same second; the
    # scan skips blocked receipts regardless of filename.
    old_path = Path(first.receipt_path)
    old_path.rename(old_path.with_name(old_path.name[:-19] + "20260102T030405Z.json"))

    def drive_completed(envelope, bootstrap):
        calls.append("completed")
        return _completed_receipt()

    second = _run_controller(tmp_path, host, drive=drive_completed)
    assert second.status == "completed"
    assert calls == ["blocked", "completed"]


def test_b10_malformed_receipt_store_fails_closed_without_dispatch(tmp_path, host):
    receipts_dir = host["store"] / "invocations" / "receipts"
    receipts_dir.mkdir(parents=True)
    (receipts_dir / "broken.json").write_text("{not json")

    def never_drive(envelope, bootstrap):
        raise AssertionError("malformed store must not dispatch")

    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=never_drive,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "receipt-store-unreadable"


def test_b10_crash_leaves_claim_and_next_run_is_blocked_not_redispatched(tmp_path, host):
    # Simulate a crash after claim acquisition but before persistence:
    # the claim file remains, no completed receipt exists.
    envelope = _envelope()
    claim_path = _acquire_fixed_pilot_claim(host["lease_dir"], envelope, "20261102T120000Z")
    assert claim_path.is_file()

    def never_drive(envelope, bootstrap):
        raise AssertionError("ambiguous claim must not dispatch")

    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=never_drive,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "fixed-pilot-claim-ambiguous"
    # The claim is NOT stolen or expired by the failed run.
    assert claim_path.is_file()


def test_b10_concurrent_duplicate_dispatches_only_once(tmp_path, host):
    calls: list = []
    lock = threading.Lock()

    def drive(envelope, bootstrap):
        with lock:
            calls.append(envelope)
        time.sleep(0.5)
        return _completed_receipt()

    path = _write_event(tmp_path, _event())
    barrier = threading.Barrier(2)
    outcomes: list = []

    def run_one():
        barrier.wait()
        try:
            result = run_gate2_fixed_pilot_controller(
                event_path=path,
                environ=host,
                drive=drive,
                resolve_selection=lambda: _selection(),
                build_transports=_transports,
            )
            outcomes.append(("completed", result.receipt_path))
        except Gate2ControllerError as exc:
            outcomes.append(("error", exc.reason))

    threads = [threading.Thread(target=run_one) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    # Exactly one dispatch happened, exactly one receipt file exists.
    assert len(calls) == 1
    receipts = list((host["store"] / "invocations" / "receipts").glob("*.json"))
    assert len(receipts) == 1
    # Either the loser was claim-blocked, or it returned the winner's
    # already-persisted receipt via the scan -- never a second dispatch.
    kinds = sorted(kind for kind, _ in outcomes)
    assert kinds in (["completed", "completed"], ["completed", "error"])
    if kinds == ["completed", "error"]:
        assert outcomes[[k for k, _ in outcomes].index("error")][1] == "fixed-pilot-claim-ambiguous"
    else:
        assert outcomes[0][1] == outcomes[1][1]


def test_b10_claim_is_released_after_verified_persist(tmp_path, host):
    def drive(envelope, bootstrap):
        return _completed_receipt()

    _run_controller(tmp_path, host, drive=drive)
    claim_files = list(host["lease_dir"].glob("gate2-fixed-pilot-claim-*.json"))
    assert claim_files == []


def test_scheduler_active_lease_guard_is_preserved(tmp_path, host):
    (host["lease_dir"] / ("f" * 64 + ".active.json")).write_text("{}")

    def never_drive(envelope, bootstrap):
        raise AssertionError("active lease must block dispatch")

    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=never_drive,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "conflicting-active-lease"


# --- Production receipt consumer ------------------------------------------


def _write_receipt_file(tmp_path: Path, receipt: dict) -> Path:
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt, sort_keys=True) + "\n")
    return path


def test_consumer_verifies_genuine_receipt_with_digest(tmp_path):
    path = _write_receipt_file(tmp_path, _completed_receipt())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result = verify_receipt_file(path, _expectation(digest_or_none=digest))
    assert result.verified is True
    assert result.reason == "receipt-verified"
    assert result.digest == digest


def test_consumer_rejects_wrong_codespace_sha_and_request_id(tmp_path):
    base = _completed_receipt()
    for field, expectation_override in [
        ("codespace_name", {"codespace_name": "other-box"}),
        ("expected_sha", {"expected_sha": OTHER_SHA}),
        ("request_id", {"request_id": "request:stale-other-invocation"}),
        ("descriptor_id", {"descriptor_id": "descriptor-other"}),
        ("argv", None),
    ]:
        if field == "argv":
            receipt = _completed_receipt(argv=["git", "log", "-1"])
            expectation = _expectation()
        else:
            receipt = base
            expectation = _expectation(**expectation_override)
        path = _write_receipt_file(tmp_path, receipt)
        result = verify_receipt_file(path, expectation)
        assert result.verified is False, field
        assert result.reason == f"receipt-verification-mismatch:{field}", field


def test_consumer_rejects_stale_or_altered_digest(tmp_path):
    path = _write_receipt_file(tmp_path, _completed_receipt())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    # Alter the bytes after the digest was recorded: same claims shape,
    # different content (stderr tail is not itself a checked field, so
    # only the digest catches this drift).
    altered = _completed_receipt(stderr_tail="drifted")
    path.write_text(json.dumps(altered, sort_keys=True) + "\n")
    result = verify_receipt_file(path, _expectation(digest_or_none=digest))
    assert result.verified is False
    assert result.reason == "receipt-verification-mismatch:digest"


def test_consumer_rejects_blocked_missing_and_malformed_receipts(tmp_path):
    blocked = _completed_receipt(status="blocked", reason_codes=["blocked-reason"])
    path = _write_receipt_file(tmp_path, blocked)
    assert verify_receipt_file(path, _expectation()).verified is False

    missing = tmp_path / "nope.json"
    result = verify_receipt_file(missing, _expectation())
    assert result.verified is False
    assert "unreadable" in result.reason

    malformed = tmp_path / "bad.json"
    malformed.write_text("{not json")
    result = verify_receipt_file(malformed, _expectation())
    assert result.verified is False
    assert "malformed" in result.reason


def test_consumer_does_not_verify_workflow_run_from_receipt_alone(tmp_path):
    # The receipt carries no workflow run id: a caller-supplied run id is
    # recorded as caller provenance, never proven from the receipt body.
    # This test pins that boundary -- body verification passes, and the
    # caller must separately bind the artifact record to the run it saw.
    path = _write_receipt_file(tmp_path, _completed_receipt())
    result = verify_receipt_file(
        path, _expectation(workflow_run_id_or_none="run-123", publisher_or_none="service-agent")
    )
    assert result.verified is True
    assert result.receipt is not None
    assert "workflow_run_id_or_none" not in result.receipt
    assert "publisher_or_none" not in result.receipt


# --- F1: post-dispatch claim lifecycle --------------------------------------
# Defect repaired here: the candidate released the dispatch claim in an
# unconditional ``finally:`` after driver entry, so every post-invoke
# failure (evidence mismatch, identity mismatch, persist failure, driver
# throw) deleted the ambiguous-outcome marker and a later run dispatched
# again. Every test below asserts ACTUAL driver invocation counts,
# claim-file existence/identity, receipt persistence + readback, and the
# exact failure reason -- not merely a nonzero exit or an error raise.
# Pre-existing tests missed F1 because they asserted the first run's
# reason and the absence of a receipt, but never the claim state or the
# second run's driver count.


def _claim_paths(host):
    return list(host["lease_dir"].glob("gate2-fixed-pilot-claim-*.json"))


def _receipt_paths(host):
    receipts_dir = host["store"] / "invocations" / "receipts"
    return sorted(receipts_dir.glob("*.json")) if receipts_dir.exists() else []


def test_f1_p0_predispatch_failure_releases_claim(tmp_path, host, monkeypatch):
    """P0: a failure demonstrably BEFORE driver entry releases the claim.

    The deepcopy of the envelope is the only step between claim
    acquisition and driver entry; forcing it to fail proves the
    pre-dispatch window: driver count 0, no claim left, and a later
    legitimate attempt may dispatch (count 1, completed).
    """

    class _BrokenCopy:
        @staticmethod
        def deepcopy(_obj):
            raise ValueError("deepcopy exploded before dispatch")

    monkeypatch.setattr(ctrl, "copy", _BrokenCopy)
    calls: list = []

    def drive(envelope, bootstrap):
        calls.append(envelope)
        return _completed_receipt()

    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=drive,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "unexpected-controller-error"
    assert calls == []
    assert _claim_paths(host) == []
    monkeypatch.undo()
    second = _run_controller(tmp_path, host, drive=drive)
    assert second.status == "completed"
    assert len(calls) == 1


def test_f1_p1_evidence_mismatch_retains_claim_and_blocks_retry(tmp_path, host):
    """P1: evidence mismatch after invoke keeps the claim; retry dispatches 0."""
    calls: list = []

    def failing_drive(envelope, bootstrap):
        calls.append(envelope)
        return _completed_receipt(stdout_tail="f" * 40 + "\n")

    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=failing_drive,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "receipt-dispatch-evidence-mismatch"
    assert len(calls) == 1
    claims = _claim_paths(host)
    assert len(claims) == 1
    assert claims[0].name == f"gate2-fixed-pilot-claim-{_claim_digest(_envelope())}.json"
    assert _receipt_paths(host) == []

    def good_drive(envelope, bootstrap):
        calls.append(envelope)
        return _completed_receipt()

    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=good_drive,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "fixed-pilot-claim-ambiguous"
    assert len(calls) == 1
    assert len(_claim_paths(host)) == 1
    assert _receipt_paths(host) == []


def test_f1_p2_identity_mismatch_retains_claim_and_blocks_retry(tmp_path, host):
    """P2: identity mismatch after invoke keeps the claim; retry dispatches 0."""
    calls: list = []

    def failing_drive(envelope, bootstrap):
        calls.append(envelope)
        return _completed_receipt(handoff_id="executor-handoff:" + "d" * 64)

    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=failing_drive,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "receipt-identity-mismatch"
    assert len(calls) == 1
    assert len(_claim_paths(host)) == 1
    assert _receipt_paths(host) == []

    def good_drive(envelope, bootstrap):
        calls.append(envelope)
        return _completed_receipt()

    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=good_drive,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "fixed-pilot-claim-ambiguous"
    assert len(calls) == 1


def test_f1_p3_persist_write_failure_retains_claim_and_blocks_retry(tmp_path, host, monkeypatch):
    """P3a: receipt write failure after invoke keeps the claim; retry dispatches 0."""

    def failing_persist(*args, **kwargs):
        raise Gate2ControllerError("receipt-write-failed", "injected")

    monkeypatch.setattr(ctrl, "_persist_receipt_atomically", failing_persist)
    calls: list = []

    def drive(envelope, bootstrap):
        calls.append(envelope)
        return _completed_receipt()

    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=drive,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "receipt-write-failed"
    assert len(calls) == 1
    assert len(_claim_paths(host)) == 1
    assert _receipt_paths(host) == []
    monkeypatch.undo()
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=drive,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "fixed-pilot-claim-ambiguous"
    assert len(calls) == 1


def test_f1_p3_persist_rename_failure_retains_claim_and_blocks_retry(tmp_path, host, monkeypatch):
    """P3b: receipt rename failure after invoke keeps the claim; retry dispatches 0."""
    import os

    real_replace = os.replace

    def failing_replace(src, dst):
        raise OSError("injected rename failure")

    monkeypatch.setattr(os, "replace", failing_replace)
    calls: list = []

    def drive(envelope, bootstrap):
        calls.append(envelope)
        return _completed_receipt()

    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=drive,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "receipt-write-failed"
    assert len(calls) == 1
    assert len(_claim_paths(host)) == 1
    assert _receipt_paths(host) == []
    monkeypatch.setattr(os, "replace", real_replace)
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=drive,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "fixed-pilot-claim-ambiguous"
    assert len(calls) == 1


def test_f1_p4_driver_throw_retains_claim_and_blocks_retry(tmp_path, host):
    """P4: driver throw after invoke begins keeps the claim; retry dispatches 0.

    The original candidate dispatched twice here (first 1, retry 1);
    the repaired run dispatches once total.
    """
    calls: list = []

    def throwing_drive(envelope, bootstrap):
        calls.append(envelope)
        raise RuntimeError("driver exploded after invoke began")

    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=throwing_drive,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "unexpected-controller-error"
    assert len(calls) == 1
    assert len(_claim_paths(host)) == 1
    assert _receipt_paths(host) == []

    def good_drive(envelope, bootstrap):
        calls.append(envelope)
        return _completed_receipt()

    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=good_drive,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "fixed-pilot-claim-ambiguous"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "bad_result,reason",
    [
        ([], "driver-returned-non-mapping"),
        ("not-a-mapping", "driver-returned-non-mapping"),
        ({"reason_codes": "not-a-list"}, "receipt-reason-codes-invalid"),
        ({"reason_codes": []}, "receipt-reason-codes-invalid"),
        ({"reason_codes": [42]}, "receipt-reason-codes-invalid"),
    ],
)
def test_f1_p5_wrong_type_driver_result_retains_claim(tmp_path, host, bad_result, reason):
    """P5: wrong-type driver result / reason_codes keeps the claim; retry dispatches 0."""
    calls: list = []

    def bad_drive(envelope, bootstrap):
        calls.append(envelope)
        return bad_result

    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=bad_drive,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == reason
    assert len(calls) == 1
    assert len(_claim_paths(host)) == 1

    def good_drive(envelope, bootstrap):
        calls.append(envelope)
        return _completed_receipt()

    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=good_drive,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "fixed-pilot-claim-ambiguous"
    assert len(calls) == 1


def test_f1_p6_success_then_retry_reuses_receipt_without_redispatch(tmp_path, host):
    """P6: after verified persist + release, a retry reuses the receipt, 0 dispatch."""
    calls: list = []

    def drive(envelope, bootstrap):
        calls.append(envelope)
        return _completed_receipt()

    first = _run_controller(tmp_path, host, drive=drive)
    assert first.status == "completed"
    assert len(calls) == 1
    assert _claim_paths(host) == []
    persisted = Path(first.receipt_path).read_text()

    def never_drive(envelope, bootstrap):
        raise AssertionError("replay must not dispatch again")

    second = _run_controller(tmp_path, host, drive=never_drive)
    assert second.status == "completed"
    assert second.receipt_path == first.receipt_path
    assert Path(second.receipt_path).read_text() == persisted
    assert len(calls) == 1


def test_f1_p7_crash_after_persist_before_release_resolves_via_receipt(tmp_path, host, monkeypatch):
    """P7: crash between persist and release leaves claim + receipt; retry needs 0 dispatch."""
    monkeypatch.setattr(ctrl, "_release_fixed_pilot_claim", lambda path: None)
    calls: list = []

    def drive(envelope, bootstrap):
        calls.append(envelope)
        return _completed_receipt()

    first = _run_controller(tmp_path, host, drive=drive)
    assert first.status == "completed"
    assert len(calls) == 1
    # Simulated crash: receipt durable, claim never released.
    assert len(_claim_paths(host)) == 1
    assert len(_receipt_paths(host)) == 1
    monkeypatch.undo()

    def never_drive(envelope, bootstrap):
        raise AssertionError("replay must not dispatch again")

    second = _run_controller(tmp_path, host, drive=never_drive)
    assert second.status == "completed"
    assert second.receipt_path == first.receipt_path
    assert len(calls) == 1


def test_f1_p8_crash_after_release_before_reply_reuses_receipt(tmp_path, host):
    """P8: crash after release, before the caller sees the reply: receipt prevents redispatch."""
    calls: list = []

    def drive(envelope, bootstrap):
        calls.append(envelope)
        return _completed_receipt()

    first = _run_controller(tmp_path, host, drive=drive)
    assert first.status == "completed"
    assert len(calls) == 1
    # Caller reply lost, but the claim was released and the receipt is durable.
    assert _claim_paths(host) == []
    assert len(_receipt_paths(host)) == 1

    def never_drive(envelope, bootstrap):
        raise AssertionError("replay must not dispatch again")

    second = _run_controller(tmp_path, host, drive=never_drive)
    assert second.status == "completed"
    assert second.receipt_path == first.receipt_path
    assert len(calls) == 1


def test_f1_p9_contenders_after_failed_winner_all_blocked(tmp_path, host):
    """P9 (failure branch): after a failed winner's claim is retained, contenders dispatch 0."""
    calls: list = []

    def failing_drive(envelope, bootstrap):
        calls.append(envelope)
        return _completed_receipt(stdout_tail="f" * 40 + "\n")

    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError):
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=failing_drive,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert len(calls) == 1

    def good_drive(envelope, bootstrap):
        calls.append(envelope)
        return _completed_receipt()

    for _ in range(2):
        with pytest.raises(Gate2ControllerError) as excinfo:
            run_gate2_fixed_pilot_controller(
                event_path=path,
                environ=host,
                drive=good_drive,
                resolve_selection=lambda: _selection(),
                build_transports=_transports,
            )
        assert excinfo.value.reason == "fixed-pilot-claim-ambiguous"
    assert len(calls) == 1


def test_f1_p10_scan_conflict_same_identity_changed_issue(tmp_path, host):
    """P10 (scan level): completed receipt, same handoff+SHA, different issue -> conflict, 0 dispatch.

    Admission enforces issue 3333 end to end, so the changed-issue case is
    exercised at the scan seam; the scan must fail closed rather than
    dispatch under a reused identity.
    """
    receipts_dir = host["store"] / "invocations" / "receipts"
    receipts_dir.mkdir(parents=True)
    placed = receipts_dir / "receipt-x.json"
    placed.write_text(json.dumps(_completed_receipt(), sort_keys=True) + "\n")
    envelope = _envelope()
    envelope["issue_number"] = 9999
    with pytest.raises(Gate2ControllerError) as excinfo:
        _find_completed_receipt(receipts_dir, envelope, "test-box")
    assert excinfo.value.reason == "receipt-identity-conflict"


def test_f1_p10_controller_wrong_codespace_rejects_without_dispatch(tmp_path, host):
    """P10 (controller level): completed receipt + different selected codespace -> no dispatch."""
    calls: list = []

    def drive(envelope, bootstrap):
        calls.append(envelope)
        return _completed_receipt()

    first = _run_controller(tmp_path, host, drive=drive)
    assert first.status == "completed"
    assert len(calls) == 1

    def never_drive(envelope, bootstrap):
        raise AssertionError("wrong-codespace replay must not dispatch")

    # A consistent other-box surface (env + selection agree) whose stored
    # receipt still claims test-box: the scan matches identity fields,
    # then the sink rejects the codespace mismatch before any dispatch.
    other_host = dict(host)
    other_host["CODESPACE_NAME"] = "other-box"
    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=other_host,
            drive=never_drive,
            resolve_selection=lambda: _selection("other-box"),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "receipt-dispatch-evidence-mismatch"
    assert len(calls) == 1


def test_f1_p11_malformed_claim_fails_closed_without_cleanup(tmp_path, host):
    """P11: malformed / conflicting claim files fail closed, are never cleaned up, 0 dispatch."""
    envelope = _envelope()
    claim_name = f"gate2-fixed-pilot-claim-{_claim_digest(envelope)}.json"
    for content in ("{not json", json.dumps({"handoff_id": "executor-handoff:" + "e" * 64})):

        def never_drive(envelope, bootstrap):
            raise AssertionError("malformed claim must not dispatch")

        claim_path = host["lease_dir"] / claim_name
        claim_path.write_text(content)
        path = _write_event(tmp_path, _event())
        with pytest.raises(Gate2ControllerError) as excinfo:
            run_gate2_fixed_pilot_controller(
                event_path=path,
                environ=host,
                drive=never_drive,
                resolve_selection=lambda: _selection(),
                build_transports=_transports,
            )
        assert excinfo.value.reason == "fixed-pilot-claim-ambiguous"
        assert claim_path.read_text() == content
        claim_path.unlink()


def test_f1_p11_malformed_receipt_fails_closed_without_cleanup(tmp_path, host):
    """P11: malformed receipt store fails closed, file untouched, 0 dispatch."""
    receipts_dir = host["store"] / "invocations" / "receipts"
    receipts_dir.mkdir(parents=True)
    broken = receipts_dir / "broken.json"
    broken.write_text("{not json")

    def never_drive(envelope, bootstrap):
        raise AssertionError("malformed store must not dispatch")

    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=never_drive,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "receipt-store-unreadable"
    assert broken.read_text() == "{not json"


# --- QF-1: post-acquisition re-scan ---------------------------------------
# QA proved a stalled loser could pass the pre-scan, pause, then obtain
# a now-free claim after the winner completed and dispatch a second
# time: the pre-scan ran before claim acquisition and was never re-run
# under the held claim. The tests below force that exact adverse order
# with thread events (no sleeps) and assert one dispatch, one receipt,
# and identical receipt path/content for both callers.


def test_qf1_stalled_loser_rescans_after_claim_and_replays_without_redispatch(
    tmp_path, host, monkeypatch
):
    """QF-1/R1: loser stalled between scan and acquisition replays the winner's receipt.

    Deterministic adverse order: the loser scans empty, then blocks in
    gated acquisition; the winner runs to completion (persists +
    releases); the loser resumes, acquires, rescans under the held
    claim, and returns the winner's receipt. Loser outcomes are
    ambiguous before persistence OR same-path replay after it -- this
    test proves the replay branch: two callers, one dispatch, one
    receipt, identical path and content, no leftover claim.
    """
    calls: list = []
    lock = threading.Lock()

    def drive(envelope, bootstrap):
        with lock:
            calls.append(envelope)
        return _completed_receipt()

    state = threading.local()
    loser_scanned = threading.Event()
    winner_done = threading.Event()
    real_scan = ctrl._find_completed_receipt
    real_acquire = ctrl._acquire_fixed_pilot_claim

    def gated_scan(receipts_dir, envelope, codespace_name):
        found = real_scan(receipts_dir, envelope, codespace_name)
        if getattr(state, "is_loser", False):
            loser_scanned.set()
        return found

    def gated_acquire(lease_directory, envelope, evaluated_at):
        if getattr(state, "is_loser", False):
            assert winner_done.wait(timeout=30)
        return real_acquire(lease_directory, envelope, evaluated_at)

    monkeypatch.setattr(ctrl, "_find_completed_receipt", gated_scan)
    monkeypatch.setattr(ctrl, "_acquire_fixed_pilot_claim", gated_acquire)

    path = _write_event(tmp_path, _event())
    results: dict = {}

    def run_loser():
        state.is_loser = True
        try:
            results["loser"] = run_gate2_fixed_pilot_controller(
                event_path=path,
                environ=host,
                drive=drive,
                resolve_selection=lambda: _selection(),
                build_transports=_transports,
            )
        except Exception as exc:  # noqa: BLE001 - captured for assertion
            results["loser"] = exc

    loser = threading.Thread(target=run_loser)
    loser.start()
    assert loser_scanned.wait(timeout=30)
    winner = run_gate2_fixed_pilot_controller(
        event_path=path,
        environ=host,
        drive=drive,
        resolve_selection=lambda: _selection(),
        build_transports=_transports,
    )
    assert winner.status == "completed"
    winner_done.set()
    loser.join(timeout=30)
    assert not loser.is_alive()
    loser_result = results["loser"]
    assert not isinstance(loser_result, Exception)
    assert loser_result.status == "completed"
    assert loser_result.receipt_path == winner.receipt_path
    assert Path(loser_result.receipt_path).read_text() == Path(
        winner.receipt_path
    ).read_text()
    assert loser_result.receipt == winner.receipt
    assert len(calls) == 1
    assert len(_receipt_paths(host)) == 1
    assert _claim_paths(host) == []


def test_qf1_rescan_store_error_preserves_claim_without_dispatch(
    tmp_path, host, monkeypatch
):
    """QF-1/R4: a re-scan store error under a held claim fails closed, claim preserved.

    P11 covers the pre-scan path, where no claim is held. This covers
    the re-scan path, which only the QF-1 correction reaches: the
    second scan call fails, so the run must not dispatch, must not
    erase evidence, and must NOT silently release the claim -- the
    claim remains as the ambiguous-outcome marker.
    """
    calls: list = []
    scan_calls = {"n": 0}
    real_scan = ctrl._find_completed_receipt

    def failing_rescan(receipts_dir, envelope, codespace_name):
        scan_calls["n"] += 1
        if scan_calls["n"] == 2:
            raise Gate2ControllerError("receipt-store-unreadable")
        return real_scan(receipts_dir, envelope, codespace_name)

    monkeypatch.setattr(ctrl, "_find_completed_receipt", failing_rescan)

    def never_drive(envelope, bootstrap):
        raise AssertionError("re-scan error must not dispatch")

    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=never_drive,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "receipt-store-unreadable"
    assert scan_calls["n"] == 2
    assert len(calls) == 0
    assert len(_claim_paths(host)) == 1
    assert _receipt_paths(host) == []
