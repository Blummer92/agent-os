"""Fail-closed developer-validation gate for governed GitHub-to-GCE evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping

DEV_VALIDATION_REASON = "accepted-dev-validation-envelope"
_ALLOWED_STATUSES = frozenset({"success", "failure", "timeout", "needs-decision"})
_SHA40 = re.compile(r"^[0-9a-f]{40}$", re.ASCII)

# --- Fixed #3333 pilot acceptance gate (D1) ---------------------------------
# A successful workflow step, a process exit code of 0, a receipt reference
# alone, or the provider-less needs-decision diagnostic must never qualify
# as completed execution. Only a genuine 30-field completed receipt, bound
# to the admitted transport, the validated transfer record, and an empty
# Gate 2 stderr channel, can pass this gate.
FIXED_PILOT_REASON = "accepted-codespace-implementation-envelope"
FIXED_PILOT_REPOSITORY = "Blummer92/agent-os"
FIXED_PILOT_ISSUE_NUMBER = 3333
FIXED_PILOT_ACTOR = "Blummer92"
FIXED_PILOT_OPERATION_ID = "codespace-implementation-pilot-v1"
FIXED_PILOT_ARGV = ["git", "rev-parse", "HEAD"]
FIXED_PILOT_CONSUMER = "github-service-agent-governed-publication-path"
FIXED_PILOT_COMPLETED_REASONS = ["fixed-head-probe-passed"]
FIXED_PILOT_MAX_EVENT_BYTES = 1_048_576
_SHA64 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_HANDOFF = re.compile(r"^executor-handoff:[0-9a-f]{64}$", re.ASCII)
_COMPACT_UTC = re.compile(r"^\d{8}T\d{6}Z$", re.ASCII)
_CANONICAL_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", re.ASCII)
_RECEIPT_BASENAME = re.compile(
    r"^fixed-head-probe-[0-9a-f]{64}-[0-9a-f]{40}-\d{8}T\d{6}Z\.json$",
    re.ASCII,
)
_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "operation_id",
        "status",
        "reason_codes",
        "repository",
        "issue_number",
        "logical_trigger_id",
        "handoff_id",
        "expected_sha",
        "request_id",
        "codespace_name",
        "argv",
        "exit_status",
        "stdout_tail",
        "stderr_tail",
        "stdout_truncated",
        "stderr_truncated",
        "started_at",
        "ended_at",
        "duration_ms",
        "execution_authorized",
        "github_writes_authorized",
        "external_writes_authorized",
        "publication_authorized",
        "merge_authorized",
        "scheduler_invoked",
        "side_effects_performed",
        "admission_id",
        "invocation_id",
        "descriptor_id",
    }
)
_REFERENCE_KEYS = frozenset(
    {
        "schema_version",
        "operation_id",
        "repository",
        "issue_number",
        "receipt_path",
        "handoff_id",
        "expected_sha",
        "status",
        "reason_codes",
        "consumer",
    }
)


@dataclass(frozen=True, slots=True)
class DevValidationGateDecision:
    applies: bool
    passed: bool
    status: str
    reason: str
    tested_sha: str | None = None
    validation_id: str | None = None
    exit_code: int | None = None
    cleanup_complete: bool | None = None


def _failure(
    reason: str,
    *,
    status: str = "needs-decision",
    tested_sha: object = None,
    validation_id: object = None,
    exit_code: object = None,
    cleanup_complete: object = None,
) -> DevValidationGateDecision:
    return DevValidationGateDecision(
        applies=True,
        passed=False,
        status=status,
        reason=reason,
        tested_sha=tested_sha if type(tested_sha) is str else None,
        validation_id=validation_id if type(validation_id) is str else None,
        exit_code=exit_code if type(exit_code) is int and type(exit_code) is not bool else None,
        cleanup_complete=cleanup_complete if type(cleanup_complete) is bool else None,
    )


def evaluate_dev_validation_gate(
    transport: Mapping[str, object],
    result: Mapping[str, object] | None,
) -> DevValidationGateDecision:
    """Return whether canonical developer-validation evidence satisfies the gate.

    Non-developer-validation ingress is intentionally not affected. For an
    accepted developer-validation envelope, only structurally valid exact-identity
    evidence with ``status == success``, ``exit_code == 0``, and completed cleanup
    can pass. Everything else fails closed without granting any authority.
    """

    if type(transport) is not dict:
        return _failure("transport-evidence-malformed")
    if transport.get("reason") != DEV_VALIDATION_REASON:
        return DevValidationGateDecision(
            applies=False,
            passed=True,
            status="not-applicable",
            reason="not-dev-validation",
        )
    if transport.get("status") != "accepted":
        return _failure("dev-validation-transport-not-accepted")
    if type(result) is not dict:
        return _failure("dev-validation-result-missing-or-malformed")

    evidence = result.get("dev_validation")
    if type(evidence) is not dict:
        return _failure("dev-validation-result-missing-or-malformed")

    status = evidence.get("status")
    tested_sha = evidence.get("tested_sha")
    validation_id = evidence.get("validation_id")
    exit_code = evidence.get("exit_code")
    cleanup_complete = evidence.get("cleanup_complete")
    reason_codes = evidence.get("reason_codes")

    if status not in _ALLOWED_STATUSES:
        return _failure(
            "dev-validation-status-invalid",
            tested_sha=tested_sha,
            validation_id=validation_id,
            exit_code=exit_code,
            cleanup_complete=cleanup_complete,
        )
    if (
        type(reason_codes) is not list
        or not reason_codes
        or any(type(item) is not str or not item for item in reason_codes)
    ):
        return _failure(
            "dev-validation-reason-codes-invalid",
            status=status,
            tested_sha=tested_sha,
            validation_id=validation_id,
            exit_code=exit_code,
            cleanup_complete=cleanup_complete,
        )

    expected_sha = transport.get("dev_validation_sha_or_none")
    expected_id = transport.get("dev_validation_id_or_none")
    expected_branch = transport.get("dev_validation_branch_or_none")
    if (
        type(expected_sha) is not str
        or _SHA40.fullmatch(expected_sha) is None
        or type(expected_id) is not str
        or not expected_id
        or type(expected_branch) is not str
        or not expected_branch
        or evidence.get("tested_sha") != expected_sha
        or evidence.get("validation_id") != expected_id
        or evidence.get("branch") != expected_branch
    ):
        return _failure(
            "dev-validation-identity-mismatch",
            status=status,
            tested_sha=tested_sha,
            validation_id=validation_id,
            exit_code=exit_code,
            cleanup_complete=cleanup_complete,
        )

    if status != "success":
        return _failure(
            "dev-validation-not-success",
            status=status,
            tested_sha=tested_sha,
            validation_id=validation_id,
            exit_code=exit_code,
            cleanup_complete=cleanup_complete,
        )
    if exit_code != 0:
        return _failure(
            "dev-validation-success-exit-code-invalid",
            status=status,
            tested_sha=tested_sha,
            validation_id=validation_id,
            exit_code=exit_code,
            cleanup_complete=cleanup_complete,
        )
    if cleanup_complete is not True:
        return _failure(
            "dev-validation-success-cleanup-incomplete",
            status=status,
            tested_sha=tested_sha,
            validation_id=validation_id,
            exit_code=exit_code,
            cleanup_complete=cleanup_complete,
        )

    return DevValidationGateDecision(
        applies=True,
        passed=True,
        status="success",
        reason="validation-passed",
        tested_sha=tested_sha,
        validation_id=validation_id,
        exit_code=0,
        cleanup_complete=True,
    )


@dataclass(frozen=True, slots=True)
class FixedPilotGateDecision:
    """Terminal outcome of the fixed #3333 pilot acceptance gate."""

    applies: bool
    passed: bool
    status: str  # "pass" | "fail"
    reason_codes: tuple[str, ...]
    failed_check: str | None = None
    diagnostic_status: str | None = None
    handoff_id: str | None = None
    expected_sha: str | None = None
    codespace_name: str | None = None
    event_verified: bool = False


