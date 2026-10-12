"""Bounded CLI seam for one #2283 GitHub-controlled Notion read.

The runner produces one deterministic evidence object for the smallest existing
approved public GitHub evidence surface (a bounded Actions artifact plus a job
summary). It creates no new persistence subsystem, writes nothing to Notion or
Drive, and never turns issue comments or repository files into a curriculum
store.

Following the existing preflight convention, the runner never reads the system
clock: ``generated_at`` is caller-supplied so results stay reproducible.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping

from .admission import admit_notion_read_request
from .catalog import load_catalog
from .execution import (
    SchedulerTaskExecutorFactory,
    execute_admitted_notion_read,
    execute_destination_verification,
    execute_source_schema,
)
from .live_executor import build_live_notion_executor_factory
from .models import SCHEMA_VERSION, NotionReadCatalog, NotionReadRequestError
from .projection import (
    reject_credential_keys,
    project_public_result,
    project_source_schema_result,
)

MAX_TRANSPORT_BYTES = 262_144

DISPATCH_BLOCKED = "blocked"
DISPATCH_NOT_ACTIVATED = "not-activated"
DISPATCH_COMPLETED = "completed"
DISPATCH_FAILED = "failed"

# Bounded failure reason codes for the published exception receipt (#3501).
# Closed vocabulary: classification uses only the phase and the exception
# class, never the message, so raw provider text cannot leak into the code.
RECEIPT_REASON_TRANSPORT_BYTE_BOUND = "transport-exceeds-byte-bound"
RECEIPT_REASON_TRANSPORT_UNREADABLE = "transport-unreadable"
RECEIPT_REASON_TRANSPORT_INVALID_JSON = "transport-invalid-json"
RECEIPT_REASON_REQUEST_ERROR = "notion-read-request-error"
RECEIPT_REASON_RECEIPT_WRITE_FAILED = "receipt-write-failed"
RECEIPT_REASON_UNHANDLED = "unhandled-runner-exception"


def run_notion_read_request(
    transport: object,
    *,
    expected_repository: str,
    expected_actor: str,
    generated_at: str,
    catalog: NotionReadCatalog | None = None,
    scheduler_task_executor_factory: SchedulerTaskExecutorFactory | None = None,
    current_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Admit, optionally execute, and project one bounded read as evidence."""
    resolved_catalog = catalog if catalog is not None else load_catalog()
    admission = admit_notion_read_request(
        transport,
        catalog=resolved_catalog,
        expected_repository=expected_repository,
        expected_actor=expected_actor,
    )

    evidence: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "admission": admission.to_dict(),
        "dispatch_status": DISPATCH_BLOCKED,
        "dispatch_reason": admission.reason_codes[0],
        "result": None,
        "notion_writes_performed": False,
        "drive_writes_performed": False,
        "classroom_artifact_writes_performed": False,
        "gce_invoked": False,
        "generated_at": generated_at,
    }

    if not admission.secret_dispatch_authorized:
        reject_credential_keys(evidence, "evidence")
        return evidence

    if scheduler_task_executor_factory is None:
        evidence["dispatch_status"] = DISPATCH_NOT_ACTIVATED
        evidence["dispatch_reason"] = "live-read-executor-not-configured"
        reject_credential_keys(evidence, "evidence")
        return evidence

    if admission.request_class == "source-schema":
        # #2816: governed property-vocabulary read. The plan is exactly one
        # get_data_source step; no filter step exists anywhere in this path.
        execution = execute_source_schema(
            admission,
            catalog=resolved_catalog,
            scheduler_task_executor_factory=scheduler_task_executor_factory,
        )
        evidence["dispatch_status"] = DISPATCH_COMPLETED
        evidence["dispatch_reason"] = "bounded-source-schema-projected"
        evidence["result"] = project_source_schema_result(
            admission,
            execution,
            catalog=resolved_catalog,
            generated_at=generated_at,
        )
    elif admission.request_class == "destination-verification":
        execution = execute_destination_verification(
            admission,
            scheduler_task_executor_factory=scheduler_task_executor_factory,
        )
        evidence["dispatch_status"] = DISPATCH_COMPLETED
        evidence["dispatch_reason"] = "bounded-destination-verification-projected"
        evidence["result"] = {
            "schema_version": SCHEMA_VERSION,
            "result_kind": "agent-os-notion-destination-verification-result",
            "repository": admission.repository,
            "issue_number": admission.issue_number,
            "request_id": admission.request_id,
            **execution,
            "generated_at": generated_at,
        }
    else:
        execution = execute_admitted_notion_read(
            admission,
            catalog=resolved_catalog,
            scheduler_task_executor_factory=scheduler_task_executor_factory,
            current_context=current_context,
        )
        evidence["dispatch_status"] = DISPATCH_COMPLETED
        evidence["dispatch_reason"] = "bounded-read-projected"
        evidence["result"] = project_public_result(
            admission,
            execution,
            catalog=resolved_catalog,
            generated_at=generated_at,
        )
    reject_credential_keys(evidence, "evidence")
    return evidence


