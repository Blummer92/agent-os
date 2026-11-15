from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

# The fixed-pilot producer lives at the repository root (scripts/), not
# under the workflow-scheduler source tree. Insert the root so the P1
# positive fixture is built from the real producer, not a hand-written
# copy of its output shape.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from workflow_scheduler.governance.dev_validation_gate import (
    _RECEIPT_KEYS,
    evaluate_dev_validation_gate,
    evaluate_fixed_pilot_gate,
    main,
)

SHA = "a" * 40
BRANCH = "agent/1552-fast-deterministic-preflight"
VALIDATION_ID = "remote-validation-suite"


def transport(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "status": "accepted",
        "reason": "accepted-dev-validation-envelope",
        "repository": "Blummer92/agent-os",
        "issue_number": 1552,
        "dev_validation_branch_or_none": BRANCH,
        "dev_validation_sha_or_none": SHA,
        "dev_validation_id_or_none": VALIDATION_ID,
    }
    payload.update(overrides)
    return payload


def evidence(status: str = "success", **overrides: object) -> dict[str, object]:
    reason = "validation-passed" if status == "success" else (
        "validation-timeout" if status == "timeout" else "validation-failed"
    )
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "status": status,
        "reason_codes": [reason],
        "repository": "Blummer92/agent-os",
        "issue_number": 1552,
        "branch": BRANCH,
        "tested_sha": SHA,
        "validation_id": VALIDATION_ID,
        "request_id": "dev-validation:test",
        "exit_code": 0 if status == "success" else 1,
        "cleanup_complete": True,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "publication_invoked": False,
        "merge_authorized": False,
    }
    payload.update(overrides)
    return {"dev_validation": payload}


def test_success_is_the_only_passing_dev_validation_state() -> None:
    decision = evaluate_dev_validation_gate(transport(), evidence())
    assert decision.applies is True
    assert decision.passed is True
    assert decision.status == "success"
    assert decision.tested_sha == SHA
    assert decision.validation_id == VALIDATION_ID


@pytest.mark.parametrize("status", ["failure", "timeout", "needs-decision"])
def test_non_success_states_fail_closed(status: str) -> None:
    result = evidence(status, exit_code=None if status != "failure" else 2)
    decision = evaluate_dev_validation_gate(transport(), result)
    assert decision.applies is True
    assert decision.passed is False
    assert decision.status == status
    assert decision.reason == "dev-validation-not-success"


def test_collection_failure_cannot_be_mistaken_for_transport_success() -> None:
    decision = evaluate_dev_validation_gate(
        transport(),
        evidence("failure", exit_code=2, reason_codes=["validation-failed"]),
    )
    assert decision.passed is False
    assert decision.exit_code == 2
    assert decision.tested_sha == SHA


def test_ordinary_test_failure_cannot_be_mistaken_for_transport_success() -> None:
    decision = evaluate_dev_validation_gate(
        transport(),
        evidence("failure", exit_code=1, reason_codes=["validation-failed"]),
    )
    assert decision.passed is False
    assert decision.exit_code == 1


def test_infrastructure_failure_remains_distinct_from_test_failure() -> None:
    decision = evaluate_dev_validation_gate(
        transport(),
        evidence(
            "needs-decision",
            exit_code=None,
            reason_codes=["dev-validation-ssh-failed"],
            cleanup_complete=False,
        ),
    )
    assert decision.passed is False
    assert decision.status == "needs-decision"
    assert decision.exit_code is None


@pytest.mark.parametrize("result", [None, {}, {"dev_validation": "bad"}])
def test_missing_or_malformed_result_fails_closed(result: object) -> None:
    decision = evaluate_dev_validation_gate(transport(), result)  # type: ignore[arg-type]
    assert decision.applies is True
    assert decision.passed is False
    assert decision.reason == "dev-validation-result-missing-or-malformed"