def _fixed_fail(
    reason: str,
    failed_check: str,
    *,
    diagnostic_status: object = None,
    handoff_id: object = None,
    expected_sha: object = None,
    codespace_name: object = None,
) -> FixedPilotGateDecision:
    return FixedPilotGateDecision(
        applies=True,
        passed=False,
        status="fail",
        reason_codes=(reason,),
        failed_check=failed_check,
        diagnostic_status=diagnostic_status if type(diagnostic_status) is str else None,
        handoff_id=handoff_id if type(handoff_id) is str else None,
        expected_sha=expected_sha if type(expected_sha) is str else None,
        codespace_name=codespace_name if type(codespace_name) is str else None,
        event_verified=False,
    )


def _is_int(value: object) -> bool:
    return type(value) is int


def _is_nonempty_str(value: object) -> bool:
    return type(value) is str and bool(value)


def _parse_canonical_utc(value: object) -> datetime | None:
    if type(value) is not str or _CANONICAL_UTC.fullmatch(value) is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def evaluate_fixed_pilot_gate(
    transport: Mapping[str, object] | None,
    result: Mapping[str, object] | None,
    reference: Mapping[str, object] | None,
    process_stderr: str | None,
    receipt: Mapping[str, object] | None,
    transfer: Mapping[str, object] | None,
    *,
    event_bytes: int | None = None,
    event_sha256: str | None = None,
    event_missing: bool = False,
) -> FixedPilotGateDecision:
    """Return whether genuine fixed-pilot completion evidence satisfies the gate.

    Check order is deliberate: the earliest (most originating) failure wins,
    so a Gate 2 stderr reason is never masked by the missing reference or
    receipt that the same failure also explains. The provider-less
    diagnostic is advisory only: it is required to be present and well
    formed, but its status can never pass the gate alone.
    """

    # 1. Transport: the admitted fixed envelope, exact identities.
    if type(transport) is not dict:
        return _fixed_fail(
            "fixed-pilot-transport-missing-or-malformed", "transport"
        )
    if transport.get("status") != "accepted":
        return _fixed_fail(
            "fixed-pilot-transport-not-accepted", "transport.status"
        )
    if transport.get("reason") != FIXED_PILOT_REASON:
        return _fixed_fail(
            "fixed-pilot-transport-reason-mismatch", "transport.reason"
        )
    handoff = transport.get("codespace_implementation_handoff_id_or_none")
    sha = transport.get("codespace_implementation_sha_or_none")
    if (
        transport.get("repository") != FIXED_PILOT_REPOSITORY
        or type(transport.get("issue_number")) is not int
        or transport.get("issue_number") != FIXED_PILOT_ISSUE_NUMBER
        or type(handoff) is not str
        or _HANDOFF.fullmatch(handoff) is None
        or type(sha) is not str
        or _SHA40.fullmatch(sha) is None
    ):
        return _fixed_fail(
            "fixed-pilot-transport-identity-mismatch", "transport.identity"
        )
    if transport.get("actor") != FIXED_PILOT_ACTOR:
        return _fixed_fail(
            "fixed-pilot-transport-actor-mismatch",
            "transport.actor",
            handoff_id=handoff,
            expected_sha=sha,
        )
    if type(transport.get("run_attempt")) is not int or transport.get("run_attempt") != 1:
        return _fixed_fail(
            "fixed-pilot-transport-attempt-mismatch",
            "transport.run_attempt",
            handoff_id=handoff,
            expected_sha=sha,
        )

    # 2. Diagnostic: present and well formed, never sufficient on its own.
    diagnostic_status: str | None = None
    if type(result) is not dict:
        return _fixed_fail(
            "fixed-pilot-diagnostic-missing-or-malformed",
            "diagnostic",
            handoff_id=handoff,
            expected_sha=sha,
        )
    diagnostic = result.get("codespace_implementation")
    if type(diagnostic) is not dict:
        return _fixed_fail(
            "fixed-pilot-diagnostic-missing-or-malformed",
            "diagnostic.codespace_implementation",
            handoff_id=handoff,
            expected_sha=sha,
        )
    diagnostic_status = diagnostic.get("status")
    reason_codes = diagnostic.get("reason_codes")
    if (
        type(diagnostic_status) is not str
        or not diagnostic_status
        or type(reason_codes) is not list
        or not reason_codes
        or any(type(item) is not str or not item for item in reason_codes)
    ):
        return _fixed_fail(
            "fixed-pilot-diagnostic-malformed",
            "diagnostic.codespace_implementation",
            handoff_id=handoff,
            expected_sha=sha,
        )

    # 3. Transfer: preflight, exclusive transfer, and receipt return.
    if type(transfer) is not dict:
        return _fixed_fail(
            "fixed-pilot-transfer-missing-or-malformed",
            "transfer",
            diagnostic_status=diagnostic_status,
            handoff_id=handoff,
            expected_sha=sha,
        )
    transfer_checks: list[tuple[str, bool]] = [
        ("transfer.run_id", _is_int(transfer.get("run_id")) and transfer["run_id"] > 0),  # type: ignore[index]
        (
            "transfer.attempt",
            _is_int(transfer.get("attempt"))
            and transfer.get("attempt") == transport.get("run_attempt"),
        ),
        ("transfer.selected", _is_nonempty_str(transfer.get("selected"))),
        ("transfer.bindings_present", transfer.get("bindings_present") is True),
        ("transfer.main_head_matches", transfer.get("main_head_matches") is True),
        ("transfer.remote_head_matches", transfer.get("remote_head_matches") is True),
        ("transfer.identity_present_equal", transfer.get("identity_present_equal") is True),
        ("transfer.probe", transfer.get("probe") == "VALID"),
        ("transfer.transfer_ok", transfer.get("transfer_ok") is True),
        (
            "transfer.event_sha256",
            type(transfer.get("event_sha256")) is str
            and _SHA64.fullmatch(transfer["event_sha256"]) is not None,  # type: ignore[index]
        ),
        (
            "transfer.event_bytes",
            _is_int(transfer.get("event_bytes"))
            and 0 < transfer["event_bytes"] <= FIXED_PILOT_MAX_EVENT_BYTES,  # type: ignore[index]
        ),
        ("transfer.staging_sha256", transfer.get("staging_sha256") == transfer.get("event_sha256")),
        ("transfer.final_sha256", transfer.get("final_sha256") == transfer.get("event_sha256")),
        ("transfer.inode_equal", transfer.get("inode_equal") is True),
        ("transfer.run_rc", _is_int(transfer.get("run_rc"))),
        ("transfer.receipt_returned", type(transfer.get("receipt_returned")) is bool),
    ]
    for check, ok in transfer_checks:
        if not ok:
            return _fixed_fail(
                "fixed-pilot-transfer-invalid",
                check,
                diagnostic_status=diagnostic_status,
                handoff_id=handoff,
                expected_sha=sha,
            )
    selected = transfer.get("selected")
    run_rc = transfer.get("run_rc")

    # 4. Gate 2 stderr: the originating failure reason, preserved verbatim.
    # Timeout first: rc 124 means the 300 s `fixed_run` timeout killed the
    # SSH session, and the remote controller may have finished or may still
    # hold its O_EXCL claim. Its stderr cannot settle that, so the gate
    # records outcome-uncertainty instead of a clean failure: FAIL, with
    # the claim and any host receipt preserved and no automatic retry.
    # (D1 repair: the PR as shipped fell through to stderr parsing here
    # and reported `fixed-pilot-process-stderr-unparseable` for a timeout.)
    if run_rc == 124:
        return _fixed_fail(
            "run-timeout-outcome-uncertain",
            "transfer.run_rc",
            diagnostic_status=diagnostic_status,
            handoff_id=handoff,
            expected_sha=sha,
            codespace_name=selected if type(selected) is str else None,
        )
    if run_rc != 0:
        if process_stderr is None:
            return _fixed_fail(
                "fixed-pilot-process-stderr-missing",
                "process_stderr",
                diagnostic_status=diagnostic_status,
                handoff_id=handoff,
                expected_sha=sha,
            )
        try:
            stderr_payload = json.loads(process_stderr)
        except (json.JSONDecodeError, ValueError):
            return _fixed_fail(
                "fixed-pilot-process-stderr-unparseable",
                "process_stderr",
                diagnostic_status=diagnostic_status,
                handoff_id=handoff,
                expected_sha=sha,
            )
        stderr_reasons = (
            stderr_payload.get("reason_codes") if type(stderr_payload) is dict else None
        )
        if (
            type(stderr_reasons) is not list
            or not stderr_reasons
            or any(type(item) is not str or not item for item in stderr_reasons)
        ):
            return _fixed_fail(
                "fixed-pilot-process-stderr-unparseable",
                "process_stderr",
                diagnostic_status=diagnostic_status,
                handoff_id=handoff,
                expected_sha=sha,
            )
        return FixedPilotGateDecision(
            applies=True,
            passed=False,
            status="fail",
            reason_codes=tuple(stderr_reasons),
            failed_check="process_stderr",
            diagnostic_status=diagnostic_status,
            handoff_id=handoff,
            expected_sha=sha,
            codespace_name=selected if type(selected) is str else None,
            event_verified=False,
        )
    if process_stderr is None:
        return _fixed_fail(
            "fixed-pilot-process-stderr-missing",
            "process_stderr",
            diagnostic_status=diagnostic_status,
            handoff_id=handoff,
            expected_sha=sha,
        )
    if process_stderr.strip() != "":
        return _fixed_fail(
            "fixed-pilot-process-stderr-nonempty",
            "process_stderr",
            diagnostic_status=diagnostic_status,
            handoff_id=handoff,
            expected_sha=sha,
        )
    if transfer.get("receipt_returned") is not True:
        return _fixed_fail(
            "fixed-pilot-receipt-not-returned",
            "transfer.receipt_returned",
            diagnostic_status=diagnostic_status,
            handoff_id=handoff,
            expected_sha=sha,
        )

    # 5. Reference: exact 10-key shape and exact identities.
    if type(reference) is not dict:
        return _fixed_fail(
            "fixed-pilot-reference-missing-or-malformed",
            "reference",
            diagnostic_status=diagnostic_status,
            handoff_id=handoff,
            expected_sha=sha,
        )
    if set(reference.keys()) != _REFERENCE_KEYS:
        return _fixed_fail(
            "fixed-pilot-reference-schema-mismatch",
            "reference.keys",
            diagnostic_status=diagnostic_status,
            handoff_id=handoff,
            expected_sha=sha,
        )
    receipt_path = reference.get("receipt_path")
    if (
        reference.get("schema_version") != "1.0"
        or reference.get("operation_id") != FIXED_PILOT_OPERATION_ID
        or reference.get("repository") != FIXED_PILOT_REPOSITORY
        or type(reference.get("issue_number")) is not int
        or reference.get("issue_number") != FIXED_PILOT_ISSUE_NUMBER
        or type(receipt_path) is not str
        or not receipt_path.startswith("/")
        or "/invocations/receipts/" not in receipt_path
        or _RECEIPT_BASENAME.fullmatch(receipt_path.rsplit("/", 1)[-1]) is None
        or reference.get("handoff_id") != handoff
        or reference.get("expected_sha") != sha
        or reference.get("status") != "completed"
        or reference.get("reason_codes") != FIXED_PILOT_COMPLETED_REASONS
        or reference.get("consumer") != FIXED_PILOT_CONSUMER
    ):
        return _fixed_fail(
            "fixed-pilot-reference-identity-mismatch",
            "reference.identity",
            diagnostic_status=diagnostic_status,
            handoff_id=handoff,
            expected_sha=sha,
        )

    # 6. Receipt: exact 30-key shape, exact identities, exact evidence.
    if type(receipt) is not dict:
        return _fixed_fail(
            "fixed-pilot-receipt-missing-or-malformed",
            "receipt",
            diagnostic_status=diagnostic_status,
            handoff_id=handoff,
            expected_sha=sha,
        )
    if set(receipt.keys()) != _RECEIPT_KEYS:
        return _fixed_fail(
            "fixed-pilot-receipt-schema-mismatch",
            "receipt.keys",
            diagnostic_status=diagnostic_status,
            handoff_id=handoff,
            expected_sha=sha,
        )
    if (
        receipt.get("schema_version") != "1.0"
        or receipt.get("operation_id") != FIXED_PILOT_OPERATION_ID
        or receipt.get("repository") != FIXED_PILOT_REPOSITORY
        or type(receipt.get("issue_number")) is not int
        or receipt.get("issue_number") != FIXED_PILOT_ISSUE_NUMBER
        or receipt.get("handoff_id") != handoff
        or type(receipt.get("handoff_id")) is not str
        or _HANDOFF.fullmatch(receipt["handoff_id"]) is None  # type: ignore[index]
        or receipt.get("expected_sha") != sha
        or not _is_nonempty_str(receipt.get("request_id"))
        or receipt.get("codespace_name") != selected
        or not _is_nonempty_str(receipt.get("admission_id"))
        or not _is_nonempty_str(receipt.get("invocation_id"))
        or not _is_nonempty_str(receipt.get("descriptor_id"))
    ):
        return _fixed_fail(
            "fixed-pilot-receipt-identity-mismatch",
            "receipt.identity",
            diagnostic_status=diagnostic_status,
            handoff_id=handoff,
            expected_sha=sha,
        )
    started = _parse_canonical_utc(receipt.get("started_at"))
    ended = _parse_canonical_utc(receipt.get("ended_at"))
    stdout_tail = receipt.get("stdout_tail")
    if (
        receipt.get("status") != "completed"
        or receipt.get("reason_codes") != FIXED_PILOT_COMPLETED_REASONS
        or receipt.get("argv") != FIXED_PILOT_ARGV
        or not _is_int(receipt.get("exit_status"))
        or receipt.get("exit_status") != 0
        or type(stdout_tail) is not str
        or stdout_tail.strip() != sha
        or receipt.get("stderr_tail") != ""
        or receipt.get("stdout_truncated") is not False
        or receipt.get("stderr_truncated") is not False
        or started is None
        or ended is None
        or ended < started
        or not _is_int(receipt.get("duration_ms"))
        or receipt["duration_ms"] < 0  # type: ignore[index]
        or receipt.get("execution_authorized") is not False
        or receipt.get("github_writes_authorized") is not False
        or receipt.get("external_writes_authorized") is not False
        or receipt.get("publication_authorized") is not False
        or receipt.get("merge_authorized") is not False
        or receipt.get("scheduler_invoked") is not False
        or receipt.get("side_effects_performed") is not True
    ):
        return _fixed_fail(
            "fixed-pilot-receipt-evidence-mismatch",
            "receipt.evidence",
            diagnostic_status=diagnostic_status,
            handoff_id=handoff,
            expected_sha=sha,
        )

    # 7. Cross-check: the reference path names this exact handoff and SHA.
    basename = receipt_path.rsplit("/", 1)[-1]  # type: ignore[union-attr]
    parts = basename.removeprefix("fixed-head-probe-").removesuffix(".json").split("-")
    if (
        len(parts) != 3
        or parts[0] != handoff.removeprefix("executor-handoff:")
        or parts[1] != sha
        or _COMPACT_UTC.fullmatch(parts[2]) is None
    ):
        return _fixed_fail(
            "fixed-pilot-receipt-path-identity-mismatch",
            "reference.receipt_path",
            diagnostic_status=diagnostic_status,
            handoff_id=handoff,
            expected_sha=sha,
        )

    # 8. Event: the staged event still matches the transferred record.
    if event_missing:
        return _fixed_fail(
            "fixed-pilot-event-evidence-missing",
            "event_private",
            diagnostic_status=diagnostic_status,
            handoff_id=handoff,
            expected_sha=sha,
        )
    if event_bytes is not None or event_sha256 is not None:
        if (
            event_bytes != transfer.get("event_bytes")
            or event_sha256 != transfer.get("event_sha256")
        ):
            return _fixed_fail(
                "fixed-pilot-event-evidence-mismatch",
                "event_private",
                diagnostic_status=diagnostic_status,
                handoff_id=handoff,
                expected_sha=sha,
            )
        event_verified = True
    else:
        event_verified = False

    return FixedPilotGateDecision(
        applies=True,
        passed=True,
        status="pass",
        reason_codes=("fixed-pilot-gate-passed",),
        failed_check=None,
        diagnostic_status=diagnostic_status,
        handoff_id=handoff,
        expected_sha=sha,
        codespace_name=selected if type(selected) is str else None,
        event_verified=event_verified,
    )


