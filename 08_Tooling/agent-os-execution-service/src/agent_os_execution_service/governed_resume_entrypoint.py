"""Fixed governed-resume entrypoint contract for Agent OS hosts.

The public contract accepts exactly one immutable ``executor-handoff:<sha256>``
identity. It never accepts command text. Currentness/admission remains owned
by the existing #1218 reconstruction seam and execution remains owned by the
existing Workflow Scheduler boundary supplied by the host composition.

``main``/``__main__`` make the module genuinely runnable as
``python3 -m agent_os_execution_service.governed_resume_entrypoint``.
``build_governed_resume_bindings`` composes the real #1218
``reconstruct_governed_invocation`` seam and the real #758/#1253 Workflow
Scheduler ``run_single_issue_pilot`` boundary into the single-argument shape
this module's bindings require; it performs no reconstruction or dispatch
logic itself.

AOS-GCE1 (#1217) wires the installed default path to the repository-owned #1319
production host bootstrap.  The import is deliberately lazy and occurs only
after the fixed argv contract has been validated, so malformed caller input
cannot trigger host configuration, credential, repository, process, or
Scheduler work.  Explicitly injected bindings remain unchanged for tests and
other governed callers, and ``_no_host_composition_bindings`` remains the
explicit fail-closed stand-in when a caller intentionally wants no host
composition.  If the production factory itself cannot safely compose the host,
the public entrypoint preserves #1238's established ``host-supplied``
fail-closed diagnostic rather than exposing a new caller-visible error contract.
"""

from __future__ import annotations

import functools
import json
import math
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from .invocation_completion_receipt import build_completion_receipt
from .invocation_reconstruction import reconstruct_governed_invocation

from workflow_scheduler.execution.single_issue_pilot import run_single_issue_pilot

HANDOFF_RE = re.compile(r"\Aexecutor-handoff:[0-9a-f]{64}\Z")
SCHEMA = "agent-os-governed-resume-host-evidence/v1"
COMPLETION_ALREADY_COMPLETED_REASON = "invocation-already-completed"
COMPLETION_RECEIPT_UNAVAILABLE_REASON = "completion-receipt-unavailable"
COMPLETION_RECEIPT_CONFLICT_REASON = "completion-receipt-identity-conflict"
COMPLETION_RECEIPT_UNRECORDED_REASON = "completion-receipt-unrecorded"
COMPLETION_CLAIM_UNAVAILABLE_REASON = "completion-claim-unavailable"
INVOCATION_ALREADY_CLAIMED_REASON = "invocation-already-claimed"
DEFAULT_CLAIM_WAIT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class GovernedResumeBindings:
    reconstruct: Callable[[str], object]
    dispatch: Callable[[object], object]
    completion_store: object | None = None
    claim_wait_seconds: float = DEFAULT_CLAIM_WAIT_SECONDS

    def __post_init__(self) -> None:
        if not callable(self.reconstruct) or not callable(self.dispatch):
            raise TypeError("reconstruct and dispatch must be callable")
        if (
            isinstance(self.claim_wait_seconds, bool)
            or not isinstance(self.claim_wait_seconds, (int, float))
            or not math.isfinite(self.claim_wait_seconds)
            or self.claim_wait_seconds < 0
        ):
            raise TypeError("claim_wait_seconds must be a finite number >= 0")
        if self.completion_store is not None:
            required = (
                "find_completed",
                "record_completed",
                "find_claim",
                "claim",
                "release_claim",
                "wait_for_completed",
            )
            missing = [
                name
                for name in required
                if not callable(getattr(self.completion_store, name, None))
            ]
            if missing:
                raise TypeError(
                    "completion_store must expose "
                    + ", ".join(required)
                    + f" (missing: {', '.join(missing)})"
                )


def parse_handoff_argv(argv: Sequence[str]) -> str:
    if type(argv) not in (list, tuple):
        raise TypeError("argv must be a list or tuple")
    if len(argv) != 2 or argv[0] != "--handoff-id":
        raise ValueError("expected exactly --handoff-id <canonical-handoff-id>")
    handoff_id = argv[1]
    if type(handoff_id) is not str or HANDOFF_RE.fullmatch(handoff_id) is None:
        raise ValueError("handoff id must be executor-handoff:<64-lowercase-hex>")
    return handoff_id


def _status_value(result: object) -> str | None:
    status = getattr(result, "status", None)
    value = getattr(status, "value", status)
    return value if type(value) is str else None