def test_exact_sha_and_validation_identity_must_match_transport() -> None:
    wrong_sha = evaluate_dev_validation_gate(
        transport(), evidence(tested_sha="b" * 40)
    )
    wrong_id = evaluate_dev_validation_gate(
        transport(), evidence(validation_id="other-validation")
    )
    wrong_branch = evaluate_dev_validation_gate(
        transport(), evidence(branch="agent/other")
    )
    assert wrong_sha.reason == "dev-validation-identity-mismatch"
    assert wrong_id.reason == "dev-validation-identity-mismatch"
    assert wrong_branch.reason == "dev-validation-identity-mismatch"


def test_success_with_nonzero_exit_code_fails_closed() -> None:
    decision = evaluate_dev_validation_gate(transport(), evidence(exit_code=1))
    assert decision.passed is False
    assert decision.reason == "dev-validation-success-exit-code-invalid"


def test_success_requires_completed_cleanup() -> None:
    decision = evaluate_dev_validation_gate(
        transport(), evidence(cleanup_complete=False)
    )
    assert decision.passed is False
    assert decision.reason == "dev-validation-success-cleanup-incomplete"


def test_non_dev_validation_ingress_is_not_affected() -> None:
    decision = evaluate_dev_validation_gate(
        transport(reason="accepted-discovery-envelope"), None
    )
    assert decision.applies is False
    assert decision.passed is True
    assert decision.status == "not-applicable"


def test_cli_returns_nonzero_for_failed_dev_validation(tmp_path) -> None:
    transport_path = tmp_path / "transport.json"
    result_path = tmp_path / "result.json"
    transport_path.write_text(json.dumps(transport()), encoding="utf-8")
    result_path.write_text(json.dumps(evidence("failure", exit_code=1)), encoding="utf-8")
    assert main(["--transport", str(transport_path), "--result", str(result_path)]) == 1


def test_cli_returns_zero_for_successful_dev_validation(tmp_path) -> None:
    transport_path = tmp_path / "transport.json"
    result_path = tmp_path / "result.json"
    transport_path.write_text(json.dumps(transport()), encoding="utf-8")
    result_path.write_text(json.dumps(evidence()), encoding="utf-8")
    assert main(["--transport", str(transport_path), "--result", str(result_path)]) == 0


def test_cli_is_noop_for_non_dev_validation_ingress(tmp_path) -> None:
    transport_path = tmp_path / "transport.json"
    transport_path.write_text(
        json.dumps(transport(reason="accepted-discovery-envelope")),
        encoding="utf-8",
    )
    assert main(
        ["--transport", str(transport_path), "--result", str(tmp_path / "missing.json")]
    ) == 0


# --- Fixed #3333 pilot acceptance gate (D1) --------------------------------
# P1 builds the positive fixture from the real fixed-pilot producer:
# _receipt() supplies the 27-key template and the host-path assignments
# below mirror consume_fixed_codespace_pilot verbatim. N1 mutates one
# field at a time; every mutation must fail with its own reason.

FIXED_SHA = "7f293b5907db42d30da6a42089f2f9ef8e23e511"
FIXED_HANDOFF = "executor-handoff:" + "ab" * 32
FIXED_CODESPACE = "d1-test-codespace-abc123"
FIXED_EVENT_BODY = b'{"action": "created", "comment": {"body": "fixed"}}'
FIXED_EVENT_SHA = hashlib.sha256(FIXED_EVENT_BODY).hexdigest()


def fixed_transport(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "status": "accepted",
        "reason": "accepted-codespace-implementation-envelope",
        "repository": "Blummer92/agent-os",
        "issue_number": 3333,
        "comment_id": 101,
        "actor": "Blummer92",
        "handoff_id_or_none": None,
        "logical_trigger_id_or_none": "fixed-trigger:test",
        "run_attempt": 1,
        "codespace_implementation_handoff_id_or_none": FIXED_HANDOFF,
        "codespace_implementation_sha_or_none": FIXED_SHA,
    }
    payload.update(overrides)
    return payload


def fixed_diagnostic(**overrides: object) -> dict[str, object]:
    diagnostic: dict[str, object] = {
        "status": "needs-decision",
        "reason_codes": ["canonical-admission-provider-unavailable"],
    }
    diagnostic.update(overrides)
    return {"codespace_implementation": diagnostic}