def _fixed_gate_json(decision: FixedPilotGateDecision) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "decision": "PASS" if decision.passed else "FAIL",
        "reason_codes": list(decision.reason_codes),
        "failed_check": decision.failed_check,
        "diagnostic_status": decision.diagnostic_status,
        "handoff_id": decision.handoff_id,
        "expected_sha": decision.expected_sha,
        "codespace_name": decision.codespace_name,
        "event_verified": decision.event_verified,
    }


def _load_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if type(payload) is not dict:
        raise ValueError("evidence must be a JSON object")
    return payload


def _format(decision: DevValidationGateDecision) -> str:
    return (
        "Developer validation gate: "
        f"status={decision.status} "
        f"reason={decision.reason} "
        f"tested_sha={decision.tested_sha or 'unavailable'} "
        f"validation_id={decision.validation_id or 'unavailable'} "
        f"exit_code={decision.exit_code if decision.exit_code is not None else 'unavailable'} "
        f"cleanup_complete={decision.cleanup_complete if decision.cleanup_complete is not None else 'unavailable'}"
    )


def _load_fixed_object(path: Path | None) -> dict[str, object] | None:
    """Load one fixed-pilot evidence file leniently: missing or malformed is None.

    The evaluator assigns the missing-or-malformed reason in check order,
    so a Gate 2 stderr reason is never masked by a missing reference or
    receipt that the same failure also explains. No traceback ever escapes.
    """
    if path is None:
        return None
    try:
        return _load_object(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _load_fixed_text(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _run_fixed_pilot_gate(args: argparse.Namespace) -> int:
    for name in ("reference", "process_stderr", "receipt", "transfer", "output"):
        if getattr(args, name) is None:
            print(
                f"Fixed pilot gate: --{name.replace('_', '-')} is required in --fixed-pilot mode",
                file=sys.stderr,
            )
            return 2
    transport = _load_fixed_object(args.transport)
    result = _load_fixed_object(args.result)
    reference = _load_fixed_object(args.reference)
    process_stderr = _load_fixed_text(args.process_stderr)
    receipt = _load_fixed_object(args.receipt)
    transfer = _load_fixed_object(args.transfer)
    event_bytes: int | None = None
    event_sha256: str | None = None
    event_missing = False
    if args.event_private is not None:
        try:
            raw = args.event_private.read_bytes()
        except OSError:
            event_missing = True
        else:
            event_bytes = len(raw)
            event_sha256 = hashlib.sha256(raw).hexdigest()
    decision = evaluate_fixed_pilot_gate(
        transport,
        result,
        reference,
        process_stderr,
        receipt,
        transfer,
        event_bytes=event_bytes,
        event_sha256=event_sha256,
        event_missing=event_missing,
    )
    try:
        args.output.write_text(
            json.dumps(_fixed_gate_json(decision), sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"Fixed pilot gate: gate output unavailable ({type(exc).__name__})", file=sys.stderr)
        return 1
    print(
        "Fixed pilot gate: "
        f"decision={'PASS' if decision.passed else 'FAIL'} "
        f"reasons={','.join(decision.reason_codes)} "
        f"failed_check={decision.failed_check or 'none'}"
    )
    return 0 if decision.passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--fixed-pilot", action="store_true")
    parser.add_argument("--reference", type=Path, default=None)
    parser.add_argument("--process-stderr", type=Path, default=None)
    parser.add_argument("--receipt", type=Path, default=None)
    parser.add_argument("--transfer", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--event-private", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.fixed_pilot:
        return _run_fixed_pilot_gate(args)

    try:
        transport = _load_object(args.transport)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Developer validation gate: transport evidence unavailable ({type(exc).__name__})", file=sys.stderr)
        return 1

    if transport.get("reason") != DEV_VALIDATION_REASON:
        return 0

    try:
        result = _load_object(args.result)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Developer validation gate: result evidence unavailable ({type(exc).__name__})", file=sys.stderr)
        return 1

    decision = evaluate_dev_validation_gate(transport, result)
    print(_format(decision))
    return 0 if decision.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