def _classify_runner_exception(exc: BaseException, *, phase: str) -> str:
    """Map an exception to a closed-vocabulary receipt reason code."""
    if isinstance(exc, json.JSONDecodeError):
        return RECEIPT_REASON_TRANSPORT_INVALID_JSON
    if isinstance(exc, OSError):
        if phase == "write":
            return RECEIPT_REASON_RECEIPT_WRITE_FAILED
        return RECEIPT_REASON_TRANSPORT_UNREADABLE
    if isinstance(exc, NotionReadRequestError):
        # In the transport phase the only NotionReadRequestError source is the
        # byte-bound guard in _read_transport.
        if phase == "transport":
            return RECEIPT_REASON_TRANSPORT_BYTE_BOUND
        return RECEIPT_REASON_REQUEST_ERROR
    return RECEIPT_REASON_UNHANDLED


def _publish_failure_receipt(
    *,
    output: Path,
    generated_at: str,
    exc: BaseException,
    phase: str,
) -> int:
    """Write a bounded sanitized failure receipt; return the exit code.

    The receipt reuses the evidence contract with a non-success disposition.
    Only developer-authored domain messages are published in the detail
    field; other exceptions contribute their class name only, so provider
    responses, paths, and secrets cannot leak through it.
    """
    reason = _classify_runner_exception(exc, phase=phase)
    detail = str(exc)[:500] if isinstance(exc, NotionReadRequestError) else None
    receipt: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "admission": None,
        "dispatch_status": DISPATCH_FAILED,
        "dispatch_reason": reason,
        "result": None,
        "notion_writes_performed": False,
        "drive_writes_performed": False,
        "classroom_artifact_writes_performed": False,
        "gce_invoked": False,
        "generated_at": generated_at,
        "failure": {
            "reason_code": reason,
            "error_class": type(exc).__name__,
            "detail": detail,
            "phase": phase,
        },
    }
    reject_credential_keys(receipt, "evidence")
    payload = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
    except OSError:
        pass  # best effort; the nonzero exit still signals the failure
    print(payload)
    return 1


def _read_transport(path: Path) -> object:
    if path.stat().st_size > MAX_TRANSPORT_BYTES:
        raise NotionReadRequestError("transport evidence exceeds byte bound")
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--allowed-actor", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--live-notion",
        action="store_true",
        help="bind the existing #936 Notion reader after admission succeeds",
    )
    args = parser.parse_args(argv)

    try:
        transport = _read_transport(args.transport)
    except Exception as exc:
        return _publish_failure_receipt(
            output=args.output,
            generated_at=args.generated_at,
            exc=exc,
            phase="transport",
        )

    try:
        executor_factory = build_live_notion_executor_factory() if args.live_notion else None
        evidence = run_notion_read_request(
            transport,
            expected_repository=args.repository,
            expected_actor=args.allowed_actor,
            generated_at=args.generated_at,
            scheduler_task_executor_factory=executor_factory,
        )
    except Exception as exc:
        return _publish_failure_receipt(
            output=args.output,
            generated_at=args.generated_at,
            exc=exc,
            phase="run",
        )

    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        return _publish_failure_receipt(
            output=args.output,
            generated_at=args.generated_at,
            exc=exc,
            phase="write",
        )
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