def fixed_reference(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "operation_id": "codespace-implementation-pilot-v1",
        "repository": "Blummer92/agent-os",
        "issue_number": 3333,
        "receipt_path": (
            "/store/invocations/receipts/fixed-head-probe-"
            + FIXED_HANDOFF.removeprefix("executor-handoff:")
            + "-" + FIXED_SHA + "-20261104T180002Z.json"
        ),
        "handoff_id": FIXED_HANDOFF,
        "expected_sha": FIXED_SHA,
        "status": "completed",
        "reason_codes": ["fixed-head-probe-passed"],
        "consumer": "github-service-agent-governed-publication-path",
    }
    payload.update(overrides)
    return payload


def fixed_receipt(**overrides: object) -> dict[str, object]:
    """Completed receipt from the real producer plus host-path assignments."""
    from scripts.agent_os_execution_interface.fixed_codespace_pilot import _receipt

    template = _receipt("blocked", "codespace-dispatch-not-completed", fixed_transport())
    assert len(template) == 27, "producer template must stay 27 keys"
    receipt: dict[str, object] = dict(template)
    # Host-path assignments, verbatim from consume_fixed_codespace_pilot.
    receipt["codespace_name"] = FIXED_CODESPACE
    receipt["exit_status"] = 0
    receipt["stdout_tail"] = FIXED_SHA + "\n"
    receipt["stderr_tail"] = ""
    receipt["argv"] = ["git", "rev-parse", "HEAD"]
    receipt["stdout_truncated"] = False
    receipt["stderr_truncated"] = False
    receipt["started_at"] = "2026-11-04T18:00:00Z"
    receipt["ended_at"] = "2026-11-04T18:00:02Z"
    receipt["duration_ms"] = 2000
    receipt["request_id"] = "transport:" + "cd" * 32
    receipt["admission_id"] = "admission:" + "01" * 16
    receipt["invocation_id"] = "invocation:" + "02" * 16
    receipt["descriptor_id"] = "descriptor:" + "03" * 16
    receipt["side_effects_performed"] = True
    receipt["status"] = "completed"
    receipt["reason_codes"] = ["fixed-head-probe-passed"]
    assert len(receipt) == 30, "completed receipt must be 30 keys"
    assert set(receipt.keys()) == _RECEIPT_KEYS, "producer/consumer key sets must match"
    receipt.update(overrides)
    return receipt


def fixed_transfer(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "run_id": 9000000001,
        "attempt": 1,
        "selected": FIXED_CODESPACE,
        "remote_dir": "/tmp/agent-os-gate2-9000000001-1",
        "bindings_present": True,
        "main_head_matches": True,
        "remote_head_matches": True,
        "identity_present_equal": True,
        "probe": "VALID",
        "transfer_ok": True,
        "event_sha256": FIXED_EVENT_SHA,
        "event_bytes": len(FIXED_EVENT_BODY),
        "staging_sha256": FIXED_EVENT_SHA,
        "final_sha256": FIXED_EVENT_SHA,
        "inode_equal": True,
        "run_rc": 0,
        "receipt_returned": True,
        "ready": True,
        "reason_codes": [],
    }
    payload.update(overrides)
    return payload


def fixed_gate_inputs(**overrides: object) -> dict[str, object]:
    inputs: dict[str, object] = {
        "transport": fixed_transport(),
        "result": fixed_diagnostic(),
        "reference": fixed_reference(),
        "process_stderr": "",
        "receipt": fixed_receipt(),
        "transfer": fixed_transfer(),
        "event_bytes": len(FIXED_EVENT_BODY),
        "event_sha256": FIXED_EVENT_SHA,
    }
    inputs.update(overrides)
    return inputs


def test_fixed_pilot_positive_passes_from_real_producer() -> None:
    """P1: the genuine producer-backed completion passes, event verified."""
    decision = evaluate_fixed_pilot_gate(**fixed_gate_inputs())  # type: ignore[arg-type]
    assert decision.passed is True
    assert decision.status == "pass"
    assert decision.reason_codes == ("fixed-pilot-gate-passed",)
    assert decision.event_verified is True
    assert decision.codespace_name == FIXED_CODESPACE
    assert decision.handoff_id == FIXED_HANDOFF
    assert decision.expected_sha == FIXED_SHA