def _reason_values(result: object) -> tuple[str, ...]:
    raw = getattr(result, "reason_codes", ())
    values: list[str] = []
    if not isinstance(raw, (tuple, list)):
        return ()
    for item in raw:
        value = getattr(item, "value", item)
        if type(value) is str and len(value) <= 80:
            values.append(value)
    return tuple(sorted(set(values)))


def _bounded_text(value: object) -> str | None:
    return value if type(value) is str and 0 < len(value) <= 512 else None


def _pilot_terminal_status(result: object) -> str:
    status = _status_value(result)
    if status == "completed":
        return "succeeded"
    if (
        status == "failed"
        and getattr(result, "validation_attempted", False) is True
        and getattr(result, "validation_passed", False) is False
    ):
        return "validation-failed"
    if status in {
        "blocked",
        "stale",
        "cancelled",
        "timed-out",
        "failed",
        "quarantined",
        "needs-decision",
    }:
        return status
    return "evidence-incomplete"


def _host_evidence(
    *,
    handoff_id: str,
    status: str,
    reasons: tuple[str, ...],
    scheduler_dispatch_count: int,
    accepted: bool,
    scheduler_invocation_id: str | None = None,
    execution_id: str | None = None,
    terminal_status: str | None = None,
    termination_confirmed: bool = False,
    lease_released: bool = False,
    cleanup_complete: bool = False,
    retained_lease: bool = False,
    quarantined: bool = False,
    evidence_refs: tuple[str, ...] = (),
) -> str:
    payload = {
        "schema": SCHEMA,
        "handoff_id": handoff_id,
        "status": status,
        "reason_codes": list(reasons),
        "scheduler_dispatch_count": scheduler_dispatch_count,
        "accepted": accepted,
        "scheduler_invocation_id": scheduler_invocation_id,
        "execution_id": execution_id,
        "terminal_status": terminal_status,
        "termination_confirmed": termination_confirmed,
        "lease_released": lease_released,
        "cleanup_complete": cleanup_complete,
        "retained_lease": retained_lease,
        "quarantined": quarantined,
        "evidence_refs": list(evidence_refs),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _blocked_evidence(*, handoff_id: str, status: str, reasons: tuple[str, ...]) -> str:
    return _host_evidence(
        handoff_id=handoff_id,
        status=status,
        reasons=reasons,
        scheduler_dispatch_count=0,
        accepted=False,
        terminal_status="blocked-before-execution",
        termination_confirmed=True,
        lease_released=True,
        cleanup_complete=True,
    )


def _pilot_evidence(
    *,
    handoff_id: str,
    result: object,
    extra_reasons: tuple[str, ...] = (),
) -> str:
    status = _status_value(result) or "needs-decision"
    reasons = _reason_values(result) + tuple(extra_reasons)
    lease_acquired = getattr(result, "lease_acquired", False) is True
    lease_released = getattr(result, "lease_released", False) is True
    workspace_created = getattr(result, "workspace_created", False) is True
    filesystem_cleaned = getattr(result, "workspace_filesystem_cleaned", False) is True
    metadata_cleaned = getattr(result, "workspace_metadata_cleaned", False) is True
    result_id = _bounded_text(getattr(result, "result_id", None))
    invocation_id = _bounded_text(getattr(result, "invocation_id", None))
    evidence_refs = () if result_id is None else (result_id,)
    return _host_evidence(
        handoff_id=handoff_id,
        status=status,
        reasons=reasons,
        scheduler_dispatch_count=1,
        accepted=True,
        scheduler_invocation_id=invocation_id,
        execution_id=result_id,
        terminal_status=_pilot_terminal_status(result),
        termination_confirmed=getattr(result, "termination_confirmed", False) is True,
        lease_released=(not lease_acquired) or lease_released,
        cleanup_complete=(not workspace_created) or (filesystem_cleaned and metadata_cleaned),
        retained_lease=lease_acquired and not lease_released,
        quarantined=status == "quarantined",
        evidence_refs=evidence_refs,
    )


def _completion_receipt_matches(receipt: object, pilot_input: object) -> bool:
    """Check a found receipt binds the same admitted pilot input.

    The handoff id already binds the admission, so a mismatch here means a
    conflicting receipt under a reused identity: fail closed, never treat it
    as the completed record for this delivery.
    """
    if type(receipt) is not dict:
        return False
    issue_numbers = getattr(pilot_input, "issue_numbers", None)
    return (
        receipt.get("repository") == getattr(pilot_input, "repository", None)
        and type(issue_numbers) is tuple
        and len(issue_numbers) == 1
        and receipt.get("issue_number") == issue_numbers[0]
        and receipt.get("invocation_id") == getattr(pilot_input, "invocation_id", None)
        and receipt.get("source_sha") == getattr(pilot_input, "source_head_sha", None)
    )


def _blocked_for_receipt(handoff_id: str, receipt: object, pilot_input: object) -> str:
    """Evidence for a delivery that finds a prior completed receipt."""
    if not _completion_receipt_matches(receipt, pilot_input):
        return _blocked_evidence(
            handoff_id=handoff_id,
            status="needs-decision",
            reasons=(COMPLETION_RECEIPT_CONFLICT_REASON,),
        )
    return _blocked_evidence(
        handoff_id=handoff_id,
        status="blocked",
        reasons=(COMPLETION_ALREADY_COMPLETED_REASON,),
    )


def _release_claim_quietly(store: object, handoff_id: str, run_id: object) -> None:
    """Best-effort claim release by the delivery that owns it."""
    if type(run_id) is not str:
        return
    try:
        store_release = getattr(store, "release_claim", None)
        if callable(store_release):
            store_release(handoff_id, run_id)
    except Exception:
        pass


def run_governed_resume(argv: Sequence[str], *, bindings: GovernedResumeBindings) -> str:
    """Reconstruct current state, then dispatch at most once only when admitted.

    When a completion store is bound, a completed receipt for this handoff
    returns without dispatching, and a durable execution claim published
    before dispatch closes the post-completion race: a second delivery that
    finds another delivery's claim waits for the receipt instead of
    dispatching. A completed dispatch records its receipt while still
    holding the claim, then releases it; failed, quarantined, and blocked
    runs release the claim and record nothing, so retries and crash
    recovery are preserved when an explicit non-completed result is returned.
    A receipt-write failure retains the claim and reports the completed
    outcome with a visible warning. A wait timeout never proves an owner
    has terminated, and an exception during dispatch leaves the outcome
    uncertain: in both cases the claim stays in place until independently
    reconciled. This favors fail-closed recovery over duplicate execution.
    Exactly-once is not claimed.
    """
    handoff_id = parse_handoff_argv(argv)
    result = bindings.reconstruct(handoff_id)
    status = _status_value(result)
    reasons = _reason_values(result)
    pilot_input = getattr(result, "pilot_input", None)

    if status != "admitted" or pilot_input is None:
        blocked_status = (
            status
            if status in {"blocked", "stale", "needs-decision"}
            else "needs-decision"
        )
        return _blocked_evidence(
            handoff_id=handoff_id,
            status=blocked_status,
            reasons=reasons,
        )

    run_id: str | None = None
    if bindings.completion_store is not None:
        store = bindings.completion_store
        try:
            prior = store.find_completed(handoff_id)
        except Exception:
            return _blocked_evidence(
                handoff_id=handoff_id,
                status="needs-decision",
                reasons=(COMPLETION_RECEIPT_UNAVAILABLE_REASON,),
            )
        if prior is not None:
            return _blocked_for_receipt(handoff_id, prior, pilot_input)

        run_id = uuid.uuid4().hex
        try:
            claimed = store.claim(handoff_id, run_id)
        except Exception:
            return _blocked_evidence(
                handoff_id=handoff_id,
                status="needs-decision",
                reasons=(COMPLETION_CLAIM_UNAVAILABLE_REASON,),
            )
        if not claimed:
            # Another delivery owns the claim. Wait briefly for its receipt.
            # A timeout is NOT evidence the owner stopped or that its
            # validation-only Pilot did not complete.
            try:
                prior = store.wait_for_completed(
                    handoff_id, timeout_seconds=bindings.claim_wait_seconds
                )
            except Exception:
                return _blocked_evidence(
                    handoff_id=handoff_id,
                    status="needs-decision",
                    reasons=(COMPLETION_RECEIPT_UNAVAILABLE_REASON,),
                )
            if prior is not None:
                return _blocked_for_receipt(handoff_id, prior, pilot_input)
            try:
                prior = store.find_completed(handoff_id)
            except Exception:
                return _blocked_evidence(
                    handoff_id=handoff_id,
                    status="needs-decision",
                    reasons=(COMPLETION_RECEIPT_UNAVAILABLE_REASON,),
                )
            if prior is not None:
                return _blocked_for_receipt(handoff_id, prior, pilot_input)
            # Never unlink another delivery's claim on a wait timeout:
            # the owner may still be dispatching or writing its receipt.
            # Recovery of an orphaned claim requires independent evidence.
            return _blocked_evidence(
                handoff_id=handoff_id,
                status="blocked",
                reasons=(INVOCATION_ALREADY_CLAIMED_REASON,),
            )
        # We own the claim. A receipt may have landed while we acquired
        # or replaced it; re-check before dispatching.
        try:
            prior = store.find_completed(handoff_id)
        except Exception:
            _release_claim_quietly(store, handoff_id, run_id)
            return _blocked_evidence(
                handoff_id=handoff_id,
                status="needs-decision",
                reasons=(COMPLETION_RECEIPT_UNAVAILABLE_REASON,),
            )
        if prior is not None:
            _release_claim_quietly(store, handoff_id, run_id)
            return _blocked_for_receipt(handoff_id, prior, pilot_input)

    try:
        pilot_result = bindings.dispatch(pilot_input)
    except BaseException:
        # Dispatch may have started before the exception. Keep the claim:
        # treating an unknown outcome as retryable can duplicate the Pilot.
        raise
    extra_reasons: tuple[str, ...] = ()
    receipt_recorded = True
    if (
        bindings.completion_store is not None
        and _status_value(pilot_result) == "completed"
    ):
        try:
            receipt = build_completion_receipt(
                handoff_id=handoff_id,
                pilot_input=pilot_input,
                pilot_result=pilot_result,
            )
            bindings.completion_store.record_completed(receipt)
        except Exception as exc:  # noqa: BLE001 - completed work must still report
            receipt_recorded = False
            location = getattr(bindings.completion_store, "receipts_dir", None)
            where = f" (store {location})" if location is not None else ""
            detail = f"{type(exc).__name__}: {exc}"[:200]
            message = (
                "governed-resume: completion receipt unrecorded for "
                f"{handoff_id}{where}: {detail}"
            )[:512]
            print(message, file=sys.stderr)
            extra_reasons = (COMPLETION_RECEIPT_UNRECORDED_REASON,)
    if (
        run_id is not None
        and bindings.completion_store is not None
        and receipt_recorded
    ):
        _release_claim_quietly(bindings.completion_store, handoff_id, run_id)
    return _pilot_evidence(
        handoff_id=handoff_id, result=pilot_result, extra_reasons=extra_reasons
    )


def build_governed_resume_bindings(
    *,
    descriptor_loader: Callable[[str], object],
    resolver: object,
    lease_reader: object,
    evaluated_at: str,
    lease: object,
    workspace: object,
    executor: object | None,
    validator: object,
    cancelled: Callable[[], bool],
    completion_store: object | None = None,
    claim_wait_seconds: float = DEFAULT_CLAIM_WAIT_SECONDS,
) -> GovernedResumeBindings:
    """Wire the real #1218 reconstruction seam and #758 Scheduler boundary.

    Every keyword argument is an existing canonical protocol implementation
    supplied by the caller/host. This function performs no reconstruction or
    dispatch logic of its own -- it only adapts the multi-argument canonical
    call shapes of ``reconstruct_governed_invocation`` and
    ``run_single_issue_pilot`` into the single-argument
    ``Callable[[str], object]``/``Callable[[object], object]`` shape
    ``GovernedResumeBindings`` requires.
    """
    reconstruct = functools.partial(
        reconstruct_governed_invocation,
        descriptor_loader=descriptor_loader,
        resolver=resolver,
        lease_reader=lease_reader,
        evaluated_at=evaluated_at,
    )
    dispatch = functools.partial(
        run_single_issue_pilot,
        lease=lease,
        workspace=workspace,
        executor=executor,
        validator=validator,
        cancelled=cancelled,
    )
    return GovernedResumeBindings(
        reconstruct, dispatch, completion_store, claim_wait_seconds
    )


def _no_host_composition_bindings(handoff_id: str) -> object:
    raise RuntimeError(
        "governed-resume requires host-supplied #1218/#1253 composition; "
        "no production reconstruction/dispatch binding is available"
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    bindings: GovernedResumeBindings | None = None,
) -> int:
    """Parse fixed argv, select production composition, then dispatch at most once."""
    if argv is None:
        argv = sys.argv[1:]
    if bindings is None:
        handoff_id = parse_handoff_argv(argv)
        from .production_governed_resume_factory import (
            ProductionGovernedResumeFactoryError,
            build_production_governed_resume_bindings_for_handoff,
        )

        try:
            bindings = build_production_governed_resume_bindings_for_handoff(handoff_id)
        except ProductionGovernedResumeFactoryError as exc:
            raise RuntimeError(
                "governed-resume requires host-supplied #1218/#1253 composition; "
                "production host composition failed closed"
            ) from exc
    print(run_governed_resume(argv, bindings=bindings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
