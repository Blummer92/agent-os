"""Trusted-host adapter for the AI Navigation pathway (local candidate, not deployed).

The thinnest composition between an initiating host and ``run_ai_navigation_payload``:
the host supplies a ``TrustedHostComposition`` (clock, authorization transport and
bindings, execution host, routing-identity provider, registry locations, durable
receipt and dispatch-journal locations). The untrusted payload carries only the work
request. Nothing here dispatches by itself: the single dispatch is the existing
``compose_and_run_validation`` reached through the pathway, exactly once per
(request fingerprint, command plan) key, guarded by a durable intent journal.

No authorization policy, no GitHub writes, no CKR6 write / CKR7 refinement, no lesson
promotion, no network, no credentials are introduced. This module is NOT wired to any
production host entrypoint; the deployment connection is OPEN until real host code
constructs a composition and calls ``run_trusted_host_navigation``.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping

from .ai_navigation_pathway import (
    AI_NAVIGATION_SCHEMA_VERSION,
    FailureClass,
    NavigationExecutionHost,
    NavigationRoutingEvidence,
    NavigationStatus,
    _payload_refusal,
    run_ai_navigation_payload,
    trusted_execution_authorization_source,
)
from .command_planning import reconstruct_validation_command_plan, validation_command_plan_id
from .evidence_ledger import EvidenceLedger
from .execution_authorization_source import ExecutionAuthorizationSourceTransport
from .models import ExecutionServiceRequest, reconstruct_execution_service_request

__all__ = [
    "DispatchJournal",
    "JournalState",
    "ReconcileResult",
    "TrustedHostComposition",
    "reconcile_navigation_receipt",
    "run_trusted_host_navigation",
]

_REGISTRY_FILES = ("agent-inheritance-registry.md", "legacy-agent-alias-registry.md")


class JournalState(str, Enum):
    DISPATCHING = "dispatching"  # intent recorded; outcome unknown if we crash here
    COMPLETED_RECEIPT_PERSISTED = "completed-receipt-persisted"
    DISPATCHED_RECEIPT_FAILED = "dispatched-receipt-failed"  # retained evidence, reconcile without replay
    DISPATCHED_NOT_COMPLETED = "dispatched-not-completed"  # dispatch ran, ended failed/host-unavailable
    RECONCILED = "reconciled"


class DispatchJournal:
    """Atomic per-key journal under a host-owned directory. Never deletes records."""

    def __init__(self, directory: Path | str) -> None:
        self._dir = Path(directory)

    @staticmethod
    def key(request: ExecutionServiceRequest, plan_id: str) -> str:
        return hashlib.sha256(f"{request.request_fingerprint}\0{plan_id}".encode()).hexdigest()[:40]

    def _path(self, key: str) -> Path:
        return self._dir / f"nav-dispatch-{key}.json"

    def read(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def write(self, key: str, record: Mapping[str, Any]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        text = json.dumps(dict(record), sort_keys=True)
        fd, tmp = tempfile.mkstemp(dir=str(self._dir), prefix=".nav-journal-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self._path(key))
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        if self._path(key).read_text(encoding="utf-8") != text:
            raise OSError("journal read-back mismatch")

    def _lock_path(self, key: str) -> Path:
        return self._dir / f"nav-reconcile-{key}.lock"

    def acquire_lock(self, key: str) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        os.close(os.open(self._lock_path(key), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))

    def release_lock(self, key: str) -> None:
        try:
            os.unlink(self._lock_path(key))
        except OSError:
            pass

    def create_intent(self, key: str, record: Mapping[str, Any]) -> None:
        """Exclusive create: a second dispatch attempt for the same key cannot pass."""
        self._dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._path(key), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(record), sort_keys=True))
            handle.flush()
            os.fsync(handle.fileno())


@dataclass(frozen=True, slots=True, kw_only=True)
class TrustedHostComposition:
    """Everything the host (not the payload) decides. All fields are required."""

    clock: Callable[[], datetime]
    transport: ExecutionAuthorizationSourceTransport
    candidate_packet_id: str
    invocation_id: str
    operation: str
    host: NavigationExecutionHost | None
    routing_evidence_provider: Callable[[ExecutionServiceRequest, Any], NavigationRoutingEvidence | None]
    registry_dir: Path
    capability_registry_path: Path
    receipt_sink: Callable[[str], None]
    journal: DispatchJournal
    execute_read: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None  # CKR6 read transport (host-owned)


def _refuse(status: NavigationStatus, failure: FailureClass, *reasons: str) -> dict[str, Any]:
    return _payload_refusal(status, failure, tuple(reasons))


def _registry_unavailable(composition: TrustedHostComposition) -> tuple[str, ...]:
    reasons: list[str] = []
    if importlib.util.find_spec("reusable_capability_registry") is None:
        reasons.append("capability-registry-distribution-unavailable")
    if not Path(composition.capability_registry_path).is_file():
        reasons.append("capability-registry-data-unavailable")
    for name in _REGISTRY_FILES:
        if not (Path(composition.registry_dir) / name).is_file():
            reasons.append(f"agent-registry-data-unavailable:{name}")
    return tuple(reasons)


def run_trusted_host_navigation(payload: Mapping[str, Any], composition: TrustedHostComposition) -> dict[str, Any]:
    """Invoke the pathway ONCE for one untrusted payload under trusted composition."""
    if isinstance(payload, Mapping) and "routing_evidence" in payload:
        return _refuse(
            NavigationStatus.REQUEST_REJECTED, FailureClass.POLICY_DENIAL,
            "payload-unknown-keys", "key:routing_evidence",
        )
    missing = _registry_unavailable(composition)
    if missing:
        return _refuse(NavigationStatus.INVALID_CAPABILITY, FailureClass.INFRASTRUCTURE_UNAVAILABLE, *missing)
    try:
        request = reconstruct_execution_service_request(payload["service_request"])
        plan = reconstruct_validation_command_plan(payload["command_plan"])
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        return _refuse(NavigationStatus.REQUEST_REJECTED, FailureClass.MISSING_OR_INVALID_EVIDENCE,
                       "payload-invalid", type(exc).__name__)
    key = DispatchJournal.key(request, validation_command_plan_id(plan))
    try:
        prior = composition.journal.read(key)
    except (OSError, ValueError) as exc:
        return _refuse(NavigationStatus.HOST_UNAVAILABLE, FailureClass.INFRASTRUCTURE_UNAVAILABLE,
                       "dispatch-journal-unreadable", type(exc).__name__)
    if prior is not None:
        return _refuse(
            NavigationStatus.REQUEST_REJECTED, FailureClass.POLICY_DENIAL,
            "dispatch-already-recorded", f"journal-state:{prior.get('state')}", "reconcile-do-not-replay",
        )
    try:
        routing = composition.routing_evidence_provider(request, plan)
    except Exception as exc:
        return _refuse(NavigationStatus.ROUTE_NOT_DISPATCHABLE, FailureClass.INFRASTRUCTURE_UNAVAILABLE,
                       "routing-evidence-provider-unavailable", type(exc).__name__)
    if routing is None:
        return _refuse(NavigationStatus.ROUTE_NOT_DISPATCHABLE, FailureClass.MISSING_OR_INVALID_EVIDENCE,
                       "routing-evidence-not-produced")
    from dataclasses import asdict

    trusted_payload = dict(payload)
    trusted_payload["routing_evidence"] = asdict(routing)
    intent_written: dict[str, bool] = {"v": False}

    class _IntentLost(RuntimeError):
        pass

    def before_dispatch() -> None:
        try:
            composition.journal.create_intent(
                key, {"state": JournalState.DISPATCHING.value, "request_fingerprint": request.request_fingerprint,
                      "command_plan_id": validation_command_plan_id(plan), "schema_version": AI_NAVIGATION_SCHEMA_VERSION},
            )
        except FileExistsError as exc:
            raise _IntentLost("another dispatch intent already exists for this key") from exc
        intent_written["v"] = True

    outcome_box: dict[str, Any] = {}

    def sink(jsonl: str) -> None:
        outcome_box["ledger_jsonl"] = jsonl
        composition.receipt_sink(jsonl)

    # run_ai_navigation_payload returns a dict; we need ledger text for the journal, captured by sink
    # (sink is invoked with the full ledger even when it then raises).
    result = run_ai_navigation_payload(
        trusted_payload,
        host=composition.host,
        authorization_source=trusted_execution_authorization_source(
            transport=composition.transport,
            candidate_packet_id=composition.candidate_packet_id,
            invocation_id=composition.invocation_id,
            operation=composition.operation,
        ),
        receipt_sink=sink,
        clock=composition.clock,
        registry_dir=Path(composition.registry_dir),
        capability_registry_path=Path(composition.capability_registry_path),
        before_dispatch=before_dispatch,
        **({} if composition.execute_read is None else {"execute_read": composition.execute_read}),
    )
    if "_IntentLost" in (result.get("reason_codes") or []) and not intent_written["v"]:
        return _refuse(NavigationStatus.REQUEST_REJECTED, FailureClass.POLICY_DENIAL,
                       "dispatch-already-recorded", "intent-lost-race", "reconcile-do-not-replay")
    if intent_written["v"]:
        if result.get("status") == NavigationStatus.COMPLETED.value and result.get("receipt_persisted"):
            state = JournalState.COMPLETED_RECEIPT_PERSISTED
        elif result.get("status") == NavigationStatus.RECEIPT_PERSISTENCE_FAILED.value:
            state = JournalState.DISPATCHED_RECEIPT_FAILED
        else:
            state = JournalState.DISPATCHED_NOT_COMPLETED
        record = {"state": state.value, "request_fingerprint": request.request_fingerprint,
                  "command_plan_id": validation_command_plan_id(plan), "status": result.get("status"),
                  "reason_codes": result.get("reason_codes"), "receipt_digest": result.get("receipt_digest")}
        if state is JournalState.DISPATCHED_RECEIPT_FAILED:
            retained = outcome_box.get("ledger_jsonl")
            record["retained_ledger_jsonl"] = retained
            if retained:
                record["retained_ledger_sha256"] = hashlib.sha256(retained.encode("utf-8")).hexdigest()
                try:
                    record["retained_ledger_head_digest"] = EvidenceLedger.from_jsonl(retained).entries[-1].entry_digest
                except Exception:
                    record["retained_ledger_head_digest"] = None
        try:
            composition.journal.write(key, record)
        except OSError as exc:
            result = dict(result)
            result["journal_update_failed"] = type(exc).__name__
            result["reconcile_required"] = True
    result = dict(result)
    result["journal_key"] = key
    return result


@dataclass(frozen=True, slots=True, kw_only=True)
class ReconcileResult:
    action: str  # re-persisted | already-persisted | manual-review-required | no-record | blocked
    reason_codes: tuple[str, ...]
    replay_attempted: bool = False  # never true: reconciliation cannot dispatch


def _verify_retained_receipt(key: str, record: Mapping[str, Any]) -> tuple[str, ...]:
    """Reasons the retained receipt may NOT be re-persisted (empty tuple = verified)."""
    fingerprint = record.get("request_fingerprint")
    plan_id = record.get("command_plan_id")
    if not isinstance(fingerprint, str) or not isinstance(plan_id, str):
        return ("journal-binding-fields-missing",)
    if hashlib.sha256(f"{fingerprint}\0{plan_id}".encode()).hexdigest()[:40] != key:
        return ("journal-key-binding-mismatch",)
    jsonl = record.get("retained_ledger_jsonl")
    if not isinstance(jsonl, str) or not jsonl:
        return ("no-retained-receipt",)
    if hashlib.sha256(jsonl.encode("utf-8")).hexdigest() != record.get("retained_ledger_sha256"):
        return ("retained-ledger-sha256-mismatch",)
    try:
        ledger = EvidenceLedger.from_jsonl(jsonl)  # verifies the hash chain
    except Exception:
        return ("retained-ledger-chain-invalid",)
    if not ledger.entries or ledger.entries[-1].entry_digest != record.get("retained_ledger_head_digest"):
        return ("retained-ledger-head-digest-mismatch",)
    if ledger.entries[-1].decision_type.value != "completion":
        return ("retained-ledger-not-a-completion",)
    if not any(f"request:{fingerprint}" in entry.provenance_refs for entry in ledger.entries):
        return ("retained-ledger-request-binding-mismatch",)
    return ()


def reconcile_navigation_receipt(composition: TrustedHostComposition, key: str) -> ReconcileResult:
    """Re-persist a verified retained receipt after a successful dispatch whose sink failed.

    Never dispatches. Verifies key binding, SHA-256, hash chain, head digest and request binding
    first. Serialised per key by an exclusive lock so concurrent reconciles cannot interleave
    (the sink itself is an atomic replace of identical bytes, so a duplicate write is also harmless).
    """
    try:
        record = composition.journal.read(key)
    except (OSError, ValueError) as exc:
        return ReconcileResult(action="blocked", reason_codes=("journal-unreadable", type(exc).__name__))
    if record is None:
        return ReconcileResult(action="no-record", reason_codes=("no-journal-record",))
    state = record.get("state")
    if state in (JournalState.COMPLETED_RECEIPT_PERSISTED.value, JournalState.RECONCILED.value):
        return ReconcileResult(action="already-persisted", reason_codes=(f"journal-state:{state}",))
    if state != JournalState.DISPATCHED_RECEIPT_FAILED.value:
        # DISPATCHING (crash, outcome unknown) or a dispatch that did not complete: a human decides.
        return ReconcileResult(action="manual-review-required", reason_codes=(f"journal-state:{state}", "no-retained-receipt"))
    problems = _verify_retained_receipt(key, record)
    if problems:
        return ReconcileResult(action="blocked", reason_codes=problems)
    try:
        composition.journal.acquire_lock(key)
    except FileExistsError:
        return ReconcileResult(action="blocked", reason_codes=("reconcile-in-progress-or-stale-lock",))
    except OSError as exc:
        return ReconcileResult(action="blocked", reason_codes=("reconcile-lock-unavailable", type(exc).__name__))
    try:
        try:
            current = composition.journal.read(key)  # re-read under the lock
        except (OSError, ValueError) as exc:
            return ReconcileResult(action="blocked", reason_codes=("journal-unreadable", type(exc).__name__))
        if current is None or current.get("state") != JournalState.DISPATCHED_RECEIPT_FAILED.value:
            return ReconcileResult(action="already-persisted", reason_codes=(f"journal-state:{None if current is None else current.get('state')}",))
        try:
            composition.receipt_sink(record["retained_ledger_jsonl"])
        except Exception as exc:
            return ReconcileResult(action="blocked", reason_codes=("receipt-sink-still-unavailable", type(exc).__name__))
        updated = {k: v for k, v in record.items() if k != "retained_ledger_jsonl"}
        updated["state"] = JournalState.RECONCILED.value
        try:
            composition.journal.write(key, updated)
        except OSError as exc:
            return ReconcileResult(action="blocked", reason_codes=("journal-update-failed-receipt-written", type(exc).__name__))
        return ReconcileResult(action="re-persisted", reason_codes=("receipt-re-persisted-without-dispatch",))
    finally:
        composition.journal.release_lock(key)