@pytest.mark.parametrize(
    "mutate,reason",
    [
        (lambda r: r.pop("descriptor_id"), "fixed-pilot-receipt-schema-mismatch"),
        (lambda r: r.update(forged_field="x"), "fixed-pilot-receipt-schema-mismatch"),
        (lambda r: r.update(exit_status=True), "fixed-pilot-receipt-evidence-mismatch"),
        (lambda r: r.update(issue_number="3333"), "fixed-pilot-receipt-identity-mismatch"),
        (
            lambda r: r.update(handoff_id="executor-handoff:" + "ff" * 32),
            "fixed-pilot-receipt-identity-mismatch",
        ),
        (
            lambda r: r.update(expected_sha="0" * 40, stdout_tail="0" * 40 + "\n"),
            "fixed-pilot-receipt-identity-mismatch",
        ),
        (lambda r: r.update(codespace_name="other-codespace"), "fixed-pilot-receipt-identity-mismatch"),
        (lambda r: r.update(logical_trigger_id="wrong-trigger"), "fixed-pilot-receipt-identity-mismatch"),
        (lambda r: r.update(stderr_tail="warning: x"), "fixed-pilot-receipt-evidence-mismatch"),
        (lambda r: r.update(side_effects_performed=False), "fixed-pilot-receipt-evidence-mismatch"),
        (lambda r: r.update(execution_authorized=True), "fixed-pilot-receipt-evidence-mismatch"),
        (lambda r: r.update(duration_ms=True), "fixed-pilot-receipt-evidence-mismatch"),
        (lambda r: r.update(ended_at="2026-11-04T17:59:59Z"), "fixed-pilot-receipt-evidence-mismatch"),
        (lambda r: r.update(argv=["git", "rev-parse", "HEAD", "--extra"]), "fixed-pilot-receipt-evidence-mismatch"),
    ],
)
def test_fixed_pilot_receipt_mutations_fail(mutate, reason) -> None:
    """N1: every single-field receipt forgery fails with its own reason."""
    receipt = fixed_receipt()
    mutate(receipt)
    decision = evaluate_fixed_pilot_gate(**fixed_gate_inputs(receipt=receipt))  # type: ignore[arg-type]
    assert decision.passed is False
    assert decision.reason_codes == (reason,)


def test_fixed_pilot_reference_operation_field_fails() -> None:
    """N1: the v2 'operation' field (not 'operation_id') is a schema failure."""
    reference = fixed_reference()
    reference["operation"] = reference.pop("operation_id")
    decision = evaluate_fixed_pilot_gate(**fixed_gate_inputs(reference=reference))  # type: ignore[arg-type]
    assert decision.passed is False
    assert decision.reason_codes == ("fixed-pilot-reference-schema-mismatch",)


def test_fixed_pilot_reference_only_and_receipt_absent_fail() -> None:
    """N1: a reference alone, or neither receipt nor reference, never passes."""
    decision = evaluate_fixed_pilot_gate(**fixed_gate_inputs(receipt=None))  # type: ignore[arg-type]
    assert decision.passed is False
    assert decision.reason_codes == ("fixed-pilot-receipt-missing-or-malformed",)
    decision = evaluate_fixed_pilot_gate(**fixed_gate_inputs(receipt=None, reference=None))  # type: ignore[arg-type]
    assert decision.passed is False
    assert decision.reason_codes == ("fixed-pilot-reference-missing-or-malformed",)


def test_fixed_pilot_diagnostic_alone_never_passes() -> None:
    """N1: the provider-less diagnostic, even claiming completed, is not execution."""
    transfer = fixed_transfer(receipt_returned=False)
    decision = evaluate_fixed_pilot_gate(
        **fixed_gate_inputs(transfer=transfer, reference=None, receipt=None)  # type: ignore[arg-type]
    )
    assert decision.passed is False
    assert decision.reason_codes == ("fixed-pilot-receipt-not-returned",)
    diagnostic = fixed_diagnostic(status="completed", reason_codes=["fixed-head-probe-passed"])
    decision = evaluate_fixed_pilot_gate(
        **fixed_gate_inputs(result=diagnostic, transfer=transfer, reference=None, receipt=None)  # type: ignore[arg-type]
    )
    assert decision.passed is False


@pytest.mark.parametrize(
    "transport_mutate,reason",
    [
        (lambda t: t.update(actor="someone-else"), "fixed-pilot-transport-actor-mismatch"),
        (lambda t: t.update(run_attempt=2), "fixed-pilot-transport-attempt-mismatch"),
        (lambda t: t.update(repository="Other/repo"), "fixed-pilot-transport-identity-mismatch"),
        (lambda t: t.update(codespace_implementation_sha_or_none="zz"), "fixed-pilot-transport-identity-mismatch"),
        (lambda t: t.update(reason="accepted-discovery-envelope"), "fixed-pilot-transport-reason-mismatch"),
        (lambda t: t.update(status="blocked"), "fixed-pilot-transport-not-accepted"),
    ],
)
def test_fixed_pilot_transport_mutations_fail(transport_mutate, reason) -> None:
    """N1: wrong actor, SHA, repository, attempt, or reason cannot dispatch."""
    transport = fixed_transport()
    transport_mutate(transport)
    decision = evaluate_fixed_pilot_gate(**fixed_gate_inputs(transport=transport))  # type: ignore[arg-type]
    assert decision.passed is False
    assert decision.reason_codes == (reason,)


def test_fixed_pilot_gate2_stderr_reason_is_preserved() -> None:
    """N7: a Gate 2 failure reason survives; it is not masked by missing evidence."""
    transfer = fixed_transfer(run_rc=1, receipt_returned=False)
    stderr = json.dumps(
        {
            "schema_version": "1.0",
            "operation_id": "codespace-implementation-pilot-v1",
            "status": "failed",
            "reason_codes": ["host-configuration-invalid"],
        }
    )
    decision = evaluate_fixed_pilot_gate(
        **fixed_gate_inputs(transfer=transfer, process_stderr=stderr, reference=None, receipt=None)  # type: ignore[arg-type]
    )
    assert decision.passed is False
    assert decision.reason_codes == ("host-configuration-invalid",)
    assert decision.failed_check == "process_stderr"


def test_fixed_pilot_gate2_stderr_unparseable_and_nonempty_fail() -> None:
    """N7: unparseable Gate 2 stderr, and stderr on a zero exit, both fail."""
    transfer = fixed_transfer(run_rc=1, receipt_returned=False)
    decision = evaluate_fixed_pilot_gate(
        **fixed_gate_inputs(transfer=transfer, process_stderr="not json", reference=None, receipt=None)  # type: ignore[arg-type]
    )
    assert decision.reason_codes == ("fixed-pilot-process-stderr-unparseable",)
    decision = evaluate_fixed_pilot_gate(**fixed_gate_inputs(process_stderr="unexpected output"))  # type: ignore[arg-type]
    assert decision.reason_codes == ("fixed-pilot-process-stderr-nonempty",)
    decision = evaluate_fixed_pilot_gate(**fixed_gate_inputs(process_stderr=None))  # type: ignore[arg-type]
    assert decision.reason_codes == ("fixed-pilot-process-stderr-missing",)


@pytest.mark.parametrize("stderr", ["", "not json", None])
def test_fixed_pilot_run_timeout_is_uncertain_not_failed(stderr: object) -> None:
    """D1 repair: rc 124 (300 s timeout) is outcome-uncertain, never a clean
    failure. The remote controller may have finished or may still hold its
    O_EXCL claim, and a killed controller's stderr cannot settle that — so
    the gate reports `run-timeout-outcome-uncertain` whatever stderr holds,
    even a well-formed Gate 2 failure payload (which must not be mistaken
    for a definitive failure here). FAIL, claim/receipt preserved, no retry."""
    transfer = fixed_transfer(run_rc=124, receipt_returned=False)
    decision = evaluate_fixed_pilot_gate(
        **fixed_gate_inputs(transfer=transfer, process_stderr=stderr, reference=None, receipt=None)  # type: ignore[arg-type]
    )
    assert decision.passed is False
    assert decision.status == "fail"
    assert decision.reason_codes == ("run-timeout-outcome-uncertain",)
    assert decision.failed_check == "transfer.run_rc"
    assert decision.event_verified is False
    assert decision.codespace_name == FIXED_CODESPACE


def test_fixed_pilot_run_timeout_beats_plausible_stderr_reason() -> None:
    """D1 repair: a plausible Gate 2 stderr reason under rc 124 still yields
    uncertainty — the timeout short-circuit precedes stderr parsing."""
    transfer = fixed_transfer(run_rc=124, receipt_returned=False)
    stderr = json.dumps(
        {
            "schema_version": "1.0",
            "operation_id": "codespace-implementation-pilot-v1",
            "status": "failed",
            "reason_codes": ["host-configuration-invalid"],
        }
    )
    decision = evaluate_fixed_pilot_gate(
        **fixed_gate_inputs(transfer=transfer, process_stderr=stderr, reference=None, receipt=None)  # type: ignore[arg-type]
    )
    assert decision.passed is False
    assert decision.reason_codes == ("run-timeout-outcome-uncertain",)


@pytest.mark.parametrize(
    "transfer_mutate,reason",
    [
        (lambda t: t.update(attempt=2), "fixed-pilot-transfer-invalid"),
        (lambda t: t.pop("run_id"), "fixed-pilot-transfer-invalid"),
        (lambda t: t.update(probe="INVALID"), "fixed-pilot-transfer-invalid"),
        (lambda t: t.update(main_head_matches=False), "fixed-pilot-transfer-invalid"),
        (lambda t: t.update(remote_head_matches=False), "fixed-pilot-transfer-invalid"),
        (lambda t: t.update(identity_present_equal=False), "fixed-pilot-transfer-invalid"),
        (lambda t: t.update(bindings_present=False), "fixed-pilot-transfer-invalid"),
        (lambda t: t.update(staging_sha256="0" * 64), "fixed-pilot-transfer-invalid"),
        (lambda t: t.update(final_sha256="0" * 64), "fixed-pilot-transfer-invalid"),
        (lambda t: t.update(inode_equal=False), "fixed-pilot-transfer-invalid"),
        (lambda t: t.update(event_bytes=1_048_577), "fixed-pilot-transfer-invalid"),
        (lambda t: t.update(transfer_ok=False), "fixed-pilot-transfer-invalid"),
    ],
)
def test_fixed_pilot_transfer_mutations_fail(transfer_mutate, reason) -> None:
    """N6/N7: transfer-record tampering (run/attempt, probe, hashes, inode) fails."""
    transfer = fixed_transfer()
    transfer_mutate(transfer)
    decision = evaluate_fixed_pilot_gate(**fixed_gate_inputs(transfer=transfer))  # type: ignore[arg-type]
    assert decision.passed is False
    assert decision.reason_codes == (reason,)


def test_fixed_pilot_receipt_path_cross_check() -> None:
    """N5 backstop: a reference path naming another handoff fails the gate.

    The gate cannot recompute Gate 2's B01 request derivation from
    artifacts (an honest limit recorded in v2.2); it does bind handoff,
    SHA, Codespace, and expected SHA across transport, reference, and
    receipt, so a mismatched pilot input cannot pass here.
    """
    reference = fixed_reference(
        receipt_path=(
            "/store/invocations/receipts/fixed-head-probe-"
            + "ff" * 32 + "-" + FIXED_SHA + "-20261104T180002Z.json"
        )
    )
    decision = evaluate_fixed_pilot_gate(**fixed_gate_inputs(reference=reference))  # type: ignore[arg-type]
    assert decision.passed is False
    assert decision.reason_codes == ("fixed-pilot-receipt-path-identity-mismatch",)


def test_fixed_pilot_cli_positive_and_event_mismatch(tmp_path) -> None:
    """P1/N6 via the CLI: full files pass; a mismatched private event fails."""
    def write(name: str, payload: object) -> Path:
        path = tmp_path / name
        if isinstance(payload, bytes):
            path.write_bytes(payload)
        else:
            path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    transport_path = write("transport.json", fixed_transport())
    result_path = write("result.json", fixed_diagnostic())
    reference_path = write("gate2-stdout.json", fixed_reference())
    stderr_path = write("gate2-stderr.json", b"")
    receipt_path = write("gate2-receipt.json", fixed_receipt())
    transfer_path = write("gate2-transfer.json", fixed_transfer())
    event_path = write("gate2-event.json", FIXED_EVENT_BODY)
    gate_path = tmp_path / "gate2-gate.json"
    argv = [
        "--transport", str(transport_path),
        "--result", str(result_path),
        "--fixed-pilot",
        "--reference", str(reference_path),
        "--process-stderr", str(stderr_path),
        "--receipt", str(receipt_path),
        "--transfer", str(transfer_path),
        "--event-private", str(event_path),
        "--output", str(gate_path),
    ]
    assert main(argv) == 0
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    assert gate["decision"] == "PASS"
    assert gate["event_verified"] is True
    event_path.write_bytes(b'{"action": "tampered"}')
    assert main(argv) == 1
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    assert gate["decision"] == "FAIL"
    assert gate["reason_codes"] == ["fixed-pilot-event-evidence-mismatch"]


def test_fixed_pilot_cli_missing_files_fail_without_traceback(tmp_path, capsys) -> None:
    """N7: missing evidence files are FAIL reasons, never tracebacks."""
    transport_path = tmp_path / "transport.json"
    transport_path.write_text(json.dumps(fixed_transport()), encoding="utf-8")
    gate_path = tmp_path / "gate2-gate.json"
    argv = [
        "--transport", str(transport_path),
        "--result", str(tmp_path / "missing-result.json"),
        "--fixed-pilot",
        "--reference", str(tmp_path / "missing-stdout.json"),
        "--process-stderr", str(tmp_path / "missing-stderr.json"),
        "--receipt", str(tmp_path / "missing-receipt.json"),
        "--transfer", str(tmp_path / "missing-transfer.json"),
        "--output", str(gate_path),
    ]
    assert main(argv) == 1
    assert "Traceback" not in capsys.readouterr().out
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    assert gate["decision"] == "FAIL"
    assert gate["reason_codes"] == ["fixed-pilot-diagnostic-missing-or-malformed"]


@pytest.mark.parametrize(
    "missing",
    [
        {"event_bytes": None},
        {"event_sha256": None},
        {"event_bytes": None, "event_sha256": None},
        {"event_missing": True},
    ],
)
def test_fixed_pilot_event_evidence_mandatory(missing: dict) -> None:
    kwargs = fixed_gate_inputs()
    kwargs.update(missing)
    decision = evaluate_fixed_pilot_gate(**kwargs)
    assert decision.passed is False
    assert decision.reason_codes == ("fixed-pilot-event-evidence-missing",)
    assert decision.event_verified is False


def test_fixed_pilot_cli_rejects_omitted_event_even_with_other_positive_evidence(
    tmp_path: Path,
) -> None:
    def write(name: str, value: object) -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path
    args = [
        "--fixed-pilot",
        "--transport", str(write("transport.json", fixed_transport())),
        "--result", str(write("result.json", fixed_diagnostic())),
        "--reference", str(write("reference.json", fixed_reference())),
        "--process-stderr", str(tmp_path / "stderr.txt"),
        "--receipt", str(write("receipt.json", fixed_receipt())),
        "--transfer", str(write("transfer.json", fixed_transfer())),
        "--output", str(tmp_path / "decision.json"),
    ]
    (tmp_path / "stderr.txt").write_text("", encoding="utf-8")
    assert main(args) == 1
    result = json.loads((tmp_path / "decision.json").read_text(encoding="utf-8"))
    assert result["decision"] == "FAIL"
    assert result["reason_codes"] == ["fixed-pilot-event-evidence-missing"]
